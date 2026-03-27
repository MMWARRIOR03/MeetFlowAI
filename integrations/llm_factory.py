"""
Factory for choosing the active LLM client.
"""
import os

from integrations.gemini import GeminiClient
from integrations.ollama import OllamaClient


def get_llm_client(api_key: str | None = None):
    """
    Return the configured LLM client.
    """
    provider = os.getenv("LLM_PROVIDER", "gemini").strip().lower()

    if provider == "ollama":
        return OllamaClient()

    if provider == "gemini":
        if not api_key:
            raise ValueError("GEMINI_API_KEY is required when LLM_PROVIDER=gemini")
        return GeminiClient(api_key=api_key)

    raise ValueError(f"Unsupported LLM_PROVIDER: {provider}")


def get_llm_api_call_label(operation: str = "generate_json") -> str:
    """Return an audit label for the active LLM provider."""
    provider = os.getenv("LLM_PROVIDER", "gemini").strip().lower()
    return f"{provider}.{operation}"
