"""
Tests for ClassifierAgent.
"""
import pytest
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

from agents.classifier_agent import ClassifierAgent
from schemas.base import (
    Decision,
    NormalizedMeeting,
    TranscriptSegment,
    WorkflowType,
    ClassifierOutput
)
from integrations.gemini import GeminiClient


@pytest.fixture
def mock_gemini_client():
    """Create mock GeminiClient."""
    client = AsyncMock(spec=GeminiClient)
    return client


@pytest.fixture
def mock_db_session():
    """Create mock database session."""
    session = AsyncMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    return session


@pytest.fixture
def sample_meeting():
    """Create sample meeting for testing."""
    return NormalizedMeeting(
        meeting_id="meet_001",
        title="Q2 Planning Sync",
        date=date(2026, 3, 21),
        participants=["Ankit", "Priya", "Mrinal"],
        transcript=[
            TranscriptSegment(
                speaker="Ankit",
                timestamp="00:01:30",
                text="Let's update PROJ-456 with the new deadline of April 10th."
            ),
            TranscriptSegment(
                speaker="Priya",
                timestamp="00:03:15",
                text="We need to hire a backend engineer by end of March."
            ),
            TranscriptSegment(
                speaker="Mrinal",
                timestamp="00:05:00",
                text="Let's raise the AWS spend limit by 40k for the quarter."
            )
        ]
    )


@pytest.fixture
def sample_jira_update_decision():
    """Create sample Jira update decision."""
    return Decision(
        decision_id="dec_001",
        description="Update PROJ-456 deadline to April 10",
        owner="Ankit",
        deadline=date(2026, 4, 10),
        confidence=0.95,
        auto_trigger=True,
        requires_approval=False,
        raw_quote="Let's update PROJ-456 with the new deadline of April 10th."
    )


@pytest.fixture
def sample_hr_hiring_decision():
    """Create sample HR hiring decision."""
    return Decision(
        decision_id="dec_002",
        description="Hire backend engineer",
        owner="Priya",
        deadline=date(2026, 3, 28),
        confidence=0.90,
        auto_trigger=False,
        requires_approval=True,
        raw_quote="We need to hire a backend engineer by end of March."
    )


@pytest.fixture
def sample_procurement_decision():
    """Create sample procurement decision."""
    return Decision(
        decision_id="dec_003",
        description="Increase AWS spend limit by $40k",
        owner="Mrinal",
        deadline=date(2026, 3, 26),
        confidence=0.92,
        auto_trigger=False,
        requires_approval=True,
        raw_quote="Let's raise the AWS spend limit by 40k for the quarter."
    )


@pytest.mark.asyncio
async def test_classify_jira_update_decision(
    mock_gemini_client,
    mock_db_session,
    sample_meeting,
    sample_jira_update_decision
):
    """Test classification of Jira update decision."""
    # Setup mock response
    mock_gemini_client.generate_json.return_value = {
        "workflow_type": "jira_update",
        "parameters": {
            "issue_key": "PROJ-456",
            "fields_to_update": ["deadline"],
            "new_values": {"deadline": "2026-04-10"}
        },
        "requires_approval": False
    }
    
    # Create agent
    agent = ClassifierAgent(mock_gemini_client, mock_db_session)
    
    # Classify decision
    result = await agent.classify_decision(
        decision=sample_jira_update_decision,
        meeting_context=sample_meeting
    )
    
    # Verify result
    assert isinstance(result, ClassifierOutput)
    assert result.decision_id == "dec_001"
    assert result.workflow_type == WorkflowType.JIRA_UPDATE
    assert result.parameters["issue_key"] == "PROJ-456"
    assert result.parameters["fields_to_update"] == ["deadline"]
    assert result.parameters["new_values"]["deadline"] == "2026-04-10"
    assert result.requires_approval is False
    
    # Verify Gemini was called
    mock_gemini_client.generate_json.assert_called_once()
    
    # Verify audit entry was written
    assert mock_db_session.add.called
    assert mock_db_session.commit.called


@pytest.mark.asyncio
async def test_classify_hr_hiring_decision(
    mock_gemini_client,
    mock_db_session,
    sample_meeting,
    sample_hr_hiring_decision
):
    """Test classification of HR hiring decision."""
    # Setup mock response
    mock_gemini_client.generate_json.return_value = {
        "workflow_type": "hr_hiring",
        "parameters": {
            "candidate_name": "TBD",
            "position": "Backend Engineer",
            "department": "Engineering",
            "start_date": "2026-03-28",
            "hiring_manager": "Priya"
        },
        "requires_approval": True
    }
    
    # Create agent
    agent = ClassifierAgent(mock_gemini_client, mock_db_session)
    
    # Classify decision
    result = await agent.classify_decision(
        decision=sample_hr_hiring_decision,
        meeting_context=sample_meeting
    )
    
    # Verify result
    assert isinstance(result, ClassifierOutput)
    assert result.decision_id == "dec_002"
    assert result.workflow_type == WorkflowType.HR_HIRING
    assert result.parameters["position"] == "Backend Engineer"
    assert result.parameters["department"] == "Engineering"
    assert result.parameters["hiring_manager"] == "Priya"
    assert result.requires_approval is True
    
    # Verify Gemini was called
    mock_gemini_client.generate_json.assert_called_once()


