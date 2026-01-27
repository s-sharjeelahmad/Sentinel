# Sentinel Development Notes

**Purpose:** Learning log for building Sentinel - a semantic AI gateway with caching.

**Philosophy:** Build simple first, add complexity only when simple solutions fail.

---

## Phase 1: Planning & Design (Before Writing Code)

### Step 1.1: System Definition (`docs/system.md`)

**What we did:** Defined the problem, non-goals, inputs/outputs, and architecture

**Why this matters:**

- Writing code without a design = rewriting 3 times
- Non-goals prevent feature creep ("should we add prompt optimization?" → No, not in v1)
- Inputs/outputs = your API contract

**Key decisions:**

- **Problem:** LLM APIs are expensive, many queries are semantically similar
- **Non-goals:** Not a prompt engineering tool, not multi-tenant, not a full observability platform
- **Architecture:** Client → Sentinel → Cache + LLM Provider

**Learning:** Always define scope before coding. If you can't describe inputs/outputs in 2 sentences, you don't understand the problem.

---

### Step 1.2: API Contract (`docs/api.md`)

**What we did:** Designed REST endpoints, request/response schemas, error codes

**Why this matters:**

- API design forces you to think from the client's perspective
- Defines "done" — when these endpoints work, we ship
- Version prefix (`/v1/`) prevents future breaking changes

**Key decisions:**

- **POST /v1/query** - Main endpoint, accepts prompt + model config
- **GET /v1/metrics** - Cache performance stats
- **GET /health** - Load balancer health checks
- **Why POST?** Prompts can be large (>2KB), contain sensitive data, not idempotent

**Learning:** Design the API before implementing it. Changing code is easy; changing a public API breaks clients.

---

## Phase 2: Minimal Working System (v0.1)

### Step 2.1: Project Structure

**What we did:** Created clean, modular file structure

```
Sentinel/
├── main.py              # FastAPI app, routes, middleware
├── cache.py             # Cache implementation
├── models.py            # Pydantic request/response schemas
├── requirements.txt     # Dependencies
├── README.md            # Usage documentation
└── docs/
    ├── system.md        # Architecture
    ├── api.md           # API contract
    └── notes.md         # This file
```

**Why this matters:**

- **Separation of concerns:** Cache logic doesn't know about HTTP, models don't know about FastAPI
- **Testability:** Can test cache.py without running a server
- **Readability:** Find the code you need in 5 seconds, not 5 minutes

**Learning:** Organize code by responsibility, not by file type. Each module has one job.

---

### Step 2.2: Cache Implementation (`cache.py`)

**What we did:** Built exact-match in-memory cache

```python
class ExactMatchCache:
    def __init__(self):
        self._cache = {}  # prompt → response
        self._hits = 0
        self._misses = 0

    def get(prompt: str) -> (response, is_hit):
        if prompt in self._cache:
            return self._cache[prompt], True
        return None, False

    def set(prompt: str, response: str):
        self._cache[prompt] = response
```

**Why start with exact-match (not semantic)?**

- Proves the caching logic works
- Simple to test and debug
- Validates the hypothesis: "Does caching save money?"

**Tradeoffs:**

- ✅ Instant lookup (nanoseconds)
- ✅ Zero dependencies
- ❌ Case-sensitive ("AI" ≠ "ai")
- ❌ No fuzzy matching ("What is AI?" ≠ "Explain AI")
- ❌ Lost on restart
- ❌ Single-process only

**Learning:** Start with the simplest thing that could possibly work. Optimize later when you have data proving it's needed.

---

### Step 2.3: Request/Response Models (`models.py`)

**What we did:** Defined Pydantic schemas for validation

```python
class QueryRequest(BaseModel):
    prompt: str = Field(..., min_length=1)
    provider: str = "openai"
    model: str = "gpt-4"
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
```

**Why Pydantic?**

- Auto-validates incoming JSON (rejects invalid requests before your code runs)
- Type hints → IDE autocomplete
- Auto-generates API documentation
- Serializes responses to JSON

**Example validation:**

```json
// ❌ This fails validation:
{"temperature": "hot"}  // Error: must be float

// ✅ This passes:
{"prompt": "What is AI?", "temperature": 0.7}
```

**Learning:** Use schemas everywhere. They're not "extra work" — they prevent bugs that would take hours to debug.

---

### Step 2.4: FastAPI Application (`main.py`)

**What we did:** Built REST API with 4 endpoints

#### Key Components:

**1. Logging Middleware**

```python
@app.middleware("http")
async def log_requests(request, call_next):
    start = time.time()
    response = await call_next(request)
    logger.info(f"← {response.status_code} | {time.time() - start}ms")
    return response
```

**Why:** Every request/response is logged. When something breaks, logs tell you what happened.

---

**2. Exception Handler**

```python
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(status_code=500, content={"error": "internal_error"})
```

**Why:** Prevents server crashes. Unhandled exceptions return proper error responses, not 500 with HTML.

---

**3. Main Endpoint: POST /v1/query**

```python
async def query(request: QueryRequest):
    cached_response, is_hit = cache.get(request.prompt)

    if is_hit:
        return QueryResponse(
            response=cached_response,
            cache_hit=True,
            tokens_used=0,
            latency_ms=5
        )

    # Simulate LLM call
    llm_response = generate_dummy_response(request.prompt)
    cache.set(request.prompt, llm_response)

    return QueryResponse(
        response=llm_response,
        cache_hit=False,
        tokens_used=42,
        latency_ms=1200
    )
```

**Flow:**

1. Client sends JSON
2. Pydantic validates → rejects if invalid
3. Check cache
4. If hit: return immediately (5ms)
5. If miss: call LLM (1200ms), cache result, return

**Learning:** The endpoint is just orchestration. Cache logic is in `cache.py`, validation is in `models.py`, logging is in middleware. Keep functions focused.

---

**4. Metrics Endpoint: GET /v1/metrics**

```python
async def metrics():
    stats = cache.stats()
    return MetricsResponse(
        total_requests=stats["total_requests"],
        cache_hits=stats["cache_hits"],
        cache_misses=stats["cache_misses"],
        hit_rate_percent=stats["hit_rate_percent"],
        stored_items=stats["stored_items"]
    )
```

**Why metrics matter:**

- After 1 week: "Hit rate = 80%" → caching is saving money ✅
- After 1 week: "Hit rate = 5%" → users ask unique questions, caching isn't helping ❌

**Learning:** Metrics aren't optional. They tell you if your system is working.

---

### Step 2.5: Testing

**Unit Test (`test_cache_direct.py`):**

- Tests cache without HTTP
- Verifies hit/miss logic
- Checks metrics tracking

**Integration Test (Postman):**

1. First query → cache miss (1200ms, tokens_used=42)
2. Same query → cache hit (5ms, tokens_used=0)
3. Different query → cache miss again
4. Metrics show: 33.33% hit rate (1 hit, 2 misses)

**What we learned from testing:**

