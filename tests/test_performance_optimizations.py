"""
Tests for performance optimizations (Task 13.4).
"""
import pytest
import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

from integrations.cache import CacheClient, get_cache_client
from integrations.http_client import HTTPClientPool, get_http_client_pool
from integrations.request_queue import RequestQueue, QueuePriority
from api.rate_limiter import RateLimiter, RateLimitMiddleware
from db.database import engine


class TestCacheClient:
    """Test Redis caching functionality."""
    
    @pytest.mark.asyncio
    async def test_cache_set_and_get(self):
        """Test setting and getting values from cache."""
        cache = CacheClient("redis://localhost:6379/0")
        await cache.connect()
        
        # Set value
        key = "test:key"
        value = {"data": "test_value", "count": 42}
        result = await cache.set(key, value, ttl=60)
        assert result is True
        
        # Get value
        retrieved = await cache.get(key)
        assert retrieved == value
        
        # Cleanup
        await cache.delete(key)
        await cache.disconnect()
    
    @pytest.mark.asyncio
    async def test_cache_miss(self):
        """Test cache miss returns None."""
        cache = CacheClient("redis://localhost:6379/0")
        await cache.connect()
        
        result = await cache.get("nonexistent:key")
        assert result is None
        
        await cache.disconnect()
    
    @pytest.mark.asyncio
    async def test_cache_delete(self):
        """Test deleting values from cache."""
        cache = CacheClient("redis://localhost:6379/0")
        await cache.connect()
        
        key = "test:delete"
        await cache.set(key, {"data": "test"})
        
        # Verify it exists
        assert await cache.get(key) is not None
        
        # Delete
        await cache.delete(key)
        
        # Verify it's gone
        assert await cache.get(key) is None
        
        await cache.disconnect()
    
    @pytest.mark.asyncio
    async def test_cache_invalidate_pattern(self):
        """Test invalidating multiple keys by pattern."""
        cache = CacheClient("redis://localhost:6379/0")
        await cache.connect()
        
        # Set multiple keys
        await cache.set("meeting:001", {"id": "001"})
        await cache.set("meeting:002", {"id": "002"})
        await cache.set("decision:001", {"id": "001"})
        
        # Invalidate meeting keys
        deleted = await cache.invalidate_pattern("meeting:*")
        assert deleted == 2
        
        # Verify meeting keys are gone
        assert await cache.get("meeting:001") is None
        assert await cache.get("meeting:002") is None
        
        # Verify decision key still exists
        assert await cache.get("decision:001") is not None
        
        # Cleanup
        await cache.delete("decision:001")
        await cache.disconnect()


class TestHTTPClientPool:
    """Test HTTP client connection pooling."""
    
    @pytest.mark.asyncio
    async def test_client_creation(self):
        """Test HTTP client is created with connection pooling."""
        pool = HTTPClientPool(max_connections=50, max_keepalive_connections=10)
        client = await pool.get_client()
        
        assert client is not None
        # Verify client is configured (limits are internal to httpx)
        assert hasattr(client, '_transport')
        
        await pool.close()
    
    @pytest.mark.asyncio
    async def test_client_reuse(self):
        """Test HTTP client is reused across calls."""
        pool = HTTPClientPool()
        client1 = await pool.get_client()
        client2 = await pool.get_client()
        
        # Should be the same instance
        assert client1 is client2
        
        await pool.close()
    
    @pytest.mark.asyncio
    async def test_get_request(self):
        """Test making GET request with pooled client."""
        pool = HTTPClientPool()
        
        with patch('httpx.AsyncClient.get') as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_get.return_value = mock_response
            
            response = await pool.get("https://example.com")
            assert response.status_code == 200
            mock_get.assert_called_once()
        
        await pool.close()


class TestRequestQueue:
    """Test request queuing system."""
    
    @pytest.mark.asyncio
    async def test_queue_processing(self):
        """Test requests are processed from queue."""
        queue = RequestQueue(max_concurrent=2, max_queue_size=10)
        await queue.start()
        
        # Define test handler
        async def test_handler(value: int) -> int:
            await asyncio.sleep(0.1)
            return value * 2
        
        # Enqueue requests
        results = await asyncio.gather(
            queue.enqueue("req1", test_handler, 5),
            queue.enqueue("req2", test_handler, 10),
            queue.enqueue("req3", test_handler, 15)
        )
        
        assert results == [10, 20, 30]
        
        await queue.stop()
    
    @pytest.mark.asyncio
    async def test_queue_priority(self):
        """Test high priority requests are processed first."""
        queue = RequestQueue(max_concurrent=1, max_queue_size=10)
        await queue.start()
        
        results = []
        
        async def test_handler(value: str) -> str:
            await asyncio.sleep(0.05)
            results.append(value)
            return value
        
        # Enqueue with different priorities
        tasks = [
            queue.enqueue("req1", test_handler, "low", priority=QueuePriority.LOW),
            queue.enqueue("req2", test_handler, "high", priority=QueuePriority.HIGH),
            queue.enqueue("req3", test_handler, "normal", priority=QueuePriority.NORMAL)
        ]
        
        await asyncio.gather(*tasks)
        
        # High priority should be processed before normal and low
        assert results[0] == "high"
        
        await queue.stop()
    
    @pytest.mark.asyncio
    async def test_queue_stats(self):
        """Test queue statistics."""
        queue = RequestQueue(max_concurrent=2, max_queue_size=10)
        await queue.start()
        
        stats = queue.get_stats()
        assert stats["max_concurrent"] == 2
        assert stats["max_queue_size"] == 10
        assert stats["running"] is True
        assert stats["total_processed"] == 0
        
        await queue.stop()


