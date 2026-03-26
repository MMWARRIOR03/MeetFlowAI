"""
Unit tests for IngestionAgent.
"""
import pytest
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

from agents.ingestion_agent import IngestionAgent
from schemas.base import InputFormat, MeetingMetadata, TranscriptSegment
from integrations.gemini import GeminiClient


@pytest.fixture
def mock_gemini_client():
    """Create mock GeminiClient."""
    client = MagicMock(spec=GeminiClient)
    client.transcribe_audio = AsyncMock()
    return client


@pytest.fixture
def ingestion_agent(mock_gemini_client):
    """Create IngestionAgent with mock GeminiClient."""
    return IngestionAgent(gemini_client=mock_gemini_client)


@pytest.fixture
def sample_metadata():
    """Sample meeting metadata."""
    return MeetingMetadata(
        title="Test Meeting",
        date=date(2026, 3, 15),
        participants=["Alice", "Bob", "Charlie"]
    )


@pytest.mark.asyncio
async def test_ingest_vtt_format(ingestion_agent, sample_metadata):
    """Test ingesting VTT format."""
    vtt_content = """WEBVTT

00:00:00.000 --> 00:00:05.000
<v Alice>Hello everyone, let's start the meeting.

00:00:05.000 --> 00:00:10.000
<v Bob>Thanks Alice. I have an update on the project.

00:00:10.000 --> 00:00:15.000
<v Charlie>Great, I'm ready to hear it.
"""
    
    with patch('agents.ingestion_agent.get_db_session'):
        result = await ingestion_agent.ingest(
            input_data=vtt_content,
            input_format=InputFormat.VTT,
            metadata=sample_metadata
        )
    
    assert result.title == "Test Meeting"
    assert result.date == date(2026, 3, 15)
    assert len(result.participants) == 3
    assert len(result.transcript) == 3
    assert result.transcript[0].speaker == "Alice"
    assert result.transcript[0].timestamp == "00:00:00"
    assert "Hello everyone" in result.transcript[0].text


@pytest.mark.asyncio
async def test_ingest_text_format_with_speaker_labels(ingestion_agent, sample_metadata):
    """Test ingesting plain text with speaker labels."""
    text_content = """Alice: Hello everyone, let's start the meeting.
Bob: Thanks Alice. I have an update on the project.
Charlie: Great, I'm ready to hear it.
"""
    
    with patch('agents.ingestion_agent.get_db_session'):
        result = await ingestion_agent.ingest(
            input_data=text_content,
            input_format=InputFormat.TXT,
            metadata=sample_metadata
        )
    
    assert len(result.transcript) == 3
    assert result.transcript[0].speaker == "Alice"
    assert result.transcript[1].speaker == "Bob"
    assert result.transcript[2].speaker == "Charlie"
    assert "Hello everyone" in result.transcript[0].text


@pytest.mark.asyncio
async def test_ingest_text_format_without_speaker_labels(ingestion_agent, sample_metadata):
    """Test ingesting plain text without speaker labels (alternating speakers)."""
    text_content = """Hello everyone, let's start the meeting.
Thanks for joining. I have an update on the project.
Great, I'm ready to hear it.
"""
    
    with patch('agents.ingestion_agent.get_db_session'):
        result = await ingestion_agent.ingest(
            input_data=text_content,
            input_format=InputFormat.TXT,
            metadata=sample_metadata
        )
    
    assert len(result.transcript) == 3
    assert result.transcript[0].speaker == "Speaker A"
    assert result.transcript[1].speaker == "Speaker B"
    assert result.transcript[2].speaker == "Speaker A"


@pytest.mark.asyncio
async def test_ingest_audio_format(ingestion_agent, mock_gemini_client, sample_metadata):
    """Test ingesting audio format."""
    audio_data = b"fake_audio_data"
    
    # Mock transcription response
    mock_gemini_client.transcribe_audio.return_value = [
        TranscriptSegment(speaker="Alice", timestamp="00:00:00", text="Hello everyone"),
        TranscriptSegment(speaker="Bob", timestamp="00:00:05", text="Thanks Alice")
    ]
    
    with patch('agents.ingestion_agent.get_db_session'):
        result = await ingestion_agent.ingest(
            input_data=audio_data,
            input_format=InputFormat.AUDIO,
            metadata=sample_metadata
        )
    
    assert len(result.transcript) == 2
    assert result.transcript[0].speaker == "Alice"
    assert result.transcript[1].speaker == "Bob"
    mock_gemini_client.transcribe_audio.assert_called_once()


