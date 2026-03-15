from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from agents.schema import ChatRequest, ChatResponse
from agents.agent import get_chat_response, get_stream_response
from shared.logger import logger


agent_router = APIRouter()


@agent_router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    logger.info(f"Chat request received, thread_id: {request.thread_id}")
    
    response = await get_chat_response(
        message=request.message,
        image=request.image,
        thread_id=request.thread_id
    )
    
    return ChatResponse(response=response)


@agent_router.post("/stream")
async def stream_chat(request: ChatRequest):
    logger.info(f"Stream request received, thread_id: {request.thread_id}")
    
    async def generate():
        async for chunk in get_stream_response(
            message=request.message,
            image=request.image,
            thread_id=request.thread_id
        ):
            yield chunk
    
    return StreamingResponse(generate(), media_type="text/plain")
