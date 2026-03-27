"""
Tests for VerificationAgent.
"""
import pytest
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

from agents.verification_agent import VerificationAgent
from schemas.base import WorkflowResult, WorkflowType, NormalizedMeeting, TranscriptSegment


@pytest.fixture
def mock_db_session():
    """Create mock database session."""
    session = AsyncMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.execute = AsyncMock()
    return session


@pytest.fixture
def verification_agent(mock_db_session):
    """Create VerificationAgent instance."""
    return VerificationAgent(db_session=mock_db_session)


@pytest.fixture
def sample_workflow_result():
    """Create sample workflow result."""
    return WorkflowResult(
        decision_id="dec_001",
        workflow_type=WorkflowType.JIRA_CREATE,
        status="success",
        artifact_links=["https://company.atlassian.net/browse/PROJ-123"],
        error_message=None
    )


@pytest.fixture
def sample_meeting():
    """Create sample meeting."""
    return NormalizedMeeting(
        meeting_id="meeting_001",
        title="Q2 Planning Sync",
        date=date(2026, 3, 20),
        participants=["Alice", "Bob", "Charlie"],
        transcript=[
            TranscriptSegment(
                speaker="Alice",
                timestamp="00:00:00",
                text="Let's create a new Jira ticket for the API refactor."
            )
        ]
    )


@pytest.mark.asyncio
async def test_verify_jira_success(verification_agent, sample_workflow_result):
    """Test successful Jira verification."""
    with patch('agents.verification_agent.JiraAgent') as mock_jira_class:
        # Mock JiraAgent
        mock_jira = AsyncMock()
        mock_jira._verify_ticket = AsyncMock(return_value=True)
        mock_jira.close = AsyncMock()
        mock_jira_class.return_value = mock_jira
        
        # Verify execution
        result = await verification_agent.verify_execution(sample_workflow_result)
        
        # Assertions
        assert result.decision_id == "dec_001"
        assert result.verified is True
        assert len(result.discrepancies) == 0
        assert result.details["issue_key"] == "PROJ-123"
        
        # Verify JiraAgent was called
        mock_jira._verify_ticket.assert_called_once_with("PROJ-123")
        mock_jira.close.assert_called_once()


@pytest.mark.asyncio
async def test_verify_jira_failure(verification_agent, sample_workflow_result):
    """Test failed Jira verification."""
    with patch('agents.verification_agent.JiraAgent') as mock_jira_class:
        # Mock JiraAgent to return failure
        mock_jira = AsyncMock()
        mock_jira._verify_ticket = AsyncMock(return_value=False)
        mock_jira.close = AsyncMock()
        mock_jira_class.return_value = mock_jira
        
        # Verify execution
        result = await verification_agent.verify_execution(sample_workflow_result)
        
        # Assertions
        assert result.decision_id == "dec_001"
        assert result.verified is False
        assert len(result.discrepancies) > 0
        assert "Failed to verify Jira issue" in result.discrepancies[0]


@pytest.mark.asyncio
async def test_verify_failed_workflow(verification_agent):
    """Test verification of failed workflow."""
    failed_result = WorkflowResult(
        decision_id="dec_002",
        workflow_type=WorkflowType.JIRA_CREATE,
        status="failed",
        artifact_links=[],
        error_message="API connection failed"
    )
    
    # Verify execution
    result = await verification_agent.verify_execution(failed_result)
    
    # Assertions
    assert result.decision_id == "dec_002"
    assert result.verified is False
    assert "Workflow status is failed" in result.discrepancies


@pytest.mark.asyncio
async def test_generate_summary(verification_agent, sample_meeting):
    """Test summary generation."""
    workflow_results = [
        WorkflowResult(
            decision_id="dec_001",
            workflow_type=WorkflowType.JIRA_CREATE,
            status="success",
            artifact_links=["https://company.atlassian.net/browse/PROJ-123"],
            error_message=None
        ),
        WorkflowResult(
            decision_id="dec_002",
            workflow_type=WorkflowType.JIRA_UPDATE,
            status="failed",
            artifact_links=[],
            error_message="Permission denied"
        )
    ]
    
    from schemas.base import VerificationResult
    verification_results = [
        VerificationResult(
            decision_id="dec_001",
            verified=True,
            discrepancies=[]
        ),
        VerificationResult(
            decision_id="dec_002",
            verified=False,
            discrepancies=["Workflow status is failed"]
        )
    ]
    
    # Generate summary
    summary = await verification_agent.generate_summary(
        meeting=sample_meeting,
        workflow_results=workflow_results,
        verification_results=verification_results
    )
    
    # Assertions
    assert "Q2 Planning Sync" in summary
    assert "1 decisions executed successfully" in summary
    assert "1 decisions failed" in summary
    assert "PROJ-123" in summary
    assert "Permission denied" in summary


@pytest.mark.asyncio
async def test_verify_hr_workflow(verification_agent):
    """Test HR workflow verification (placeholder)."""
    hr_result = WorkflowResult(
        decision_id="dec_003",
        workflow_type=WorkflowType.HR_HIRING,
        status="success",
        artifact_links=[],
        error_message=None
    )
    
    # Verify execution
    result = await verification_agent.verify_execution(hr_result)
    
    # Assertions
    assert result.decision_id == "dec_003"
    assert result.verified is True
    assert result.details["note"] == "HR verification not implemented"


@pytest.mark.asyncio
async def test_verify_procurement_workflow(verification_agent):
    """Test procurement workflow verification (placeholder)."""
    procurement_result = WorkflowResult(
        decision_id="dec_004",
        workflow_type=WorkflowType.PROCUREMENT_REQUEST,
        status="success",
        artifact_links=[],
        error_message=None
    )
    
    # Verify execution
    result = await verification_agent.verify_execution(procurement_result)
    
    # Assertions
    assert result.decision_id == "dec_004"
    assert result.verified is True
    assert result.details["note"] == "Procurement verification not implemented"


@pytest.mark.asyncio
async def test_write_audit_entry_resolves_meeting_id_from_decision(
    verification_agent,
    mock_db_session,
):
    execute_result = MagicMock()
    execute_result.scalar_one_or_none.return_value = "meeting_001"
    mock_db_session.execute.return_value = execute_result

    await verification_agent._write_audit_entry(
        decision_id="dec_001",
        outcome="success",
        detail="Verified Jira issue PROJ-1",
    )

    audit_entry = mock_db_session.add.call_args.args[0]
    assert audit_entry.meeting_id == "meeting_001"
    assert audit_entry.decision_id == "dec_001"
