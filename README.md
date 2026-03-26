# MeetFlow AI Multi-Agent System

**Production-grade multi-agent orchestration system for autonomous enterprise workflows**

MeetFlow AI automatically processes meeting recordings, extracts structured decisions using Google Gemini 2.0 Flash, and executes downstream business workflows across Jira, HR systems, and procurement platforms with human-in-the-loop approval gates.

Built for the **ET AI Hackathon 2026 - Problem Statement 2: Agentic AI for Autonomous Enterprise Workflows**.

## Features

- **Multi-Format Ingestion**: Process VTT transcripts, plain text, audio files, or JSON data
- **AI-Powered Extraction**: Extract structured decisions with Gemini 2.0 Flash
- **Intelligent Routing**: Classify decisions into workflow types (Jira, HR, Procurement)
- **Human Oversight**: Slack approval gate with Block Kit messages for high-impact decisions
- **Autonomous Execution**: Auto-trigger low-risk workflows without manual intervention
- **Comprehensive Audit Trail**: Append-only audit log for all agent actions
- **Fault Tolerance**: LangGraph checkpointing, exponential backoff, and retry logic
- **Real-World Integration**: Live API integrations with Jira, Slack, and enterprise systems

## Architecture

### System Overview

```
Meeting Input (VTT/Audio/Text/JSON)
    ↓
Ingestion Agent (Normalize)
    ↓
Extraction Agent (Gemini 2.0 Flash)
    ↓
Classifier Agent (Route to Workflows)
    ↓
Approval Gate (Slack - if required)
    ↓
Workflow Execution (Jira/HR/Procurement - Parallel)
    ↓
Verification Agent (Verify Outcomes)
    ↓
Summary (Slack Notification)
```

### Components

- **Ingestion Agent**: Normalizes meeting inputs into standardized format
- **Extraction Agent**: Extracts structured decisions using Gemini AI
- **Classifier Agent**: Routes decisions to appropriate workflow types
- **Jira Agent**: Creates/updates Jira tickets with verification
- **Onboarding Agent**: Executes 6-step employee onboarding workflows
- **Procurement Agent**: Handles procurement requests with approval tiers
- **Slack Approval Gate**: Human-in-the-loop approval with Block Kit UI
- **Verification Agent**: Verifies execution outcomes by querying target systems
- **LangGraph Orchestrator**: Coordinates multi-agent pipeline with checkpointing

### Technology Stack

- **Runtime**: Python 3.11+
- **Web Framework**: FastAPI with async/await
- **AI Model**: Google Gemini 2.0 Flash (`gemini-2.0-flash`)
- **Orchestration**: LangGraph with checkpointing
- **Database**: PostgreSQL 15 with SQLAlchemy async
- **Caching**: Redis
- **Testing**: pytest, pytest-asyncio, pytest-mock
- **HTTP Client**: httpx (async)
- **Validation**: Pydantic v2
- **Containerization**: Docker Compose

## Quick Start

### Prerequisites

- Docker and Docker Compose
- Python 3.11 or higher
- Google Gemini API key
- Slack Bot Token (optional, for approval gate)
- Jira API credentials (optional, for Jira workflows)

### 1. Clone and Setup

```bash
# Clone repository
git clone <repository-url>
cd meetflow-ai

# Copy environment template
cp .env.example .env

# Edit .env with your credentials
nano .env
```

### 2. Configure Environment Variables

Edit `.env` with your credentials:

```bash
# Database Configuration
DATABASE_URL=postgresql+psycopg://meetflow:meetflow@localhost:5432/meetflow

# Redis Configuration
REDIS_URL=redis://localhost:6379/0

# Google Gemini API (REQUIRED)
GEMINI_API_KEY=your_gemini_api_key_here

# Slack Configuration (Optional - for approval gate)
SLACK_BOT_TOKEN=xoxb-your-slack-bot-token
SLACK_SIGNING_SECRET=your_slack_signing_secret

# Jira Configuration (Optional - for Jira workflows)
JIRA_URL=https://your-domain.atlassian.net
JIRA_EMAIL=your-email@company.com
JIRA_API_TOKEN=your_jira_api_token
```

### 3. Start Services with Docker Compose

```bash
# Start PostgreSQL, Redis, and application
docker-compose up -d

# Check service health
docker-compose ps

# View logs
docker-compose logs -f app
```

### 4. Verify Setup

