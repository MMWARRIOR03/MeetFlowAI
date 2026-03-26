"""
End-to-end integration test for MeetFlow AI demo fixture.
Tests complete pipeline execution with q2_planning_sync.vtt fixture.
"""
import pytest
import os
from datetime import date
from pathlib import Path
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agents.ingestion_agent import IngestionAgent
from agents.extraction_agent import ExtractionAgent
from agents.classifier_agent import ClassifierAgent
from integrations.gemini import GeminiClient
from schemas.base import InputFormat, MeetingMetadata, WorkflowType
from db.models import Meeting, Decision, AuditEntry
from db.database import get_db_session


@pytest.fixture
def demo_fixture_path():
    """Path to demo fixture file."""
    return Path(__file__).parent.parent / "fixtures" / "q2_planning_sync.vtt"


@pytest.fixture
def demo_fixture_content(demo_fixture_path):
    """Load demo fixture content."""
    with open(demo_fixture_path, 'r') as f:
        return f.read()


@pytest.fixture
def meeting_metadata():
    """Metadata for demo meeting."""
    return MeetingMetadata(
        title="Q2 Planning Sync",
        date=date(2026, 3, 26),
        participants=["Ankit", "Priya", "Mrinal"]
    )


@pytest.mark.asyncio
async def test_demo_fixture_end_to_end(
    demo_fixture_content,
    meeting_metadata,
    db_session: AsyncSession
):
    """
    Test complete pipeline execution with demo fixture.
    
    Verifies:
    - 4 decisions extracted (dec_001, dec_002, dec_003, dec_004)
    - 1 ambiguous item extracted
    - dec_001 (jira_update) is auto-triggered
    - dec_002 (hr_hiring) requires approval
    - dec_003 (procurement_request) requires approval
    - dec_004 (jira_create) is auto-triggered
    - All AuditEntry records are created
    """
    # Initialize Gemini client
    api_key = os.getenv("GEMINI_API_KEY", "test-api-key")
    gemini_client = GeminiClient(api_key=api_key)
    
    # Step 1: Ingestion
    ingestion_agent = IngestionAgent(gemini_client=gemini_client)
    normalized_meeting = await ingestion_agent.ingest(
        input_data=demo_fixture_content,
        input_format=InputFormat.VTT,
        metadata=meeting_metadata
    )
    
    # Verify ingestion
    assert normalized_meeting.meeting_id is not None
    assert normalized_meeting.title == "Q2 Planning Sync"
    assert normalized_meeting.date == date(2026, 3, 26)
    assert len(normalized_meeting.participants) == 3
    assert len(normalized_meeting.transcript) > 0
    
    # Verify ingestion audit entry
    audit_query = select(AuditEntry).where(
        AuditEntry.meeting_id == normalized_meeting.meeting_id,
        AuditEntry.agent == "IngestionAgent"
    )
    result = await db_session.execute(audit_query)
    ingestion_audits = result.scalars().all()
    assert len(ingestion_audits) > 0
    assert any(a.outcome == "success" for a in ingestion_audits)
    
    # Step 2: Extraction
    extraction_agent = ExtractionAgent(
        gemini_client=gemini_client,
        db_session=db_session
    )
    extraction_output = await extraction_agent.extract_decisions(meeting=normalized_meeting)
    
    # Verify extraction output
    assert len(extraction_output.decisions) == 4, \
        f"Expected 4 decisions, got {len(extraction_output.decisions)}"
    assert len(extraction_output.ambiguous_items) == 1, \
        f"Expected 1 ambiguous item, got {len(extraction_output.ambiguous_items)}"
    
    # Verify decision IDs
    decision_ids = [d.decision_id for d in extraction_output.decisions]
    assert "dec_001" in decision_ids
    assert "dec_002" in decision_ids
    assert "dec_003" in decision_ids
    assert "dec_004" in decision_ids
    
    # Verify extraction audit entries
    extraction_audit_query = select(AuditEntry).where(
        AuditEntry.meeting_id == normalized_meeting.meeting_id,
        AuditEntry.agent == "ExtractionAgent"
    )
    result = await db_session.execute(extraction_audit_query)
    extraction_audits = result.scalars().all()
    assert len(extraction_audits) >= 4  # At least one per decision
    
    # Step 3: Classification
    classifier_agent = ClassifierAgent(
        gemini_client=gemini_client,
        db_session=db_session
    )
    
    classifier_outputs = []
    for decision in extraction_output.decisions:
        classifier_output = await classifier_agent.classify_decision(
            decision=decision,
            meeting_context=normalized_meeting
        )
        classifier_outputs.append(classifier_output)
    
    # Verify classification outputs
    assert len(classifier_outputs) == 4
    
    # Find specific decisions by ID
    dec_001 = next((d for d in extraction_output.decisions if d.decision_id == "dec_001"), None)
    dec_002 = next((d for d in extraction_output.decisions if d.decision_id == "dec_002"), None)
    dec_003 = next((d for d in extraction_output.decisions if d.decision_id == "dec_003"), None)
    dec_004 = next((d for d in extraction_output.decisions if d.decision_id == "dec_004"), None)
    
    assert dec_001 is not None, "dec_001 not found"
    assert dec_002 is not None, "dec_002 not found"
    assert dec_003 is not None, "dec_003 not found"
    assert dec_004 is not None, "dec_004 not found"
    
    # Find classifier outputs by decision ID
    class_001 = next((c for c in classifier_outputs if c.decision_id == "dec_001"), None)
    class_002 = next((c for c in classifier_outputs if c.decision_id == "dec_002"), None)
    class_003 = next((c for c in classifier_outputs if c.decision_id == "dec_003"), None)
    class_004 = next((c for c in classifier_outputs if c.decision_id == "dec_004"), None)
    
    # Verify dec_001: jira_update, auto_trigger
    assert class_001 is not None
    assert class_001.workflow_type == WorkflowType.JIRA_UPDATE
    assert dec_001.auto_trigger is True
    assert dec_001.owner == "Ankit"
    assert dec_001.deadline == date(2026, 4, 10)
    
    # Verify dec_002: hr_hiring, requires_approval
    assert class_002 is not None
    assert class_002.workflow_type == WorkflowType.HR_HIRING
    assert dec_002.requires_approval is True
    assert dec_002.owner == "Priya"
    assert dec_002.deadline == date(2026, 3, 28)
    
    # Verify dec_003: procurement_request, requires_approval
    assert class_003 is not None
    assert class_003.workflow_type == WorkflowType.PROCUREMENT_REQUEST
    assert dec_003.requires_approval is True
    assert dec_003.owner == "Mrinal"
    assert dec_003.deadline == date(2026, 3, 26)
    
    # Verify dec_004: jira_create, auto_trigger
    assert class_004 is not None
    assert class_004.workflow_type == WorkflowType.JIRA_CREATE
    assert dec_004.auto_trigger is True
    assert dec_004.owner == "Mrinal"
    assert dec_004.deadline == date(2026, 4, 1)
    
    # Verify classification audit entries
    classification_audit_query = select(AuditEntry).where(
        AuditEntry.meeting_id == normalized_meeting.meeting_id,
        AuditEntry.agent == "ClassifierAgent"
    )
    result = await db_session.execute(classification_audit_query)
    classification_audits = result.scalars().all()
    assert len(classification_audits) >= 4  # At least one per decision
    
    # Verify ambiguous item
    assert len(extraction_output.ambiguous_items) == 1
    ambiguous = extraction_output.ambiguous_items[0]
    assert "pricing model" in ambiguous.description.lower() or \
           "review" in ambiguous.description.lower()


