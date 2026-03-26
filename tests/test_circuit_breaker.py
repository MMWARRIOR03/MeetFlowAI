"""
Tests for circuit breaker pattern implementation.
"""
import pytest
import asyncio
from datetime import datetime

from integrations.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitBreakerError,
    CircuitState,
    get_circuit_breaker
)


@pytest.mark.asyncio
async def test_circuit_breaker_closed_state():
    """Test circuit breaker in CLOSED state allows requests."""
    breaker = CircuitBreaker("test", CircuitBreakerConfig(failure_threshold=3))
    
    async def success_func():
        return "success"
    
    result = await breaker.call(success_func)
    assert result == "success"
    assert breaker.stats.state == CircuitState.CLOSED
    assert breaker.stats.total_successes == 1
    assert breaker.stats.failure_count == 0


@pytest.mark.asyncio
async def test_circuit_breaker_opens_after_failures():
    """Test circuit breaker opens after threshold failures."""
    breaker = CircuitBreaker("test", CircuitBreakerConfig(failure_threshold=3))
    
    async def failing_func():
        raise ValueError("Test error")
    
    # First 3 failures should be allowed
    for i in range(3):
        with pytest.raises(ValueError):
            await breaker.call(failing_func)
    
    # Circuit should now be OPEN
    assert breaker.stats.state == CircuitState.OPEN
    assert breaker.stats.failure_count == 3
    
    # Next call should be rejected immediately
    with pytest.raises(CircuitBreakerError):
        await breaker.call(failing_func)


@pytest.mark.asyncio
async def test_circuit_breaker_half_open_recovery():
    """Test circuit breaker transitions to HALF_OPEN and recovers."""
    breaker = CircuitBreaker(
        "test",
        CircuitBreakerConfig(
            failure_threshold=2,
            recovery_timeout=1,  # 1 second for testing
            success_threshold=2
        )
    )
    
    async def failing_func():
        raise ValueError("Test error")
    
    async def success_func():
        return "success"
    
    # Open the circuit
    for i in range(2):
        with pytest.raises(ValueError):
            await breaker.call(failing_func)
    
    assert breaker.stats.state == CircuitState.OPEN
    
    # Wait for recovery timeout
    await asyncio.sleep(1.1)
    
    # Next call should transition to HALF_OPEN
    result = await breaker.call(success_func)
    assert result == "success"
    assert breaker.stats.state == CircuitState.HALF_OPEN
    
    # Another success should close the circuit
    result = await breaker.call(success_func)
    assert result == "success"
    assert breaker.stats.state == CircuitState.CLOSED


@pytest.mark.asyncio
async def test_circuit_breaker_half_open_reopens_on_failure():
    """Test circuit breaker reopens if failure occurs in HALF_OPEN."""
    breaker = CircuitBreaker(
        "test",
        CircuitBreakerConfig(
            failure_threshold=2,
            recovery_timeout=1,
            success_threshold=2
        )
    )
    
    async def failing_func():
        raise ValueError("Test error")
    
    # Open the circuit
    for i in range(2):
        with pytest.raises(ValueError):
            await breaker.call(failing_func)
    
    assert breaker.stats.state == CircuitState.OPEN
    
    # Wait for recovery timeout
    await asyncio.sleep(1.1)
    
    # Failure in HALF_OPEN should reopen circuit
    with pytest.raises(ValueError):
        await breaker.call(failing_func)
    
    assert breaker.stats.state == CircuitState.OPEN


@pytest.mark.asyncio
async def test_circuit_breaker_stats():
    """Test circuit breaker statistics tracking."""
    breaker = CircuitBreaker("test", CircuitBreakerConfig(failure_threshold=3))
    
    async def success_func():
        return "success"
    
    async def failing_func():
        raise ValueError("Test error")
    
    # Execute some calls
    await breaker.call(success_func)
    await breaker.call(success_func)
    
    with pytest.raises(ValueError):
        await breaker.call(failing_func)
    
    stats = breaker.get_stats()
    
    assert stats["name"] == "test"
    assert stats["state"] == CircuitState.CLOSED.value
    assert stats["total_calls"] == 3
    assert stats["total_successes"] == 2
    assert stats["total_failures"] == 1
    assert stats["failure_count"] == 1


@pytest.mark.asyncio
async def test_circuit_breaker_reset():
    """Test circuit breaker reset functionality."""
    breaker = CircuitBreaker("test", CircuitBreakerConfig(failure_threshold=2))
    
    async def failing_func():
        raise ValueError("Test error")
    
    # Open the circuit
    for i in range(2):
        with pytest.raises(ValueError):
            await breaker.call(failing_func)
    
    assert breaker.stats.state == CircuitState.OPEN
    
    # Reset the circuit
    await breaker.reset()
    
    assert breaker.stats.state == CircuitState.CLOSED
    assert breaker.stats.failure_count == 0
    assert breaker.stats.total_calls == 0


@pytest.mark.asyncio
async def test_get_circuit_breaker_registry():
    """Test circuit breaker registry."""
    config = CircuitBreakerConfig(failure_threshold=5)
    
    breaker1 = await get_circuit_breaker("test_service", config)
    breaker2 = await get_circuit_breaker("test_service")
    
    # Should return same instance
    assert breaker1 is breaker2
    assert breaker1.name == "test_service"
