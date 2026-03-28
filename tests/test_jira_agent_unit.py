"""
Focused unit tests for JiraAgent payload normalization.
"""
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.workflow.jira_agent import JiraAgent
from db.models import AuditEntry


def test_normalize_update_fields_maps_deadline_to_duedate():
    agent = JiraAgent()

    normalized = agent._normalize_update_fields(
        {
            "fields_to_update": ["deadline"],
            "new_values": {"deadline": "2026-04-10"},
        }
    )

    assert normalized == {"duedate": "2026-04-10"}


def test_normalize_update_fields_wraps_priority_name():
    agent = JiraAgent()

    normalized = agent._normalize_update_fields(
        {
            "fields_to_update": ["priority"],
            "new_values": {"priority": "High"},
        }
    )

    assert normalized == {"priority": {"name": "High"}}


def test_normalize_update_fields_wraps_direct_priority_name():
    agent = JiraAgent()

    normalized = agent._normalize_update_fields(
        {
            "fields": {"summary": "API migration schedule has shifted", "priority": "High"},
        }
    )

    assert normalized == {
        "summary": "API migration schedule has shifted",
        "priority": {"name": "High"},
    }


def test_normalize_update_fields_canonicalizes_capitalized_classifier_keys():
    agent = JiraAgent()

    normalized = agent._normalize_update_fields(
        {
            "fields_to_update": ["Summary", "Priority"],
            "new_values": {
                "Summary": "API migration schedule has shifted",
                "Priority": "High",
            },
        }
    )

    assert normalized == {
        "summary": "API migration schedule has shifted",
        "priority": {"name": "High"},
    }


def test_resolve_project_key_defaults_to_proj_for_missing_or_invalid_key():
    agent = JiraAgent()

    assert agent._resolve_project_key(None) == "PROJ"
    assert agent._resolve_project_key("MOBILE") == "PROJ"


def test_resolve_project_key_preserves_allowed_project():
    agent = JiraAgent()

    assert agent._resolve_project_key("PROJ") == "PROJ"


@pytest.mark.asyncio
async def test_write_audit_entry_includes_meeting_id():
    agent = JiraAgent()

    session = AsyncMock()
    session.add = MagicMock()
    session.commit = AsyncMock()

    @asynccontextmanager
    async def fake_session():
        yield session

    with patch("agents.workflow.jira_agent.get_db_session", fake_session):
        await agent._write_audit_entry(
            meeting_id="meeting_123",
            decision_id="dec_123",
            outcome="success",
            detail="Executed Jira update",
            api_call="PUT /rest/api/3/issue/PROJ-1",
            http_status=204,
        )

    audit_entry = session.add.call_args.args[0]
    assert isinstance(audit_entry, AuditEntry)
    assert audit_entry.meeting_id == "meeting_123"
    assert audit_entry.decision_id == "dec_123"
