from shared.sql_client import get_pg_session
from persistence.message import Message
from shared.embeddings import get_query_embeddings_model, get_chat_model
from shared.logger import logger
from ingestion.models import Embedding
from langchain_core.messages import HumanMessage
from langchain.messages import RemoveMessage
from langchain_core.tools import tool
from langchain.agents import create_agent, AgentState
from langchain.agents.middleware import before_model
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph.message import REMOVE_ALL_MESSAGES
from langgraph.runtime import Runtime
from typing import Any

@tool
def search_knowledge_base(query: str) -> str:
    """Search the knowledge base for information from crawled websites and parsed documents.
    Use this tool to find relevant information about any topic in the indexed content."""
    
    logger.info(f"Knowledge base search: '{query[:100]}{'...' if len(query) > 100 else ''}'")

    embeddings_model = get_query_embeddings_model()
    query_vector = embeddings_model.embed_query(query)
    
    with get_pg_session() as session:
        try:
            results = (
                session.query(Embedding)
                .order_by(Embedding.embedding.cosine_distance(query_vector))
                .limit(5)
                .all()
            )

            logger.info(f"Retrieved {len(results)} chunks from knowledge base")

            if not results:
                return "No relevant information found in the knowledge base."

            context_parts = []
            for res in results:
                if res.source:
                    source_name = res.source.source_name
                    source_type = res.source.type
                    if source_type == "web_url":
                        context_parts.append(f"[Source URL: {source_name}]\n{res.content}")
                    else:
                        context_parts.append(f"[Document: {source_name}]\n{res.content}")
                else:
                    context_parts.append(res.content)

            return "\n\n---\n\n".join(context_parts)
        except Exception as e:
            logger.exception(f"Error during knowledge base search: {e}")
            raise

SYSTEM_PROMPT = """You are a helpful assistant that answers questions using the knowledge base.

RESPONSE STYLE:
- Be SPECIFIC and GROUNDED - only state facts from the knowledge base
- Keep responses CRISP - avoid long generic descriptions
- Extract EXACT numbers, specs, and prices from the knowledge base

LINKS - VERY IMPORTANT:
- At the END of your response, ALWAYS include relevant links as clickable hyperlinks
- Format: "For more details, visit: [Page Title](https://example.com/page)"
- Use descriptive link text
- NEVER show raw URLs like https://... - always wrap in markdown [text](url)
- Include the source URLs from the knowledge base context
- If the user writes in another language, reply in that language.

FORMATTING:
- Use bullet points for listing features or items
- Bold important terms: **Feature Name**
- Use tables when comparing multiple items

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
