"""
HTTP client with connection pooling.
"""
import logging
from typing import Optional, Dict, Any
import httpx


logger = logging.getLogger(__name__)


class HTTPClientPool:
    """
    HTTP client with connection pooling for external API calls.
    """
    
    def __init__(
        self,
        max_connections: int = 100,
        max_keepalive_connections: int = 20,
        timeout: float = 30.0
    ):
        """
        Initialize HTTP client pool.
        
        Args:
            max_connections: Maximum number of connections
            max_keepalive_connections: Maximum keepalive connections
            timeout: Request timeout in seconds
        """
        self.max_connections = max_connections
        self.max_keepalive_connections = max_keepalive_connections
        self.timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None
        logger.info(
            f"Initialized HTTPClientPool: max_connections={max_connections}, "
            f"max_keepalive={max_keepalive_connections}"
        )
    
    async def get_client(self) -> httpx.AsyncClient:
        """
        Get or create HTTP client with connection pooling.
        
        Returns:
            httpx.AsyncClient instance
        """
        if not self._client:
            limits = httpx.Limits(
                max_connections=self.max_connections,
                max_keepalive_connections=self.max_keepalive_connections
            )
            self._client = httpx.AsyncClient(
                limits=limits,
                timeout=httpx.Timeout(self.timeout),
                follow_redirects=True
            )
            logger.info("HTTP client created with connection pooling")
        return self._client
    
    async def close(self):
        """Close HTTP client and release connections."""
        if self._client:
            await self._client.aclose()
            self._client = None
            logger.info("HTTP client closed")
    
    async def get(
        self,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None
    ) -> httpx.Response:
        """
        Make GET request.
        
        Args:
            url: Request URL
            headers: Optional headers
            params: Optional query parameters
            
        Returns:
            Response object
        """
        client = await self.get_client()
        logger.debug(f"GET {url}")
        return await client.get(url, headers=headers, params=params)
    
    async def post(
        self,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        json: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None
    ) -> httpx.Response:
        """
        Make POST request.
        
        Args:
            url: Request URL
            headers: Optional headers
            json: Optional JSON body
            data: Optional form data
            
        Returns:
            Response object
        """
        client = await self.get_client()
        logger.debug(f"POST {url}")
        return await client.post(url, headers=headers, json=json, data=data)
    
    async def put(
        self,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        json: Optional[Dict[str, Any]] = None
    ) -> httpx.Response:
        """
        Make PUT request.
        
        Args:
            url: Request URL
            headers: Optional headers
            json: Optional JSON body
            
        Returns:
            Response object
        """
        client = await self.get_client()
        logger.debug(f"PUT {url}")
        return await client.put(url, headers=headers, json=json)
    
    async def delete(
        self,
        url: str,
        headers: Optional[Dict[str, str]] = None
    ) -> httpx.Response:
        """
        Make DELETE request.
        
        Args:
            url: Request URL
            headers: Optional headers
            
        Returns:
            Response object
        """
        client = await self.get_client()
        logger.debug(f"DELETE {url}")
        return await client.delete(url, headers=headers)


# Global HTTP client pool instance
_http_client_pool: Optional[HTTPClientPool] = None


def get_http_client_pool(
    max_connections: int = 100,
    max_keepalive_connections: int = 20,
    timeout: float = 30.0
) -> HTTPClientPool:
    """
    Get or create global HTTP client pool instance.
    
    Args:
        max_connections: Maximum number of connections
        max_keepalive_connections: Maximum keepalive connections
        timeout: Request timeout in seconds
        
    Returns:
        HTTPClientPool instance
    """
    global _http_client_pool
    if not _http_client_pool:
        _http_client_pool = HTTPClientPool(
            max_connections,
            max_keepalive_connections,
            timeout
        )
    return _http_client_pool
