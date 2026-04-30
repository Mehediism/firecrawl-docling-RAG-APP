from persistence.message import Message
from shared.embeddings import get_chat_model
from shared.logger import logger
from agents.retrieval import retrieve, RetrievedChunk
from langchain_core.messages import HumanMessage
from langchain.messages import RemoveMessage
from langchain_core.tools import tool
from langchain.agents import create_agent, AgentState
from langchain.agents.middleware import before_model
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph.message import REMOVE_ALL_MESSAGES
from langgraph.runtime import Runtime

NO_RESULTS_SENTINEL = (
    "NO_RELEVANT_RESULTS_IN_KNOWLEDGE_BASE: The knowledge base does not contain "
    "information that closely matches this query. You MUST tell the user that "
    "this specific information is not in the indexed sources, and you MUST NOT "
    "answer the question from your own prior knowledge. Do NOT cite any source. "
    "Suggest the user re-index the relevant page or rephrase the question."
)


def _format_chunks_for_llm(chunks: list[RetrievedChunk]) -> str:
    parts = []
    for c in chunks:
        score = c.rerank_score if c.rerank_score is not None else 0.0
        methods = "+".join(sorted(c.matched_methods)) or "?"
        if c.source_type == "web_url":
            title = c.page_title or c.page_url or c.source_name
            url = c.page_url or c.source_name
            header = (
                f"[WEB PAGE] (relevance: {score:.1f}/10, methods: {methods})\n"
                f"Title: {title}\nURL: {url}"
            )
        else:
            header = (
                f"[DOCUMENT] (relevance: {score:.1f}/10, methods: {methods})\n"
                f"Name: {c.source_name}"
            )
        parts.append(f"{header}\nContent:\n{c.content}")
    return "\n\n---\n\n".join(parts)


@tool
def search_knowledge_base(query: str) -> str:
    """Search the knowledge base for information from crawled websites and parsed documents.

    Uses a multi-stage RAG pipeline: query rewriting (Banglish→Bangla, English↔Bangla),
    hybrid retrieval (BM25 full-text + vector cosine), Reciprocal Rank Fusion across
    query variants, and LLM cross-rerank scored 0-10 with a relevance threshold.
    Returns chunks with explicit relevance scores and source URLs the LLM must cite
    verbatim, or NO_RELEVANT_RESULTS_IN_KNOWLEDGE_BASE if nothing meets the bar."""
    logger.info(f"Knowledge base search: '{query[:120]}{'...' if len(query) > 120 else ''}'")
    try:
        chunks = retrieve(query)
    except Exception as e:
        logger.exception(f"Retrieval pipeline failed: {e}")
        raise

    if not chunks:
        return NO_RESULTS_SENTINEL
    return _format_chunks_for_llm(chunks)

SYSTEM_PROMPT = """You are a helpful assistant that answers questions using the knowledge base.

LANGUAGE - HIGHEST PRIORITY RULE:
- Detect the language of the user's MOST RECENT message and reply in that SAME natural language
- If the user writes in English → reply in English
- If the user writes in Bangla script (বাংলা) → reply entirely in Bangla script
- If the user writes in BANGLISH (Bangla words typed using Roman/English letters, e.g. "ki bola ache", "kemon achen", "amar nam", "bapare") → reply entirely in PURE BANGLA SCRIPT (বাংলা), NOT in English and NOT in Roman letters
- A message is Banglish if it contains Bangla words/grammar even though the letters are Latin — recognise patterns like "ki", "kothai", "bolo", "ache", "korbe", "amake", "tahole", "kintu", "ki vabe", "onujayi", "bapare", "hoiye gele", "korte hoi", etc.
- Mixed message (some English + some Banglish/Bangla) → reply in Bangla script
- The ONLY parts kept in English when replying in Bangla: proper nouns, law/section names that have no common Bangla form, code/URLs, and technical identifiers
- NEVER reply in English to a Banglish question — this is the most common mistake; do not make it
- Match the user's tone (formal/informal) — "tumi" vs "apni" should follow the user's register

GROUNDING - ABSOLUTE RULE (highest priority after language):
- You MUST call the `search_knowledge_base` tool for every substantive user question
- You may ONLY state facts that appear verbatim or near-verbatim in the search results
- DO NOT use your own prior knowledge / training data to answer questions about the indexed domain (laws, products, documents, etc.) — even if you "know" the answer
- DO NOT fill in plausible-sounding details (e.g. "the chairman is usually a senior official") that are not present in the retrieved chunks
- If the tool returns the sentinel "NO_RELEVANT_RESULTS_IN_KNOWLEDGE_BASE", you MUST reply something like: "I couldn't find this specific information in the indexed knowledge base. The page may not have been crawled, or you may want to rephrase the question." (Translate to user's language.) Do NOT then proceed to answer from memory. Do NOT invent sources.
- Each retrieved chunk has a "relevance:" score (0-10). Strongly prefer chunks scored ≥ 7 for direct factual claims. Chunks scored 4-6 are tangential — usable for context only, never as definitive citations. Anything below 4 was already filtered by the retriever; if you somehow see it, ignore it
- If retrieved chunks only partially answer the question, answer ONLY the part covered, and explicitly say what is missing — do not fill the gap with prior knowledge

RESPONSE STYLE:
- Be SPECIFIC and GROUNDED - quote / paraphrase the retrieved chunks
- Keep responses CRISP - avoid long generic descriptions
- Extract EXACT numbers, section numbers, dates, and names from the knowledge base
- Prefer direct quotation of statutory language when answering legal questions

CITATIONS - STRICT RULES:
- Each search result is tagged with [WEB PAGE] (Title + URL) or [DOCUMENT] (Name)
- At the END of your answer, list the sources you actually used under a "**Sources**" heading
- For [WEB PAGE] results, format as: `- [<exact Title from context>](<exact URL from context>)`
- For [DOCUMENT] results, format as: `- <exact Name from context>` (no link)
- COPY the URL VERBATIM from the search result — DO NOT shorten, guess, modify, or invent any part of the URL
- DO NOT cite a page unless its URL appeared in the search results
- DO NOT use the homepage / root URL when a more specific page URL is available in the results
- If the same page appears in multiple results, cite it once
- NEVER show raw URLs in prose — they only appear inside markdown links in the Sources list

FORMATTING (GitHub-Flavored Markdown):
- Use bullet points for short lists of items
- Bold important terms: **Feature Name**
- Use fenced code blocks for code, commands, or config snippets
- USE A MARKDOWN TABLE whenever the answer involves any of:
  - comparing 2+ items across the same attributes (e.g. plans, models, sections, schedules)
  - structured records with consistent fields (e.g. name + role + date)
  - numeric data with categories (e.g. fees, deadlines, quantities)
  - any content the user explicitly asks for in a table
- Table format example:
  | Column A | Column B | Column C |
  | --- | --- | --- |
  | value | value | value |
- Keep table cells short — push long prose outside the table as a follow-up paragraph
- Do NOT force a table when a single fact or short paragraph would be clearer
"""

