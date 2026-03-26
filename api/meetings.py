"""
FastAPI endpoints for meeting and decision management.
"""
import logging
from typing import Dict, Any, Optional
from datetime import date as date_type

from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel, Field

from db.database import get_db
from db.models import Meeting, Decision, WorkflowResult as WorkflowResultModel
from schemas.base import InputFormat, MeetingMetadata
from orchestrator.graph import build_pipeline, PipelineState


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["meetings"])


# Request/Response models
class MeetingIngestRequest(BaseModel):
    """Request model for meeting ingestion."""
    input_format: str = Field(..., description="Input format: vtt, txt, audio, json")
    title: str = Field(..., description="Meeting title")
    date: str = Field(..., description="Meeting date (ISO format)")
    participants: list[str] = Field(..., description="List of participant names")
    content: str = Field(..., description="Meeting content (text/vtt/json)")


class MeetingIngestResponse(BaseModel):
    """Response model for meeting ingestion."""
    meeting_id: str
    status: str
    message: str


class MeetingResponse(BaseModel):
    """Response model for meeting details."""
    meeting_id: str
    title: str
    date: str
    participants: list[str]
    status: str
    decisions: list[Dict[str, Any]]


class DecisionResponse(BaseModel):
    """Response model for decision details."""
    decision_id: str
    meeting_id: str
    description: str
    owner: str
    deadline: str
    workflow_type: Optional[str]
    approval_status: str
    confidence: float
    parameters: Optional[Dict[str, Any]]


class ApprovalRequest(BaseModel):
    """Request model for approval/rejection."""
    approver: str = Field(..., description="Name of approver")
    comment: Optional[str] = Field(None, description="Optional comment")


class PipelineStatusResponse(BaseModel):
    """Response model for pipeline status."""
    meeting_id: str
    status: str
    completed_steps: list[str]
    pending_steps: list[str]
    errors: list[str]


@router.post("/meetings/ingest", response_model=MeetingIngestResponse, status_code=status.HTTP_201_CREATED)
async def ingest_meeting(
    request: MeetingIngestRequest,
    db: AsyncSession = Depends(get_db)
) -> MeetingIngestResponse:
    """
    Ingest a meeting and start the processing pipeline.
    
    Args:
        request: Meeting ingestion request
        db: Database session
        
    Returns:
        Meeting ID and status
        
    Raises:
        HTTPException: If ingestion fails
    """
    logger.info(f"Ingesting meeting: {request.title}")
    
    try:
        # Validate input format
        try:
            input_format = InputFormat(request.input_format.lower())
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid input format: {request.input_format}. Must be one of: vtt, txt, audio, json"
            )
        
        # Parse date
        try:
            meeting_date = date_type.fromisoformat(request.date)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid date format: {request.date}. Must be ISO format (YYYY-MM-DD)"
            )
        
        # Build pipeline
        pipeline = build_pipeline()
        
        # Generate meeting ID
        import uuid
        meeting_id = str(uuid.uuid4())
        
        # Create initial state
        initial_state: PipelineState = {
            "meeting_id": meeting_id,
            "meeting": None,
            "decisions": [],
            "classifier_outputs": [],
            "approval_pending": [],
            "workflow_results": [],
            "errors": [],
            "input_data": request.content,
            "input_format": input_format.value,
            "metadata": {
                "title": request.title,
                "date": request.date,
                "participants": request.participants
            }
        }
        
        # Invoke pipeline asynchronously
        # Note: In production, this should be run in a background task
        config = {"configurable": {"thread_id": meeting_id}}
        result = await pipeline.ainvoke(initial_state, config)
        
        logger.info(f"Meeting {meeting_id} ingested successfully")
        
        return MeetingIngestResponse(
            meeting_id=meeting_id,
            status="processing",
            message="Meeting ingestion started successfully"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to ingest meeting: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to ingest meeting: {str(e)}"
        )


