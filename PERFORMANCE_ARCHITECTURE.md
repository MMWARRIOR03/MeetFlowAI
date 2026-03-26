# Performance Optimizations Architecture

## System Architecture with Performance Enhancements

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Client Requests                              │
└────────────────────────────┬────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    Rate Limiting Middleware                          │
│  • 100 requests/minute per client                                    │
│  • Token bucket algorithm                                            │
│  • Per-client tracking (API key or IP)                               │
└────────────────────────────┬────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      Request Queue                                   │
│  • Max 10 concurrent workers                                         │
│  • Priority-based (HIGH, NORMAL, LOW)                                │
│  • Queue capacity: 1000 requests                                     │
└────────────────────────────┬────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      FastAPI Application                             │
│                                                                       │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐  │
│  │  Meetings API    │  │   Decisions API  │  │   Health API     │  │
│  │  /api/meetings   │  │  /api/decisions  │  │   /health        │  │
│  └────────┬─────────┘  └────────┬─────────┘  └────────┬─────────┘  │
│           │                     │                      │             │
└───────────┼─────────────────────┼──────────────────────┼─────────────┘
            │                     │                      │
            ▼                     ▼                      ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         Redis Cache                                  │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │  Cache Keys:                                                    │ │
│  │  • meeting:{id} (TTL: 1 hour)                                   │ │
│  │  • decision:{id} (TTL: 5 minutes)                               │ │
│  │  • meeting:{id}:decisions                                       │ │
│  └────────────────────────────────────────────────────────────────┘ │
└────────────────────────────┬────────────────────────────────────────┘
                             │
                    Cache Miss│
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│                  PostgreSQL Database                                 │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │  Connection Pool (AsyncAdaptedQueuePool)                        │ │
│  │  • Pool size: 20 connections                                    │ │
│  │  • Max overflow: 10 connections                                 │ │
│  │  • Pool timeout: 30 seconds                                     │ │
│  │  • Pool recycle: 1 hour                                         │ │
│  │  • Pre-ping: Enabled                                            │ │
│  └────────────────────────────────────────────────────────────────┘ │
│                                                                       │
│  Tables: meetings, decisions, audit_entries, workflow_results        │
└───────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│                  External API Integrations                           │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │  HTTP Client Pool (httpx)                                       │ │
│  │  • Max connections: 100                                         │ │
│  │  • Max keepalive: 20                                            │ │
│  │  • Timeout: 30 seconds                                          │ │
│  └────────────────────────────────────────────────────────────────┘ │
│                                                                       │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐              │
│  │  Jira API    │  │  Slack API   │  │  Gemini API  │              │
│  └──────────────┘  └──────────────┘  └──────────────┘              │
└───────────────────────────────────────────────────────────────────────┘
```

## Request Flow with Optimizations

### 1. Read Request (GET /api/meetings/{id})

```
Client Request
    │
    ▼
Rate Limiter (check limit)
    │
    ▼
Request Queue (enqueue)
    │
    ▼
API Handler
    │
    ├─► Redis Cache (check)
    │       │
    │       ├─► Cache HIT ──► Return cached data
    │       │
    │       └─► Cache MISS
    │               │
    │               ▼
    │       Database Pool (get connection)
    │               │
    │               ▼
    │       Query Database
    │               │
    │               ▼
    │       Cache Result (set with TTL)
    │               │
    │               ▼
    └───────────► Return data
```

### 2. Write Request (POST /api/decisions/{id}/approve)

```
Client Request
    │
    ▼
Rate Limiter (check limit)
    │
    ▼
Request Queue (enqueue with priority)
    │
    ▼
API Handler
    │
    ▼
Database Pool (get connection)
    │
    ▼
Update Database
    │
    ▼
Invalidate Cache
    │   ├─► Delete decision:{id}
    │   └─► Delete meeting:{id}
    │
    ▼
Return success
```

### 3. External API Call (Jira/Slack)

```
Agent/Handler
    │
    ▼