@pytest.mark.asyncio
async def test_demo_fixture_ingestion_only(
    demo_fixture_content,
    meeting_metadata
):
    """
    Test ingestion of demo fixture in isolation.
    """
    # Initialize Gemini client
    api_key = os.getenv("GEMINI_API_KEY", "test-api-key")
    gemini_client = GeminiClient(api_key=api_key)
    
    # Ingest demo fixture
    ingestion_agent = IngestionAgent(gemini_client=gemini_client)
    normalized_meeting = await ingestion_agent.ingest(
        input_data=demo_fixture_content,
        input_format=InputFormat.VTT,
        metadata=meeting_metadata
    )
    
    # Verify transcript segments
    assert len(normalized_meeting.transcript) > 0
    
    # Verify speakers are extracted correctly
    speakers = {seg.speaker for seg in normalized_meeting.transcript}
    assert "Ankit" in speakers
    assert "Priya" in speakers
    assert "Mrinal" in speakers
    
    # Verify timestamps are in correct format
    for segment in normalized_meeting.transcript:
        assert segment.timestamp.count(':') == 2
        parts = segment.timestamp.split(':')
        assert len(parts) == 3
        assert all(p.isdigit() for p in parts)


@pytest.mark.asyncio
async def test_demo_fixture_extraction_only(
    demo_fixture_content,
    meeting_metadata,
    db_session: AsyncSession
):
    """
    Test extraction from demo fixture in isolation.
    """
    # Initialize clients and agents
    api_key = os.getenv("GEMINI_API_KEY", "test-api-key")
    gemini_client = GeminiClient(api_key=api_key)
    
    # Ingest first
    ingestion_agent = IngestionAgent(gemini_client=gemini_client)
    normalized_meeting = await ingestion_agent.ingest(
        input_data=demo_fixture_content,
        input_format=InputFormat.VTT,
        metadata=meeting_metadata
    )
    
    # Extract decisions
    extraction_agent = ExtractionAgent(
        gemini_client=gemini_client,
        db_session=db_session
    )
    extraction_output = await extraction_agent.extract_decisions(meeting=normalized_meeting)
    
    # Verify counts
    assert len(extraction_output.decisions) == 4
    assert len(extraction_output.ambiguous_items) == 1
    
    # Verify all decisions have required fields
    for decision in extraction_output.decisions:
        assert decision.decision_id
        assert decision.description
        assert decision.owner
        assert decision.deadline
        assert 0.0 <= decision.confidence <= 1.0
        assert decision.raw_quote