@pytest.mark.asyncio
async def test_ingest_json_format(ingestion_agent, sample_metadata):
    """Test ingesting JSON format."""
    json_content = """{
    "transcript": [
        {"speaker": "Alice", "timestamp": "00:00:00", "text": "Hello everyone"},
        {"speaker": "Bob", "timestamp": "00:00:05", "text": "Thanks Alice"}
    ]
}"""
    
    with patch('agents.ingestion_agent.get_db_session'):
        result = await ingestion_agent.ingest(
            input_data=json_content,
            input_format=InputFormat.JSON,
            metadata=sample_metadata
        )
    
    assert len(result.transcript) == 2
    assert result.transcript[0].speaker == "Alice"
    assert result.transcript[1].speaker == "Bob"


@pytest.mark.asyncio
async def test_ingest_invalid_json(ingestion_agent, sample_metadata):
    """Test ingesting invalid JSON."""
    json_content = "{ invalid json }"
    
    with patch('agents.ingestion_agent.get_db_session'):
        with pytest.raises(ValueError, match="Invalid JSON"):
            await ingestion_agent.ingest(
                input_data=json_content,
                input_format=InputFormat.JSON,
                metadata=sample_metadata
            )


@pytest.mark.asyncio
async def test_ingest_json_missing_transcript(ingestion_agent, sample_metadata):
    """Test ingesting JSON without transcript field."""
    json_content = '{"title": "Test Meeting"}'
    
    with patch('agents.ingestion_agent.get_db_session'):
        with pytest.raises(ValueError, match="must contain 'transcript' field"):
            await ingestion_agent.ingest(
                input_data=json_content,
                input_format=InputFormat.JSON,
                metadata=sample_metadata
            )


@pytest.mark.asyncio
async def test_parse_vtt_with_voice_tags(ingestion_agent):
    """Test VTT parsing with <v Speaker> tags."""
    vtt_content = """WEBVTT

00:00:00.000 --> 00:00:05.000
<v Alice>Hello everyone

00:00:05.000 --> 00:00:10.000
<v Bob>Thanks Alice
"""
    
    segments = await ingestion_agent._parse_vtt(vtt_content)
    
    assert len(segments) == 2
    assert segments[0].speaker == "Alice"
    assert segments[0].text == "Hello everyone"
    assert segments[1].speaker == "Bob"


@pytest.mark.asyncio
async def test_parse_vtt_with_speaker_colon(ingestion_agent):
    """Test VTT parsing with Speaker: format."""
    vtt_content = """WEBVTT

00:00:00.000 --> 00:00:05.000
Alice: Hello everyone

00:00:05.000 --> 00:00:10.000
Bob: Thanks Alice
"""
    
    segments = await ingestion_agent._parse_vtt(vtt_content)
    
    assert len(segments) == 2
    assert segments[0].speaker == "Alice"
    assert segments[0].text == "Hello everyone"


@pytest.mark.asyncio
async def test_parse_text_with_multiword_speakers(ingestion_agent):
    """Test text parsing with multi-word speaker names."""
    text_content = """John Smith: Hello everyone
Mary Jane: Thanks John
"""
    
    segments = await ingestion_agent._parse_text(text_content)
    
    assert len(segments) == 2
    assert segments[0].speaker == "John Smith"
    assert segments[1].speaker == "Mary Jane"


@pytest.mark.asyncio
async def test_ingest_writes_audit_entry_on_success(ingestion_agent, sample_metadata):
    """Test that successful ingestion writes audit entry."""
    vtt_content = """WEBVTT

00:00:00.000 --> 00:00:05.000
<v Alice>Hello
"""
    
    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock()
    
    with patch('agents.ingestion_agent.get_db_session') as mock_get_session:
        mock_get_session.return_value.__aenter__.return_value = mock_session
        
        result = await ingestion_agent.ingest(
            input_data=vtt_content,
            input_format=InputFormat.VTT,
            metadata=sample_metadata
        )
    
    # Verify audit entry was written
    assert mock_session.add.called
    audit_entry = mock_session.add.call_args[0][0]
    assert audit_entry.agent == "IngestionAgent"
    assert audit_entry.outcome == "success"


@pytest.mark.asyncio
async def test_ingest_writes_audit_entry_on_failure(ingestion_agent, sample_metadata):
    """Test that failed ingestion writes audit entry."""
    invalid_json = "{ invalid }"
    
    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock()
    
    with patch('agents.ingestion_agent.get_db_session') as mock_get_session:
        mock_get_session.return_value.__aenter__.return_value = mock_session
        
        with pytest.raises(ValueError):
            await ingestion_agent.ingest(
                input_data=invalid_json,
                input_format=InputFormat.JSON,
                metadata=sample_metadata
            )
    
    # Verify audit entry was written
    assert mock_session.add.called
    audit_entry = mock_session.add.call_args[0][0]
    assert audit_entry.agent == "IngestionAgent"
    assert audit_entry.outcome == "failure"
