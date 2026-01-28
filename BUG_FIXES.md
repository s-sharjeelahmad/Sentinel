# Sentinel V2: Critical Bug Fixes

**Status:** 2 bugs identified that MUST be fixed before production deployment  
**Estimated Fix Time:** 30 minutes  
**Risk Level:** High (affects correctness and reliability)

---

## Bug #1: CircuitBreaker None Check (MUST FIX)

### Location

`llm_provider.py`, CircuitBreaker.call() method, line ~30

### Current Code (BROKEN)

```python
async def call(self, coro):
    """Execute coroutine with circuit breaker protection."""
    if self.state == CircuitBreakerState.OPEN:
        # ❌ BUG: last_failure_time is None on first failure
        if time.time() - self.last_failure_time > self.cooldown_sec:
            self.state = CircuitBreakerState.HALF_OPEN
            logger.info("Circuit breaker: HALF_OPEN - attempting recovery")
        else:
            raise RuntimeError("Circuit breaker OPEN - LLM API unavailable")
```

### Problem

- On **first LLM failure**, `self.last_failure_time` is initialized as `None`
- Next request checks `if self.state == OPEN` → True
- Attempts: `time.time() - None` → **TypeError: unsupported operand type(s)**
- Result: **Crash instead of graceful failure**

### Fixed Code

```python
async def call(self, coro):
    """Execute coroutine with circuit breaker protection."""
    if self.state == CircuitBreakerState.OPEN:
        # ✅ FIXED: Check if last_failure_time is set before comparing
        if self.last_failure_time and time.time() - self.last_failure_time > self.cooldown_sec:
            self.state = CircuitBreakerState.HALF_OPEN
            logger.info("Circuit breaker: HALF_OPEN - attempting recovery")
        else:
            raise RuntimeError("Circuit breaker OPEN - LLM API unavailable")
```

### Why This Matters

- **Correctness:** Circuit breaker must NEVER crash; must always fail gracefully
- **Cost:** Crash = restart = downtime; graceful fail = 503 response (fast recovery)
- **Interview Signal:** Error handling must be bulletproof

### Test Case

```python
# This should NOT crash
cb = CircuitBreaker()
try:
    # First failure
    for i in range(5):
        try:
            await cb.call(failing_coro())
        except Exception:
            pass
    # Should be in OPEN state now, not crashed
    assert cb.state == CircuitBreakerState.OPEN
except Exception as e:
    print(f"❌ FAILED: {e}")  # Should not reach here
```

---

## Bug #2: Duplicate active_requests Counter Decrement (MUST FIX)

### Location

`main.py`, log_requests middleware, lines ~145-160

### Current Code (BROKEN)

```python
@app.middleware("http")
async def log_requests(request: Request, call_next):
    global active_requests

    if shutdown_event and shutdown_event.is_set():
        return JSONResponse(status_code=503, content={"error": "server_shutting_down"})

    active_requests += 1

    try:
        response = await call_next(request)
    except Exception as e:
        logger.error(f"Request error: {e}")
        active_requests -= 1  # ❌ BUG: Decremented here
        raise
    finally:
        if active_requests > 0:
            active_requests -= 1  # ❌ BUG: Decremented again here

    # ... rest of middleware ...
    return response
```

### Problem

- **Normal flow:**
  - `active_requests += 1` (increment)
  - No exception
  - `finally` block: `active_requests -= 1` (decrement)
  - **Result: Correct** ✅

- **Exception flow:**
  - `active_requests += 1` (increment)
  - Exception occurs
  - `except` block: `active_requests -= 1` (decrement once)
  - `finally` block: `active_requests -= 1` (decrement AGAIN)
  - **Result: Counter goes negative!** ❌

### Impact on Graceful Shutdown

