"""
LangGraph pipeline for MeetFlow AI multi-agent orchestration.
Implements conditional routing, checkpointing, and idempotency.
"""
import logging
from typing import TypedDict, Optional, List, Dict, Any
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.sqlite import SqliteSaver

from schemas.base import NormalizedMeeting, Decision, ClassifierOutput, WorkflowResult
from orchestrator.nodes import (
    ingest_node,
    extract_node,
    classify_node,
    send_approval_node,
    wait_approval_node,
    execute_workflows_node,
    verify_node,
    send_summary_node
)


logger = logging.getLogger(__name__)


class PipelineState(TypedDict):
    """State shared across all agents in the pipeline."""
    meeting_id: str
    meeting: Optional[NormalizedMeeting]
    decisions: List[Decision]
    classifier_outputs: List[ClassifierOutput]
    approval_pending: List[str]  # Decision IDs
    workflow_results: List[WorkflowResult]
    errors: List[str]
    # Input data for ingestion
    input_data: Optional[Any]
    input_format: Optional[str]
    metadata: Optional[Dict[str, Any]]


def should_send_approval(state: PipelineState) -> str:
    """
    Conditional routing after classification.
    Routes to approval if any decisions require approval.
    
    Args:
        state: Current pipeline state
        
    Returns:
        Next node name: "send_approval", "execute", or "summary"
    """
    # Check if there are any decisions
    if not state.get("decisions"):
        logger.info("No decisions found, routing to summary")
        return "summary"
    
    # Check if any decisions require approval
    approval_required = []
    auto_trigger = []
    
    for classifier_output in state.get("classifier_outputs", []):
        if classifier_output.requires_approval:
            approval_required.append(classifier_output.decision_id)
        else:
            auto_trigger.append(classifier_output.decision_id)
    
    if approval_required:
        logger.info(f"Routing {len(approval_required)} decisions to approval gate")
        state["approval_pending"] = approval_required
        return "send_approval"
    elif auto_trigger:
        logger.info(f"Auto-triggering {len(auto_trigger)} decisions")
        return "execute"
    else:
        logger.info("No decisions to execute, routing to summary")
        return "summary"


def build_pipeline(checkpoint_path: Optional[str] = None) -> StateGraph:
    """
    Build LangGraph pipeline with conditional routing and optional checkpointing.
    
    Args:
        checkpoint_path: Path to SQLite checkpoint database (optional)
        
    Returns:
        Compiled StateGraph with optional checkpointing enabled
    """
    logger.info("Building LangGraph pipeline")
    
    # Create state graph
    workflow = StateGraph(PipelineState)
    
    # Add nodes
    workflow.add_node("ingest", ingest_node)
    workflow.add_node("extract", extract_node)
    workflow.add_node("classify", classify_node)
    workflow.add_node("send_approval", send_approval_node)
    workflow.add_node("wait_approval", wait_approval_node)
    workflow.add_node("execute_workflows", execute_workflows_node)
    workflow.add_node("verify", verify_node)
    workflow.add_node("send_summary", send_summary_node)
    
    # Set entry point
    workflow.set_entry_point("ingest")
    
    # Add edges
    workflow.add_edge("ingest", "extract")
    workflow.add_edge("extract", "classify")
    
    # Conditional routing after classification
    workflow.add_conditional_edges(
        "classify",
        should_send_approval,
        {
            "send_approval": "send_approval",
            "execute": "execute_workflows",
            "summary": "send_summary"
        }
    )
    
    # Approval flow
    workflow.add_edge("send_approval", "wait_approval")
    workflow.add_edge("wait_approval", "execute_workflows")
    
    # Execution and verification flow
    workflow.add_edge("execute_workflows", "verify")
    workflow.add_edge("verify", "send_summary")
    
    # Set finish point
    workflow.add_edge("send_summary", END)
    
    # Configure checkpointing if path provided
    if checkpoint_path:
        checkpointer = SqliteSaver.from_conn_string(checkpoint_path)
        compiled_graph = workflow.compile(checkpointer=checkpointer)
        logger.info("LangGraph pipeline built with checkpointing")
    else:
        compiled_graph = workflow.compile()
        logger.info("LangGraph pipeline built without checkpointing")
    
    return compiled_graph
