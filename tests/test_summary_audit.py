"""
Focused tests for summary-node audit behavior.
"""
from contextlib import asynccontextmanager
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from orchestrator.nodes import send_summary_node
from schemas.base import NormalizedMeeting


@pytest.mark.asyncio
async def test_send_summary_node_writes_summary_agent_audit():
    state = {
        "meeting_id": "meeting_123",
        "meeting": NormalizedMeeting(
            meeting_id="meeting_123",
            title="Q2 Planning",
            date=date(2026, 3, 20),
            participants=["Alice"],
            transcript=[],
        ),
        "workflow_results": [],
        "verification_results": [],
        "errors": [],
    }

    mock_session = AsyncMock()
    mock_verification_agent = AsyncMock()
    mock_verification_agent.generate_summary.return_value = "summary text"
    mock_verification_agent_cls = MagicMock(return_value=mock_verification_agent)

    @asynccontextmanager
    async def fake_session():
        yield mock_session

    with patch("orchestrator.nodes.get_db_session", fake_session), \
         patch("agents.verification_agent.VerificationAgent", mock_verification_agent_cls), \
         patch("orchestrator.nodes._write_meeting_audit_entry", new=AsyncMock()) as mock_write_audit, \
         patch("orchestrator.nodes._set_meeting_status", new=AsyncMock()) as mock_set_status:
        await send_summary_node(state)

        mock_set_status.assert_awaited_once_with("meeting_123", "completed")
        mock_write_audit.assert_awaited_once()
        assert mock_write_audit.await_args.kwargs["agent"] == "SummaryAgent"
        assert mock_write_audit.await_args.kwargs["step"] == "send_summary"
