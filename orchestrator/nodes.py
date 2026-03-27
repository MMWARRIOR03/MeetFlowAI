"""
LangGraph node functions for MeetFlow AI pipeline.
Each node represents an agent or processing step in the orchestration.
"""
import logging
import asyncio
from typing import Dict, Any
from datetime import datetime, date

from schemas.base import (
    NormalizedMeeting,
    Decision,
    ClassifierOutput,
    WorkflowResult,
    InputFormat,
    MeetingMetadata
)
from agents.ingestion_agent import IngestionAgent
from agents.extraction_agent import ExtractionAgent
from agents.classifier_agent import ClassifierAgent
from agents.workflow.jira_agent import JiraAgent, JiraMode
from integrations.slack import SlackApprovalGate, create_slack_approval_gate
from integrations.llm_factory import get_llm_client
from integrations.llm_factory import get_llm_api_call_label
from db.database import get_db_session
from db.models import AuditEntry, Decision as DecisionModel, Meeting as MeetingModel
from sqlalchemy import select


logger = logging.getLogger(__name__)


async def _write_meeting_audit_entry(
    meeting_id: str,
    agent: str,
    step: str,
    outcome: str,
    detail: str,
    payload_snapshot: Dict[str, Any] | None = None,
) -> None:
    """Write an audit row that is explicitly linked to a meeting."""
    try:
        async with get_db_session() as session:
            session.add(
                AuditEntry(
                    meeting_id=meeting_id,
                    agent=agent,
                    step=step,
                    outcome=outcome,
                    detail=detail,
                    payload_snapshot=payload_snapshot,
                )
            )
            await session.commit()
    except Exception as exc:
        logger.error("Failed to write meeting audit entry for %s.%s: %s", agent, step, exc)


async def _mark_meeting_failed(meeting_id: str, reason: str) -> None:
    """Persist a terminal meeting failure so the API stops reporting 'processing'."""
    try:
        async with get_db_session() as session:
            result = await session.execute(
                select(MeetingModel).where(MeetingModel.id == meeting_id)
            )
            meeting_model = result.scalar_one_or_none()
            if meeting_model:
                meeting_model.status = "failed"
                await session.commit()
    except Exception as exc:
        logger.error(f"Failed to mark meeting {meeting_id} as failed: {exc}")


async def _set_meeting_status(meeting_id: str, status: str) -> None:
    """Persist a meeting status transition."""
    try:
        async with get_db_session() as session:
            result = await session.execute(
                select(MeetingModel).where(MeetingModel.id == meeting_id)
            )
            meeting_model = result.scalar_one_or_none()
            if meeting_model:
                meeting_model.status = status
                await session.commit()
    except Exception as exc:
        logger.error(f"Failed to set meeting {meeting_id} status to {status}: {exc}")


