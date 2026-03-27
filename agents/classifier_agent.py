"""
Classifier Agent for MeetFlow AI.
Routes decisions to workflow types and resolves workflow-specific parameters.
"""
import logging
from typing import Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from schemas.base import (
    Decision,
    NormalizedMeeting,
    ClassifierOutput,
    WorkflowType
)
from integrations.gemini import GeminiClient
from integrations.llm_factory import get_llm_api_call_label
from prompts.classification import CLASSIFICATION_PROMPT, CLASSIFICATION_SCHEMA
from db.models import AuditEntry


logger = logging.getLogger(__name__)


class ClassifierAgent:
    """
    Classifies decisions into workflow types and resolves parameters.
    Uses Gemini for AI-powered classification and parameter extraction.
    """
    
    def __init__(self, gemini_client: GeminiClient, db_session: AsyncSession):
        """
        Initialize ClassifierAgent.
        
        Args:
            gemini_client: GeminiClient instance for API calls
            db_session: Database session for audit trail
        """
        self.gemini_client = gemini_client
        self.db_session = db_session
        logger.info("ClassifierAgent initialized")
    
    async def classify_decision(
        self,
        decision: Decision,
        meeting_context: NormalizedMeeting
    ) -> ClassifierOutput:
        """
        Classify decision and extract workflow parameters.
        
        Args:
            decision: Extracted decision
            meeting_context: Full meeting context for parameter resolution
            
        Returns:
            ClassifierOutput with workflow_type and parameters
        """
        logger.info(f"Classifying decision: {decision.decision_id}")
        
        try:
            # Build classification prompt
            prompt = self._build_classification_prompt(decision, meeting_context)
            
            # Call Gemini for classification
            logger.info("Calling Gemini for decision classification")
            response = await self.gemini_client.generate_json(
                prompt=prompt,
                system_instruction=CLASSIFICATION_PROMPT,
                response_schema=CLASSIFICATION_SCHEMA,
                temperature=0.1
            )
            
            # Parse response
            workflow_type_str = response.get("workflow_type")
            parameters = response.get("parameters", {})
            requires_approval = response.get("requires_approval", decision.requires_approval)
            
            # Convert workflow_type string to enum
            workflow_type = WorkflowType(workflow_type_str)
            
            # Resolve parameters with additional context
            resolved_parameters = await self._resolve_parameters(
                decision=decision,
                workflow_type=workflow_type,
                parameters=parameters
            )
            
            logger.info(
                f"Classified decision {decision.decision_id} as {workflow_type.value} "
                f"with {len(resolved_parameters)} parameters"
            )
            
            # Create classifier output
            classifier_output = ClassifierOutput(
                decision_id=decision.decision_id,
                workflow_type=workflow_type,
                parameters=resolved_parameters,
                requires_approval=requires_approval
            )
            
            # Write audit entry
            await self._write_audit_entry(
                meeting_id=meeting_context.meeting_id,
                decision_id=decision.decision_id,
                outcome="success",
                detail=f"Classified as {workflow_type.value}",
                payload_snapshot={
                    "workflow_type": workflow_type.value,
                    "parameters": resolved_parameters,
                    "requires_approval": requires_approval
                },
                api_call=get_llm_api_call_label()
            )
            
            return classifier_output
            
        except Exception as e:
            logger.error(f"Classification failed for decision {decision.decision_id}: {e}")
            
            # Write audit entry for failure
            await self._write_audit_entry(
                meeting_id=meeting_context.meeting_id,
                decision_id=decision.decision_id,
                outcome="failure",
                detail=f"Classification failed: {str(e)}"
            )
            
            raise
    
    def _build_classification_prompt(
        self,
        decision: Decision,
        meeting_context: NormalizedMeeting
    ) -> str:
        """
        Build classification prompt with decision and meeting context.
        
        Args:
            decision: Decision to classify
            meeting_context: Full meeting context
            
        Returns:
            Complete prompt for Gemini
        """
        # Format transcript for context
        transcript_text = "\n".join([
            f"[{seg.timestamp}] {seg.speaker}: {seg.text}"
            for seg in meeting_context.transcript
        ])
        
        prompt = f"""
Meeting Title: {meeting_context.title}
Meeting Date: {meeting_context.date.isoformat()}
Participants: {", ".join(meeting_context.participants)}

Decision to Classify:
- Decision ID: {decision.decision_id}
- Description: {decision.description}
- Owner: {decision.owner}
- Deadline: {decision.deadline.isoformat()}
- Raw Quote: "{decision.raw_quote}"

Full Meeting Transcript (for context):
{transcript_text}

Classify this decision into the appropriate workflow type and extract all relevant parameters.
"""
        return prompt
    
    async def _resolve_parameters(
        self,
        decision: Decision,
        workflow_type: WorkflowType,
        parameters: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Resolve workflow-specific parameters with additional context.
        
        Args:
            decision: Decision being classified
            workflow_type: Classified workflow type
            parameters: Initial parameters from Gemini
            
        Returns:
            Resolved parameters dictionary
        """
        logger.info(f"Resolving parameters for {workflow_type.value}")
        
        # Add decision metadata to parameters
        resolved = {
            **parameters,
            "decision_id": decision.decision_id,
            "owner": decision.owner,
            "deadline": decision.deadline.isoformat()
        }
        
        # Workflow-specific parameter resolution
        if workflow_type == WorkflowType.JIRA_CREATE:
            resolved = self._resolve_jira_create_params(resolved)
        elif workflow_type == WorkflowType.JIRA_UPDATE:
            resolved = self._resolve_jira_update_params(resolved)
        elif workflow_type == WorkflowType.JIRA_SEARCH:
            resolved = self._resolve_jira_search_params(resolved)
        elif workflow_type == WorkflowType.HR_HIRING:
            resolved = self._resolve_hr_hiring_params(resolved)
        elif workflow_type == WorkflowType.PROCUREMENT_REQUEST:
            resolved = self._resolve_procurement_params(resolved)
        
        return resolved
    
    def _resolve_jira_create_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Resolve parameters for jira_create workflow.
        
        Args:
            params: Initial parameters
            
        Returns:
            Resolved parameters with defaults
        """
        defaults = {
            "project_key": "PROJ",
            "issue_type": "Task",
            "priority": "Medium"
        }
        
        # Apply defaults for missing fields
        for key, value in defaults.items():
            if key not in params:
                params[key] = value
        
        # Ensure required fields exist
        if "summary" not in params:
            params["summary"] = params.get("description", "New task")[:100]
        
        if "assignee" not in params:
            params["assignee"] = params.get("owner", "Unassigned")
        
        return params
    
    def _resolve_jira_update_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Resolve parameters for jira_update workflow.
        
        Args:
            params: Initial parameters
            
        Returns:
            Resolved parameters
        """
        # Ensure fields_to_update and new_values are present
        if "fields_to_update" not in params:
            params["fields_to_update"] = list(params.get("new_values", {}).keys())
        
        if "new_values" not in params:
            params["new_values"] = {}
        
        return params
    
    def _resolve_jira_search_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Resolve parameters for jira_search workflow.
        
        Args:
            params: Initial parameters
            
        Returns:
            Resolved parameters
        """
        # Ensure search_criteria exists
        if "search_criteria" not in params:
            params["search_criteria"] = ""
        
        # Ensure fields_to_update and new_values are present
        if "fields_to_update" not in params:
            params["fields_to_update"] = list(params.get("new_values", {}).keys())
        
        if "new_values" not in params:
            params["new_values"] = {}
        
        return params
    
    def _resolve_hr_hiring_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Resolve parameters for hr_hiring workflow.
        
        Args:
            params: Initial parameters
            
        Returns:
            Resolved parameters with defaults
        """
        defaults = {
            "department": "Engineering"
        }
        
        # Apply defaults for missing fields
        for key, value in defaults.items():
            if key not in params:
                params[key] = value
        
        # Ensure hiring_manager is set
        if "hiring_manager" not in params:
            params["hiring_manager"] = params.get("owner", "Unknown")
        
        return params
    
    def _resolve_procurement_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Resolve parameters for procurement_request workflow.
        
        Args:
            params: Initial parameters
            
        Returns:
            Resolved parameters with defaults
        """
        defaults = {
            "quantity": 1,
            "vendor": "TBD"
        }
        
        # Apply defaults for missing fields
        for key, value in defaults.items():
            if key not in params:
                params[key] = value
        
        # Ensure requester is set
        if "requester" not in params:
            params["requester"] = params.get("owner", "Unknown")
        
        # Ensure estimated_cost is a number
        if "estimated_cost" in params and isinstance(params["estimated_cost"], str):
            # Try to extract numeric value from string
            import re
            cost_match = re.search(r'[\d,]+', params["estimated_cost"].replace('$', ''))
            if cost_match:
                params["estimated_cost"] = float(cost_match.group().replace(',', ''))
            else:
                params["estimated_cost"] = 0.0
        
        return params
    
    async def _write_audit_entry(
        self,
        meeting_id: str,
        decision_id: str,
        outcome: str,
        detail: str,
        payload_snapshot: Optional[Dict[str, Any]] = None,
        api_call: Optional[str] = None
    ) -> None:
        """
        Write audit entry for classification action.
        
        Args:
            meeting_id: Meeting identifier
            decision_id: Decision identifier
            outcome: Outcome status (success, failure, pending)
            detail: Detailed description of the action
            payload_snapshot: Optional snapshot of classification result
        """
        audit_entry = AuditEntry(
            meeting_id=meeting_id,
            decision_id=decision_id,
            agent="ClassifierAgent",
            step="classify_decision",
            outcome=outcome,
            detail=detail,
            api_call=api_call,
            payload_snapshot=payload_snapshot
        )
        
        self.db_session.add(audit_entry)
        await self.db_session.commit()
        
        logger.debug(f"Audit entry written: {outcome} - {detail}")