@router.get("/meetings/{meeting_id}", response_model=MeetingResponse)
async def get_meeting(
    meeting_id: str,
    db: AsyncSession = Depends(get_db)
) -> MeetingResponse:
    """
    Get meeting details and extracted decisions.
    
    Args:
        meeting_id: Meeting identifier
        db: Database session
        
    Returns:
        Meeting details with decisions
        
    Raises:
        HTTPException: If meeting not found
    """
    logger.info(f"Fetching meeting: {meeting_id}")
    
    try:
        # Query meeting
        result = await db.execute(
            select(Meeting).where(Meeting.id == meeting_id)
        )
        meeting = result.scalar_one_or_none()
        
        if not meeting:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Meeting {meeting_id} not found"
            )
        
        # Query decisions
        decisions_result = await db.execute(
            select(Decision).where(Decision.meeting_id == meeting_id)
        )
        decisions = decisions_result.scalars().all()
        
        # Format decisions
        decisions_data = [
            {
                "decision_id": d.id,
                "description": d.description,
                "owner": d.owner,
                "deadline": d.deadline.isoformat(),
                "workflow_type": d.workflow_type,
                "approval_status": d.approval_status,
                "confidence": d.confidence
            }
            for d in decisions
        ]
        
        return MeetingResponse(
            meeting_id=meeting.id,
            title=meeting.title,
            date=meeting.date.isoformat(),
            participants=meeting.participants,
            status=meeting.status,
            decisions=decisions_data
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to fetch meeting: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch meeting: {str(e)}"
        )


@router.get("/decisions/{decision_id}", response_model=DecisionResponse)
async def get_decision(
    decision_id: str,
    db: AsyncSession = Depends(get_db)
) -> DecisionResponse:
    """
    Get decision details and execution status.
    
    Args:
        decision_id: Decision identifier
        db: Database session
        
    Returns:
        Decision details
        
    Raises:
        HTTPException: If decision not found
    """
    logger.info(f"Fetching decision: {decision_id}")
    
    try:
        # Query decision
        result = await db.execute(
            select(Decision).where(Decision.id == decision_id)
        )
        decision = result.scalar_one_or_none()
        
        if not decision:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Decision {decision_id} not found"
            )
        
        return DecisionResponse(
            decision_id=decision.id,
            meeting_id=decision.meeting_id,
            description=decision.description,
            owner=decision.owner,
            deadline=decision.deadline.isoformat(),
            workflow_type=decision.workflow_type,
            approval_status=decision.approval_status,
            confidence=decision.confidence,
            parameters=decision.parameters
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to fetch decision: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch decision: {str(e)}"
        )


@router.post("/decisions/{decision_id}/approve", status_code=status.HTTP_200_OK)
async def approve_decision(
    decision_id: str,
    request: ApprovalRequest,
    db: AsyncSession = Depends(get_db)
) -> Dict[str, str]:
    """
    Manually approve a decision.
    
    Args:
        decision_id: Decision identifier
        request: Approval request with approver info
        db: Database session
        
    Returns:
        Success message
        
    Raises:
        HTTPException: If decision not found or already processed
    """
    logger.info(f"Approving decision: {decision_id} by {request.approver}")
    
    try:
        # Query decision
        result = await db.execute(
            select(Decision).where(Decision.id == decision_id)
        )
        decision = result.scalar_one_or_none()
        
        if not decision:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Decision {decision_id} not found"
            )
        
        # Check if already approved or rejected
        if decision.approval_status in ["approved", "rejected"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Decision already {decision.approval_status}"
            )
        
        # Update approval status
        decision.approval_status = "approved"
        
        # Write audit entry
        from db.models import AuditEntry
        from datetime import datetime
        
        audit_entry = AuditEntry(
            decision_id=decision.id,
            meeting_id=decision.meeting_id,
            agent="API",
            step="approve_decision",
            outcome="success",
            detail=f"Decision approved by {request.approver}",
            payload_snapshot={
                "approver": request.approver,
                "comment": request.comment,
                "timestamp": datetime.utcnow().isoformat()
            }
        )
        db.add(audit_entry)
        
        await db.commit()
        
        logger.info(f"Decision {decision_id} approved successfully")
        
        return {
            "status": "success",
            "message": f"Decision {decision_id} approved by {request.approver}"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to approve decision: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to approve decision: {str(e)}"
        )