```bash
# Run verification script
bash scripts/verify_setup.sh

# Or manually check health
curl http://localhost:8000/health
```

### 5. Run Demo Fixture

```bash
# Process the demo meeting transcript
curl -X POST http://localhost:8000/api/meetings/ingest \
  -H "Content-Type: application/json" \
  -d '{
    "input_format": "vtt",
    "input_data": "@tests/fixtures/q2_planning_sync.vtt",
    "metadata": {
      "title": "Q2 Planning Sync",
      "date": "2026-03-20",
      "participants": ["Ankit", "Priya", "Mrinal"]
    }
  }'

# Check meeting status
curl http://localhost:8000/api/meetings/{meeting_id}

# View audit trail
curl http://localhost:8000/api/audit/{meeting_id}
```

## API Endpoints

### Meetings

#### POST /api/meetings/ingest
Ingest meeting data in VTT, text, audio, or JSON format.

**Request:**
```json
{
  "input_format": "vtt",
  "input_data": "WEBVTT\n\n00:00:00.000 --> 00:00:05.000\n<v Ankit>Let's update PROJ-456 deadline to April 10th.",
  "metadata": {
    "title": "Q2 Planning Sync",
    "date": "2026-03-20",
    "participants": ["Ankit", "Priya", "Mrinal"]
  }
}
```

**Response:**
```json
{
  "meeting_id": "mtg_abc123",
  "status": "processing",
  "message": "Meeting ingestion started"
}
```

#### GET /api/meetings/{meeting_id}
Get meeting details and extracted decisions.

**Response:**
```json
{
  "meeting_id": "mtg_abc123",
  "title": "Q2 Planning Sync",
  "date": "2026-03-20",
  "participants": ["Ankit", "Priya", "Mrinal"],
  "status": "completed",
  "decisions": [
    {
      "decision_id": "dec_001",
      "description": "Update PROJ-456 deadline to April 10",
      "owner": "Ankit",
      "deadline": "2026-04-10",
      "workflow_type": "jira_update",
      "status": "completed",
      "auto_trigger": true
    }
  ]
}
```

### Decisions

#### GET /api/decisions/{decision_id}
Get decision details and execution status.

**Response:**
```json
{
  "decision_id": "dec_001",
  "description": "Update PROJ-456 deadline to April 10",
  "owner": "Ankit",
  "deadline": "2026-04-10",
  "workflow_type": "jira_update",
  "status": "completed",
  "workflow_results": [
    {
      "workflow_type": "jira_update",
      "status": "success",
      "artifact_links": ["https://company.atlassian.net/browse/PROJ-456"]
    }
  ]
}
```

#### POST /api/decisions/{decision_id}/approve
Manually approve a decision.

**Response:**
```json
{
  "decision_id": "dec_002",
  "approval_status": "approved",
  "message": "Decision approved and workflow triggered"
}
```

#### POST /api/decisions/{decision_id}/reject
Manually reject a decision.

**Response:**
```json
{
  "decision_id": "dec_002",
  "approval_status": "rejected",
  "message": "Decision rejected"
}
```

### Audit Trail

#### GET /api/audit/{meeting_id}
Get all audit entries for a meeting.

**Response:**
```json
{
  "meeting_id": "mtg_abc123",
  "audit_entries": [
    {
      "audit_id": 1,
      "timestamp": "2026-03-20T10:00:00Z",
      "agent": "IngestionAgent",
      "step": "ingest",
      "outcome": "success",
      "detail": "Normalized VTT input to meeting record"
    },
    {
      "audit_id": 2,
      "timestamp": "2026-03-20T10:00:15Z",
      "agent": "ExtractionAgent",
      "step": "extract_decisions",
      "outcome": "success",
      "detail": "Extracted 4 decisions, 1 ambiguous item"
    }
  ]
}
```

#### GET /api/audit/decision/{decision_id}
Get all audit entries for a specific decision.

#### GET /api/audit/summary
Get aggregate statistics.

**Response:**
```json
{
  "total_meetings": 42,
  "total_decisions": 156,
  "success_rate": 0.94,
  "pending_approvals": 8,
  "failed_decisions": 3
}
```

### Pipeline Status

#### GET /api/pipeline/status/{meeting_id}
Get current pipeline execution state.

**Response:**
```json
{
  "meeting_id": "mtg_abc123",
  "status": "executing_workflows",
  "completed_steps": ["ingest", "extract", "classify"],
  "pending_steps": ["verify", "send_summary"],
  "errors": []
}
```

