"""
Tests for FastAPI endpoints.
"""
import pytest
from datetime import date, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import AsyncClient

from main import app
from db.models import Meeting, Decision, AuditEntry


# Test API key for authenticated requests
TEST_API_KEY = "test-key-12345"


@pytest.fixture
def mock_db():
    """Create mock database session."""
    session = AsyncMock()
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    session.add = MagicMock()
    return session


@pytest.mark.asyncio
async def test_root_endpoint():
    """Test root endpoint."""
    async with AsyncClient(app=app, base_url="http://test") as client:
        response = await client.get("/")
        
        assert response.status_code == 200
        data = response.json()
        assert data["message"] == "MeetFlow AI Multi-Agent System"
        assert data["status"] == "running"


@pytest.mark.asyncio
async def test_health_check():
    """Test health check endpoint."""
    async with AsyncClient(app=app, base_url="http://test") as client:
        response = await client.get("/health")
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"


@pytest.mark.asyncio
async def test_get_meeting_not_found():
    """Test getting non-existent meeting."""
    with patch('api.meetings.get_db') as mock_get_db, \
         patch('api.auth.get_valid_api_keys', return_value={TEST_API_KEY}), \
         patch('api.meetings.get_cache') as mock_get_cache:
        # Mock cache to return None
        mock_cache = AsyncMock()
        mock_cache.get = AsyncMock(return_value=None)
        mock_get_cache.return_value = mock_cache
        
        # Mock database to return None
        mock_session = AsyncMock()
        mock_result = AsyncMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=None)
        mock_session.execute = AsyncMock(return_value=mock_result)
        
        async def mock_db_generator():
            yield mock_session
        
        mock_get_db.return_value = mock_db_generator()
        
        async with AsyncClient(app=app, base_url="http://test") as client:
            response = await client.get(
                "/api/meetings/nonexistent",
                headers={"X-API-Key": TEST_API_KEY}
            )
            
            assert response.status_code == 404
            assert "not found" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_get_decision_not_found():
    """Test getting non-existent decision."""
    with patch('api.meetings.get_db') as mock_get_db, \
         patch('api.auth.get_valid_api_keys', return_value={TEST_API_KEY}), \
         patch('api.meetings.get_cache') as mock_get_cache:
        # Mock cache to return None
        mock_cache = AsyncMock()
        mock_cache.get = AsyncMock(return_value=None)
        mock_get_cache.return_value = mock_cache
        
        # Mock database to return None
        mock_session = AsyncMock()
        mock_result = AsyncMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=None)
        mock_session.execute = AsyncMock(return_value=mock_result)
        
        async def mock_db_generator():
            yield mock_session
        
        mock_get_db.return_value = mock_db_generator()
        
        async with AsyncClient(app=app, base_url="http://test") as client:
            response = await client.get(
                "/api/decisions/nonexistent",
                headers={"X-API-Key": TEST_API_KEY}
            )
            
            assert response.status_code == 404
            assert "not found" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_approve_decision_not_found():
    """Test approving non-existent decision."""
    with patch('api.meetings.get_db') as mock_get_db, \
         patch('api.auth.get_valid_api_keys', return_value={TEST_API_KEY}), \
         patch('api.meetings.get_cache') as mock_get_cache:
        # Mock cache
        mock_cache = AsyncMock()
        mock_cache.delete = AsyncMock()
        mock_get_cache.return_value = mock_cache
        
        # Mock database to return None
        mock_session = AsyncMock()
        mock_result = AsyncMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=None)
        mock_session.execute = AsyncMock(return_value=mock_result)
        
        async def mock_db_generator():
            yield mock_session
        
        mock_get_db.return_value = mock_db_generator()
        
        async with AsyncClient(app=app, base_url="http://test") as client:
            response = await client.post(
                "/api/decisions/nonexistent/approve",
                json={"approver": "test_user"},
                headers={"X-API-Key": TEST_API_KEY}
            )
            
            assert response.status_code == 404
            assert "not found" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_reject_decision_not_found():
    """Test rejecting non-existent decision."""
    with patch('api.meetings.get_db') as mock_get_db, \
         patch('api.auth.get_valid_api_keys', return_value={TEST_API_KEY}), \
         patch('api.meetings.get_cache') as mock_get_cache:
        # Mock cache
        mock_cache = AsyncMock()
        mock_cache.delete = AsyncMock()
        mock_get_cache.return_value = mock_cache
        
        # Mock database to return None
        mock_session = AsyncMock()
        mock_result = AsyncMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=None)
        mock_session.execute = AsyncMock(return_value=mock_result)
        
        async def mock_db_generator():
            yield mock_session
        
        mock_get_db.return_value = mock_db_generator()
        
        async with AsyncClient(app=app, base_url="http://test") as client:
            response = await client.post(
                "/api/decisions/nonexistent/reject",
                json={"approver": "test_user"},
                headers={"X-API-Key": TEST_API_KEY}
            )
            
            assert response.status_code == 404
            assert "not found" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_get_audit_summary():
    """Test getting audit summary."""
    with patch('api.audit.get_db') as mock_get_db, \
         patch('api.auth.get_valid_api_keys', return_value={TEST_API_KEY}):
        # Mock database to return counts
        mock_session = AsyncMock()
        
        # Mock scalar results for counts
        mock_session.execute = AsyncMock(side_effect=[
            AsyncMock(scalar=MagicMock(return_value=5)),   # total_meetings
            AsyncMock(scalar=MagicMock(return_value=20)),  # total_decisions
            AsyncMock(scalar=MagicMock(return_value=100)), # total_audit_entries
            AsyncMock(scalar=MagicMock(return_value=90)),  # success_count
            AsyncMock(scalar=MagicMock(return_value=10)),  # failure_count
            AsyncMock(scalar=MagicMock(return_value=3)),   # pending_approvals
            AsyncMock(scalar=MagicMock(return_value=15)),  # completed_workflows
            AsyncMock(scalar=MagicMock(return_value=2)),   # failed_workflows
        ])
        
        async def mock_db_generator():
            yield mock_session
        
        mock_get_db.return_value = mock_db_generator()
        
        async with AsyncClient(app=app, base_url="http://test") as client:
            response = await client.get(
                "/api/audit/summary",
                headers={"X-API-Key": TEST_API_KEY}
            )
            
            assert response.status_code == 200
            data = response.json()
            assert data["total_meetings"] == 5
            assert data["total_decisions"] == 20
            assert data["total_audit_entries"] == 100
            assert data["success_rate"] == 90.0
            assert data["failure_rate"] == 10.0
            assert data["pending_approvals"] == 3
            assert data["completed_workflows"] == 15
            assert data["failed_workflows"] == 2


