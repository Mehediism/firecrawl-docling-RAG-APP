from shared.config import LLM_PROVIDER, API_KEY, CHAT_MODEL, EMBEDDING_MODEL, EMBEDDING_DIMENSIONS


def _require_key():
    if not API_KEY:
        raise ValueError("API_KEY environment variable is not set")


if LLM_PROVIDER == "openai":
    from langchain_openai import OpenAIEmbeddings, ChatOpenAI

    def get_embeddings_model():
        _require_key()
        kwargs = {"model": EMBEDDING_MODEL, "openai_api_key": API_KEY}
        if "text-embedding-3" in EMBEDDING_MODEL:
            kwargs["dimensions"] = EMBEDDING_DIMENSIONS
        return OpenAIEmbeddings(**kwargs)

    def get_query_embeddings_model():
        _require_key()
        kwargs = {"model": EMBEDDING_MODEL, "openai_api_key": API_KEY}
        if "text-embedding-3" in EMBEDDING_MODEL:
            kwargs["dimensions"] = EMBEDDING_DIMENSIONS
        return OpenAIEmbeddings(**kwargs)

    def get_chat_model():
        _require_key()
        return ChatOpenAI(model=CHAT_MODEL, openai_api_key=API_KEY, temperature=0.7)

    def count_tokens(text: str) -> int:
        import tiktoken
        try:
            enc = tiktoken.encoding_for_model(CHAT_MODEL)
        except KeyError:
            enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))

else:  # google (default)
    from langchain_google_genai import GoogleGenerativeAIEmbeddings, ChatGoogleGenerativeAI
    from google import genai

    _genai_client = None

    def _get_genai_client():
        global _genai_client
        if _genai_client is None:
            _require_key()
            _genai_client = genai.Client(api_key=API_KEY)
        return _genai_client

    def get_embeddings_model():
        _require_key()
        return GoogleGenerativeAIEmbeddings(
            model=EMBEDDING_MODEL,
            task_type="retrieval_document",
            google_api_key=API_KEY,
        )

    def get_query_embeddings_model():
        _require_key()
        return GoogleGenerativeAIEmbeddings(
            model=EMBEDDING_MODEL,
            task_type="retrieval_query",
            google_api_key=API_KEY,
        )

    def get_chat_model():
        _require_key()
        return ChatGoogleGenerativeAI(
            model=CHAT_MODEL, google_api_key=API_KEY, temperature=0.7
        )

    def count_tokens(text: str) -> int:
        client = _get_genai_client()
        response = client.models.count_tokens(model=CHAT_MODEL, contents=text)
        return response.total_tokens
