"""
Health check endpoints for system dependencies.
"""
import os
import logging
from typing import Dict, Any
from datetime import datetime

from fastapi import APIRouter, status
from pydantic import BaseModel
import httpx

from db.database import get_db_session
from integrations.circuit_breaker import get_all_circuit_breaker_stats


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/health", tags=["health"])


class HealthCheckResponse(BaseModel):
    """Response model for health check."""
    status: str
    timestamp: str
    checks: Dict[str, Dict[str, Any]]


class DependencyStatus(BaseModel):
    """Status of a single dependency."""
    healthy: bool
    latency_ms: float
    error: str = None


async def check_database() -> DependencyStatus:
    """
    Check PostgreSQL database connectivity.
    
    Returns:
        DependencyStatus with health status
    """
    start_time = datetime.utcnow()
    
    try:
        async with get_db_session() as session:
            # Simple query to test connection
            result = await session.execute("SELECT 1")
            result.scalar()
        
        latency = (datetime.utcnow() - start_time).total_seconds() * 1000
        
        return DependencyStatus(
            healthy=True,
            latency_ms=round(latency, 2)
        )
        
    except Exception as e:
        latency = (datetime.utcnow() - start_time).total_seconds() * 1000
        logger.error(f"Database health check failed: {e}")
        
        return DependencyStatus(
            healthy=False,
            latency_ms=round(latency, 2),
            error=str(e)
        )


async def check_redis() -> DependencyStatus:
    """
    Check Redis connectivity.
    
    Returns:
        DependencyStatus with health status
    """
    start_time = datetime.utcnow()
    
    try:
        import redis.asyncio as redis
        
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
        client = redis.from_url(redis_url)
        
        # Ping Redis
        await client.ping()
        await client.close()
        
        latency = (datetime.utcnow() - start_time).total_seconds() * 1000
        
        return DependencyStatus(
            healthy=True,
            latency_ms=round(latency, 2)
        )
        
    except Exception as e:
        latency = (datetime.utcnow() - start_time).total_seconds() * 1000
        logger.error(f"Redis health check failed: {e}")
        
        return DependencyStatus(
            healthy=False,
            latency_ms=round(latency, 2),
            error=str(e)
        )


async def check_gemini_api() -> DependencyStatus:
    """
    Check Google Gemini API connectivity.
    
    Returns:
        DependencyStatus with health status
    """
    start_time = datetime.utcnow()
    
    try:
        import google.generativeai as genai
        
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY not configured")
        
        genai.configure(api_key=api_key)
        
        # List models to test API connectivity
        models = genai.list_models()
        list(models)  # Force evaluation
        
        latency = (datetime.utcnow() - start_time).total_seconds() * 1000
        
        return DependencyStatus(
            healthy=True,
            latency_ms=round(latency, 2)
        )
        
    except Exception as e:
        latency = (datetime.utcnow() - start_time).total_seconds() * 1000
        logger.error(f"Gemini API health check failed: {e}")
        
        return DependencyStatus(
            healthy=False,
            latency_ms=round(latency, 2),
            error=str(e)
        )


async def check_slack_api() -> DependencyStatus:
    """
    Check Slack API connectivity.
    
    Returns:
        DependencyStatus with health status
    """
    start_time = datetime.utcnow()
    
    try:
        bot_token = os.getenv("SLACK_BOT_TOKEN")
        if not bot_token:
            raise ValueError("SLACK_BOT_TOKEN not configured")
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://slack.com/api/auth.test",
                headers={"Authorization": f"Bearer {bot_token}"}
            )
            response.raise_for_status()
            
            data = response.json()
            if not data.get("ok"):
                raise ValueError(f"Slack API error: {data.get('error')}")
        
        latency = (datetime.utcnow() - start_time).total_seconds() * 1000
        
        return DependencyStatus(
            healthy=True,
            latency_ms=round(latency, 2)
        )
        
    except Exception as e:
        latency = (datetime.utcnow() - start_time).total_seconds() * 1000
        logger.error(f"Slack API health check failed: {e}")
        
        return DependencyStatus(
            healthy=False,
            latency_ms=round(latency, 2),
            error=str(e)
        )


