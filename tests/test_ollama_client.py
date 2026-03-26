"""
Tests for Ollama-backed local LLM integration.
"""
import pytest
from unittest.mock import AsyncMock, Mock, patch

from integrations.llm_factory import get_llm_client
from integrations.ollama import OllamaAPIError, OllamaClient


@pytest.mark.asyncio
async def test_ollama_generate_json():
    """Test JSON generation through the Ollama client."""
    mock_response = Mock()
    mock_response.json.return_value = {"response": '{"decisions": [], "ambiguous_items": []}'}
    mock_response.raise_for_status = Mock()

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response

    with patch("httpx.AsyncClient") as mock_async_client:
        mock_async_client.return_value.__aenter__.return_value = mock_client

        client = OllamaClient(model="llama3.2:3b", base_url="http://localhost:11434")
        result = await client.generate_json(
            prompt="Extract decisions",
            system_instruction="Return JSON",
            response_schema={"type": "object"},
        )

    assert result == {"decisions": [], "ambiguous_items": []}
    mock_client.post.assert_awaited_once()


@pytest.mark.asyncio
async def test_ollama_transcribe_audio_not_supported():
    """Test that the Ollama workaround rejects audio transcription."""
    client = OllamaClient()

    with pytest.raises(OllamaAPIError):
        await client.transcribe_audio(b"audio", "audio/wav")


def test_factory_returns_ollama_client(monkeypatch):
    """Test provider selection for Ollama."""
    monkeypatch.setenv("LLM_PROVIDER", "ollama")

    client = get_llm_client()

    assert isinstance(client, OllamaClient)