### Health Check

#### GET /health
Check system health.

**Response:**
```json
{
  "status": "healthy",
  "database": "connected",
  "redis": "connected",
  "gemini_api": "available"
}
```

## Demo Fixture

The system includes a demo meeting transcript at `tests/fixtures/q2_planning_sync.vtt` that demonstrates all workflow types.

### Demo Meeting: Q2 Planning Sync

**Participants**: Ankit, Priya, Mrinal  
**Date**: March 20, 2026

**Extracted Decisions**:

1. **dec_001** - Jira Update (Auto-trigger)
   - Description: Update PROJ-456 deadline to April 10
   - Owner: Ankit
   - Workflow: `jira_update`
   - Status: Auto-executed

2. **dec_002** - HR Hiring (Requires Approval)
   - Description: Hire backend engineer (Priya)
   - Owner: Priya
   - Workflow: `hr_hiring`
   - Status: Pending approval

3. **dec_003** - Procurement Request (Requires Approval)
   - Description: Increase AWS spend limit by $40k
   - Owner: Mrinal
   - Workflow: `procurement_request`
   - Status: Pending approval

4. **dec_004** - Jira Create (Auto-trigger)
   - Description: Create task for pricing model review
   - Owner: Mrinal
   - Workflow: `jira_create`
   - Status: Auto-executed

**Ambiguous Items**:
- Pricing model review (Ankit) - no deadline specified

### Running the Demo

#### Option 1: Automated Demo Script (Recommended)

```bash
# Run the complete demo script
./demo.sh
```

The demo script will:
- Check if services are running and start them if needed
- Process the demo fixture through the API
- Display meeting status and extracted decisions
- Show pipeline execution status
- Display the complete audit trail
- Query individual decision details
- Show system summary statistics

See [DEMO_README.md](DEMO_README.md) for detailed documentation.

#### Option 2: Manual API Testing

```bash
# Run integration test with demo fixture
pytest tests/integration/test_demo_fixture.py -v

# Or process via API
curl -X POST http://localhost:8000/api/meetings/ingest \
  -F "file=@tests/fixtures/q2_planning_sync.vtt" \
  -F "input_format=vtt" \
  -F 'metadata={"title":"Q2 Planning Sync","date":"2026-03-20","participants":["Ankit","Priya","Mrinal"]}'
```

## Development

### Local Setup (Without Docker)

```bash
# Create virtual environment
python3.11 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Start PostgreSQL and Redis locally
# (or use docker-compose for just the databases)
docker-compose up -d postgres redis

# Run database migrations
alembic upgrade head

# Start FastAPI server
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### Running Tests

```bash
# Run all tests
pytest -v

# Run specific test suites
pytest tests/test_ingestion_agent.py -v
pytest tests/test_extraction_agent.py -v
pytest tests/test_classifier_agent.py -v
pytest tests/test_orchestrator.py -v

# Run integration tests
pytest tests/integration/ -v