async def check_jira_api() -> DependencyStatus:
    """
    Check Jira API connectivity.
    
    Returns:
        DependencyStatus with health status
    """
    start_time = datetime.utcnow()
    
    try:
        jira_url = os.getenv("JIRA_URL", "").rstrip('/')
        jira_email = os.getenv("JIRA_EMAIL")
        jira_api_token = os.getenv("JIRA_API_TOKEN")
        
        if not all([jira_url, jira_email, jira_api_token]):
            raise ValueError("Jira credentials not fully configured")
        
        async with httpx.AsyncClient(
            auth=(jira_email, jira_api_token),
            timeout=10.0
        ) as client:
            response = await client.get(f"{jira_url}/rest/api/3/myself")
            response.raise_for_status()
        
        latency = (datetime.utcnow() - start_time).total_seconds() * 1000
        
        return DependencyStatus(
            healthy=True,
            latency_ms=round(latency, 2)
        )
        
    except Exception as e:
        latency = (datetime.utcnow() - start_time).total_seconds() * 1000
        logger.error(f"Jira API health check failed: {e}")
        
        return DependencyStatus(
            healthy=False,
            latency_ms=round(latency, 2),
            error=str(e)
        )


@router.get("", response_model=HealthCheckResponse)
async def health_check() -> HealthCheckResponse:
    """
    Comprehensive health check for all system dependencies.
    
    Returns:
        HealthCheckResponse with status of all dependencies
    """
    logger.info("Running health checks")
    
    # Run all health checks in parallel
    import asyncio
    
    db_check, redis_check, gemini_check, slack_check, jira_check = await asyncio.gather(
        check_database(),
        check_redis(),
        check_gemini_api(),
        check_slack_api(),
        check_jira_api(),
        return_exceptions=True
    )
    
    # Handle exceptions from gather
    def safe_status(check_result) -> Dict[str, Any]:
        if isinstance(check_result, Exception):
            return {
                "healthy": False,
                "latency_ms": 0,
                "error": str(check_result)
            }
        return check_result.model_dump()
    
    checks = {
        "database": safe_status(db_check),
        "redis": safe_status(redis_check),
        "gemini_api": safe_status(gemini_check),
        "slack_api": safe_status(slack_check),
        "jira_api": safe_status(jira_check)
    }
    
    # Determine overall status
    all_healthy = all(check["healthy"] for check in checks.values())
    overall_status = "healthy" if all_healthy else "degraded"
    
    return HealthCheckResponse(
        status=overall_status,
        timestamp=datetime.utcnow().isoformat(),
        checks=checks
    )


@router.get("/database")
async def health_check_database() -> DependencyStatus:
    """Check PostgreSQL database health."""
    return await check_database()


@router.get("/redis")
async def health_check_redis() -> DependencyStatus:
    """Check Redis health."""
    return await check_redis()


@router.get("/gemini")
async def health_check_gemini() -> DependencyStatus:
    """Check Gemini API health."""
    return await check_gemini_api()


@router.get("/slack")
async def health_check_slack() -> DependencyStatus:
    """Check Slack API health."""
    return await check_slack_api()


@router.get("/jira")
async def health_check_jira() -> DependencyStatus:
    """Check Jira API health."""
    return await check_jira_api()


@router.get("/circuit-breakers")
async def get_circuit_breaker_status() -> Dict[str, Any]:
    """
    Get status of all circuit breakers.
    
    Returns:
        Dictionary with circuit breaker statistics
    """
    stats = get_all_circuit_breaker_stats()
    
    return {
        "timestamp": datetime.utcnow().isoformat(),
        "circuit_breakers": stats
    }