@pytest.mark.asyncio
async def test_classify_procurement_decision(
    mock_gemini_client,
    mock_db_session,
    sample_meeting,
    sample_procurement_decision
):
    """Test classification of procurement decision."""
    # Setup mock response
    mock_gemini_client.generate_json.return_value = {
        "workflow_type": "procurement_request",
        "parameters": {
            "item_description": "AWS cloud services spend increase",
            "quantity": 1,
            "estimated_cost": "$40,000",
            "vendor": "Amazon Web Services",
            "requester": "Mrinal"
        },
        "requires_approval": True
    }
    
    # Create agent
    agent = ClassifierAgent(mock_gemini_client, mock_db_session)
    
    # Classify decision
    result = await agent.classify_decision(
        decision=sample_procurement_decision,
        meeting_context=sample_meeting
    )
    
    # Verify result
    assert isinstance(result, ClassifierOutput)
    assert result.decision_id == "dec_003"
    assert result.workflow_type == WorkflowType.PROCUREMENT_REQUEST
    assert result.parameters["item_description"] == "AWS cloud services spend increase"
    assert result.parameters["estimated_cost"] == 40000.0  # Converted to float
    assert result.parameters["requester"] == "Mrinal"
    assert result.requires_approval is True


@pytest.mark.asyncio
async def test_classify_jira_create_decision(
    mock_gemini_client,
    mock_db_session,
    sample_meeting
):
    """Test classification of Jira create decision."""
    decision = Decision(
        decision_id="dec_004",
        description="Create new task for API documentation",
        owner="Mrinal",
        deadline=date(2026, 4, 1),
        confidence=0.88,
        auto_trigger=True,
        requires_approval=False,
        raw_quote="Mrinal, can you create a task for the API documentation by April 1st?"
    )
    
    # Setup mock response
    mock_gemini_client.generate_json.return_value = {
        "workflow_type": "jira_create",
        "parameters": {
            "project_key": "PROJ",
            "issue_type": "Task",
            "summary": "API documentation",
            "description": "Create API documentation",
            "assignee": "Mrinal",
            "priority": "Medium"
        },
        "requires_approval": False
    }
    
    # Create agent
    agent = ClassifierAgent(mock_gemini_client, mock_db_session)
    
    # Classify decision
    result = await agent.classify_decision(
        decision=decision,
        meeting_context=sample_meeting
    )
    
    # Verify result
    assert result.workflow_type == WorkflowType.JIRA_CREATE
    assert result.parameters["project_key"] == "PROJ"
    assert result.parameters["issue_type"] == "Task"
    assert result.parameters["summary"] == "API documentation"
    assert result.parameters["assignee"] == "Mrinal"


@pytest.mark.asyncio
async def test_classification_failure_writes_audit(
    mock_gemini_client,
    mock_db_session,
    sample_meeting,
    sample_jira_update_decision
):
    """Test that classification failure writes audit entry."""
    # Setup mock to raise exception
    mock_gemini_client.generate_json.side_effect = Exception("API error")
    
    # Create agent
    agent = ClassifierAgent(mock_gemini_client, mock_db_session)
    
    # Classify decision should raise exception
    with pytest.raises(Exception, match="API error"):
        await agent.classify_decision(
            decision=sample_jira_update_decision,
            meeting_context=sample_meeting
        )
    
    # Verify audit entry was written for failure
    assert mock_db_session.add.called
    assert mock_db_session.commit.called


@pytest.mark.asyncio
async def test_resolve_jira_create_params_with_defaults(
    mock_gemini_client,
    mock_db_session
):
    """Test parameter resolution with defaults for jira_create."""
    agent = ClassifierAgent(mock_gemini_client, mock_db_session)
    
    # Minimal parameters
    params = {
        "description": "Test task"
    }
    
    # Resolve parameters
    resolved = agent._resolve_jira_create_params(params)
    
    # Verify defaults were applied
    assert resolved["project_key"] == "PROJ"
    assert resolved["issue_type"] == "Task"
    assert resolved["priority"] == "Medium"
    assert "summary" in resolved


@pytest.mark.asyncio
async def test_resolve_procurement_params_cost_parsing(
    mock_gemini_client,
    mock_db_session
):
    """Test procurement parameter resolution with cost parsing."""
    agent = ClassifierAgent(mock_gemini_client, mock_db_session)
    
    # Parameters with string cost
    params = {
        "item_description": "Test item",
        "estimated_cost": "$40,000"
    }
    
    # Resolve parameters
    resolved = agent._resolve_procurement_params(params)
    
    # Verify cost was parsed to float
    assert resolved["estimated_cost"] == 40000.0
    assert resolved["quantity"] == 1  # Default
    assert resolved["vendor"] == "TBD"  # Default