# Run with coverage
pytest --cov=. --cov-report=html
```

### Project Structure

```
meetflow-ai/
├── agents/                    # Agent implementations
│   ├── ingestion_agent.py    # Normalizes meeting inputs
│   ├── extraction_agent.py   # Extracts decisions with Gemini
│   ├── classifier_agent.py   # Routes to workflow types
│   ├── verification_agent.py # Verifies execution outcomes
│   └── workflow/             # Workflow-specific agents
│       ├── jira_agent.py     # Jira operations
│       ├── onboarding_agent.py  # HR onboarding
│       └── procurement_agent.py # Procurement workflows
├── api/                      # FastAPI endpoints
│   ├── meetings.py          # Meeting ingestion endpoints
│   ├── audit.py             # Audit trail endpoints
│   └── slack.py             # Slack webhook handlers
├── db/                       # Database models and migrations
│   ├── models.py            # SQLAlchemy models
│   └── database.py          # Database connection
├── integrations/             # External API clients
│   ├── gemini.py            # Gemini API wrapper
│   └── slack.py             # Slack API wrapper
├── orchestrator/             # LangGraph pipeline
│   ├── graph.py             # Pipeline definition
│   └── nodes.py             # Node implementations
├── prompts/                  # AI prompts
│   ├── extraction.py        # Decision extraction prompts
│   └── classification.py    # Classification prompts
├── schemas/                  # Pydantic schemas
│   └── base.py              # Shared data models
├── tests/                    # Test suite
│   ├── fixtures/            # Test data
│   │   └── q2_planning_sync.vtt
│   └── integration/         # Integration tests
├── docker-compose.yml        # Docker services
├── Dockerfile               # Application container
├── main.py                  # FastAPI application
├── requirements.txt         # Python dependencies
└── .env.example             # Environment template
```

## Workflow Types

### Jira Workflows

#### jira_create
Creates a new Jira issue.

**Parameters**:
- `project_key`: Jira project key (e.g., "PROJ")
- `issue_type`: Issue type (e.g., "Task", "Bug", "Story")
- `summary`: Issue title
- `description`: Issue description
- `assignee`: Jira username
- `priority`: Priority level (e.g., "High", "Medium", "Low")

**Example Decision**:
> "Create a task for Mrinal to review the pricing model by April 1st"

#### jira_update
Updates an existing Jira issue.

**Parameters**:
- `issue_key`: Jira issue key (e.g., "PROJ-456")
- `fields`: Fields to update (e.g., `{"duedate": "2026-04-10"}`)

**Example Decision**:
> "Update PROJ-456 deadline to April 10th"

#### jira_search
Searches for Jira issues and updates them.

**Parameters**:
- `jql_query`: JQL search query
- `fields`: Fields to update on matched issues

**Example Decision**:
> "Update all open bugs assigned to Ankit to high priority"

### HR Onboarding Workflow

#### hr_hiring
Executes 6-step employee onboarding workflow.

**Parameters**:
- `candidate_name`: New hire name
- `position`: Job title
- `department`: Department
- `start_date`: Start date
- `hiring_manager`: Manager name

**Steps**:
1. Create employee record in HR system
2. Provision email account and credentials
3. Assign equipment (laptop, phone, access cards)
4. Enroll in benefits and payroll
5. Schedule orientation and training sessions
6. Notify hiring manager and team

**Example Decision**:
> "Hire Priya as Backend Engineer in Engineering, starting March 28th"

### Procurement Workflow

#### procurement_request
Handles procurement requests with approval tiers.

**Parameters**:
- `item_description`: Item to purchase
- `quantity`: Quantity
- `estimated_cost`: Cost estimate
- `vendor`: Vendor name
- `requester`: Requester name

**Approval Tiers**:
- **Tier 1** (<$1,000): Auto-approve
- **Tier 2** ($1,000-$10,000): Department manager approval
- **Tier 3** (>$10,000): Executive approval

**Example Decision**:
> "Increase AWS spend limit by $40k for Q2"

## Slack Integration

### Approval Gate

High-impact decisions are routed to Slack for human approval using Block Kit messages.

**Approval Message Format**:

```
🔔 Approval Required

Decision: Increase AWS spend limit by $40k
Owner: Mrinal | Deadline: Mar 26
Workflow: procurement_request | Cost: $40,000

💬 "Let's raise the AWS spend limit by 40k for the quarter"

[✅ Approve] [❌ Reject] [❓ Ask]
```

**Button Actions**:
- **Approve**: Triggers workflow execution
- **Reject**: Halts workflow and notifies owner
- **Ask**: Requests clarification from decision owner

### Summary Notifications

After pipeline completion, a summary is sent to Slack:

```
📊 Meeting Summary: Q2 Planning Sync

✅ 3 decisions executed successfully
⏳ 1 decision pending approval
❌ 0 decisions failed

Completed Actions:
✅ PROJ-456 updated (deadline → April 10)
   🔗 https://company.atlassian.net/browse/PROJ-456
   
✅ JOB-789 created (Backend Engineer - Priya)
   🔗 https://company.atlassian.net/browse/JOB-789

Pending Approval:
⏳ Procurement request: AWS spend increase ($40k)
   Owner: Mrinal | Deadline: Mar 26

Follow-up Items:
💡 Pricing model review (Ankit) - no deadline set
```

## Error Handling and Resilience

### Retry Logic

- **Gemini API**: 3 retries with exponential backoff (5s, 15s, 45s) on 429 errors
- **Jira API**: 2 retries with backoff (3s, 6s) on failures
- **Rate Limiting**: 4-second delay between consecutive Gemini API calls

### Circuit Breaker

- Opens after 5 consecutive failures to external API
- Half-open state after 60 seconds
- Prevents cascading failures

### Checkpointing

- LangGraph checkpointing enables pipeline resumption after failures
- Idempotent execution: safe to re-run with same `meeting_id`
- State persisted to SQLite (dev) or PostgreSQL (prod)

### Audit Trail

- Append-only audit log for all agent actions
- Captures: agent name, step, outcome, timestamp, payload snapshot
- Enables debugging, compliance, and accountability

## Deployment

### Production Deployment

```bash
# Build production image
docker build -t meetflow-ai:latest .

