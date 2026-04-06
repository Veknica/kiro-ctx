"""
embeddings.py — Embedding generation for agora-kiro memory system.

Provider priority (auto-detected):
  1. OpenAI  text-embedding-3-small  (1536 dims) — set OPENAI_API_KEY
  2. Gemini  gemini-embedding-001    (768 dims)  — set GEMINI_API_KEY
  3. Local   sentence-transformers   (768 dims)  — set EMBEDDING_PROVIDER=local
                                                   or install sentence-transformers
  4. None    → FTS5/BM25 keyword search only

Provider selection via EMBEDDING_PROVIDER env var:
  EMBEDDING_PROVIDER=auto    Auto-detect (default): OpenAI → Gemini → local
  EMBEDDING_PROVIDER=local   Force local sentence-transformers (fully offline)
  EMBEDDING_PROVIDER=openai  Force OpenAI
  EMBEDDING_PROVIDER=gemini  Force Gemini

Usage:
    from agora_kiro.embeddings import get_embedding, is_available

    vec = get_embedding("POST /users rejects + in emails")  # list[float] | None
"""
from __future__ import annotations

import os
from functools import lru_cache
from typing import Optional

# --------------------------------------------------------------------------- #
#  Config                                                                      #
# --------------------------------------------------------------------------- #

_OPENAI_KEY  = os.environ.get("OPENAI_API_KEY")
_GEMINI_KEY  = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
_PROVIDER_PREF = os.environ.get("EMBEDDING_PROVIDER", "auto").lower()

OPENAI_MODEL  = "text-embedding-3-small"
OPENAI_DIM    = 1536

GEMINI_MODEL  = "gemini-embedding-001"
GEMINI_DIM    = 768          # MRL-reduced from 3072

LOCAL_MODEL   = os.environ.get("LOCAL_EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")
LOCAL_DIM     = 384          # bge-small; bge-large-en-v1.5 = 1024

# Dimension used for this installation (determined once at first embed call)
_active_provider: Optional[str] = None   # "openai" | "gemini" | "local" | None
_active_dim: int = OPENAI_DIM            # updated on first real embed

# Lazy clients
_openai_client = None
_gemini_client = None
_local_model   = None


# --------------------------------------------------------------------------- #
#  Provider detection                                                          #
# --------------------------------------------------------------------------- #

def _local_available() -> bool:
    try:
        from sentence_transformers import SentenceTransformer  # noqa: F401
        return True
    except ImportError:
        return False


def _select_provider() -> str | None:
    """Pick best available provider. Cached after first call."""
    global _active_provider, _active_dim

    if _active_provider is not None:
        return _active_provider

    pref = _PROVIDER_PREF

    # Explicit local-only mode
    if pref == "local":
        if _local_available():
            _active_provider = "local"
            _active_dim = _get_local_dim()
            return _active_provider
        _active_provider = ""
        return None

    # Explicit OpenAI
    if pref == "openai":
        if _OPENAI_KEY:
            try:
                from openai import OpenAI  # noqa: F401
                _active_provider = "openai"
                _active_dim = OPENAI_DIM
                return _active_provider
            except ImportError:
                pass
        _active_provider = ""
        return None

    # Explicit Gemini
    if pref == "gemini":
        if _GEMINI_KEY:
            try:
                from google import genai  # noqa: F401
                _active_provider = "gemini"
                _active_dim = GEMINI_DIM
                return _active_provider
            except ImportError:
                pass
        _active_provider = ""
        return None

    # Auto: OpenAI → Gemini → local → none
    if _OPENAI_KEY:
        try:
            from openai import OpenAI  # noqa: F401
            _active_provider = "openai"
            _active_dim = OPENAI_DIM
            return _active_provider
        except ImportError:
            pass

    if _GEMINI_KEY:
        try:
            from google import genai  # noqa: F401
            _active_provider = "gemini"
            _active_dim = GEMINI_DIM
            return _active_provider
        except ImportError:
            pass

    if _local_available():
        _active_provider = "local"
        _active_dim = _get_local_dim()
        return _active_provider

    # No provider — keyword search only
    _active_provider = ""          # empty string = "checked, none available"
    return None


