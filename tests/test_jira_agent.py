"""
Unit tests for JiraAgent.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import date

from agents.workflow.jira_agent import JiraAgent, JiraMode
from schemas.base import WorkflowResult, WorkflowType
from db.models import Decision as DecisionModel


@pytest.fixture
def mock_decision():
    """Create a mock decision for testing."""
    decision = MagicMock(spec=DecisionModel)
    decision.id = "dec_001"
    decision.description = "Update PROJ-456 deadline to April 10"
    decision.owner = "Ankit"
    decision.deadline = date(2026, 4, 10)
    decision.raw_quote = "Let's push the deadline to April 10"
    return decision


@pytest.fixture
def jira_agent():
    """Create JiraAgent instance for testing."""
    with patch.dict('os.environ', {
        'JIRA_URL': 'https://test.atlassian.net',
        'JIRA_EMAIL': 'test@example.com',
        'JIRA_API_TOKEN': 'test-token',
        'JIRA_DEFAULT_PROJECT_KEY': 'PROJ',
        'JIRA_ALLOWED_PROJECT_KEYS': 'PROJ',
    }):
        agent = JiraAgent()
        yield agent


@pytest.mark.asyncio
async def test_jira_agent_initialization(jira_agent):
    """Test JiraAgent initializes with correct credentials."""
    assert jira_agent.jira_url == 'https://test.atlassian.net'
    assert jira_agent.jira_email == 'test@example.com'
    assert jira_agent.jira_api_token == 'test-token'
    assert jira_agent.client is not None


@pytest.mark.asyncio
async def test_create_ticket_success(jira_agent, mock_decision):
    """Test successful ticket creation."""
    # Mock HTTP responses
    create_response = MagicMock()
    create_response.json.return_value = {"key": "PROJ-123"}
    create_response.raise_for_status = MagicMock()
    
    verify_response = MagicMock()
    verify_response.json.return_value = {
        "key": "PROJ-123",
        "fields": {"summary": "Test issue"}
    }
    verify_response.raise_for_status = MagicMock()
    
    comment_response = MagicMock()
    comment_response.raise_for_status = MagicMock()
    
    # Mock client methods
    jira_agent.client.post = AsyncMock(side_effect=[create_response, comment_response])
    jira_agent.client.get = AsyncMock(return_value=verify_response)
    jira_agent._resolve_user = AsyncMock(return_value="account123")
    
    # Mock audit entry
    with patch('agents.workflow.jira_agent.get_db_session'):
        parameters = {
            "project_key": "PROJ",
            "issue_type": "Task",
            "summary": "Test issue",
            "description": "Test description",
            "assignee": "Ankit",
            "priority": "Medium"
        }
        
        result = await jira_agent.execute(mock_decision, parameters, JiraMode.CREATE)
    
    assert result.status == "success"
    assert result.decision_id == "dec_001"
    assert len(result.artifact_links) == 1
    assert "PROJ-123" in result.artifact_links[0]
    assert result.error_message is None


@pytest.mark.asyncio
async def test_create_ticket_falls_back_to_default_project(jira_agent, mock_decision):
    create_response = MagicMock()
    create_response.json.return_value = {"key": "PROJ-124"}
    create_response.raise_for_status = MagicMock()

    verify_response = MagicMock()
    verify_response.json.return_value = {
        "key": "PROJ-124",
        "fields": {"summary": "Fallback issue"}
    }
    verify_response.raise_for_status = MagicMock()

    comment_response = MagicMock()
    comment_response.raise_for_status = MagicMock()

    jira_agent.client.post = AsyncMock(side_effect=[create_response, comment_response])
    jira_agent.client.get = AsyncMock(return_value=verify_response)
    jira_agent._resolve_user = AsyncMock(return_value="account123")

    with patch('agents.workflow.jira_agent.get_db_session'):
        parameters = {
            "project_key": "MOBILE",
            "issue_type": "Task",
            "summary": "Fallback issue",
            "description": "Test description",
            "assignee": "Ankit",
            "priority": "Medium"
        }

        result = await jira_agent.execute(mock_decision, parameters, JiraMode.CREATE)

    assert result.status == "success"
    post_payload = jira_agent.client.post.await_args_list[0].kwargs["json"]
    assert post_payload["fields"]["project"]["key"] == "PROJ"


@pytest.mark.asyncio
async def test_create_ticket_omits_blank_priority(jira_agent, mock_decision):
    create_response = MagicMock()
    create_response.json.return_value = {"key": "PROJ-125"}
    create_response.raise_for_status = MagicMock()

    verify_response = MagicMock()
    verify_response.json.return_value = {
        "key": "PROJ-125",
        "fields": {"summary": "No priority issue"}
    }
    verify_response.raise_for_status = MagicMock()

    comment_response = MagicMock()
    comment_response.raise_for_status = MagicMock()

    jira_agent.client.post = AsyncMock(side_effect=[create_response, comment_response])
    jira_agent.client.get = AsyncMock(return_value=verify_response)
    jira_agent._resolve_user = AsyncMock(return_value="account123")

    with patch('agents.workflow.jira_agent.get_db_session'):
        parameters = {
            "project_key": "PROJ",
            "issue_type": "Task",
            "summary": "No priority issue",
            "description": "Test description",
            "assignee": "Ankit",
            "priority": "   ",
        }

        result = await jira_agent.execute(mock_decision, parameters, JiraMode.CREATE)

    assert result.status == "success"
    post_payload = jira_agent.client.post.await_args_list[0].kwargs["json"]
    assert "priority" not in post_payload["fields"]


@pytest.mark.asyncio
async def test_update_ticket_success(jira_agent, mock_decision):
    """Test successful ticket update."""
    # Mock HTTP responses
    update_response = MagicMock()
    update_response.raise_for_status = MagicMock()
    
    verify_response = MagicMock()
    verify_response.json.return_value = {
        "key": "PROJ-456",
        "fields": {"summary": "Updated issue"}
    }
    verify_response.raise_for_status = MagicMock()
    
    # Mock client methods
    jira_agent.client.put = AsyncMock(return_value=update_response)
    jira_agent.client.get = AsyncMock(return_value=verify_response)
    
    # Mock audit entry
    with patch('agents.workflow.jira_agent.get_db_session'):
        parameters = {
            "issue_key": "PROJ-456",
            "fields": {
                "duedate": "2026-04-10"
            }
        }
        
        result = await jira_agent.execute(mock_decision, parameters, JiraMode.UPDATE)
    
    assert result.status == "success"
    assert result.decision_id == "dec_001"
    assert "PROJ-456" in result.artifact_links[0]


@pytest.mark.asyncio
async def test_search_then_update_found(jira_agent, mock_decision):
    """Test search then update when issue is found."""
    # Mock HTTP responses
    search_response = MagicMock()
    search_response.json.return_value = {
        "total": 1,
        "issues": [{"key": "PROJ-789"}]
    }
    search_response.raise_for_status = MagicMock()
    
    update_response = MagicMock()
    update_response.raise_for_status = MagicMock()
    
    verify_response = MagicMock()
    verify_response.json.return_value = {
        "key": "PROJ-789",
        "fields": {"summary": "Found issue"}
    }
    verify_response.raise_for_status = MagicMock()
    
    # Mock client methods
    jira_agent.client.get = AsyncMock(side_effect=[search_response, verify_response])
    jira_agent.client.put = AsyncMock(return_value=update_response)
    
    # Mock audit entry
    with patch('agents.workflow.jira_agent.get_db_session'):
        parameters = {
            "jql_query": "project = PROJ AND summary ~ 'test'",
            "fields": {
                "status": {"name": "In Progress"}
            }
        }
        
        result = await jira_agent.execute(mock_decision, parameters, JiraMode.SEARCH_THEN_UPDATE)
    
    assert result.status == "success"
    assert "PROJ-789" in result.artifact_links[0]


@pytest.mark.asyncio
async def test_search_then_update_not_found(jira_agent, mock_decision):
    """Test search then update when no issue is found."""
    # Mock HTTP responses
    search_response = MagicMock()
    search_response.json.return_value = {
        "total": 0,
        "issues": []
    }
    search_response.raise_for_status = MagicMock()
    
    # Mock client methods
    jira_agent.client.get = AsyncMock(return_value=search_response)
    
    # Mock audit entry
    with patch('agents.workflow.jira_agent.get_db_session'):
        parameters = {
            "jql_query": "project = PROJ AND summary ~ 'nonexistent'",
            "fields": {}
        }
        
        result = await jira_agent.execute(mock_decision, parameters, JiraMode.SEARCH_THEN_UPDATE)
    
    assert result.status == "failed"
    assert "No issue found" in result.error_message


@pytest.mark.asyncio
async def test_resolve_user_success(jira_agent):
    """Test successful user resolution."""
    # Mock HTTP response
    response = MagicMock()
    response.json.return_value = [
        {"accountId": "account123", "displayName": "Ankit"}
    ]
    response.raise_for_status = MagicMock()
    
    jira_agent.client.get = AsyncMock(return_value=response)
    
    account_id = await jira_agent._resolve_user("Ankit")
    
    assert account_id == "account123"


@pytest.mark.asyncio
async def test_resolve_user_not_found(jira_agent):
    """Test user resolution when user not found."""
    # Mock HTTP response
    response = MagicMock()
    response.json.return_value = []
    response.raise_for_status = MagicMock()
    
    jira_agent.client.get = AsyncMock(return_value=response)
    
    account_id = await jira_agent._resolve_user("NonexistentUser")
    
    assert account_id is None


@pytest.mark.asyncio
async def test_verify_ticket_success(jira_agent):
    """Test successful ticket verification."""
    # Mock HTTP response
    response = MagicMock()
    response.json.return_value = {
        "key": "PROJ-123",
        "fields": {"summary": "Test issue"}
    }
    response.raise_for_status = MagicMock()
    
    jira_agent.client.get = AsyncMock(return_value=response)
    
    verified = await jira_agent._verify_ticket("PROJ-123")
    
    assert verified is True


@pytest.mark.asyncio
async def test_verify_ticket_failure(jira_agent):
    """Test ticket verification failure."""
    # Mock HTTP response to raise exception
    jira_agent.client.get = AsyncMock(side_effect=Exception("Not found"))
    
    verified = await jira_agent._verify_ticket("PROJ-999")
    
    assert verified is False


@pytest.mark.asyncio
async def test_retry_with_backoff_success_on_retry(jira_agent):
    """Test retry logic succeeds on second attempt."""
    # Mock function that fails once then succeeds
    mock_func = AsyncMock(side_effect=[
        Exception("First attempt failed"),
        MagicMock()  # Success on second attempt
    ])
    
    result = await jira_agent._retry_with_backoff(mock_func, max_retries=2, backoff_schedule=[0.1, 0.2])
    
    assert result is not None
    assert mock_func.call_count == 2


@pytest.mark.asyncio
async def test_retry_with_backoff_all_fail(jira_agent):
    """Test retry logic fails after all attempts."""
    # Mock function that always fails
    mock_func = AsyncMock(side_effect=Exception("Always fails"))
    
    with pytest.raises(Exception, match="Always fails"):
        await jira_agent._retry_with_backoff(mock_func, max_retries=2, backoff_schedule=[0.1, 0.2])
    
    assert mock_func.call_count == 3  # Initial + 2 retries


@pytest.mark.asyncio
async def test_create_ticket_with_adf_format(jira_agent, mock_decision):
    """Test that ticket creation uses ADF format."""
    # Mock HTTP responses
    create_response = MagicMock()
    create_response.json.return_value = {"key": "PROJ-123"}
    create_response.raise_for_status = MagicMock()
    
    verify_response = MagicMock()
    verify_response.json.return_value = {
        "key": "PROJ-123",
        "fields": {"summary": "Test"}
    }
    verify_response.raise_for_status = MagicMock()
    
    comment_response = MagicMock()
    comment_response.raise_for_status = MagicMock()
    
    # Capture the payloads
    captured_payloads = []
    
    async def capture_post(*args, **kwargs):
        if 'json' in kwargs:
            captured_payloads.append(kwargs['json'])
        return create_response if '/issue' in args[0] and '/comment' not in args[0] else comment_response
    
    jira_agent.client.post = AsyncMock(side_effect=capture_post)
    jira_agent.client.get = AsyncMock(return_value=verify_response)
    jira_agent._resolve_user = AsyncMock(return_value="account123")
    
    with patch('agents.workflow.jira_agent.get_db_session'):
        parameters = {
            "project_key": "PROJ",
            "issue_type": "Task",
            "summary": "Test",
            "description": "Test description",
            "assignee": "Ankit",
            "priority": "High"
        }
        
        await jira_agent.execute(mock_decision, parameters, JiraMode.CREATE)
    
    # Verify ADF format - first payload should be the create issue call
    assert len(captured_payloads) >= 1
    create_payload = captured_payloads[0]
    assert "fields" in create_payload
    assert "description" in create_payload["fields"]
    desc = create_payload["fields"]["description"]
    assert desc["type"] == "doc"
    assert desc["version"] == 1
    assert "content" in desc


@pytest.mark.asyncio
async def test_add_comment_with_raw_quote(jira_agent):
    """Test that comment is added with raw quote."""
    # Mock HTTP response
    response = MagicMock()
    response.raise_for_status = MagicMock()
    
    # Capture the comment payload
    captured_payload = None
    
    async def capture_post(*args, **kwargs):
        nonlocal captured_payload
        if 'json' in kwargs:
            captured_payload = kwargs['json']
        return response
    
    jira_agent.client.post = AsyncMock(side_effect=capture_post)
    
    await jira_agent._add_comment("PROJ-123", "Original meeting quote")
    
    # Verify comment format
    assert captured_payload is not None
    assert "body" in captured_payload
    body = captured_payload["body"]
    assert body["type"] == "doc"
    assert "Original meeting quote" in str(body)
