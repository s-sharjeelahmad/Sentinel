"""
Sentinel: Semantic AI Gateway - Reduce redundant LLM calls with intelligent caching.
"""

import logging
import time
import asyncio
import os
from datetime import datetime
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from dotenv import load_dotenv

load_dotenv()

from cache_redis import RedisCache
from embeddings import embedding_model
from models import QueryRequest, QueryResponse, HealthResponse, MetricsResponse
import llm_provider
from llm_provider import initialize_llm_provider, cleanup_llm_provider

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

DEBUG_MODE = os.getenv("DEBUG_MODE", "false").lower() == "true"
cache = RedisCache(redis_url=None, ttl_seconds=3600, key_prefix="sentinel:cache:")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: Initialize cache and LLM. Shutdown: Cleanup resources."""
    try:
        await cache.connect()
        await embedding_model.load()
        await initialize_llm_provider()
        
        logger.info("Sentinel started")
        if DEBUG_MODE:
            logger.warning("DEBUG MODE ENABLED - Debug endpoints exposed")
        else:
            logger.info("Debug endpoints disabled")
    except Exception as e:
        logger.error(f"Startup failed: {e}")
        raise
    
    yield
    
    await embedding_model.close()
    await cleanup_llm_provider()
    await cache.disconnect()
    logger.info("Sentinel shut down")


app = FastAPI(title="Sentinel", description="Semantic AI Gateway with intelligent caching", version="0.1.0", lifespan=lifespan)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log request method, path, and response latency."""
    start_time = time.time()
    logger.info(f"→ {request.method} {request.url.path}")
    response = await call_next(request)
    latency_ms = (time.time() - start_time) * 1000
    logger.info(f"← {response.status_code} | {latency_ms:.1f}ms")
    return response


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Handle unhandled exceptions."""
    logger.error(f"Error: {exc}", exc_info=True)
    return JSONResponse(status_code=500, content={"error": "internal_error", "message": "An unexpected error occurred"})


@app.get("/", tags=["health"])
async def root() -> dict:
    """Connectivity check."""
    return {"message": "Sentinel gateway is running", "timestamp": datetime.utcnow().isoformat(), "docs": "/docs"}


@app.get("/health", response_model=HealthResponse, tags=["health"])
async def health_check() -> HealthResponse:
    """Health check for load balancers."""
    return HealthResponse(status="healthy", version="0.1.0")


@app.post("/v1/query", response_model=QueryResponse, tags=["cache"])
async def query(request: QueryRequest) -> QueryResponse:
    """Submit prompt with semantic caching. Returns cached response if similarity >= threshold."""
    prompt = request.prompt
    threshold = request.similarity_threshold
    start_time = time.perf_counter()

    try:
        query_embedding = await embedding_model.embed(prompt)
    except Exception as e:
        logger.error(f"Embedding error: {e}")
        query_embedding = None

    cached_response, is_hit = await cache.get(prompt)
    if is_hit:
        latency_ms = (time.perf_counter() - start_time) * 1000
        logger.info(f"Cache HIT (exact): similarity=1.00 | latency={latency_ms:.1f}ms")
        return QueryResponse(response=cached_response or "", cache_hit=True, similarity_score=1.0, matched_prompt=prompt or "", provider=request.provider, model=request.model, tokens_used=0, latency_ms=latency_ms)

    semantic_hit = None
    if query_embedding is not None:
        cached_items = await cache.get_all_cached()
        semantic_hit = embedding_model.find_similar(query_embedding, cached_items, threshold)

    if semantic_hit:
        latency_ms = (time.perf_counter() - start_time) * 1000
        similarity = semantic_hit["similarity"]
        logger.info(f"Cache HIT (semantic): similarity={similarity:.2f} | latency={latency_ms:.1f}ms")
        return QueryResponse(response=semantic_hit["response"], cache_hit=True, similarity_score=similarity, matched_prompt=semantic_hit["prompt"], provider=request.provider, model=request.model, tokens_used=0, latency_ms=latency_ms)

    try:
        logger.info(f"Cache MISS: calling LLM")
        
        llm_result = await llm_provider.llm_provider.call(prompt=prompt, model=request.model, temperature=request.temperature, max_tokens=request.max_tokens)
        
        llm_response = llm_result["response"]
        cost_usd = llm_result["cost_usd"]
        latency_ms = (time.perf_counter() - start_time) * 1000
        tokens_used = llm_result["tokens_used"]
        
        await cache.set(prompt, llm_response, query_embedding)
        logger.info(f"LLM call: latency={latency_ms:.1f}ms | cost=${cost_usd:.6f} | tokens={tokens_used}")
        
        return QueryResponse(response=llm_response, cache_hit=False, similarity_score=None, matched_prompt=None, provider="groq", model=request.model, tokens_used=tokens_used, latency_ms=latency_ms)
    
    except Exception as e:
        logger.error(f"LLM call failed: {e}")
        latency_ms = (time.perf_counter() - start_time) * 1000
        return QueryResponse(response=f"Error: {str(e)}", cache_hit=False, similarity_score=None, matched_prompt=None, provider="error", model=request.model, tokens_used=0, latency_ms=latency_ms)


@app.get("/v1/metrics", response_model=MetricsResponse, tags=["monitoring"])
async def metrics() -> MetricsResponse:
    """Return cache statistics."""
    stats = await cache.stats()
    return MetricsResponse(total_requests=stats["total_requests"], cache_hits=stats["cache_hits"], cache_misses=stats["cache_misses"], hit_rate_percent=stats["hit_rate_percent"], stored_items=stats["stored_items"], uptime_seconds=0)


# Debug endpoints (conditionally enabled via DEBUG_MODE)
if DEBUG_MODE:
    @app.get("/v1/cache/all", tags=["debug"])
    async def get_all_cached() -> dict:
    """
    Get all cached prompts with their responses and embeddings.
    
    Useful for debugging semantic matching.
    
    Returns:
        dict with:
        - cached_items: List of cached prompts
        - total_cached: Number of cached items
        - embeddings_stored: Number of embeddings
    """
    try:
        all_cached = await cache.get_all_cached()
        
        items_list = []
        embeddings_count = 0
        
        for item in all_cached:
            embedding = item.get("embedding")
            items_list.append({
                "prompt": item["prompt"][:100],  # Truncate for readability
                "response": item["response"][:100],
                "embedding_type": str(type(embedding).__name__),
                "embedding_shape": str(embedding.shape) if hasattr(embedding, 'shape') else "N/A",
                "embedding_dtype": str(embedding.dtype) if hasattr(embedding, 'dtype') else "N/A",
            })
            if embedding is not None:
                embeddings_count += 1
        
        return {
            "cached_items": items_list,
            "total_cached": len(all_cached),
            "embeddings_stored": embeddings_count,
        }
    except Exception as e:
        logger.error(f"Error getting cached items: {e}")
        return {"error": str(e)}

    @app.delete("/v1/cache/clear", tags=["debug"])
    async def clear_cache() -> dict:
    """
    Clear all cached entries from Redis.
    
    WARNING: This deletes all cached responses and embeddings.
    """
    try:
        if not cache.client:
            return {"error": "Redis not connected"}
        
        # Find and delete all keys with our prefix
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
        
        logger.info(f"🗑️ Cache cleared: {deleted_count} keys deleted")
        return {
            "status": "success",
            "deleted_keys": deleted_count,
            "message": "Cache cleared successfully"
        }
    except Exception as e:
        logger.error(f"Error clearing cache: {e}")
        return {"error": str(e)}

    @app.post("/v1/cache/test-embeddings", tags=["debug"])
async def test_embeddings(request: QueryRequest) -> dict:
    """
    Debug endpoint: Test embedding generation and similarity calculation.
    
    Shows:
    - Query embedding vector
    - All cached embeddings
    - Similarity scores for each cached item
    """
    try:
        # Get query embedding
        query_embedding = await embedding_model.embed(request.prompt)
        
        # Get all cached items
        all_cached = await cache.get_all_cached()
        
        # Calculate similarity with each cached item
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
            "query_embedding_dim": int(query_embedding.shape[0]),
            "query_embedding_type": str(type(query_embedding).__name__),
            "cached_items_count": len(all_cached),
            "similarity_threshold": request.similarity_threshold,
            "similarity_scores": similarity_scores,
        }
    except Exception as e:
        logger.error(f"Error in embedding test: {e}")
        return {"error": str(e)}
else:
    logger.info("Debug endpoints disabled (DEBUG_MODE=false)")

# ============================================================================
# ENTRY POINT
# ============================================================================

if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        log_level="info",
    )
