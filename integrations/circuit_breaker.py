"""
Circuit breaker pattern implementation for external API calls.
Prevents cascading failures by opening circuit after consecutive failures.
"""
import asyncio
import logging
from datetime import datetime, timedelta
from enum import Enum
from typing import Callable, Any, Optional
from dataclasses import dataclass, field


logger = logging.getLogger(__name__)


class CircuitState(str, Enum):
    """Circuit breaker states."""
    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Circuit is open, rejecting requests
    HALF_OPEN = "half_open"  # Testing if service recovered


@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker."""
    failure_threshold: int = 5  # Open circuit after N consecutive failures
    recovery_timeout: int = 60  # Seconds before attempting recovery
    success_threshold: int = 2  # Successes needed in half-open to close circuit


@dataclass
class CircuitBreakerStats:
    """Statistics for circuit breaker."""
    state: CircuitState = CircuitState.CLOSED
    failure_count: int = 0
    success_count: int = 0
    last_failure_time: Optional[datetime] = None
    opened_at: Optional[datetime] = None
    total_calls: int = 0
    total_failures: int = 0
    total_successes: int = 0


class CircuitBreakerError(Exception):
    """Raised when circuit breaker is open."""
    pass


class CircuitBreaker:
    """
    Circuit breaker for external API calls.
    
    States:
    - CLOSED: Normal operation, requests pass through
    - OPEN: Circuit is open, requests are rejected immediately
    - HALF_OPEN: Testing recovery, limited requests allowed
    
    Transitions:
    - CLOSED -> OPEN: After failure_threshold consecutive failures
    - OPEN -> HALF_OPEN: After recovery_timeout seconds
    - HALF_OPEN -> CLOSED: After success_threshold consecutive successes
    - HALF_OPEN -> OPEN: On any failure
    """
    
    def __init__(
        self,
        name: str,
        config: Optional[CircuitBreakerConfig] = None
    ):
        """
        Initialize circuit breaker.
        
        Args:
            name: Name of the circuit (e.g., "gemini_api", "jira_api")
            config: Circuit breaker configuration
        """
        self.name = name
        self.config = config or CircuitBreakerConfig()
        self.stats = CircuitBreakerStats()
        self._lock = asyncio.Lock()
        
        logger.info(
            f"Circuit breaker '{name}' initialized: "
            f"failure_threshold={self.config.failure_threshold}, "
            f"recovery_timeout={self.config.recovery_timeout}s"
        )
    
    async def call(self, func: Callable, *args, **kwargs) -> Any:
        """
        Execute function with circuit breaker protection.
        
        Args:
            func: Async function to execute
            *args: Positional arguments for func
            **kwargs: Keyword arguments for func
            
        Returns:
            Result from func
            
        Raises:
            CircuitBreakerError: If circuit is open
            Exception: Original exception from func if circuit allows call
        """
        async with self._lock:
            self.stats.total_calls += 1
            
            # Check if circuit should transition from OPEN to HALF_OPEN
            if self.stats.state == CircuitState.OPEN:
                if self._should_attempt_recovery():
                    logger.info(f"Circuit '{self.name}' transitioning to HALF_OPEN")
                    self.stats.state = CircuitState.HALF_OPEN
                    self.stats.success_count = 0
                else:
                    # Circuit is still open, reject request
                    logger.warning(
                        f"Circuit '{self.name}' is OPEN, rejecting request "
                        f"(opened {self._time_since_opened():.1f}s ago)"
                    )
                    raise CircuitBreakerError(
                        f"Circuit breaker '{self.name}' is open. "
                        f"Service unavailable. Try again in "
                        f"{self._time_until_recovery():.1f}s"
                    )
        
        # Execute the function
        try:
            result = await func(*args, **kwargs)
            await self._on_success()
            return result
            
        except Exception as e:
            await self._on_failure(e)
            raise
    
    async def _on_success(self) -> None:
        """Handle successful call."""
        async with self._lock:
            self.stats.total_successes += 1
            self.stats.failure_count = 0  # Reset consecutive failures
            
            if self.stats.state == CircuitState.HALF_OPEN:
                self.stats.success_count += 1
                logger.info(
                    f"Circuit '{self.name}' success in HALF_OPEN "
                    f"({self.stats.success_count}/{self.config.success_threshold})"
                )
                
                # Close circuit if enough successes
                if self.stats.success_count >= self.config.success_threshold:
                    logger.info(f"Circuit '{self.name}' transitioning to CLOSED")
                    self.stats.state = CircuitState.CLOSED
                    self.stats.success_count = 0
                    self.stats.opened_at = None
    
    async def _on_failure(self, exception: Exception) -> None:
        """Handle failed call."""
        async with self._lock:
            self.stats.total_failures += 1
            self.stats.failure_count += 1
            self.stats.success_count = 0  # Reset consecutive successes
            self.stats.last_failure_time = datetime.utcnow()
            
            logger.warning(
                f"Circuit '{self.name}' failure "
                f"({self.stats.failure_count}/{self.config.failure_threshold}): "
                f"{type(exception).__name__}: {str(exception)}"
            )
            
            # Open circuit if threshold reached
            if self.stats.state == CircuitState.CLOSED:
                if self.stats.failure_count >= self.config.failure_threshold:
                    logger.error(
                        f"Circuit '{self.name}' transitioning to OPEN "
                        f"after {self.stats.failure_count} consecutive failures"
                    )
                    self.stats.state = CircuitState.OPEN
                    self.stats.opened_at = datetime.utcnow()
                    
            elif self.stats.state == CircuitState.HALF_OPEN:
                # Any failure in half-open reopens the circuit
                logger.error(
                    f"Circuit '{self.name}' transitioning back to OPEN "
                    f"(failure during recovery test)"
                )
                self.stats.state = CircuitState.OPEN
                self.stats.opened_at = datetime.utcnow()
    
    def _should_attempt_recovery(self) -> bool:
        """Check if enough time has passed to attempt recovery."""
        if not self.stats.opened_at:
            return False
        
        elapsed = (datetime.utcnow() - self.stats.opened_at).total_seconds()
        return elapsed >= self.config.recovery_timeout
    
    def _time_since_opened(self) -> float:
        """Get seconds since circuit was opened."""
        if not self.stats.opened_at:
            return 0.0
        return (datetime.utcnow() - self.stats.opened_at).total_seconds()
    
    def _time_until_recovery(self) -> float:
        """Get seconds until recovery attempt."""
        if not self.stats.opened_at:
            return 0.0
        
        elapsed = self._time_since_opened()
        remaining = self.config.recovery_timeout - elapsed
        return max(0.0, remaining)
    
    def get_stats(self) -> dict:
        """
        Get circuit breaker statistics.
        
        Returns:
            Dictionary with current stats
        """
        return {
            "name": self.name,
            "state": self.stats.state.value,
            "failure_count": self.stats.failure_count,
            "success_count": self.stats.success_count,
            "total_calls": self.stats.total_calls,
            "total_failures": self.stats.total_failures,
            "total_successes": self.stats.total_successes,
            "last_failure_time": self.stats.last_failure_time.isoformat() if self.stats.last_failure_time else None,
            "opened_at": self.stats.opened_at.isoformat() if self.stats.opened_at else None,
            "time_since_opened": self._time_since_opened() if self.stats.state == CircuitState.OPEN else None,
            "time_until_recovery": self._time_until_recovery() if self.stats.state == CircuitState.OPEN else None
        }
    
    async def reset(self) -> None:
        """Reset circuit breaker to initial state."""
        async with self._lock:
            logger.info(f"Resetting circuit breaker '{self.name}'")
            self.stats = CircuitBreakerStats()


class CircuitBreakerRegistry:
    """Registry for managing multiple circuit breakers."""
    
    def __init__(self):
        """Initialize circuit breaker registry."""
        self._breakers: dict[str, CircuitBreaker] = {}
        self._lock = asyncio.Lock()
    
    async def get_breaker(
        self,
        name: str,
        config: Optional[CircuitBreakerConfig] = None
    ) -> CircuitBreaker:
        """
        Get or create circuit breaker by name.
        
        Args:
            name: Circuit breaker name
            config: Configuration (only used if creating new breaker)
            
        Returns:
            CircuitBreaker instance
        """
        async with self._lock:
            if name not in self._breakers:
                self._breakers[name] = CircuitBreaker(name, config)
            return self._breakers[name]
    
    def get_all_stats(self) -> dict[str, dict]:
        """
        Get statistics for all circuit breakers.
        
        Returns:
            Dictionary mapping breaker names to their stats
        """
        return {
            name: breaker.get_stats()
            for name, breaker in self._breakers.items()
        }
    
    async def reset_all(self) -> None:
        """Reset all circuit breakers."""
        async with self._lock:
            for breaker in self._breakers.values():
                await breaker.reset()


# Global registry instance
_registry = CircuitBreakerRegistry()


async def get_circuit_breaker(
    name: str,
    config: Optional[CircuitBreakerConfig] = None
) -> CircuitBreaker:
    """
    Get circuit breaker from global registry.
    
    Args:
        name: Circuit breaker name
        config: Configuration (only used if creating new breaker)
        
    Returns:
        CircuitBreaker instance
    """
    return await _registry.get_breaker(name, config)


def get_all_circuit_breaker_stats() -> dict[str, dict]:
    """
    Get statistics for all circuit breakers.
    
    Returns:
        Dictionary mapping breaker names to their stats
    """
    return _registry.get_all_stats()
