# Error Recovery and Resilience Features

This document describes the error recovery and resilience features implemented in MeetFlow AI.

## Overview

The system implements multiple layers of error recovery and resilience to ensure robust operation in production environments:

1. **Circuit Breaker Pattern** - Prevents cascading failures
2. **Manual Retry Endpoint** - Allows manual retry of failed decisions
3. **Approval Timeout Reminders** - Sends reminders for pending approvals
4. **Health Check Endpoints** - Monitors system dependencies

## 1. Circuit Breaker Pattern

### Purpose
Prevents cascading failures by temporarily blocking requests to failing external services, allowing them time to recover.

### Implementation
Located in `integrations/circuit_breaker.py`

### States
- **CLOSED**: Normal operation, requests pass through
- **OPEN**: Circuit is open, requests are rejected immediately
- **HALF_OPEN**: Testing recovery, limited requests allowed

### Configuration
```python
CircuitBreakerConfig(
    failure_threshold=5,      # Open after 5 consecutive failures
    recovery_timeout=60,      # Wait 60s before attempting recovery
    success_threshold=2       # Need 2 successes to close circuit
)
```

### Usage
Circuit breakers are automatically applied to:
- **Gemini API** (`gemini_api`)
- **Jira API** (`jira_api`)

Additional services can be protected by:
```python
from integrations.circuit_breaker import get_circuit_breaker

breaker = await get_circuit_breaker("service_name")
result = await breaker.call(async_function, *args, **kwargs)
```

### Monitoring
Check circuit breaker status:
```bash
GET /api/health/circuit-breakers
```

Response:
```json
{
  "timestamp": "2026-03-20T10:30:00",
  "circuit_breakers": {
    "gemini_api": {
      "state": "closed",
      "failure_count": 0,
      "total_calls": 150,
      "total_failures": 2,
      "total_successes": 148
    },
    "jira_api": {
      "state": "open",
      "failure_count": 5,
      "opened_at": "2026-03-20T10:25:00",
      "time_until_recovery": 45.2
    }
  }
}
```

## 2. Manual Retry Endpoint

### Purpose
Allows operators to manually retry failed decisions without re-ingesting the entire meeting.

### Endpoint
```bash
POST /api/retry/{decision_id}
```

### Usage Example
```bash
curl -X POST http://localhost:8000/api/retry/dec_001
```

Response:
```json
{
  "status": "success",
  "message": "Decision dec_001 retry initiated",
  "workflow_type": "jira_create"
}
```

### Behavior
1. Validates decision exists and has failed workflow
2. Marks workflow result as `pending_retry`
3. Writes audit entry for retry action
4. Triggers workflow execution in background
5. Returns immediately (non-blocking)

### Error Cases
- **404**: Decision not found
- **400**: Decision has no failed workflow to retry

## 3. Approval Timeout Reminders

### Purpose
Sends reminder notifications for pending approvals that exceed timeout threshold.

### Implementation
Located in `integrations/approval_reminders.py`

### Configuration
```python
ApprovalReminderService(
    slack_gate=slack_gate,
    timeout_hours=24,              # First reminder after 24h
    reminder_interval_hours=12,    # Subsequent reminders every 12h
    check_interval_seconds=300     # Check every 5 minutes
)
```

### Starting the Service
```python
from integrations.approval_reminders import start_approval_reminder_service
from integrations.slack import create_slack_approval_gate

slack_gate = create_slack_approval_gate()
service = await start_approval_reminder_service(
    slack_gate=slack_gate,
    timeout_hours=24,
    reminder_interval_hours=12
)
```

### Reminder Message Format
Reminders include:
- Time pending (e.g., "pending for 26.5 hours")
- Deadline urgency (OVERDUE, DUE TODAY, Due in X days)
- Decision details (owner, deadline, workflow type)
- Original quote from meeting transcript

### Audit Trail
All reminders are logged in the audit trail:
```sql
SELECT * FROM audit_entries 
WHERE agent = 'ApprovalReminderService' 
  AND step = 'send_reminder';
```

## 4. Health Check Endpoints

### Purpose
Monitor health and connectivity of all system dependencies.

### Endpoints

#### Comprehensive Health Check
```bash
GET /api/health
```

Response:
```json
{
  "status": "healthy",
  "timestamp": "2026-03-20T10:30:00",
  "checks": {
    "database": {
      "healthy": true,
      "latency_ms": 10.5
    },
    "redis": {
      "healthy": true,
      "latency_ms": 5.2
    },
    "gemini_api": {
      "healthy": true,
      "latency_ms": 150.0
    },
    "slack_api": {
      "healthy": true,
      "latency_ms": 80.0
    },
    "jira_api": {
      "healthy": false,
      "latency_ms": 0,
      "error": "Connection timeout"
    }
  }
}
```

