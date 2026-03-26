"""
MeetFlow AI Multi-Agent System - Main FastAPI Application
"""
import os
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.slack import router as slack_router
from api.meetings import router as meetings_router
from api.audit import router as audit_router
from api.health import router as health_router
from api.rate_limiter import RateLimitMiddleware
from api.auth import AuthenticationMiddleware
from integrations.cache import get_cache_client
from integrations.http_client import get_http_client_pool
from integrations.request_queue import get_request_queue


logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager.
    Handles startup and shutdown of resources.
    """
    # Startup
    logger.info("Starting MeetFlow AI application...")
    
    # Initialize Redis cache
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    cache_client = get_cache_client(redis_url)
    await cache_client.connect()
    logger.info("Redis cache connected")
    
    # Initialize HTTP client pool
    http_client_pool = get_http_client_pool(
        max_connections=100,
        max_keepalive_connections=20,
        timeout=30.0
    )
    logger.info("HTTP client pool initialized")
    
    # Initialize request queue
    request_queue = get_request_queue(
        max_concurrent=10,
        max_queue_size=1000
    )
    await request_queue.start()
    logger.info("Request queue started")
    
    logger.info("MeetFlow AI application started successfully")
    
    yield
    
    # Shutdown
    logger.info("Shutting down MeetFlow AI application...")
    
    # Close Redis cache
    await cache_client.disconnect()
    logger.info("Redis cache disconnected")
    
    # Close HTTP client pool
    await http_client_pool.close()
    logger.info("HTTP client pool closed")
    
    # Stop request queue
    await request_queue.stop()
    logger.info("Request queue stopped")
    
    logger.info("MeetFlow AI application shut down successfully")


app = FastAPI(
    title="MeetFlow AI",
    description="Multi-Agent System for Autonomous Enterprise Workflows",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add authentication middleware (must be before rate limiting)
app.add_middleware(AuthenticationMiddleware)

# Add rate limiting middleware (100 requests per minute per client)
app.add_middleware(
    RateLimitMiddleware,
    max_requests=100,
    window_seconds=60
)

# Include routers
app.include_router(slack_router)
app.include_router(meetings_router)
app.include_router(audit_router)
app.include_router(health_router)


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "message": "MeetFlow AI Multi-Agent System",
        "version": "0.1.0",
        "status": "running"
    }


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
