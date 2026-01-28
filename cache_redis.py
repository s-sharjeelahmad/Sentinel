"""Sentinel Redis Cache Layer - Persistent LLM response cache."""

import logging
import os
import hashlib
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
        self.lock_prefix = "sentinel:lock:"  # Prefix for distributed locks
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
    def _make_lock_key(self, prompt: str, model: str) -> str:
        """
        Generate deterministic lock key from prompt and model.
        
        Why hash? 
        - Prompts can be long (>1KB) → inefficient as Redis key
        - Hash = fixed size (64 chars), deterministic, collision-resistant
        
        Why SHA256?
        - Fast, deterministic, sufficient collision resistance for this use case
        - Alternative: MD5 (faster but weaker), UUID (not deterministic)
        
        Lock key format: "sentinel:lock:{sha256_hash}"
        Example: "sentinel:lock:a3f5c9..."
        
        Interview question: "Why hash the prompt instead of using it directly?"
        Answer: "Prompts are variable length, can be very long. Hash gives fixed-size,
        Redis-friendly key. Same prompt+model always → same hash → same lock."
        """
        # Combine prompt and model to ensure different models don't share locks
        # Example: "What is Python?" with gpt-4 vs llama should have different locks
        lock_input = f"{prompt}:{model}"
        hash_digest = hashlib.sha256(lock_input.encode()).hexdigest()
        return f"{self.lock_prefix}{hash_digest}"
    
    async def acquire_lock(self, prompt: str, model: str, ttl_seconds: int = 30) -> bool:
        """
        Attempt to acquire distributed lock for LLM call.
        
        Why distributed lock?
        - Prevents duplicate LLM calls when identical requests arrive concurrently
        - Example: 2 requests for "What is Python?" arrive within 1ms
          → Without lock: both call LLM (2x cost)
          → With lock: first acquires lock + calls LLM, second waits for cache
        
        Algorithm: Redis SET NX EX (atomic operation)
        - NX: Set if Not eXists (only succeeds if key doesn't exist)
        - EX: Set EXpiry (TTL in seconds)
        - Atomic: Both operations happen together, no race condition
        
        Args:
            prompt: User prompt (used to generate lock key)
            model: LLM model name (different models = different locks)
            ttl_seconds: Lock TTL (default 30s)
        
        Returns:
            True if lock acquired (this request should call LLM)
            False if lock already held (another request is calling LLM)
        
        TTL Reasoning:
        - 30s = typical LLM call time (5-15s) + safety margin
        - Too short: Lock expires while LLM still running → duplicate calls
        - Too long: If holder crashes, next request waits too long
        - Trade-off: 30s balances safety vs latency
        
        Failure mode:
        - If Redis down: Returns False (fail-open, allow request to proceed)
        - Alternative: Return True = both requests call LLM (2x cost)
        - Decision: Fail-open = prefer availability over preventing duplicates
        
        Interview question: "What if lock holder crashes before releasing?"
        Answer: "TTL auto-expires lock after 30s. Next request can then proceed.
        This prevents deadlocks but means potential 30s wait on crash."
        
        Interview question: "Why not use Redlock (multi-Redis algorithm)?"
        Answer: "Redlock adds complexity, requires multiple Redis instances.
        For this use case (cost optimization, not critical correctness),
        single Redis with TTL is sufficient. Trade-off: simplicity vs safety."
        """
        if not self.client:
            logger.warning("Redis unavailable, skipping lock (fail-open)")
            return False  # Fail-open: Skip locking, allow duplicate calls
        
        try:
            lock_key = self._make_lock_key(prompt, model)
            
            # SET NX EX: Atomic set-if-not-exists with expiry
            # Returns True if key was set (lock acquired)
            # Returns False if key already exists (lock held by another request)
            acquired = await self.client.set(
                lock_key,
                "locked",  # Value doesn't matter, key existence is the lock
                nx=True,   # Only set if key doesn't exist (NX = Not eXists)
                ex=ttl_seconds  # Expire after TTL seconds (EX = EXpiry)
            )
            
            if acquired:
                logger.info(f"Lock acquired: {lock_key[:50]}... (TTL={ttl_seconds}s)")
            else:
                logger.info(f"Lock already held: {lock_key[:50]}... (waiting for other request)")
            
            return bool(acquired)
        
        except Exception as e:
            logger.error(f"Lock acquisition error: {e}, failing open")
            return False  # Fail-open on errors
    
    async def release_lock(self, prompt: str, model: str) -> None:
        """
        Release distributed lock after LLM call completes.
        
        Why release explicitly?
        - Frees lock immediately (don't wait for TTL)
        - Allows next waiting request to proceed faster
        - Good citizenship: hold locks for minimum time
        
        Failure handling:
        - If delete fails: Lock will expire via TTL (graceful degradation)
        - Not critical: worst case = next request waits for TTL
        
        Interview question: "What if release fails?"
        Answer: "Lock expires via TTL anyway. Release is optimization for
        faster unlock, not required for correctness. Fail gracefully."
        """
        if not self.client:
            return
        
        try:
            lock_key = self._make_lock_key(prompt, model)
            deleted = await self.client.delete(lock_key)
            
            if deleted:
                logger.info(f"Lock released: {lock_key[:50]}...")
            else:
                logger.debug(f"Lock already expired: {lock_key[:50]}...")
        
        except Exception as e:
            logger.error(f"Lock release error: {e} (will expire via TTL)")
    
    async def disconnect(self) -> None:
        """Close Redis connection."""
        if self.client:
            await self.client.close()
            logger.info("Redis connection closed")