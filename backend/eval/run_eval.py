"""Eval harness for the RAG retriever.

Two modes:
  --mode retrieval  (default, fast)  : runs only the retriever, scores
                                       URL-recall@K and method-coverage.
                                       No LLM generation, no API cost beyond
                                       the embedding + rerank calls.
  --mode end_to_end                  : actually invokes the agent and grades
                                       the final answer text against expected
                                       keywords. Costs more, slower.

Run:
    cd backend
    python -m eval.run_eval                              # retrieval mode
    python -m eval.run_eval --mode end_to_end            # full pipeline
    python -m eval.run_eval --questions eval/questions.json --top-k 6

Exit code is non-zero when overall pass-rate is below 0.6, so this can be
wired into CI or a pre-deploy check.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

# Make 'backend' importable when run as `python -m eval.run_eval`
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agents.retrieval import retrieve, RetrievedChunk  # noqa: E402
from shared.logger import logger  # noqa: E402


PASS_RATE_THRESHOLD = 0.60


def _hit_url(chunks: list[RetrievedChunk], url_substrings: list[str]) -> tuple[bool, str | None]:
    """Returns (hit, first_matching_url)."""
    if not url_substrings:
        return False, None
    for c in chunks:
        url = c.page_url or ""
        for needle in url_substrings:
            if needle and needle.lower() in url.lower():
                return True, url
    return False, None


def _hit_keywords(text_value: str, keywords: list[str]) -> int:
    if not keywords:
        return 0
    text_lower = text_value.lower()
    return sum(1 for k in keywords if k.lower() in text_lower)


def run_retrieval_mode(items: list[dict]) -> list[dict]:
    rows = []
    for item in items:
        t0 = time.time()
        try:
            chunks = retrieve(item["query"])
            err = None
        except Exception as e:
            chunks = []
            err = str(e)
        dt_ms = (time.time() - t0) * 1000

        hit, matched_url = _hit_url(chunks, item.get("expected_url_substrings", []))
        should_refuse = bool(item.get("should_refuse", False))
        passed = (
            (should_refuse and len(chunks) == 0)
            or (not should_refuse and (hit or not item.get("expected_url_substrings")))
        )

        # Aggregate retrieval signals
        methods_used: set[str] = set()
        for c in chunks:
            methods_used |= c.matched_methods
        avg_rerank = (
            sum((c.rerank_score or 0) for c in chunks) / max(len(chunks), 1)
            if chunks else 0
        )

        rows.append({
            "id": item["id"],
            "query": item["query"],
            "lang": item.get("language", "?"),
            "passed": passed,
            "hit_url": hit,
            "matched_url": matched_url,
            "n_chunks": len(chunks),
            "methods": "+".join(sorted(methods_used)) if methods_used else "-",
            "avg_rerank": round(avg_rerank, 2),
            "latency_ms": round(dt_ms, 1),
            "should_refuse": should_refuse,
            "error": err,
        })
    return rows


async def run_end_to_end_mode(items: list[dict]) -> list[dict]:
    from agents.agent import get_chat_response  # imported lazily

    rows = []
    for idx, item in enumerate(items):
        thread_id = f"eval-{idx}-{int(time.time())}"
        t0 = time.time()
        try:
            answer = await get_chat_response(item["query"], image=None, thread_id=thread_id)
            err = None
        except Exception as e:
            answer = ""
            err = str(e)
        dt_ms = (time.time() - t0) * 1000

        keyword_hits = _hit_keywords(answer, item.get("expected_answer_keywords", []))
        keyword_total = len(item.get("expected_answer_keywords", []))
        url_hit = any(
            (s or "").lower() in (answer or "").lower()
            for s in item.get("expected_url_substrings", [])
        )
        should_refuse = bool(item.get("should_refuse", False))
        if should_refuse:
            passed = any(
                phrase in (answer or "").lower()
                for phrase in [
                    "couldn't find", "could not find", "not in the indexed",
                    "knowledge base", "খুঁজে পাইনি", "তথ্য নেই", "তথ্য পাইনি",
                ]
            )
        else:
            kw_threshold = max(1, keyword_total // 2)
            passed = (keyword_hits >= kw_threshold) or url_hit

        rows.append({
            "id": item["id"],
            "query": item["query"],
            "lang": item.get("language", "?"),
            "passed": passed,
            "kw_hits": f"{keyword_hits}/{keyword_total}",
            "answer_excerpt": (answer or "")[:140].replace("\n", " "),
            "latency_ms": round(dt_ms, 1),
            "should_refuse": should_refuse,
            "error": err,
        })
    return rows


def _print_table(rows: list[dict], mode: str):
    if mode == "retrieval":
        headers = ["id", "lang", "pass", "url_hit", "n", "methods", "rerank", "ms"]
        widths = [28, 9, 6, 8, 4, 14, 7, 7]
        print(" | ".join(h.ljust(w) for h, w in zip(headers, widths)))
        print("-+-".join("-" * w for w in widths))
        for r in rows:
            cells = [
                r["id"][:28],
                r["lang"][:9],
                "✓" if r["passed"] else "✗",
                "✓" if r["hit_url"] else "-",
                str(r["n_chunks"]),
                r["methods"][:14],
                str(r["avg_rerank"]),
                str(r["latency_ms"]),
            ]
            print(" | ".join(c.ljust(w) for c, w in zip(cells, widths)))
    else:
        headers = ["id", "lang", "pass", "kw", "ms", "answer_excerpt"]
        widths = [28, 9, 6, 8, 7, 80]
        print(" | ".join(h.ljust(w) for h, w in zip(headers, widths)))
        print("-+-".join("-" * w for w in widths))
        for r in rows:
            cells = [
                r["id"][:28],
                r["lang"][:9],
                "✓" if r["passed"] else "✗",
                r["kw_hits"],
                str(r["latency_ms"]),
                r["answer_excerpt"][:80],
            ]
            print(" | ".join(c.ljust(w) for c, w in zip(cells, widths)))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode",
        choices=["retrieval", "end_to_end"],
        default="retrieval",
    )
    parser.add_argument(
        "--questions",
        default=str(Path(__file__).parent / "questions.json"),
    )
    parser.add_argument(
        "--out",
        default=None,
        help="Optional path to write a JSONL report.",
    )
    args = parser.parse_args()

    data = json.loads(Path(args.questions).read_text())
    items = data["items"] if isinstance(data, dict) and "items" in data else data
    print(f"Loaded {len(items)} eval questions from {args.questions}")
    print(f"Mode: {args.mode}\n")

    if args.mode == "retrieval":
        rows = run_retrieval_mode(items)
    else:
        rows = asyncio.run(run_end_to_end_mode(items))

    _print_table(rows, args.mode)

    n = len(rows)
    n_pass = sum(1 for r in rows if r["passed"])
    rate = n_pass / max(n, 1)
    print(f"\nPass rate: {n_pass}/{n} = {rate:.1%}")

    if args.out:
        Path(args.out).write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows))
        print(f"Wrote per-question results to {args.out}")

    sys.exit(0 if rate >= PASS_RATE_THRESHOLD else 1)


if __name__ == "__main__":
    main()