```python
# In lifespan function
while active_requests > 0 and time.time() - start < TIMEOUT:
    logger.info(f"Waiting for {active_requests} active requests...")
    await asyncio.sleep(0.1)

# If counter is negative (-5):
# Condition: -5 > 0 → False
# Loop doesn't run
# Shutdown proceeds immediately (doesn't wait for real requests)
# Requests in-flight may be dropped ❌
```

### Fixed Code

```python
@app.middleware("http")
async def log_requests(request: Request, call_next):
    global active_requests

    if shutdown_event and shutdown_event.is_set():
        return JSONResponse(status_code=503, content={"error": "server_shutting_down"})

    active_requests += 1

    try:
        response = await call_next(request)
    finally:
        # ✅ FIXED: Decrement ONLY in finally, not in except
        if active_requests > 0:
            active_requests -= 1

    # ... rest of middleware ...
    return response
```

### Why This Matters

- **Correctness:** Graceful shutdown requires accurate active request count
- **Reliability:** Negative counter breaks shutdown logic
- **Downtime Risk:** If requests dropped during deployment, users see connection errors
- **Interview Signal:** Understanding of exception handling and finally blocks

### Test Case

```python
# Simulate normal request
active_requests = 0
await log_requests(normal_request, call_next_success)
assert active_requests == 0  # Should return to 0

# Simulate request with exception
active_requests = 0
try:
    await log_requests(error_request, call_next_error)
except:
    pass
assert active_requests == 0  # Should STILL be 0, not -1
```

---

## Bug Fix Checklist

### Bug #1: CircuitBreaker None Check

- [ ] Open `llm_provider.py`
- [ ] Find line ~30 in `CircuitBreaker.call()` method
- [ ] Change: `if time.time() - self.last_failure_time > self.cooldown_sec:`
- [ ] To: `if self.last_failure_time and time.time() - self.last_failure_time > self.cooldown_sec:`
- [ ] Verify: `python -m py_compile llm_provider.py` (no syntax errors)

### Bug #2: active_requests Counter

- [ ] Open `main.py`
- [ ] Find `log_requests` middleware function (~line 130)
- [ ] Remove: `active_requests -= 1` from except block (3 lines)
- [ ] Keep: `active_requests -= 1` in finally block only
- [ ] Verify: `python -m py_compile main.py` (no syntax errors)

### Testing

- [ ] Manual: Restart app, make requests, verify no crashes
- [ ] Integration: Test with forced LLM errors (curl with bad API key)
- [ ] Graceful Shutdown: Send SIGTERM, verify requests drain

---

## Verification Commands

After applying fixes:

```bash
# Syntax check
python -m py_compile llm_provider.py main.py

# Run with dummy env (no real LLM API key)
export REDIS_URL="redis://localhost:6379"
export GROQ_API_KEY="dummy-key-for-testing"
uvicorn main:app --host 0.0.0.0 --port 8000 &

# Test LLM failure scenario (should NOT crash)
curl -X POST http://localhost:8000/v1/query \
  -H "X-API-Key: test-key-1" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "test", "model": "llama-3.1-8b-instant"}'

# Should see: 503 Service Unavailable (not 500 Internal Error)
# Circuit breaker OPEN log message should appear

# Test graceful shutdown
kill -SIGTERM $!  # Kill server
# Should see: "Sentinel shut down" message (not crash)
```

---

## Impact Assessment

| Bug | Severity | Impact                     | When It Happens           | Fix Time  |
| --- | -------- | -------------------------- | ------------------------- | --------- |
| #1  | CRITICAL | Crash on first LLM failure | Production LLM outages    | 2 minutes |
| #2  | CRITICAL | Graceful shutdown broken   | Deployments drop requests | 3 minutes |

**Do Not Deploy Without Fixing Both.**

---

## References

- **Bug #1:** Python TypeError on None arithmetic operations
- **Bug #2:** Exception handling anti-pattern (duplicate cleanup in except + finally)
- **Pattern:** Correct exception handling uses only `finally` for guaranteed cleanup

---