@router.post("/decisions/{decision_id}/reject", status_code=status.HTTP_200_OK)
async def reject_decision(
    decision_id: str,
    request: ApprovalRequest,
    db: AsyncSession = Depends(get_db)
) -> Dict[str, str]:
    """
    Manually reject a decision.
    
    Args:
        decision_id: Decision identifier
        request: Rejection request with approver info
        db: Database session
        
    Returns:
        Success message
        
    Raises:
        HTTPException: If decision not found or already processed
    """
    logger.info(f"Rejecting decision: {decision_id} by {request.approver}")
    
    try:
        # Query decision
        result = await db.execute(
            select(Decision).where(Decision.id == decision_id)
        )
        decision = result.scalar_one_or_none()
        
        if not decision:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Decision {decision_id} not found"
            )
        
        # Check if already approved or rejected
        if decision.approval_status in ["approved", "rejected"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Decision already {decision.approval_status}"
            )
        
        # Update approval status
        decision.approval_status = "rejected"
        
        # Write audit entry
        from db.models import AuditEntry
        from datetime import datetime
        
        audit_entry = AuditEntry(
            decision_id=decision.id,
            meeting_id=decision.meeting_id,
            agent="API",
            step="reject_decision",
            outcome="success",
            detail=f"Decision rejected by {request.approver}",
            payload_snapshot={
                "approver": request.approver,
                "comment": request.comment,
                "timestamp": datetime.utcnow().isoformat()
            }
        )
        db.add(audit_entry)
        
        await db.commit()
        
        logger.info(f"Decision {decision_id} rejected successfully")
        
        return {
            "status": "success",
            "message": f"Decision {decision_id} rejected by {request.approver}"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to reject decision: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to reject decision: {str(e)}"
        )


@router.get("/pipeline/status/{meeting_id}", response_model=PipelineStatusResponse)
async def get_pipeline_status(
    meeting_id: str,
    db: AsyncSession = Depends(get_db)
) -> PipelineStatusResponse:
    """
    Get pipeline execution status for a meeting.
    
    Args:
        meeting_id: Meeting identifier
        db: Database session
        
    Returns:
        Pipeline status with completed and pending steps
        
    Raises:
        HTTPException: If meeting not found
    """
    logger.info(f"Fetching pipeline status for meeting: {meeting_id}")
    
    try:
        # Query meeting
        result = await db.execute(
            select(Meeting).where(Meeting.id == meeting_id)
        )
        meeting = result.scalar_one_or_none()
        
        if not meeting:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Meeting {meeting_id} not found"
            )
        
        # Query audit entries to determine completed steps
        from db.models import AuditEntry
        
        audit_result = await db.execute(
            select(AuditEntry)
            .where(AuditEntry.meeting_id == meeting_id)
            .where(AuditEntry.outcome == "success")
            .order_by(AuditEntry.created_at)
        )
        audit_entries = audit_result.scalars().all()
        
        # Extract completed steps
        completed_steps = list(set([
            f"{entry.agent}.{entry.step}"
            for entry in audit_entries
        ]))
        
        # Query for errors
        error_result = await db.execute(
            select(AuditEntry)
            .where(AuditEntry.meeting_id == meeting_id)
            .where(AuditEntry.outcome == "failure")
        )
        error_entries = error_result.scalars().all()
        
        errors = [entry.detail for entry in error_entries]
        
        # Determine pending steps based on meeting status
        all_steps = [
            "IngestionAgent.ingest",
            "ExtractionAgent.extract_decisions",
            "ClassifierAgent.classify_decision",
            "SlackApprovalGate.send_approval_message",
            "JiraAgent.execute",
            "VerificationAgent.verify_execution",
            "SummaryAgent.send_summary"
        ]
        
        pending_steps = [step for step in all_steps if step not in completed_steps]
        
        return PipelineStatusResponse(
            meeting_id=meeting_id,
            status=meeting.status,
            completed_steps=completed_steps,
            pending_steps=pending_steps,
            errors=errors
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to fetch pipeline status: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch pipeline status: {str(e)}"
        )
