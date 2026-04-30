import os

# ============================================================
# SINGLE PLACE TO CONFIGURE YOUR LLM PROVIDER
#
# Set these two variables in your .env file:
#   LLM_PROVIDER = "openai"  or  "google"
#   API_KEY      = your API key for the chosen provider
#
# Everything else (models, dimensions) has sensible defaults.
# ============================================================

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "google").lower()

# Unified key — falls back to provider-specific env vars for backward compatibility
API_KEY = (
    os.getenv("API_KEY")
    or os.getenv("OPENAI_API_KEY")
    or os.getenv("GOOGLE_API_KEY")
)

_PROVIDER_DEFAULTS = {
    "openai": {
        "chat_model": "gpt-4o-mini",
        "embedding_model": "text-embedding-3-small",
        "embedding_dimensions": 768,
    },
    "google": {
        "chat_model": "gemini-2.5-flash",
        "embedding_model": "models/text-embedding-004",
        "embedding_dimensions": 768,
    },
}

_defaults = _PROVIDER_DEFAULTS.get(LLM_PROVIDER, _PROVIDER_DEFAULTS["google"])

CHAT_MODEL = os.getenv("CHAT_MODEL", _defaults["chat_model"])
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", _defaults["embedding_model"])
EMBEDDING_DIMENSIONS = int(os.getenv("EMBEDDING_DIMENSIONS", str(_defaults["embedding_dimensions"])))
