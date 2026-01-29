# API Reference

Complete API documentation for Sentinel AI Gateway.

---

## Base URL

**Local Development:**

```
http://localhost:8000
```

**Production (Fly.io):**

```
https://sentinel-ai-gateway.fly.dev
```

---

## Authentication

**API key authentication required** for all endpoints except health checks.

**Mechanism:** Include `X-API-Key` header with every request (except `GET /` and `GET /health`).

**Key Types:**

| Key Type | Access                                                          | Example            |
| -------- | --------------------------------------------------------------- | ------------------ |
| User     | `/v1/query`, `/health`, `/`, `/docs`, `/metrics`, `/v1/metrics` | sk_user_xyz...     |
| Admin    | All endpoints (includes `/v1/cache/*` debug endpoints)          | sk_admin_secret123 |

**Example Request:**

```bash
curl -X POST http://localhost:8000/v1/query \
  -H "Content-Type: application/json" \
  -H "X-API-Key: sk_user_xyz123" \
  -d '{"prompt": "Explain quantum computing"}'
```

**Rate Limiting:**

- **Limit:** 100 requests per minute (configurable)
- **Enforcement:** Per API key
- **Headers Returned:**
  - `X-RateLimit-Limit: 100`
  - `X-RateLimit-Remaining: 87`
  - `X-RateLimit-Reset: 1234567890`

**Status Codes:**

- `401 Unauthorized` - Missing or invalid API key
- `429 Too Many Requests` - Rate limit exceeded

---

## Endpoints

### 1. Root Check

