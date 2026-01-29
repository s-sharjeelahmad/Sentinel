"""
Query Service - Orchestrates semantic cache lookup and LLM fallback.

RESPONSIBILITY:
    Execute the cache → semantic search → LLM fallback workflow.
    Coordinate between cache, embeddings, and LLM provider.
    Return QueryResponse with appropriate metadata.

WHY THIS EXISTS (Backend Principle: Separation of Concerns):
    - API layer (main.py) handles HTTP: routing, validation, serialization
    - Service layer (this file) handles business logic: orchestration, decisions
    - Data layer (cache_redis.py) handles persistence
    
    Mixing these = hard to test, hard to change, hard to reuse.

TESTABILITY:
    With service layer, you can test business logic WITHOUT:
    - Starting FastAPI server
    - Making real HTTP requests
    - Mocking HTTP framework internals
    
    Just: mock_cache = Mock(), service = QueryService(mock_cache, ...), result = service.execute()

INTERVIEW QUESTION:
    "Why not keep this logic in the endpoint?"
    
    Answer: Violates Single Responsibility Principle. The endpoint would be doing:
    1. HTTP handling (FastAPI's job)
    2. Request validation (Pydantic's job)  
    3. Business orchestration (this service's job)
    4. Response serialization (FastAPI's job)
    
    Result: 80-line endpoint that's impossible to unit test.
    
    Better: Thin controller delegates to service. Controller = 10 lines. Service = testable.
"""

import logging
import time
import asyncio
from typing import Optional

from cache_redis import RedisCache
from embeddings import EmbeddingModel
from llm_provider import LLMProvider
from models import QueryRequest, QueryResponse
from exceptions import EmbeddingServiceError, LLMProviderError
import metrics  # Prometheus instrumentation

logger = logging.getLogger(__name__)


