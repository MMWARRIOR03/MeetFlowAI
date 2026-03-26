"""
FastAPI endpoints for Slack interactions.
Handles interactive message callbacks from Slack.
"""
import logging
from fastapi import APIRouter, Request, HTTPException, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from db.database import get_db
from integrations.slack import SlackApprovalGate, create_slack_approval_gate

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/slack", tags=["slack"])


# Dependency to get SlackApprovalGate instance
_slack_gate_instance = None


def get_slack_gate() -> SlackApprovalGate:
    """
    Get or create SlackApprovalGate singleton instance.
    
    Returns:
        SlackApprovalGate instance
    """
    global _slack_gate_instance
    if _slack_gate_instance is None:
        _slack_gate_instance = create_slack_approval_gate()
    return _slack_gate_instance


@router.post("/interactions")
async def handle_slack_interaction(
    request: Request,
    db_session: AsyncSession = Depends(get_db)
):
    """
    Handle Slack interactive message callbacks.
    Verifies signature and routes to SlackApprovalGate.
    
    Args:
        request: FastAPI request object
        db_session: Database session
        
    Returns:
        200 OK response for Slack
        
    Raises:
        HTTPException: If signature verification fails or processing error occurs
    """
    try:
        # Get headers and body
        timestamp = request.headers.get("X-Slack-Request-Timestamp", "")
        signature = request.headers.get("X-Slack-Signature", "")
        body = await request.body()
        body_str = body.decode("utf-8")
        
        # Get Slack gate instance
        slack_gate = get_slack_gate()
        
        # Verify Slack signature
        if not SlackApprovalGate.verify_slack_signature(
            slack_gate.signing_secret,
            timestamp,
            body_str,
            signature
        ):
            logger.warning("Invalid Slack signature - possible unauthorized request")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid Slack signature"
            )
        
        # Parse form data (Slack sends as application/x-www-form-urlencoded)
        form_data = await request.form()
        payload_str = form_data.get("payload")
        
        if not payload_str:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Missing payload in request"
            )
        
        # Parse JSON payload
        import json
        payload = json.loads(payload_str)
        
        logger.info(f"Received Slack interaction: {payload.get('type')}")
        
        # Handle interaction
        await slack_gate.handle_interaction(payload, db_session)
        
        # Return 200 OK to Slack
        return {"ok": True}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error processing Slack interaction: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to process interaction: {str(e)}"
        )