async def ingest_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Ingestion node: Normalizes meeting inputs.
    
    Args:
        state: Pipeline state
        
    Returns:
        Updated state with normalized meeting
    """
    logger.info(f"Ingestion node: Processing meeting {state.get('meeting_id')}")
    
    try:
        # Check for idempotency - skip if already ingested
        async with get_db_session() as session:
            result = await session.execute(
                select(AuditEntry).where(
                    AuditEntry.meeting_id == state["meeting_id"],
                    AuditEntry.agent == "IngestionAgent",
                    AuditEntry.outcome == "success"
                )
            )
            existing_audit = result.scalar_one_or_none()
            
            if existing_audit:
                logger.info(f"Meeting {state['meeting_id']} already ingested, skipping")
                # Load existing meeting from database
                meeting_result = await session.execute(
                    select(MeetingModel).where(MeetingModel.id == state["meeting_id"])
                )
                meeting_model = meeting_result.scalar_one_or_none()
                
                if meeting_model:
                    # Convert to NormalizedMeeting
                    from schemas.base import TranscriptSegment
                    transcript = [TranscriptSegment(**seg) for seg in meeting_model.transcript]
                    normalized_meeting = NormalizedMeeting(
                        meeting_id=meeting_model.id,
                        title=meeting_model.title,
                        date=meeting_model.date,
                        participants=meeting_model.participants,
                        transcript=transcript
                    )
                    state["meeting"] = normalized_meeting
                    return state
        
        # Create Gemini client
        import os
        gemini_client = get_llm_client(api_key=os.getenv("GEMINI_API_KEY"))
        
        # Create ingestion agent
        ingestion_agent = IngestionAgent(gemini_client=gemini_client)
        
        # Parse input format
        input_format = InputFormat(state["input_format"])
        
        # Parse metadata
        metadata_dict = state["metadata"]
        metadata = MeetingMetadata(
            title=metadata_dict["title"],
            date=date.fromisoformat(metadata_dict["date"]) if isinstance(metadata_dict["date"], str) else metadata_dict["date"],
            participants=metadata_dict["participants"]
        )
        
        # Ingest meeting
        normalized_meeting = await ingestion_agent.ingest(
            input_data=state["input_data"],
            input_format=input_format,
            metadata=metadata
        )
        
        # Override meeting_id with the one from state
        normalized_meeting.meeting_id = state["meeting_id"]
        
        # Save to database
        async with get_db_session() as session:
            meeting_model = MeetingModel(
                id=normalized_meeting.meeting_id,
                title=normalized_meeting.title,
                date=normalized_meeting.date,
                participants=normalized_meeting.participants,
                transcript=[seg.model_dump() for seg in normalized_meeting.transcript],
                status="processing"
            )
            session.add(meeting_model)
            await session.commit()
            
            # Write audit entry after meeting is saved
            audit_entry = AuditEntry(
                meeting_id=normalized_meeting.meeting_id,
                agent="IngestionAgent",
                step="ingest",
                outcome="success",
                detail=f"Successfully ingested meeting from {input_format} format with {len(normalized_meeting.transcript)} segments"
            )
            session.add(audit_entry)
            await session.commit()
        
        state["meeting"] = normalized_meeting
        logger.info(f"Ingestion complete: {len(normalized_meeting.transcript)} segments")
        
    except Exception as e:
        logger.error(f"Ingestion node failed: {e}")
        state["errors"].append(f"Ingestion failed: {str(e)}")
        if state.get("meeting_id"):
            await _mark_meeting_failed(state["meeting_id"], str(e))
    
    return state


async def extract_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extraction node: Extracts decisions from meeting transcript.
    
    Args:
        state: Pipeline state
        
    Returns:
        Updated state with extracted decisions
    """
    logger.info(f"Extraction node: Processing meeting {state.get('meeting_id')}")
    
    try:
        # Check for idempotency
        async with get_db_session() as session:
            result = await session.execute(
                select(AuditEntry).where(
                    AuditEntry.meeting_id == state["meeting_id"],
                    AuditEntry.agent == "ExtractionAgent",
                    AuditEntry.outcome == "success"
                )
            )
            existing_audit = result.scalar_one_or_none()
            
            if existing_audit:
                logger.info(f"Decisions already extracted for meeting {state['meeting_id']}, skipping")
                # Load existing decisions from database
                decisions_result = await session.execute(
                    select(DecisionModel).where(DecisionModel.meeting_id == state["meeting_id"])
                )
                decision_models = decisions_result.scalars().all()
                
                # Convert to Decision schema
                decisions = []
                for dm in decision_models:
                    decisions.append(Decision(
                        decision_id=dm.id,
                        description=dm.description,
                        owner=dm.owner,
                        deadline=dm.deadline,
                        workflow_type=dm.workflow_type,
                        confidence=dm.confidence,
                        auto_trigger=dm.auto_trigger,
                        requires_approval=not dm.auto_trigger,
                        raw_quote=dm.raw_quote
                    ))
                
                state["decisions"] = decisions
                return state
        
        # Create Gemini client and extraction agent
        import os
        gemini_client = get_llm_client(api_key=os.getenv("GEMINI_API_KEY"))
        
        async with get_db_session() as session:
            extraction_agent = ExtractionAgent(
                gemini_client=gemini_client,
                db_session=session
            )
            
            # Extract decisions
            extraction_output = await extraction_agent.extract_decisions(
                meeting=state["meeting"]
            )
            
            # Save decisions to database
            for decision in extraction_output.decisions:
                decision_model = DecisionModel(
                    id=decision.decision_id,
                    meeting_id=state["meeting_id"],
                    description=decision.description,
                    owner=decision.owner,
                    deadline=decision.deadline,
                    workflow_type=decision.workflow_type.value if decision.workflow_type else None,
                    approval_status="pending",
                    auto_trigger=decision.auto_trigger,
                    confidence=decision.confidence,
                    raw_quote=decision.raw_quote
                )
                session.add(decision_model)
            
            await session.commit()
            
            # Write audit entry after decisions are saved
            audit_entry = AuditEntry(
                meeting_id=state["meeting_id"],
                agent="ExtractionAgent",
                step="extract_decisions",
                outcome="success",
                detail=f"Extraction complete: {len(extraction_output.decisions)} decisions, {len(extraction_output.ambiguous_items)} ambiguous",
                api_call=get_llm_api_call_label()
            )
            session.add(audit_entry)
            await session.commit()
            
            state["decisions"] = extraction_output.decisions
            logger.info(f"Extraction complete: {len(extraction_output.decisions)} decisions")
    
    except Exception as e:
        logger.error(f"Extraction node failed: {e}")
        state["errors"].append(f"Extraction failed: {str(e)}")
        if state.get("meeting_id"):
            await _mark_meeting_failed(state["meeting_id"], str(e))
    
    return state


