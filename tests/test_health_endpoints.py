"""
Tests for health check endpoints.
"""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from httpx import AsyncClient

from main import app


@pytest.mark.asyncio
async def test_health_check_all_healthy():
    """Test health check endpoint when all services are healthy."""
    with patch("api.health.check_database") as mock_db, \
         patch("api.health.check_redis") as mock_redis, \
         patch("api.health.check_gemini_api") as mock_gemini, \
         patch("api.health.check_slack_api") as mock_slack, \
         patch("api.health.check_jira_api") as mock_jira:
        
        # Mock all checks as healthy
        from api.health import DependencyStatus
        
        mock_db.return_value = DependencyStatus(healthy=True, latency_ms=10.5)
        mock_redis.return_value = DependencyStatus(healthy=True, latency_ms=5.2)
        mock_gemini.return_value = DependencyStatus(healthy=True, latency_ms=150.0)
        mock_slack.return_value = DependencyStatus(healthy=True, latency_ms=80.0)
        mock_jira.return_value = DependencyStatus(healthy=True, latency_ms=120.0)
        
        async with AsyncClient(app=app, base_url="http://test") as client:
            response = await client.get("/api/health")
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["status"] == "healthy"
        assert "timestamp" in data
        assert "checks" in data
        
        # Verify all checks are present
        assert "database" in data["checks"]
        assert "redis" in data["checks"]
        assert "gemini_api" in data["checks"]
        assert "slack_api" in data["checks"]
        assert "jira_api" in data["checks"]
        
        # Verify all are healthy
        for check_name, check_data in data["checks"].items():
            assert check_data["healthy"] is True
            assert "latency_ms" in check_data


@pytest.mark.asyncio
async def test_health_check_degraded():
    """Test health check endpoint when some services are unhealthy."""
    with patch("api.health.check_database") as mock_db, \
         patch("api.health.check_redis") as mock_redis, \
         patch("api.health.check_gemini_api") as mock_gemini, \
         patch("api.health.check_slack_api") as mock_slack, \
         patch("api.health.check_jira_api") as mock_jira:
        
        from api.health import DependencyStatus
        
        # Mock some checks as unhealthy
        mock_db.return_value = DependencyStatus(healthy=True, latency_ms=10.5)
        mock_redis.return_value = DependencyStatus(healthy=False, latency_ms=0, error="Connection refused")
        mock_gemini.return_value = DependencyStatus(healthy=True, latency_ms=150.0)
        mock_slack.return_value = DependencyStatus(healthy=False, latency_ms=0, error="Invalid token")
        mock_jira.return_value = DependencyStatus(healthy=True, latency_ms=120.0)
        
        async with AsyncClient(app=app, base_url="http://test") as client:
            response = await client.get("/api/health")
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["status"] == "degraded"
        assert data["checks"]["redis"]["healthy"] is False
        assert data["checks"]["slack_api"]["healthy"] is False
        assert "error" in data["checks"]["redis"]
        assert "error" in data["checks"]["slack_api"]


@pytest.mark.asyncio
async def test_health_check_database_only():
    """Test individual database health check endpoint."""
    with patch("api.health.check_database") as mock_db:
        from api.health import DependencyStatus
        
        mock_db.return_value = DependencyStatus(healthy=True, latency_ms=10.5)
        
        async with AsyncClient(app=app, base_url="http://test") as client:
            response = await client.get("/api/health/database")
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["healthy"] is True
        assert data["latency_ms"] == 10.5


@pytest.mark.asyncio
async def test_health_check_circuit_breakers():
    """Test circuit breaker status endpoint."""
    from integrations.circuit_breaker import get_circuit_breaker, CircuitBreakerConfig
    
    # Create some circuit breakers
    config = CircuitBreakerConfig(failure_threshold=3)
    breaker1 = await get_circuit_breaker("test_service_1", config)
    breaker2 = await get_circuit_breaker("test_service_2", config)
    
    async with AsyncClient(app=app, base_url="http://test") as client:
        response = await client.get("/api/health/circuit-breakers")
    
    assert response.status_code == 200
    data = response.json()
    
    assert "timestamp" in data
    assert "circuit_breakers" in data
    assert "test_service_1" in data["circuit_breakers"]
    assert "test_service_2" in data["circuit_breakers"]
    
    # Verify circuit breaker stats structure
    cb_stats = data["circuit_breakers"]["test_service_1"]
    assert "state" in cb_stats
    assert "total_calls" in cb_stats
    assert "total_failures" in cb_stats
    assert "total_successes" in cb_stats
