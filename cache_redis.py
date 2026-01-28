"""Sentinel Redis Cache Layer - Persistent LLM response cache."""

import logging
import os
from typing import Optional
import redis.asyncio as redis
import json
import numpy as np

logger = logging.getLogger(__name__)


class RedisCache:
    """Redis-backed cache for LLM responses with semantic embeddings and TTL."""
    
    def __init__(self, redis_url: str | None = None, ttl_seconds: int = 3600, key_prefix: str = "sentinel:cache:") -> None:
        """Initialize Redis cache with URL, TTL, and key prefix."""
        self.redis_url = redis_url or os.getenv("REDIS_URL")
        if not self.redis_url:
            raise ValueError("Redis URL required. Set REDIS_URL env var or pass redis_url parameter.")
        self.ttl_seconds = ttl_seconds
        self.key_prefix = key_prefix
        self.client: Optional[redis.Redis] = None
        self._hits = 0
        self._misses = 0
    
    async def connect(self) -> None:
        """Establish Redis connection."""
        try:
            self.client = await redis.from_url(self.redis_url, encoding="utf-8", decode_responses=True)
            if self.client:
                await self.client.ping()
            logger.info(f"Connected to Redis")
        except Exception as e:
            logger.error(f"Redis connection failed: {e}")
            raise
    
    
    def _make_key(self, prompt: str) -> str:
        """Create Redis key from prompt with prefix."""
        return f"{self.key_prefix}{prompt}"
    
    async def get(self, prompt: str) -> tuple[Optional[str], bool]:
        """Retrieve cached response. Returns (response, is_hit)."""
        if not self.client:
            self._misses += 1
            return None, False
        
        try:
            key = self._make_key(prompt)
            response = await self.client.get(key)
            if response:
                self._hits += 1
                return response, True
            self._misses += 1
            return None, False
        except Exception as e:
            logger.error(f"Redis GET error: {e}")
            self._misses += 1
            return None, False
    
    async def set(self, prompt: str, response: str, embedding: Optional[np.ndarray] = None) -> None:
        """Store prompt-response pair with TTL and optional embedding vector."""
        if not self.client:
            return
        
        try:
            key = self._make_key(prompt)
            await self.client.setex(key, self.ttl_seconds, response)
            
            if embedding is not None:
                embedding_key = f"{key}:embedding"
                embedding_json = json.dumps(embedding.tolist())
                await self.client.setex(embedding_key, self.ttl_seconds, embedding_json)
        except Exception as e:
            logger.error(f"Redis SET error: {e}")
    
    async def get_all_cached(self) -> list[dict]:
        """Retrieve all cached prompts with responses and embeddings for semantic search."""
        if not self.client:
            return []
        
        try:
            cursor = 0
            pattern = f"{self.key_prefix}*"
            cached_items = []
            
            while True:
                cursor, keys = await self.client.scan(cursor, match=pattern, count=100)
                
                for key in keys:
                    if key.endswith(":embedding"):
                        continue
                    
                    response = await self.client.get(key)
                    if not response:
                        continue
                    
                    prompt = key[len(self.key_prefix):]
                    embedding_key = f"{key}:embedding"
                    embedding_json = await self.client.get(embedding_key)
                    
                    if embedding_json:
                        embedding = np.array(json.loads(embedding_json), dtype=np.float32)
                        cached_items.append({"prompt": prompt, "response": response, "embedding": embedding})
                
                if cursor == 0:
                    break
            
            return cached_items
        except Exception as e:
            logger.error(f"Error retrieving cached items: {e}")
            return []
    
    async def stats(self) -> dict:
        """Return cache statistics: total requests, hits, misses, hit rate, stored items."""
        total = self._hits + self._misses
        hit_rate = (self._hits / total * 100) if total > 0 else 0
        
        stored_items = 0
        if self.client:
            try:
                pattern = f"{self.key_prefix}*"
                cursor = 0
                while True:
                    cursor, keys = await self.client.scan(cursor, match=pattern, count=100)
                    stored_items += len(keys)
                    if cursor == 0:
                        break
            except Exception as e:
                logger.error(f"Error counting Redis keys: {e}")
        
        return {"total_requests": total, "cache_hits": self._hits, "cache_misses": self._misses, "hit_rate_percent": round(hit_rate, 2), "stored_items": stored_items}
    
    async def clear(self) -> int:
        """Clear all cached entries. Returns number of keys deleted."""
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
            
            logger.info(f"Cleared {deleted} cache entries")
            return deleted
        except Exception as e:
            logger.error(f"Error clearing cache: {e}")
            return 0