@pytest.mark.asyncio
async def test_demo_fixture_classification_only(
    demo_fixture_content,
    meeting_metadata,
    db_session: AsyncSession
):
    """
    Test classification of demo fixture decisions in isolation.
    """
    # Initialize clients and agents
    api_key = os.getenv("GEMINI_API_KEY", "test-api-key")
    gemini_client = GeminiClient(api_key=api_key)
    
    # Ingest and extract
    ingestion_agent = IngestionAgent(gemini_client=gemini_client)
    normalized_meeting = await ingestion_agent.ingest(
        input_data=demo_fixture_content,
        input_format=InputFormat.VTT,
        metadata=meeting_metadata
    )
    
    extraction_agent = ExtractionAgent(
        gemini_client=gemini_client,
        db_session=db_session
    )
    extraction_output = await extraction_agent.extract_decisions(meeting=normalized_meeting)
    
    # Classify all decisions
    classifier_agent = ClassifierAgent(
        gemini_client=gemini_client,
        db_session=db_session
    )
    
    classifier_outputs = []
    for decision in extraction_output.decisions:
        classifier_output = await classifier_agent.classify_decision(
            decision=decision,
            meeting_context=normalized_meeting
        )
        classifier_outputs.append(classifier_output)
    
    # Verify workflow types
    workflow_types = {c.workflow_type for c in classifier_outputs}
    assert WorkflowType.JIRA_UPDATE in workflow_types
    assert WorkflowType.JIRA_CREATE in workflow_types
    assert WorkflowType.HR_HIRING in workflow_types
    assert WorkflowType.PROCUREMENT_REQUEST in workflow_types
    
    # Verify approval requirements
    auto_trigger_count = sum(1 for c in classifier_outputs if not c.requires_approval)
    requires_approval_count = sum(1 for c in classifier_outputs if c.requires_approval)
    
    assert auto_trigger_count == 2, f"Expected 2 auto-trigger decisions, got {auto_trigger_count}"
    assert requires_approval_count == 2, f"Expected 2 approval-required decisions, got {requires_approval_count}"


@pytest.mark.asyncio
async def test_demo_fixture_audit_trail(
    demo_fixture_content,
    meeting_metadata,
    db_session: AsyncSession
):
    """
    Test that all AuditEntry records are created during pipeline execution.
    """
    # Initialize clients and agents
    api_key = os.getenv("GEMINI_API_KEY", "test-api-key")
    gemini_client = GeminiClient(api_key=api_key)
    
    # Execute pipeline steps
    ingestion_agent = IngestionAgent(gemini_client=gemini_client)
    normalized_meeting = await ingestion_agent.ingest(
        input_data=demo_fixture_content,
        input_format=InputFormat.VTT,
        metadata=meeting_metadata
    )
    
    extraction_agent = ExtractionAgent(
        gemini_client=gemini_client,
        db_session=db_session
    )
    extraction_output = await extraction_agent.extract_decisions(meeting=normalized_meeting)
    
    classifier_agent = ClassifierAgent(
        gemini_client=gemini_client,
        db_session=db_session
    )
    
    for decision in extraction_output.decisions:
        await classifier_agent.classify_decision(
            decision=decision,
            meeting_context=normalized_meeting
        )
    
    # Query all audit entries for this meeting
    audit_query = select(AuditEntry).where(
        AuditEntry.meeting_id == normalized_meeting.meeting_id
    ).order_by(AuditEntry.created_at)
    
    result = await db_session.execute(audit_query)
    audit_entries = result.scalars().all()
    
    # Verify audit entries exist
    assert len(audit_entries) > 0, "No audit entries found"
    
    # Verify audit entries by agent
    agents = {entry.agent for entry in audit_entries}
    assert "IngestionAgent" in agents
    assert "ExtractionAgent" in agents
    assert "ClassifierAgent" in agents
    
    # Verify audit entries by outcome
    outcomes = [entry.outcome for entry in audit_entries]
    assert "success" in outcomes
    
    # Verify audit entries for each decision
    decision_ids = {entry.decision_id for entry in audit_entries if entry.decision_id}
    assert "dec_001" in decision_ids
    assert "dec_002" in decision_ids
    assert "dec_003" in decision_ids
    assert "dec_004" in decision_ids
    
    # Verify audit trail completeness
    ingestion_audits = [e for e in audit_entries if e.agent == "IngestionAgent"]
    extraction_audits = [e for e in audit_entries if e.agent == "ExtractionAgent"]
    classification_audits = [e for e in audit_entries if e.agent == "ClassifierAgent"]
    
    assert len(ingestion_audits) >= 1, "Missing ingestion audit entries"
    assert len(extraction_audits) >= 4, "Missing extraction audit entries"
    assert len(classification_audits) >= 4, "Missing classification audit entries"


