"""
Approval timeout reminder system.
Sends reminder notifications for pending approvals that exceed timeout threshold.
"""
import asyncio
import logging
from datetime import datetime, timedelta
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.database import get_db_session
from db.models import Decision, AuditEntry
from integrations.slack import SlackApprovalGate


logger = logging.getLogger(__name__)


class ApprovalReminderService:
    """
    Service for monitoring and sending approval timeout reminders.
    """
    
    def __init__(
        self,
        slack_gate: SlackApprovalGate,
        timeout_hours: int = 24,
        reminder_interval_hours: int = 12,
        check_interval_seconds: int = 300  # 5 minutes
    ):
        """
        Initialize approval reminder service.
        
        Args:
            slack_gate: Slack approval gate for sending reminders
            timeout_hours: Hours before first reminder (default 24)
            reminder_interval_hours: Hours between reminders (default 12)
            check_interval_seconds: Seconds between checks (default 300)
        """
        self.slack_gate = slack_gate
        self.timeout_hours = timeout_hours
        self.reminder_interval_hours = reminder_interval_hours
        self.check_interval_seconds = check_interval_seconds
        self._running = False
        self._task: Optional[asyncio.Task] = None
        
        logger.info(
            f"ApprovalReminderService initialized: "
            f"timeout={timeout_hours}h, interval={reminder_interval_hours}h"
        )
    
    async def start(self) -> None:
        """Start the reminder service background task."""
        if self._running:
            logger.warning("Reminder service already running")
            return
        
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("Approval reminder service started")
    
    async def stop(self) -> None:
        """Stop the reminder service background task."""
        if not self._running:
            return
        
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        
        logger.info("Approval reminder service stopped")
    
    async def _run_loop(self) -> None:
        """Main loop for checking and sending reminders."""
        while self._running:
            try:
                await self._check_and_send_reminders()
            except Exception as e:
                logger.error(f"Error in reminder loop: {e}")
            
            # Wait before next check
            await asyncio.sleep(self.check_interval_seconds)
    
    async def _check_and_send_reminders(self) -> None:
        """Check for pending approvals and send reminders if needed."""
        async with get_db_session() as session:
            # Find pending approvals
            pending_decisions = await self._get_pending_approvals(session)
            
            if not pending_decisions:
                logger.debug("No pending approvals found")
                return
            
            logger.info(f"Found {len(pending_decisions)} pending approvals")
            
            # Check each decision for timeout
            for decision in pending_decisions:
                try:
                    await self._process_decision_reminder(decision, session)
                except Exception as e:
                    logger.error(f"Error processing reminder for decision {decision.id}: {e}")
            
            await session.commit()
    
    async def _get_pending_approvals(
        self,
        session: AsyncSession
    ) -> List[Decision]:
        """
        Get all decisions with pending approval status.
        
        Args:
            session: Database session
            
        Returns:
            List of pending decisions
        """
        result = await session.execute(
            select(Decision)
            .where(Decision.approval_status == "pending")
            .order_by(Decision.created_at)
        )
        return list(result.scalars().all())
    
    async def _process_decision_reminder(
        self,
        decision: Decision,
        session: AsyncSession
    ) -> None:
        """
        Process a single decision for reminder.
        
        Args:
            decision: Decision to check
            session: Database session
        """
        # Calculate time since decision was created
        time_pending = datetime.utcnow() - decision.created_at
        hours_pending = time_pending.total_seconds() / 3600
        
        # Check if timeout threshold reached
        if hours_pending < self.timeout_hours:
            return
        
        # Check if we already sent a reminder recently
        last_reminder = await self._get_last_reminder_time(decision.id, session)
        
        if last_reminder:
            time_since_reminder = datetime.utcnow() - last_reminder
            hours_since_reminder = time_since_reminder.total_seconds() / 3600
            
            if hours_since_reminder < self.reminder_interval_hours:
                logger.debug(
                    f"Skipping reminder for {decision.id} "
                    f"(last reminder {hours_since_reminder:.1f}h ago)"
                )
                return
        
        # Send reminder
        await self._send_reminder(decision, session, hours_pending)
    
    async def _get_last_reminder_time(
        self,
        decision_id: str,
        session: AsyncSession
    ) -> Optional[datetime]:
        """
        Get timestamp of last reminder sent for a decision.
        
        Args:
            decision_id: Decision identifier
            session: Database session
            
        Returns:
            Timestamp of last reminder or None
        """
        result = await session.execute(
            select(AuditEntry)
            .where(AuditEntry.decision_id == decision_id)
            .where(AuditEntry.agent == "ApprovalReminderService")
            .where(AuditEntry.step == "send_reminder")
            .order_by(AuditEntry.created_at.desc())
            .limit(1)
        )
        entry = result.scalar_one_or_none()
        
        return entry.created_at if entry else None
    
    async def _send_reminder(
        self,
        decision: Decision,
        session: AsyncSession,
        hours_pending: float
    ) -> None:
        """
        Send reminder notification for pending approval.
        
        Args:
            decision: Decision requiring approval
            session: Database session
            hours_pending: Hours the decision has been pending
        """
        logger.info(
            f"Sending reminder for decision {decision.id} "
            f"(pending {hours_pending:.1f}h)"
        )
        
        try:
            # Build reminder message
            blocks = self._build_reminder_blocks(decision, hours_pending)
            
            # Send to Slack
            response = await self.slack_gate.app.client.chat_postMessage(
                channel=self.slack_gate.approval_channel,
                blocks=blocks,
                text=f"⏰ Reminder: Approval pending for {decision.description}"
            )
            
            # Write audit entry
            audit_entry = AuditEntry(
                decision_id=decision.id,
                meeting_id=decision.meeting_id,
                agent="ApprovalReminderService",
                step="send_reminder",
                outcome="success",
                detail=f"Reminder sent after {hours_pending:.1f} hours pending",
                api_call="chat.postMessage",
                http_status=200,
                payload_snapshot={
                    "hours_pending": hours_pending,
                    "message_ts": response["ts"]
                }
            )
            session.add(audit_entry)
            
            logger.info(f"Reminder sent successfully for decision {decision.id}")
            
        except Exception as e:
            logger.error(f"Failed to send reminder for decision {decision.id}: {e}")
            
            # Write failure audit entry
            audit_entry = AuditEntry(
                decision_id=decision.id,
                meeting_id=decision.meeting_id,
                agent="ApprovalReminderService",
                step="send_reminder",
                outcome="failure",
                detail=f"Failed to send reminder: {str(e)}"
            )
            session.add(audit_entry)
    
    def _build_reminder_blocks(
        self,
        decision: Decision,
        hours_pending: float
    ) -> List[dict]:
        """
        Build Slack Block Kit message for reminder.
        
        Args:
            decision: Decision requiring approval
            hours_pending: Hours the decision has been pending
            
        Returns:
            List of Block Kit blocks
        """
        # Calculate deadline urgency
        if decision.deadline:
            days_until_deadline = (decision.deadline - datetime.utcnow().date()).days
            urgency_text = ""
            
            if days_until_deadline < 0:
                urgency_text = f" ⚠️ *OVERDUE by {abs(days_until_deadline)} days*"
            elif days_until_deadline == 0:
                urgency_text = " ⚠️ *DUE TODAY*"
            elif days_until_deadline <= 2:
                urgency_text = f" ⚠️ *Due in {days_until_deadline} days*"
        else:
            urgency_text = ""
        
        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": "⏰ Approval Reminder"
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"*This approval has been pending for {hours_pending:.1f} hours*\n\n"
                        f"*Decision:* {decision.description}{urgency_text}"
                    )
                }
            },
            {
                "type": "section",
                "fields": [
                    {
                        "type": "mrkdwn",
                        "text": f"*Owner:* {decision.owner}"
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*Deadline:* {decision.deadline.isoformat() if decision.deadline else 'Not set'}"
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*Workflow:* {decision.workflow_type or 'Not classified'}"
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*Decision ID:* {decision.id}"
                    }
                ]
            },
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"💬 _{decision.raw_quote}_"
                    }
                ]
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "Please review and approve/reject this decision."
                }
            }
        ]
        
        return blocks


# Global service instance
_reminder_service: Optional[ApprovalReminderService] = None


async def start_approval_reminder_service(
    slack_gate: SlackApprovalGate,
    timeout_hours: int = 24,
    reminder_interval_hours: int = 12
) -> ApprovalReminderService:
    """
    Start the global approval reminder service.
    
    Args:
        slack_gate: Slack approval gate
        timeout_hours: Hours before first reminder
        reminder_interval_hours: Hours between reminders
        
    Returns:
        ApprovalReminderService instance
    """
    global _reminder_service
    
    if _reminder_service:
        logger.warning("Approval reminder service already started")
        return _reminder_service
    
    _reminder_service = ApprovalReminderService(
        slack_gate=slack_gate,
        timeout_hours=timeout_hours,
        reminder_interval_hours=reminder_interval_hours
    )
    
    await _reminder_service.start()
    return _reminder_service


async def stop_approval_reminder_service() -> None:
    """Stop the global approval reminder service."""
    global _reminder_service
    
    if _reminder_service:
        await _reminder_service.stop()
        _reminder_service = None
