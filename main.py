"""
Sentinel: Semantic AI Gateway
Reduces redundant LLM calls using intelligent caching.
"""

import logging
import time
import asyncio
from datetime import datetime
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

from cache_redis import RedisCache
from embeddings import embedding_model
from models import QueryRequest, QueryResponse, HealthResponse, MetricsResponse
import llm_provider
from llm_provider import initialize_llm_provider, cleanup_llm_provider

# ============================================================================
# LOGGING CONFIGURATION
# ============================================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


# ============================================================================
# FASTAPI APP SETUP
# ============================================================================

app = FastAPI(
    title="Sentinel",
    description="Semantic AI Gateway with intelligent caching",
    version="0.1.0",
)

# Global cache instance (will be initialized on startup)
cache = RedisCache(
    redis_url="redis://localhost:6379",
    ttl_seconds=3600,  # 1 hour TTL
    key_prefix="sentinel:cache:",
)


# ============================================================================
# LIFECYCLE EVENTS
# ============================================================================

@app.on_event("startup")
async def startup_event():
    """Initialize Redis, embedding model, and LLM provider on application startup."""
    try:
        await cache.connect()
        embedding_model.load()
        await initialize_llm_provider()
        logger.info("🚀 Sentinel started successfully")
    except Exception as e:
        logger.error(f"Failed to start Sentinel: {e}")
        raise


@app.on_event("shutdown")
async def shutdown_event():
    """Disconnect from Redis and LLM provider on application shutdown."""
    await cleanup_llm_provider()
    await cache.disconnect()
    logger.info("👋 Sentinel shut down gracefully")


# ============================================================================
# MIDDLEWARE
# ============================================================================

@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log incoming requests and response latency."""
    start_time = time.time()
    
    logger.info(
        f"→ {request.method} {request.url.path} | "
        f"Query: {dict(request.query_params) if request.query_params else 'none'}"
    )
    
    response = await call_next(request)
    
    latency_ms = (time.time() - start_time) * 1000
    logger.info(f"← {response.status_code} | Latency: {latency_ms:.1f}ms")
    
    return response


# ============================================================================
# EXCEPTION HANDLERS
# ============================================================================

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Catch unhandled exceptions and return proper error response."""
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "error": "internal_error",
            "message": "An unexpected error occurred",
        },
    )


# ============================================================================
# API ENDPOINTS
# ============================================================================

@app.get("/", tags=["health"])
async def root() -> dict:
    """Root endpoint for basic connectivity check."""
    return {
        "message": "Sentinel gateway is running",
        "timestamp": datetime.utcnow().isoformat(),
        "docs": "/docs",
    }


@app.get("/health", response_model=HealthResponse, tags=["health"])
async def health_check() -> HealthResponse:
    """Health check endpoint for load balancers."""
    return HealthResponse(status="healthy", version="0.1.0")


@app.post("/v1/query", response_model=QueryResponse, tags=["cache"])
async def query(request: QueryRequest) -> QueryResponse:
    """
    Submit a prompt to an LLM provider with semantic caching.
    
    Logic:
    1. Compute embedding of prompt
    2. Search cached embeddings for semantic similarity
    3. If match found (similarity >= threshold): return cached response
    4. If no match: simulate LLM call, cache result + embedding, return response
    """
    prompt = request.prompt
    threshold = request.similarity_threshold

    # Measure total latency for educational visibility
    start_time = time.perf_counter()

    # Step 1: Compute embedding of current prompt
    try:
        query_embedding = embedding_model.embed(prompt)
    except Exception as e:
        logger.error(f"Embedding error: {e}")
        query_embedding = None

    # Step 2: Try exact match first (fastest)
    cached_response, is_hit = await cache.get(prompt)
    if is_hit:
        latency_ms = (time.perf_counter() - start_time) * 1000
        logger.info(
            f"Exact Cache HIT: {prompt[:50]}... | similarity=1.00 | latency={latency_ms:.1f}ms | cost=$0.0000"
        )
        return QueryResponse(
            response=cached_response or "",
            cache_hit=True,
            similarity_score=1.0,
            matched_prompt=prompt or "",
            provider=request.provider,
            model=request.model,
            tokens_used=0,
            latency_ms=latency_ms,
        )

    # Step 3: Try semantic similarity search
    semantic_hit = None
    if query_embedding is not None:
        cached_items = await cache.get_all_cached()
        semantic_hit = embedding_model.find_similar(query_embedding, cached_items, threshold)

    if semantic_hit:
        latency_ms = (time.perf_counter() - start_time) * 1000
        similarity = semantic_hit["similarity"]
        logger.info(
            f"Semantic Cache HIT: {prompt[:50]}... → matched '{semantic_hit['prompt'][:50]}...' "
            f"| similarity={similarity:.2f} | latency={latency_ms:.1f}ms | cost=$0.0000"
        )
        return QueryResponse(
            response=semantic_hit["response"],
            cache_hit=True,
            similarity_score=similarity,
            matched_prompt=semantic_hit["prompt"],
            provider=request.provider,
            model=request.model,
            tokens_used=0,
            latency_ms=latency_ms,
        )

    # Step 4: No cache hit (exact or semantic) - call LLM provider
    try:
        logger.info(f"Cache MISS: {prompt[:50]}... | calling Groq API with model={request.model}")
        
        llm_result = await llm_provider.llm_provider.call(
            prompt=prompt,
            model=request.model,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
        )
        
        llm_response = llm_result["response"]
        cost_usd = llm_result["cost_usd"]
        latency_ms = (time.perf_counter() - start_time) * 1000
        tokens_used = llm_result["tokens_used"]
        
        # Cache the response with embedding for future semantic lookups
        await cache.set(prompt, llm_response, query_embedding)
        
        logger.info(
            f"LLM CALL (Groq): latency={latency_ms:.1f}ms | cost=${cost_usd:.6f} | "
            f"tokens={tokens_used} | prompt='{prompt[:50]}...'"
        )
        
        return QueryResponse(
            response=llm_response,
            cache_hit=False,
            similarity_score=None,
            matched_prompt=None,
            provider="groq",
            model=request.model,
            tokens_used=tokens_used,
            latency_ms=latency_ms,
        )
    
    except Exception as e:
        logger.error(f"LLM API call failed: {e}")
        return QueryResponse(
            response=f"Error: LLM provider unavailable ({str(e)})",
            cache_hit=False,
            similarity_score=None,
            matched_prompt=None,
            provider="error",
            model=request.model,
            tokens_used=0,
            latency_ms=(time.perf_counter() - start_time) * 1000,
        )


@app.get("/v1/metrics", response_model=MetricsResponse, tags=["monitoring"])
async def metrics() -> MetricsResponse:
    """Return cache performance statistics."""
    stats = await cache.stats()
    return MetricsResponse(
        total_requests=stats["total_requests"],
        cache_hits=stats["cache_hits"],
        cache_misses=stats["cache_misses"],
        hit_rate_percent=stats["hit_rate_percent"],
        stored_items=stats["stored_items"],
        uptime_seconds=0,
    )


# ============================================================================
# ENTRY POINT
# ============================================================================

if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8001,
        log_level="info",
    )
