"""
Gemini Client wrapper for Google Gemini 2.0 Flash API.
Handles rate limiting, retries, and structured output.
"""
import asyncio
import logging
import time
from typing import Any, Callable, List, Optional
import json

import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold
from pydantic import BaseModel, Field, field_validator


logger = logging.getLogger(__name__)


class TranscriptSegment(BaseModel):
    """Single segment of meeting transcript."""
    speaker: str = Field(..., description="Speaker name or identifier")
    timestamp: str = Field(..., description="Timestamp in HH:MM:SS format")
    text: str = Field(..., description="Transcript text")
    
    @field_validator('timestamp')
    @classmethod
    def validate_timestamp(cls, v: str) -> str:
        """Validate timestamp format HH:MM:SS."""
        parts = v.split(':')
        if len(parts) != 3:
            raise ValueError('Timestamp must be in HH:MM:SS format')
        try:
            hours, minutes, seconds = map(int, parts)
            if not (0 <= hours <= 23 and 0 <= minutes <= 59 and 0 <= seconds <= 59):
                raise ValueError('Invalid time values')
        except ValueError:
            raise ValueError('Timestamp must contain valid integers')
        return v


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
    
    def __init__(self, api_key: str, model: str = "gemini-2.0-flash-exp"):
        """
        Initialize Gemini client with API key.
        
        Args:
            api_key: Google AI API key
            model: Model name (default: gemini-2.0-flash-exp)
        """
        self.api_key = api_key
        self.model_name = model
        self.last_call_time: Optional[float] = None
        
        # Configure the SDK
        genai.configure(api_key=api_key)
        
        logger.info(f"Initialized GeminiClient with model: {model}")
    
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
        
        async def _generate():
            # Rate limiting: wait 4 seconds between consecutive calls
            await self._rate_limit()
            
            # Create model with structured output configuration
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
            
            # Generate content
            response = await asyncio.to_thread(
                model.generate_content,
                prompt
            )
            
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
        
        # Retry with backoff on 429 errors
        try:
            result = await self._retry_with_backoff(_generate)
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
            # Rate limiting: wait 4 seconds between consecutive calls
            await self._rate_limit()
            
            # Create model for transcription
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
            
            # Upload audio file
            prompt = (
                "Transcribe this meeting audio. "
                "Identify different speakers and label them (Speaker A, Speaker B, etc.). "
                "Include timestamps in HH:MM:SS format for each segment."
            )
            
            # Generate content with audio
            response = await asyncio.to_thread(
                model.generate_content,
                [
                    {"mime_type": mime_type, "data": audio_data},
                    prompt
                ]
            )
            
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
            result = await self._retry_with_backoff(_transcribe)
            return result
        except Exception as e:
            logger.error(f"Audio transcription failed: {e}")
            raise
    
    async def _retry_with_backoff(
        self,
        func: Callable,
        max_retries: int = 3,
        backoff_schedule: List[int] = [5, 15, 45]
    ) -> Any:
        """
        Retry function with exponential backoff on 429 errors.
        Waits 4 seconds between all API calls for rate limiting.
        
        Args:
            func: Async function to retry
            max_retries: Maximum number of retries (default: 3)
            backoff_schedule: Backoff delays in seconds (default: [5, 15, 45])
            
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
                        backoff_delay = backoff_schedule[attempt]
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
        """
        Enforce 4-second delay between consecutive API calls.
        """
        if self.last_call_time is not None:
            elapsed = time.time() - self.last_call_time
            if elapsed < 4.0:
                wait_time = 4.0 - elapsed
                logger.debug(f"Rate limiting: waiting {wait_time:.2f}s")
                await asyncio.sleep(wait_time)
        
        self.last_call_time = time.time()
