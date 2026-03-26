"""
Rate limiting middleware for API endpoints.
"""
import logging
import time
from typing import Callable, Dict
from collections import defaultdict, deque

from fastapi import Request, Response, HTTPException, status
from starlette.middleware.base import BaseHTTPMiddleware


logger = logging.getLogger(__name__)


class RateLimiter:
    """
    Token bucket rate limiter.
    Limits requests to 100 per minute per client.
    """
    
    def __init__(
        self,
        max_requests: int = 100,
        window_seconds: int = 60
    ):
        """
        Initialize rate limiter.
        
        Args:
            max_requests: Maximum requests per window
            window_seconds: Time window in seconds
        """
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.clients: Dict[str, deque] = defaultdict(deque)
        logger.info(
            f"Initialized RateLimiter: {max_requests} req/{window_seconds}s"
        )
    
    def is_allowed(self, client_id: str) -> bool:
        """
        Check if request is allowed for client.
        
        Args:
            client_id: Client identifier (IP address or API key)
            
        Returns:
            True if request is allowed, False if rate limit exceeded
        """
        now = time.time()
        window_start = now - self.window_seconds
        
        # Get client's request history
        requests = self.clients[client_id]
        
        # Remove requests outside the current window
        while requests and requests[0] < window_start:
            requests.popleft()
        
        # Check if limit exceeded
        if len(requests) >= self.max_requests:
            logger.warning(
                f"Rate limit exceeded for client {client_id}: "
                f"{len(requests)} requests in {self.window_seconds}s"
            )
            return False
        
        # Add current request
        requests.append(now)
        return True
    
    def get_remaining(self, client_id: str) -> int:
        """
        Get remaining requests for client in current window.
        
        Args:
            client_id: Client identifier
            
        Returns:
            Number of remaining requests
        """
        now = time.time()
        window_start = now - self.window_seconds
        
        requests = self.clients[client_id]
        
        # Count requests in current window
        count = sum(1 for req_time in requests if req_time >= window_start)
        return max(0, self.max_requests - count)
    
    def cleanup_old_clients(self):
        """Remove inactive clients to prevent memory leaks."""
        now = time.time()
        window_start = now - self.window_seconds
        
        inactive_clients = []
        for client_id, requests in self.clients.items():
            # Remove old requests
            while requests and requests[0] < window_start:
                requests.popleft()
            
            # Mark client for removal if no recent requests
            if not requests:
                inactive_clients.append(client_id)
        
        # Remove inactive clients
        for client_id in inactive_clients:
            del self.clients[client_id]
        
        if inactive_clients:
            logger.debug(f"Cleaned up {len(inactive_clients)} inactive clients")


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    FastAPI middleware for rate limiting.
    """
    
    def __init__(
        self,
        app,
        max_requests: int = 100,
        window_seconds: int = 60
    ):
        """
        Initialize rate limit middleware.
        
        Args:
            app: FastAPI application
            max_requests: Maximum requests per window
            window_seconds: Time window in seconds
        """
        super().__init__(app)
        self.rate_limiter = RateLimiter(max_requests, window_seconds)
        self.last_cleanup = time.time()
        self.cleanup_interval = 300  # 5 minutes
    
    async def dispatch(
        self,
        request: Request,
        call_next: Callable
    ) -> Response:
        """
        Process request with rate limiting.
        
        Args:
            request: Incoming request
            call_next: Next middleware/handler
            
        Returns:
            Response
            
        Raises:
            HTTPException: If rate limit exceeded
        """
        # Skip rate limiting for health check endpoints
        if request.url.path in ["/health", "/", "/docs", "/redoc", "/openapi.json"]:
            return await call_next(request)
        
        # Get client identifier (IP address or API key)
        client_id = self._get_client_id(request)
        
        # Check rate limit
        if not self.rate_limiter.is_allowed(client_id):
            remaining = self.rate_limiter.get_remaining(client_id)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "error": "Rate limit exceeded",
                    "limit": self.rate_limiter.max_requests,
                    "window": f"{self.rate_limiter.window_seconds}s",
                    "remaining": remaining,
                    "retry_after": self.rate_limiter.window_seconds
                }
            )
        
        # Add rate limit headers to response
        response = await call_next(request)
        remaining = self.rate_limiter.get_remaining(client_id)
        response.headers["X-RateLimit-Limit"] = str(self.rate_limiter.max_requests)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-RateLimit-Window"] = str(self.rate_limiter.window_seconds)
        
        # Periodic cleanup
        now = time.time()
        if now - self.last_cleanup > self.cleanup_interval:
            self.rate_limiter.cleanup_old_clients()
            self.last_cleanup = now
        
        return response
    
    def _get_client_id(self, request: Request) -> str:
        """
        Extract client identifier from request.
        
        Args:
            request: Incoming request
            
        Returns:
            Client identifier (API key or IP address)
        """
        # Check for API key in header
        api_key = request.headers.get("X-API-Key")
        if api_key:
            return f"key:{api_key}"
        
        # Fall back to IP address
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            # Use first IP in X-Forwarded-For chain
            return f"ip:{forwarded_for.split(',')[0].strip()}"
        
        # Use direct client IP
        client_host = request.client.host if request.client else "unknown"
        return f"ip:{client_host}"