checkpointer = InMemorySaver()

@before_model
def trim_around_tool_call(state: AgentState, runtime: Runtime):
    last_n_context_size = 30
    messages = state["messages"]
    trimmed_messages = []
    for message in messages[::-1]:
        trimmed_messages.append(message)
        if (len(trimmed_messages) > last_n_context_size) and isinstance(message, HumanMessage):
            break
    trimmed_messages = trimmed_messages[::-1]
    logger.debug(f'middleware, before_model, trim_around_tool_call, context_length: {len(trimmed_messages)}')
    return {"messages": [RemoveMessage(id=REMOVE_ALL_MESSAGES), *trimmed_messages]}

agent = create_agent(
    get_chat_model(),
    tools=[search_knowledge_base],
    system_prompt=SYSTEM_PROMPT,
    middleware=[trim_around_tool_call],
    checkpointer=checkpointer,
)

async def get_chat_response(message: str, image: str | None, thread_id: str):
    try:
        # Validate and normalize input
        image_data = image.split("base64,")[1] if image and "base64," in image else image
        msg_obj = Message(text=message, image_b64=image_data)
        
        user_message = msg_obj.text
        
        if msg_obj.converted_image_b64:
            logger.info("Processing image...")
            image_llm = get_chat_model()
            
            image_analysis_msg = HumanMessage(
                content=[
                    {"type": "text", "text": "Analyze this image. Extract any text and describe the visual content in detail."},
                    {"type": "image_url", "image_url": {"url": f"data:{msg_obj.converted_image_mime_type};base64,{msg_obj.converted_image_b64}"}}
                ]
            )
            
            image_response = await image_llm.ainvoke([image_analysis_msg])
            image_context = image_response.content
            logger.info("Image analysis complete")
            
            user_message = f"[Image Context: {image_context}]\n\nUser Query: {user_message}" if user_message else f"[Image Context: {image_context}]"

        result = await agent.ainvoke(
            {"messages": [{"role": "user", "content": user_message}]},
            config={"configurable": {"thread_id": thread_id}}
        )
        content = result["messages"][-1].content
        if isinstance(content, list):
            content = "".join([block.get("text", "") for block in content if isinstance(block, dict) and "text" in block])
        return content
        
    except Exception as e:
        logger.exception(f"Error in get_chat_response: {e}")
        raise

async def get_stream_response(message: str, image: str | None, thread_id: str):
    try:
        # Validate and normalize input
        image_data = image.split("base64,")[1] if image and "base64," in image else image
        msg_obj = Message(text=message, image_b64=image_data)
        
        user_message = msg_obj.text
        
        if msg_obj.converted_image_b64:
            logger.info("Processing image for streaming...")
            image_llm = get_chat_model()
            
            image_analysis_msg = HumanMessage(
                content=[
                    {"type": "text", "text": "Analyze this image. Extract any text and describe the visual content."},
                    {"type": "image_url", "image_url": {"url": f"data:{msg_obj.converted_image_mime_type};base64,{msg_obj.converted_image_b64}"}}
                ]
            )
            
            image_response = await image_llm.ainvoke([image_analysis_msg])
            image_context = image_response.content
            # Handle list content for image response too just in case
            if isinstance(image_context, list):
                image_context = "".join([block.get("text", "") for block in image_context if isinstance(block, dict) and "text" in block])
            
            user_message = f"[Image Context: {image_context}]\n\nUser Query: {user_message}" if user_message else f"[Image Context: {image_context}]"

        async for chunk in agent.astream(
            {"messages": [{"role": "user", "content": user_message}]},
            config={"configurable": {"thread_id": thread_id}},
            stream_mode="values"
        ):
            latest_message = chunk["messages"][-1]
            if hasattr(latest_message, "content") and latest_message.content:
                content = latest_message.content
                if isinstance(content, list):
                    content = "".join([block.get("text", "") for block in content if isinstance(block, dict) and "text" in block])
                yield content
            elif hasattr(latest_message, "tool_calls") and latest_message.tool_calls:
                yield f"\n[Searching knowledge base...]\n"
                
    except Exception as e:
        logger.exception(f"Error in get_stream_response: {e}")
        raise
