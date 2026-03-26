# API Authentication and Authorization

## Overview

The MeetFlow AI API now implements API key authentication for all endpoints except public routes. This ensures that only authorized clients can access sensitive operations and data.

## Authentication Method

The API uses **API Key Authentication** via the `X-API-Key` HTTP header.

### Request Format

```http
GET /api/meetings/abc-123 HTTP/1.1
Host: api.meetflow.ai
X-API-Key: your-api-key-here
```

## Configuration

### Environment Variables

API keys are configured via the `API_KEYS` environment variable:

```bash
# Single API key
API_KEYS=my-secret-key-12345

# Multiple API keys (comma-separated)
API_KEYS=dev-key-12345,prod-key-67890,test-key-abcde
```

### Setup

1. Add API keys to your `.env` file:
   ```
   API_KEYS=your-api-key-1,your-api-key-2
   ```

2. Restart the application to load the new keys

3. Include the `X-API-Key` header in all API requests

## Public Routes

The following routes do **NOT** require authentication:

- `/` - Root endpoint
- `/health` - Health check endpoint
- `/docs` - API documentation (Swagger UI)
- `/redoc` - API documentation (ReDoc)
- `/openapi.json` - OpenAPI schema

## Protected Routes

All other routes require authentication:

- `/api/meetings/*` - Meeting management endpoints
- `/api/decisions/*` - Decision management endpoints
- `/api/audit/*` - Audit trail endpoints
- `/api/slack/*` - Slack integration endpoints
- `/api/health/*` - Detailed health check endpoints

## HTTP Status Codes

The API returns appropriate HTTP status codes:

### Success Codes
- **200 OK** - Successful GET request
- **201 Created** - Successful POST request that creates a resource

### Client Error Codes
- **400 Bad Request** - Invalid input data (e.g., invalid date format, missing required fields)
- **401 Unauthorized** - Missing or invalid API key
- **404 Not Found** - Requested resource does not exist

### Server Error Codes
- **500 Internal Server Error** - Server-side error during request processing

## Authentication Errors

### Missing API Key

**Request:**
```http
GET /api/meetings/abc-123 HTTP/1.1
Host: api.meetflow.ai
```

**Response:**
```http
HTTP/1.1 401 Unauthorized
Content-Type: application/json

{
  "detail": "Missing API key. Provide X-API-Key header."
}
```

### Invalid API Key

**Request:**
```http
GET /api/meetings/abc-123 HTTP/1.1
Host: api.meetflow.ai
X-API-Key: invalid-key
```

**Response:**
```http
HTTP/1.1 401 Unauthorized
Content-Type: application/json

{
  "detail": "Invalid API key"
}
```

## Example Usage

### Python (httpx)

```python
import httpx

API_KEY = "your-api-key-here"
BASE_URL = "http://localhost:8000"

async with httpx.AsyncClient() as client:
    response = await client.get(
        f"{BASE_URL}/api/meetings/abc-123",
        headers={"X-API-Key": API_KEY}
    )
    
    if response.status_code == 200:
        meeting = response.json()
        print(f"Meeting: {meeting['title']}")
    elif response.status_code == 401:
        print("Authentication failed")
    elif response.status_code == 404:
        print("Meeting not found")
```

### cURL

```bash
# With authentication
curl -H "X-API-Key: your-api-key-here" \
  http://localhost:8000/api/meetings/abc-123

# Public endpoint (no auth required)
curl http://localhost:8000/health
```

### JavaScript (fetch)

```javascript
const API_KEY = 'your-api-key-here';
const BASE_URL = 'http://localhost:8000';

async function getMeeting(meetingId) {
  const response = await fetch(`${BASE_URL}/api/meetings/${meetingId}`, {
    headers: {
      'X-API-Key': API_KEY
    }
  });
  
  if (response.ok) {
    const meeting = await response.json();
    console.log('Meeting:', meeting.title);
  } else if (response.status === 401) {
    console.error('Authentication failed');
  } else if (response.status === 404) {
    console.error('Meeting not found');
  }
}
```

## Security Best Practices

1. **Keep API Keys Secret**: Never commit API keys to version control
2. **Use Environment Variables**: Store API keys in `.env` files (excluded from git)
3. **Rotate Keys Regularly**: Change API keys periodically
4. **Use HTTPS**: Always use HTTPS in production to encrypt API keys in transit
5. **Limit Key Scope**: Use different API keys for different environments (dev, staging, prod)
6. **Monitor Usage**: Track API key usage and revoke compromised keys immediately

## Development Mode

If no API keys are configured (`API_KEYS` is empty or not set), the system will log a warning but allow requests to proceed. This is for development/testing purposes only.

**Warning:** Never deploy to production without configuring API keys!

## Testing

The authentication system includes comprehensive tests:

```bash
# Run authentication tests
pytest tests/test_authentication.py -v

# Run all tests
pytest tests/ -v
```

## Implementation Details

### Middleware

Authentication is implemented as a FastAPI middleware (`AuthenticationMiddleware`) that:

1. Checks if the requested route is public
2. Extracts the `X-API-Key` header from the request
3. Validates the API key against configured keys
4. Returns 401 if authentication fails
5. Allows the request to proceed if authentication succeeds

### Code Location

- **Middleware**: `api/auth.py`
- **Integration**: `main.py` (middleware registration)
- **Tests**: `tests/test_authentication.py`
- **Configuration**: `.env` and `.env.example`

## Troubleshooting

### Issue: Getting 401 on all requests

**Solution**: Ensure you're including the `X-API-Key` header with a valid key from your `API_KEYS` environment variable.

### Issue: API key not recognized after adding to .env

**Solution**: Restart the application to reload environment variables.

### Issue: Public routes returning 401

**Solution**: Check that the route is in the `PUBLIC_ROUTES` set in `api/auth.py`. The `/health` and `/docs` routes should always be public.

## Future Enhancements

Potential improvements for the authentication system:

1. **JWT Tokens**: Support for JWT-based authentication
2. **OAuth 2.0**: Integration with OAuth providers
3. **Rate Limiting per Key**: Different rate limits for different API keys
4. **Key Metadata**: Associate metadata with keys (name, permissions, expiry)
5. **Audit Logging**: Log all authentication attempts
6. **Key Management API**: Endpoints for creating/revoking API keys
