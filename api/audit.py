"""
FastAPI endpoints for audit trail queries.
"""
import logging
from typing import List, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from pydantic import BaseModel

from db.database import get_db
from db.models import AuditEntry, Meeting, Decision


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/audit", tags=["audit"])


# Response models
class AuditEntryResponse(BaseModel):
    """Response model for audit entry."""
    id: int
    meeting_id: str | None
    decision_id: str | None
    agent: str
    step: str
    outcome: str
    detail: str | None
    api_call: str | None
    http_status: int | None
    payload_snapshot: Dict[str, Any] | None
    created_at: str


class AuditSummaryResponse(BaseModel):
    """Response model for audit summary statistics."""
    total_meetings: int
    total_decisions: int
    total_audit_entries: int
    success_rate: float
    failure_rate: float
    pending_approvals: int
    completed_workflows: int
    failed_workflows: int


@router.get("/summary", response_model=AuditSummaryResponse)
async def get_audit_summary(
    db: AsyncSession = Depends(get_db)
) -> AuditSummaryResponse:
    """
    Get aggregate audit statistics.
    
    Args:
        db: Database session
        
    Returns:
        Audit summary with statistics
    """
    logger.info("Fetching audit summary")
    
    try:
        # Count total meetings
        meetings_result = await db.execute(select(func.count(Meeting.id)))
        total_meetings = meetings_result.scalar() or 0
        
        # Count total decisions
        decisions_result = await db.execute(select(func.count(Decision.id)))
        total_decisions = decisions_result.scalar() or 0
        
        # Count total audit entries
        audit_result = await db.execute(select(func.count(AuditEntry.id)))
        total_audit_entries = audit_result.scalar() or 0
        
        # Count success/failure outcomes
        success_result = await db.execute(
            select(func.count(AuditEntry.id))
            .where(AuditEntry.outcome == "success")
        )
        success_count = success_result.scalar() or 0
        
        failure_result = await db.execute(
            select(func.count(AuditEntry.id))
            .where(AuditEntry.outcome == "failure")
        )
        failure_count = failure_result.scalar() or 0
        
        # Calculate rates
        total_outcomes = success_count + failure_count
        success_rate = (success_count / total_outcomes * 100) if total_outcomes > 0 else 0.0
        failure_rate = (failure_count / total_outcomes * 100) if total_outcomes > 0 else 0.0
        
        # Count pending approvals
        pending_result = await db.execute(
            select(func.count(Decision.id))
            .where(Decision.approval_status == "pending")
        )
        pending_approvals = pending_result.scalar() or 0
        
        # Count completed workflows
        from db.models import WorkflowResult
        completed_result = await db.execute(
            select(func.count(WorkflowResult.id))
            .where(WorkflowResult.status == "success")
        )
        completed_workflows = completed_result.scalar() or 0
        
        # Count failed workflows
        failed_result = await db.execute(
            select(func.count(WorkflowResult.id))
            .where(WorkflowResult.status == "failed")
        )
        failed_workflows = failed_result.scalar() or 0
        
        return AuditSummaryResponse(
            total_meetings=total_meetings,
            total_decisions=total_decisions,
            total_audit_entries=total_audit_entries,
            success_rate=round(success_rate, 2),
            failure_rate=round(failure_rate, 2),
            pending_approvals=pending_approvals,
            completed_workflows=completed_workflows,
            failed_workflows=failed_workflows
        )
        
    except Exception as e:
        logger.error(f"Failed to fetch audit summary: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch audit summary: {str(e)}"
        )


@router.get("/decision/{decision_id}", response_model=List[AuditEntryResponse])
async def get_decision_audit_trail(
    decision_id: str,
    db: AsyncSession = Depends(get_db)
) -> List[AuditEntryResponse]:
    """
    Get all audit entries for a decision.
    
    Args:
        decision_id: Decision identifier
        db: Database session
        
    Returns:
        List of audit entries
        
    Raises:
        HTTPException: If decision not found
    """
    logger.info(f"Fetching audit trail for decision: {decision_id}")
    
    try:
        # Verify decision exists
        decision_result = await db.execute(
            select(Decision).where(Decision.id == decision_id)
        )
        decision = decision_result.scalar_one_or_none()
        
        if not decision:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Decision {decision_id} not found"
            )
        
        # Query audit entries
        result = await db.execute(
            select(AuditEntry)
            .where(AuditEntry.decision_id == decision_id)
            .order_by(AuditEntry.created_at)
        )
        audit_entries = result.scalars().all()
        
        return [
            AuditEntryResponse(
                id=entry.id,
                meeting_id=entry.meeting_id,
                decision_id=entry.decision_id,
                agent=entry.agent,
                step=entry.step,
                outcome=entry.outcome,
                detail=entry.detail,
                api_call=entry.api_call,
                http_status=entry.http_status,
                payload_snapshot=entry.payload_snapshot,
                created_at=entry.created_at.isoformat()
            )
            for entry in audit_entries
        ]
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to fetch audit trail: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch audit trail: {str(e)}"
        )


@router.get("/{meeting_id}", response_model=List[AuditEntryResponse])
async def get_meeting_audit_trail(
    meeting_id: str,
    db: AsyncSession = Depends(get_db)
) -> List[AuditEntryResponse]:
    """
    Get all audit entries for a meeting.
    
    Args:
        meeting_id: Meeting identifier
        db: Database session
        
    Returns:
        List of audit entries
        
    Raises:
        HTTPException: If meeting not found
    """
    logger.info(f"Fetching audit trail for meeting: {meeting_id}")
    
    try:
        meeting_result = await db.execute(
            select(Meeting).where(Meeting.id == meeting_id)
        )
        meeting = meeting_result.scalar_one_or_none()
        
        if not meeting:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Meeting {meeting_id} not found"
            )
        
        result = await db.execute(
            select(AuditEntry)
            .where(AuditEntry.meeting_id == meeting_id)
            .order_by(AuditEntry.created_at)
        )
        audit_entries = result.scalars().all()
        
        return [
            AuditEntryResponse(
                id=entry.id,
                meeting_id=entry.meeting_id,
                decision_id=entry.decision_id,
                agent=entry.agent,
                step=entry.step,
                outcome=entry.outcome,
                detail=entry.detail,
                api_call=entry.api_call,
                http_status=entry.http_status,
                payload_snapshot=entry.payload_snapshot,
                created_at=entry.created_at.isoformat()
            )
            for entry in audit_entries
        ]
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to fetch audit trail: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch audit trail: {str(e)}"
        )
