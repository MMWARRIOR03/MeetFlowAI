"""
Slack integration for approval gate using Block Kit messages.
Handles sending approval requests and processing button interactions.
"""
import os
import hmac
import hashlib
import json
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional
from slack_bolt.async_app import AsyncApp
from slack_sdk.errors import SlackApiError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from db.models import Decision, AuditEntry
from schemas.base import WorkflowType

logger = logging.getLogger(__name__)


class SlackApprovalGate:
    """
    Slack approval gate with Block Kit interactive messages.
    Sends approval requests and handles button interactions.
    """
    
    def __init__(
        self,
        bot_token: str,
        signing_secret: str,
        approval_channel: str
    ):
        """
        Initialize Slack approval gate.
        
        Args:
            bot_token: Slack bot token
            signing_secret: Slack signing secret for request verification
            approval_channel: Default channel ID for approval messages
        """
        self.app = AsyncApp(token=bot_token, signing_secret=signing_secret)
        self.bot_token = bot_token
        self.signing_secret = signing_secret
        self.approval_channel = approval_channel
        
        logger.info(f"SlackApprovalGate initialized with channel {approval_channel}")
    
    async def send_approval_message(
        self,
        decisions: List[Decision],
        db_session: AsyncSession,
        channel: Optional[str] = None
    ) -> str:
        """
        Send approval request to Slack channel.
        
        Args:
            decisions: List of decisions requiring approval
            db_session: Database session for audit logging
            channel: Slack channel ID (uses default if not provided)
            
        Returns:
            Message timestamp for tracking
            
        Raises:
            SlackApiError: If message sending fails
        """
        target_channel = channel or self.approval_channel
        
        try:
            # Build Block Kit message for each decision
            for decision in decisions:
                blocks = self._build_approval_blocks(decision)
                
                # Send message to Slack
                response = await self.app.client.chat_postMessage(
                    channel=target_channel,
                    blocks=blocks,
                    text=f"Approval required: {decision.description}"  # Fallback text
                )
                
                message_ts = response["ts"]
                
                # Write audit entry for approval request sent
                audit_entry = AuditEntry(
                    decision_id=decision.id,
                    meeting_id=decision.meeting_id,
                    agent="SlackApprovalGate",
                    step="send_approval_message",
                    outcome="success",
                    detail=f"Approval message sent to channel {target_channel}",
                    api_call="chat.postMessage",
                    http_status=200,
                    payload_snapshot={
                        "channel": target_channel,
                        "message_ts": message_ts,
                        "decision_id": decision.id
                    }
                )
                db_session.add(audit_entry)
                
                logger.info(f"Sent approval message for decision {decision.id} to {target_channel}")
            
            await db_session.commit()
            return message_ts
            
        except SlackApiError as e:
            logger.error(f"Failed to send approval message: {e.response['error']}")
            
            # Write audit entry for failure
            audit_entry = AuditEntry(
                decision_id=decisions[0].id if decisions else None,
                meeting_id=decisions[0].meeting_id if decisions else None,
                agent="SlackApprovalGate",
                step="send_approval_message",
                outcome="failure",
                detail=f"Failed to send approval message: {e.response['error']}",
                api_call="chat.postMessage",
                http_status=e.response.status_code if hasattr(e.response, 'status_code') else None
            )
            db_session.add(audit_entry)
            await db_session.commit()
            
            raise
    
    def _build_approval_blocks(self, decision: Decision) -> List[Dict[str, Any]]:
        """
        Build Block Kit message structure for approval request.
        
        Args:
            decision: Decision requiring approval
            
        Returns:
            List of Block Kit blocks
        """
        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": "🔔 Approval Required"
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Decision:* {decision.description}"
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
                        "text": f"*Deadline:* {decision.deadline.isoformat()}"
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
            }
        ]
        
        # Add workflow-specific parameters if available
        if decision.parameters:
            param_text = self._format_parameters(decision.parameters, decision.workflow_type)
            if param_text:
                blocks.append({
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*Parameters:*\n{param_text}"
                    }
                })
        
        # Add raw quote from transcript
        blocks.append({
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"💬 _{decision.raw_quote}_"
                }
            ]
        })
        
        # Add action buttons
        blocks.append({
            "type": "actions",
            "block_id": f"approval_actions_{decision.id}",
            "elements": [
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "✅ Approve"
                    },
                    "style": "primary",
                    "value": json.dumps({"decision_id": decision.id, "action": "approve"}),
                    "action_id": "approve_decision"
                },
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "❌ Reject"
                    },
                    "style": "danger",
                    "value": json.dumps({"decision_id": decision.id, "action": "reject"}),
                    "action_id": "reject_decision"
                },
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "❓ Ask"
                    },
                    "value": json.dumps({"decision_id": decision.id, "action": "ask"}),
                    "action_id": "ask_clarification"
                }
            ]
        })
        
        # Add divider
        blocks.append({"type": "divider"})
        
        return blocks
    
    def _format_parameters(self, parameters: Dict[str, Any], workflow_type: Optional[str]) -> str:
        """
        Format workflow parameters for display.
        
        Args:
            parameters: Workflow parameters
            workflow_type: Type of workflow
            
        Returns:
            Formatted parameter string
        """
        if not parameters:
            return ""
        
        lines = []
        
        # Format based on workflow type
        if workflow_type == WorkflowType.JIRA_CREATE.value:
            lines.append(f"• Project: {parameters.get('project_key', 'N/A')}")
            lines.append(f"• Type: {parameters.get('issue_type', 'N/A')}")
            lines.append(f"• Summary: {parameters.get('summary', 'N/A')}")
            if parameters.get('assignee'):
                lines.append(f"• Assignee: {parameters['assignee']}")
            if parameters.get('priority'):
                lines.append(f"• Priority: {parameters['priority']}")
                
        elif workflow_type == WorkflowType.JIRA_UPDATE.value:
            lines.append(f"• Issue: {parameters.get('issue_key', 'N/A')}")
            if parameters.get('fields_to_update'):
                lines.append(f"• Fields: {', '.join(parameters['fields_to_update'])}")
                
        elif workflow_type == WorkflowType.HR_HIRING.value:
            lines.append(f"• Candidate: {parameters.get('candidate_name', 'N/A')}")
            lines.append(f"• Position: {parameters.get('position', 'N/A')}")
            lines.append(f"• Department: {parameters.get('department', 'N/A')}")
            if parameters.get('start_date'):
                lines.append(f"• Start Date: {parameters['start_date']}")
                
        elif workflow_type == WorkflowType.PROCUREMENT_REQUEST.value:
            lines.append(f"• Item: {parameters.get('item_description', 'N/A')}")
            lines.append(f"• Quantity: {parameters.get('quantity', 'N/A')}")
            estimated_cost = parameters.get("estimated_cost")
            if estimated_cost in (None, ""):
                lines.append("• Cost: N/A")
            else:
                try:
                    lines.append(f"• Cost: ${float(estimated_cost):,.2f}")
                except (TypeError, ValueError):
                    lines.append(f"• Cost: {estimated_cost}")
            if parameters.get('vendor'):
                lines.append(f"• Vendor: {parameters['vendor']}")
        else:
            # Generic parameter display
            for key, value in parameters.items():
                lines.append(f"• {key}: {value}")
        
        return "\n".join(lines)
    
    async def handle_interaction(
        self,
        payload: Dict[str, Any],
        db_session: AsyncSession
    ) -> None:
        """
        Handle button clicks (Approve/Reject/Ask).
        Updates database with approval status and writes audit entry.
        
        Args:
            payload: Slack interaction payload
            db_session: Database session
            
        Raises:
            ValueError: If decision not found or invalid action
        """
        try:
            # Extract action data from payload
            actions = payload.get("actions", [])
            if not actions:
                raise ValueError("No actions in payload")
            
            action = actions[0]
            action_id = action.get("action_id")
            value_data = json.loads(action.get("value", "{}"))
            decision_id = value_data.get("decision_id")
            action_type = value_data.get("action")
            
            # Get user info
            user_id = payload.get("user", {}).get("id")
            user_name = payload.get("user", {}).get("username", user_id)
            
            logger.info(f"Processing {action_type} action for decision {decision_id} by {user_name}")
            
            # Fetch decision from database
            result = await db_session.execute(
                select(Decision).where(Decision.id == decision_id)
            )
            decision = result.scalar_one_or_none()
            
            if not decision:
                raise ValueError(f"Decision {decision_id} not found")
            
            # Update approval status based on action
            if action_type == "approve":
                decision.approval_status = "approved"
                outcome_detail = f"Decision approved by {user_name}"
                response_text = f"✅ Decision approved by <@{user_id}>"
                
            elif action_type == "reject":
                decision.approval_status = "rejected"
                outcome_detail = f"Decision rejected by {user_name}"
                response_text = f"❌ Decision rejected by <@{user_id}>"
                
            elif action_type == "ask":
                decision.approval_status = "clarification_requested"
                outcome_detail = f"Clarification requested by {user_name}"
                response_text = f"❓ Clarification requested by <@{user_id}> - owner {decision.owner} will be notified"
                
            else:
                raise ValueError(f"Unknown action type: {action_type}")
            
            # Write audit entry
            audit_entry = AuditEntry(
                decision_id=decision.id,
                meeting_id=decision.meeting_id,
                agent="SlackApprovalGate",
                step="handle_interaction",
                outcome="success",
                detail=outcome_detail,
                api_call="interaction_callback",
                payload_snapshot={
                    "action": action_type,
                    "approver": user_name,
                    "approver_id": user_id,
                    "timestamp": datetime.utcnow().isoformat()
                }
            )
            db_session.add(audit_entry)
            
            await db_session.commit()
            
            # Update Slack message to show action taken
            await self._update_message_with_response(payload, response_text)
            
            logger.info(f"Decision {decision_id} status updated to {decision.approval_status}")
            
        except Exception as e:
            logger.error(f"Error handling interaction: {str(e)}")
            
            # Write audit entry for failure
            audit_entry = AuditEntry(
                decision_id=decision_id if 'decision_id' in locals() else None,
                agent="SlackApprovalGate",
                step="handle_interaction",
                outcome="failure",
                detail=f"Failed to handle interaction: {str(e)}"
            )
            db_session.add(audit_entry)
            await db_session.commit()
            
            raise
    
    async def _update_message_with_response(
        self,
        payload: Dict[str, Any],
        response_text: str
    ) -> None:
        """
        Update the original message to show the action taken.
        
        Args:
            payload: Slack interaction payload
            response_text: Text to display in the updated message
        """
        try:
            channel = payload.get("channel", {}).get("id")
            message_ts = payload.get("message", {}).get("ts")
            original_blocks = payload.get("message", {}).get("blocks", [])
            
            # Remove action buttons and add response
            updated_blocks = [
                block for block in original_blocks 
                if block.get("type") != "actions"
            ]
            
            # Add response section
            updated_blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": response_text
                }
            })
            
            await self.app.client.chat_update(
                channel=channel,
                ts=message_ts,
                blocks=updated_blocks,
                text=response_text
            )
            
        except SlackApiError as e:
            logger.error(f"Failed to update message: {e.response['error']}")
            # Don't raise - message update is not critical
    
    @staticmethod
    def verify_slack_signature(
        signing_secret: str,
        timestamp: str,
        body: str,
        signature: str
    ) -> bool:
        """
        Verify Slack request signature for security.
        
        Args:
            signing_secret: Slack signing secret
            timestamp: Request timestamp from X-Slack-Request-Timestamp header
            body: Raw request body
            signature: Signature from X-Slack-Signature header
            
        Returns:
            True if signature is valid, False otherwise
        """
        # Prevent replay attacks - reject requests older than 5 minutes
        current_timestamp = int(datetime.utcnow().timestamp())
        if abs(current_timestamp - int(timestamp)) > 60 * 5:
            logger.warning("Request timestamp too old - possible replay attack")
            return False
        
        # Compute expected signature
        sig_basestring = f"v0:{timestamp}:{body}"
        expected_signature = 'v0=' + hmac.new(
            signing_secret.encode(),
            sig_basestring.encode(),
            hashlib.sha256
        ).hexdigest()
        
        # Compare signatures
        return hmac.compare_digest(expected_signature, signature)


def create_slack_approval_gate() -> SlackApprovalGate:
    """
    Factory function to create SlackApprovalGate from environment variables.
    
    Returns:
        Configured SlackApprovalGate instance
        
    Raises:
        ValueError: If required environment variables are missing
    """
    bot_token = os.getenv("SLACK_BOT_TOKEN")
    signing_secret = os.getenv("SLACK_SIGNING_SECRET")
    approval_channel = os.getenv("SLACK_APPROVAL_CHANNEL")
    
    if not bot_token:
        raise ValueError("SLACK_BOT_TOKEN environment variable is required")
    if not signing_secret:
        raise ValueError("SLACK_SIGNING_SECRET environment variable is required")
    if not approval_channel:
        raise ValueError("SLACK_APPROVAL_CHANNEL environment variable is required")
    
    return SlackApprovalGate(
        bot_token=bot_token,
        signing_secret=signing_secret,
        approval_channel=approval_channel
    )
