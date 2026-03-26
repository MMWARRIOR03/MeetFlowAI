"""
Example script demonstrating LangGraph pipeline execution.
"""
import asyncio
import os
from datetime import date
from orchestrator.graph import build_pipeline, PipelineState


async def run_example_pipeline():
    """Run example pipeline with sample meeting data."""
    
    # Check for required environment variables
    required_vars = ["GEMINI_API_KEY", "JIRA_URL", "JIRA_EMAIL", "JIRA_API_TOKEN"]
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    
    if missing_vars:
        print(f"Warning: Missing environment variables: {', '.join(missing_vars)}")
        print("Pipeline may fail without proper configuration.")
    
    # Build pipeline
    print("Building LangGraph pipeline...")
    pipeline = build_pipeline(checkpoint_path="checkpoints.db")
    print("Pipeline built successfully!")
    
    # Create sample meeting data
    sample_transcript = """
[00:00:00] Ankit: Let's update PROJ-456 deadline to April 10th.
[00:00:15] Priya: Sounds good. Also, we need to hire a backend engineer.
[00:00:30] Mrinal: Agreed. Let's also increase AWS spend limit by 40k for Q2.
[00:01:00] Ankit: I'll create a task to review the pricing model.
"""
    
    # Create initial state
    initial_state = PipelineState(
        meeting_id="example-meeting-001",
        meeting=None,
        decisions=[],
        classifier_outputs=[],
        approval_pending=[],
        workflow_results=[],
        errors=[],
        input_data=sample_transcript,
        input_format="txt",
        metadata={
            "title": "Q2 Planning Sync",
            "date": date(2026, 3, 20).isoformat(),
            "participants": ["Ankit", "Priya", "Mrinal"]
        }
    )
    
    print("\nStarting pipeline execution...")
    print(f"Meeting ID: {initial_state['meeting_id']}")
    print(f"Meeting Title: {initial_state['metadata']['title']}")
    
    # Configure pipeline execution
    config = {
        "configurable": {
            "thread_id": "example-thread-001"
        }
    }
    
    try:
        # Execute pipeline
        # Note: In LangGraph 0.0.26, we use invoke() for synchronous execution
        # The pipeline will execute all nodes in sequence
        
        print("\nNote: Full pipeline execution requires:")
        print("1. Database connection (PostgreSQL)")
        print("2. Gemini API key for decision extraction")
        print("3. Jira credentials for workflow execution")
        print("4. Slack credentials for approval gate")
        print("\nThis example demonstrates the pipeline structure.")
        print("For full execution, ensure all dependencies are configured.")
        
        # In a real scenario, you would call:
        # final_state = pipeline.invoke(initial_state, config)
        # print(f"\nPipeline completed!")
        # print(f"Decisions extracted: {len(final_state.get('decisions', []))}")
        # print(f"Workflows executed: {len(final_state.get('workflow_results', []))}")
        # print(f"Errors: {len(final_state.get('errors', []))}")
        
    except Exception as e:
        print(f"\nPipeline execution failed: {e}")
        print("This is expected if dependencies are not configured.")


if __name__ == "__main__":
    asyncio.run(run_example_pipeline())
