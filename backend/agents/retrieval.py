"""Production-grade RAG retrieval pipeline.

Pipeline stages (each independently togglable via env var):

    User query
        ↓
    QueryRewriter   — Banglish→Bangla, expand abbreviations, generate variants
        ↓
    HybridRetriever — vector (pgvector cosine) + BM25 (Postgres tsvector) per variant
        ↓
    RRF Fusion      — Reciprocal Rank Fusion across all (variant × method) rankings
        ↓
    LLM Reranker    — single batch JSON call scores candidates 0–10 (optional)
        ↓
    Threshold gate  — drops chunks below MIN_RELEVANCE_SCORE

Design notes:
- Reranking uses the existing chat model (no new heavy deps). One LLM call
  per query; chunk previews capped at ~600 chars to control token cost.
- BM25 uses Postgres tsvector with the 'simple' config — no language-specific
  stemming, so it works on Bangla, English, and Banglish uniformly.
- Vector + BM25 cover complementary failure modes: vectors miss rare proper
  nouns (Act numbers), BM25 misses semantic paraphrase. RRF combines them
  without needing score normalization.
"""

from __future__ import annotations

import os
import json
import re
from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy import text

from shared.embeddings import get_query_embeddings_model, get_chat_model
from shared.sql_client import get_pg_session
from shared.logger import logger
from ingestion.models import Embedding


# ----------------------- Tunables -----------------------

TOP_K_PER_METHOD = int(os.getenv("RAG_TOP_K_PER_METHOD", "25"))
TOP_K_AFTER_FUSION = int(os.getenv("RAG_TOP_K_AFTER_FUSION", "20"))
TOP_K_FINAL = int(os.getenv("RAG_TOP_K_FINAL", "6"))
RRF_K = int(os.getenv("RAG_RRF_K", "60"))
MIN_RELEVANCE_SCORE = float(os.getenv("RAG_MIN_RELEVANCE_SCORE", "4.0"))  # 0–10 scale
ENABLE_QUERY_REWRITE = os.getenv("RAG_ENABLE_QUERY_REWRITE", "true").lower() == "true"
ENABLE_RERANK = os.getenv("RAG_ENABLE_RERANK", "true").lower() == "true"
MAX_QUERY_VARIANTS = 3  # original + 2 rewrites


# ----------------------- Data class ---------------------

@dataclass
class RetrievedChunk:
    embedding_id: int
    content: str
    page_url: Optional[str]
    page_title: Optional[str]
    source_name: str
    source_type: str
    vector_distance: Optional[float] = None
    bm25_rank: Optional[float] = None
    fused_score: float = 0.0
    rerank_score: Optional[float] = None  # 0–10 from LLM reranker
    matched_methods: set[str] = field(default_factory=set)  # {"vector", "bm25"}


# ----------------------- Stage 1: Query rewrite ---------

_BANGLISH_HINTS = re.compile(
    r"\b(ki|kothai|kothay|bolo|ache|achhe|korbe|korte|hoi|hoiye|hobe|"
    r"amake|amar|tumi|apni|tahole|kintu|onujayi|bapare|kemon|kivabe|"
    r"vabe|gele|kore|hoyeche|hoyechilo|chilo|jodi|jokhon|tokhon)\b",
    re.IGNORECASE,
)


def _quick_lang_signal(text_value: str) -> str:
    """Cheap pre-classification before invoking the LLM."""
    if re.search(r"[ঀ-৿]", text_value):
        return "bangla"
    if _BANGLISH_HINTS.search(text_value):
        return "banglish"
    return "english"


def rewrite_query(query: str) -> list[str]:
    """Return up to MAX_QUERY_VARIANTS variants of the query.

    The list ALWAYS includes the original. If rewriting is disabled or the
    LLM call fails, only the original is returned. Other variants are forms
    that improve retrieval recall (e.g. Bangla translation for Banglish
    input, English for Bangla input, expanded acronyms).
    """
    variants: list[str] = [query.strip()]
    if not ENABLE_QUERY_REWRITE:
        return variants

    lang = _quick_lang_signal(query)
    instruction = (
        "You are a query rewriter for a multilingual legal RAG system. "
        "Given a user query, output 2 alternative phrasings that improve retrieval over a "
        "knowledge base of Bangladesh laws (text in Bangla and English). Rules:\n"
        "1. If the input is BANGLISH (Bangla written in Roman letters like 'ki bola ache', "
        "'onujayi', 'bapare'), produce one variant in pure Bangla script and one in English.\n"
        "2. If the input is in Bangla script, produce one variant in English and one Bangla "
        "variant that expands abbreviations and uses formal legal vocabulary.\n"
        "3. If the input is in English, produce one Bangla translation and one English variant "
        "that uses alternative legal phrasing.\n"
        "4. Keep act names, section numbers, dates VERBATIM.\n"
        "5. Output STRICT JSON: {\"variants\": [\"variant 1\", \"variant 2\"]}. No prose."
    )
    prompt = f"{instruction}\n\nDetected input language: {lang}\nUser query: {query}"

    try:
        llm = get_chat_model()
        resp = llm.invoke(prompt)
        raw = resp.content if hasattr(resp, "content") else str(resp)
        if isinstance(raw, list):
            raw = "".join(b.get("text", "") for b in raw if isinstance(b, dict))
        # Extract first {...} JSON block
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            return variants
        parsed = json.loads(match.group(0))
        for v in parsed.get("variants", [])[: MAX_QUERY_VARIANTS - 1]:
            v = (v or "").strip()
            if v and v not in variants:
                variants.append(v)
        logger.info(f"Query rewrite produced {len(variants)} variants ({lang} input)")
    except Exception as e:
        logger.warning(f"Query rewrite failed, falling back to original only: {e}")

    return variants


