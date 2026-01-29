# Sentinel Architecture & System Design

## Overview

Sentinel is a **semantic AI gateway** that sits between your application and LLM providers (Groq, OpenAI, etc.). It reduces LLM API costs by 70-90% using intelligent semantic caching—matching not just exact queries, but semantically similar ones.

## Problem Statement

**Challenges:**

- LLM APIs are expensive ($0.001–$0.06 per 1K tokens)
- LLM APIs are slow (500–2000ms latency per request)
- Many user queries are semantically identical but worded differently:
  - "What is AI?" vs. "Explain artificial intelligence"
  - "Summarize this article" vs. "Give me a summary"

**Traditional Approach:** Exact string caching only matches identical queries → Low hit rate (~10-20%)

**Sentinel's Approach:** Semantic caching using embeddings → Matches similar queries → High hit rate (40-70%)

---

## Architecture Diagram

```
┌─────────────┐
│   Client    │
│ Application │
└──────┬──────┘
       │ HTTP POST /v1/query
       ▼
┌─────────────────────────────────────────┐
│          Sentinel Gateway               │
│  ┌───────────────────────────────────┐  │
│  │  1. Exact Cache Check (5ms)       │  │
│  │     Redis key lookup              │  │
│  └───────────────────────────────────┘  │
│               ↓ (if miss)                │
│  ┌───────────────────────────────────┐  │
│  │  2. Compute Embedding (300ms)     │  │
│  │     Jina Embeddings API           │  │
│  └───────────────────────────────────┘  │
│               ↓                          │
│  ┌───────────────────────────────────┐  │
│  │  3. Semantic Search (50ms)        │  │
│  │     Cosine similarity > 0.75?     │  │
│  └───────────────────────────────────┘  │
│               ↓ (if miss)                │
│  ┌───────────────────────────────────┐  │
│  │  4. Call LLM (1200ms)             │  │
│  │     Groq API                      │  │
│  │  5. Cache result + embedding      │  │
│  └───────────────────────────────────┘  │
└─────────────────────────────────────────┘
       │ ↔ Redis (persistent cache)
       ▼
┌─────────────┐
│  Redis      │  TTL: 3600s (1 hour)
│  Cache      │  Stores: prompt → {response, embedding}
└─────────────┘
```

---

## Core Components

### 1. FastAPI Application (`main.py`)

**Responsibilities:**

- HTTP endpoint handling (`POST /v1/query`, `GET /health`, etc.)
- Request validation (Pydantic models)
- Cache lookup orchestration (exact → semantic → LLM)
- Response formatting
- Middleware (logging, error handling)

**Key Design Decisions:**

- **Modern lifespan pattern:** Uses `@asynccontextmanager` (not deprecated `@app.on_event`)
- **Async I/O:** All external calls (Redis, Jina, Groq) are async
- **Fail-fast validation:** Missing env vars raise errors at startup

### 2. Redis Cache (`cache_redis.py`)

**Responsibilities:**

- Store prompt → response mappings (exact match cache)
- Store prompt → embedding mappings (semantic search)
- TTL management (auto-expire old entries after 1 hour)
- Cache statistics (hits, misses, hit rate)

**Why Redis (not in-memory):**

- **Persistent:** Survives server restarts
- **Shared:** Multiple instances share the same cache
- **Built-in TTL:** Auto-cleanup without custom logic
- **Free tier available:** Fly.io includes managed Redis

**Storage Format:**

```
Key: "sentinel:cache:What is AI?"
Value: "AI is the simulation of human intelligence..."

Key: "sentinel:cache:What is AI?:embedding"
Value: "[0.123, -0.456, 0.789, ...]" (JSON array of 1024 floats)
```

### 3. Embeddings (`embeddings.py`)

**Responsibilities:**

- Generate 1024-dimensional vectors from text (via Jina API)
- Compute cosine similarity between embeddings
- Find best matching cached embedding above threshold

