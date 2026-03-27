#!/bin/bash

# MeetFlow AI Demo Script
# Demonstrates the complete pipeline using the Q2 Planning Sync demo fixture

set -euo pipefail

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Configuration
API_BASE_URL="http://localhost:8000"
API_KEY="dev-key-12345"
DEMO_FIXTURE="tests/fixtures/q2_planning_sync.vtt"
MEETING_ID=""
MAX_POLL_ATTEMPTS="${MAX_POLL_ATTEMPTS:-36}"
POLL_INTERVAL_SECONDS="${POLL_INTERVAL_SECONDS:-10}"

# Helper functions
print_header() {
    echo -e "\n${BLUE}========================================${NC}"
    echo -e "${BLUE}$1${NC}"
    echo -e "${BLUE}========================================${NC}\n"
}

print_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

print_info() {
    echo -e "${YELLOW}ℹ $1${NC}"
}

print_error() {
    echo -e "${RED}✗ $1${NC}"
}

api_get() {
    local url=$1
    curl -s -H "X-API-Key: ${API_KEY}" "$url"
}

wait_for_pipeline() {
    local meeting_id=$1
    local attempt=1

    print_info "Waiting for pipeline completion (up to $((MAX_POLL_ATTEMPTS * POLL_INTERVAL_SECONDS))s)..."

    while [ $attempt -le $MAX_POLL_ATTEMPTS ]; do
        local pipeline_status
        pipeline_status=$(api_get "${API_BASE_URL}/api/pipeline/status/${meeting_id}")

        local detail
        detail=$(echo "$pipeline_status" | jq -r '.detail // empty')

        if [ -n "$detail" ]; then
            print_info "Poll $attempt/$MAX_POLL_ATTEMPTS: pipeline status not ready yet (${detail})"
            sleep "$POLL_INTERVAL_SECONDS"
            attempt=$((attempt + 1))
            continue
        fi

        local meeting_status
        meeting_status=$(echo "$pipeline_status" | jq -r '.status // "unknown"')

        local error_count
        error_count=$(echo "$pipeline_status" | jq '(.errors // []) | length')

        local completed_steps
        completed_steps=$(echo "$pipeline_status" | jq -r '(.completed_steps // []) | join(", ")')

        if [ "$meeting_status" = "completed" ]; then
            print_success "Pipeline completed"
            return 0
        fi

        if [ "$meeting_status" = "failed" ] || [ "$error_count" -gt 0 ]; then
            print_error "Pipeline failed"
            echo "$pipeline_status" | jq '.'
            return 1
        fi

        print_info "Poll $attempt/$MAX_POLL_ATTEMPTS: status=$meeting_status completed_steps=[${completed_steps}]"
        sleep "$POLL_INTERVAL_SECONDS"
        attempt=$((attempt + 1))
    done

    print_error "Pipeline did not reach a terminal state in time"
    api_get "${API_BASE_URL}/api/pipeline/status/${meeting_id}" | jq '.'
    return 1
}

wait_for_service() {
    local url=$1
    local service_name=$2
    local max_attempts=30
    local attempt=1
    
    print_info "Waiting for $service_name to be ready..."
    
    while [ $attempt -le $max_attempts ]; do
        if curl -s "$url" > /dev/null 2>&1; then
            print_success "$service_name is ready!"
            return 0
        fi
        echo -n "."
        sleep 2
        attempt=$((attempt + 1))
    done
    
    print_error "$service_name failed to start after $max_attempts attempts"
    return 1
}

# Step 1: Check if services are running
print_header "Step 1: Checking Services"

if curl -s "${API_BASE_URL}/health" > /dev/null 2>&1; then
    print_success "MeetFlow API is already running"
else
    print_info "MeetFlow API is not running. Starting services..."
    
    # Check if docker-compose is available
    if ! command -v docker-compose &> /dev/null; then
        print_error "docker-compose not found. Please install docker-compose first."
        exit 1
    fi
    
    # Start services
    print_info "Starting Docker containers..."
    docker-compose up -d
    
    # Wait for services to be ready
    wait_for_service "${API_BASE_URL}/health" "MeetFlow API"
