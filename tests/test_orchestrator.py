"""
Tests for LangGraph orchestration pipeline.
"""
import pytest
from orchestrator.graph import build_pipeline, PipelineState, should_send_approval
from schemas.base import Decision, ClassifierOutput, WorkflowType
from datetime import date


def test_build_pipeline():
    """Test that pipeline can be built successfully."""
    pipeline = build_pipeline(checkpoint_path=":memory:")
    assert pipeline is not None


def test_should_send_approval_with_approval_required():
    """Test conditional routing when approval is required."""
    state = PipelineState(
        meeting_id="test-123",
        meeting=None,
        decisions=[
            Decision(
                decision_id="dec_001",
                description="Test decision",
                owner="Test Owner",
                deadline=date(2026, 4, 1),
                confidence=0.9,
                auto_trigger=False,
                requires_approval=True,
                raw_quote="Test quote"
            )
        ],
        classifier_outputs=[
            ClassifierOutput(
                decision_id="dec_001",
                workflow_type=WorkflowType.JIRA_CREATE,
                parameters={"project_key": "TEST"},
                requires_approval=True
            )
        ],
        approval_pending=[],
        workflow_results=[],
        errors=[],
        input_data=None,
        input_format=None,
        metadata=None
    )
    
    result = should_send_approval(state)
    assert result == "send_approval"
    assert state["approval_pending"] == ["dec_001"]


def test_should_send_approval_with_auto_trigger():
    """Test conditional routing when auto-trigger is enabled."""
    state = PipelineState(
        meeting_id="test-123",
        meeting=None,
        decisions=[
            Decision(
                decision_id="dec_001",
                description="Test decision",
                owner="Test Owner",
                deadline=date(2026, 4, 1),
                confidence=0.9,
                auto_trigger=True,
                requires_approval=False,
                raw_quote="Test quote"
            )
        ],
        classifier_outputs=[
            ClassifierOutput(
                decision_id="dec_001",
                workflow_type=WorkflowType.JIRA_CREATE,
                parameters={"project_key": "TEST"},
                requires_approval=False
            )
        ],
        approval_pending=[],
        workflow_results=[],
        errors=[],
        input_data=None,
        input_format=None,
        metadata=None
    )
    
    result = should_send_approval(state)
    assert result == "execute"


def test_should_send_approval_with_no_decisions():
    """Test conditional routing when no decisions exist."""
    state = PipelineState(
        meeting_id="test-123",
        meeting=None,
        decisions=[],
        classifier_outputs=[],
        approval_pending=[],
        workflow_results=[],
        errors=[],
        input_data=None,
        input_format=None,
        metadata=None
    )
    
    result = should_send_approval(state)
    assert result == "summary"
