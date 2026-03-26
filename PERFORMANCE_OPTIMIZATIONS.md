# Performance Optimizations (Task 13.4)

This document describes the performance optimizations implemented in MeetFlow AI to handle high volumes of meetings efficiently.

## Overview

The system now includes four key performance optimizations:

1. **Connection Pooling** for database and HTTP clients
2. **Redis Caching** for frequently accessed data
3. **Rate Limiting** on API endpoints (100 req/min per client)
4. **Request Queuing** for handling heavy load

## 1. Database Connection Pooling

### Implementation
- **File**: `db/database.py`
- **Pool Type**: `AsyncAdaptedQueuePool`
- **Configuration**:
  - Pool size: 20 connections
  - Max overflow: 10 additional connections
  - Pool timeout: 30 seconds
  - Pool recycle: 3600 seconds (1 hour)
  - Pre-ping: Enabled (verifies connections before use)

### Benefits
- Reuses database connections across requests
- Reduces connection overhead
- Handles concurrent requests efficiently
- Automatically recycles stale connections

## 2. HTTP Client Connection Pooling

### Implementation
- **File**: `integrations/http_client.py`
- **Class**: `HTTPClientPool`
- **Configuration**:
  - Max connections: 100
  - Max keepalive connections: 20
  - Timeout: 30 seconds

### Usage
```python
from integrations.http_client import get_http_client_pool

pool = get_http_client_pool()
response = await pool.get("https://api.example.com/data")
```

### Benefits
- Reuses HTTP connections for external API calls
- Reduces connection establishment overhead
- Improves throughput for Jira, Slack, and other integrations
- Automatic connection management

## 3. Redis Caching

### Implementation
- **File**: `integrations/cache.py`
- **Class**: `CacheClient`
- **Cache Keys**:
  - `meeting:{meeting_id}` - Meeting metadata (TTL: 1 hour)
  - `decision:{decision_id}` - Decision status (TTL: 5 minutes)
  - `meeting:{meeting_id}:decisions` - Meeting decisions list

### Usage
```python
from integrations.cache import get_cache_client, meeting_cache_key

cache = get_cache_client()
await cache.connect()

# Set value
await cache.set(meeting_cache_key(meeting_id), data, ttl=3600)

# Get value
data = await cache.get(meeting_cache_key(meeting_id))

# Invalidate pattern
await cache.invalidate_pattern("meeting:*")
```

### Cached Endpoints
- `GET /api/meetings/{meeting_id}` - Caches meeting details
- `GET /api/decisions/{decision_id}` - Caches decision status

### Cache Invalidation
Cache is automatically invalidated when:
- Decision is approved/rejected
- Meeting status changes
- Workflow execution completes

### Benefits
- Reduces database queries for frequently accessed data
- Improves response times for read operations
- Reduces load on PostgreSQL
- Supports pattern-based invalidation

## 4. Rate Limiting

### Implementation
- **File**: `api/rate_limiter.py`
- **Class**: `RateLimitMiddleware`
- **Algorithm**: Token bucket
- **Configuration**:
  - Max requests: 100 per minute per client
  - Window: 60 seconds

### Client Identification
1. API key from `X-API-Key` header (preferred)
2. IP address from `X-Forwarded-For` header
3. Direct client IP address

### Response Headers
```
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 95
X-RateLimit-Window: 60
```

### Error Response (429 Too Many Requests)
```json
{
  "error": "Rate limit exceeded",
  "limit": 100,
  "window": "60s",
  "remaining": 0,
  "retry_after": 60
}
```

### Excluded Endpoints
- `/health`
- `/`
- `/docs`
- `/redoc`
- `/openapi.json`

### Benefits
- Prevents API abuse
- Ensures fair resource allocation
- Protects against DDoS attacks
- Per-client rate limiting

## 5. Request Queuing

### Implementation
- **File**: `integrations/request_queue.py`
- **Class**: `RequestQueue`
- **Configuration**:
  - Max concurrent: 10 requests
  - Max queue size: 1000 requests

