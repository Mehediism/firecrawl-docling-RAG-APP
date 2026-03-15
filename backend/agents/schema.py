from pydantic import BaseModel
from typing import Optional


class ChatRequest(BaseModel):
    message: str
    thread_id: str
    image: Optional[str] = None


class ChatResponse(BaseModel):
    response: str
