"""
Functional Testing - Test critical bugs and core functionality without running server.

Tests:
1. CircuitBreaker: Verify None check bug (Bug #1)
2. Rate Limiter: Basic functionality
3. Embedding Model: Load and embed
4. LLM Provider: Circuit breaker states
"""

import asyncio
import sys
import os
from typing import Optional

# Setup logging
import logging
logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
logger = logging.getLogger(__name__)


async def test_circuit_breaker_none_check():
    """Test Bug #1: CircuitBreaker None check on first failure"""
    logger.info("\n=== TEST 1: CircuitBreaker None Check ===")
    
    from llm_provider import CircuitBreaker, CircuitBreakerState
    
    cb = CircuitBreaker(failure_threshold=1, cooldown_sec=1)
    logger.info(f"Initial state: {cb.state}")
    logger.info(f"Initial last_failure_time: {cb.last_failure_time}")
    
    # Simulate first failure
    try:
        async def failing_coro():
            raise Exception("Simulated LLM failure")
        
        await cb.call(failing_coro())
    except Exception as e:
        logger.info(f"First failure captured: {e}")
    
    logger.info(f"State after failure: {cb.state}")
    logger.info(f"last_failure_time set: {cb.last_failure_time is not None}")
    
    # Now try to call again while circuit is OPEN
    # BUG #1: This will crash with TypeError if last_failure_time check is missing
    try:
        async def another_coro():
            return "should not run"
        
        await cb.call(another_coro())
        logger.error("❌ BUG NOT FOUND: Should have raised RuntimeError (circuit open)")
        return False
    except RuntimeError as e:
        if "OPEN" in str(e):
            logger.info(f"✅ Circuit breaker correctly OPEN: {e}")
            return True
        else:
            logger.error(f"❌ Unexpected RuntimeError: {e}")
            return False
    except TypeError as e:
        logger.error(f"❌ BUG FOUND (TypeError): {e}")
        logger.error("   This is the None check bug - last_failure_time is None")
        return False


async def test_rate_limiter_basic():
    """Test Token Bucket Rate Limiter basic functionality"""
    logger.info("\n=== TEST 2: Token Bucket Rate Limiter ===")
    
    from rate_limiter import TokenBucketRateLimiter
    from cache_redis import RedisCache
    
    try:
        # Initialize Redis
        cache = RedisCache(redis_url=None, ttl_seconds=3600)
        await cache.connect()
        
        limiter = TokenBucketRateLimiter(
            redis_client=cache.client,
            max_requests=3,
            window_seconds=60
        )
        
        # Test 3 requests should succeed
        for i in range(3):
            allowed, remaining, reset_at = await limiter.check_rate_limit("test_user")
            logger.info(f"Request {i+1}: allowed={allowed}, remaining={remaining}")
            if not allowed:
                logger.error(f"❌ Request {i+1} denied when it should be allowed")
                await cache.disconnect()
                return False
        
        # 4th request should fail
        allowed, remaining, reset_at = await limiter.check_rate_limit("test_user")
        logger.info(f"Request 4: allowed={allowed}, remaining={remaining}")
        if allowed:
            logger.error("❌ 4th request allowed when it should be denied")
            await cache.disconnect()
            return False
        
        logger.info("✅ Rate limiter working correctly")
        await cache.disconnect()
        return True
        
    except Exception as e:
        logger.error(f"❌ Error testing rate limiter: {e}")
        return False


async def test_embedding_model():
    """Test embedding model loading"""
    logger.info("\n=== TEST 3: Embedding Model ===")
    
    try:
        from embeddings import embedding_model
        
        await embedding_model.load()
        logger.info("✅ Embedding model loaded")
        
        # Test embedding
        text = "hello world"
        embedding = await embedding_model.embed(text)
        logger.info(f"✅ Generated embedding (dim={len(embedding)})")
        
        await embedding_model.close()
        return True
        
    except Exception as e:
        logger.error(f"❌ Error testing embedding model: {e}")
        return False


async def test_redis_connection():
    """Test Redis connection"""
    logger.info("\n=== TEST 4: Redis Connection ===")
    
    try:
        from cache_redis import RedisCache
        
        cache = RedisCache(redis_url=None, ttl_seconds=3600)
        await cache.connect()
        
        # Test set/get
        await cache.set("test_key", "test_value")
        value = await cache.get("test_key")
        
        if value == "test_value":
            logger.info("✅ Redis set/get working")
            await cache.disconnect()
            return True
        else:
            logger.error(f"❌ Redis get returned wrong value: {value}")
            await cache.disconnect()
            return False
            
    except Exception as e:
        logger.error(f"❌ Error testing Redis: {e}")
        return False


async def test_metrics_recording():
    """Test metrics recording"""
    logger.info("\n=== TEST 5: Metrics Recording ===")
    
    try:
        import metrics
        
        # Record some metrics
        metrics.record_request(endpoint="/test", status=200, duration_seconds=0.05)
        metrics.record_request(endpoint="/test", status=200, duration_seconds=0.06)
        metrics.record_request(endpoint="/test", status=500, duration_seconds=0.10)
        
        logger.info("✅ Metrics recorded successfully")
        return True
        
    except Exception as e:
        logger.error(f"❌ Error recording metrics: {e}")
        return False


async def main():
    """Run all tests"""
    logger.info("=" * 60)
    logger.info("SENTINEL V2 - FUNCTIONAL TEST SUITE")
    logger.info("=" * 60)
    
    results = []
    
    # Test 1: Circuit Breaker None Check (Bug #1)
    try:
        results.append(("CircuitBreaker None Check (Bug #1)", await test_circuit_breaker_none_check()))
    except Exception as e:
        logger.error(f"FATAL: CircuitBreaker test crashed: {e}")
        results.append(("CircuitBreaker None Check (Bug #1)", False))
    
    # Test 2: Rate Limiter
    try:
        results.append(("Rate Limiter", await test_rate_limiter_basic()))
    except Exception as e:
        logger.error(f"FATAL: Rate Limiter test crashed: {e}")
        results.append(("Rate Limiter", False))
    
    # Test 3: Embedding Model
    try:
        results.append(("Embedding Model", await test_embedding_model()))
    except Exception as e:
        logger.error(f"FATAL: Embedding test crashed: {e}")
        results.append(("Embedding Model", False))
    
    # Test 4: Redis Connection
    try:
        results.append(("Redis Connection", await test_redis_connection()))
    except Exception as e:
        logger.error(f"FATAL: Redis test crashed: {e}")
        results.append(("Redis Connection", False))
    
    # Test 5: Metrics Recording
    try:
        results.append(("Metrics Recording", await test_metrics_recording()))
    except Exception as e:
        logger.error(f"FATAL: Metrics test crashed: {e}")
        results.append(("Metrics Recording", False))
    
    # Summary
    logger.info("\n" + "=" * 60)
    logger.info("TEST SUMMARY")
    logger.info("=" * 60)
    
    passed = 0
    failed = 0
    
    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        logger.info(f"{status:10} | {test_name}")
        if result:
            passed += 1
        else:
            failed += 1
    
    logger.info("=" * 60)
    logger.info(f"TOTAL: {passed} passed, {failed} failed")
    logger.info("=" * 60)
    
    return failed == 0


if __name__ == "__main__":
    # Ensure Redis is running
    os.environ["REDIS_URL"] = "redis://localhost:6379"
    os.environ["GROQ_API_KEY"] = "dummy"
    
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