**Why Jina API (not local model):**

- **No RAM overhead:** Local models require 256MB+ RAM
- **No startup delay:** No model download (90MB+ files)
- **Stateless:** Scales infinitely (external API)
- **Free tier:** 1M tokens/month
- **High quality:** 1024D vectors, enterprise-grade

**Embedding Process:**

```
Input:  "What is quantum computing?"
        ↓ (HTTP POST to Jina API)
Output: [0.234, -0.567, 0.123, ..., 0.890]  (1024 floats)
```

**Similarity Calculation:**

```python
similarity = cosine_similarity(query_embedding, cached_embedding)
# Returns float 0.0–1.0
# - 1.0 = identical
# - 0.85 = very similar (default threshold: 0.75)
# - 0.5 = somewhat related
# - 0.0 = completely different
```

### 4. LLM Provider (`llm_provider.py`)

**Responsibilities:**

- Call Groq API with retry logic (exponential backoff)
- Handle rate limiting (429 errors)
- Calculate token usage and costs
- Track latency

**Why Groq:**

- **Free tier:** 20,000 tokens/min
- **Fast:** 500–1500ms latency
- **Cheap:** $0.05/$0.15 per 1M tokens (input/output)
- **Reliable:** Stable API, good error messages

**Retry Strategy:**