#### Individual Service Checks
```bash
GET /api/health/database
GET /api/health/redis
GET /api/health/gemini
GET /api/health/slack
GET /api/health/jira
```

### Status Codes
- **healthy**: All services operational
- **degraded**: One or more services unhealthy

### Integration with Monitoring
Health check endpoints can be integrated with:
- **Kubernetes**: Liveness and readiness probes
- **Prometheus**: Metrics scraping
- **Datadog/New Relic**: APM monitoring
- **PagerDuty**: Alerting

Example Kubernetes configuration:
```yaml
livenessProbe:
  httpGet:
    path: /api/health
    port: 8000
  initialDelaySeconds: 30
  periodSeconds: 10

readinessProbe:
  httpGet:
    path: /api/health
    port: 8000
  initialDelaySeconds: 5
  periodSeconds: 5
```

## Error Recovery Workflow

### Scenario: Jira API Failure

1. **Initial Failure**
   - Jira API call fails (network timeout)
   - Retry logic attempts 2 more times with backoff (3s, 6s)
   - All retries fail

2. **Circuit Breaker Opens**
   - After 5 consecutive failures, circuit breaker opens
   - Subsequent requests are rejected immediately
   - Error logged in audit trail

3. **Health Check Detects Issue**
   - `/api/health/jira` returns unhealthy status
   - Monitoring system alerts operators

4. **Recovery Attempt**
   - After 60 seconds, circuit transitions to HALF_OPEN
   - Next request is allowed through as test
   - If successful, circuit closes after 2 successes

5. **Manual Intervention (if needed)**
   - Operator identifies failed decisions in audit trail
   - Uses `/api/retry/{decision_id}` to retry failed workflows
   - System re-executes workflow with fresh circuit breaker state

### Scenario: Approval Timeout

1. **Decision Requires Approval**
   - Decision extracted and classified
   - Approval message sent to Slack
   - Status set to `pending`

2. **Timeout Threshold Reached**
   - After 24 hours, reminder service detects timeout
   - Reminder message sent to Slack channel
   - Audit entry created

3. **Subsequent Reminders**
   - Every 12 hours, additional reminders sent
   - Each reminder includes urgency indicators
   - Reminders continue until approval/rejection

4. **Approval Received**
   - User clicks Approve/Reject button
   - Status updated in database
   - Workflow execution triggered (if approved)
   - No more reminders sent

## Best Practices

### Circuit Breaker Tuning
- **failure_threshold**: Set based on expected error rate (5 is reasonable default)
- **recovery_timeout**: Balance between quick recovery and avoiding flapping (60s default)
- **success_threshold**: Require multiple successes to avoid premature closure (2 is safe)

### Retry Strategy
- Use exponential backoff to avoid overwhelming failing services
- Limit total retry attempts to prevent infinite loops
- Log all retry attempts for debugging

### Monitoring
- Set up alerts for circuit breaker state changes
- Monitor health check endpoints continuously
- Track approval timeout metrics
- Review audit trail regularly for patterns

### Production Deployment
1. Enable health check monitoring
2. Configure alerting for degraded status
3. Start approval reminder service on application startup
4. Set up circuit breaker metrics collection
5. Document runbook for manual retry procedures

## Testing

### Circuit Breaker Tests
```bash
pytest tests/test_circuit_breaker.py -v
```

### Health Endpoint Tests
```bash
pytest tests/test_health_endpoints.py -v
```

### Manual Testing
```bash
# Test health check
curl http://localhost:8000/api/health

# Test circuit breaker status
curl http://localhost:8000/api/health/circuit-breakers

# Test manual retry
curl -X POST http://localhost:8000/api/retry/dec_001
```

## Troubleshooting

### Circuit Breaker Stuck Open
**Symptom**: Circuit remains open despite service recovery

**Solution**:
1. Check circuit breaker status: `GET /api/health/circuit-breakers`
2. Verify service is actually healthy: `GET /api/health/{service}`
3. Wait for recovery timeout to elapse
4. If needed, restart application to reset circuit breakers

### Approval Reminders Not Sending
**Symptom**: No reminders received for pending approvals

**Solution**:
1. Verify reminder service is started
2. Check Slack credentials are configured
3. Review audit trail for reminder failures
4. Check Slack channel permissions

### Manual Retry Fails
**Symptom**: Retry endpoint returns error

**Solution**:
1. Verify decision exists: `GET /api/decisions/{decision_id}`
2. Check decision has failed workflow result
3. Review audit trail for original failure reason
4. Ensure underlying service is healthy before retry

## Future Enhancements

- **Automatic Retry Queue**: Background job queue for automatic retries
- **Adaptive Circuit Breaker**: Adjust thresholds based on error patterns
- **Distributed Circuit Breaker**: Share state across multiple instances
- **Advanced Alerting**: Integration with PagerDuty, Opsgenie
- **Metrics Dashboard**: Real-time visualization of circuit breaker states
