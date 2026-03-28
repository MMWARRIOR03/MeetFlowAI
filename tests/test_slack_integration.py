"""
Integration tests for Slack approval gate.
"""
import pytest
import json
import hmac
import hashlib
import time
from urllib.parse import urlencode
from datetime import date, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi.testclient import TestClient

import api.slack as slack_api
from integrations.slack import SlackApprovalGate
from db.models import Decision, AuditEntry
from schemas.base import WorkflowType
from main import app


@pytest.fixture
def mock_slack_app():
    """Mock Slack app."""
    with patch('integrations.slack.AsyncApp') as mock_app:
        mock_client = AsyncMock()
        mock_app.return_value.client = mock_client
        yield mock_app


@pytest.fixture
def slack_gate(mock_slack_app):
    """Create SlackApprovalGate instance with mocked Slack app."""
    return SlackApprovalGate(
        bot_token="xoxb-test-token",
        signing_secret="test-secret",
        approval_channel="C123456"
    )


@pytest.fixture
def sample_decision():
    """Create sample decision for testing."""
    return Decision(
        id="dec_001",
        meeting_id="meeting_001",
        description="Update AWS spend limit",
        owner="Mrinal",
        deadline=date(2026, 3, 26),
        workflow_type=WorkflowType.PROCUREMENT_REQUEST.value,
        approval_status="pending",
        auto_trigger=False,
        confidence=0.95,
        raw_quote="Let's raise the AWS spend limit by 40k for the quarter",
        parameters={
            "item_description": "AWS cloud services",
            "quantity": 1,
            "estimated_cost": 40000,
            "vendor": "Amazon Web Services"
        }
    )


@pytest.fixture
def client():
    return TestClient(app)


@pytest.mark.asyncio
async def test_send_approval_message(slack_gate, sample_decision, mock_slack_app):
    """Test sending approval message to Slack."""
    # Mock database session
    db_session = AsyncMock(spec=AsyncSession)
    
    # Mock Slack API response
    slack_gate.app.client.chat_postMessage.return_value = {
        "ok": True,
        "ts": "1234567890.123456"
    }
    
    # Send approval message
    message_ts = await slack_gate.send_approval_message(
        decisions=[sample_decision],
        db_session=db_session
    )
    
    # Verify message was sent
    assert message_ts == "1234567890.123456"
    slack_gate.app.client.chat_postMessage.assert_called_once()
    
    # Verify audit entry was created
    assert db_session.add.called
    assert db_session.commit.called


def test_build_approval_blocks_handles_missing_procurement_cost(slack_gate, sample_decision):
    """Procurement Slack blocks should tolerate a missing estimated_cost."""
    sample_decision.parameters["estimated_cost"] = None

    blocks = slack_gate._build_approval_blocks(sample_decision)

    parameter_block = next(
        block for block in blocks
        if block["type"] == "section"
        and "text" in block
        and "*Parameters:*" in block["text"]["text"]
    )

    assert "• Cost: N/A" in parameter_block["text"]["text"]


@pytest.mark.asyncio
async def test_build_approval_blocks(slack_gate, sample_decision):
    """Test Block Kit message structure."""
    blocks = slack_gate._build_approval_blocks(sample_decision)
    
    # Verify block structure
    assert len(blocks) > 0
    assert blocks[0]["type"] == "header"
    assert "Approval Required" in blocks[0]["text"]["text"]
    
    # Find actions block
    actions_block = next((b for b in blocks if b["type"] == "actions"), None)
    assert actions_block is not None
    assert len(actions_block["elements"]) == 3  # Approve, Reject, Ask
    
    # Verify button values contain decision_id
    for button in actions_block["elements"]:
        value_data = json.loads(button["value"])
        assert value_data["decision_id"] == "dec_001"
        assert value_data["action"] in ["approve", "reject", "ask"]


@pytest.mark.asyncio
async def test_handle_interaction_approve(slack_gate):
    """Test handling approve button click."""
    # Mock database session
    db_session = AsyncMock(spec=AsyncSession)
    
    # Create mock decision
    mock_decision = MagicMock(spec=Decision)
    mock_decision.id = "dec_001"
    mock_decision.meeting_id = "meeting_001"
    mock_decision.owner = "Mrinal"
    mock_decision.approval_status = "pending"
    
    # Mock database query
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_decision
    db_session.execute = AsyncMock(return_value=mock_result)
    
    # Mock Slack message update
    slack_gate.app.client.chat_update = AsyncMock()
    
    # Create interaction payload
    payload = {
        "type": "block_actions",
        "user": {
            "id": "U123456",
            "username": "john.doe"
        },
        "actions": [
            {
                "action_id": "approve_decision",
                "value": json.dumps({"decision_id": "dec_001", "action": "approve"})
            }
        ],
        "channel": {"id": "C123456"},
        "message": {
            "ts": "1234567890.123456",
            "blocks": []
        }
    }
    
    # Handle interaction
    await slack_gate.handle_interaction(payload, db_session)
    
    # Verify approval status was updated
    assert mock_decision.approval_status == "approved"
    
    # Verify audit entry was created
    assert db_session.add.called
    assert db_session.commit.called


