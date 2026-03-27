"""
Verification Agent for MeetFlow AI system.
Verifies workflow execution outcomes by querying target systems.
"""
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from schemas.base import WorkflowResult, VerificationResult, WorkflowType, NormalizedMeeting
from db.models import AuditEntry, Decision as DecisionModel, WorkflowResult as WorkflowResultModel
from agents.workflow.jira_agent import JiraAgent


logger = logging.getLogger(__name__)


class VerificationAgent:
    """
    Verifies workflow execution outcomes by querying target systems.
    Generates summaries for Slack notifications.
    """
    
    def __init__(self, db_session: AsyncSession):
        """
        Initialize VerificationAgent.
        
        Args:
            db_session: Database session for audit trail
        """
        self.db_session = db_session
        logger.info("VerificationAgent initialized")
    
    async def verify_execution(
        self,
        workflow_result: WorkflowResult
    ) -> VerificationResult:
        """
        Verify workflow execution by querying target system.
        
        Args:
            workflow_result: Result from workflow agent
            
        Returns:
            VerificationResult with status and discrepancies
        """
        logger.info(f"Verifying execution for decision {workflow_result.decision_id}")
        
        try:
            # Route to workflow-specific verification
            if workflow_result.workflow_type in [
                WorkflowType.JIRA_CREATE,
                WorkflowType.JIRA_UPDATE,
                WorkflowType.JIRA_SEARCH
            ]:
                return await self._verify_jira(workflow_result)
            elif workflow_result.workflow_type == WorkflowType.HR_HIRING:
                return await self._verify_hr(workflow_result)
            elif workflow_result.workflow_type == WorkflowType.PROCUREMENT_REQUEST:
                return await self._verify_procurement(workflow_result)
            else:
                logger.warning(f"Unknown workflow type: {workflow_result.workflow_type}")
                detail = f"Unknown workflow type: {workflow_result.workflow_type}"
                await self._write_audit_entry(
                    decision_id=workflow_result.decision_id,
                    outcome="failure",
                    detail=detail,
                )
                return VerificationResult(
                    decision_id=workflow_result.decision_id,
                    verified=False,
                    discrepancies=[detail]
                )
                
        except Exception as e:
            logger.error(f"Verification failed for decision {workflow_result.decision_id}: {e}")
            
            # Write audit entry for failure
            await self._write_audit_entry(
                decision_id=workflow_result.decision_id,
                outcome="failure",
                detail=f"Verification failed: {str(e)}"
            )
            
            return VerificationResult(
                decision_id=workflow_result.decision_id,
                verified=False,
                discrepancies=[f"Verification error: {str(e)}"]
            )
    
    async def _verify_jira(self, workflow_result: WorkflowResult) -> VerificationResult:
        """
        Verify Jira workflow execution.
        Query Jira API to confirm issue exists and fields match.
        
        Args:
            workflow_result: Workflow result to verify
            
        Returns:
            VerificationResult
        """
        logger.info(f"Verifying Jira workflow for decision {workflow_result.decision_id}")
        
        discrepancies = []
        
        # Check if workflow succeeded
        if workflow_result.status != "success":
            discrepancies.append(f"Workflow status is {workflow_result.status}")
            await self._write_audit_entry(
                decision_id=workflow_result.decision_id,
                outcome="failure",
                detail=f"Verification skipped because workflow status is {workflow_result.status}",
                payload_snapshot={"workflow_status": workflow_result.status},
            )
            return VerificationResult(
                decision_id=workflow_result.decision_id,
                verified=False,
                discrepancies=discrepancies
            )
        
        # Extract issue key from artifact links
        issue_key = None
        for link in workflow_result.artifact_links:
            if "/browse/" in link:
                issue_key = link.split("/browse/")[-1]
                break
        
        if not issue_key:
            discrepancies.append("No issue key found in artifact links")
            await self._write_audit_entry(
                decision_id=workflow_result.decision_id,
                outcome="failure",
                detail="Verification failed: no issue key found in artifact links",
            )
            return VerificationResult(
                decision_id=workflow_result.decision_id,
                verified=False,
                discrepancies=discrepancies
            )
        
        # Query Jira to verify issue exists
        jira_agent = JiraAgent()
        try:
            meeting_id = await self._resolve_meeting_id(workflow_result.decision_id)
            verified = await jira_agent._verify_ticket(issue_key)
            
            if verified:
                logger.info(f"Jira issue {issue_key} verified successfully")
                
                # Write success audit entry
                await self._write_audit_entry(
                    meeting_id=meeting_id,
                    decision_id=workflow_result.decision_id,
                    outcome="success",
                    detail=f"Verified Jira issue {issue_key}",
                    payload_snapshot={"issue_key": issue_key}
                )
                
                return VerificationResult(
                    decision_id=workflow_result.decision_id,
                    verified=True,
                    discrepancies=[],
                    details={"issue_key": issue_key}
                )
            else:
                discrepancies.append(f"Failed to verify Jira issue {issue_key}")
                
                # Write failure audit entry
                await self._write_audit_entry(
                    meeting_id=meeting_id,
                    decision_id=workflow_result.decision_id,
                    outcome="failure",
                    detail=f"Failed to verify Jira issue {issue_key}"
                )
                
                return VerificationResult(
                    decision_id=workflow_result.decision_id,
                    verified=False,
                    discrepancies=discrepancies
                )
        finally:
            await jira_agent.close()
    
    async def _verify_hr(self, workflow_result: WorkflowResult) -> VerificationResult:
        """
        Verify HR workflow execution.
        Note: HR system integration not implemented yet.
        
        Args:
            workflow_result: Workflow result to verify
            
        Returns:
            VerificationResult
        """
        logger.info(f"Verifying HR workflow for decision {workflow_result.decision_id}")
        
        # Placeholder - HR system not implemented
        # In production, would query HR system API
        
        if workflow_result.status == "success":
            await self._write_audit_entry(
                decision_id=workflow_result.decision_id,
                outcome="success",
                detail="HR workflow verification skipped (not implemented)"
            )
            
            return VerificationResult(
                decision_id=workflow_result.decision_id,
                verified=True,
                discrepancies=[],
                details={"note": "HR verification not implemented"}
            )
        else:
            await self._write_audit_entry(
                decision_id=workflow_result.decision_id,
                outcome="failure",
                detail=f"HR verification skipped because workflow status is {workflow_result.status}",
                payload_snapshot={"workflow_status": workflow_result.status},
            )
            return VerificationResult(
                decision_id=workflow_result.decision_id,
                verified=False,
                discrepancies=[f"Workflow status is {workflow_result.status}"]
            )
    
    async def _verify_procurement(self, workflow_result: WorkflowResult) -> VerificationResult:
        """
        Verify procurement workflow execution.
        Note: Procurement system integration not implemented yet.
        
        Args:
            workflow_result: Workflow result to verify
            
        Returns:
            VerificationResult
        """
        logger.info(f"Verifying procurement workflow for decision {workflow_result.decision_id}")
        
        # Placeholder - Procurement system not implemented
        # In production, would query procurement system API
        
        if workflow_result.status == "success":
            await self._write_audit_entry(
                decision_id=workflow_result.decision_id,
                outcome="success",
                detail="Procurement workflow verification skipped (not implemented)"
            )
            
            return VerificationResult(
                decision_id=workflow_result.decision_id,
                verified=True,
                discrepancies=[],
                details={"note": "Procurement verification not implemented"}
            )
        else:
            await self._write_audit_entry(
                decision_id=workflow_result.decision_id,
                outcome="failure",
                detail=f"Procurement verification skipped because workflow status is {workflow_result.status}",
                payload_snapshot={"workflow_status": workflow_result.status},
            )
            return VerificationResult(
                decision_id=workflow_result.decision_id,
                verified=False,
                discrepancies=[f"Workflow status is {workflow_result.status}"]
            )
    
    async def generate_summary(
        self,
        meeting: NormalizedMeeting,
        workflow_results: List[WorkflowResult],
        verification_results: List[VerificationResult]
    ) -> str:
        """
        Generate Slack summary message.
        Include status icons, artifact links, follow-up items.
        
        Args:
            meeting: Meeting that was processed
            workflow_results: Results from workflow execution
            verification_results: Results from verification
            
        Returns:
            Formatted summary text for Slack
        """
        logger.info(f"Generating summary for meeting {meeting.meeting_id}")
        
        # Count statuses
        success_count = len([r for r in workflow_results if r.status == "success"])
        failed_count = len([r for r in workflow_results if r.status == "failed"])
        pending_count = len([r for r in workflow_results if r.status == "pending_retry"])
        
        # Build summary
        summary_lines = [
            f"📊 *Meeting Summary: {meeting.title}*",
            f"_Date: {meeting.date.isoformat()}_",
            "",
            f"✅ {success_count} decisions executed successfully",
            f"❌ {failed_count} decisions failed",
            f"⏳ {pending_count} decisions pending retry",
            ""
        ]
        
        # Add completed actions
        if success_count > 0:
            summary_lines.append("*Completed Actions:*")
            for result in workflow_results:
                if result.status == "success":
                    # Find corresponding verification result
                    verification = next(
                        (v for v in verification_results if v.decision_id == result.decision_id),
                        None
                    )
                    
                    status_icon = "✅" if verification and verification.verified else "⚠️"
                    summary_lines.append(f"{status_icon} Decision {result.decision_id}")
                    
                    # Add artifact links
                    for link in result.artifact_links:
                        summary_lines.append(f"   🔗 {link}")
                    
                    # Add discrepancies if any
                    if verification and verification.discrepancies:
                        for discrepancy in verification.discrepancies:
                            summary_lines.append(f"   ⚠️ {discrepancy}")
            
            summary_lines.append("")
        
        # Add failed actions
        if failed_count > 0:
            summary_lines.append("*Failed Actions:*")
            for result in workflow_results:
                if result.status == "failed":
                    summary_lines.append(f"❌ Decision {result.decision_id}")
                    if result.error_message:
                        summary_lines.append(f"   Error: {result.error_message}")
            
            summary_lines.append("")
        
        # Add pending actions
        if pending_count > 0:
            summary_lines.append("*Pending Actions:*")
            for result in workflow_results:
                if result.status == "pending_retry":
                    summary_lines.append(f"⏳ Decision {result.decision_id}")
            
            summary_lines.append("")
        
        # Add footer
        summary_lines.append(f"_Processed {len(workflow_results)} total decisions_")
        
        summary_text = "\n".join(summary_lines)
        
        return summary_text

    async def _resolve_meeting_id(self, decision_id: Optional[str]) -> Optional[str]:
        """Resolve a decision back to its parent meeting for meeting-linked audit rows."""
        if not decision_id:
            return None

        result = await self.db_session.execute(
            select(DecisionModel.meeting_id).where(DecisionModel.id == decision_id)
        )
        return result.scalar_one_or_none()
    
    async def _write_audit_entry(
        self,
        decision_id: Optional[str],
        outcome: str,
        detail: str,
        payload_snapshot: Optional[Dict[str, Any]] = None,
        meeting_id: Optional[str] = None,
    ) -> None:
        """
        Write audit entry for verification action.
        
        Args:
            meeting_id: Meeting identifier (optional)
            decision_id: Decision identifier (optional)
            outcome: Outcome status (success, failure, pending)
            detail: Detailed description of the action
            payload_snapshot: Optional snapshot of verification result
        """
        if meeting_id is None and decision_id:
            meeting_id = await self._resolve_meeting_id(decision_id)

        audit_entry = AuditEntry(
            meeting_id=meeting_id,
            decision_id=decision_id,
            agent="VerificationAgent",
            step="verify_execution",
            outcome=outcome,
            detail=detail,
            payload_snapshot=payload_snapshot,
            created_at=datetime.utcnow()
        )
        
        self.db_session.add(audit_entry)
        await self.db_session.commit()
        
        logger.debug(f"Audit entry written: {outcome} - {detail}")
