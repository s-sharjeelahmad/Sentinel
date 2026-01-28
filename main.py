"""
Sentinel: Semantic AI Gateway - Reduce redundant LLM calls with intelligent caching.
"""

import logging
import time
import asyncio
import os
from datetime import datetime
from typing import Optional
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from dotenv import load_dotenv
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
from starlette.responses import Response

load_dotenv()

from cache_redis import RedisCache
from embeddings import embedding_model
from models import QueryRequest, QueryResponse, HealthResponse, MetricsResponse
import llm_provider
from llm_provider import initialize_llm_provider, cleanup_llm_provider
from query_service import QueryService
from auth import APIKeyAuth, auth_middleware
from rate_limiter import TokenBucketRateLimiter
import metrics  # Prometheus instrumentation

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

DEBUG_MODE = os.getenv("DEBUG_MODE", "false").lower() == "true"
cache = RedisCache(redis_url=None, ttl_seconds=3600, key_prefix="sentinel:cache:")

# Service layer instance - initialized during startup with injected dependencies
# Why global? Service is stateless, shared across all requests (same as cache, embedding_model)
# Alternative: FastAPI Depends() for request-scoped injection - overkill for stateless service
query_service: QueryService = None

# Auth and rate limiting - initialized during startup
# Why separate instances? Single Responsibility Principle
# - rate_limiter: Enforces request limits
# - auth: Validates API keys and integrates rate limiting
rate_limiter: TokenBucketRateLimiter = None
auth: APIKeyAuth = None

