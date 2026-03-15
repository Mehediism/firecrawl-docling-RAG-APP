import os
from langchain_google_genai import GoogleGenerativeAIEmbeddings, ChatGoogleGenerativeAI
from google import genai

# Create a single client instance for the new SDK
_genai_client = None

def _get_genai_client():
    global _genai_client
    if _genai_client is None:
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise ValueError("GOOGLE_API_KEY environment variable is not set")
        _genai_client = genai.Client(api_key=api_key)
    return _genai_client

def get_embeddings_model():
    if not os.getenv("GOOGLE_API_KEY"):
        raise ValueError("GOOGLE_API_KEY environment variable is not set")
    return GoogleGenerativeAIEmbeddings(
        model="models/text-embedding-004",
        task_type="retrieval_document"
    )

def get_query_embeddings_model():
    if not os.getenv("GOOGLE_API_KEY"):
        raise ValueError("GOOGLE_API_KEY environment variable is not set")
    return GoogleGenerativeAIEmbeddings(
        model="models/text-embedding-004",
        task_type="retrieval_query"
    )

def get_chat_model():
    if not os.getenv("GOOGLE_API_KEY"):
        raise ValueError("GOOGLE_API_KEY environment variable is not set")
    return ChatGoogleGenerativeAI(
        model="gemini-2.5-flash",
        temperature=0.7
    )

def count_tokens(text: str) -> int:
    """Count tokens using the new google-genai SDK."""
    client = _get_genai_client()
    response = client.models.count_tokens(
        model='gemini-2.5-flash',
        contents=text,
    )
    return response.total_tokens

