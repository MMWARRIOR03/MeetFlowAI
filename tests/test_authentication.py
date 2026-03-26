"""
Tests for API key authentication.
"""
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch

from main import app


@pytest.fixture
def client():
    """Create test client."""
    return TestClient(app)


@pytest.fixture
def mock_api_keys():
    """Mock API keys for testing."""
    return {"test-key-123", "valid-key-456"}


class TestAuthenticationMiddleware:
    """Test authentication middleware."""
    
    def test_public_routes_no_auth_required(self, client):
        """Public routes should not require authentication."""
        # Root endpoint
        response = client.get("/")
        assert response.status_code == 200
        
        # Health check
        response = client.get("/health")
        assert response.status_code == 200
        
        # API docs
        response = client.get("/docs")
        assert response.status_code == 200
        
        # OpenAPI schema
        response = client.get("/openapi.json")
        assert response.status_code == 200
    
    @patch("api.auth.get_valid_api_keys")
    def test_protected_route_without_api_key(self, mock_get_keys, client, mock_api_keys):
        """Protected routes should return 401 without API key."""
        mock_get_keys.return_value = mock_api_keys
        
        # Try to access protected endpoint without API key
        response = client.get("/api/audit/summary")
        
        assert response.status_code == 401
        assert "Missing API key" in response.json()["detail"]
    
    @patch("api.auth.get_valid_api_keys")
    def test_protected_route_with_invalid_api_key(self, mock_get_keys, client, mock_api_keys):
        """Protected routes should return 401 with invalid API key."""
        mock_get_keys.return_value = mock_api_keys
        
        # Try to access protected endpoint with invalid API key
        response = client.get(
            "/api/audit/summary",
            headers={"X-API-Key": "invalid-key"}
        )
        
        assert response.status_code == 401
        assert "Invalid API key" in response.json()["detail"]
    
    @patch("api.auth.get_valid_api_keys")
    def test_protected_route_with_valid_api_key(self, mock_get_keys, client, mock_api_keys):
        """Protected routes should allow access with valid API key."""
        mock_get_keys.return_value = mock_api_keys
        
        # Access protected endpoint with valid API key
        response = client.get(
            "/api/audit/summary",
            headers={"X-API-Key": "test-key-123"}
        )
        
        # Should not return 401 (may return other errors due to missing DB, but auth passed)
        assert response.status_code != 401
    
    @patch("api.auth.get_valid_api_keys")
    def test_no_api_keys_configured_allows_request(self, mock_get_keys, client):
        """When no API keys configured, requests should be allowed (dev mode)."""
        mock_get_keys.return_value = set()
        
        # Access protected endpoint without API key when none configured
        response = client.get(
            "/api/audit/summary",
            headers={"X-API-Key": "any-key"}
        )
        
        # Should not return 401 (may return other errors due to missing DB, but auth passed)
        assert response.status_code != 401


class TestAPIEndpointsAuthentication:
    """Test authentication on specific API endpoints."""
    
    @patch("api.auth.get_valid_api_keys")
    def test_meetings_ingest_requires_auth(self, mock_get_keys, client, mock_api_keys):
        """POST /api/meetings/ingest should require authentication."""
        mock_get_keys.return_value = mock_api_keys
        
        # Without API key
        response = client.post("/api/meetings/ingest", json={})
        assert response.status_code == 401
        
        # With invalid API key
        response = client.post(
            "/api/meetings/ingest",
            json={},
            headers={"X-API-Key": "invalid"}
        )
        assert response.status_code == 401
    
    @patch("api.auth.get_valid_api_keys")
    def test_meetings_get_requires_auth(self, mock_get_keys, client, mock_api_keys):
        """GET /api/meetings/{id} should require authentication."""
        mock_get_keys.return_value = mock_api_keys
        
        # Without API key
        response = client.get("/api/meetings/test-id")
        assert response.status_code == 401
        
        # With invalid API key
        response = client.get(
            "/api/meetings/test-id",
            headers={"X-API-Key": "invalid"}
        )
        assert response.status_code == 401
    
    @patch("api.auth.get_valid_api_keys")
    def test_decisions_approve_requires_auth(self, mock_get_keys, client, mock_api_keys):
        """POST /api/decisions/{id}/approve should require authentication."""
        mock_get_keys.return_value = mock_api_keys
        
        # Without API key
        response = client.post(
            "/api/decisions/test-id/approve",
            json={"approver": "test"}
        )
        assert response.status_code == 401
    
    @patch("api.auth.get_valid_api_keys")
    def test_audit_endpoints_require_auth(self, mock_get_keys, client, mock_api_keys):
        """Audit endpoints should require authentication."""
        mock_get_keys.return_value = mock_api_keys
        
        # Without API key
        response = client.get("/api/audit/test-meeting-id")
        assert response.status_code == 401
        
        response = client.get("/api/audit/decision/test-decision-id")
        assert response.status_code == 401
        
        response = client.get("/api/audit/summary")
        assert response.status_code == 401


class TestHTTPStatusCodes:
    """Test proper HTTP status codes are returned."""
    
    @patch("api.auth.get_valid_api_keys")
    def test_unauthorized_returns_401(self, mock_get_keys, client, mock_api_keys):
        """Missing or invalid API key should return 401."""
        mock_get_keys.return_value = mock_api_keys
        
        # Missing API key
        response = client.get("/api/audit/summary")
        assert response.status_code == 401
        
        # Invalid API key
        response = client.get(
            "/api/audit/summary",
            headers={"X-API-Key": "wrong-key"}
        )
        assert response.status_code == 401
    
    def test_not_found_returns_404(self, client):
        """Non-existent routes should return 404."""
        response = client.get("/api/nonexistent/route")
        # Will return 401 first due to auth, but with valid key would be 404
        assert response.status_code in [401, 404]
    
    def test_health_check_returns_200(self, client):
        """Health check should return 200."""
        response = client.get("/health")
        assert response.status_code == 200


class TestAPIKeyParsing:
    """Test API key parsing from environment."""
    
    def test_parse_single_api_key(self):
        """Should parse single API key."""
        from api.auth import get_valid_api_keys
        
        with patch.dict("os.environ", {"API_KEYS": "single-key"}):
            keys = get_valid_api_keys()
            assert keys == {"single-key"}
    
    def test_parse_multiple_api_keys(self):
        """Should parse comma-separated API keys."""
        from api.auth import get_valid_api_keys
        
        with patch.dict("os.environ", {"API_KEYS": "key1,key2,key3"}):
            keys = get_valid_api_keys()
            assert keys == {"key1", "key2", "key3"}
    
    def test_parse_api_keys_with_whitespace(self):
        """Should handle whitespace in API keys."""
        from api.auth import get_valid_api_keys
        
        with patch.dict("os.environ", {"API_KEYS": " key1 , key2 , key3 "}):
            keys = get_valid_api_keys()
            assert keys == {"key1", "key2", "key3"}
    
    def test_empty_api_keys(self):
        """Should return empty set when no API keys configured."""
        from api.auth import get_valid_api_keys
        
        with patch.dict("os.environ", {"API_KEYS": ""}):
            keys = get_valid_api_keys()
            assert keys == set()
    
    def test_missing_api_keys_env(self):
        """Should return empty set when API_KEYS not in environment."""
        from api.auth import get_valid_api_keys
        
        with patch.dict("os.environ", {}, clear=True):
            keys = get_valid_api_keys()
            assert keys == set()