- Max 3 retries
- Exponential backoff: 1s → 2s → 4s
- Respect 429 rate limits (don't spam)

---

## Request Flow (Step-by-Step)

### Example: User asks "What is AI?"

**Step 1: Exact Cache Check (5ms)**

```python
# Check Redis for exact key
cache_key = "sentinel:cache:What is AI?"
cached_response = await redis.get(cache_key)

if cached_response:
    return {"response": cached_response, "cache_hit": true, "similarity_score": 1.0}
```

**Result:** MISS (first time query)

---

**Step 2: Compute Embedding (300ms)**

```python
# Call Jina API to get embedding vector
embedding = await jina_api.embed("What is AI?")
# Returns: np.array([0.234, -0.567, ...], shape=(1024,))
```

---

**Step 3: Semantic Search (50ms)**

```python
# Get all cached embeddings from Redis
cached_items = await redis.get_all_cached()
# [{"prompt": "Explain AI", "embedding": [...], "response": "..."}, ...]

# Find best match
best_match = None
best_similarity = 0.0

for item in cached_items:
    similarity = cosine_similarity(embedding, item["embedding"])
    if similarity > 0.75 and similarity > best_similarity:
        best_match = item
        best_similarity = similarity

if best_match:
    return {
        "response": best_match["response"],
        "cache_hit": true,
        "similarity_score": best_similarity,
        "matched_prompt": best_match["prompt"]
    }
```

**Result:** MISS (no cached items yet)

---

**Step 4: Call LLM (1200ms)**

```python
# Call Groq API
llm_response = await groq_api.call(
    prompt="What is AI?",
    model="llama-3.1-8b-instant",
    temperature=0.7,
    max_tokens=500
)
# Returns: {
#   "response": "AI is the simulation of human intelligence...",
#   "tokens_used": 145,
#   "cost_usd": 0.000218
# }
```

---

**Step 5: Cache Result (10ms)**

```python
# Store in Redis
await redis.set("sentinel:cache:What is AI?", llm_response["response"])
await redis.set("sentinel:cache:What is AI?:embedding", json.dumps(embedding.tolist()))

# Set TTL (auto-expire after 1 hour)
await redis.expire("sentinel:cache:What is AI?", 3600)
await redis.expire("sentinel:cache:What is AI?:embedding", 3600)
```

---

**Step 6: Return to Client**

```json
{
  "response": "AI is the simulation of human intelligence...",
  "cache_hit": false,
  "similarity_score": null,
  "matched_prompt": null,
  "provider": "groq",
  "model": "llama-3.1-8b-instant",
  "tokens_used": 145,
  "latency_ms": 1234.5
}
```

---

### Next Request: "Explain artificial intelligence"

**Step 1: Exact Check** → MISS (different wording)

**Step 2: Compute Embedding** → `[0.241, -0.572, ...]` (slightly different from "What is AI?")

**Step 3: Semantic Search**

```python
cached_items = [{"prompt": "What is AI?", "embedding": [...], "response": "..."}]
similarity = cosine_similarity(new_embedding, cached_embedding)
# Returns: 0.92 (very similar!)

if 0.92 > 0.75:  # Above threshold
    return cached_response  # ✅ CACHE HIT!
```

**Result:**

```json
{
  "response": "AI is the simulation of human intelligence...",
  "cache_hit": true,
  "similarity_score": 0.92,
  "matched_prompt": "What is AI?",
  "latency_ms": 45.2
}
```

**Savings:**

- Latency: 1234ms → 45ms (96% faster)
- Cost: $0.000218 → $0 (100% saved)

---

## Performance Characteristics

| Operation             | Latency | Notes                         |
| --------------------- | ------- | ----------------------------- |
| Exact cache hit       | 5ms     | Redis key lookup              |
| Semantic cache hit    | 45ms    | 300ms embedding + 50ms search |
| Cache miss (LLM call) | 1200ms  | Groq API + cache write        |

**Typical Cache Hit Rate:** 40-70% (depends on query diversity)

**Cost Savings Example:**

```
1000 requests/day
- 600 cache hits → $0
- 400 cache misses → 400 × $0.000218 = $0.087/day = $2.61/month
- Without caching: 1000 × $0.000218 = $6.54/month
- Savings: 60% reduction
```

---

## Design Decisions & Trade-offs

### 1. Why External Embedding API (Jina) vs. Local Model?

**Local Model (e.g., sentence-transformers):**

- ✅ No external API dependency
- ❌ 256MB+ RAM overhead
- ❌ 90MB model download at startup (90s delay)
- ❌ CPU-intensive (slow on weak machines)

**External API (Jina):**

- ✅ Stateless (scales infinitely)
- ✅ No RAM overhead
- ✅ Instant startup (<1s)
- ✅ High quality (1024D vectors)
- ❌ External dependency (can fail)
- ❌ Adds 300ms latency

**Decision:** External API wins for production deployments. Graceful degradation handles API failures.

### 2. Why Two-Pass Cache (Exact + Semantic)?

**Single-Pass (Semantic Only):**

- Always compute embedding (300ms) even for exact duplicates

**Two-Pass (Exact First):**

- Exact duplicates skip embedding computation (5ms vs 350ms)
- If 30% of queries are exact duplicates, saves 30% × 300ms = 90ms/query average

**Decision:** Two-pass is a free optimization with minimal code complexity.

### 3. Why Cosine Similarity (not Euclidean Distance)?

**Cosine Similarity:**

- Magnitude-independent ("AI" vs. "ARTIFICIAL INTELLIGENCE" same similarity)
- Interpretable (0-1 scale, 1.0 = identical)
- Standard for embeddings

**Euclidean Distance:**

- Sensitive to magnitude (penalizes longer text)
- Harder to interpret (what does distance 0.3 mean?)

**Decision:** Cosine similarity is the industry standard for embeddings.

### 4. Why Default Threshold = 0.75?

**Too High (0.95):**

- Only exact rephrasings match → Low hit rate (<30%)

**Too Low (0.60):**

- False positives ("What is AI?" matches "What is ML?") → Confuses users

**Sweet Spot (0.75):**

- Catches legitimate rephrases without false positives
- Tunable per-request

**Decision:** Start conservative (0.75), let users tune based on metrics.

---

## Failure Modes & Mitigations

### 1. Jina API Down

**Symptom:** All embedding requests fail

**Mitigation:**

```python
try:
    embedding = await jina_api.embed(prompt)
except Exception:
    # Fall back to exact-match-only mode
    embedding = None
    logger.warning("Jina API unavailable, using exact-match cache only")
```

### 2. Redis Out of Memory

**Symptom:** New cache writes fail, old entries not evicted

**Mitigation:**

```bash
# Configure Redis maxmemory + LRU eviction
redis-cli CONFIG SET maxmemory 512mb
redis-cli CONFIG SET maxmemory-policy allkeys-lru
```

### 3. Groq Rate Limit (429)

**Symptom:** LLM calls fail with "Too Many Requests"

**Mitigation:**

```python
# Exponential backoff retry
for retry in range(3):
    try:
        return await groq_api.call(prompt)
    except RateLimitError:
        await asyncio.sleep(2 ** retry)  # 1s, 2s, 4s
```

---

## Monitoring & Observability

**Key Metrics (Available at `/v1/metrics`):**

- `cache_hit_rate`: Percentage of requests served from cache
- `total_requests`: Lifetime request count
- `stored_items`: Number of unique prompts cached

**Health Check (`/health`):**

- Returns 200 OK if all services (Redis, Jina, Groq) are reachable
- Used by load balancers and monitoring systems

**Logs:**

- Structured logging (timestamp, level, module, message)
- Request/response latency tracking
- Cache hit/miss events
- Error traces with full stack

---

## Success Criteria

✅ **Functional:**

- Cache hit rate > 40%
- No false positives (semantically different queries don't match)
- Graceful degradation (external API failures don't crash system)

✅ **Performance:**

- Cache hit latency < 50ms
- Total overhead < 10% (embedding + search time)

✅ **Cost:**

- Total savings > 30% for realistic workloads
- Free tier deployment possible ($0/month on Fly.io)

---

## Security & Access Control

### Authentication (Implemented ✅)

**Mechanism:** API key-based authentication via `X-API-Key` header.

**Key Types:**

| Type  | Access                                              | Example              |
| ----- | --------------------------------------------------- | -------------------- |
| User  | `/v1/query`, `/health`, `/docs`, `/metrics`         | `sk_user_xyz...`     |
| Admin | All endpoints (includes `/v1/cache/*` debug routes) | `sk_admin_secret123` |

**Why This Design:**

- **Simple:** No JWT complexity, no token refresh logic
- **Secure:** Header-based (not URL param), constant-time comparison
- **Auditable:** Easy to revoke individual keys
- **Stateless:** No session storage required

### Rate Limiting (Implemented ✅)

**Token Bucket Algorithm:**

- **Limit:** 100 requests per minute (configurable)
- **Per-Key:** Each API key has its own bucket
- **Redis-Backed:** Distributed rate limiting across instances

**Response Headers:**

- `X-RateLimit-Limit: 100`
- `X-RateLimit-Remaining: 87`
- `X-RateLimit-Reset: 1234567890` (Unix timestamp)

**Error Handling:**

- `429 Too Many Requests` - Rate limit exceeded
- Response includes `Retry-After` header

### Observability (Implemented ✅)

**Prometheus Metrics:**

- `sentinel_requests_total` - Total requests by endpoint, status, API key role
- `sentinel_cache_hits_total` - Cache hits by type (exact, semantic, miss)
- `sentinel_latency_ms` - Request duration distribution
- `sentinel_tokens_used_total` - LLM token usage
- `sentinel_costs_usd_total` - API call costs

**Metrics Endpoint:**

- `GET /metrics` - Prometheus format (raw metrics)
- `GET /v1/metrics` - JSON format (cache statistics)

**Health Checks:**

- `GET /health` - Service health + Redis connectivity

---

## Future Enhancements (Post-V2)

**Potential Additions:**

- Streaming responses (chunked transfer for perceived latency reduction)
- Multi-provider support (OpenAI, Anthropic, Cohere)
- Cache invalidation API (manual cache clearing)
- Advanced RBAC (granular permissions, resource-level control)
- Webhook notifications (cache hits/misses alerts)