async def classify_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Classification node: Routes decisions to workflow types.
    
    Args:
        state: Pipeline state
        
    Returns:
        Updated state with classifier outputs
    """
    logger.info(f"Classification node: Processing {len(state.get('decisions', []))} decisions")
    
    try:
        # Check for idempotency
        async with get_db_session() as session:
            result = await session.execute(
                select(AuditEntry).where(
                    AuditEntry.meeting_id == state["meeting_id"],
                    AuditEntry.agent == "ClassifierAgent",
                    AuditEntry.outcome == "success"
                )
            )
            existing_audits = result.scalars().all()
            
            if len(existing_audits) >= len(state.get("decisions", [])):
                logger.info(f"Decisions already classified for meeting {state['meeting_id']}, skipping")
                # Load existing classifier outputs from database
                decisions_result = await session.execute(
                    select(DecisionModel).where(DecisionModel.meeting_id == state["meeting_id"])
                )
                decision_models = decisions_result.scalars().all()
                
                classifier_outputs = []
                for dm in decision_models:
                    if dm.workflow_type and dm.parameters:
                        from schemas.base import WorkflowType
                        classifier_outputs.append(ClassifierOutput(
                            decision_id=dm.id,
                            workflow_type=WorkflowType(dm.workflow_type),
                            parameters=dm.parameters,
                            requires_approval=not dm.auto_trigger
                        ))
                
                state["classifier_outputs"] = classifier_outputs
                return state
        
        # Create Gemini client and classifier agent
        import os
        gemini_client = get_llm_client(api_key=os.getenv("GEMINI_API_KEY"))
        
        classifier_outputs = []
        
        async with get_db_session() as session:
            classifier_agent = ClassifierAgent(
                gemini_client=gemini_client,
                db_session=session
            )
            
            # Classify each decision
            for decision in state["decisions"]:
                classifier_output = await classifier_agent.classify_decision(
                    decision=decision,
                    meeting_context=state["meeting"]
                )
                classifier_outputs.append(classifier_output)
                
                # Update decision in database with workflow_type and parameters
                result = await session.execute(
                    select(DecisionModel).where(DecisionModel.id == decision.decision_id)
                )
                decision_model = result.scalar_one_or_none()
                
                if decision_model:
                    decision_model.workflow_type = classifier_output.workflow_type.value
                    decision_model.parameters = classifier_output.parameters
                    await session.commit()
            
            state["classifier_outputs"] = classifier_outputs
            logger.info(f"Classification complete: {len(classifier_outputs)} decisions classified")
    
    except Exception as e:
        logger.error(f"Classification node failed: {e}")
        state["errors"].append(f"Classification failed: {str(e)}")
        if state.get("meeting_id"):
            await _mark_meeting_failed(state["meeting_id"], str(e))
    
    return state


async def send_approval_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Send approval node: Sends approval requests to Slack.
    
    Args:
        state: Pipeline state
        
    Returns:
        Updated state
    """
    logger.info(f"Send approval node: Sending approval for {len(state.get('approval_pending', []))} decisions")
    
    try:
        # Get decisions requiring approval
        approval_decision_ids = state.get("approval_pending", [])
        
        if not approval_decision_ids:
            logger.info("No decisions require approval")
            return state
        
        # Load decisions from database
        async with get_db_session() as session:
            result = await session.execute(
                select(DecisionModel).where(DecisionModel.id.in_(approval_decision_ids))
            )
            decisions = result.scalars().all()
            
            # Create Slack approval gate
            slack_gate = create_slack_approval_gate()
            
            # Send approval messages
            await slack_gate.send_approval_message(
                decisions=decisions,
                db_session=session
            )
            
            logger.info(f"Approval messages sent for {len(decisions)} decisions")
    
    except Exception as e:
        logger.error(f"Send approval node failed: {e}")
        state["errors"].append(f"Send approval failed: {str(e)}")
    
    return state