# ----------------------- Stage 2: Hybrid retrieval ------

def _vector_search(query: str, top_k: int) -> list[tuple[int, float]]:
    """Return [(embedding_id, cosine_distance), ...] sorted ascending by distance."""
    embeddings_model = get_query_embeddings_model()
    qvec = embeddings_model.embed_query(query)
    with get_pg_session() as session:
        distance_col = Embedding.embedding.cosine_distance(qvec).label("distance")
        rows = (
            session.query(Embedding.id, distance_col)
            .order_by(distance_col)
            .limit(top_k)
            .all()
        )
    return [(int(r[0]), float(r[1])) for r in rows]


def _bm25_search(query: str, top_k: int) -> list[tuple[int, float]]:
    """Return [(embedding_id, ts_rank), ...] sorted descending by rank.

    Uses websearch_to_tsquery so the user's query string is interpreted with
    web-style operators; gracefully returns [] if nothing matches.
    """
    sql = text("""
        SELECT id, ts_rank_cd(content_tsv, websearch_to_tsquery('simple', :q)) AS rank
        FROM embeddings
        WHERE content_tsv @@ websearch_to_tsquery('simple', :q)
        ORDER BY rank DESC
        LIMIT :k
    """)
    with get_pg_session() as session:
        try:
            rows = session.execute(sql, {"q": query, "k": top_k}).fetchall()
        except Exception as e:
            logger.warning(f"BM25 search failed: {e}")
            return []
    return [(int(r[0]), float(r[1])) for r in rows]


def _hydrate(embedding_ids: list[int]) -> dict[int, Embedding]:
    if not embedding_ids:
        return {}
    with get_pg_session() as session:
        rows = (
            session.query(Embedding)
            .filter(Embedding.id.in_(embedding_ids))
            .all()
        )
        # Force-load relationships before session closes
        out: dict[int, Embedding] = {}
        for r in rows:
            _ = r.source.source_name if r.source else None
            _ = r.page.page_url if r.page else None
            _ = r.page.page_title if r.page else None
            _ = r.meta_data
            _ = r.content
            out[r.id] = r
        return out


# ----------------------- Stage 3: RRF fusion ------------

def _rrf_fuse(
    vector_rankings: list[list[tuple[int, float]]],
    bm25_rankings: list[list[tuple[int, float]]],
) -> list[tuple[int, float, dict]]:
    """Reciprocal Rank Fusion across all per-variant rankings.

    Returns [(emb_id, fused_score, info), ...] sorted descending. info contains
    the best vector_distance, best bm25_rank, and methods that hit the id.
    """
    fused: dict[int, float] = {}
    info: dict[int, dict] = {}

    for ranking in vector_rankings:
        for rank, (emb_id, distance) in enumerate(ranking):
            fused[emb_id] = fused.get(emb_id, 0.0) + 1.0 / (RRF_K + rank)
            entry = info.setdefault(emb_id, {"methods": set()})
            entry["methods"].add("vector")
            prev = entry.get("vector_distance")
            if prev is None or distance < prev:
                entry["vector_distance"] = distance

    for ranking in bm25_rankings:
        for rank, (emb_id, score) in enumerate(ranking):
            fused[emb_id] = fused.get(emb_id, 0.0) + 1.0 / (RRF_K + rank)
            entry = info.setdefault(emb_id, {"methods": set()})
            entry["methods"].add("bm25")
            prev = entry.get("bm25_rank")
            if prev is None or score > prev:
                entry["bm25_rank"] = score

    ranked = sorted(fused.items(), key=lambda kv: kv[1], reverse=True)
    return [(emb_id, score, info[emb_id]) for emb_id, score in ranked]


# ----------------------- Stage 4: LLM rerank -----------