class TestRateLimiter:
    """Test rate limiting functionality."""
    
    def test_rate_limit_allows_requests(self):
        """Test rate limiter allows requests within limit."""
        limiter = RateLimiter(max_requests=5, window_seconds=60)
        
        # Should allow first 5 requests
        for i in range(5):
            assert limiter.is_allowed("client1") is True
        
        # Should block 6th request
        assert limiter.is_allowed("client1") is False
    
    def test_rate_limit_per_client(self):
        """Test rate limiting is per client."""
        limiter = RateLimiter(max_requests=3, window_seconds=60)
        
        # Client 1 makes 3 requests
        for i in range(3):
            assert limiter.is_allowed("client1") is True
        
        # Client 1 is blocked
        assert limiter.is_allowed("client1") is False
        
        # Client 2 can still make requests
        assert limiter.is_allowed("client2") is True
    
    def test_rate_limit_window_reset(self):
        """Test rate limit resets after window expires."""
        limiter = RateLimiter(max_requests=2, window_seconds=1)
        
        # Make 2 requests
        assert limiter.is_allowed("client1") is True
        assert limiter.is_allowed("client1") is True
        
        # Should be blocked
        assert limiter.is_allowed("client1") is False
        
        # Wait for window to expire
        time.sleep(1.1)
        
        # Should be allowed again
        assert limiter.is_allowed("client1") is True
    
    def test_get_remaining_requests(self):
        """Test getting remaining requests."""
        limiter = RateLimiter(max_requests=5, window_seconds=60)
        
        assert limiter.get_remaining("client1") == 5
        
        limiter.is_allowed("client1")
        assert limiter.get_remaining("client1") == 4
        
        limiter.is_allowed("client1")
        assert limiter.get_remaining("client1") == 3


class TestDatabaseConnectionPooling:
    """Test database connection pooling."""
    
    def test_engine_has_connection_pool(self):
        """Test database engine is configured with connection pooling."""
        # Check pool configuration
        assert engine.pool.size() >= 0  # Pool exists
        assert hasattr(engine.pool, '_pool')  # Has pool attribute
    
    @pytest.mark.asyncio
    async def test_concurrent_database_connections(self):
        """Test multiple concurrent database connections."""
        from db.database import get_db
        
        async def get_connection():
            async for session in get_db():
                # Simulate some work
                await asyncio.sleep(0.1)
                return True
        
        # Create multiple concurrent connections
        results = await asyncio.gather(
            *[get_connection() for _ in range(5)]
        )
        
        assert all(results)


@pytest.mark.asyncio
async def test_integration_cache_and_api():
    """Integration test: Cache with API endpoints."""
    from api.meetings import get_cache
    from integrations.cache import meeting_cache_key
    
    cache = get_cache()
    await cache.connect()
    
    # Simulate caching meeting data
    meeting_id = "test-meeting-123"
    meeting_data = {
        "meeting_id": meeting_id,
        "title": "Test Meeting",
        "date": "2026-03-20",
        "participants": ["Alice", "Bob"],
        "status": "completed",
        "decisions": []
    }
    
    key = meeting_cache_key(meeting_id)
    await cache.set(key, meeting_data, ttl=60)
    
    # Retrieve from cache
    cached = await cache.get(key)
    assert cached == meeting_data
    
    # Cleanup
    await cache.delete(key)
    await cache.disconnect()


@pytest.mark.asyncio
async def test_integration_http_client_pool():
    """Integration test: HTTP client pool with external API."""
    pool = get_http_client_pool()
    
    # Mock external API call
    with patch('httpx.AsyncClient.get') as mock_get:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "ok"}
        mock_get.return_value = mock_response
        
        response = await pool.get("https://api.example.com/status")
        assert response.status_code == 200
    
    await pool.close()