async def wait_approval_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Wait approval node: Polls for approval status.
    
    Args:
        state: Pipeline state
        
    Returns:
        Updated state
    """
    logger.info(f"Wait approval node: Waiting for approval of {len(state.get('approval_pending', []))} decisions")
    
    try:
        approval_decision_ids = state.get("approval_pending", [])
        
        if not approval_decision_ids:
            return state
        
        # Poll for approval status
        max_polls = 60  # 5 minutes with 5-second intervals
        poll_interval = 5
        
        for poll_count in range(max_polls):
            async with get_db_session() as session:
                result = await session.execute(
                    select(DecisionModel).where(DecisionModel.id.in_(approval_decision_ids))
                )
                decisions = result.scalars().all()
                
                # Check if all decisions have been approved or rejected
                all_resolved = all(
                    d.approval_status in ["approved", "rejected"]
                    for d in decisions
                )
                
                if all_resolved:
                    logger.info("All approvals resolved")
                    # Filter out rejected decisions
                    approved_ids = [
                        d.id for d in decisions
                        if d.approval_status == "approved"
                    ]
                    state["approval_pending"] = approved_ids
                    return state
            
            # Wait before next poll
            await asyncio.sleep(poll_interval)
        
        logger.warning("Approval timeout reached")
        state["errors"].append("Approval timeout: Some decisions not approved within time limit")
    
    except Exception as e:
        logger.error(f"Wait approval node failed: {e}")
        state["errors"].append(f"Wait approval failed: {str(e)}")
    
    return state


async def execute_workflows_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Execute workflows node: Executes workflows in parallel.
    
    Args:
        state: Pipeline state
        
    Returns:
        Updated state with workflow results
    """
    logger.info(f"Execute workflows node: Executing {len(state.get('classifier_outputs', []))} workflows")
    
    try:
        # Check for idempotency
        async with get_db_session() as session:
            result = await session.execute(
                select(AuditEntry).where(
                    AuditEntry.meeting_id == state["meeting_id"],
                    AuditEntry.agent == "JiraAgent",
                    AuditEntry.step == "execute",
                    AuditEntry.outcome == "success"
                )
            )
            existing_audits = result.scalars().all()
            
            if len(existing_audits) >= len(state.get("classifier_outputs", [])):
                logger.info(f"Workflows already executed for meeting {state['meeting_id']}, skipping")
                # Load existing workflow results
                from db.models import WorkflowResult as WorkflowResultModel
                results_query = await session.execute(
                    select(WorkflowResultModel).join(DecisionModel).where(
                        DecisionModel.meeting_id == state["meeting_id"]
                    )
                )
                result_models = results_query.scalars().all()
                
                workflow_results = []
                for rm in result_models:
                    from schemas.base import WorkflowType
                    workflow_results.append(WorkflowResult(
                        decision_id=rm.decision_id,
                        workflow_type=WorkflowType(rm.workflow_type),
                        status=rm.status,
                        artifact_links=rm.artifact_links or [],
                        error_message=rm.error_message
                    ))
                
                state["workflow_results"] = workflow_results
                return state
        
        # Create workflow agents
        jira_agent = JiraAgent()
        
        # Build tasks for parallel execution
        tasks = []
        
        for classifier_output in state["classifier_outputs"]:
            # Skip if requires approval and not approved
            if classifier_output.requires_approval:
                if classifier_output.decision_id not in state.get("approval_pending", []):
                    logger.info(f"Skipping decision {classifier_output.decision_id} - not approved")
                    continue
            
            # Load decision from database
            async with get_db_session() as session:
                result = await session.execute(
                    select(DecisionModel).where(DecisionModel.id == classifier_output.decision_id)
                )
                decision_model = result.scalar_one_or_none()
                
                if not decision_model:
                    logger.warning(f"Decision {classifier_output.decision_id} not found in database")
                    continue
                
                # Route to appropriate workflow agent
                from schemas.base import WorkflowType
                
                if classifier_output.workflow_type == WorkflowType.JIRA_CREATE:
                    task = jira_agent.execute(
                        decision=decision_model,
                        parameters=classifier_output.parameters,
                        mode=JiraMode.CREATE
                    )
                    tasks.append(task)
                    
                elif classifier_output.workflow_type == WorkflowType.JIRA_UPDATE:
                    task = jira_agent.execute(
                        decision=decision_model,
                        parameters=classifier_output.parameters,
                        mode=JiraMode.UPDATE
                    )
                    tasks.append(task)
                    
                elif classifier_output.workflow_type == WorkflowType.JIRA_SEARCH:
                    task = jira_agent.execute(
                        decision=decision_model,
                        parameters=classifier_output.parameters,
                        mode=JiraMode.SEARCH_THEN_UPDATE
                    )
                    tasks.append(task)
                
                # Note: HR and Procurement agents not implemented yet
                # Placeholder for future implementation
        
        # Execute workflows in parallel
        if tasks:
            workflow_results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Filter out exceptions and log them
            valid_results = []
            for result in workflow_results:
                if isinstance(result, Exception):
                    logger.error(f"Workflow execution failed: {result}")
                    state["errors"].append(f"Workflow execution failed: {str(result)}")
                else:
                    valid_results.append(result)
            
            state["workflow_results"] = valid_results
            logger.info(f"Workflow execution complete: {len(valid_results)} successful")
        else:
            logger.info("No workflows to execute")
            state["workflow_results"] = []
        
        # Close Jira agent
        await jira_agent.close()
    
    except Exception as e:
        logger.error(f"Execute workflows node failed: {e}")
        state["errors"].append(f"Execute workflows failed: {str(e)}")
    
    return state