**GET /** - Connectivity test

**Description:** Simple health check to verify service is running.

**Request:**

```bash
curl http://localhost:8000/
```

**Response:**

```json
{
  "status": "Sentinel AI Gateway is running",
  "timestamp": "2024-01-15T10:30:00Z"
}
```

**Status Codes:**

- `200 OK` - Service is healthy

---

### 2. Health Check

**GET /health** - Service health status

**Description:** Used by load balancers and monitoring systems. Checks Redis connectivity.

**Request:**

```bash
curl http://localhost:8000/health
```

**Response:**

```json
{
  "status": "healthy",
  "redis": "connected",
  "timestamp": "2024-01-15T10:30:00Z"
}
```

**Status Codes:**

- `200 OK` - All systems operational
- `503 Service Unavailable` - Redis connection failed

---

### 3. Query (Main Endpoint)

**POST /v1/query** - Submit query with semantic caching

**Description:** Primary endpoint for LLM queries. Uses two-pass caching (exact → semantic) before calling LLM.

**Request Headers:**

```
Content-Type: application/json
X-API-Key: sk_user_xyz123
```

**Request Body:**

```json
{
  "prompt": "What is artificial intelligence?",
  "model": "llama-3.1-8b-instant",
  "temperature": 0.7,
  "max_tokens": 500,
  "stream": false,
  "similarity_threshold": 0.75
}
```

**Parameters:**

| Field                  | Type   | Required | Default              | Description                        |
| ---------------------- | ------ | -------- | -------------------- | ---------------------------------- |
| `prompt`               | string | ✅       | -                    | User query (max 2000 chars)        |
| `model`                | string | ❌       | llama-3.1-8b-instant | Groq model ID                      |
| `temperature`          | float  | ❌       | 0.7                  | Randomness (0.0–2.0)               |
| `max_tokens`           | int    | ❌       | 500                  | Max response length                |
| `stream`               | bool   | ❌       | false                | Streaming (not implemented yet)    |
| `similarity_threshold` | float  | ❌       | 0.75                 | Semantic match threshold (0.0–1.0) |

**Example Request:**

```bash
curl -X POST http://localhost:8000/v1/query \
  -H "Content-Type: application/json" \
  -H "X-API-Key: sk_user_xyz123" \
  -d '{
    "prompt": "Explain quantum computing in simple terms",
    "temperature": 0.5,
    "max_tokens": 300
  }'
```

**Response (Cache Miss - LLM Call):**

```json
{
  "response": "Quantum computing uses quantum mechanics principles like superposition and entanglement to process information. Unlike classical computers that use bits (0 or 1), quantum computers use qubits that can be both 0 and 1 simultaneously...",
  "cache_hit": false,
  "similarity_score": null,
  "matched_prompt": null,
  "provider": "groq",
  "model": "llama-3.1-8b-instant",
  "tokens_used": 145,
  "cost_usd": 0.000218,
  "latency_ms": 1234.5
}
```

**Response (Cache Hit - Exact Match):**

```json
{
  "response": "Quantum computing uses quantum mechanics principles...",
  "cache_hit": true,
  "similarity_score": 1.0,
  "matched_prompt": "Explain quantum computing in simple terms",
  "provider": "cache",
  "model": null,
  "tokens_used": 0,
  "cost_usd": 0.0,
  "latency_ms": 5.2
}
```

**Response (Cache Hit - Semantic Match):**

```json
{
  "response": "Quantum computing uses quantum mechanics principles...",
  "cache_hit": true,
  "similarity_score": 0.87,
  "matched_prompt": "What is quantum computing?",
  "provider": "cache",
  "model": null,
  "tokens_used": 0,
  "cost_usd": 0.0,
  "latency_ms": 42.1
}
```

**Response Fields:**

| Field              | Type        | Description                                                  |
| ------------------ | ----------- | ------------------------------------------------------------ |
| `response`         | string      | LLM-generated answer                                         |
| `cache_hit`        | bool        | `true` if served from cache                                  |
| `similarity_score` | float/null  | Cosine similarity (1.0 = exact, 0.87 = semantic, null = LLM) |
| `matched_prompt`   | string/null | Original cached prompt (if cache hit)                        |
| `provider`         | string      | "groq" or "cache"                                            |
| `model`            | string/null | Model ID used (null if cached)                               |
| `tokens_used`      | int         | Token count (0 if cached)                                    |
| `cost_usd`         | float       | Estimated cost (0.0 if cached)                               |
| `latency_ms`       | float       | Request duration                                             |

**Status Codes:**

- `200 OK` - Successful response
- `400 Bad Request` - Invalid input (missing prompt, invalid parameters)
- `500 Internal Server Error` - LLM API failure or Redis error
- `503 Service Unavailable` - External services (Jina/Groq) unreachable

**Error Response:**

```json
{
  "detail": "Prompt is required",
  "error_code": "VALIDATION_ERROR"
}
```

---

### 4. Cache Metrics

**GET /v1/metrics** - Cache performance statistics

**Description:** Returns cache hit rate, total requests, and stored items. Requires user or admin API key.

**Request:**

```bash
curl http://localhost:8000/v1/metrics \
  -H "X-API-Key: sk_user_xyz123"
```

**Response:**

```json
{
  "total_requests": 1523,
  "cache_hits": 892,
  "cache_misses": 631,
  "cache_hit_rate": 58.57,
  "stored_items": 412,
  "uptime_seconds": 86400
}
```

**Response Fields:**

| Field            | Type  | Description                 |
| ---------------- | ----- | --------------------------- |
| `total_requests` | int   | Lifetime request count      |
| `cache_hits`     | int   | Requests served from cache  |
| `cache_misses`   | int   | Requests requiring LLM call |
| `cache_hit_rate` | float | Percentage (0-100)          |
| `stored_items`   | int   | Unique prompts cached       |
| `uptime_seconds` | int   | Time since server start     |

**Status Codes:**

- `200 OK` - Metrics retrieved successfully
- `503 Service Unavailable` - Redis connection failed

---

### 5. List Cached Items (Debug)

**GET /v1/cache/all** - Retrieve all cached prompts

**Description:** Returns list of all cached prompts with responses and embeddings.

**Request:**

```bash
curl http://localhost:8000/v1/cache/all
```

**Response:**

```json
{
  "cached_items": [
    {
      "prompt": "What is AI?",
      "response": "AI is the simulation of human intelligence...",
      "embedding": [0.234, -0.567, 0.123, ...],
      "cached_at": "2024-01-15T10:15:00Z",
      "ttl_seconds": 2145
    },
    {
      "prompt": "Explain quantum computing",
      "response": "Quantum computing uses quantum mechanics...",
      "embedding": [0.112, -0.334, 0.889, ...],
      "cached_at": "2024-01-15T10:20:00Z",
      "ttl_seconds": 2445
    }
  ],
  "total_count": 2
}
```

**Response Fields:**

| Field          | Type   | Description               |
| -------------- | ------ | ------------------------- |
| `cached_items` | array  | List of cached entries    |
| `prompt`       | string | Original query            |
| `response`     | string | Cached LLM response       |
| `embedding`    | array  | 1024D vector (floats)     |
| `cached_at`    | string | ISO timestamp when cached |
| `ttl_seconds`  | int    | Time until expiration     |
| `total_count`  | int    | Total cached items        |

**Status Codes:**

- `200 OK` - Cache items retrieved
- `503 Service Unavailable` - Redis error

**Security Warning:** This endpoint exposes all cached data. Remove in production or add authentication.

---

### 6. Clear Cache (Debug)

**DELETE /v1/cache/clear** - Delete all cached items

**Description:** Removes all entries from Redis cache. Useful for testing.

**Request:**

```bash
curl -X DELETE http://localhost:8000/v1/cache/clear
```

**Response:**

```json
{
  "status": "success",
  "message": "Cache cleared successfully",
  "deleted_count": 412
}
```

**Status Codes:**

- `200 OK` - Cache cleared
- `503 Service Unavailable` - Redis error

**Security Warning:** This is a destructive operation. Protect with authentication in production.

---

### 7. Test Embeddings (Debug)

**POST /v1/cache/test-embeddings** - Compare similarity between two prompts

**Description:** Compute embeddings and cosine similarity for testing semantic matching.

**Request:**

```bash
curl -X POST http://localhost:8000/v1/cache/test-embeddings \
  -H "Content-Type: application/json" \
  -d '{
    "prompt1": "What is artificial intelligence?",
    "prompt2": "Explain AI"
  }'
```

**Request Body:**

```json
{
  "prompt1": "What is artificial intelligence?",
  "prompt2": "Explain AI"
}
```

**Response:**

```json
{
  "prompt1": "What is artificial intelligence?",
  "prompt2": "Explain AI",
  "similarity": 0.92,
  "is_match": true,
  "threshold": 0.75,
  "embedding1": [0.234, -0.567, ...],
  "embedding2": [0.241, -0.572, ...]
}
```

**Response Fields:**

| Field        | Type   | Description                      |
| ------------ | ------ | -------------------------------- |
| `prompt1`    | string | First prompt                     |
| `prompt2`    | string | Second prompt                    |
| `similarity` | float  | Cosine similarity (0.0–1.0)      |
| `is_match`   | bool   | `true` if similarity ≥ threshold |
| `threshold`  | float  | Default threshold (0.75)         |
| `embedding1` | array  | 1024D vector for prompt1         |
| `embedding2` | array  | 1024D vector for prompt2         |

**Status Codes:**

- `200 OK` - Similarity computed
- `400 Bad Request` - Missing prompts
- `503 Service Unavailable` - Jina API error

---

## Rate Limits

**Current:** No rate limiting (development mode)

**Groq Free Tier Limits:**

- 20,000 tokens/minute
- 5,000 requests/day

**Jina Free Tier Limits:**

- 1,000,000 tokens/month
- 100 requests/second

---

## Error Handling

### Common Error Codes

| Code               | Status | Description                |
| ------------------ | ------ | -------------------------- |
| `VALIDATION_ERROR` | 400    | Invalid request parameters |
| `REDIS_ERROR`      | 503    | Redis connection failed    |
| `EMBEDDING_ERROR`  | 503    | Jina API unavailable       |
| `LLM_ERROR`        | 500    | Groq API error             |
| `RATE_LIMIT_ERROR` | 429    | Groq rate limit exceeded   |

### Example Error Responses

**Validation Error:**

```json
{
  "detail": "Prompt is required and cannot be empty",
  "error_code": "VALIDATION_ERROR"
}
```

**Redis Error:**

```json
{
  "detail": "Cache service unavailable",
  "error_code": "REDIS_ERROR"
}
```

**LLM Error:**

```json
{
  "detail": "Groq API error: rate limit exceeded",
  "error_code": "RATE_LIMIT_ERROR",
  "retry_after_seconds": 60
}
```

---

## Best Practices

### 1. Optimize Cache Hit Rate

**Do:**

- Use consistent phrasing for common queries
- Set appropriate `similarity_threshold` (0.70–0.80)
- Monitor `/v1/metrics` to track hit rate

**Don't:**

- Add timestamps or random IDs to prompts (reduces cache hits)
- Set threshold too low (<0.6) → false positives
- Set threshold too high (>0.9) → low hit rate

### 2. Handle Errors Gracefully

**Example:**

```python
import requests

def query_sentinel(prompt):
    try:
        response = requests.post(
            "http://localhost:8000/v1/query",
            json={"prompt": prompt},
            timeout=5.0
        )
        response.raise_for_status()
        return response.json()["response"]
    except requests.exceptions.Timeout:
        return "Service timeout - please retry"
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 429:
            return "Rate limit exceeded - retry in 60s"
        raise
```

### 3. Monitor Performance

**Key Metrics to Track:**

- Cache hit rate (target: >40%)
- P95 latency (cache hit: <50ms, miss: <1500ms)
- Cost per 1000 requests
- Error rate (<1%)

**Example Dashboard:**

```bash
# Check metrics every 5 minutes
watch -n 300 'curl -s http://localhost:8000/v1/metrics | jq'
```

---

## Troubleshooting

### Issue: Low Cache Hit Rate (<20%)

**Possible Causes:**

- Queries are too diverse (every prompt is unique)
- Threshold too high (try 0.70 instead of 0.75)
- Cache expiring too quickly (increase TTL in code)

**Solution:**

```bash
# Test similarity between similar queries
curl -X POST http://localhost:8000/v1/cache/test-embeddings \
  -H "Content-Type: application/json" \
  -d '{"prompt1": "What is AI?", "prompt2": "Explain AI"}'

# If similarity < 0.75, lower threshold:
curl -X POST http://localhost:8000/v1/query \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Explain AI", "similarity_threshold": 0.70}'
```

---

### Issue: High Latency (>2000ms)

**Possible Causes:**

- Groq API slow (check status.groq.com)
- Jina API slow (check status.jina.ai)
- Too many cached items (semantic search takes longer)

**Solution:**

```bash
# Check metrics for cache performance
curl http://localhost:8000/v1/metrics

# If stored_items > 10,000, clear old entries:
curl -X DELETE http://localhost:8000/v1/cache/clear
```

---

### Issue: "Cache service unavailable" Error

**Possible Causes:**

- Redis not running
- Incorrect `REDIS_URL` environment variable

**Solution:**

```bash
# Check Redis connection
redis-cli ping
# Should return: PONG

# Verify environment variable
echo $REDIS_URL
# Should be: redis://localhost:6379

# Restart Redis (Docker)
docker-compose restart redis
```

---

### Issue: "Embedding error" (503)

**Possible Causes:**

- Missing `JINA_API_KEY` environment variable
- Invalid API key
- Jina API rate limit exceeded

**Solution:**

```bash
# Verify API key is set
echo $JINA_API_KEY
# Should start with: jina_...

# Test Jina API directly
curl https://api.jina.ai/v1/embeddings \
  -H "Authorization: Bearer $JINA_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"input": "test", "model": "jina-embeddings-v3"}'
```

---

## Migration from HuggingFace to Jina

**Old (HuggingFace Inference API):**

```json
{
  "HF_API_TOKEN": "hf_...",
  "model": "sentence-transformers/all-MiniLM-L6-v2",
  "embedding_dimension": 384
}
```

**New (Jina Embeddings API):**

```json
{
  "JINA_API_KEY": "jina_...",
  "model": "jina-embeddings-v3",
  "embedding_dimension": 1024
}
```

**Impact:**

- Better embedding quality (1024D vs 384D)
- Faster API response (~300ms vs ~800ms)
- Higher free tier (1M tokens/month vs 100K/month)

**No code changes required** - just update environment variable.

---

## Examples

### Python Client

```python
import requests

class SentinelClient:
    def __init__(self, base_url="http://localhost:8000"):
        self.base_url = base_url

    def query(self, prompt, **kwargs):
        response = requests.post(
            f"{self.base_url}/v1/query",
            json={"prompt": prompt, **kwargs},
            timeout=10.0
        )
        response.raise_for_status()
        return response.json()

    def get_metrics(self):
        response = requests.get(f"{self.base_url}/v1/metrics")
        response.raise_for_status()
        return response.json()

# Usage
client = SentinelClient()
result = client.query("What is machine learning?")
print(result["response"])
print(f"Cache hit: {result['cache_hit']}")
```

### JavaScript Client

```javascript
class SentinelClient {
  constructor(baseURL = "http://localhost:8000") {
    this.baseURL = baseURL;
  }

  async query(prompt, options = {}) {
    const response = await fetch(`${this.baseURL}/v1/query`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prompt, ...options }),
    });

    if (!response.ok) {
      throw new Error(`API error: ${response.status}`);
    }

    return response.json();
  }

  async getMetrics() {
    const response = await fetch(`${this.baseURL}/v1/metrics`);
    return response.json();
  }
}

// Usage
const client = new SentinelClient();
const result = await client.query("Explain neural networks");
console.log(result.response);
console.log(`Cache hit: ${result.cache_hit}`);
```

### cURL Examples

**Basic Query:**

```bash
curl -X POST http://localhost:8000/v1/query \
  -H "Content-Type: application/json" \
  -d '{"prompt": "What is Docker?"}'
```

**Custom Temperature:**

```bash
curl -X POST http://localhost:8000/v1/query \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "Write a creative story",
    "temperature": 1.2,
    "max_tokens": 1000
  }'
```

**Lower Similarity Threshold:**

```bash
curl -X POST http://localhost:8000/v1/query \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "Explain blockchain",
    "similarity_threshold": 0.65
  }'
```

**Check Metrics:**

```bash
curl http://localhost:8000/v1/metrics | jq
```

**Test Semantic Similarity:**

```bash
curl -X POST http://localhost:8000/v1/cache/test-embeddings \
  -H "Content-Type: application/json" \
  -d '{
    "prompt1": "What is Python?",
    "prompt2": "Explain Python programming"
  }' | jq '.similarity'
```