class QueryService:
    """
    Service layer for query execution with semantic caching.
    
    Encapsulates the core business logic:
    1. Try exact cache match (O(1) Redis GET)
    2. Try semantic cache match (O(n) embedding similarity scan)
    3. On miss: call LLM and store result
    
    DEPENDENCY INJECTION PATTERN:
        Service receives dependencies via constructor, not global imports.
        
        Why?
        - Testability: Inject mocks in tests
        - Flexibility: Swap implementations without changing service code
        - Explicitness: Clear what this service needs to function
        
        Trade-off: More verbose (must pass dependencies) vs implicit globals.
        For production systems, explicitness > convenience.
    """
    
    def __init__(
        self,
        cache: RedisCache,
        embedding_model: EmbeddingModel,
        llm_provider: LLMProvider
    ):
        """
        Initialize service with injected dependencies.
        
        Interview note: This is CONSTRUCTOR INJECTION, most common DI pattern.
        Alternatives: setter injection, interface injection, service locator (anti-pattern).
        """
        self.cache = cache
        self.embedding_model = embedding_model
        self.llm_provider = llm_provider
    
    async def execute_query(self, request: QueryRequest) -> QueryResponse:
        """
        Execute query with semantic cache fallback to LLM.
        
        FLOW (unchanged from V1 - this is a refactor, not a rewrite):
        1. Generate embedding for query
        2. Check exact cache hit (Redis key lookup)
        3. If miss: check semantic similarity against all cached embeddings
        4. If still miss: call LLM, cache result
        
        BACKEND CONCEPT: Orchestration Pattern
            Service coordinates multiple dependencies (cache, embeddings, LLM).
            Each dependency has single responsibility.
            Service doesn't know HOW they work, only WHAT they do.
            
            This is the "Hollywood Principle": Don't call us, we'll call you.
            Service calls dependencies, not the other way around.
        
        CONCURRENCY NOTE (for Phase 3):
            Current behavior: If two identical requests arrive simultaneously,
            both will call LLM (race condition = 2x cost).
            
            Interview question: "How would you prevent duplicate LLM calls?"
            Answer: Distributed lock in Redis (Phase 3 will add this).
        """
        prompt = request.prompt
        threshold = request.similarity_threshold
        start_time = time.perf_counter()
        
        # Step 1: Generate embedding for semantic search
        # Why try-except? Embedding service can fail (network, API key, rate limit)
        # Graceful degradation: If embeddings fail, we can still do exact match
        # TRADE-OFF: Availability > semantic matching (fail-open for embeddings)
        try:
            query_embedding = await self.embedding_model.embed(prompt)
        except EmbeddingServiceError as e:
            # Expected failure mode - log and degrade gracefully
            logger.warning(f"Embedding service unavailable, falling back to exact cache only: {e}")
            query_embedding = None
        
        # Step 2: Exact cache hit check
        # Why check exact first? Performance.
        # - Exact match: O(1) Redis GET (~1ms)
        # - Semantic match: O(n) scan of all cached items (~50ms with 100 items)
        cached_response, is_hit = await self.cache.get(prompt)
        if is_hit:
            latency_ms = (time.perf_counter() - start_time) * 1000
            logger.info(f"Cache HIT (exact): similarity=1.00 | latency={latency_ms:.1f}ms")
            
            # PHASE 4: Record exact cache hit metric
            metrics.record_cache_hit("exact")
            
            return QueryResponse(
                response=cached_response or "",
                cache_hit=True,
                similarity_score=1.0,
                matched_prompt=prompt or "",
                provider=request.provider,
                model=request.model,
                tokens_used=0,
                latency_ms=latency_ms
            )
        
        # Step 3: Semantic cache hit check
        # Trade-off: O(n) scan is expensive, but avoids LLM cost on similar queries
        # Example: "What is Python?" vs "What's Python?" → 0.95 similarity → cache hit
        semantic_hit = None
        if query_embedding is not None:
            cached_items = await self.cache.get_all_cached()
            semantic_hit = self.embedding_model.find_similar(
                query_embedding, cached_items, threshold
            )
        
        if semantic_hit:
            latency_ms = (time.perf_counter() - start_time) * 1000
            similarity = semantic_hit["similarity"]
            logger.info(f"Cache HIT (semantic): similarity={similarity:.2f} | latency={latency_ms:.1f}ms")
            
            # PHASE 4: Record semantic cache hit metric
            metrics.record_cache_hit("semantic")
            
            return QueryResponse(
                response=semantic_hit["response"],
                cache_hit=True,
                similarity_score=similarity,
                matched_prompt=semantic_hit["prompt"],
                provider=request.provider,
                model=request.model,
                tokens_used=0,
                latency_ms=latency_ms
            )
        
        # Step 4: Cache MISS - call LLM (expensive path)
        # This is where real cost happens: external API call, money spent
        # Interview question: "What happens if LLM API is down?"
        # Current answer: Exception propagates, user sees error. Phase 5 will add circuit breaker.
        
        # PHASE 3: CONCURRENCY SAFETY
        # Problem: Two identical requests arrive simultaneously
        #   → Both see cache miss → Both call LLM → 2x cost (race condition)
        # Solution: Distributed lock (first request locks, calls LLM; second waits for cache)
        
        logger.info(f"Cache MISS: attempting lock for LLM call")
        
        # PHASE 4: Record cache miss metric
        metrics.record_cache_hit("miss")
        
        # Try to acquire distributed lock
        # Lock key = hash(prompt + model) ensures identical requests share same lock
        # TTL = 30s prevents deadlock if this process crashes mid-LLM-call
        lock_acquired = await self.cache.acquire_lock(prompt, request.model, ttl_seconds=30)
        
        if lock_acquired:
            # We got the lock - we're responsible for calling LLM
            # This is the "fast path" - first request for this prompt
            logger.info(f"Lock acquired, calling LLM")
            
            # PHASE 4: Track active lock
            metrics.increment_active_locks()
            
            try:
                llm_result = await self.llm_provider.call(
                    prompt=prompt,
                    model=request.model,
                    temperature=request.temperature,
                    max_tokens=request.max_tokens
                )
                
                llm_response = llm_result["response"]
                cost_usd = llm_result["cost_usd"]
                latency_ms = (time.perf_counter() - start_time) * 1000
                tokens_used = llm_result["tokens_used"]
                
                # PHASE 4: Record LLM cost metric
                metrics.record_llm_cost(
                    provider=llm_result.get("provider", "groq"),
                    model=request.model,
                    cost_usd=cost_usd
                )
                
                # Store in cache for future queries (and for waiting requests)
                # Note: Stores both response AND embedding for semantic search
                await self.cache.set(prompt, llm_response, query_embedding)
                logger.info(f"LLM call: latency={latency_ms:.1f}ms | cost=${cost_usd:.6f} | tokens={tokens_used}")
                
                return QueryResponse(
                    response=llm_response,
                    cache_hit=False,
                    similarity_score=None,
                    matched_prompt=None,
                    provider="groq",
                    model=request.model,
                    tokens_used=tokens_used,
                    latency_ms=latency_ms
                )
            
            finally:
                # Always release lock, even if LLM call fails
                # Why finally? Ensures lock released on exception (prevents deadlock)
                # If release fails, TTL will expire lock anyway (graceful degradation)
                
                # PHASE 4: Decrement active lock gauge
                metrics.decrement_active_locks()
                
                await self.cache.release_lock(prompt, request.model)
                logger.info(f"Lock released")
        
        else:
            # Lock already held by another request
            # This is the "slow path" - we arrived while another request is calling LLM
            # Strategy: Poll cache with exponential backoff until result appears
            logger.info(f"Lock held by another request, polling cache")
            
            # Polling parameters
            max_wait_seconds = 30  # Match lock TTL
            poll_interval_ms = 100  # Start with 100ms
            max_poll_interval_ms = 2000  # Cap at 2s
            
            elapsed = 0
            while elapsed < max_wait_seconds:
                # Wait before polling (exponential backoff)
                await asyncio.sleep(poll_interval_ms / 1000)
                elapsed += poll_interval_ms / 1000
                
                # Check if cache now has the result
                cached_response, is_hit = await self.cache.get(prompt)
                if is_hit:
                    latency_ms = (time.perf_counter() - start_time) * 1000
                    logger.info(f"Cache populated by other request: latency={latency_ms:.1f}ms (waited {elapsed:.1f}s)")
                    
                    # PHASE 4: This is effectively an exact cache hit (waited for lock holder)
                    # Already recorded cache miss earlier, so don't double-count
                    
                    return QueryResponse(
                        response=cached_response or "",
                        cache_hit=True,
                        similarity_score=1.0,
                        matched_prompt=prompt,
                        provider=request.provider,
                        model=request.model,
                        tokens_used=0,
                        latency_ms=latency_ms
                    )
                
                # Exponential backoff: double interval, cap at max
                poll_interval_ms = min(poll_interval_ms * 2, max_poll_interval_ms)
            
            # Timeout: Other request took too long or failed
            # Fallback: Try calling LLM ourselves (lock may have expired)
            logger.warning(f"Polling timeout after {max_wait_seconds}s, attempting LLM call")
            
            # Retry LLM call (lock should have expired by now)
            llm_result = await self.llm_provider.call(
                prompt=prompt,
                model=request.model,
                temperature=request.temperature,
                max_tokens=request.max_tokens
            )
            
            llm_response = llm_result["response"]
            cost_usd = llm_result["cost_usd"]
            latency_ms = (time.perf_counter() - start_time) * 1000
            tokens_used = llm_result["tokens_used"]
            
            # PHASE 4: Record LLM cost metric (timeout fallback path)
            metrics.record_llm_cost(
                provider=llm_result.get("provider", "groq"),
                model=request.model,
                cost_usd=cost_usd
            )
            
            await self.cache.set(prompt, llm_response, query_embedding)
            logger.info(f"LLM call (after timeout): latency={latency_ms:.1f}ms | cost=${cost_usd:.6f} | tokens={tokens_used}")
            
            return QueryResponse(
                response=llm_response,
                cache_hit=False,
                similarity_score=None,
                matched_prompt=None,
                provider="groq",
                model=request.model,
                tokens_used=tokens_used,
                latency_ms=latency_ms
            )
        
        # NOTE: No except block here - let exceptions propagate to API layer
        # Why? Service layer is transport-agnostic (doesn't know about HTTP).
        # API layer (main.py) catches exceptions and maps to HTTP status codes.
        #
        # Possible exceptions from this method:
        #   - LLMProviderError: LLM API failed (maps to 502 Bad Gateway)
        #   - CircuitBreakerOpenError: Circuit breaker open (maps to 503)
        #   - CacheError: Redis failed (maps to 503)
        #
        # INTERVIEW POINT:
        #   "Why not catch exceptions here?"
        #   Answer: "Service layer should be transport-agnostic. HTTP semantics
        #   (status codes, response format) belong in the API layer only.
        #   This enables the same service to work with HTTP, gRPC, CLI, etc."