# Run with production configuration
docker-compose -f docker-compose.prod.yml up -d

# Run database migrations
docker-compose exec app alembic upgrade head

# Check logs
docker-compose logs -f app
```

### Environment Variables (Production)

```bash
# Use PostgreSQL for checkpointing
DATABASE_URL=postgresql+psycopg://user:pass@prod-db:5432/meetflow

# Use Redis for caching
REDIS_URL=redis://prod-redis:6379/0

# Production Gemini API key
GEMINI_API_KEY=prod_gemini_key

# Production Slack credentials
SLACK_BOT_TOKEN=xoxb-prod-token
SLACK_SIGNING_SECRET=prod_signing_secret

# Production Jira credentials
JIRA_URL=https://company.atlassian.net
JIRA_EMAIL=bot@company.com
JIRA_API_TOKEN=prod_jira_token
```

### Scaling Considerations

- **Horizontal Scaling**: Run multiple FastAPI instances behind load balancer
- **Database Connection Pooling**: Configure SQLAlchemy pool size
- **Redis Caching**: Cache meeting metadata and decision status
- **Async Execution**: All I/O operations use async/await for high throughput
- **Rate Limiting**: 100 requests/minute per client on API endpoints

## Troubleshooting

### Common Issues

#### 1. Gemini API Rate Limiting

**Symptom**: `GeminiRateLimitError: Rate limit exceeded after 3 retries`

**Solution**:
- Verify `GEMINI_API_KEY` is valid
- Check Gemini API quota in Google Cloud Console
- Increase backoff delays in `integrations/gemini.py`

#### 2. Database Connection Errors

**Symptom**: `sqlalchemy.exc.OperationalError: could not connect to server`

**Solution**:
```bash
# Check PostgreSQL is running
docker-compose ps postgres

# Restart PostgreSQL
docker-compose restart postgres

# Verify connection string in .env
DATABASE_URL=postgresql+psycopg://meetflow:meetflow@localhost:5432/meetflow
```

#### 3. Slack Webhook Verification Failed

**Symptom**: `SlackRequestVerificationError: Invalid signature`

**Solution**:
- Verify `SLACK_SIGNING_SECRET` matches Slack app settings
- Check system clock is synchronized (Slack uses timestamps)
- Ensure webhook URL is publicly accessible

#### 4. Jira Authentication Failed

**Symptom**: `JiraAPIError: 401 Unauthorized`

**Solution**:
- Verify `JIRA_API_TOKEN` is valid
- Check `JIRA_EMAIL` matches token owner
- Ensure Jira user has required permissions

### Debug Mode

Enable debug logging:

```bash
# Set log level in .env
LOG_LEVEL=DEBUG

# Restart application
docker-compose restart app

# View detailed logs
docker-compose logs -f app
```

### Health Checks

```bash
# Check all services
curl http://localhost:8000/health

# Check database
docker-compose exec postgres pg_isready -U meetflow

# Check Redis
docker-compose exec redis redis-cli ping
```

## Contributing

### Development Workflow

1. Create feature branch: `git checkout -b feature/my-feature`
2. Make changes and add tests
3. Run tests: `pytest -v`
4. Run linter: `ruff check .`
5. Format code: `black .`
6. Commit changes: `git commit -m "Add feature"`
7. Push and create PR: `git push origin feature/my-feature`

### Code Style

- Follow PEP 8 style guide
- Use type hints for all functions
- Write docstrings for public APIs
- Add unit tests for new features
- Update README for user-facing changes

## License

MIT License - see LICENSE file for details

## Acknowledgments

- Built for **ET AI Hackathon 2026**
- Powered by **Google Gemini 2.0 Flash**
- Orchestrated with **LangGraph**
- Inspired by autonomous enterprise workflow automation

## Support

For issues, questions, or contributions:
- GitHub Issues: [repository-url]/issues
- Documentation: [repository-url]/docs
- Email: support@meetflow.ai

---

**MeetFlow AI** - Autonomous Enterprise Workflows with Multi-Agent AI
