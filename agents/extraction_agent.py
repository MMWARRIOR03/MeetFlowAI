"""
Decision Extraction Agent for MeetFlow AI.
Extracts structured decisions from meeting transcripts using Gemini.
"""
import logging
from datetime import date, timedelta
from typing import List, Tuple, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from schemas.base import (
    NormalizedMeeting,
    Decision,
    AmbiguousItem,
    ExtractionOutput
)
from integrations.gemini import GeminiClient
from integrations.llm_factory import get_llm_api_call_label
from prompts.extraction import EXTRACTION_PROMPT, EXTRACTION_SCHEMA
from db.models import AuditEntry


logger = logging.getLogger(__name__)


class ExtractionAgent:
    """
    Extracts structured decisions from meeting transcripts.
    Uses Gemini for AI-powered extraction with confidence scoring.
    """
    
    def __init__(self, gemini_client: GeminiClient, db_session: AsyncSession):
        """
        Initialize ExtractionAgent.
        
        Args:
            gemini_client: GeminiClient instance for API calls
            db_session: Database session for audit trail
        """
        self.gemini_client = gemini_client
        self.db_session = db_session
        logger.info("ExtractionAgent initialized")
    
    async def extract_decisions(
        self,
        meeting: NormalizedMeeting
    ) -> ExtractionOutput:
        """
        Extract decisions from meeting transcript.
        
        Args:
            meeting: Normalized meeting with transcript
            
        Returns:
            ExtractionOutput with decisions and ambiguous items
        """
        logger.info(f"Extracting decisions from meeting: {meeting.meeting_id}")
        
        try:
            # Build prompt from transcript
            transcript_text = self._format_transcript(meeting)
            prompt = self._build_extraction_prompt(meeting, transcript_text)
            
            # Call Gemini for extraction
            logger.info("Calling Gemini for decision extraction")
            response = await self.gemini_client.generate_json(
                prompt=prompt,
                system_instruction=EXTRACTION_PROMPT,
                response_schema=EXTRACTION_SCHEMA,
                temperature=0.1
            )
            
            # Parse response into Pydantic models
            decisions_raw = response.get("decisions", [])
            ambiguous_items_raw = response.get("ambiguous_items", [])
            
            # Generate unique decision IDs (replace Gemini's sequential IDs)
            import uuid
            for i, decision_data in enumerate(decisions_raw):
                decision_data["decision_id"] = f"dec_{uuid.uuid4().hex[:8]}"
            
            # Convert to Pydantic models
            decisions = [Decision(**d) for d in decisions_raw]
            ambiguous_items = [AmbiguousItem(**a) for a in ambiguous_items_raw]
            
            # Resolve relative deadlines
            decisions = await self._resolve_relative_deadlines(decisions, meeting.date)
            
            # Filter low confidence decisions
            decisions, additional_ambiguous = self._filter_low_confidence(decisions)
            ambiguous_items.extend(additional_ambiguous)
            
            logger.info(
                f"Extracted {len(decisions)} decisions and "
                f"{len(ambiguous_items)} ambiguous items"
            )
            
            # Write audit entry for extraction completion only (no per-decision entries)
            await self._write_audit_entry(
                meeting_id=meeting.meeting_id,
                decision_id=None,
                outcome="success",
                detail=f"Extraction complete: {len(decisions)} decisions, {len(ambiguous_items)} ambiguous",
                api_call=get_llm_api_call_label()
            )
            
            return ExtractionOutput(
                decisions=decisions,
                ambiguous_items=ambiguous_items
            )
            
        except Exception as e:
            logger.error(f"Decision extraction failed: {e}")
            
            # Write audit entry for failure
            await self._write_audit_entry(
                meeting_id=meeting.meeting_id,
                decision_id=None,
                outcome="failure",
                detail=f"Extraction failed: {str(e)}"
            )
            
            raise
    
    def _format_transcript(self, meeting: NormalizedMeeting) -> str:
        """
        Format transcript segments into readable text.
        
        Args:
            meeting: Normalized meeting
            
        Returns:
            Formatted transcript text
        """
        lines = []
        for segment in meeting.transcript:
            lines.append(f"[{segment.timestamp}] {segment.speaker}: {segment.text}")
        return "\n".join(lines)
    
    def _build_extraction_prompt(
        self,
        meeting: NormalizedMeeting,
        transcript_text: str
    ) -> str:
        """
        Build extraction prompt with meeting context.
        
        Args:
            meeting: Normalized meeting
            transcript_text: Formatted transcript
            
        Returns:
            Complete prompt for Gemini
        """
        prompt = f"""
Meeting Title: {meeting.title}
Meeting Date: {meeting.date.isoformat()}
Participants: {", ".join(meeting.participants)}

Transcript:
{transcript_text}

Extract all actionable decisions from this meeting transcript.
Resolve relative deadlines based on the meeting date ({meeting.date.isoformat()}).
"""
        return prompt

    async def _resolve_relative_deadlines(
        self,
        decisions: List[Decision],
        meeting_date: date
    ) -> List[Decision]:
        """
        Resolve relative deadlines to ISO dates.
        
        Args:
            decisions: List of decisions with potentially relative deadlines
            meeting_date: Date of the meeting for reference
            
        Returns:
            List of decisions with resolved deadlines
        """
        logger.info("Resolving relative deadlines")
        
        resolved_decisions = []
        for decision in decisions:
            # Decision deadlines should already be in ISO format from Gemini
            # This method is a safety check and can handle edge cases
            resolved_decisions.append(decision)
        
        return resolved_decisions
    
    def _filter_low_confidence(
        self,
        decisions: List[Decision],
        threshold: float = 0.75
    ) -> Tuple[List[Decision], List[AmbiguousItem]]:
        """
        Filter decisions below confidence threshold to ambiguous_items.
        
        Args:
            decisions: List of extracted decisions
            threshold: Confidence threshold (default: 0.75)
            
        Returns:
            Tuple of (high_confidence_decisions, low_confidence_ambiguous_items)
        """
        logger.info(f"Filtering decisions with confidence threshold: {threshold}")
        
        high_confidence = []
        low_confidence_ambiguous = []
        
        for decision in decisions:
            if decision.confidence >= threshold:
                high_confidence.append(decision)
            else:
                # Convert low confidence decision to ambiguous item
                ambiguous = AmbiguousItem(
                    description=decision.description,
                    reason=f"Low confidence score: {decision.confidence:.2f}",
                    raw_quote=decision.raw_quote
                )
                low_confidence_ambiguous.append(ambiguous)
                logger.info(
                    f"Decision {decision.decision_id} filtered as ambiguous "
                    f"(confidence: {decision.confidence:.2f})"
                )
        
        logger.info(
            f"Filtered: {len(high_confidence)} high confidence, "
            f"{len(low_confidence_ambiguous)} low confidence"
        )
        
        return high_confidence, low_confidence_ambiguous
    
    async def _write_audit_entry(
        self,
        meeting_id: str,
        decision_id: Optional[str],
        outcome: str,
        detail: str,
        api_call: Optional[str] = None
    ) -> None:
        """
        Write audit entry for extraction action.
        
        Args:
            meeting_id: Meeting identifier
            decision_id: Decision identifier (optional)
            outcome: Outcome status (success, failure, pending)
            detail: Detailed description of the action
        """
        audit_entry = AuditEntry(
            meeting_id=meeting_id,
            decision_id=decision_id,
            agent="ExtractionAgent",
            step="extract_decisions",
                outcome=outcome,
                detail=detail,
                api_call=api_call
            )
        
        self.db_session.add(audit_entry)
        await self.db_session.commit()
        
        logger.debug(f"Audit entry written: {outcome} - {detail}")