@pytest.mark.asyncio
async def test_ingest_meeting_invalid_format():
    """Test ingesting meeting with invalid format."""
    with patch('api.auth.get_valid_api_keys', return_value={TEST_API_KEY}):
        async with AsyncClient(app=app, base_url="http://test") as client:
            response = await client.post(
                "/api/meetings/ingest",
                json={
                    "input_format": "invalid",
                    "title": "Test Meeting",
                    "date": "2026-03-20",
                    "participants": ["Alice", "Bob"],
                    "content": "Test content"
                },
                headers={"X-API-Key": TEST_API_KEY}
            )
            
            assert response.status_code == 400
            assert "Invalid input format" in response.json()["detail"]


@pytest.mark.asyncio
async def test_ingest_meeting_invalid_date():
    """Test ingesting meeting with invalid date."""
    with patch('api.auth.get_valid_api_keys', return_value={TEST_API_KEY}):
        async with AsyncClient(app=app, base_url="http://test") as client:
            response = await client.post(
                "/api/meetings/ingest",
                json={
                    "input_format": "txt",
                    "title": "Test Meeting",
                    "date": "invalid-date",
                    "participants": ["Alice", "Bob"],
                    "content": "Test content"
                },
                headers={"X-API-Key": TEST_API_KEY}
            )
            
            assert response.status_code == 400
            assert "Invalid date format" in response.json()["detail"]