HTTP Client Pool (get client)
    │
    ▼
Reuse existing connection (if available)
    │
    ▼
Make API request
    │
    ▼
Return response
```

## Performance Metrics

### Before Optimizations
- Database: New connection per request
- HTTP: New connection per API call
- Cache: None (all queries hit database)
- Rate limiting: None
- Concurrency: Limited by database connections

### After Optimizations
- Database: Connection pooling (20 + 10 overflow)
- HTTP: Connection pooling (100 + 20 keepalive)
- Cache: Redis with 50-70% hit rate
- Rate limiting: 100 req/min per client
- Concurrency: 10 concurrent request workers

### Expected Improvements
| Metric | Before | After | Improvement |
|--------|--------|-------|-------------|
| Database queries | 100% | 30-50% | 50-70% reduction |
| HTTP connections | New each time | Reused | 40-60% reduction |
| Response time (cached) | 100ms | 30-50ms | 50-70% faster |
| Throughput | 10 req/s | 20-30 req/s | 2-3x improvement |
| Concurrent meetings | 5 | 10+ | 2x improvement |

## Resource Utilization

### Memory
- Redis cache: ~100MB for 1000 meetings
- Connection pools: ~50MB
- Request queue: ~10MB
- Total overhead: ~160MB

### CPU
- Rate limiting: Minimal (<1%)
- Cache operations: Minimal (<2%)
- Connection pooling: Minimal (<1%)
- Request queue: Low (2-5%)

### Network
- Reduced connections: 40-60% fewer TCP handshakes
- Keepalive connections: Persistent for external APIs
- Cache hits: No database network traffic

## Monitoring Dashboard (Recommended)

```
┌─────────────────────────────────────────────────────────────────┐
│                  Performance Metrics Dashboard                   │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Rate Limiting                                                   │
│  ├─ Requests/min: 85/100                                         │
│  ├─ Blocked requests: 12                                         │
│  └─ Top clients: client1 (45), client2 (30)                      │
│                                                                  │
│  Cache Performance                                               │
│  ├─ Hit rate: 68%                                                │
│  ├─ Miss rate: 32%                                               │
│  ├─ Avg response time (hit): 15ms                                │
│  └─ Avg response time (miss): 85ms                               │
│                                                                  │
│  Database Pool                                                   │
│  ├─ Active connections: 12/20                                    │
│  ├─ Overflow connections: 3/10                                   │
│  ├─ Wait time: 5ms                                               │
│  └─ Pool utilization: 60%                                        │
│                                                                  │
│  HTTP Client Pool                                                │
│  ├─ Active connections: 8/100                                    │
│  ├─ Keepalive connections: 15/20                                 │
│  └─ Connection reuse rate: 85%                                   │
│                                                                  │
│  Request Queue                                                   │
│  ├─ Active workers: 7/10                                         │
│  ├─ Queued requests: 23/1000                                     │
│  ├─ Avg queue time: 150ms                                        │
│  ├─ Total processed: 1,234                                       │
│  └─ Total failed: 3                                              │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

## Configuration Tuning Guide

### High Traffic (100+ meetings/day)
```python
# Database
pool_size=30
max_overflow=20

# HTTP Client
max_connections=200
max_keepalive=40

# Request Queue
max_concurrent=20
max_queue_size=2000

# Rate Limiting
max_requests=200
window_seconds=60
```

### Low Traffic (10-50 meetings/day)
```python
# Database
pool_size=10
max_overflow=5

# HTTP Client
max_connections=50
max_keepalive=10

# Request Queue
max_concurrent=5
max_queue_size=500

# Rate Limiting
max_requests=50
window_seconds=60
```

### Development
```python
# Database
pool_size=5
max_overflow=2

# HTTP Client
max_connections=20
max_keepalive=5

# Request Queue
max_concurrent=2
max_queue_size=100

# Rate Limiting
max_requests=1000  # Effectively disabled
window_seconds=60
```