# Phase 5: Track active requests for graceful shutdown
active_requests = 0
shutdown_event: Optional[asyncio.Event] = None
shutdown_timeout_sec = 10


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: Initialize cache and LLM. Shutdown: Cleanup resources gracefully."""
    global query_service, rate_limiter, auth, shutdown_event
    
    # Phase 5: Initialize shutdown event for this async context
    shutdown_event = asyncio.Event()
    
    try:
        await cache.connect()
        await embedding_model.load()
        await initialize_llm_provider()
        
        # Initialize service layer with dependencies (Dependency Injection pattern)
        # Service doesn't create its own dependencies - they're passed in
        # Why? Testability: can inject mocks. Flexibility: can swap implementations.
        query_service = QueryService(
            cache=cache,
            embedding_model=embedding_model,
            llm_provider=llm_provider.llm_provider
        )
        
        # Initialize rate limiter with Redis (shared with cache)
        # Why share Redis? Cost efficiency, fewer connections
        # Rate limits: 100 requests/minute per API key (configurable via env)
        rate_limiter = TokenBucketRateLimiter(
            redis_client=cache.client,
            max_requests=int(os.getenv("RATE_LIMIT_REQUESTS", "100")),
            window_seconds=int(os.getenv("RATE_LIMIT_WINDOW", "60"))
        )
        
        # Initialize auth with rate limiter integration
        # Auth enforces both authentication AND rate limiting
        # API keys loaded from environment: SENTINEL_USER_KEYS, SENTINEL_ADMIN_KEY
        auth = APIKeyAuth(rate_limiter=rate_limiter)
        
        logger.info("Sentinel started")
        if DEBUG_MODE:
            logger.warning("DEBUG MODE ENABLED - Debug endpoints exposed")
        else:
            logger.info("Debug endpoints disabled")
    except (OSError, ConnectionError, ValueError) as e:
        logger.error(f"Startup failed: {e}")
        raise
    
    yield
    
    # Phase 5: Graceful shutdown - stop accepting requests and drain active connections
    logger.info("Shutting down gracefully...")
    if shutdown_event:
        shutdown_event.set()
    
    # Wait for active requests to complete (with timeout)
    start_shutdown = time.time()
    while active_requests > 0 and time.time() - start_shutdown < shutdown_timeout_sec:
        logger.info(f"Waiting for {active_requests} active request(s) to complete...")
        await asyncio.sleep(0.1)
    
    if active_requests > 0:
        logger.warning(f"Shutdown timeout: {active_requests} request(s) still active after {shutdown_timeout_sec}s")
    
    await embedding_model.close()
    await cleanup_llm_provider()
    await cache.disconnect()
    logger.info("Sentinel shut down")


app = FastAPI(
    title="Sentinel",
    description="Semantic AI Gateway with intelligent caching",
    version="0.1.0",
    lifespan=lifespan
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """
    Log request method, path, and response latency.
    
    PHASE 4: Also records Prometheus metrics for every request.
    - Increments request counter with endpoint and status labels
    - Records latency histogram
    
    PHASE 5: Track active requests for graceful shutdown.
    - Reject new requests if shutdown is in progress
    - Decrement counter when request completes
    """
    global active_requests
    
    # Phase 5: Check if shutdown in progress - reject new requests
    if shutdown_event and shutdown_event.is_set():
        logger.warning(f"Rejecting request during shutdown: {request.method} {request.url.path}")
        return JSONResponse(status_code=503, content={"error": "server_shutting_down"})
    
    active_requests += 1
    start_time = time.time()
    endpoint = request.url.path
    
    logger.info(f"→ {request.method} {endpoint}")
    
    try:
        response = await call_next(request)
    finally:
        active_requests -= 1
    
    latency_ms = (time.time() - start_time) * 1000
    latency_seconds = latency_ms / 1000
    
    logger.info(f"← {response.status_code} | {latency_ms:.1f}ms")
    
    # PHASE 4: Record request metrics (RED: Rate, Errors, Duration)
    metrics.record_request(
        endpoint=endpoint,
        status=response.status_code,
        duration_seconds=latency_seconds
    )
    
    return response


@app.middleware("http")
async def authentication_middleware(request: Request, call_next):
    """
    Authenticate requests via X-API-Key header and enforce rate limits.
    
    Middleware execution order (bottom-up):
    1. This middleware (auth + rate limit)
    2. log_requests (logging)
    3. Endpoint handler
    
    Why middleware? Runs BEFORE endpoints, protects all routes automatically.
    
    Excluded routes (public):
    - / (root health check)
    - /health (load balancer health check)
    - /metrics (Prometheus scraping)
    - /docs, /openapi.json (API documentation)
    """
    return await auth_middleware(request, call_next, auth)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Handle unhandled exceptions."""
    logger.error(f"Error: {exc}", exc_info=True)
    return JSONResponse(status_code=500, content={"error": "internal_error"})


@app.get("/", tags=["health"])
async def root() -> dict:
    """Connectivity check."""
    return {"message": "Sentinel gateway is running", "timestamp": datetime.utcnow().isoformat()}


@app.get("/health", response_model=HealthResponse, tags=["health"])
async def health_check() -> HealthResponse:
    """Health check for load balancers."""
    return HealthResponse(status="healthy", version="0.1.0")


@app.post("/v1/query", response_model=QueryResponse, tags=["cache"])
async def query(request: QueryRequest) -> QueryResponse:
    """Submit prompt with semantic caching. Returns cached response if similarity >= threshold."""
    return await query_service.execute_query(request)


@app.get("/metrics", tags=["monitoring"])
async def prometheus_metrics() -> Response:
    """Prometheus metrics endpoint (text format, Prometheus scraping standard)."""
    return Response(
        content=generate_latest(metrics.REGISTRY),
        media_type=CONTENT_TYPE_LATEST
    )


@app.get("/v1/metrics", response_model=MetricsResponse, tags=["monitoring"])
async def metrics_json() -> MetricsResponse:
    """
    Return cache statistics (legacy JSON endpoint).
    
    PHASE 4: For Prometheus metrics, use GET /metrics instead.
    This endpoint returns JSON (not Prometheus format).
    Kept for backwards compatibility and quick debugging.
    """
    stats = await cache.stats()
    return MetricsResponse(
        total_requests=stats["total_requests"],
        cache_hits=stats["cache_hits"],
        cache_misses=stats["cache_misses"],
        hit_rate_percent=stats["hit_rate_percent"],
        stored_items=stats["stored_items"],
        uptime_seconds=0
    )


