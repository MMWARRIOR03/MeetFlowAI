"""
Integration tests for ClassifierAgent with realistic scenarios.
"""
import pytest
from datetime import date
from unittest.mock import AsyncMock

from agents.classifier_agent import ClassifierAgent
from schemas.base import (
    Decision,
    NormalizedMeeting,
    TranscriptSegment,
    WorkflowType
)


@pytest.fixture
def mock_gemini_client():
    """Create mock GeminiClient."""
    return AsyncMock()


@pytest.fixture
def mock_db_session():
    """Create mock database session."""
    session = AsyncMock()
    return session


@pytest.fixture
def realistic_meeting():
    """Create realistic meeting transcript."""
    return NormalizedMeeting(
        meeting_id="meet_q2_planning_2026",
        title="Q2 Planning Sync",
        date=date(2026, 3, 21),
        participants=["Ankit", "Priya", "Mrinal", "Sarah"],
        transcript=[
            TranscriptSegment(
                speaker="Ankit",
                timestamp="00:00:15",
                text="Good morning everyone. Let's start with our Q2 planning."
            ),
            TranscriptSegment(
                speaker="Ankit",
                timestamp="00:01:30",
                text="First item - we need to update PROJ-456 with the new deadline of April 10th."
            ),
            TranscriptSegment(
                speaker="Priya",
                timestamp="00:03:15",
                text="Agreed. Also, we need to hire a backend engineer by end of March. The position is critical for our API development."
            ),
            TranscriptSegment(
                speaker="Mrinal",
                timestamp="00:05:00",
                text="Let's raise the AWS spend limit by 40k for the quarter. We're hitting our current limits."
            ),
            TranscriptSegment(
                speaker="Sarah",
                timestamp="00:06:30",
                text="Mrinal, can you create a task for the API documentation by April 1st?"
            ),
            TranscriptSegment(
                speaker="Mrinal",
                timestamp="00:07:00",
                text="Sure, I'll handle that."
            )
        ]
    )


@pytest.mark.asyncio
async def test_end_to_end_classification_workflow(
    mock_gemini_client,
    mock_db_session,
    realistic_meeting
):
    """Test end-to-end classification of multiple decision types."""
    
    # Create agent
    agent = ClassifierAgent(mock_gemini_client, mock_db_session)
    
    # Test 1: Jira Update Decision
    jira_update_decision = Decision(
        decision_id="dec_001",
        description="Update PROJ-456 deadline to April 10",
        owner="Ankit",
        deadline=date(2026, 4, 10),
        confidence=0.95,
        auto_trigger=True,
        requires_approval=False,
        raw_quote="First item - we need to update PROJ-456 with the new deadline of April 10th."
    )
    
    mock_gemini_client.generate_json.return_value = {
        "workflow_type": "jira_update",
        "parameters": {
            "issue_key": "PROJ-456",
            "fields_to_update": ["deadline"],
            "new_values": {"deadline": "2026-04-10"}
        },
        "requires_approval": False
    }
    
    result1 = await agent.classify_decision(jira_update_decision, realistic_meeting)
    assert result1.workflow_type == WorkflowType.JIRA_UPDATE
    assert result1.parameters["issue_key"] == "PROJ-456"
    
    # Test 2: HR Hiring Decision
    hr_decision = Decision(
        decision_id="dec_002",
        description="Hire backend engineer for API development",
        owner="Priya",
        deadline=date(2026, 3, 28),
        confidence=0.90,
        auto_trigger=False,
        requires_approval=True,
        raw_quote="Also, we need to hire a backend engineer by end of March. The position is critical for our API development."
    )
    
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
    
    result2 = await agent.classify_decision(hr_decision, realistic_meeting)
    assert result2.workflow_type == WorkflowType.HR_HIRING
    assert result2.parameters["position"] == "Backend Engineer"
    assert result2.requires_approval is True
    
    # Test 3: Procurement Decision
    procurement_decision = Decision(
        decision_id="dec_003",
        description="Increase AWS spend limit by $40k",
        owner="Mrinal",
        deadline=date(2026, 3, 26),
        confidence=0.92,
        auto_trigger=False,
        requires_approval=True,
        raw_quote="Let's raise the AWS spend limit by 40k for the quarter. We're hitting our current limits."
    )
    
    mock_gemini_client.generate_json.return_value = {
        "workflow_type": "procurement_request",
        "parameters": {
            "item_description": "AWS cloud services spend increase",
            "quantity": 1,
            "estimated_cost": "40000",
            "vendor": "Amazon Web Services",
            "requester": "Mrinal"
        },
        "requires_approval": True
    }
    
    result3 = await agent.classify_decision(procurement_decision, realistic_meeting)
    assert result3.workflow_type == WorkflowType.PROCUREMENT_REQUEST
    assert result3.parameters["estimated_cost"] == 40000.0
    assert result3.requires_approval is True
    
    # Test 4: Jira Create Decision
    jira_create_decision = Decision(
        decision_id="dec_004",
        description="Create task for API documentation",
        owner="Mrinal",
        deadline=date(2026, 4, 1),
        confidence=0.88,
        auto_trigger=True,
        requires_approval=False,
        raw_quote="Mrinal, can you create a task for the API documentation by April 1st?"
    )
    
    mock_gemini_client.generate_json.return_value = {
        "workflow_type": "jira_create",
        "parameters": {
            "project_key": "PROJ",
            "issue_type": "Task",
            "summary": "API documentation",
            "description": "Create comprehensive API documentation",
            "assignee": "Mrinal",
            "priority": "Medium"
        },
        "requires_approval": False
    }
    
    result4 = await agent.classify_decision(jira_create_decision, realistic_meeting)
    assert result4.workflow_type == WorkflowType.JIRA_CREATE
    assert result4.parameters["summary"] == "API documentation"
    assert result4.parameters["assignee"] == "Mrinal"
    
    # Verify all classifications were successful
    assert mock_gemini_client.generate_json.call_count == 4
    assert mock_db_session.add.call_count == 4  # 4 audit entries
    assert mock_db_session.commit.call_count == 4


@pytest.mark.asyncio
async def test_all_workflow_types_supported(
    mock_gemini_client,
    mock_db_session,
    realistic_meeting
):
    """Test that all 5 workflow types are supported."""
    
    agent = ClassifierAgent(mock_gemini_client, mock_db_session)
    
    workflow_types = [
        "jira_create",
        "jira_update",
        "jira_search",
        "hr_hiring",
        "procurement_request"
    ]
    
    for i, wf_type in enumerate(workflow_types):
        decision = Decision(
            decision_id=f"dec_{i:03d}",
            description=f"Test decision for {wf_type}",
            owner="Test User",
            deadline=date(2026, 4, 1),
            confidence=0.9,
            auto_trigger=False,
            requires_approval=False,
            raw_quote=f"Test quote for {wf_type}"
        )
        
        mock_gemini_client.generate_json.return_value = {
            "workflow_type": wf_type,
            "parameters": {"test": "param"},
            "requires_approval": False
        }
        
        result = await agent.classify_decision(decision, realistic_meeting)
        assert result.workflow_type.value == wf_type
        assert result.decision_id == f"dec_{i:03d}"
