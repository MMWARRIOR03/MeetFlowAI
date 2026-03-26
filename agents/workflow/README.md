# Workflow Agents

This directory contains workflow execution agents for the MeetFlow AI system.

## JiraAgent

The `JiraAgent` executes Jira operations (CREATE/UPDATE/SEARCH) with retry logic and verification.

### Features

- **Three Operation Modes**:
  - `CREATE`: Create new Jira issues with ADF formatting
  - `UPDATE`: Update existing Jira issues
  - `SEARCH_THEN_UPDATE`: Search for issues using JQL, then update (fallback to CREATE if not found)

- **Jira ADF Support**: Uses Atlassian Document Format for issue descriptions and comments

- **User Resolution**: Automatically resolves usernames to Jira accountIds

- **Retry Logic**: 2 retries with exponential backoff (3s, 6s) on failures

- **Verification**: Reads back created/updated issues to verify operations

- **Audit Trail**: Writes AuditEntry records for all operations (success/failure)

- **Comment Support**: Adds comments with raw quotes from meeting transcripts

### Usage

```python
from agents.workflow.jira_agent import JiraAgent, JiraMode
from db.models import Decision

# Initialize agent
agent = JiraAgent()

# Create a ticket
parameters = {
    "project_key": "PROJ",
    "issue_type": "Task",
    "summary": "Implement feature X",
    "description": "Detailed description",
    "assignee": "john.doe",
    "priority": "High"
}

result = await agent.execute(decision, parameters, JiraMode.CREATE)

# Update a ticket
parameters = {
    "issue_key": "PROJ-123",
    "fields": {
        "duedate": "2026-04-10",
        "status": {"name": "In Progress"}
    }
}

result = await agent.execute(decision, parameters, JiraMode.UPDATE)

# Search and update
parameters = {
    "jql_query": "project = PROJ AND summary ~ 'feature X'",
    "fields": {
        "priority": {"name": "Critical"}
    }
}

result = await agent.execute(decision, parameters, JiraMode.SEARCH_THEN_UPDATE)
```

### Configuration

Set the following environment variables:

- `JIRA_URL`: Jira instance URL (e.g., https://company.atlassian.net)
- `JIRA_EMAIL`: Jira user email
- `JIRA_API_TOKEN`: Jira API token

### Testing

Run tests with:

```bash
pytest tests/test_jira_agent.py -v
pytest tests/test_jira_integration.py -v
```

### Requirements Satisfied

This implementation satisfies the following requirements from the spec:

- **6.1**: Support CREATE mode for creating new Jira issues
- **6.2**: Support UPDATE mode for modifying existing Jira issues
- **6.3**: Support SEARCH mode for finding Jira issues by criteria
- **6.4**: Create Jira issues with proper field mapping
- **6.5**: Update Jira issues with field values
- **6.6**: Retry up to 2 times with exponential backoff (3s, 6s)
- **6.7**: Verify operations by reading back created/updated issues
- **6.8**: Write AuditEntry for each operation with API call details
- **6.9**: Mark decisions as FAILED after retries exhausted
