"""
Integration Test: Verify Bug #1 fix (CircuitBreaker None check)
"""

import asyncio
import logging

logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
logger = logging.getLogger(__name__)


async def test_circuit_breaker_bug1_fix():
    """
    Test that CircuitBreaker properly handles None check on first failure.
    
    Timeline:
    1. Circuit starts in CLOSED state
    2. First request fails -> state = OPEN, last_failure_time = time.time()
    3. Second request while OPEN -> should raise RuntimeError (not TypeError)
    4. After cooldown -> state = HALF_OPEN, attempt recovery
    """
    from llm_provider import CircuitBreaker, CircuitBreakerState
    import time
    
    logger.info("\n" + "="*70)
    logger.info("TEST: CircuitBreaker None Check Fix (Bug #1)")
    logger.info("="*70)
    
    # Create circuit breaker with 1 failure threshold and 2s cooldown
    cb = CircuitBreaker(failure_threshold=1, cooldown_sec=2)
    
    # Step 1: Verify initial state
    logger.info(f"\n[1] Initial state: {cb.state.name}")
    logger.info(f"    last_failure_time: {cb.last_failure_time}")
    assert cb.state == CircuitBreakerState.CLOSED, "Should start CLOSED"
    assert cb.last_failure_time is None, "Should have no failure time initially"
    
    # Step 2: First failure -> transitions to OPEN
    logger.info(f"\n[2] Simulating first failure...")
    async def failing_request():
        raise Exception("Groq API timeout")
    
    try:
        await cb.call(failing_request())
    except Exception as e:
        logger.info(f"    Caught exception: {type(e).__name__}: {e}")
    
    logger.info(f"    State after failure: {cb.state.name}")
    logger.info(f"    last_failure_time: {cb.last_failure_time is not None}")
    assert cb.state == CircuitBreakerState.OPEN, "Should be OPEN after failure"
    assert cb.last_failure_time is not None, "Should have set failure time"
    
    # Step 3: Second request while OPEN -> should fail with RuntimeError (not TypeError)
    logger.info(f"\n[3] Second request while circuit OPEN (cooldown not elapsed)...")
    async def second_request():
        return "should not execute"
    
    try:
        await cb.call(second_request())
        logger.error("    ❌ FAIL: Should have raised RuntimeError")
        return False
    except RuntimeError as e:
        if "OPEN" in str(e):
            logger.info(f"    ✅ Correctly raised RuntimeError: {e}")
        else:
            logger.error(f"    ❌ FAIL: Wrong RuntimeError: {e}")
            return False
    except TypeError as e:
        logger.error(f"    ❌ FAIL: TypeError (Bug #1 not fixed): {e}")
        logger.error(f"           This means last_failure_time is still None")
        return False
    
    # Step 4: Wait for cooldown and try HALF_OPEN transition
    logger.info(f"\n[4] Waiting for cooldown (2 seconds)...")
    await asyncio.sleep(2.1)
    logger.info(f"    Cooldown elapsed, next request should try HALF_OPEN state")
    
    async def recovery_request():
        return "recovery attempt"
    
    try:
        result = await cb.call(recovery_request())
        logger.info(f"    ✅ Recovery request executed: {result}")
        logger.info(f"    State: {cb.state.name}")
    except Exception as e:
        logger.error(f"    ❌ Recovery request failed: {e}")
        return False
    
    logger.info("\n" + "="*70)
    logger.info("✅ TEST PASSED: Bug #1 (None check) is FIXED")
    logger.info("="*70)
    return True


async def test_multiple_failures():
    """
    Test circuit breaker with multiple failures to ensure None check works
    """
    from llm_provider import CircuitBreaker, CircuitBreakerState
    
    logger.info("\n" + "="*70)
    logger.info("TEST: Multiple Failures (Stress Test)")
    logger.info("="*70)
    
    cb = CircuitBreaker(failure_threshold=2, cooldown_sec=1)
    
    # Simulate 3 failures
    for i in range(3):
        logger.info(f"\n[Failure {i+1}]")
        async def fail():
            raise Exception(f"Failure {i+1}")
        
        try:
            await cb.call(fail())
        except Exception as e:
            logger.info(f"  Caught: {type(e).__name__}")
        
        logger.info(f"  State: {cb.state.name}")
    
    # After 2+ failures, should be OPEN
    assert cb.state == CircuitBreakerState.OPEN, "Should be OPEN after 2 failures"
    logger.info(f"\n✅ Circuit correctly OPEN after threshold reached")
    
    # Try to call while OPEN - should fail with RuntimeError, not TypeError
    logger.info(f"\nAttempting call while OPEN (within cooldown)...")
    async def attempt():
        return "test"
    
    try:
        await cb.call(attempt())
        logger.error("❌ Should have raised RuntimeError")
        return False
    except RuntimeError as e:
        logger.info(f"✅ RuntimeError raised (None check works): {e}")
        return True
    except TypeError as e:
        logger.error(f"❌ TypeError (Bug still exists): {e}")
        return False


async def main():
    """Run all tests"""
    test1_pass = await test_circuit_breaker_bug1_fix()
    test2_pass = await test_multiple_failures()
    
    logger.info("\n" + "="*70)
    logger.info("FINAL RESULTS")
    logger.info("="*70)
    logger.info(f"Test 1 (Bug #1 Fix): {'✅ PASS' if test1_pass else '❌ FAIL'}")
    logger.info(f"Test 2 (Stress Test): {'✅ PASS' if test2_pass else '❌ FAIL'}")
    logger.info("="*70)
    
    return test1_pass and test2_pass


if __name__ == "__main__":
    success = asyncio.run(main())
    exit(0 if success else 1)