@pytest.mark.asyncio
async def test_demo_fixture_decision_details(
    demo_fixture_content,
    meeting_metadata,
    db_session: AsyncSession
):
    """
    Test specific decision details from demo fixture.
    Verifies each decision matches expected values.
    """
    # Initialize and run pipeline
    api_key = os.getenv("GEMINI_API_KEY", "test-api-key")
    gemini_client = GeminiClient(api_key=api_key)
    
    ingestion_agent = IngestionAgent(gemini_client=gemini_client)
    normalized_meeting = await ingestion_agent.ingest(
        input_data=demo_fixture_content,
        input_format=InputFormat.VTT,
        metadata=meeting_metadata
    )
    
    extraction_agent = ExtractionAgent(
        gemini_client=gemini_client,
        db_session=db_session
    )
    extraction_output = await extraction_agent.extract_decisions(meeting=normalized_meeting)
    
    # Find specific decisions
    decisions_by_id = {d.decision_id: d for d in extraction_output.decisions}
    
    # Verify dec_001: jira_update
    dec_001 = decisions_by_id.get("dec_001")
    assert dec_001 is not None
    assert dec_001.owner == "Ankit"
    assert dec_001.deadline == date(2026, 4, 10)
    assert dec_001.auto_trigger is True
    assert "PROJ-456" in dec_001.description or "PROJ-456" in dec_001.raw_quote
    
    # Verify dec_002: hr_hiring
    dec_002 = decisions_by_id.get("dec_002")
    assert dec_002 is not None
    assert dec_002.owner == "Priya"
    assert dec_002.deadline == date(2026, 3, 28)
    assert dec_002.requires_approval is True
    assert "backend engineer" in dec_002.description.lower() or \
           "backend engineer" in dec_002.raw_quote.lower()
    
    # Verify dec_003: procurement_request
    dec_003 = decisions_by_id.get("dec_003")
    assert dec_003 is not None
    assert dec_003.owner == "Mrinal"
    assert dec_003.deadline == date(2026, 3, 26)
    assert dec_003.requires_approval is True
    assert "AWS" in dec_003.description or "AWS" in dec_003.raw_quote
    assert "40" in dec_003.description or "40k" in dec_003.raw_quote or \
           "40" in dec_003.description or "40000" in dec_003.raw_quote
    
    # Verify dec_004: jira_create
    dec_004 = decisions_by_id.get("dec_004")
    assert dec_004 is not None
    assert dec_004.owner == "Mrinal"
    assert dec_004.deadline == date(2026, 4, 1)
    assert dec_004.auto_trigger is True
    assert "mobile" in dec_004.description.lower() or \
           "mobile" in dec_004.raw_quote.lower()


@pytest.mark.asyncio
async def test_demo_fixture_ambiguous_item(
    demo_fixture_content,
    meeting_metadata,
    db_session: AsyncSession
):
    """
    Test that ambiguous item is correctly identified.
    """
    # Initialize and run extraction
    api_key = os.getenv("GEMINI_API_KEY", "test-api-key")
    gemini_client = GeminiClient(api_key=api_key)
    
    ingestion_agent = IngestionAgent(gemini_client=gemini_client)
    normalized_meeting = await ingestion_agent.ingest(
        input_data=demo_fixture_content,
        input_format=InputFormat.VTT,
        metadata=meeting_metadata
    )
    
    extraction_agent = ExtractionAgent(
        gemini_client=gemini_client,
        db_session=db_session
    )
    extraction_output = await extraction_agent.extract_decisions(meeting=normalized_meeting)
    
    # Verify ambiguous item
    assert len(extraction_output.ambiguous_items) == 1
    ambiguous = extraction_output.ambiguous_items[0]
    
    # Should be about pricing model review (no clear deadline)
    assert ambiguous.description
    assert ambiguous.reason
    assert ambiguous.raw_quote
    assert "pricing" in ambiguous.description.lower() or \
           "pricing" in ambiguous.raw_quote.lower()