@pytest.mark.asyncio
async def test_handle_interaction_reject(slack_gate):
    """Test handling reject button click."""
    # Mock database session
    db_session = AsyncMock(spec=AsyncSession)
    
    # Create mock decision
    mock_decision = MagicMock(spec=Decision)
    mock_decision.id = "dec_002"
    mock_decision.meeting_id = "meeting_001"
    mock_decision.approval_status = "pending"
    
    # Mock database query
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_decision
    db_session.execute = AsyncMock(return_value=mock_result)
    
    # Mock Slack message update
    slack_gate.app.client.chat_update = AsyncMock()
    
    # Create interaction payload
    payload = {
        "type": "block_actions",
        "user": {
            "id": "U123456",
            "username": "jane.smith"
        },
        "actions": [
            {
                "action_id": "reject_decision",
                "value": json.dumps({"decision_id": "dec_002", "action": "reject"})
            }
        ],
        "channel": {"id": "C123456"},
        "message": {
            "ts": "1234567890.123456",
            "blocks": []
        }
    }
    
    # Handle interaction
    await slack_gate.handle_interaction(payload, db_session)
    
    # Verify approval status was updated
    assert mock_decision.approval_status == "rejected"


@pytest.mark.asyncio
async def test_handle_interaction_ask(slack_gate):
    """Test handling ask clarification button click."""
    # Mock database session
    db_session = AsyncMock(spec=AsyncSession)
    
    # Create mock decision
    mock_decision = MagicMock(spec=Decision)
    mock_decision.id = "dec_003"
    mock_decision.meeting_id = "meeting_001"
    mock_decision.owner = "Priya"
    mock_decision.approval_status = "pending"
    
    # Mock database query
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_decision
    db_session.execute = AsyncMock(return_value=mock_result)
    
    # Mock Slack message update
    slack_gate.app.client.chat_update = AsyncMock()
    
    # Create interaction payload
    payload = {
        "type": "block_actions",
        "user": {
            "id": "U123456",
            "username": "approver"
        },
        "actions": [
            {
                "action_id": "ask_clarification",
                "value": json.dumps({"decision_id": "dec_003", "action": "ask"})
            }
        ],
        "channel": {"id": "C123456"},
        "message": {
            "ts": "1234567890.123456",
            "blocks": []
        }
    }
    
    # Handle interaction
    await slack_gate.handle_interaction(payload, db_session)
    
    # Verify approval status was updated
    assert mock_decision.approval_status == "clarification_requested"


def test_verify_slack_signature_valid():
    """Test Slack signature verification with valid signature."""
    signing_secret = "test_secret"
    timestamp = str(int(datetime.utcnow().timestamp()))
    body = "payload=test"
    
    # Generate valid signature
    import hmac
    import hashlib
    sig_basestring = f"v0:{timestamp}:{body}"
    signature = 'v0=' + hmac.new(
        signing_secret.encode(),
        sig_basestring.encode(),
        hashlib.sha256
    ).hexdigest()
    
    # Verify
    is_valid = SlackApprovalGate.verify_slack_signature(
        signing_secret,
        timestamp,
        body,
        signature
    )
    
    assert is_valid is True


def test_verify_slack_signature_invalid():
    """Test Slack signature verification with invalid signature."""
    signing_secret = "test_secret"
    timestamp = str(int(datetime.utcnow().timestamp()))
    body = "payload=test"
    signature = "v0=invalid_signature"
    
    # Verify
    is_valid = SlackApprovalGate.verify_slack_signature(
        signing_secret,
        timestamp,
        body,
        signature
    )
    
    assert is_valid is False


def test_verify_slack_signature_old_timestamp():
    """Test Slack signature verification rejects old timestamps."""
    signing_secret = "test_secret"
    timestamp = str(int(datetime.utcnow().timestamp()) - 400)  # 6+ minutes old
    body = "payload=test"
    
    # Generate valid signature
    import hmac
    import hashlib
    sig_basestring = f"v0:{timestamp}:{body}"
    signature = 'v0=' + hmac.new(
        signing_secret.encode(),
        sig_basestring.encode(),
        hashlib.sha256
    ).hexdigest()
    
    # Verify - should fail due to old timestamp
    is_valid = SlackApprovalGate.verify_slack_signature(
        signing_secret,
        timestamp,
        body,
        signature
    )
    
    assert is_valid is False


@patch("api.slack.SlackApprovalGate.verify_slack_signature", return_value=True)
@patch("api.slack.get_slack_gate")
def test_slack_interactions_endpoint_parses_urlencoded_payload(
    mock_get_slack_gate,
    mock_verify_signature,
    client,
):
    fake_gate = MagicMock()
    fake_gate.signing_secret = "test-secret"
    fake_gate.handle_interaction = AsyncMock()
    mock_get_slack_gate.return_value = fake_gate

    fake_db = AsyncMock(spec=AsyncSession)

    async def override_get_db():
        yield fake_db

    app.dependency_overrides[slack_api.get_db] = override_get_db

    payload = {
        "type": "block_actions",
        "user": {"id": "U123", "username": "approver"},
        "actions": [
            {
                "action_id": "approve_decision",
                "value": json.dumps({"decision_id": "dec_001", "action": "approve"}),
            }
        ],
        "channel": {"id": "C123456"},
        "message": {"ts": "1234567890.123456", "blocks": []},
    }
    body = urlencode({"payload": json.dumps(payload)})
    response = client.post(
        "/slack/interactions",
        content=body,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "X-Slack-Request-Timestamp": str(int(time.time())),
            "X-Slack-Signature": "v0=test",
        },
    )

    app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    mock_verify_signature.assert_called_once()
    fake_gate.handle_interaction.assert_awaited_once()