# Debug endpoints (conditionally enabled via DEBUG_MODE)
if DEBUG_MODE:
    @app.get("/v1/cache/all", tags=["debug"])
    async def get_all_cached(request: Request) -> dict:
        """
        Get all cached prompts with responses and embeddings.
        
        ADMIN ONLY: Requires admin API key.
        
        Why admin-only? Debug endpoint exposes internal data.
        Security principle: Least privilege - only admins need cache visibility.
        """
        # Enforce admin role (403 if user key)
        auth.require_admin(request)
        
        try:
            all_cached = await cache.get_all_cached()
            items_list = []
            embeddings_count = 0
            
            for item in all_cached:
                embedding = item.get("embedding")
                items_list.append({
                    "prompt": item["prompt"][:100],
                    "response": item["response"][:100],
                })
                if embedding is not None:
                    embeddings_count += 1
            
            return {
                "cached_items": items_list,
                "total_cached": len(all_cached),
                "embeddings_stored": embeddings_count,
            }
        except (OSError, ConnectionError, ValueError) as e:
            logger.error(f"Error getting cached items: {e}")
            return {"error": str(e)}

    @app.delete("/v1/cache/clear", tags=["debug"])
    async def clear_cache(request: Request) -> dict:
        """
        Clear all cached entries from Redis.
        
        ADMIN ONLY: Requires admin API key.
        
        Why admin-only? Destructive operation - clears production cache.
        Security principle: Defense in depth - auth + role check.
        """
        # Enforce admin role (403 if user key)
        auth.require_admin(request)
        
        try:
            if not cache.client:
                return {"error": "Redis not connected"}
            
            pattern = f"{cache.key_prefix}*"
            cursor = 0
            deleted_count = 0
            
            while True:
                cursor, keys = await cache.client.scan(cursor, match=pattern, count=100)
                for key in keys:
                    await cache.client.delete(key)
                    deleted_count += 1
                if cursor == 0:
                    break
            
            logger.info(f"Cache cleared: {deleted_count} keys deleted")
            return {"status": "success", "deleted_keys": deleted_count}
        except (OSError, ConnectionError, RuntimeError) as e:
            logger.error(f"Error clearing cache: {e}")
            return {"error": str(e)}

    @app.post("/v1/cache/test-embeddings", tags=["debug"])
    async def test_embeddings(http_request: Request, request: QueryRequest) -> dict:
        """
        Test embedding generation and similarity calculation.
        
        ADMIN ONLY: Requires admin API key.
        
        Why admin-only? Exposes internal ML operations and cache data.
        
        Note: Two 'request' params:
        - http_request: FastAPI Request (for auth check)
        - request: QueryRequest (Pydantic model for body)
        """
        # Enforce admin role (403 if user key)
        auth.require_admin(http_request)
        
        try:
            query_embedding = await embedding_model.embed(request.prompt)
            all_cached = await cache.get_all_cached()
            
            similarity_scores = []
            for item in all_cached:
                cached_embedding = item.get("embedding")
                if cached_embedding is not None:
                    similarity = embedding_model.cosine_similarity(query_embedding, cached_embedding)
                    similarity_scores.append({
                        "cached_prompt": item["prompt"][:100],
                        "similarity": float(similarity),
                        "above_threshold": similarity >= request.similarity_threshold,
                    })
            
            return {
                "query_prompt": request.prompt,
                "cached_items": len(all_cached),
                "similarity_scores": similarity_scores,
            }
        except (ValueError, OSError, RuntimeError) as e:
            logger.error(f"Error in embedding test: {e}")
            return {"error": str(e)}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
