"""
Pydantic v2 schemas for MeetFlow AI system.
All schemas use BaseModel with field validators.
"""
from __future__ import annotations

from datetime import date as date_type, datetime
from typing import List, Optional, Dict, Any, Literal, TYPE_CHECKING
from enum import Enum
from pydantic import BaseModel, Field, field_validator


class WorkflowType(str, Enum):
    """Workflow type enumeration."""
    JIRA_CREATE = "jira_create"
    JIRA_UPDATE = "jira_update"
    JIRA_SEARCH = "jira_search"
    HR_HIRING = "hr_hiring"
    PROCUREMENT_REQUEST = "procurement_request"


class InputFormat(str, Enum):
    """Input format enumeration."""
    VTT = "vtt"
    TXT = "txt"
    AUDIO = "audio"
    JSON = "json"


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


class MeetingMetadata(BaseModel):
    """Metadata for a meeting."""
    title: str = Field(..., description="Meeting title")
    date: "date_type" = Field(..., description="Meeting date")
    participants: List[str] = Field(..., description="List of participant names")


class NormalizedMeeting(BaseModel):
    """Normalized meeting representation."""
    meeting_id: str = Field(..., description="Unique meeting identifier")
    title: str = Field(..., description="Meeting title")
    date: "date_type" = Field(..., description="Meeting date")
    participants: List[str] = Field(..., description="List of participant names")
    transcript: List[TranscriptSegment] = Field(..., description="Meeting transcript")


class Decision(BaseModel):
    """Extracted decision from meeting."""
    decision_id: str = Field(..., description="Unique decision identifier")
    description: str = Field(..., description="Decision description")
    owner: str = Field(..., description="Person responsible for execution")
    deadline: "date_type" = Field(..., description="Target completion date")
    workflow_type: Optional[WorkflowType] = Field(None, description="Workflow type classification")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Extraction confidence score")
    auto_trigger: bool = Field(False, description="Whether decision can auto-execute")
    requires_approval: bool = Field(False, description="Whether decision requires human approval")
    raw_quote: str = Field(..., description="Original text from transcript")


class AmbiguousItem(BaseModel):
    """Item that requires clarification."""
    description: str = Field(..., description="Description of ambiguous item")
    reason: str = Field(..., description="Reason for ambiguity")
    raw_quote: str = Field(..., description="Original text from transcript")


class ExtractionOutput(BaseModel):
    """Output from decision extraction agent."""
    decisions: List[Decision] = Field(..., description="Extracted decisions")
    ambiguous_items: List[AmbiguousItem] = Field(default_factory=list, description="Items requiring clarification")


class ClassifierOutput(BaseModel):
    """Output from classifier agent."""
    decision_id: str = Field(..., description="Decision identifier")
    workflow_type: WorkflowType = Field(..., description="Classified workflow type")
    parameters: Dict[str, Any] = Field(..., description="Workflow-specific parameters")
    requires_approval: bool = Field(..., description="Whether approval is required")
    slack_approval_batch: Optional[List[str]] = Field(None, description="Decision IDs for batch approval")


class WorkflowResult(BaseModel):
    """Result of workflow execution."""
    decision_id: str = Field(..., description="Decision identifier")
    workflow_type: WorkflowType = Field(..., description="Workflow type")
    status: Literal["success", "failed", "pending_retry"] = Field(..., description="Execution status")
    artifact_links: List[str] = Field(default_factory=list, description="Links to created artifacts")
    error_message: Optional[str] = Field(None, description="Error message if failed")


class VerificationResult(BaseModel):
    """Result of verification check."""
    decision_id: str = Field(..., description="Decision identifier")
    verified: bool = Field(..., description="Whether verification succeeded")
    discrepancies: List[str] = Field(default_factory=list, description="List of discrepancies found")
    details: Optional[Dict[str, Any]] = Field(None, description="Additional verification details")
