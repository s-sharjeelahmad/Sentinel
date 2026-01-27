"""
Sentinel Redis Cache Layer
Persistent, multi-process cache using Redis.
"""

import logging
import os
from typing import Optional
import redis.asyncio as redis
import json
import numpy as np

logger = logging.getLogger(__name__)


class RedisCache:
    """
    Redis-backed cache for LLM responses.
    
    Improvements over in-memory cache:
    - Persists across server restarts
    - Shared across multiple processes/servers
    - Built-in eviction (LRU when maxmemory reached)
    - TTL support (auto-expire old responses)
    """
    
    def __init__(
        self,
        redis_url: str | None = None,
        ttl_seconds: int = 3600,
        key_prefix: str = "sentinel:cache:",
    ) -> None:
        """
        Initialize Redis cache.
        
        Args:
            redis_url: Redis connection string (default: localhost:6379)
            ttl_seconds: Time-to-live for cached entries (default: 1 hour)
            key_prefix: Prefix for all keys to avoid collisions (default: "sentinel:cache:")
        """
        # Prefer explicit argument, otherwise read from environment
        self.redis_url = redis_url or os.getenv("REDIS_URL")
        if not self.redis_url:
            raise ValueError(
                "Redis URL is required. Set REDIS_URL environment variable or pass redis_url parameter."
            )
        self.ttl_seconds = ttl_seconds
        self.key_prefix = key_prefix
        self.client: Optional[redis.Redis] = None
        
        # Metrics tracking (in-memory, reset on restart)
        self._hits = 0
        self._misses = 0
    
    async def connect(self) -> None:
        """Establish connection to Redis server."""
        try:
            self.client = await redis.from_url(
                self.redis_url,
                encoding="utf-8",
                decode_responses=True,  # Auto-decode bytes to strings
            )
            # Test connection
            if self.client:
                await self.client.ping()
            logger.info(f"✅ Connected to Redis at {self.redis_url}")
        except Exception as e:
            logger.error(f"❌ Failed to connect to Redis: {e}")
            raise
    
    async def disconnect(self) -> None:
        """Close Redis connection gracefully."""
        if self.client:
            await self.client.close()
            logger.info("Redis connection closed")
    
    def _make_key(self, prompt: str) -> str:
        """
        Create Redis key from prompt.
        
        Format: "sentinel:cache:{prompt}"
        
        Example:
            "What is AI?" → "sentinel:cache:What is AI?"
        """
        return f"{self.key_prefix}{prompt}"
    
    async def get(self, prompt: str) -> tuple[Optional[str], bool]:
        """
        Retrieve cached response if prompt exists.
        
        Args:
            prompt: The user's query
            
        Returns:
            (response_text, is_hit)
            - response_text: Cached response or None if not found
            - is_hit: True if found in cache, False otherwise
        
        Example:
            response, hit = await cache.get("What is AI?")
            if hit:
                print(f"Cache hit! Response: {response}")
            else:
                print("Cache miss, need to call LLM")
        """
        if not self.client:
            logger.warning("Redis client not connected, skipping cache lookup")
            self._misses += 1
            return None, False
        
        try:
            key = self._make_key(prompt)
            response = await self.client.get(key)
            
            if response:
                self._hits += 1
                logger.debug(f"Cache HIT: {prompt[:50]}...")
                return response, True
            else:
                self._misses += 1
                logger.debug(f"Cache MISS: {prompt[:50]}...")
                return None, False
                
        except Exception as e:
            logger.error(f"Redis GET error: {e}")
            self._misses += 1
            return None, False
    
    async def set(self, prompt: str, response: str, embedding: Optional[np.ndarray] = None) -> None:
        """
        Store a prompt-response pair in cache with TTL and optional embedding.
        
        Args:
            prompt: The user's query
            response: The LLM's response
            embedding: Optional embedding vector for semantic search
        
        Example:
            await cache.set("What is AI?", "AI is the simulation of...", embedding_vector)
        """
        if not self.client:
            logger.warning("Redis client not connected, skipping cache write")
            return
        
        try:
            key = self._make_key(prompt)
            
            # Store response
            await self.client.setex(
                key,
                self.ttl_seconds,  # TTL in seconds
                response,
            )
            
            # Store embedding if provided (for semantic search)
            if embedding is not None:
                embedding_key = f"{key}:embedding"
                embedding_json = json.dumps(embedding.tolist())  # Convert numpy array to list
                await self.client.setex(
                    embedding_key,
                    self.ttl_seconds,
                    embedding_json,
                )
            
            logger.debug(f"Cached response for: {prompt[:50]}... (TTL: {self.ttl_seconds}s)")
            
        except Exception as e:
            logger.error(f"Redis SET error: {e}")
    
    async def get_all_cached(self) -> list[dict]:
        """
        Retrieve all cached prompts with responses and embeddings.
        
        Used for semantic search to find similar cached responses.
        
        Returns:
            List of dicts: [{"prompt": str, "response": str, "embedding": np.ndarray}, ...]
            
        Example:
            cached_items = await cache.get_all_cached()
            # Use for semantic similarity search
        """
        if not self.client:
            return []
        
        try:
            # Find all keys matching cache pattern
            cursor = 0
            pattern = f"{self.key_prefix}*"
            cached_items = []
            
            while True:
                cursor, keys = await self.client.scan(cursor, match=pattern, count=100)
                
                for key in keys:
                    # Skip embedding keys (we handle them specially)
                    if key.endswith(":embedding"):
                        continue
                    
                    # Get response
                    response = await self.client.get(key)
                    if not response:
                        continue
                    
                    # Extract prompt from key (remove prefix)
                    prompt = key[len(self.key_prefix):]
                    
                    # Try to get embedding
                    embedding_key = f"{key}:embedding"
                    embedding_json = await self.client.get(embedding_key)
                    
                    if embedding_json:
                        embedding = np.array(json.loads(embedding_json))
                        cached_items.append({
                            "prompt": prompt,
                            "response": response,
                            "embedding": embedding,
                        })
                
                if cursor == 0:
                    break
            
            return cached_items
            
        except Exception as e:
            logger.error(f"Error retrieving cached items: {e}")
            return []
    
    async def stats(self) -> dict:
        """
        Return cache statistics.
        
        Returns:
            dict with metrics:
            - total_requests: Hit + miss count
            - cache_hits: Number of cache hits
            - cache_misses: Number of cache misses
            - hit_rate_percent: Cache hit percentage
            - stored_items: Number of keys in Redis (approximate)
        """
        total = self._hits + self._misses
        hit_rate = (self._hits / total * 100) if total > 0 else 0
        
        # Get approximate count of cached items
        stored_items = 0
        if self.client:
            try:
                # Count keys matching our prefix
                # Note: This is O(N) operation, use with caution in production
                cursor = 0
                pattern = f"{self.key_prefix}*"
                while True:
                    cursor, keys = await self.client.scan(cursor, match=pattern, count=100)
                    stored_items += len(keys)
                    if cursor == 0:
                        break
            except Exception as e:
                logger.error(f"Error counting Redis keys: {e}")
        
        return {
            "total_requests": total,
            "cache_hits": self._hits,
            "cache_misses": self._misses,
            "hit_rate_percent": round(hit_rate, 2),
            "stored_items": stored_items,
        }
    
    async def clear(self) -> int:
        """
        Clear all cached entries (for testing/debugging).
        
        Returns:
            Number of keys deleted
        """
        if not self.client:
            return 0
        
        try:
            pattern = f"{self.key_prefix}*"
            cursor = 0
            deleted = 0
            
            while True:
                cursor, keys = await self.client.scan(cursor, match=pattern, count=100)
                if keys:
                    deleted += await self.client.delete(*keys)
                if cursor == 0:
                    break
            
            logger.info(f"Cleared {deleted} cached entries")
            return deleted
            
        except Exception as e:
            logger.error(f"Error clearing cache: {e}")
            return 0
