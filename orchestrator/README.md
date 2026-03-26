# LangGraph Orchestration

This module implements the multi-agent orchestration pipeline for MeetFlow AI using LangGraph.

## Architecture

The pipeline follows a linear flow with conditional branching:

```
Ingest → Extract → Classify → [Approval Gate?] → Execute → Verify → Summary
```

### Pipeline Nodes

1. **Ingest Node**: Normalizes meeting inputs (VTT/txt/audio/JSON) into standardized format
2. **Extract Node**: Extracts structured decisions from meeting transcript using Gemini
3. **Classify Node**: Routes decisions to workflow types and resolves parameters
4. **Send Approval Node**: Sends approval requests to Slack for high-impact decisions
5. **Wait Approval Node**: Polls for approval status from Slack
6. **Execute Workflows Node**: Executes workflows in parallel (Jira, HR, Procurement)
7. **Verify Node**: Verifies workflow execution outcomes
8. **Send Summary Node**: Generates and sends Slack summary

### Conditional Routing

After the **Classify Node**, the pipeline routes based on decision requirements:

- **Requires Approval**: Routes to `send_approval` → `wait_approval` → `execute_workflows`
- **Auto-Trigger**: Routes directly to `execute_workflows`
- **No Decisions**: Routes to `send_summary`

## Features

### Checkpointing

The pipeline uses LangGraph's checkpointing feature with SqliteSaver:

```python
from orchestrator.graph import build_pipeline

# Build pipeline with checkpointing
pipeline = build_pipeline(checkpoint_path="checkpoints.db")
```

Checkpointing enables:
- **Resumption**: Continue pipeline execution after failures
- **Debugging**: Inspect state at each node
- **Replay**: Re-run pipeline from specific checkpoints

### Idempotency

The pipeline implements idempotency checks using AuditEntry records:

- Each node checks for existing audit entries before executing
- If a step was already completed successfully, it's skipped
- This makes the pipeline safe to re-run with the same `meeting_id`

### Parallel Execution

The **Execute Workflows Node** executes multiple workflows in parallel using `asyncio.gather()`:

```python
tasks = [
    jira_agent.execute(...),
    hr_agent.execute(...),
    procurement_agent.execute(...)
]
results = await asyncio.gather(*tasks, return_exceptions=True)
```

## Usage

### Basic Usage

```python
from orchestrator.graph import build_pipeline, PipelineState
from datetime import date

# Build pipeline
pipeline = build_pipeline()

# Create initial state
initial_state = PipelineState(
    meeting_id="meeting-001",
    meeting=None,
    decisions=[],
    classifier_outputs=[],
    approval_pending=[],
    workflow_results=[],
    errors=[],
    input_data="Meeting transcript here...",
    input_format="txt",
    metadata={
        "title": "Q2 Planning",
        "date": date(2026, 3, 20).isoformat(),
        "participants": ["Alice", "Bob"]
    }
)

# Execute pipeline
config = {"configurable": {"thread_id": "thread-001"}}
final_state = pipeline.invoke(initial_state, config)

# Check results
print(f"Decisions: {len(final_state['decisions'])}")
print(f"Workflows: {len(final_state['workflow_results'])}")
print(f"Errors: {len(final_state['errors'])}")
```

### With Checkpointing

```python
# First run
pipeline = build_pipeline(checkpoint_path="checkpoints.db")
config = {"configurable": {"thread_id": "thread-001"}}

try:
    final_state = pipeline.invoke(initial_state, config)
except Exception as e:
    print(f"Pipeline failed: {e}")

# Resume from checkpoint
final_state = pipeline.invoke(initial_state, config)
```

## State Schema

```python
class PipelineState(TypedDict):
    meeting_id: str                          # Unique meeting identifier
    meeting: Optional[NormalizedMeeting]     # Normalized meeting data
    decisions: List[Decision]                # Extracted decisions
    classifier_outputs: List[ClassifierOutput]  # Classification results
    approval_pending: List[str]              # Decision IDs pending approval
    workflow_results: List[WorkflowResult]   # Execution results
    errors: List[str]                        # Error messages
    input_data: Optional[Any]                # Raw input data
    input_format: Optional[str]              # Input format (vtt/txt/audio/json)
    metadata: Optional[Dict[str, Any]]       # Meeting metadata
```

## Error Handling

The pipeline implements robust error handling:

1. **Node-Level Errors**: Caught and added to `state["errors"]`
2. **Workflow Errors**: Captured in `WorkflowResult.error_message`
3. **Audit Trail**: All errors logged to AuditEntry table
4. **Graceful Degradation**: Pipeline continues even if individual workflows fail

## Testing

Run orchestrator tests:

```bash
# Unit tests
pytest tests/test_orchestrator.py -v

# Integration tests
pytest tests/test_orchestrator_integration.py -v
```

## Dependencies

- `langgraph>=0.0.26`: Multi-agent orchestration framework
- `sqlalchemy>=2.0.25`: Database ORM for checkpointing
- `asyncio`: Async execution for parallel workflows

## Future Enhancements

- [ ] Add VerificationAgent implementation
- [ ] Add HR and Procurement workflow agents
- [ ] Implement approval timeout handling
- [ ] Add pipeline metrics and monitoring
- [ ] Support for custom workflow plugins