def _llm_rerank(query: str, candidates: list[RetrievedChunk]) -> list[RetrievedChunk]:
    """Score each candidate's relevance to the query in 0–10. One batch call."""
    if not candidates or not ENABLE_RERANK:
        return candidates

    snippets = []
    for i, c in enumerate(candidates):
        body = (c.content or "").strip().replace("\n", " ")
        if len(body) > 600:
            body = body[:600] + "…"
        title = c.page_title or c.source_name
        snippets.append(f"[{i}] (from: {title})\n{body}")
    snippet_block = "\n\n".join(snippets)

    instruction = (
        "You are a relevance scorer for a RAG system. For EACH numbered chunk below, "
        "score how relevant it is to answering the user's query, on a scale of 0 to 10:\n"
        " 10 = directly answers the query with specific facts\n"
        "  7 = clearly on-topic, partially answers\n"
        "  4 = tangentially related (same domain, different specific topic)\n"
        "  1 = same source/site but different topic\n"
        "  0 = irrelevant noise (navigation, boilerplate, unrelated content)\n\n"
        "Output STRICT JSON: {\"scores\": [{\"id\": 0, \"score\": 7}, ...]}. "
        "Include EVERY chunk index. No prose, no explanation."
    )
    prompt = f"{instruction}\n\nQuery: {query}\n\nChunks:\n{snippet_block}"

    try:
        llm = get_chat_model()
        resp = llm.invoke(prompt)
        raw = resp.content if hasattr(resp, "content") else str(resp)
        if isinstance(raw, list):
            raw = "".join(b.get("text", "") for b in raw if isinstance(b, dict))
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            logger.warning("LLM reranker returned no JSON; skipping rerank")
            return candidates
        parsed = json.loads(match.group(0))
        for entry in parsed.get("scores", []):
            idx = entry.get("id")
            score = entry.get("score")
            if isinstance(idx, int) and 0 <= idx < len(candidates) and isinstance(score, (int, float)):
                candidates[idx].rerank_score = float(score)
        # Anything the LLM forgot to score gets a conservative midpoint
        for c in candidates:
            if c.rerank_score is None:
                c.rerank_score = 3.0
        candidates.sort(key=lambda c: (c.rerank_score or 0), reverse=True)
        return candidates
    except Exception as e:
        logger.warning(f"LLM reranker failed, falling back to RRF order: {e}")
        return candidates


# ----------------------- Public entry point -------------

def retrieve(query: str) -> list[RetrievedChunk]:
    """End-to-end retrieval: rewrite → hybrid → fuse → rerank → threshold.

    Returns chunks sorted by final relevance, all of which passed the
    MIN_RELEVANCE_SCORE gate. May return an empty list — caller is
    responsible for surfacing a "no relevant info" signal upstream.
    """
    variants = rewrite_query(query)

    vector_rankings: list[list[tuple[int, float]]] = []
    bm25_rankings: list[list[tuple[int, float]]] = []
    for v in variants:
        vector_rankings.append(_vector_search(v, TOP_K_PER_METHOD))
        bm25_rankings.append(_bm25_search(v, TOP_K_PER_METHOD))

    fused = _rrf_fuse(vector_rankings, bm25_rankings)
    if not fused:
        logger.warning("Hybrid retrieval returned nothing")
        return []

    fused = fused[:TOP_K_AFTER_FUSION]
    hydrated = _hydrate([eid for eid, _, _ in fused])

    candidates: list[RetrievedChunk] = []
    for emb_id, fused_score, info in fused:
        emb = hydrated.get(emb_id)
        if not emb:
            continue
        page_url = None
        page_title = None
        if emb.page:
            page_url = emb.page.page_url
            page_title = emb.page.page_title
        if not page_url and emb.meta_data:
            page_url = emb.meta_data.get("page_url")
            page_title = page_title or emb.meta_data.get("page_title")
        candidates.append(RetrievedChunk(
            embedding_id=emb.id,
            content=emb.content or "",
            page_url=page_url,
            page_title=page_title,
            source_name=emb.source.source_name if emb.source else "",
            source_type=emb.source.type if emb.source else "",
            vector_distance=info.get("vector_distance"),
            bm25_rank=info.get("bm25_rank"),
            fused_score=fused_score,
            matched_methods=info.get("methods", set()),
        ))

    candidates = _llm_rerank(query, candidates)
    candidates = candidates[:TOP_K_FINAL]

    kept = [c for c in candidates if (c.rerank_score or 0) >= MIN_RELEVANCE_SCORE]
    dropped = len(candidates) - len(kept)
    logger.info(
        f"Retrieval: {len(variants)} variants → {len(fused)} fused → "
        f"{len(candidates)} reranked → {len(kept)} above threshold "
        f"(dropped {dropped} below {MIN_RELEVANCE_SCORE})"
    )
    return kept