def is_available() -> bool:
    """Return True if any embedding provider is configured."""
    return bool(_select_provider())


def vector_dim() -> int:
    """Return the embedding dimension for the active provider."""
    _select_provider()
    return _active_dim


def _get_local_dim() -> int:
    """Return the actual output dim of the configured local model."""
    # bge-small variants = 384, bge-large = 1024, all-MiniLM = 384
    model = LOCAL_MODEL.lower()
    if "large" in model:
        return 1024
    return 384


# --------------------------------------------------------------------------- #
#  OpenAI                                                                      #
# --------------------------------------------------------------------------- #

def _openai_embed(text: str) -> list[float]:
    global _openai_client
    if _openai_client is None:
        from openai import OpenAI
        _openai_client = OpenAI(api_key=_OPENAI_KEY)

    resp = _openai_client.embeddings.create(
        model=OPENAI_MODEL,
        input=text[:8000],
    )
    return resp.data[0].embedding


# --------------------------------------------------------------------------- #
#  Gemini                                                                      #
# --------------------------------------------------------------------------- #

def _gemini_embed(text: str) -> list[float]:
    global _gemini_client
    if _gemini_client is None:
        from google import genai
        _gemini_client = genai.Client(api_key=_GEMINI_KEY)

    result = _gemini_client.models.embed_content(
        model=GEMINI_MODEL,
        contents=text[:8000],
        config={"output_dimensionality": GEMINI_DIM},
    )
    return list(result.embeddings[0].values)


# --------------------------------------------------------------------------- #
#  Local (sentence-transformers)                                               #
# --------------------------------------------------------------------------- #

def _local_embed(text: str) -> list[float]:
    global _local_model
    if _local_model is None:
        from sentence_transformers import SentenceTransformer
        device = os.environ.get("EMBEDDING_DEVICE", "cpu")
        _local_model = SentenceTransformer(LOCAL_MODEL, device=device)
    vec = _local_model.encode(text[:8000], normalize_embeddings=True, show_progress_bar=False)
    return vec.tolist()


# --------------------------------------------------------------------------- #
#  Public API                                                                  #
# --------------------------------------------------------------------------- #

def get_embedding(text: str) -> Optional[list[float]]:
    """
    Generate an embedding for text.

    Returns:
        list[float] on success, None if no provider available or on error.
        Callers should treat None as "fall back to keyword search".
    """
    if not text or not text.strip():
        return None

    provider = _select_provider()
    if not provider:
        return None

    try:
        if provider == "openai":
            return _openai_embed(text)
        elif provider == "gemini":
            return _gemini_embed(text)
        elif provider == "local":
            return _local_embed(text)
    except Exception:
        return None

    return None


@lru_cache(maxsize=256)
def _cached_embedding(text: str) -> Optional[tuple]:
    """Cache embeddings for repeated search queries."""
    vec = get_embedding(text)
    return tuple(vec) if vec else None


def get_query_embedding(query: str) -> Optional[list[float]]:
    """get_embedding with LRU cache — use for search queries, not for storage."""
    result = _cached_embedding(query)
    return list(result) if result else None


def clear_cache() -> None:
    """Clear the query embedding cache."""
    _cached_embedding.cache_clear()


def provider_info() -> dict:
    """Return info about the active embedding configuration."""
    provider = _select_provider()
    if provider == "openai":
        model = OPENAI_MODEL
    elif provider == "gemini":
        model = GEMINI_MODEL
    elif provider == "local":
        model = LOCAL_MODEL
    else:
        model = None
    return {
        "provider": provider or "none (keyword search only)",
        "model": model,
        "dim": _active_dim if provider else None,
        "openai_key_set": bool(_OPENAI_KEY),
        "gemini_key_set": bool(_GEMINI_KEY),
        "local_available": _local_available(),
        "embedding_provider_pref": _PROVIDER_PREF,
    }