fi

# Step 2: Process demo fixture
print_header "Step 2: Processing Demo Fixture"

if [ ! -f "$DEMO_FIXTURE" ]; then
    print_error "Demo fixture not found at $DEMO_FIXTURE"
    exit 1
fi

print_info "Reading demo fixture: $DEMO_FIXTURE"

# Read VTT content
VTT_CONTENT=$(cat "$DEMO_FIXTURE")

# Create JSON payload
PAYLOAD=$(jq -n \
    --arg format "vtt" \
    --arg title "Q2 Planning Sync" \
    --arg date "2026-03-26" \
    --argjson participants '["Ankit", "Priya", "Mrinal"]' \
    --arg content "$VTT_CONTENT" \
    '{
        input_format: $format,
        title: $title,
        date: $date,
        participants: $participants,
        content: $content
    }')

print_info "Ingesting meeting via API..."

# Ingest meeting
RESPONSE=$(curl -s -X POST "${API_BASE_URL}/api/meetings/ingest" \
    -H "Content-Type: application/json" \
    -H "X-API-Key: ${API_KEY}" \
    -d "$PAYLOAD")

# Extract meeting ID
MEETING_ID=$(echo "$RESPONSE" | jq -r '.meeting_id')

if [ "$MEETING_ID" == "null" ] || [ -z "$MEETING_ID" ]; then
    print_error "Failed to ingest meeting"
    echo "$RESPONSE" | jq '.'
    exit 1
fi

print_success "Meeting ingested successfully!"
print_info "Meeting ID: $MEETING_ID"

# Wait for processing to complete
wait_for_pipeline "$MEETING_ID"

# Step 3: Query meeting status
print_header "Step 3: Meeting Status"

MEETING_DATA=$(curl -s -H "X-API-Key: ${API_KEY}" "${API_BASE_URL}/api/meetings/${MEETING_ID}")

echo "$MEETING_DATA" | jq '{
    meeting_id: .meeting_id,
    title: .title,
    date: .date,
    participants: .participants,
    status: .status,
    decision_count: (.decisions | length)
}'

print_success "Meeting details retrieved"

# Step 4: Display extracted decisions
print_header "Step 4: Extracted Decisions"

DECISIONS=$(echo "$MEETING_DATA" | jq -r '.decisions')
DECISION_COUNT=$(echo "$DECISIONS" | jq 'length')

if [ "$DECISION_COUNT" -eq 0 ]; then
    print_error "Meeting completed with 0 extracted decisions"
    echo "$MEETING_DATA" | jq '.'
    exit 1
fi

print_info "Found $DECISION_COUNT decisions:"
echo ""

echo "$DECISIONS" | jq -r '.[] | 
    "Decision ID: \(.decision_id)\n" +
    "  Description: \(.description)\n" +
    "  Owner: \(.owner)\n" +
    "  Deadline: \(.deadline)\n" +
    "  Workflow Type: \(.workflow_type)\n" +
    "  Approval Status: \(.approval_status)\n" +
    "  Confidence: \(.confidence)\n"'

# Step 5: Check pipeline status
print_header "Step 5: Pipeline Execution Status"

PIPELINE_STATUS=$(api_get "${API_BASE_URL}/api/pipeline/status/${MEETING_ID}")

echo "$PIPELINE_STATUS" | jq '{
    meeting_id: .meeting_id,
    status: .status,
    completed_steps: .completed_steps,
    failed_steps: .failed_steps,
    pending_steps: .pending_steps,
    errors: .errors
}'

print_success "Pipeline status retrieved"

# Step 6: Check audit trail
print_header "Step 6: Audit Trail"

AUDIT_TRAIL=$(api_get "${API_BASE_URL}/api/audit/${MEETING_ID}")
AUDIT_COUNT=$(echo "$AUDIT_TRAIL" | jq 'length')

