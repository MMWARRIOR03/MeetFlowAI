"""
API key authentication middleware and dependencies.
"""
import os
import logging
from typing import Optional

from fastapi import Request, HTTPException, status
from fastapi.security import APIKeyHeader
from starlette.middleware.base import BaseHTTPMiddleware


logger = logging.getLogger(__name__)

# API key header scheme
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def get_valid_api_keys() -> set[str]:
    """
    Get valid API keys from environment.
    
    Returns:
        Set of valid API keys
    """
    api_keys_str = os.getenv("API_KEYS", "")
    if not api_keys_str:
        logger.warning("No API_KEYS configured in environment")
        return set()
    
    # Support comma-separated list of API keys
    return set(key.strip() for key in api_keys_str.split(",") if key.strip())


async def verify_api_key(api_key: Optional[str] = None) -> str:
    """
    Verify API key from request header.
    
    Args:
        api_key: API key from X-API-Key header
        
    Returns:
        Validated API key
        
    Raises:
        HTTPException: 401 if API key is missing or invalid
    """
    if not api_key:
        logger.warning("Missing API key in request")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing API key. Provide X-API-Key header."
        )
    
    valid_keys = get_valid_api_keys()
    
    if not valid_keys:
        # If no API keys configured, log warning but allow request
        # This is for development/testing purposes
        logger.warning("No API keys configured - allowing request")
        return api_key
    
    if api_key not in valid_keys:
        logger.warning(f"Invalid API key attempted: {api_key[:8]}...")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key"
        )
    
    return api_key


class AuthenticationMiddleware(BaseHTTPMiddleware):
    """
    Middleware to enforce API key authentication on all endpoints
    except public routes (/health, /docs, /redoc, /openapi.json).
    """
    
    # Routes that don't require authentication
    PUBLIC_ROUTES = {
        "/",
        "/health",
        "/docs",
        "/redoc",
        "/openapi.json",
    }
    
    # Route prefixes that don't require authentication
    PUBLIC_PREFIXES = [
        "/api/health",
        "/slack",
    ]
    
    async def dispatch(self, request: Request, call_next):
        """
        Process request and verify authentication.
        
        Args:
            request: Incoming request
            call_next: Next middleware/handler
            
        Returns:
            Response from handler or 401 error
        """
        # Check if route is public
        path = request.url.path
        
        # Allow public routes without authentication
        if path in self.PUBLIC_ROUTES or path.startswith("/docs") or path.startswith("/redoc"):
            return await call_next(request)
        
        # Allow public prefixes without authentication
        for prefix in self.PUBLIC_PREFIXES:
            if path.startswith(prefix):
                return await call_next(request)
        
        # Extract API key from header
        api_key = request.headers.get("X-API-Key")
        
        # Verify API key
        try:
            await verify_api_key(api_key)
        except HTTPException as e:
            # Return 401 response
            from fastapi.responses import JSONResponse
            return JSONResponse(
                status_code=e.status_code,
                content={"detail": e.detail}
            )
        
        # API key is valid, proceed with request
        response = await call_next(request)
        return response
