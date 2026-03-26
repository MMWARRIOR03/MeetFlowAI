"""
Integration tests for JiraAgent with real-world scenarios.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import date

from agents.workflow.jira_agent import JiraAgent, JiraMode
from db.models import Decision as DecisionModel


@pytest.fixture
def jira_agent():
    """Create JiraAgent instance for testing."""
    with patch.dict('os.environ', {
        'JIRA_URL': 'https://projectexhibition69.atlassian.net',
        'JIRA_EMAIL': 'test@example.com',
        'JIRA_API_TOKEN': 'test-token'
    }):
        agent = JiraAgent()
        yield agent


@pytest.mark.asyncio
async def test_full_create_workflow(jira_agent):
    """Test complete CREATE workflow with all steps."""
    # Create mock decision
    decision = MagicMock(spec=DecisionModel)
    decision.id = "dec_004"
    decision.description = "Create Jira ticket for Q2 planning"
    decision.owner = "Mrinal"
    decision.deadline = date(2026, 4, 1)
    decision.raw_quote = "Let's create a ticket to track Q2 planning tasks"
    
    # Mock all HTTP interactions
    user_response = MagicMock()
    user_response.json.return_value = [{"accountId": "mrinal123"}]
    user_response.raise_for_status = MagicMock()
    
    create_response = MagicMock()
    create_response.json.return_value = {"key": "PROJ-999"}
    create_response.raise_for_status = MagicMock()
    
    comment_response = MagicMock()
    comment_response.raise_for_status = MagicMock()
    
    verify_response = MagicMock()
    verify_response.json.return_value = {
        "key": "PROJ-999",
        "fields": {
            "summary": "Q2 Planning Tasks",
            "description": {"type": "doc", "content": []},
            "assignee": {"accountId": "mrinal123"},
            "priority": {"name": "High"}
        }
    }
    verify_response.raise_for_status = MagicMock()
    
    # Setup mock responses
    jira_agent.client.get = AsyncMock(side_effect=[user_response, verify_response])
    jira_agent.client.post = AsyncMock(side_effect=[create_response, comment_response])
    
    # Mock database
    with patch('agents.workflow.jira_agent.get_db_session'):
        parameters = {
            "project_key": "PROJ",
            "issue_type": "Epic",
            "summary": "Q2 Planning Tasks",
            "description": "Track all Q2 planning related tasks",
            "assignee": "Mrinal",
            "priority": "High"
        }
        
        result = await jira_agent.execute(decision, parameters, JiraMode.CREATE)
    
    # Verify result
    assert result.status == "success"
    assert result.decision_id == "dec_004"
    assert len(result.artifact_links) == 1
    assert "PROJ-999" in result.artifact_links[0]
    assert result.error_message is None
    
    # Verify all API calls were made
    assert jira_agent.client.get.call_count == 2  # user lookup + verify
    assert jira_agent.client.post.call_count == 2  # create + comment


@pytest.mark.asyncio
async def test_full_update_workflow(jira_agent):
    """Test complete UPDATE workflow."""
    # Create mock decision
    decision = MagicMock(spec=DecisionModel)
    decision.id = "dec_001"
    decision.description = "Update PROJ-456 deadline to April 10"
    decision.owner = "Ankit"
    decision.deadline = date(2026, 4, 10)
    decision.raw_quote = "Let's push the deadline to April 10"
    
    # Mock HTTP interactions
    update_response = MagicMock()
    update_response.raise_for_status = MagicMock()
    
    verify_response = MagicMock()
    verify_response.json.return_value = {
        "key": "PROJ-456",
        "fields": {
            "summary": "Existing task",
            "duedate": "2026-04-10"
        }
    }
    verify_response.raise_for_status = MagicMock()
    
    jira_agent.client.put = AsyncMock(return_value=update_response)
    jira_agent.client.get = AsyncMock(return_value=verify_response)
    
    # Mock database
    with patch('agents.workflow.jira_agent.get_db_session'):
        parameters = {
            "issue_key": "PROJ-456",
            "fields": {
                "duedate": "2026-04-10"
            }
        }
        
        result = await jira_agent.execute(decision, parameters, JiraMode.UPDATE)
    
    # Verify result
    assert result.status == "success"
    assert "PROJ-456" in result.artifact_links[0]
    
    # Verify API calls
    assert jira_agent.client.put.call_count == 1
    assert jira_agent.client.get.call_count == 1


@pytest.mark.asyncio
async def test_retry_on_transient_failure(jira_agent):
    """Test that retry logic handles transient failures."""
    decision = MagicMock(spec=DecisionModel)
    decision.id = "dec_retry"
    decision.description = "Test retry"
    decision.owner = "Test"
    decision.deadline = date(2026, 4, 1)
    decision.raw_quote = "Test"
    
    # Mock responses: fail twice, then succeed
    update_response_success = MagicMock()
    update_response_success.raise_for_status = MagicMock()
    
    verify_response = MagicMock()
    verify_response.json.return_value = {
        "key": "PROJ-123",
        "fields": {"summary": "Test"}
    }
    verify_response.raise_for_status = MagicMock()
    
    # Simulate transient failures followed by success
    call_count = 0
    async def mock_put(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count <= 2:
            raise Exception("Transient error")
        return update_response_success
    
    jira_agent.client.put = mock_put
    jira_agent.client.get = AsyncMock(return_value=verify_response)
    
    with patch('agents.workflow.jira_agent.get_db_session'):
        parameters = {
            "issue_key": "PROJ-123",
            "fields": {"status": {"name": "Done"}}
        }
        
        result = await jira_agent.execute(decision, parameters, JiraMode.UPDATE)
    
    # Should succeed after retries
    assert result.status == "success"
    assert call_count == 3  # 1 initial + 2 retries


@pytest.mark.asyncio
async def test_handles_missing_user_gracefully(jira_agent):
    """Test that missing user doesn't block ticket creation."""
    decision = MagicMock(spec=DecisionModel)
    decision.id = "dec_nouser"
    decision.description = "Test missing user"
    decision.owner = "NonexistentUser"
    decision.deadline = date(2026, 4, 1)
    decision.raw_quote = "Test"
    
    # Mock user not found
    user_response = MagicMock()
    user_response.json.return_value = []
    user_response.raise_for_status = MagicMock()
    
    create_response = MagicMock()
    create_response.json.return_value = {"key": "PROJ-888"}
    create_response.raise_for_status = MagicMock()
    
    comment_response = MagicMock()
    comment_response.raise_for_status = MagicMock()
    
    verify_response = MagicMock()
    verify_response.json.return_value = {
        "key": "PROJ-888",
        "fields": {"summary": "Test"}
    }
    verify_response.raise_for_status = MagicMock()
    
    jira_agent.client.get = AsyncMock(side_effect=[user_response, verify_response])
    jira_agent.client.post = AsyncMock(side_effect=[create_response, comment_response])
    
    with patch('agents.workflow.jira_agent.get_db_session'):
        parameters = {
            "project_key": "PROJ",
            "issue_type": "Task",
            "summary": "Test",
            "description": "Test",
            "assignee": "NonexistentUser",
            "priority": "Medium"
        }
        
        result = await jira_agent.execute(decision, parameters, JiraMode.CREATE)
    
    # Should still succeed, just without assignee
    assert result.status == "success"
    assert "PROJ-888" in result.artifact_links[0]
