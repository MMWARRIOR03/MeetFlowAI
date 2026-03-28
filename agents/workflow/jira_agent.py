"""
Jira Workflow Agent for MeetFlow AI system.
Executes Jira operations (CREATE/UPDATE/SEARCH) with retry logic and verification.
"""
import os
import logging
import asyncio
import json
from typing import Dict, Any, Optional, List
from datetime import datetime
from enum import Enum

import httpx
from schemas.base import WorkflowResult, WorkflowType
from db.models import AuditEntry, Decision as DecisionModel
from db.database import get_db_session
from integrations.circuit_breaker import get_circuit_breaker, CircuitBreakerConfig


logger = logging.getLogger(__name__)


class JiraMode(str, Enum):
    """Jira operation modes."""
    CREATE = "create"
    UPDATE = "update"
    SEARCH_THEN_UPDATE = "search_then_update"


class JiraAgent:
    """
    Executes Jira workflows (CREATE/UPDATE/SEARCH).
    """
    
    def __init__(self):
        """
        Initialize JiraAgent with credentials from environment.
        """
        self.jira_url = os.getenv("JIRA_URL", "").rstrip('/')
        self.jira_email = os.getenv("JIRA_EMAIL", "")
        self.jira_api_token = os.getenv("JIRA_API_TOKEN", "")
        self.default_project_key = os.getenv("JIRA_DEFAULT_PROJECT_KEY", "PROJ")
        allowed_project_keys = os.getenv("JIRA_ALLOWED_PROJECT_KEYS", self.default_project_key)
        self.allowed_project_keys = {
            key.strip() for key in allowed_project_keys.split(",") if key.strip()
        } or {self.default_project_key}
        
        if not all([self.jira_url, self.jira_email, self.jira_api_token]):
            logger.warning("Jira credentials not fully configured")
        
        # Create httpx client with basic auth
        self.client = httpx.AsyncClient(
            auth=(self.jira_email, self.jira_api_token),
            timeout=30.0
        )
        
        self._circuit_breaker = None
        
        logger.info("JiraAgent initialized")
    
    async def _get_circuit_breaker(self):
        """Get or create circuit breaker for Jira API."""
        if not self._circuit_breaker:
            config = CircuitBreakerConfig(
                failure_threshold=5,
                recovery_timeout=60,
                success_threshold=2
            )
            self._circuit_breaker = await get_circuit_breaker("jira_api", config)
        return self._circuit_breaker
    
    async def execute(
        self,
        decision: DecisionModel,
        parameters: Dict[str, Any],
        mode: JiraMode
    ) -> WorkflowResult:
        """
        Execute Jira workflow.
        
        Args:
            decision: Decision to execute
            parameters: Workflow parameters
            mode: CREATE, UPDATE, or SEARCH_THEN_UPDATE
            
        Returns:
            WorkflowResult with status and artifact links
        """
        logger.info(f"Executing Jira workflow for decision {decision.id} in {mode} mode")
        
        try:
            # Route to mode-specific handler
            if mode == JiraMode.CREATE:
                project_key = self._resolve_project_key(parameters.get("project_key"))
                issue_key = await self._create_ticket(
                    project_key=project_key,
                    issue_type=parameters.get("issue_type", "Task"),
                    summary=parameters.get("summary", decision.description),
                    description=parameters.get("description", decision.description),
                    assignee=parameters.get("assignee", decision.owner),
                    priority=parameters.get("priority", "Medium"),
                    raw_quote=decision.raw_quote
                )
            elif mode == JiraMode.UPDATE:
                update_fields = self._normalize_update_fields(parameters)
                issue_key = await self._update_ticket(
                    issue_key=parameters.get("issue_key"),
                    fields=update_fields
                )
            elif mode == JiraMode.SEARCH_THEN_UPDATE:
                update_fields = self._normalize_update_fields(parameters)
                issue_key = await self._search_then_update(
                    jql_query=parameters.get("jql_query"),
                    fields=update_fields
                )
            else:
                raise ValueError(f"Unsupported Jira mode: {mode}")
            
            # Verify the operation
            verified = await self._verify_ticket(issue_key)
            
            if not verified:
                logger.warning(f"Verification failed for issue {issue_key}")
            
            # Build artifact link
            artifact_link = f"{self.jira_url}/browse/{issue_key}"
            
            # Write success audit entry
            await self._write_audit_entry(
                meeting_id=decision.meeting_id,
                decision_id=decision.id,
                outcome="success",
                detail=f"Successfully executed {mode} operation for issue {issue_key}",
                api_call=f"POST /rest/api/3/issue" if mode == JiraMode.CREATE else f"PUT /rest/api/3/issue/{issue_key}",
                http_status=200 if mode == JiraMode.CREATE else 204
            )
            
            return WorkflowResult(
                decision_id=decision.id,
                workflow_type=WorkflowType.JIRA_CREATE if mode == JiraMode.CREATE else WorkflowType.JIRA_UPDATE,
                status="success",
                artifact_links=[artifact_link],
                error_message=None
            )
            
        except Exception as e:
            logger.error(f"Failed to execute Jira workflow: {e}")
            
            # Write failure audit entry
            await self._write_audit_entry(
                meeting_id=decision.meeting_id,
                decision_id=decision.id,
                outcome="failure",
                detail=f"Failed to execute {mode} operation: {str(e)}",
                api_call=f"Jira API {mode}",
                http_status=None
            )
            
            return WorkflowResult(
                decision_id=decision.id,
                workflow_type=WorkflowType.JIRA_CREATE if mode == JiraMode.CREATE else WorkflowType.JIRA_UPDATE,
                status="failed",
                artifact_links=[],
                error_message=str(e)
            )

    def _resolve_project_key(self, requested_project_key: Optional[str]) -> str:
        """Normalize create requests onto an allowed Jira project key."""
        if requested_project_key in self.allowed_project_keys:
            return requested_project_key

        if requested_project_key and requested_project_key != self.default_project_key:
            logger.warning(
                "Unsupported Jira project key '%s'; falling back to default project '%s'",
                requested_project_key,
                self.default_project_key,
            )

        return self.default_project_key

    async def _create_ticket(
        self,
        project_key: str,
        issue_type: str,
        summary: str,
        description: str,
        assignee: str,
        priority: str,
        raw_quote: str
    ) -> str:
        """
        Create Jira ticket.
        Build Jira ADF (Atlassian Document Format) body.
        POST /rest/api/3/issue
        Add comment with raw_quote from decision.
        
        Args:
            project_key: Jira project key (e.g., PROJ)
            issue_type: Issue type (Task, Bug, Story, etc.)
            summary: Issue summary
            description: Issue description
            assignee: Assignee username
            priority: Priority (Highest, High, Medium, Low, Lowest)
            raw_quote: Original quote from meeting transcript
            
        Returns:
            Issue key (e.g., PROJ-123)
        """
        logger.info(f"Creating Jira ticket in project {project_key}")
        
        # Resolve assignee to accountId
        assignee_id = await self._resolve_user(assignee)
        
        # Build ADF description
        adf_description = {
            "type": "doc",
            "version": 1,
            "content": [
                {
                    "type": "paragraph",
                    "content": [
                        {
                            "type": "text",
                            "text": description
                        }
                    ]
                }
            ]
        }
        
        # Build issue payload
        payload = {
            "fields": {
                "project": {
                    "key": project_key
                },
                "summary": summary,
                "description": adf_description,
                "issuetype": {
                    "name": issue_type
                },
            }
        }

        if isinstance(priority, str) and priority.strip():
            payload["fields"]["priority"] = {
                "name": priority.strip()
            }
        
        # Add assignee if resolved
        if assignee_id:
            payload["fields"]["assignee"] = {"accountId": assignee_id}
        
        # Execute with retry logic
        response = await self._retry_with_backoff(
            lambda: self.client.post(
                f"{self.jira_url}/rest/api/3/issue",
                json=payload
            )
        )

        self._raise_for_status_with_context(
            response,
            operation="create issue",
            payload=payload
        )
        result = response.json()
        issue_key = result["key"]
        
        logger.info(f"Created Jira issue {issue_key}")
        
        # Add comment with raw quote
        if raw_quote:
            await self._add_comment(issue_key, raw_quote)
        
        return issue_key
    
    async def _update_ticket(
        self,
        issue_key: str,
        fields: Dict[str, Any]
    ) -> str:
        """
        Update Jira ticket.
        PUT /rest/api/3/issue/{issue_key}
        
        Args:
            issue_key: Issue key (e.g., PROJ-123)
            fields: Fields to update
            
        Returns:
            Issue key
        """
        logger.info(f"Updating Jira ticket {issue_key}")
        
        # Build update payload
        payload = {"fields": fields}
        
        # Execute with retry logic
        response = await self._retry_with_backoff(
            lambda: self.client.put(
                f"{self.jira_url}/rest/api/3/issue/{issue_key}",
                json=payload
            )
        )

        self._raise_for_status_with_context(
            response,
            operation=f"update issue {issue_key}",
            payload=payload
        )
        
        logger.info(f"Updated Jira issue {issue_key}")
        return issue_key
    
    async def _search_then_update(
        self,
        jql_query: str,
        fields: Dict[str, Any]
    ) -> str:
        """
        Search for ticket using JQL, then update.
        Fallback to CREATE if no match found.
        
        Args:
            jql_query: JQL query string
            fields: Fields to update
            
        Returns:
            Issue key
        """
        logger.info(f"Searching Jira with JQL: {jql_query}")
        
        # Execute search with retry logic
        response = await self._retry_with_backoff(
            lambda: self.client.get(
                f"{self.jira_url}/rest/api/3/search",
                params={"jql": jql_query, "maxResults": 1}
            )
        )

        self._raise_for_status_with_context(
            response,
            operation="search issue",
            payload={"jql": jql_query, "maxResults": 1}
        )
        result = response.json()
        
        if result.get("total", 0) > 0:
            # Found issue, update it
            issue_key = result["issues"][0]["key"]
            logger.info(f"Found issue {issue_key}, updating")
            return await self._update_ticket(issue_key, fields)
        else:
            # No issue found, would need to create
            # For now, raise error as we need more context to create
            raise ValueError(f"No issue found matching JQL: {jql_query}")
    
    async def _verify_ticket(self, issue_key: str) -> bool:
        """
        Verify ticket by reading back from Jira.
        GET /rest/api/3/issue/{issue_key}
        Compare fields to ensure operation succeeded.
        
        Args:
            issue_key: Issue key to verify
            
        Returns:
            True if verification succeeded
        """
        logger.info(f"Verifying Jira ticket {issue_key}")
        
        try:
            response = await self.client.get(
                f"{self.jira_url}/rest/api/3/issue/{issue_key}"
            )
            response.raise_for_status()
            
            # If we can read the issue, verification succeeds
            result = response.json()
            logger.info(f"Verified issue {issue_key}: {result['fields']['summary']}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to verify issue {issue_key}: {e}")
            return False

    def _normalize_update_fields(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Convert classifier-style update parameters into Jira field payloads."""
        if parameters.get("fields"):
            return self._normalize_jira_field_values(parameters["fields"])

        fields_to_update = parameters.get("fields_to_update", [])
        new_values = parameters.get("new_values", {})
        normalized: Dict[str, Any] = {}

        field_name_map = {
            "deadline": "duedate",
        }

        for field_name in fields_to_update:
            if field_name not in new_values:
                continue
            jira_field = field_name_map.get(field_name, field_name)
            normalized[jira_field] = new_values[field_name]

        if not normalized and "new_values" in parameters:
            for field_name, value in new_values.items():
                jira_field = field_name_map.get(field_name, field_name)
                normalized[jira_field] = value

        return self._normalize_jira_field_values(normalized)

    def _normalize_jira_field_values(self, fields: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize field values into Jira's expected update payload shapes."""
        field_name_map = {
            "summary": "summary",
            "priority": "priority",
            "deadline": "duedate",
            "duedate": "duedate",
        }
        normalized: Dict[str, Any] = {}

        for field_name, value in fields.items():
            jira_field = field_name_map.get(field_name.lower(), field_name)
            normalized[jira_field] = value

        priority_value = normalized.get("priority")
        if isinstance(priority_value, str):
            if priority_value.strip():
                normalized["priority"] = {"name": priority_value.strip()}
            else:
                normalized.pop("priority", None)

        return normalized

    def _raise_for_status_with_context(
        self,
        response: httpx.Response,
        operation: str,
        payload: Dict[str, Any]
    ) -> None:
        """Raise a descriptive error with Jira response details and request payload."""
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            response_text = response.text.strip()
            detail = (
                f"Jira {operation} failed with {response.status_code} for {response.request.url}. "
                f"Response: {response_text or '<empty>'}. "
                f"Payload: {json.dumps(payload, default=str)}"
            )
            raise ValueError(detail) from exc
    
    async def _resolve_user(self, username: str) -> Optional[str]:
        """
        Resolve username to Jira accountId.
        GET /rest/api/3/user/search?query={username}
        Fallback to None if user not found.
        
        Args:
            username: Username to resolve
            
        Returns:
            Jira accountId or None
        """
        logger.info(f"Resolving user: {username}")
        
        try:
            response = await self.client.get(
                f"{self.jira_url}/rest/api/3/user/search",
                params={"query": username}
            )
            response.raise_for_status()
            
            users = response.json()
            if users:
                account_id = users[0]["accountId"]
                logger.info(f"Resolved {username} to accountId {account_id}")
                return account_id
            else:
                logger.warning(f"User {username} not found in Jira")
                return None
                
        except Exception as e:
            logger.error(f"Failed to resolve user {username}: {e}")
            return None
    
    async def _add_comment(self, issue_key: str, comment_text: str) -> None:
        """
        Add comment to Jira issue.
        POST /rest/api/3/issue/{issue_key}/comment
        
        Args:
            issue_key: Issue key
            comment_text: Comment text
        """
        logger.info(f"Adding comment to issue {issue_key}")
        
        # Build ADF comment
        adf_comment = {
            "body": {
                "type": "doc",
                "version": 1,
                "content": [
                    {
                        "type": "paragraph",
                        "content": [
                            {
                                "type": "text",
                                "text": f"Original quote from meeting: \"{comment_text}\""
                            }
                        ]
                    }
                ]
            }
        }
        
        try:
            response = await self._retry_with_backoff(
                lambda: self.client.post(
                    f"{self.jira_url}/rest/api/3/issue/{issue_key}/comment",
                    json=adf_comment
                )
            )
            response.raise_for_status()
            logger.info(f"Added comment to issue {issue_key}")
        except Exception as e:
            logger.error(f"Failed to add comment to issue {issue_key}: {e}")
            # Don't raise - comment failure shouldn't block ticket creation
    
    async def _retry_with_backoff(
        self,
        func,
        max_retries: int = 2,
        backoff_schedule: List[int] = [3, 6]
    ):
        """
        Retry function with exponential backoff on failures.
        Uses circuit breaker for protection.
        
        Args:
            func: Async function to retry
            max_retries: Maximum number of retries (default 2)
            backoff_schedule: Backoff delays in seconds (default [3, 6])
            
        Returns:
            Function result
            
        Raises:
            Last exception if all retries fail
        """
        # Get circuit breaker
        circuit_breaker = await self._get_circuit_breaker()
        
        async def _execute_with_retry():
            last_exception = None
            
            for attempt in range(max_retries + 1):
                try:
                    return await func()
                except Exception as e:
                    last_exception = e
                    
                    if attempt < max_retries:
                        delay = backoff_schedule[attempt] if attempt < len(backoff_schedule) else backoff_schedule[-1]
                        logger.warning(f"Attempt {attempt + 1} failed: {e}. Retrying in {delay}s...")
                        await asyncio.sleep(delay)
                    else:
                        logger.error(f"All {max_retries + 1} attempts failed")
            
            raise last_exception
        
        # Execute with circuit breaker
        return await circuit_breaker.call(_execute_with_retry)
    
    async def _write_audit_entry(
        self,
        meeting_id: Optional[str],
        decision_id: str,
        outcome: str,
        detail: str,
        api_call: str,
        http_status: Optional[int]
    ) -> None:
        """
        Write audit entry for Jira operation.
        
        Args:
            decision_id: Decision identifier
            outcome: success or failure
            detail: Detailed description of the outcome
            api_call: API endpoint called
            http_status: HTTP status code
        """
        try:
            async with get_db_session() as session:
                audit_entry = AuditEntry(
                    meeting_id=meeting_id,
                    decision_id=decision_id,
                    agent="JiraAgent",
                    step="execute",
                    outcome=outcome,
                    detail=detail,
                    api_call=api_call,
                    http_status=http_status,
                    created_at=datetime.utcnow()
                )
                session.add(audit_entry)
                await session.commit()
                logger.debug(f"Wrote audit entry for decision {decision_id}")
        except Exception as e:
            logger.error(f"Failed to write audit entry: {e}")
            # Don't raise - audit failure shouldn't block workflow
    
    async def close(self):
        """Close the HTTP client."""
        await self.client.aclose()
