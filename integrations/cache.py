"""
Redis caching layer for frequently accessed data.
"""
import json
import logging
from typing import Any, Optional
from datetime import timedelta

import redis.asyncio as redis


logger = logging.getLogger(__name__)


class CacheClient:
    """
    Redis cache client for meeting metadata and decision status.
    """
    
    def __init__(self, redis_url: str):
        """
        Initialize Redis cache client.
        
        Args:
            redis_url: Redis connection URL
        """
        self.redis_url = redis_url
        self._client: Optional[redis.Redis] = None
        logger.info(f"Initialized CacheClient with URL: {redis_url}")
    
    async def connect(self):
        """Establish Redis connection."""
        if not self._client:
            self._client = await redis.from_url(
                self.redis_url,
                encoding="utf-8",
                decode_responses=True
            )
            logger.info("Redis connection established")
    
    async def disconnect(self):
        """Close Redis connection."""
        if self._client:
            await self._client.aclose()
            self._client = None
            logger.info("Redis connection closed")
    
    async def get(self, key: str) -> Optional[Any]:
        """
        Get value from cache.
        
        Args:
            key: Cache key
            
        Returns:
            Cached value or None if not found
        """
        if not self._client:
            await self.connect()
        
        try:
            value = await self._client.get(key)
            if value:
                logger.debug(f"Cache HIT: {key}")
                return json.loads(value)
            logger.debug(f"Cache MISS: {key}")
            return None
        except Exception as e:
            logger.error(f"Cache GET error for key {key}: {e}")
            return None
    
    async def set(
        self,
        key: str,
        value: Any,
        ttl: Optional[int] = None
    ) -> bool:
        """
        Set value in cache.
        
        Args:
            key: Cache key
            value: Value to cache (will be JSON serialized)
            ttl: Time to live in seconds (optional)
            
        Returns:
            True if successful, False otherwise
        """
        if not self._client:
            await self.connect()
        
        try:
            serialized = json.dumps(value)
            if ttl:
                await self._client.setex(key, ttl, serialized)
            else:
                await self._client.set(key, serialized)
            logger.debug(f"Cache SET: {key} (TTL: {ttl}s)")
            return True
        except Exception as e:
            logger.error(f"Cache SET error for key {key}: {e}")
            return False
    
    async def delete(self, key: str) -> bool:
        """
        Delete value from cache.
        
        Args:
            key: Cache key
            
        Returns:
            True if successful, False otherwise
        """
        if not self._client:
            await self.connect()
        
        try:
            await self._client.delete(key)
            logger.debug(f"Cache DELETE: {key}")
            return True
        except Exception as e:
            logger.error(f"Cache DELETE error for key {key}: {e}")
            return False
    
    async def invalidate_pattern(self, pattern: str) -> int:
        """
        Invalidate all keys matching pattern.
        
        Args:
            pattern: Key pattern (e.g., "meeting:*")
            
        Returns:
            Number of keys deleted
        """
        if not self._client:
            await self.connect()
        
        try:
            keys = []
            async for key in self._client.scan_iter(match=pattern):
                keys.append(key)
            
            if keys:
                deleted = await self._client.delete(*keys)
                logger.info(f"Cache INVALIDATE: {pattern} ({deleted} keys)")
                return deleted
            return 0
        except Exception as e:
            logger.error(f"Cache INVALIDATE error for pattern {pattern}: {e}")
            return 0


# Global cache client instance
_cache_client: Optional[CacheClient] = None


def get_cache_client(redis_url: str = "redis://localhost:6379/0") -> CacheClient:
    """
    Get or create global cache client instance.
    
    Args:
        redis_url: Redis connection URL
        
    Returns:
        CacheClient instance
    """
    global _cache_client
    if not _cache_client:
        _cache_client = CacheClient(redis_url)
    return _cache_client


# Cache key builders
def meeting_cache_key(meeting_id: str) -> str:
    """Build cache key for meeting metadata."""
    return f"meeting:{meeting_id}"


def decision_cache_key(decision_id: str) -> str:
    """Build cache key for decision status."""
    return f"decision:{decision_id}"


def meeting_decisions_cache_key(meeting_id: str) -> str:
    """Build cache key for meeting decisions list."""
    return f"meeting:{meeting_id}:decisions"


# Cache TTL constants (in seconds)
MEETING_CACHE_TTL = 3600  # 1 hour
DECISION_CACHE_TTL = 300  # 5 minutes
