# Sentinel — System Definition

## Problem Statement

LLM APIs are expensive and slow. Many requests are semantically identical (e.g., "summarize this article" vs. "give me a summary of this text") but get processed as unique calls, wasting money and time.  
Sentinel sits between clients and LLM providers to cache responses based on semantic similarity, not exact string matching.

---

## Non-Goals (What Sentinel Does NOT Do)

- **Not a prompt engineering tool**: We don't optimize or modify prompts
- **Not an LLM model**: We don't generate responses, only cache/forward them
- **Not a full observability platform**: We may log requests, but we're not replacing DataDog
- **Not multi-tenant (v1)**: Single deployment per user/team to keep complexity low
- **Not responsible for LLM provider failover**: If OpenAI is down, we fail too

---

## Inputs

1. **Client HTTP request** containing:

   - Prompt text (the user's query)
   - Target LLM provider (e.g., `openai`, `anthropic`)
   - Model name (e.g., `gpt-4`, `claude-3-sonnet`)
   - Optional: temperature, max_tokens, etc.

2. **Configuration** (at startup):
   - Similarity threshold (0.0–1.0, e.g., 0.85 means "85% similar = cache hit")
   - Cache backend type (in-memory, Redis, etc.)
   - LLM provider API keys

---

## Outputs

1. **HTTP response** to client:

   - LLM-generated text (from cache OR fresh API call)
   - Metadata: `cache_hit: true/false`, `similarity_score: 0.92`
   - Standard HTTP codes (200, 429, 500, etc.)

2. **Side effects**:
   - Cache storage (embedding + response stored for future matches)
   - Logs (request/response, cache hits/misses)

---

## Minimal Architecture Outline

```
┌─────────┐      ┌──────────────┐      ┌─────────────┐
│ Client  │─────▶│   Sentinel   │─────▶│ LLM Provider│
│         │◀─────│   Gateway    │◀─────│ (OpenAI)    │
└─────────┘      └──────────────┘      └─────────────┘
                        │
                        ▼
                  ┌──────────┐
                  │  Cache   │
                  │ (Embedder│
                  │  + Store)│
                  └──────────┘
```

**Flow:**

1. Request arrives → Extract prompt
2. Generate embedding of prompt (using sentence-transformers or similar)
3. Check cache for similar embeddings (cosine similarity > threshold)
4. **If cache hit:** Return cached response
5. **If cache miss:** Forward to LLM → Store response + embedding → Return to client

**Key constraint:** Embedding generation must be fast (<100ms) or we defeat the purpose.

---

## Success Criteria (How We Know It Works)

- Cache hit rate > 40% in realistic workloads
- Embedding lookup adds < 50ms latency overhead
- Total cost savings > 30% for redundant queries
- No false positives (semantically different queries should NOT match)
