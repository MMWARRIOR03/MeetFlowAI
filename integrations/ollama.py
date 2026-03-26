"""
Ollama client for local LLM-backed JSON generation.
"""
import json
import logging
import os
from typing import Any

import httpx


logger = logging.getLogger(__name__)


class OllamaAPIError(Exception):
    """Raised when the Ollama API request fails."""
    pass


class OllamaClient:
    """
    Minimal Ollama wrapper that mirrors the JSON-generation surface used by the agents.
    """

    def __init__(
        self,
        model: str | None = None,
        base_url: str | None = None,
        timeout_seconds: float | None = None,
    ):
        self.model_name = model or os.getenv("OLLAMA_MODEL", "llama3.2:3b")
        self.base_url = (base_url or os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")).rstrip("/")
        self.timeout_seconds = timeout_seconds or float(os.getenv("OLLAMA_TIMEOUT_SECONDS", "180"))

    async def generate_json(
        self,
        prompt: str,
        system_instruction: str,
        response_schema: dict,
        temperature: float = 0.1,
    ) -> dict:
        """
        Generate structured JSON using a local Ollama model.
        """
        payload = {
            "model": self.model_name,
            "system": system_instruction,
            "prompt": self._build_json_prompt(prompt, response_schema),
            "format": "json",
            "stream": False,
            "options": {
                "temperature": temperature,
            },
        }

        logger.info("Generating JSON with Ollama model %s", self.model_name)

        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(f"{self.base_url}/api/generate", json=payload)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise OllamaAPIError(f"Ollama request failed: {exc}") from exc

        data = response.json()
        raw_text = data.get("response", "")
        cleaned = self._clean_json_text(raw_text)

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as exc:
            logger.error("Invalid Ollama JSON response: %s", raw_text)
            raise OllamaAPIError(f"Invalid JSON response from Ollama: {exc}") from exc

    async def transcribe_audio(self, audio_data: bytes, mime_type: str) -> list[Any]:
        """
        Audio transcription is not supported by the local Ollama workaround.
        """
        raise OllamaAPIError(
            "Audio transcription is not supported by the Ollama workaround. "
            "Use text/VTT/JSON input formats or switch back to Gemini for audio."
        )

    def _build_json_prompt(self, prompt: str, response_schema: dict) -> str:
        schema_json = json.dumps(response_schema, indent=2)
        return (
            f"{prompt}\n\n"
            "Return only valid JSON matching this schema.\n"
            "Do not include markdown fences, commentary, or extra text.\n"
            f"Schema:\n{schema_json}\n"
        )

    def _clean_json_text(self, text: str) -> str:
        cleaned = text.strip()
        if cleaned.startswith("```"):
            lines = cleaned.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            cleaned = "\n".join(lines).strip()
        return cleaned