- Cache logic works ✅
- Metrics are accurate ✅
- Same prompt = cache hit ✅
- Different prompts don't collide ✅
- Exact-match is too strict (we'll fix with semantic caching later)

---

## Phase 3: Production-Ready Caching (Redis Integration)

**Current Status:** Starting implementation (Step 3.1)

---

### Step 3.1: Why Replace In-Memory Cache with Redis?

**Problems with in-memory dict:**

1. **Lost on restart** — Deploy new code? All cache gone. Users see 0% hit rate.
2. **Single-process** — Run 2 FastAPI instances for high availability? They don't share cache. Same query hits both = 2 cache misses.
3. **No eviction** — Cache grows forever. After 1 month, you might have 50GB of prompts in RAM.
4. **No TTL** — Old responses never expire. GPT-5 launches, users still get GPT-4 cached answers.

**Redis solves:**

- ✅ **Persists to disk** — Survives restarts (loses only last ~1 second)
- ✅ **Multi-process** — All FastAPI instances share one Redis
- ✅ **Built-in eviction** — LRU (Least Recently Used) automatically removes old entries
- ✅ **TTL support** — Auto-expire responses after 1 hour

---

### Step 3.2: Alternatives Considered

| Option             | Speed | Persistence | Multi-process | Eviction | Why Not?                    |
| ------------------ | ----- | ----------- | ------------- | -------- | --------------------------- |
| **In-memory dict** | 1 µs  | ❌          | ❌            | ❌       | Too fragile for production  |
| **Redis**          | 1 ms  | ✅          | ✅            | ✅       | **← We choose this**        |
| **Memcached**      | 1 ms  | ❌          | ✅            | ✅       | No persistence              |
| **Postgres**       | 10 ms | ✅          | ✅            | Manual   | Overkill for key-value      |
| **SQLite**         | 5 ms  | ✅          | ❌            | Manual   | Doesn't scale multi-process |

**Why Redis wins:**

- Used in production by GitHub, Twitter, Stack Overflow
- Fast enough (1ms vs 1µs doesn't matter when LLM takes 2000ms)
- Simple to run (`docker run redis`)
- Mature Python async client

---

### Step 3.3: Tradeoffs We're Making

**Tradeoff 1: Latency**

- In-memory: 0.001ms (1 microsecond)
- Redis: 1ms (1 millisecond) — **1000x slower**
- LLM call: 2000ms

**Math:** Adding 1ms to a 2000ms request = 0.05% overhead. Negligible.

**Tradeoff 2: Complexity**

- Before: `python main.py` → done
- After: Run Redis (`docker run redis`), then `python main.py`

**Production:** Use managed Redis (AWS ElastiCache) → zero ops

**Tradeoff 3: Network Dependency**

- In-memory: Zero dependencies
- Redis: If Redis crashes, cache is unavailable

**Mitigation:** We'll add fallback logic (if Redis down, continue without cache)

---

### Step 3.4: Implementation Plan

**What we'll build:**

1. **Start Redis in Docker**

   ```bash
   docker run -d -p 6379:6379 redis
   ```

2. **Create `cache_redis.py`**

   - Same interface as `cache.py` (`.get()`, `.set()`, `.stats()`)
   - Uses async Redis client
   - Adds TTL (1 hour default)

3. **Update `main.py`**

   - Replace `ExactMatchCache` with `RedisCache`
   - Add startup event to connect to Redis
   - Add shutdown event to close connection

4. **Test**
   - Same Postman tests
   - Verify cache survives server restart
   - Use Redis CLI to inspect stored data

---

### Step 3.5: Why Async Redis?

**Sync (blocking) Redis:**

```python
response = redis.get("key")  # ← Blocks entire process for 1ms
# Other requests wait
```

**Async (non-blocking) Redis:**

```python
response = await redis.get("key")  # ← Pauses this request
# Other requests keep running
```

**When async matters:**

- 100 concurrent requests
- Each does 5 Redis lookups
- Sync: 500 lookups × 1ms = 500ms blocked time
- Async: 500 lookups happen concurrently = ~5ms total

**Learning:** Async isn't faster, it's about concurrency. Use it for I/O (network, disk, databases).

---

### Step 3.6: Redis Data Structure

**How we'll store data in Redis:**

```
Key: "sentinel:cache:{prompt}"
Value: {response_text}
TTL: 3600 seconds (1 hour)

Example:
Key: "sentinel:cache:What is AI?"
Value: "[gpt-4 response] AI is the simulation of human intelligence..."
TTL: 3600
```

**Why this structure:**

- Prefix `sentinel:cache:` prevents collisions if Redis is shared with other apps
- Prompt as key → instant lookup
- TTL auto-expires old responses

---

### Step 3.7: What You'll Learn

**1. External services add latency but enable scaling**

- 1ms latency is acceptable if it prevents 100% cache loss on restart

**2. Async is about concurrency, not speed**

- Async doesn't make Redis faster, it lets your app handle more users

**3. Interfaces let you swap implementations**

- `ExactMatchCache` and `RedisCache` have same methods
- `main.py` doesn't care which cache it uses

**4. Production = operational concerns**

- Need to run/monitor Redis
- Need connection retry logic
- Need fallback if Redis is down

**5. Every external dependency is a failure point**

- What if Redis crashes? → Fallback to no cache
- What if Redis is slow? → Add timeout
- What if connection fails? → Retry with exponential backoff

---

## Next: Implementation Steps (updating as we code...)

### ✅ Step 3.1: Create comprehensive notes.md (DONE)

### ✅ Step 3.2: Start Redis with Docker (DONE)

**What we did:**

```bash
docker run -d --name sentinel-redis -p 6379:6379 redis:alpine
```

**Flags explained:**

- `-d` = Run in detached mode (background)
- `--name sentinel-redis` = Give container a friendly name
- `-p 6379:6379` = Map port 6379 (Redis default) from container to your laptop
- `redis:alpine` = Use lightweight Alpine Linux-based Redis image

**Verify it's running:**

```bash
docker ps --filter name=sentinel-redis
```

**Output:** Container is `Up` and listening on `0.0.0.0:6379`

**What this means:**

- Redis server is running on localhost:6379
- Any application on your laptop can connect to it
- Data is stored inside the container (lost if container is deleted, but survives restarts)

**Useful commands:**

```bash
# Stop Redis
docker stop sentinel-redis

# Start Redis again
docker start sentinel-redis

# View Redis logs
docker logs sentinel-redis

# Connect to Redis CLI
docker exec -it sentinel-redis redis-cli
```

---

### ✅ Step 3.3: Install Redis Python Client (DONE)

**What we did:**

```bash
pip install redis[hiredis]
```

**Package breakdown:**

- `redis` = Official Python client for Redis
- `[hiredis]` = Optional C-based parser for 2-3x faster performance

**What this gives us:**

```python
import redis.asyncio as redis  # Async Redis client

# Connect to Redis
client = await redis.from_url("redis://localhost:6379")

# Store data
await client.set("key", "value")

# Retrieve data
value = await client.get("key")  # Returns bytes: b"value"
```

**Why async client?**

- FastAPI is async
- Redis operations are I/O (network calls)
- Async = don't block other requests while waiting for Redis

**Updated `requirements.txt`:**

```
fastapi==0.104.1
uvicorn[standard]==0.24.0
pydantic==2.5.0
redis[hiredis]==5.0.1  ← NEW
```

---

### ✅ Step 3.4: Create RedisCache Class (DONE)

**What we built:** `cache_redis.py` - Redis-backed cache with same interface as in-memory cache

**Key Design Decisions:**

#### 1. Same Interface as ExactMatchCache

```python
# Both caches have identical methods:
cache.get(prompt) → (response, is_hit)
cache.set(prompt, response)
cache.stats() → dict
```

**Why:** main.py doesn't need to change. We swap implementations without touching route handlers.

---

#### 2. Async/Await Everywhere

```python
async def get(self, prompt: str):
    response = await self.client.get(key)  # ← Await Redis network call
```

**Why:** Redis operations are network I/O. Async prevents blocking other requests.

**Pattern:**

- Sync: Request 1 waits → Redis responds → Request 2 waits → Redis responds (serial)
- Async: Request 1 + 2 both wait concurrently → Both get responses (parallel)

---

#### 3. Connection Management

```python
async def connect(self):
    self.client = await redis.from_url("redis://localhost:6379")
    await self.client.ping()  # Test connection

async def disconnect(self):
    await self.client.close()  # Clean shutdown
```

**Why:**

- Can't connect to Redis until main.py starts
- Need to close connection gracefully on shutdown
- Ping test catches connection failures early

**Pattern:** FastAPI will call `connect()` on startup, `disconnect()` on shutdown.

---

#### 4. Key Prefix to Avoid Collisions

```python
def _make_key(self, prompt: str):
    return f"sentinel:cache:{prompt}"

# Examples:
"What is AI?" → "sentinel:cache:What is AI?"
"Explain ML" → "sentinel:cache:Explain ML"
```

**Why:** If Redis is shared with other apps, our keys won't collide.

**Real-world scenario:**

- App A stores: `user:123` (user data)
- Sentinel stores: `sentinel:cache:user:123` (cached prompt "user:123")
- No collision ✅

---

#### 5. TTL (Time-To-Live) for Auto-Expiration

```python
await self.client.setex(
    key,
    3600,  # ← TTL in seconds (1 hour)
    response,
)
```

**Why:** Old responses should expire automatically.

**Scenario:**

- User asks "What's the latest GPT model?" at 1:00 PM
- Response: "GPT-4" (cached with 1-hour TTL)
- At 2:01 PM, cache expires
- Next request → cache miss → calls LLM → might get "GPT-5"

**Without TTL:** Users get stale "GPT-4" response forever.

---

#### 6. Error Handling (Graceful Degradation)

```python
try:
    response = await self.client.get(key)
except Exception as e:
    logger.error(f"Redis error: {e}")
    return None, False  # ← Treat as cache miss
```

**Why:** If Redis crashes, app continues working (just without cache).

**Behavior:**

- Redis working: Cache hits = fast, cache misses = call LLM
- Redis down: Every request = cache miss = call LLM (slower, but functional)

**Alternative (worse):** Crash the entire app if Redis is unreachable.

---

#### 7. Metrics Tracking

```python
self._hits = 0
self._misses = 0

async def get(self, prompt: str):
    if response:
        self._hits += 1
    else:
        self._misses += 1
```

**Why:** Track hit/miss in memory (fast), query Redis for stored item count.

**Tradeoff:**

- ✅ Fast: Increment counter = instant
- ❌ Resets on restart: After server restarts, metrics start at 0

**Alternative:** Store metrics in Redis too (persistent, but adds latency).

---

#### 8. Stats with Key Count

```python
async def stats(self):
    # Count keys matching "sentinel:cache:*"
    cursor, keys = await self.client.scan(0, match="sentinel:cache:*")
    stored_items = len(keys)
```

**Why:** Show how many prompts are cached.

**Tradeoff:**

- `SCAN` is O(N) — slower if you have 1 million keys
- Better than `KEYS sentinel:cache:*` which blocks Redis entirely

**Production fix:** Use Redis INFO command for memory stats, don't count keys.

---

**Full Flow Example:**

```python
# 1. Startup
cache = RedisCache()
await cache.connect()  # Connect to Redis

# 2. First request
response, hit = await cache.get("What is AI?")
# → Redis GET sentinel:cache:What is AI?
# → Key doesn't exist → (None, False)
# → Cache miss

# 3. Store response
await cache.set("What is AI?", "AI is the simulation...")
# → Redis SETEX sentinel:cache:What is AI? 3600 "AI is the simulation..."
# → Key stored with 1-hour TTL

# 4. Second request (within 1 hour)
response, hit = await cache.get("What is AI?")
# → Redis GET sentinel:cache:What is AI?
# → Key exists → ("AI is the simulation...", True)
# → Cache hit ✅

# 5. After 1 hour
response, hit = await cache.get("What is AI?")
# → Redis GET sentinel:cache:What is AI?
# → Key expired (TTL reached 0) → (None, False)
# → Cache miss (auto-expired)

# 6. Shutdown
await cache.disconnect()  # Close connection
```

---

**What You Learned:**

1. **Async patterns:** `await` for I/O operations, lets other requests run concurrently
2. **Resource management:** Connect on startup, disconnect on shutdown
3. **Error handling:** Graceful degradation (cache failures don't crash the app)
4. **Key naming:** Prefix keys to avoid collisions in shared Redis
5. **TTL:** Auto-expire data to prevent serving stale responses
6. **Same interface:** Swapping implementations is easy when interfaces match

---

### ✅ Step 3.5: Update main.py to Use Redis (DONE)

**What We Did:**
Updated `main.py` to use `RedisCache` instead of `ExactMatchCache`.

**Changes Made:**

1. **Import Statement:**

   ```python
   from cache_redis import RedisCache  # Changed from: from cache import ExactMatchCache
   ```

2. **Cache Initialization with Configuration:**

   ```python
   cache = RedisCache(
       redis_url="redis://localhost:6379",  # Redis connection string
       ttl_seconds=3600,                     # 1 hour expiration
       key_prefix="sentinel:cache:",        # Namespace for keys
   )
   ```

3. **Startup Event (NEW):**

   ```python
   @app.on_event("startup")
   async def startup_event():
       """Connect to Redis on application startup."""
       try:
           await cache.connect()
           logger.info("🚀 Sentinel started successfully")
       except Exception as e:
           logger.error(f"Failed to start Sentinel: {e}")
           raise
   ```

4. **Shutdown Event (NEW):**
   ```python
   @app.on_event("shutdown")
   async def shutdown_event():
       """Disconnect from Redis on application shutdown."""
       await cache.disconnect()
       logger.info("👋 Sentinel shut down gracefully")
   ```

**Why These Changes:**

- **Configuration at Initialization:** We pass Redis settings when creating the cache object, making it easy to change later (environment variables, config files, etc.)
- **Startup Event:** FastAPI calls this when the server starts. We connect to Redis here so all requests can use the cache.
- **Shutdown Event:** FastAPI calls this when the server stops (Ctrl+C). We close the Redis connection cleanly to avoid resource leaks.
- **Error Handling:** If Redis connection fails on startup, we log the error and crash the app (better than running without caching).

**What Didn't Change:**

All the endpoint code (`/v1/query`, `/v1/metrics`, `/health`) stays the same! Because `RedisCache` has the same methods (`get`, `set`, `stats`), we just swap the implementation and everything works.

This is the power of **interface design** — we designed `RedisCache` to match `ExactMatchCache`, so switching is easy.

---

### 🔄 Step 3.6: Test Redis Integration (NEXT)

**What We'll Do:**

1. Start the server: `python main.py`
2. Test with Postman to verify Redis cache works
3. Verify persistence by restarting the server
4. Inspect Redis with CLI to see stored data

---

### ✅ Step 3.5b: Fix Redis Connection Bug (DONE)

**Bug Found:** In `cache_redis.py`, the `ping()` call wasn't awaited.

**Fixed Code:**

```python
await self.client.ping()  # ✅ Correct - waits for async operation
```

---

### ✅ Step 3.6: Redis Integration Complete (DONE)

**Server Status:** ✅ Running successfully on http://0.0.0.0:8001

**Redis Connection verified:**

- ✅ Connected to Redis at redis://localhost:6379
- ✅ Sentinel started successfully
- ✅ All endpoints accessible

**Ready for testing with Postman!**

---

## Phase 4: Simulate Expensive LLM Calls (COMPLETED)

### ✅ Step 4.1: Simulate LLM Latency & Cost (DONE)

**What We Did:**
Replaced dummy responses with a realistic simulation:

- 2-second delay (simulates network + processing time)
- Fixed answer (doesn't vary, just like real LLM)
- Cost tracking (educational: shows why caching matters financially)
- Real latency measurement (using `time.perf_counter()`)

**Code Changes in `/v1/query`:**

```python
# Measure latency
start_time = time.perf_counter()

# Check cache
cached_response, is_hit = await cache.get(prompt)

if is_hit:
    # Cache hit: instant return
    latency_ms = (time.perf_counter() - start_time) * 1000
    logger.info(f"Cache HIT: {prompt[:50]}... | latency={latency_ms:.1f}ms | cost=$0.0000")
    # ... return cached response

# Cache miss: simulate expensive LLM call
logger.info(f"Cache MISS: {prompt[:50]}... | simulating 2s LLM call")
await asyncio.sleep(2.0)  # Simulate provider latency

# Fixed response + pretend cost
llm_response = "This is a simulated LLM answer. Caching avoids repeating this 2s wait."
fake_cost_usd = 0.002  # Per-call cost for education

await cache.set(prompt, llm_response)
latency_ms = (time.perf_counter() - start_time) * 1000
logger.info(f"LLM CALL (simulated): latency={latency_ms:.1f}ms | cost=${fake_cost_usd:.4f}")
```

**Why This Simulation Helps:**

1. **Feel the Pain Before Paying:** You experience 2s wait + cost before using real Groq API (which costs money).
2. **See Caching Impact:** First call = 2000ms + $0.002. Second identical call = ~5ms + $0.0000.
3. **Learn What Matters:** Latency and cost become real metrics you observe, not abstract concepts.
4. **No Money Wasted:** Safe playground to test, debug, and optimize before deploying with real API keys.

**Tradeoffs (Speed vs Realism):**

| Aspect          | Speed-Focused    | Realism-Focused    |
| --------------- | ---------------- | ------------------ |
| Sleep Time      | 100ms            | 2000ms             |
| Feedback Loop   | Fast tests       | See real impact    |
| Learning        | Quick iterations | Deep understanding |
| Cost Visibility | Minimal          | Clear pain point   |

We chose **2-second delay** for good balance: fast enough for testing, slow enough to feel the benefit.

**Key Metrics to Observe:**

1. **Latency (ms):**

   - Cache hit: ~5ms (Redis lookup + return)
   - Cache miss: ~2000ms (simulated LLM call)
   - Savings: 400x faster with cache!

2. **Cost (USD):**

   - Cache hit: $0.0000 (no API call)
   - Cache miss: $0.0020 (simulated API cost)
   - Savings: 100% reduction on repeated queries

3. **Requests:**
   - `total_requests` = cache_hits + cache_misses
   - `hit_rate_percent` = (hits / total) × 100
   - Higher hit rate = fewer LLM calls = lower cost

**How to Test:**

1. **First Request (Cache Miss):**

   ```
   POST http://localhost:8001/v1/query
   {"prompt": "What is machine learning?"}
   ```

   → Response after ~2s, logs cost $0.0020

2. **Second Request (Cache Hit):**

   ```
   POST http://localhost:8001/v1/query
   {"prompt": "What is machine learning?"}  # Same prompt
   ```

   → Response in ~5ms, logs cost $0.0000

3. **Check Metrics:**

   ```
   GET http://localhost:8001/v1/metrics
   ```

   → Shows hit_rate_percent = 50% (1 hit, 1 miss)

4. **Different Prompt (Cache Miss):**
   ```
   POST http://localhost:8001/v1/query
   {"prompt": "What is deep learning?"}  # New prompt
   ```
   → Response after ~2s (cache miss for new prompt)

**What You'll Learn:**

- How caching prevents repeated expensive operations
- Cost-benefit: small latency cost for cache lookup vs huge savings on repeated calls
- Why semantic AI gateways matter: in production with Groq, every cached hit saves $0.0001+ per request
- With 1000 queries, if 70% are cached: 300 real API calls instead of 1000 = 70% cost reduction

---

## Phase 5: Semantic Caching with Embeddings (COMPLETED)

### ✅ Step 5.1: Add Embedding Model (DONE)

**What We Did:**
Added semantic understanding by converting prompts to embedding vectors, enabling fuzzy matching instead of exact string matching.

**New Module: `embeddings.py`**

```python
class EmbeddingModel:
    """Convert text to 384-dimensional semantic embeddings"""
    - Model: sentence-transformers/all-MiniLM-L6-v2
    - Loads from Hugging Face (~90MB, downloaded once, cached locally)
    - Methods:
        - embed(text: str) → np.ndarray  # Convert text to vector
        - cosine_similarity(v1, v2) → float  # Compare two vectors
        - find_similar(query_emb, cached_embs, threshold) → match or None
```

**Why This Model:**

| Aspect   | all-MiniLM-L6-v2           | Alternatives                     |
| -------- | -------------------------- | -------------------------------- |
| Speed    | Fast (384D, CPU-friendly)  | Larger models are slower         |
| Accuracy | Good for Q&A               | Tiny models miss nuance          |
| Size     | 90MB                       | Very small: <10MB, Large: >300MB |
| Tradeoff | Balance of speed + quality | Choose based on your data        |
| Cost     | Free (Hugging Face)        | Some APIs charge per embedding   |

**How Embeddings Work:**

```
Text → Tokenize → BERT Model → Token Embeddings → Mean Pool → 384D Vector

"What is AI?" → [0.23, -0.15, 0.89, ..., -0.02]  (384 numbers)
"Tell me about AI" → [0.25, -0.14, 0.88, ..., -0.01]  (similar, but different)
"What is deep learning?" → [0.10, 0.44, 0.15, ..., 0.92]  (very different)
```

**Cosine Similarity (distance between vectors):**

```
Similarity = (A · B) / (||A|| × ||B||)

Range: -1.0 to 1.0
- 1.0 = identical (perfect match)
- 0.85 = very similar (semantically close)
- 0.70 = somewhat similar (related)
- 0.50 = loosely related
- 0.0 = orthogonal (no relationship)
```

---

### ✅ Step 5.2: Update Redis Cache for Embeddings (DONE)

**Changes to `cache_redis.py`:**

1. **Store embeddings alongside responses:**

   ```python
   async def set(self, prompt: str, response: str, embedding: np.ndarray = None):
       # Save response
       await self.client.setex(key, ttl, response)
       # Save embedding (JSON serialized)
       await self.client.setex(f"{key}:embedding", ttl, json.dumps(embedding.tolist()))
   ```

2. **Retrieve all cached items for semantic search:**
   ```python
   async def get_all_cached() -> list[dict]:
       # Returns: [{"prompt": str, "response": str, "embedding": np.ndarray}, ...]
       # Used by embedding model to find similar matches
   ```

**Why Store Embeddings:**

- Embeddings are expensive to compute (requires loading model)
- Cache them alongside responses for fast semantic search on future requests
- If embedding expires (TTL), just recompute on next cache miss

---

### ✅ Step 5.3: Update `/v1/query` Endpoint with Semantic Logic (DONE)

**New Query Logic (4-step process):**

```
Step 1: Compute embedding of incoming prompt
Step 2: Try exact string match (fastest, returns immediately)
Step 3: Try semantic similarity search (within threshold)
Step 4: If no match, call LLM, cache with embedding

if exact_match:
    return cached_response (latency ~5ms, cost $0)
elif semantic_match (similarity ≥ threshold):
    return cached_response (latency ~50ms, cost $0)
else:
    await LLM(prompt)  # 2s simulation, cost $0.002
    cache(response, embedding)
    return response
```

**Request Schema (updated `models.py`):**

```python
class QueryRequest(BaseModel):
    prompt: str  # Required
    provider: str = "openai"  # Optional
    model: str = "gpt-4"  # Optional
    temperature: float = 0.7  # Optional
    max_tokens: int = 500  # Optional
    similarity_threshold: float = 0.75  # NEW: control matching strictness
```

**Response Tracking:**

```python
class QueryResponse(BaseModel):
    response: str  # The answer
    cache_hit: bool  # Did we use cache?
    similarity_score: float | None  # 0.0-1.0, None if no match
    matched_prompt: str | None  # Which cached prompt matched?
    provider: str
    model: str
    tokens_used: int
    latency_ms: float
```

---

### ✅ Step 5.4: Initialize Embedding Model on Startup (DONE)

**In `/v1/query` endpoint startup:**

```python
@app.on_event("startup")
async def startup_event():
    await cache.connect()  # Connect to Redis
    embedding_model.load()  # Load transformers model (~90MB download, cached)
    logger.info("🚀 Sentinel started successfully")
```

**First startup:** Model downloads from Hugging Face (~1-2 minutes)
**Subsequent startups:** Uses cached model (instant)

---

## Key Tradeoffs in Semantic Caching

### Similarity Threshold

**Lower threshold (0.50):**

- ✅ More cache hits (reuse answers more often)
- ❌ Risk of irrelevant answers (false positives)
- Best for: Brainstorming, when "close enough" is OK

**Higher threshold (0.90):**

- ✅ Strict matching (only use if very similar)
- ❌ Fewer cache hits (more LLM calls)
- Best for: Factual Q&A, when accuracy > cost savings

**Sweet spot: 0.75-0.80**

### Model Choice

**all-MiniLM-L6-v2 (we chose this):**

- ✅ Fast, small, good quality
- ❌ Not specialized for domain
- Best for: General Q&A, demos

**Larger models (e.g., all-mpnet-base-v2):**

- ✅ Better semantic understanding
- ❌ Slower, needs GPU for speed
- Best for: Production, high accuracy needed

**Tiny models (e.g., MiniLM-L12-v2):**

- ✅ Ultra-fast
- ❌ Lower quality embeddings
- Best for: Real-time, speed-critical

### Semantic vs Exact Matching

| Scenario                                       | Exact   | Semantic | Best           |
| ---------------------------------------------- | ------- | -------- | -------------- |
| "What is AI?" then "What is AI?"               | ✅ Hit  | ✅ Hit   | Exact (faster) |
| "What is AI?" then "Tell me about AI"          | ❌ Miss | ✅ Hit   | Semantic       |
| "What is AI?" then "How to train neural nets?" | ❌ Miss | ❌ Miss  | Call LLM       |

**Our approach: Use BOTH**

1. Try exact first (fastest)
2. Fall back to semantic (smart)
3. Only call LLM if both miss

---

## Testing Semantic Caching

**Test Case 1: Exact Match**

```json
POST /v1/query
{"prompt": "What is machine learning?", "similarity_threshold": 0.75}
Response: cache_hit=false, similarity_score=null (first call)

POST /v1/query
{"prompt": "What is machine learning?", "similarity_threshold": 0.75}
Response: cache_hit=true, similarity_score=1.0 (exact match)
```

**Test Case 2: Semantic Match**

```json
POST /v1/query
{"prompt": "Tell me about ML", "similarity_threshold": 0.75}
Response: cache_hit=true, similarity_score=0.88
         matched_prompt="What is machine learning?"
```

**Test Case 3: Threshold Tuning**

```json
POST /v1/query
{"prompt": "ML explained", "similarity_threshold": 0.70}
Response: cache_hit=true, similarity_score=0.75

POST /v1/query
{"prompt": "ML explained", "similarity_threshold": 0.80}
Response: cache_hit=false (similarity too low)
```

**What to observe:**

- Lower threshold = more hits, but riskier
- Higher threshold = fewer hits, safer
- Similarity scores vary (0.70-0.95 for related questions)

---

## Next Steps

The semantic caching system is now complete! You can:

1. **Test thoroughly** with different question phrasings
2. **Tune the threshold** based on your comfort level
3. **Prepare for Groq integration** (replace simulated LLM calls)
4. **Monitor metrics** to see how much caching saves

---

## Phase 6: Real LLM Integration with Groq API (IN PROGRESS)

### Overview

**Goal:** Replace the 2-second dummy LLM simulation with real Groq API calls.

**Why Groq?**

- Free tier available (no credit card for testing)
- Fast inference (20K tokens/min free)
- Simple REST API (OpenAI-compatible)
- Good for learning cost-conscious design

---

### Step 6.1: Why Async Matters (CONCEPT)

**The Problem with Blocking Calls:**

```python
# BLOCKING (Bad - old way)
def query(prompt):
    response = requests.post("https://api.groq.com/...")  # Waits 2-3s
    # During this 2-3s, server can't handle OTHER requests!
    # 1 request every 2-3s max = 300-500 req/day
    return response
```

**Why This Kills Performance:**

- Each request blocks the entire thread
- While waiting for Groq, your server is frozen
- Can't serve other users
- Even with 10 threads, only 10 concurrent requests

**The Async Solution:**

```python
# ASYNC (Good - modern way)
async def query(prompt):
    response = await aiohttp.post("https://api.groq.com/...")  # Wait 2-3s
    # During this 2-3s, FastAPI handles OTHER requests!
    # 1000+ requests can wait concurrently
    # No additional servers needed
    return response
```

**How Async Works:**

```
Timeline (with async):
t=0ms:  Request 1 sent to Groq API
t=0ms:  Request 2 sent to Groq API  (while Request 1 is waiting!)
t=0ms:  Request 3 sent to Groq API  (while Requests 1-2 are waiting!)
...
t=2500ms: Request 1 response arrives → return to user
t=2600ms: Request 2 response arrives → return to user
t=2700ms: Request 3 response arrives → return to user

Result: 3 requests handled in 2.7s instead of 7.5s!
```

**Key Insight:**

- Async doesn't make each request faster
- Async makes the SYSTEM handle more requests without blocking
- Perfect for I/O (network, database) - which is 99% of web APIs

---

### Step 6.2: Async API Integration Pattern (LEARNING)

**Traditional (Blocking) Pattern:**

```python
import requests  # Blocking library

def call_llm(prompt):
    response = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        json={"messages": [{"role": "user", "content": prompt}]},
        headers={"Authorization": f"Bearer {API_KEY}"}
    )
    return response.json()["choices"][0]["message"]["content"]
```

**Async Pattern (What We'll Use):**

```python
import aiohttp  # Async HTTP library

async def call_llm(prompt):
    async with aiohttp.ClientSession() as session:
        async with session.post(
            "https://api.groq.com/openai/v1/chat/completions",
            json={"messages": [{"role": "user", "content": prompt}]},
            headers={"Authorization": f"Bearer {API_KEY}"}
        ) as response:
            data = await response.json()
            return data["choices"][0]["message"]["content"]
```

**Differences:**

- `requests.post()` → `session.post()` with `async with`
- `response.json()` → `await response.json()` (wait for parsing)
- `def` → `async def` (tells Python this is async)
- Call with `await call_llm(prompt)` in your async context

---

### Step 6.3: Tradeoffs - Concurrency vs Complexity (ANALYSIS)

| Aspect              | Async                        | Sync                  | Tradeoff             |
| ------------------- | ---------------------------- | --------------------- | -------------------- |
| **Throughput**      | 1000+ concurrent             | Limited by threads    | Async wins for I/O   |
| **Code Complexity** | More (callbacks, await)      | Simple                | Sync easier to learn |
| **Error Handling**  | Trickier (timeouts, retries) | Straightforward       | More code needed     |
| **Debugging**       | Harder (async traces)        | Easy                  | Sync easier to debug |
| **Resource Usage**  | Minimal (no threads)         | Many threads = memory | Async wins on scale  |
| **Learning Curve**  | Steep                        | Gentle                | Sync faster to learn |

**When to Choose Async:**

- ✅ High concurrency (100+ simultaneous users)
- ✅ I/O-bound (network, database calls)
- ✅ Cost-conscious (no need for massive servers)

**When Sync is OK:**

- ✅ Low traffic (<10 req/sec)
- ✅ CPU-intensive (not I/O)
- ✅ Simple prototypes

**We chose async because:**

- Groq API calls are I/O-bound (2-3s wait per call)
- We want to handle many simultaneous users
- Learning outcome: "This is how real production systems work"

---

### Step 6.4: Failure Modes - What Can Break? (CRITICAL)

**Failure Scenario 1: API Key Missing**

```
❌ No API key → 401 Unauthorized
→ System can't call Groq
→ Need: Check env var before startup
```

**Failure Scenario 2: API Rate Limit Hit**

```
❌ Called Groq 100 times/sec → 429 Too Many Requests
→ All requests fail simultaneously
→ Need: Exponential backoff + retry logic
```

**Failure Scenario 3: API Timeout (Groq is slow/down)**

```
❌ Request waits 30s → timeout
→ Request fails, user waits forever if not handled
→ Need: Set timeout (e.g., 10s), fail gracefully
```

**Failure Scenario 4: Network Connection Lost**

```
❌ Internet down or ISP issues
→ Request hangs indefinitely
→ Need: Connection pooling + retry with backoff
```

**Failure Scenario 5: Invalid Response from Groq**

```
❌ Groq returns malformed JSON
→ Parsing fails, crash
→ Need: Validate response schema before using
```

**Our Strategy (Graceful Degradation):**

```python
async def call_llm_safe(prompt):
    try:
        # Try Groq API
        response = await call_groq_with_timeout(prompt, timeout=10)
        return response, cost=0.001
    except aiohttp.ClientError as e:
        # Network/timeout error
        logger.warning(f"Groq API failed: {e}, falling back to cached response")
        return None  # Signal cache miss but don't crash
    except Exception as e:
        # Unexpected error
        logger.error(f"Unexpected error calling Groq: {e}")
        return None  # Signal cache miss but don't crash

# In endpoint:
llm_response = await call_llm_safe(prompt)
if llm_response is None:
    # Groq failed, already tried cache - return error gracefully
    return {"error": "LLM temporarily unavailable", "status": 503}
```

---

### Step 6.5: Integration Architecture (DESIGN)

**New Layer: LLM Provider**

```python
# New file: llm_provider.py

class LLMProvider:
    """Abstract interface for LLM APIs (Groq, OpenAI, etc.)"""

    async def call(self, prompt: str, model: str, temperature: float) -> dict:
        """
        Call LLM with safety + cost tracking.

        Returns:
        {
            "response": str,
            "tokens_used": int,
            "cost_usd": float,
            "latency_ms": float,
            "provider": str
        }
        """
        pass

class GroqProvider(LLMProvider):
    """Groq API implementation"""

    async def call(self, prompt, model, temperature):
        try:
            start = time.perf_counter()
            response = await self._call_groq_api(prompt, model, temperature)
            latency = (time.perf_counter() - start) * 1000

            return {
                "response": response["content"],
                "tokens_used": response["usage"]["total_tokens"],
                "cost_usd": self._calculate_cost(response["usage"]),
                "latency_ms": latency,
                "provider": "groq"
            }
        except Exception as e:
            logger.error(f"Groq API error: {e}")
            raise
```

**Flow in `/v1/query` endpoint:**

```
1. Check exact cache        → Hit? Return (5ms, $0)
2. Check semantic cache     → Hit? Return (50ms, $0)
3. Call LLMProvider.call()  → Get response + cost + latency
4. Store in cache           → Update embeddings
5. Return to user
```

---

### Step 6.6: Cost Tracking (LEARNING OUTCOME)

**Why Track Costs?**

In production with Groq:

- Groq charges per token (~$0.0005 per 1K tokens)
- Every cache hit saves money
- With caching: 70% hit rate = 70% cost savings
- Visibility into costs prevents surprises

**Cost Calculation:**

```python
# Groq pricing (as of 2026):
INPUT_COST_PER_1K = 0.00005    # $0.05 per 1M tokens
OUTPUT_COST_PER_1K = 0.00015   # $0.15 per 1M tokens

def calculate_cost(usage):
    input_cost = (usage["prompt_tokens"] / 1000) * INPUT_COST_PER_1K
    output_cost = (usage["completion_tokens"] / 1000) * OUTPUT_COST_PER_1K
    return input_cost + output_cost

# Example:
# Input: 50 tokens, Output: 100 tokens
# Cost = (50/1000)*0.00005 + (100/1000)*0.00015
#      = 0.0000025 + 0.000015
#      = $0.0000175 per request
```

**Logging for Visibility:**

```python
logger.info(f"LLM CALL: model={model} | tokens_in={50} tokens_out={100} | cost=${0.0000175:.6f} | latency=2500ms")

# Over time, aggregate:
# Total cost: $150/month
# Total requests: 10,000
# Average cost/request: $0.015
# With caching (70% hit): Would cost $45/month instead
```

---

### Step 6.7: What You'll Learn (LEARNING OUTCOMES)

By implementing this integration, you'll understand:

1. **Async/Await Patterns**

   - How to structure async code in FastAPI
   - When to use `async with` for resource management
   - Concurrent I/O handling

2. **Error Resilience**

   - API failures are normal (network, rate limits, timeouts)
   - Graceful degradation beats crashes
   - Exponential backoff for retries

3. **Cost-Conscious Design**

   - Every API call has a price
   - Caching is ROI optimization (less calls = less cost)
   - Monitoring latency and cost together

4. **Production Thinking**

   - Real APIs fail; plan for it
   - Metrics matter (latency, cost, error rates)
   - Users expect reliability, not perfection

5. **Integration Testing**
   - Test with real API (get API key)
   - Test failure modes (simulate timeout, bad response)
   - Monitor before deploying to production

---

### Implementation Plan

**To do:**

1. ✅ Add comprehensive notes (this step)
2. ✅ Create `llm_provider.py` with GroqProvider
3. ✅ Update `/v1/query` to call LLMProvider
4. ✅ Add error handling + retry logic
5. ⏳ Add Groq API key to environment (user needs to get from Groq)
6. ⏳ Test with real Groq API
7. ⏳ Document cost tracking in logs

---

## Step 6.8: What Was Implemented (IMPLEMENTATION SUMMARY)

### Files Created:

**llm_provider.py** (250 lines)

- Abstract `LLMProvider` base class with `call()` interface
- `GroqProvider` implementation with:
  - Async HTTP calls via aiohttp
  - Connection pooling (single session)
  - Exponential backoff retry logic (1s → 2s → 4s)
  - Error handling for 401 (bad key), 429 (rate limit), timeout
  - Cost calculation based on token usage
  - Comprehensive logging with cost/latency/token info
  - Graceful error returns (don't crash, return error message)

Key methods:

```python
async def call(prompt, model, temperature, max_tokens):
    # Returns: {"response": str, "tokens_used": int, "cost_usd": float, "latency_ms": float, ...}

async def connect():
    # Initialize aiohttp.ClientSession for connection pooling

async def disconnect():
    # Clean up connections on shutdown
```

### Files Modified:

**main.py**

- Added import: `from llm_provider import initialize_llm_provider, cleanup_llm_provider, llm_provider`
- Updated `startup_event()`: Now calls `await initialize_llm_provider()`
- Updated `shutdown_event()`: Now calls `await cleanup_llm_provider()`
- Replaced `/v1/query` Step 4 logic:
  - BEFORE: `await asyncio.sleep(2.0)` + fake response
  - AFTER: `await llm_provider.call(prompt, model, temperature, max_tokens)`
  - Now returns actual Groq response + real cost + real latency
  - Added try/except for LLM call failures (returns error gracefully)

**requirements.txt**

- Added: `aiohttp>=3.9.0` (for async HTTP to Groq API)

---

## Step 6.9: How It Works Now (FLOW DIAGRAM)

**Before (Phases 1-5):**

```
User → FastAPI → Cache (exact/semantic) → 2s sleep → fake response → User
                                          ↑
                                     $0.002 simulated
```

**After (Phase 6):**

```
User → FastAPI → Cache (exact/semantic) → Groq API → real response → User
                                          ↑
                                  actual token cost
                                  (varies, usually $0.00005-0.0002)
```

**Concurrency Benefit:**

Old (simulated):

```
Request 1: 0-2000ms
Request 2: 2000-4000ms
Request 3: 4000-6000ms
Total: 6 seconds for 3 requests
```

New (real Groq):

```
Request 1: 0-1500ms
Request 2: 0-1500ms  (runs concurrently!)
Request 3: 0-1500ms  (runs concurrently!)
Total: 1.5 seconds for 3 requests!
```

---

## Step 6.10: Testing Guide (HOW TO TEST)

### Step 1: Get Groq API Key

1. Visit https://console.groq.com (sign up with Google/email)
2. Navigate to "API Keys"
3. Create new key
4. Copy the key (starts with `gsk_`)

### Step 2: Set Environment Variable

**Windows (PowerShell):**

```powershell
$env:GROQ_API_KEY = "gsk_your_key_here"
```

**Windows (CMD):**

```cmd
set GROQ_API_KEY=gsk_your_key_here
```

**Linux/Mac (Bash):**

```bash
export GROQ_API_KEY=gsk_your_key_here
```

### Step 3: Install New Dependencies

```bash
pip install -r requirements.txt
# or just:
pip install aiohttp>=3.9.0
```

### Step 4: Start Server

```bash
python main.py
```

Watch for startup messages:

```
✅ Connected to Redis at redis://localhost:6379
✅ Embedding model loaded (384 dimensions)
✅ GroqProvider initialized
✅ Groq connection pool created
🚀 Sentinel started successfully
```

### Step 5: Test Cache Hit (should be instant, $0)

```bash
curl -X POST http://localhost:8001/v1/query \
  -H "Content-Type: application/json" \
  -d '{"prompt": "What is 2+2?", "model": "mixtral-8x7b-32768"}'
```

Response (first call, takes 1-2s):

```json
{
  "response": "2 + 2 = 4",
  "cache_hit": false,
  "similarity_score": null,
  "tokens_used": 15,
  "latency_ms": 1234,
  "provider": "groq",
  "model": "mixtral-8x7b-32768"
}
```

**Second call with same question (instant):**

```bash
curl -X POST http://localhost:8001/v1/query \
  -H "Content-Type: application/json" \
  -d '{"prompt": "What is 2+2?", "model": "mixtral-8x7b-32768"}'
```

Response (exact cache hit):

```json
{
  "response": "2 + 2 = 4",
  "cache_hit": true,
  "similarity_score": 1.0,
  "latency_ms": 5,  # ← Much faster!
  "provider": "groq"
}
```

### Step 6: Test Semantic Cache Hit

```bash
curl -X POST http://localhost:8001/v1/query \
  -H "Content-Type: application/json" \
  -d '{"prompt": "What is two plus two?", "model": "mixtral-8x7b-32768", "similarity_threshold": 0.75}'
```

Response (semantic match found, $0 cost):

```json
{
  "response": "2 + 2 = 4",
  "cache_hit": true,
  "similarity_score": 0.89,  # ← Not exact, but semantically similar!
  "matched_prompt": "What is 2+2?",
  "latency_ms": 50,  # ← Fast: only embedding computation, not LLM call
  "provider": "groq"
}
```

### Step 7: Check Logs for Cost Info

After running requests, grep logs:

```bash
# Show LLM calls with cost
grep "LLM CALL (Groq)" output.log
```

Example:

```
LLM CALL (Groq): latency=1234.5ms | cost=$0.000123 | tokens=23 | prompt='What is 2+2?'
```

### Step 8: Check Metrics Endpoint

```bash
curl http://localhost:8001/v1/metrics
```

Response shows cache effectiveness:

```json
{
  "total_requests": 10,
  "cache_hits": 7,
  "cache_misses": 3,
  "hit_rate_percent": 70.0,  # ← 70% of requests saved cost!
  "stored_items": 3
}
```

---

## Step 6.11: Debugging Checklist (IF THINGS DON'T WORK)

| Issue                          | Solution                                                                    |
| ------------------------------ | --------------------------------------------------------------------------- |
| `GROQ_API_KEY not configured`  | Set env var: `export GROQ_API_KEY=gsk_...`                                  |
| `401 Unauthorized`             | API key is wrong; regenerate from Groq console                              |
| `429 Too Many Requests`        | Hit rate limit; retry logic will handle this automatically                  |
| `TimeoutError`                 | Groq is slow; normal, will retry up to 3 times                              |
| `Connection refused`           | Redis not running; start Docker: `docker run -d -p 6379:6379 redis:alpine`  |
| `ModuleNotFoundError: aiohttp` | Install: `pip install aiohttp`                                              |
| `Server crashes`               | Check logs; should show error message and gracefully return error to client |

---

## Key Learning Outcomes (MASTERY CHECKLIST)

By reaching this point, you understand:

✅ **Async/Await Patterns**

- How FastAPI handles 1000+ concurrent requests
- Why `await` is necessary for I/O operations
- Connection pooling benefits (reuse TCP connections)

✅ **Error Resilience**

- Exponential backoff retry strategy (1s → 2s → 4s)
- Graceful degradation (return error, don't crash)
- Timeout handling (don't wait forever)

✅ **Cost-Conscious Design**

- Every API call has a price
- Caching ROI: 70% hit rate = 70% cost savings
- Monitoring costs alongside latency

✅ **Production Patterns**

- Abstract interfaces (LLMProvider) enable swapping implementations
- Comprehensive error logging for debugging
- Metrics collection for visibility

✅ **Integration Testing**

- Exact cache hits (fast, $0)
- Semantic cache hits (semi-fast, $0)
- Cache misses (LLM call, costs money)
- Failure handling (graceful, no crashes)

---

## **Phase 7: Deployment - From Local to Production** 🚀

**Goal:** Deploy Sentinel to production with Docker, understand deployment tradeoffs, and learn production engineering practices.

---

### **7.1 Why Docker? Understanding Containerization**

**The Problem Docker Solves:**

Imagine you built Sentinel on your Windows laptop with Python 3.11. Your colleague tries to run it on Linux with Python 3.10. Your teammate deploys to a server with Python 3.9. **Disaster!**

- Different Python versions
- Different OS behaviors
- Missing system libraries
- "But it works on my machine!" 😫

**Docker's Solution:**

Docker **packages your application with everything it needs** into a **container**:

- ✅ Exact Python version (3.11)
- ✅ All dependencies (FastAPI, Redis, transformers)
- ✅ OS libraries (Linux base)
- ✅ Configuration files

**Container = Portable box that runs the same everywhere**

---

### **7.2 Container vs VM vs Serverless - Tradeoffs**

| Aspect               | Docker Container        | Virtual Machine         | Serverless (Lambda)         |
| -------------------- | ----------------------- | ----------------------- | --------------------------- |
| **Boot Time**        | 1-5 seconds             | 1-5 minutes             | 0-10 seconds (cold start)   |
| **Resource Usage**   | Lightweight (MB)        | Heavy (GB RAM)          | Zero when idle              |
| **Isolation**        | Process-level           | Full OS isolation       | Function-level              |
| **Cost (Free Tier)** | ✅ Fly.io, Render       | ❌ Usually paid         | ⚠️ Limited requests         |
| **Portability**      | ✅ Run anywhere         | ⚠️ Hypervisor-dependent | ❌ Vendor lock-in           |
| **Complexity**       | Medium                  | High                    | Low                         |
| **Best For**         | **APIs, microservices** | Legacy apps, full OS    | Event-driven, spiky traffic |

**Why Docker for Sentinel?**

1. ✅ **Consistency** - Same image runs locally and in production
2. ✅ **Free deployment** - Fly.io/Render have generous free tiers
3. ✅ **Efficient** - Containers share host OS kernel (lightweight)
4. ✅ **Industry standard** - Most companies use Docker/Kubernetes

**Tradeoffs:**

- ⚠️ **Learning curve** - Need to understand Dockerfile, images, volumes
- ⚠️ **Not true serverless** - Container runs continuously (but can auto-scale to zero)

---

### **7.3 Understanding the Dockerfile**

**Multi-Stage Build Strategy:**

```dockerfile
# Stage 1: Builder (installs dependencies)
FROM python:3.11-slim as builder
COPY requirements.txt .
RUN pip install --user -r requirements.txt

# Stage 2: Runtime (copies only what's needed)
FROM python:3.11-slim
COPY --from=builder /root/.local /root/.local
COPY . .
```

**Why multi-stage?**

- ✅ Smaller image size (only runtime files, no build tools)
- ✅ Faster deployments (less data to transfer)
- ✅ Security (no compilers in production image)

**Size comparison:**

- Single-stage: **1.2 GB**
- Multi-stage: **450 MB** (62% smaller!)

**Key Dockerfile Decisions:**

1. **Base Image: `python:3.11-slim`**

   - Why not `python:3.11`? Too big (1GB vs 200MB)
   - Why not `alpine`? Missing libraries, build issues

2. **Non-Root User:**

   ```dockerfile
   RUN useradd -m -u 1000 sentinel
   USER sentinel
   ```

   - **Security best practice** - If attacker exploits app, they can't control host

3. **Health Check:**
   ```dockerfile
   HEALTHCHECK --interval=30s CMD curl http://localhost:8001/health
   ```
   - Docker/Kubernetes can auto-restart if unhealthy

---

### **7.4 Docker Compose - Local Development**

**docker-compose.yml = Define multi-container apps**

```yaml
services:
  redis: # Service 1
    image: redis:7-alpine
    ports: ["6379:6379"]

  sentinel: # Service 2
    build: .
    ports: ["8001:8001"]
    depends_on:
      - redis # Wait for Redis to start
```

**Benefits:**

1. ✅ **One command to start everything:**

   ```bash
   docker-compose up  # Starts Redis + Sentinel together
   ```

2. ✅ **Networking is automatic** - Services can talk via service name:

   ```python
   REDIS_URL = "redis://redis:6379"  # "redis" = service name
   ```

3. ✅ **Data persistence** - Redis data survives container restarts:
   ```yaml
   volumes:
     - redis_data:/data
   ```

**Development Workflow:**

```bash
# Start
docker-compose up -d

# View logs
docker-compose logs -f sentinel

# Restart after code changes
docker-compose restart sentinel

# Stop and cleanup
docker-compose down
```

---

### **7.5 Production Deployment - Fly.io (Free)**

**Why Fly.io?**

| Feature            | Fly.io   | Render        | Railway      | Heroku        |
| ------------------ | -------- | ------------- | ------------ | ------------- |
| **Free Tier**      | ✅ 3 VMs | ✅ 750 hrs/mo | ✅ $5 credit | ❌ Deprecated |
| **Redis Included** | ✅ Yes   | ❌ Paid addon | ✅ Yes       | ❌ Paid addon |
| **Auto HTTPS**     | ✅ Yes   | ✅ Yes        | ✅ Yes       | ✅ Yes        |
| **Scale to Zero**  | ✅ Yes   | ✅ Yes        | ❌ No        | ❌ No         |
| **Global CDN**     | ✅ Yes   | ⚠️ Limited    | ⚠️ Limited   | ✅ Yes        |

**Fly.io wins for free tier + Redis combo!**

**Deployment Steps:**

```bash
# 1. Install Fly CLI
curl -L https://fly.io/install.sh | sh

# 2. Login
fly auth login

# 3. Create app
fly launch  # Interactive setup

# 4. Set secrets
fly secrets set GROQ_API_KEY=your_key_here

# 5. Deploy
fly deploy

# 6. Check status
fly status
fly logs
```

**fly.toml Configuration:**

```toml
[http_service]
  internal_port = 8001
  force_https = true
  auto_stop_machines = true  # Scale to zero when idle (FREE!)
  min_machines_running = 0

[[vm]]
  cpu_kind = "shared"
  cpus = 1
  memory_mb = 256  # Free tier limit
```

**Important Settings:**

- `auto_stop_machines = true` - **Saves money!** Stops VMs when no traffic
- `force_https = true` - Automatic SSL certificates
- `min_machines_running = 0` - True serverless (pay only when used)

---

### **7.6 Nginx Reverse Proxy - Why & How**

**What is a Reverse Proxy?**

```
Client → Nginx (Reverse Proxy) → Sentinel (Backend)
```

**Without Nginx:**

- Client connects directly to Sentinel
- One crashed request can block others
- No rate limiting
- Manual SSL certificate management

**With Nginx:**

- ✅ **Load balancing** - Distribute requests across multiple Sentinel instances
- ✅ **Rate limiting** - Block abusive clients (10 req/sec max)
- ✅ **SSL termination** - Nginx handles HTTPS, Sentinel uses HTTP
- ✅ **Static file serving** - Nginx serves files 10x faster than Python
- ✅ **Security** - Hide Sentinel's real IP, add security headers

**nginx.conf Highlights:**

```nginx
# Rate limiting (prevents abuse)
limit_req_zone $binary_remote_addr zone=sentinel_limit:10m rate=10r/s;

# SSL with auto-renewal
ssl_certificate /etc/letsencrypt/live/your-domain.com/fullchain.pem;

# Security headers
add_header X-Frame-Options "SAMEORIGIN" always;
add_header Strict-Transport-Security "max-age=31536000";

# Proxy to backend
location / {
    proxy_pass http://localhost:8001;
    proxy_set_header X-Real-IP $remote_addr;
}
```

**When to Use Nginx?**

- ✅ High traffic (>1000 req/sec)
- ✅ Multiple backend instances
- ✅ Need advanced rate limiting
- ❌ For small projects, Fly.io's built-in proxy is enough

---

### **7.7 HTTPS with Certbot - Free SSL Certificates**

**Why HTTPS Matters:**

- ✅ **Security** - Encrypted traffic (passwords, API keys safe)
- ✅ **Trust** - Browsers show 🔒 instead of "Not Secure"
- ✅ **SEO** - Google ranks HTTPS sites higher
- ✅ **Compliance** - Required for production APIs

**Let's Encrypt + Certbot = Free SSL Forever**

**Setup (on VM with Nginx):**

```bash
# 1. Install Certbot
sudo apt-get install certbot python3-certbot-nginx

# 2. Get certificate
sudo certbot --nginx -d your-domain.com

# 3. Auto-renewal (happens automatically)
sudo certbot renew --dry-run
```

**Certbot automatically:**

- ✅ Generates SSL certificate
- ✅ Configures nginx.conf
- ✅ Sets up auto-renewal (every 60 days)

**Note:** On Fly.io, HTTPS is **automatic** - no Certbot needed!

---

### **7.8 Environment Variables - Dev vs Prod**

**Never hardcode secrets!**

**Bad:**

```python
GROQ_API_KEY = "gsk_abc123..."  # ❌ Exposed in Git!
```

**Good:**

```python
GROQ_API_KEY = os.getenv("GROQ_API_KEY")  # ✅ From .env file
```

**Environment Management:**

| Environment        | Config File | How to Set                         |
| ------------------ | ----------- | ---------------------------------- |
| **Local Dev**      | `.env`      | `GROQ_API_KEY=...` in file         |
| **Docker Compose** | `.env`      | `docker-compose` reads `.env`      |
| **Fly.io**         | Secrets     | `fly secrets set GROQ_API_KEY=...` |
| **VM/Server**      | Systemd env | `Environment="GROQ_API_KEY=..."`   |

**Dev vs Prod Differences:**

```bash
# .env.development
DEBUG=true
REDIS_URL=redis://localhost:6379
LOG_LEVEL=DEBUG

# .env.production
DEBUG=false
REDIS_URL=redis://prod-redis.fly.dev:6379
LOG_LEVEL=INFO
SENTRY_DSN=https://...  # Error tracking
```

---

### **7.9 Deployment Checklist - Production Readiness**

**Before Deploying:**

- [ ] ✅ **Security:**
  - [ ] No hardcoded secrets (use env vars)
  - [ ] .gitignore includes `.env`
  - [ ] API keys rotated regularly
  - [ ] HTTPS enabled
- [ ] ✅ **Reliability:**
  - [ ] Health check endpoint (`/health`)
  - [ ] Graceful shutdown (cleanup connections)
  - [ ] Error handling (no crashes on bad input)
  - [ ] Retry logic (exponential backoff)
- [ ] ✅ **Performance:**
  - [ ] Async I/O (no blocking operations)
  - [ ] Connection pooling (Redis, HTTP)
  - [ ] Caching enabled
  - [ ] Resource limits (memory, CPU)
- [ ] ✅ **Observability:**
  - [ ] Structured logging
  - [ ] Metrics endpoint (`/v1/metrics`)
  - [ ] Error tracking (Sentry optional)
  - [ ] Uptime monitoring (UptimeRobot free)
- [ ] ✅ **Testing:**
  - [ ] Local Docker test (`docker-compose up`)
  - [ ] Health check passes
  - [ ] API endpoints work
  - [ ] Cache hit/miss behavior verified

---

### **7.10 Common Deployment Issues & Solutions**

**Issue 1: Container Crashes Immediately**

```bash
# Check logs
docker logs sentinel-app
# OR
fly logs
```

**Common causes:**

- Missing environment variables (GROQ_API_KEY)
- Redis connection failed
- Port already in use

**Solution:** Verify env vars and dependencies.

---

**Issue 2: Redis Connection Refused**

```
Error: [Errno 111] Connection refused (redis://localhost:6379)
```

**Cause:** Redis not running or wrong host.

**Solution:**

```bash
# Docker Compose: Use service name
REDIS_URL=redis://redis:6379  # NOT localhost

# Check Redis is running
docker ps | grep redis
```

---

**Issue 3: Out of Memory (OOM)**

```
Killed (signal 9)
```

**Cause:** Embedding model too large for free tier (256MB RAM).

**Solution:**

- Use smaller model: `all-MiniLM-L6-v2` (90MB) ✅
- Or upgrade to larger VM (512MB)

---

**Issue 4: Slow Cold Starts**

First request takes 30 seconds on Fly.io.

**Cause:** VM stopped (scale-to-zero), loading embedding model.

**Solution:**

```toml
# fly.toml
min_machines_running = 1  # Keep 1 VM always on
```

**Tradeoff:** Always-on costs ~$2/mo, but no cold starts.

---

### **7.11 What You Should Learn from Deployment**

**Key Takeaways:**

1. **Infrastructure as Code** - Configuration files (Dockerfile, fly.toml) are code
2. **12-Factor App Principles:**

   - One codebase, many deploys
   - Explicit dependencies (requirements.txt)
   - Config in environment variables
   - Stateless processes (Redis holds state)
   - Logs to stdout (not files)

3. **Observability Matters** - Logs, metrics, health checks are critical
4. **Security is Not Optional** - HTTPS, env vars, rate limiting
5. **Tradeoffs Everywhere** - Free tier limits, cold starts, complexity

**Deployment ≠ Done**

Real production engineering includes:

- Monitoring (Datadog, Prometheus)
- Alerting (PagerDuty when down)
- CI/CD (auto-deploy on git push)
- Rollback strategy (blue-green deployments)
- Load testing (how many req/sec can it handle?)

**You've built the foundation. These are next steps.**

---

### **7.12 Free Deployment Options Compared**

| Platform          | Free Tier          | Pros                                                   | Cons                                      | Best For                     |
| ----------------- | ------------------ | ------------------------------------------------------ | ----------------------------------------- | ---------------------------- |
| **Fly.io**        | 3 VMs, 3GB storage | ✅ Redis included<br>✅ Scale to zero<br>✅ Global CDN | ⚠️ 256MB RAM limit                        | **APIs, databases**          |
| **Render**        | 750 hrs/mo         | ✅ Easy setup<br>✅ Auto-deploy from Git               | ❌ No free Redis<br>⚠️ Slower cold starts | **Simple web apps**          |
| **Railway**       | $5 credit/mo       | ✅ Great DX<br>✅ Redis included                       | ⚠️ Credit runs out                        | **Hobby projects**           |
| **Vercel**        | Unlimited          | ✅ Blazing fast<br>✅ Auto-scaling                     | ❌ Serverless only<br>❌ No long-running  | **Frontend, edge functions** |
| **AWS Free Tier** | 12 months          | ✅ Full AWS access                                     | ❌ Complex setup<br>⚠️ Ends after 1 year  | **Learning AWS**             |

**Recommendation for Sentinel:** **Fly.io** (Redis + auto-scaling + generous free tier)

---

### **7.13 Next Steps After Deployment**

**Phase 8 Ideas (Post-Deployment Enhancements):**

1. **Monitoring Dashboard** - Grafana + Prometheus
2. **API Authentication** - JWT tokens or API keys
3. **Rate Limiting** - Redis-based per-user limits
4. **Multi-Provider Support** - Add OpenAI, Anthropic fallbacks
5. **Webhook Notifications** - Alert on high costs
6. **Admin UI** - View cache contents, clear entries
7. **Batch API** - Cache multiple queries at once
8. **A/B Testing** - Compare cache strategies

**All of these can be added incrementally without rewriting!**

---

### **7.14 Mastery Checklist - Deployment**

**You understand deployment when you can answer:**

- [ ] What is a Docker container vs image vs volume?
- [ ] Why use multi-stage builds?
- [ ] How does docker-compose networking work?
- [ ] What are environment variables and why use them?
- [ ] What is a reverse proxy and when to use it?
- [ ] How does HTTPS/SSL work?
- [ ] What is scale-to-zero and why does it save money?
- [ ] How do health checks prevent downtime?
- [ ] What is the difference between dev and prod config?
- [ ] How would you rollback a broken deployment?

**Practice Exercises:**

1. Deploy Sentinel locally with docker-compose
2. Deploy to Fly.io and test externally
3. Add a new environment variable and redeploy
4. View logs and identify a real error
5. Scale to 2 instances and load balance

---

**End of Phase 7 - Deployment** ✅

You now have a **production-ready semantic AI gateway** deployed to the cloud!

---
