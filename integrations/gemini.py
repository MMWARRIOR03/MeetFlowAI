"""
Gemini Client wrapper for Google Gemini 2.0 Flash API.
Handles rate limiting, retries, and structured output.
"""
import asyncio
import json
import logging
import os
import re
import time
from typing import Any, Callable, List

import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold

from schemas.base import TranscriptSegment
from integrations.circuit_breaker import get_circuit_breaker, CircuitBreakerConfig


logger = logging.getLogger(__name__)


# Global rate limiter state (shared across all GeminiClient instances)
_global_next_allowed_time: float = 0.0
_global_rate_limit_lock = asyncio.Lock()
_global_request_semaphore = asyncio.Semaphore(1)


class GeminiRateLimitError(Exception):
    """Raised when Gemini API rate limit is exceeded after retries."""
    pass


class GeminiAPIError(Exception):
    """Raised when Gemini API encounters an error."""
    pass


class GeminiClient:
    """
    Wrapper for Google Gemini 2.0 Flash API.
    Handles rate limiting, retries, and structured output.
    """
    
    def __init__(self, api_key: str, model: str = "gemini-2.5-flash"):
        """
        Initialize Gemini client with API key.
        
        Args:
            api_key: Google AI API key
            model: Model name (default: gemini-2.5-flash)
        """
        self.api_key = api_key
        self.model_name = model
        self._circuit_breaker = None
        self.min_interval_seconds = float(os.getenv("GEMINI_MIN_INTERVAL_SECONDS", "20"))
        self.max_retries = int(os.getenv("GEMINI_MAX_RETRIES", "5"))
        self.backoff_schedule = self._parse_backoff_schedule(
            os.getenv("GEMINI_BACKOFF_SCHEDULE_SECONDS", "20,40,80,120,180")
        )
        
        # Configure the SDK
        genai.configure(api_key=api_key)
        
        logger.info(f"Initialized GeminiClient with model: {model}")
    
    async def _get_circuit_breaker(self):
        """Get or create circuit breaker for Gemini API."""
        if not self._circuit_breaker:
            config = CircuitBreakerConfig(
                failure_threshold=5,
                recovery_timeout=60,
                success_threshold=2
            )
            self._circuit_breaker = await get_circuit_breaker("gemini_api", config)
        return self._circuit_breaker
    
    async def generate_json(
        self,
        prompt: str,
        system_instruction: str,
        response_schema: dict,
        temperature: float = 0.1
    ) -> dict:
        """
        Generate structured JSON output from Gemini.
        
        Args:
            prompt: User prompt
            system_instruction: System instruction for the model
            response_schema: JSON schema for structured output
            temperature: Sampling temperature (default 0.1 for deterministic)
            
        Returns:
            Parsed JSON response
            
        Raises:
            GeminiRateLimitError: After 3 retry attempts on 429
            GeminiAPIError: On other API failures
        """
        logger.info(f"Generating JSON with prompt length: {len(prompt)}")
        
        # Get circuit breaker
        circuit_breaker = await self._get_circuit_breaker()
        
        async def _generate():
            async def _request():
                model = genai.GenerativeModel(
                    model_name=self.model_name,
                    generation_config={
                        "temperature": temperature,
                        "response_mime_type": "application/json",
                        "response_schema": response_schema
                    },
                    system_instruction=system_instruction,
                    safety_settings={
                        HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
                        HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
                        HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
                        HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
                    }
                )
                return await asyncio.to_thread(model.generate_content, prompt)

            response = await self._execute_rate_limited(_request)
            
            # Log response
            logger.info(f"Gemini API response received: {len(response.text)} chars")
            
            # Parse JSON response
            try:
                result = json.loads(response.text)
                return result
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse JSON response: {e}")
                logger.error(f"Response text: {response.text}")
                raise GeminiAPIError(f"Invalid JSON response: {e}")
        
        # Wrap with circuit breaker and retry logic
        async def _generate_with_retry():
            return await self._retry_with_backoff(
                _generate,
                max_retries=self.max_retries,
                backoff_schedule=self.backoff_schedule
            )
        
        # Execute with circuit breaker
        try:
            result = await circuit_breaker.call(_generate_with_retry)
            return result
        except Exception as e:
            logger.error(f"Gemini API call failed: {e}")
            raise
    
    async def transcribe_audio(
        self,
        audio_data: bytes,
        mime_type: str
    ) -> List[TranscriptSegment]:
        """
        Transcribe audio file to structured transcript.
        
        Args:
            audio_data: Raw audio bytes
            mime_type: Audio MIME type (audio/wav, audio/mp3, etc.)
            
        Returns:
            List of transcript segments with speaker, timestamp, text
        """
        logger.info(f"Transcribing audio: {len(audio_data)} bytes, type: {mime_type}")
        
        async def _transcribe():
            prompt = (
                "Transcribe this meeting audio. "
                "Identify different speakers and label them (Speaker A, Speaker B, etc.). "
                "Include timestamps in HH:MM:SS format for each segment."
            )

            async def _request():
                model = genai.GenerativeModel(
                    model_name=self.model_name,
                    generation_config={
                        "temperature": 0.1,
                        "response_mime_type": "application/json",
                        "response_schema": {
                            "type": "object",
                            "properties": {
                                "segments": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "speaker": {"type": "string"},
                                            "timestamp": {"type": "string"},
                                            "text": {"type": "string"}
                                        },
                                        "required": ["speaker", "timestamp", "text"]
                                    }
                                }
                            },
                            "required": ["segments"]
                        }
                    },
                    system_instruction=(
                        "You are an expert at transcribing meeting audio. "
                        "Transcribe the audio and identify speakers. "
                        "Format timestamps as HH:MM:SS. "
                        "Return a JSON object with a 'segments' array."
                    )
                )
                return await asyncio.to_thread(
                    model.generate_content,
                    [
                        {"mime_type": mime_type, "data": audio_data},
                        prompt
                    ]
                )

            response = await self._execute_rate_limited(_request)
            
            logger.info(f"Audio transcription response received: {len(response.text)} chars")
            
            # Parse JSON response
            try:
                result = json.loads(response.text)
                segments = [
                    TranscriptSegment(**seg)
                    for seg in result.get("segments", [])
                ]
                return segments
            except (json.JSONDecodeError, ValueError) as e:
                logger.error(f"Failed to parse transcription response: {e}")
                logger.error(f"Response text: {response.text}")
                raise GeminiAPIError(f"Invalid transcription response: {e}")
        
        # Retry with backoff on 429 errors
        try:
            result = await self._retry_with_backoff(
                _transcribe,
                max_retries=self.max_retries,
                backoff_schedule=self.backoff_schedule
            )
            return result
        except Exception as e:
            logger.error(f"Audio transcription failed: {e}")
            raise
    
    async def _retry_with_backoff(
        self,
        func: Callable,
        max_retries: int = 3,
        backoff_schedule: List[int] = [10, 30, 60]
    ) -> Any:
        """
        Retry function with exponential backoff on 429 errors.
        Waits 6 seconds between all API calls for rate limiting.
        
        Args:
            func: Async function to retry
            max_retries: Maximum number of retries (default: 3)
            backoff_schedule: Backoff delays in seconds (default: [10, 30, 60])
            
        Returns:
            Result from successful function call
            
        Raises:
            GeminiRateLimitError: After max retries on 429
            GeminiAPIError: On other API failures
        """
        last_exception = None
        
        for attempt in range(max_retries):
            try:
                result = await func()
                return result
            except Exception as e:
                last_exception = e
                error_str = str(e).lower()
                
                # Check if it's a rate limit error (429)
                if "429" in error_str or "rate limit" in error_str or "quota" in error_str:
                    if attempt < max_retries - 1:
                        schedule_index = min(attempt, len(backoff_schedule) - 1)
                        server_delay = self._extract_retry_delay(str(e))
                        backoff_delay = max(backoff_schedule[schedule_index], server_delay or 0)
                        await self._extend_global_cooldown(backoff_delay)
                        logger.warning(
                            f"Rate limit hit (attempt {attempt + 1}/{max_retries}). "
                            f"Retrying in {backoff_delay}s..."
                        )
                        await asyncio.sleep(backoff_delay)
                        continue
                    else:
                        logger.error(f"Rate limit exceeded after {max_retries} retries")
                        raise GeminiRateLimitError(
                            f"Rate limit exceeded after {max_retries} retries"
                        ) from e
                else:
                    # Non-rate-limit error, don't retry
                    logger.error(f"Gemini API error: {e}")
                    raise GeminiAPIError(f"Gemini API error: {e}") from e
        
        # Should not reach here, but just in case
        raise GeminiAPIError(f"Failed after {max_retries} retries") from last_exception

    async def _rate_limit(self):
        """Wait until the next shared Gemini slot is available."""
        global _global_next_allowed_time

        async with _global_rate_limit_lock:
            now = time.monotonic()
            wait_time = max(0.0, _global_next_allowed_time - now)

        if wait_time > 0:
            logger.debug(f"Rate limiting: waiting {wait_time:.2f}s")
            await asyncio.sleep(wait_time)

    async def _execute_rate_limited(self, func: Callable[[], Any]) -> Any:
        """
        Run a Gemini request with a global single-flight limiter.
        This prevents overlapping in-flight requests across concurrent tasks.
        """
        async with _global_request_semaphore:
            await self._rate_limit()
            try:
                return await func()
            finally:
                await self._extend_global_cooldown(self.min_interval_seconds)

    async def _extend_global_cooldown(self, delay_seconds: float) -> None:
        """Push the shared cooldown window forward."""
        global _global_next_allowed_time

        async with _global_rate_limit_lock:
            _global_next_allowed_time = max(
                _global_next_allowed_time,
                time.monotonic() + max(0.0, delay_seconds)
            )

    def _extract_retry_delay(self, error_message: str) -> int | None:
        """Extract retry-after hints from Gemini error messages when present."""
        patterns = [
            r"retry after\s+(\d+)\s*s",
            r"retry_delay\s*[:=]\s*(\d+)",
            r"please try again in\s+(\d+)\s*s",
        ]

        lowered = error_message.lower()
        for pattern in patterns:
            match = re.search(pattern, lowered)
            if match:
                return int(match.group(1))

        return None

    def _parse_backoff_schedule(self, raw_value: str) -> List[int]:
        """Parse a comma-separated retry schedule from the environment."""
        try:
            schedule = [int(part.strip()) for part in raw_value.split(",") if part.strip()]
        except ValueError as exc:
            raise ValueError("GEMINI_BACKOFF_SCHEDULE_SECONDS must contain integers") from exc

        if not schedule:
            raise ValueError("GEMINI_BACKOFF_SCHEDULE_SECONDS must not be empty")

        return schedule
