"""
Ingestion Agent for MeetFlow AI system.
Normalizes meeting inputs from multiple formats (VTT/txt/audio/JSON) into standardized NormalizedMeeting format.
"""
import logging
import re
import json
from datetime import datetime
from typing import List
from uuid import uuid4

from schemas.base import (
    InputFormat,
    MeetingMetadata,
    NormalizedMeeting,
    TranscriptSegment
)
from integrations.gemini import GeminiClient
from db.models import AuditEntry
from db.database import get_db_session


logger = logging.getLogger(__name__)


class IngestionAgent:
    """
    Normalizes meeting inputs (VTT/txt/audio/JSON) into NormalizedMeeting.
    """
    
    def __init__(self, gemini_client: GeminiClient):
        """
        Initialize IngestionAgent with GeminiClient for audio transcription.
        
        Args:
            gemini_client: GeminiClient instance for audio transcription
        """
        self.gemini_client = gemini_client
        logger.info("IngestionAgent initialized")
    
    async def ingest(
        self,
        input_data: bytes | str,
        input_format: InputFormat,
        metadata: MeetingMetadata
    ) -> NormalizedMeeting:
        """
        Ingest meeting data and normalize to standard format.
        
        Args:
            input_data: Raw input data (bytes for audio, str for text formats)
            input_format: VTT, TXT, AUDIO, or JSON
            metadata: Meeting metadata (title, date, participants)
            
        Returns:
            NormalizedMeeting with standardized transcript
            
        Raises:
            ValueError: If input format is invalid or parsing fails
        """
        meeting_id = str(uuid4())
        logger.info(f"Ingesting meeting {meeting_id} with format {input_format}")
        
        try:
            # Route to format-specific parser
            if input_format == InputFormat.VTT:
                transcript = await self._parse_vtt(input_data)
            elif input_format == InputFormat.TXT:
                transcript = await self._parse_text(input_data)
            elif input_format == InputFormat.AUDIO:
                transcript = await self._transcribe_audio(input_data)
            elif input_format == InputFormat.JSON:
                transcript = await self._parse_json(input_data)
            else:
                raise ValueError(f"Unsupported input format: {input_format}")
            
            # Create normalized meeting
            normalized_meeting = NormalizedMeeting(
                meeting_id=meeting_id,
                title=metadata.title,
                date=metadata.date,
                participants=metadata.participants,
                transcript=transcript
            )
            
            logger.info(f"Successfully ingested meeting {meeting_id} with {len(transcript)} transcript segments")
            return normalized_meeting
            
        except Exception as e:
            logger.error(f"Failed to ingest meeting: {e}")
            raise
    
    async def _parse_vtt(self, vtt_content: str) -> List[TranscriptSegment]:
        """
        Parse WebVTT format.
        Extract speaker labels from cue headers.
        Normalize timestamps to HH:MM:SS format.
        
        Args:
            vtt_content: WebVTT file content as string
            
        Returns:
            List of TranscriptSegment objects
        """
        logger.info("Parsing VTT format")
        segments = []
        
        # Split into lines and remove WEBVTT header
        lines = vtt_content.strip().split('\n')
        
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            
            # Skip empty lines and WEBVTT header
            if not line or line.startswith('WEBVTT') or line.startswith('NOTE'):
                i += 1
                continue
            
            # Check if this is a cue identifier (optional)
            if '-->' not in line:
                # This might be a cue identifier or speaker label
                cue_id = line
                i += 1
                if i >= len(lines):
                    break
                line = lines[i].strip()
            else:
                cue_id = None
            
            # Parse timestamp line (format: 00:00:00.000 --> 00:00:05.000)
            if '-->' in line:
                timestamp_match = re.match(r'(\d{2}:\d{2}:\d{2})\.\d+ --> \d{2}:\d{2}:\d{2}\.\d+', line)
                if timestamp_match:
                    timestamp = timestamp_match.group(1)
                else:
                    # Try alternative format without milliseconds
                    timestamp_match = re.match(r'(\d{2}:\d{2}:\d{2})', line)
                    if timestamp_match:
                        timestamp = timestamp_match.group(1)
                    else:
                        logger.warning(f"Could not parse timestamp: {line}")
                        i += 1
                        continue
                
                i += 1
                
                # Read cue text (may span multiple lines)
                cue_text_lines = []
                while i < len(lines) and lines[i].strip():
                    cue_text_lines.append(lines[i].strip())
                    i += 1
                
                cue_text = ' '.join(cue_text_lines)
                
                # Extract speaker from cue text
                # Format: <v Speaker Name>text or Speaker: text
                speaker = "Unknown"
                text = cue_text
                
                # Try <v Speaker> format
                voice_tag_match = re.match(r'<v\s+([^>]+)>(.*)', cue_text)
                if voice_tag_match:
                    speaker = voice_tag_match.group(1).strip()
                    text = voice_tag_match.group(2).strip()
                # Try "Speaker:" format
                elif ':' in cue_text:
                    parts = cue_text.split(':', 1)
                    if len(parts) == 2 and len(parts[0].split()) <= 3:  # Likely a speaker name
                        speaker = parts[0].strip()
                        text = parts[1].strip()
                # Use cue_id as speaker if available
                elif cue_id and not cue_id.isdigit():
                    speaker = cue_id
                
                segments.append(TranscriptSegment(
                    speaker=speaker,
                    timestamp=timestamp,
                    text=text
                ))
            else:
                i += 1
        
        logger.info(f"Parsed {len(segments)} segments from VTT")
        return segments
    
    async def _parse_text(self, text_content: str) -> List[TranscriptSegment]:
        """
        Parse plain text format.
        Detect 'Speaker:' prefixes.
        Assign Speaker A/B if no prefix found.
        
        Args:
            text_content: Plain text content
            
        Returns:
            List of TranscriptSegment objects
        """
        logger.info("Parsing plain text format")
        segments = []
        
        lines = text_content.strip().split('\n')
        current_speaker = "Speaker A"
        speaker_toggle = {"Speaker A": "Speaker B", "Speaker B": "Speaker A"}
        timestamp_counter = 0
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            # Try to detect speaker prefix (format: "Speaker Name: text")
            speaker_match = re.match(r'^([A-Za-z\s]+):\s*(.+)$', line)
            if speaker_match:
                speaker = speaker_match.group(1).strip()
                text = speaker_match.group(2).strip()
            else:
                # No speaker prefix, alternate between Speaker A and B
                speaker = current_speaker
                text = line
                current_speaker = speaker_toggle.get(current_speaker, "Speaker A")
            
            # Generate synthetic timestamp (increment by 5 seconds per segment)
            hours = timestamp_counter // 3600
            minutes = (timestamp_counter % 3600) // 60
            seconds = timestamp_counter % 60
            timestamp = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
            timestamp_counter += 5
            
            segments.append(TranscriptSegment(
                speaker=speaker,
                timestamp=timestamp,
                text=text
            ))
        
        logger.info(f"Parsed {len(segments)} segments from plain text")
        return segments
    
    async def _transcribe_audio(
        self,
        audio_data: bytes,
        mime_type: str = "audio/wav"
    ) -> List[TranscriptSegment]:
        """
        Transcribe audio using GeminiClient.
        
        Args:
            audio_data: Raw audio bytes
            mime_type: Audio MIME type (default: audio/wav)
            
        Returns:
            List of TranscriptSegment objects
        """
        logger.info(f"Transcribing audio: {len(audio_data)} bytes")
        
        # Use GeminiClient to transcribe
        segments = await self.gemini_client.transcribe_audio(audio_data, mime_type)
        
        logger.info(f"Transcribed {len(segments)} segments from audio")
        return segments
    
    async def _parse_json(self, json_content: str) -> List[TranscriptSegment]:
        """
        Parse JSON format meeting data.
        Validate against NormalizedMeeting schema.
        
        Args:
            json_content: JSON string content
            
        Returns:
            List of TranscriptSegment objects
            
        Raises:
            ValueError: If JSON is invalid or doesn't match schema
        """
        logger.info("Parsing JSON format")
        
        try:
            data = json.loads(json_content)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON: {e}")
        
        # Extract transcript from JSON
        if 'transcript' not in data:
            raise ValueError("JSON must contain 'transcript' field")
        
        transcript_data = data['transcript']
        if not isinstance(transcript_data, list):
            raise ValueError("'transcript' must be a list")
        
        # Validate and convert to TranscriptSegment objects
        segments = []
        for i, segment_data in enumerate(transcript_data):
            try:
                segment = TranscriptSegment(**segment_data)
                segments.append(segment)
            except Exception as e:
                raise ValueError(f"Invalid segment at index {i}: {e}")
        
        logger.info(f"Parsed {len(segments)} segments from JSON")
        return segments
    
    async def _write_audit_entry(
        self,
        meeting_id: str,
        outcome: str,
        detail: str
    ) -> None:
        """
        Write audit entry for ingestion event.
        
        Args:
            meeting_id: Meeting identifier
            outcome: success or failure
            detail: Detailed description of the outcome
        """
        try:
            async with get_db_session() as session:
                audit_entry = AuditEntry(
                    meeting_id=meeting_id,
                    agent="IngestionAgent",
                    step="ingest",
                    outcome=outcome,
                    detail=detail,
                    created_at=datetime.utcnow()
                )
                session.add(audit_entry)
                await session.commit()
                logger.debug(f"Wrote audit entry for meeting {meeting_id}")
        except Exception as e:
            logger.error(f"Failed to write audit entry: {e}")
            # Don't raise - audit failure shouldn't block ingestion