### Priority Levels
- `HIGH` (1) - Critical requests
- `NORMAL` (2) - Standard requests
- `LOW` (3) - Background tasks

### Usage
```python
from integrations.request_queue import get_request_queue, QueuePriority

queue = get_request_queue()
await queue.start()

# Enqueue request
result = await queue.enqueue(
    "req-123",
    async_handler_function,
    arg1, arg2,
    priority=QueuePriority.HIGH
)
```

### Queue Statistics
```python
stats = queue.get_stats()
# {
#   "active_requests": 5,
#   "queued_requests": 12,
#   "total_processed": 1234,
#   "total_failed": 3,
#   "max_concurrent": 10,
#   "max_queue_size": 1000,
#   "running": true
# }
```

### Benefits
- Prevents system overload during traffic spikes
- Ensures fair request processing (FIFO with priority)
- Graceful degradation under heavy load
- Automatic worker management

## Application Lifecycle

### Startup
The FastAPI application initializes all performance components on startup:

```python
# main.py lifespan manager
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    cache_client = get_cache_client(redis_url)
    await cache_client.connect()
    
    http_client_pool = get_http_client_pool()
    
    request_queue = get_request_queue()
    await request_queue.start()
    
    yield
    
    # Shutdown
    await cache_client.disconnect()
    await http_client_pool.close()
    await request_queue.stop()
```

### Middleware Stack
1. CORS middleware
2. Rate limiting middleware
3. Application routes

## Testing

### Test Coverage
- **File**: `tests/test_performance_optimizations.py`
- **Tests**: 18 tests covering all components
- **Coverage**:
  - Cache operations (set, get, delete, pattern invalidation)
  - HTTP client pooling (creation, reuse, requests)
  - Request queue (processing, priority, stats)
  - Rate limiting (per-client, window reset, remaining requests)
  - Database connection pooling
  - Integration tests

### Running Tests
```bash
pytest tests/test_performance_optimizations.py -v
```

## Performance Metrics

### Expected Improvements
- **Database queries**: 50-70% reduction for cached data
- **HTTP connections**: 40-60% reduction in connection overhead
- **Response times**: 30-50% improvement for cached endpoints
- **Throughput**: 2-3x improvement under heavy load
- **Concurrent requests**: Support for 10+ simultaneous meetings

### Monitoring
Monitor these metrics in production:
- Cache hit/miss ratio
- Rate limit violations per client
- Queue depth and processing time
- Database connection pool utilization
- HTTP client pool utilization

## Configuration

### Environment Variables
```bash
# Redis
REDIS_URL=redis://localhost:6379/0

# Database (with connection pooling)
DATABASE_URL=postgresql+psycopg://user:pass@localhost:5432/meetflow
```

### Tuning Parameters
Adjust these based on your workload:

```python
# Database pool
pool_size=20          # Increase for more concurrent DB operations
max_overflow=10       # Additional connections when pool is full

# HTTP client pool
max_connections=100   # Total connections across all hosts
max_keepalive=20      # Persistent connections

# Rate limiting
max_requests=100      # Requests per window
window_seconds=60     # Time window

# Request queue
max_concurrent=10     # Concurrent request handlers
max_queue_size=1000   # Maximum queued requests
```

## Best Practices

1. **Cache Invalidation**: Always invalidate cache when data changes
2. **Rate Limiting**: Use API keys for better client identification
3. **Queue Priority**: Use HIGH priority sparingly for critical requests
4. **Connection Pooling**: Monitor pool utilization and adjust sizes
5. **Error Handling**: Handle cache failures gracefully (fallback to DB)

## Future Enhancements

Potential improvements for future iterations:
- Distributed caching with Redis Cluster
- Advanced rate limiting (sliding window, token bucket per endpoint)
- Request prioritization based on user tier
- Automatic cache warming
- Connection pool metrics and alerting
- Circuit breaker integration with connection pools