async def verify_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Verification node: Verifies workflow execution outcomes.
    
    Args:
        state: Pipeline state
        
    Returns:
        Updated state
    """
    logger.info(f"Verification node: Verifying {len(state.get('workflow_results', []))} workflow results")
    
    try:
        workflow_results = state.get("workflow_results", [])
        
        if not workflow_results:
            logger.info("No workflow results to verify")
            return state
        
        # Create verification agent
        async with get_db_session() as session:
            from agents.verification_agent import VerificationAgent
            
            verification_agent = VerificationAgent(db_session=session)
            
            # Verify each workflow result
            verification_results = []
            for result in workflow_results:
                verification_result = await verification_agent.verify_execution(result)
                verification_results.append(verification_result)
                
                if verification_result.verified:
                    logger.info(f"Workflow {result.decision_id} verified successfully")
                else:
                    logger.warning(
                        f"Workflow {result.decision_id} verification failed: "
                        f"{', '.join(verification_result.discrepancies)}"
                    )
            
            # Store verification results in state
            state["verification_results"] = verification_results
            
            logger.info(f"Verification complete: {len(verification_results)} results")
    
    except Exception as e:
        logger.error(f"Verification node failed: {e}")
        state["errors"].append(f"Verification failed: {str(e)}")
    
    return state


async def send_summary_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Send summary node: Sends Slack summary of pipeline execution.
    
    Args:
        state: Pipeline state
        
    Returns:
        Updated state
    """
    logger.info(f"Send summary node: Generating summary for meeting {state.get('meeting_id')}")
    
    try:
        meeting = state.get("meeting")
        workflow_results = state.get("workflow_results", [])
        verification_results = state.get("verification_results", [])
        
        if not meeting:
            logger.warning("No meeting data available for summary")
            return state
        
        # Generate summary using VerificationAgent
        async with get_db_session() as session:
            from agents.verification_agent import VerificationAgent
            
            verification_agent = VerificationAgent(db_session=session)
            
            summary_text = await verification_agent.generate_summary(
                meeting=meeting,
                workflow_results=workflow_results,
                verification_results=verification_results
            )
            
            logger.info(f"Summary generated:\n{summary_text}")
            
            # Note: Actual Slack sending would happen here
            # For now, just log the summary
            
            # Update meeting status
            final_status = "failed" if state.get("errors") else "completed"
            await _set_meeting_status(state["meeting_id"], final_status)
            await _write_meeting_audit_entry(
                meeting_id=state["meeting_id"],
                agent="SummaryAgent",
                step="send_summary",
                outcome="success",
                detail=f"Generated execution summary with final meeting status {final_status}",
                payload_snapshot={
                    "summary_text": summary_text,
                    "summary_length": len(summary_text),
                    "workflow_result_count": len(workflow_results),
                    "verification_result_count": len(verification_results),
                    "final_status": final_status,
                },
            )
    
    except Exception as e:
        logger.error(f"Send summary node failed: {e}")
        state["errors"].append(f"Send summary failed: {str(e)}")
        if state.get("meeting_id"):
            await _write_meeting_audit_entry(
                meeting_id=state["meeting_id"],
                agent="SummaryAgent",
                step="send_summary",
                outcome="failure",
                detail=f"Failed to generate or send summary: {str(e)}",
            )
    
    return state
