# Sentinel API Contract

## Version: v1

All endpoints prefixed with `/v1` to allow future breaking changes without disrupting existing clients.

---

## Endpoints

### 1. POST /v1/query

**Purpose:** Submit a prompt to an LLM provider with semantic caching.

#### Request

```http
POST /v1/query
Content-Type: application/json
X-API-Key: <optional-client-auth-token>
```

**Body:**

```json
{
  "prompt": "Explain quantum computing in simple terms",
  "provider": "openai",
  "model": "gpt-4",
  "temperature": 0.7,
  "max_tokens": 500,
  "metadata": {
    "user_id": "optional-tracking-id"
  }
}
```

**Field Definitions:**

- `prompt` (required, string): The user's query/instruction
- `provider` (required, string): One of: `openai`, `anthropic`, `cohere`
- `model` (required, string): Model identifier (e.g., `gpt-4`, `claude-3-sonnet`)
- `temperature` (optional, float, default=0.0): Sampling temperature (0.0–2.0)
- `max_tokens` (optional, int, default=1000): Maximum response length
- `metadata` (optional, object): Arbitrary key-value pairs for logging (not used in caching)

#### Response (200 OK)

```json
{
  "response": "Quantum computing uses quantum bits (qubits) that can exist in...",
  "cache_hit": false,
  "similarity_score": null,
  "matched_prompt": null,
  "provider": "openai",
  "model": "gpt-4",
  "tokens_used": 87,
  "latency_ms": 1243
}
```

**Field Definitions:**

- `response` (string): The LLM's generated text
- `cache_hit` (boolean): `true` if served from cache, `false` if fresh API call
- `similarity_score` (float|null): Cosine similarity to matched cached prompt (0.0–1.0), null if cache miss
- `matched_prompt` (string|null): The original cached prompt that matched (null if cache miss)
- `provider` (string): Echo of request provider
- `model` (string): Echo of request model
- `tokens_used` (int): Token count (from LLM provider or estimated if cached)
- `latency_ms` (int): Time from request received to response sent

#### Error Responses

**400 Bad Request** — Invalid request body

```json
{
  "error": "validation_error",
  "message": "Field 'prompt' is required",
  "field": "prompt"
}
```

**429 Too Many Requests** — LLM provider rate limit hit

```json
{
  "error": "rate_limit_exceeded",
  "message": "OpenAI rate limit exceeded, retry after 60s",
  "retry_after": 60
}
```

**500 Internal Server Error** — Sentinel or LLM provider failure

```json
{
  "error": "internal_error",
  "message": "Failed to generate embedding",
  "details": "sentence-transformers model not loaded"
}
```

**503 Service Unavailable** — LLM provider is down

```json
{
  "error": "provider_unavailable",
  "message": "OpenAI API is unreachable",
  "provider": "openai"
}
```

---

### 2. GET /health

**Purpose:** Basic health check for load balancers and monitoring.

#### Response (200 OK)

```json
{
  "status": "healthy",
  "version": "0.1.0",
  "uptime_seconds": 3847
}
```

#### Response (503 Service Unavailable)

```json
{
  "status": "unhealthy",
  "reason": "cache_backend_unreachable"
}
```

---

### 3. GET /v1/metrics

**Purpose:** Retrieve cache performance statistics (useful for debugging/monitoring).

#### Response (200 OK)

```json
{
  "total_requests": 1523,
  "cache_hits": 682,
  "cache_misses": 841,
  "hit_rate": 0.448,
  "avg_similarity_score": 0.91,
  "total_tokens_saved": 45230,
  "uptime_seconds": 3847
}
```

**Field Definitions:**

- `total_requests` (int): Lifetime request count since startup
- `cache_hits` (int): Number of requests served from cache
- `cache_misses` (int): Number of requests forwarded to LLM
- `hit_rate` (float): `cache_hits / total_requests`
- `avg_similarity_score` (float): Mean similarity score of cache hits
- `total_tokens_saved` (int): Estimated tokens NOT sent to LLM due to caching

---

## Design Decisions

### Why POST for `/v1/query`?

- Prompts are not idempotent (temperature > 0 means different responses)
- Prompts can be large (>2KB for complex instructions)
- Prompts may contain sensitive data (shouldn't appear in URL logs)

### Why JSON request/response?

- Universal: Every language has JSON libraries
- Human-readable: Easy to debug with curl/Postman
- Schema-validatable: We can use Pydantic models in FastAPI

### Why include `similarity_score` and `matched_prompt` in responses?

- **Transparency:** Clients can audit cache behavior
- **Debugging:** Helps identify false positives (low similarity score = bad match)
- **Trust:** Users see _why_ they got a cached response

### Why NOT implement streaming (yet)?

Streaming requires:

- Chunked transfer encoding or SSE
- Partial cache writes (what if stream fails halfway?)
- More complex client handling

We'd gain perceived latency improvements but lose simplicity. **Deferred to v2.**

### Why version prefix `/v1/`?

When we inevitably need breaking changes (e.g., add streaming, change schema), we can launch `/v2/` without migrating existing clients.

---

## Open Questions (To Decide Later)

1. **Authentication:** Do we need API keys? (Current: optional `X-API-Key` header)
2. **Rate limiting:** Should Sentinel rate-limit clients, or assume that's handled upstream?
3. **Batch requests:** Should clients send multiple prompts in one request? (Current: no, keep it simple)
4. **Cache invalidation:** Should we expose a DELETE endpoint to clear cache? (Current: no, cache expires naturally)
