"""
Tests for GeminiClient.
"""
import pytest
import asyncio
from unittest.mock import Mock, patch, AsyncMock
import integrations.gemini as gemini_module
from integrations.gemini import GeminiClient, GeminiRateLimitError, GeminiAPIError, TranscriptSegment


@pytest.fixture
def gemini_client():
    """Create a GeminiClient instance for testing."""
    return GeminiClient(api_key="test_api_key")


@pytest.mark.asyncio
async def test_gemini_client_initialization():
    """Test GeminiClient initialization."""
    client = GeminiClient(api_key="test_key", model="gemini-2.0-flash-exp")
    assert client.api_key == "test_key"
    assert client.model_name == "gemini-2.0-flash-exp"
    assert client.min_interval_seconds == 20.0
    assert client.max_retries == 5


@pytest.mark.asyncio
async def test_rate_limiting(gemini_client):
    """Test that rate limiting waits until the next shared slot."""
    import time

    gemini_module._global_next_allowed_time = time.monotonic() + 0.15

    start = time.time()
    await gemini_client._rate_limit()
    duration = time.time() - start
    assert 0.12 <= duration <= 0.35


@pytest.mark.asyncio
async def test_execute_rate_limited_serializes_requests(gemini_client):
    """Test that rate-limited execution prevents overlapping Gemini calls."""
    gemini_client.min_interval_seconds = 0.05
    gemini_module._global_next_allowed_time = 0.0

    running = 0
    max_running = 0

    async def fake_request():
        nonlocal running, max_running
        running += 1
        max_running = max(max_running, running)
        await asyncio.sleep(0.02)
        running -= 1
        return "ok"

    await asyncio.gather(
        gemini_client._execute_rate_limited(fake_request),
        gemini_client._execute_rate_limited(fake_request),
    )

    assert max_running == 1


@pytest.mark.asyncio
async def test_generate_json_structure(gemini_client):
    """Test generate_json method structure (mocked)."""
    mock_response = Mock()
    mock_response.text = '{"decisions": [], "ambiguous_items": []}'
    
    with patch('google.generativeai.GenerativeModel') as mock_model_class:
        mock_model = Mock()
        mock_model.generate_content = Mock(return_value=mock_response)
        mock_model_class.return_value = mock_model
        gemini_client.min_interval_seconds = 0
        gemini_module._global_next_allowed_time = 0.0
        
        result = await gemini_client.generate_json(
            prompt="Test prompt",
            system_instruction="Test instruction",
            response_schema={"type": "object"},
            temperature=0.1
        )
        
        assert result == {"decisions": [], "ambiguous_items": []}


@pytest.mark.asyncio
async def test_retry_with_backoff_success(gemini_client):
    """Test retry logic succeeds on first attempt."""
    async def success_func():
        return {"result": "success"}
    
    result = await gemini_client._retry_with_backoff(success_func)
    assert result == {"result": "success"}


@pytest.mark.asyncio
async def test_retry_with_backoff_rate_limit(gemini_client):
    """Test retry logic handles rate limit errors."""
    call_count = 0
    
    async def rate_limit_func():
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise Exception("429 Rate limit exceeded")
        return {"result": "success"}
    
    result = await gemini_client._retry_with_backoff(
        rate_limit_func,
        backoff_schedule=[0.1, 0.2, 0.3]  # Shorter delays for testing
    )
    
    assert result == {"result": "success"}
    assert call_count == 3


@pytest.mark.asyncio
async def test_retry_with_backoff_max_retries(gemini_client):
    """Test retry logic raises error after max retries."""
    async def always_fail_func():
        raise Exception("429 Rate limit exceeded")
    
    with pytest.raises(GeminiRateLimitError):
        await gemini_client._retry_with_backoff(
            always_fail_func,
            backoff_schedule=[0.1, 0.2, 0.3]
        )


@pytest.mark.asyncio
async def test_retry_with_backoff_non_rate_limit_error(gemini_client):
    """Test retry logic doesn't retry non-rate-limit errors."""
    async def other_error_func():
        raise Exception("Some other error")
    
    with pytest.raises(GeminiAPIError):
        await gemini_client._retry_with_backoff(other_error_func)


@pytest.mark.asyncio
async def test_transcribe_audio_structure(gemini_client):
    """Test transcribe_audio method structure (mocked)."""
    mock_response = Mock()
    mock_response.text = '''
    {
        "segments": [
            {"speaker": "Speaker A", "timestamp": "00:00:05", "text": "Hello"},
            {"speaker": "Speaker B", "timestamp": "00:00:10", "text": "Hi there"}
        ]
    }
    '''
    
    with patch('google.generativeai.GenerativeModel') as mock_model_class:
        mock_model = Mock()
        mock_model.generate_content = Mock(return_value=mock_response)
        mock_model_class.return_value = mock_model
        gemini_client.min_interval_seconds = 0
        gemini_module._global_next_allowed_time = 0.0
        
        result = await gemini_client.transcribe_audio(
            audio_data=b"fake_audio_data",
            mime_type="audio/wav"
        )
        
        assert len(result) == 2
        assert isinstance(result[0], TranscriptSegment)
        assert result[0].speaker == "Speaker A"
        assert result[0].timestamp == "00:00:05"
        assert result[0].text == "Hello"