print_info "Found $AUDIT_COUNT audit entries:"
echo ""

echo "$AUDIT_TRAIL" | jq -r '.[] | 
    "[\(.created_at)] \(.agent).\(.step) - \(.outcome)\n" +
    "  Detail: \(.detail // "N/A")\n"' | head -n 50

if [ "$AUDIT_COUNT" -gt 25 ]; then
    print_info "Showing first 25 entries. Full audit trail available via API."
fi

# Step 7: Query individual decisions
print_header "Step 7: Individual Decision Details"

# Get first decision ID
FIRST_DECISION_ID=$(echo "$DECISIONS" | jq -r '.[0].decision_id')

if [ "$FIRST_DECISION_ID" != "null" ] && [ -n "$FIRST_DECISION_ID" ]; then
    print_info "Querying decision: $FIRST_DECISION_ID"
    
    DECISION_DETAIL=$(api_get "${API_BASE_URL}/api/decisions/${FIRST_DECISION_ID}")
    
    echo "$DECISION_DETAIL" | jq '{
        decision_id: .decision_id,
        description: .description,
        owner: .owner,
        deadline: .deadline,
        workflow_type: .workflow_type,
        approval_status: .approval_status,
        parameters: .parameters
    }'
    
    print_success "Decision details retrieved"
    
    # Get decision audit trail
    print_info "Querying audit trail for decision: $FIRST_DECISION_ID"
    
    DECISION_AUDIT=$(api_get "${API_BASE_URL}/api/audit/decision/${FIRST_DECISION_ID}")
    DECISION_AUDIT_COUNT=$(echo "$DECISION_AUDIT" | jq 'length')
    
    print_info "Found $DECISION_AUDIT_COUNT audit entries for this decision"
    
    echo "$DECISION_AUDIT" | jq -r '.[] | 
        "[\(.created_at)] \(.agent).\(.step) - \(.outcome)"'
fi

# Step 8: System summary
print_header "Step 8: System Summary"

SUMMARY=$(api_get "${API_BASE_URL}/api/audit/summary")

echo "$SUMMARY" | jq '{
    total_meetings: .total_meetings,
    total_decisions: .total_decisions,
    total_audit_entries: .total_audit_entries,
    success_rate: "\(.success_rate)%",
    failure_rate: "\(.failure_rate)%",
    pending_approvals: .pending_approvals,
    completed_workflows: .completed_workflows,
    failed_workflows: .failed_workflows
}'

print_success "System summary retrieved"

# Final summary
print_header "Demo Complete!"

echo -e "${GREEN}Successfully demonstrated MeetFlow AI pipeline:${NC}"
echo -e "  ✓ Ingested demo fixture (Q2 Planning Sync)"
echo -e "  ✓ Extracted $DECISION_COUNT decisions"
echo -e "  ✓ Processed through multi-agent pipeline"
echo -e "  ✓ Generated $AUDIT_COUNT audit trail entries"
echo -e ""
echo -e "${YELLOW}Meeting ID: $MEETING_ID${NC}"
echo -e ""
echo -e "${BLUE}API Endpoints Used:${NC}"
echo -e "  • POST   ${API_BASE_URL}/api/meetings/ingest"
echo -e "  • GET    ${API_BASE_URL}/api/meetings/${MEETING_ID}"
echo -e "  • GET    ${API_BASE_URL}/api/decisions/{decision_id}"
echo -e "  • GET    ${API_BASE_URL}/api/pipeline/status/${MEETING_ID}"
echo -e "  • GET    ${API_BASE_URL}/api/audit/audit/${MEETING_ID}"
echo -e "  • GET    ${API_BASE_URL}/api/audit/audit/decision/{decision_id}"
echo -e "  • GET    ${API_BASE_URL}/api/audit/audit/summary"
echo -e ""
echo -e "${BLUE}View full API documentation at: ${API_BASE_URL}/docs${NC}"
echo -e ""
