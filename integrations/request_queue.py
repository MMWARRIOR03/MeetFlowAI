"""
Request queuing system for handling heavy load.
"""
import asyncio
import logging
from typing import Any, Callable, Optional
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum


logger = logging.getLogger(__name__)


class QueuePriority(Enum):
    """Request priority levels."""
    HIGH = 1
    NORMAL = 2
    LOW = 3


@dataclass
class QueuedRequest:
    """Queued request with metadata."""
    request_id: str
    handler: Callable
    args: tuple
    kwargs: dict
    priority: QueuePriority
    created_at: datetime
    future: asyncio.Future


class RequestQueue:
    """
    Async request queue with priority and concurrency control.
    """
    
    def __init__(
        self,
        max_concurrent: int = 10,
        max_queue_size: int = 1000
    ):
        """
        Initialize request queue.
        
        Args:
            max_concurrent: Maximum concurrent requests
            max_queue_size: Maximum queue size
        """
        self.max_concurrent = max_concurrent
        self.max_queue_size = max_queue_size
        self.queue: asyncio.PriorityQueue = asyncio.PriorityQueue(maxsize=max_queue_size)
        self.active_requests = 0
        self.total_processed = 0
        self.total_failed = 0
        self._workers: list[asyncio.Task] = []
        self._running = False
        logger.info(
            f"Initialized RequestQueue: max_concurrent={max_concurrent}, "
            f"max_queue_size={max_queue_size}"
        )
    
    async def start(self):
        """Start queue workers."""
        if self._running:
            logger.warning("RequestQueue already running")
            return
        
        self._running = True
        self._workers = [
            asyncio.create_task(self._worker(i))
            for i in range(self.max_concurrent)
        ]
        logger.info(f"Started {self.max_concurrent} queue workers")
    
    async def stop(self):
        """Stop queue workers."""
        if not self._running:
            return
        
        self._running = False
        
        # Cancel all workers
        for worker in self._workers:
            worker.cancel()
        
        # Wait for workers to finish
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers = []
        
        logger.info("Stopped queue workers")
    
    async def enqueue(
        self,
        request_id: str,
        handler: Callable,
        *args,
        priority: QueuePriority = QueuePriority.NORMAL,
        **kwargs
    ) -> Any:
        """
        Enqueue request for processing.
        
        Args:
            request_id: Unique request identifier
            handler: Async function to execute
            *args: Positional arguments for handler
            priority: Request priority
            **kwargs: Keyword arguments for handler
            
        Returns:
            Result from handler
            
        Raises:
            asyncio.QueueFull: If queue is full
        """
        if not self._running:
            await self.start()
        
        # Create future for result
        future = asyncio.Future()
        
        # Create queued request
        queued_request = QueuedRequest(
            request_id=request_id,
            handler=handler,
            args=args,
            kwargs=kwargs,
            priority=priority,
            created_at=datetime.now(timezone.utc),
            future=future
        )
        
        # Add to queue (priority, timestamp, request)
        # Lower priority value = higher priority
        try:
            await self.queue.put((
                priority.value,
                queued_request.created_at.timestamp(),
                queued_request
            ))
            logger.debug(
                f"Enqueued request {request_id} with priority {priority.name}"
            )
        except asyncio.QueueFull:
            logger.error(f"Queue full, rejecting request {request_id}")
            raise
        
        # Wait for result
        return await future
    
    async def _worker(self, worker_id: int):
        """
        Worker coroutine that processes queued requests.
        
        Args:
            worker_id: Worker identifier
        """
        logger.info(f"Worker {worker_id} started")
        
        while self._running:
            try:
                # Get next request from queue (with timeout)
                try:
                    priority, timestamp, queued_request = await asyncio.wait_for(
                        self.queue.get(),
                        timeout=1.0
                    )
                except asyncio.TimeoutError:
                    continue
                
                self.active_requests += 1
                
                # Calculate queue time
                queue_time = (datetime.now(timezone.utc) - queued_request.created_at).total_seconds()
                logger.debug(
                    f"Worker {worker_id} processing request {queued_request.request_id} "
                    f"(queued for {queue_time:.2f}s)"
                )
                
                # Execute handler
                try:
                    result = await queued_request.handler(
                        *queued_request.args,
                        **queued_request.kwargs
                    )
                    queued_request.future.set_result(result)
                    self.total_processed += 1
                    logger.debug(
                        f"Worker {worker_id} completed request {queued_request.request_id}"
                    )
                except Exception as e:
                    queued_request.future.set_exception(e)
                    self.total_failed += 1
                    logger.error(
                        f"Worker {worker_id} failed request {queued_request.request_id}: {e}"
                    )
                finally:
                    self.active_requests -= 1
                    self.queue.task_done()
                    
            except asyncio.CancelledError:
                logger.info(f"Worker {worker_id} cancelled")
                break
            except Exception as e:
                logger.error(f"Worker {worker_id} error: {e}")
        
        logger.info(f"Worker {worker_id} stopped")
    
    def get_stats(self) -> dict:
        """
        Get queue statistics.
        
        Returns:
            Dictionary with queue stats
        """
        return {
            "active_requests": self.active_requests,
            "queued_requests": self.queue.qsize(),
            "total_processed": self.total_processed,
            "total_failed": self.total_failed,
            "max_concurrent": self.max_concurrent,
            "max_queue_size": self.max_queue_size,
            "running": self._running
        }


# Global request queue instance
_request_queue: Optional[RequestQueue] = None


def get_request_queue(
    max_concurrent: int = 10,
    max_queue_size: int = 1000
) -> RequestQueue:
    """
    Get or create global request queue instance.
    
    Args:
        max_concurrent: Maximum concurrent requests
        max_queue_size: Maximum queue size
        
    Returns:
        RequestQueue instance
    """
    global _request_queue
    if not _request_queue:
        _request_queue = RequestQueue(max_concurrent, max_queue_size)
    return _request_queue
