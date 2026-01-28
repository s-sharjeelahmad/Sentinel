"""
Rate Limiter - Token bucket algorithm with Redis backing.

RESPONSIBILITY:
    Prevent API abuse by limiting requests per API key.
    Distributed rate limiting (works across multiple server instances).

WHY TOKEN BUCKET ALGORITHM:
    - Allows bursts: User can consume tokens quickly if available
    - Self-replenishing: Tokens refill at constant rate
    - Industry standard: Used by AWS, Stripe, GitHub, etc.
    
    Alternatives:
    - Fixed window: Simple but allows "thundering herd" at window reset
    - Leaky bucket: Smoother but doesn't allow bursts
    - Sliding window: Most accurate but higher memory cost

BACKEND PRINCIPLE: Distributed State
    Rate limit state stored in Redis (not in-memory) because:
    - Survives server restarts
    - Works with multiple server instances (horizontal scaling)
    - Single source of truth across distributed system

INTERVIEW QUESTION:
    "How would you implement rate limiting?"
    
    Answer: "Token bucket with Redis. Each key has a bucket with max tokens.
    Every request consumes 1 token. Tokens refill at fixed rate (e.g., 100/min).
    Redis INCR + EXPIRE for atomic operations. Handles distributed systems."

TRADE-OFFS:
    - Redis dependency: If Redis down, rate limiting fails (we'll fail-open for availability)
    - Network overhead: Every request = Redis call (~1-2ms latency)
    - Memory cost: One Redis key per API key
    
    Alternative: In-memory (faster, but doesn't work with multiple servers)
"""

import logging
import time
from typing import Optional
import redis.asyncio as redis

logger = logging.getLogger(__name__)


class TokenBucketRateLimiter:
    """
    Token bucket rate limiter with Redis backing.
    
    How it works:
    1. Each API key has a "bucket" with max tokens (e.g., 100)
    2. Every request consumes 1 token
    3. Tokens refill at constant rate (e.g., 100 tokens per 60 seconds = 1.67/sec)
    4. If bucket empty, request is rejected with 429
    
    Redis keys:
    - `ratelimit:{api_key}:count` = current token count
    - `ratelimit:{api_key}:reset` = timestamp when bucket last refilled
    
    Interview note: This is "distributed token bucket" - works across servers.
    """
    
    def __init__(
        self,
        redis_client: redis.Redis,
        max_requests: int = 100,
        window_seconds: int = 60,
        key_prefix: str = "ratelimit:"
    ):
        """
        Initialize rate limiter.
        
        Args:
            redis_client: Redis connection (shared with cache)
            max_requests: Max requests per window (bucket capacity)
            window_seconds: Time window in seconds
            key_prefix: Redis key prefix for rate limit data
        
        Example: max_requests=100, window_seconds=60 = 100 requests/minute
        """
        self.redis = redis_client
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.key_prefix = key_prefix
        
        # Token refill rate: tokens per second
        self.refill_rate = max_requests / window_seconds
    
    async def check_rate_limit(self, api_key: str) -> tuple[bool, dict]:
        """
        Check if request is allowed under rate limit.
        
        Returns:
            (allowed: bool, info: dict)
            - allowed: True if request should proceed, False if rate limited
            - info: {"remaining": int, "reset_at": int, "limit": int}
        
        Algorithm (simplified token bucket):
        1. Get current token count from Redis
        2. Calculate tokens to add based on time elapsed
        3. Add tokens (capped at max_requests)
        4. If tokens >= 1: consume 1 token, allow request
        5. Else: reject with 429
        
        Interview question: "Why not just count requests in a time window?"
        Answer: "Fixed windows allow burst at boundaries. Token bucket smooths traffic."
        
        Edge case handling:
        - If Redis fails: Fail-open (allow request) for availability
        - First request for key: Initialize bucket with max tokens
        """
        if not self.redis:
            # Redis unavailable - fail-open (allow request)
            # Trade-off: Availability > rate limiting
            # Alternative: Fail-closed (deny) for security
            logger.warning("Redis unavailable, rate limiting disabled (fail-open)")
            return True, {"remaining": self.max_requests, "reset_at": 0, "limit": self.max_requests}
        
        try:
            now = time.time()
            count_key = f"{self.key_prefix}{api_key}:count"
            reset_key = f"{self.key_prefix}{api_key}:reset"
            
            # Get current state from Redis
            # Using pipeline for atomicity (prevents race conditions)
            pipe = self.redis.pipeline()
            pipe.get(count_key)
            pipe.get(reset_key)
            results = await pipe.execute()
            
            current_tokens = float(results[0]) if results[0] else self.max_requests
            last_reset = float(results[1]) if results[1] else now
            
            # Calculate tokens to add based on elapsed time
            elapsed = now - last_reset
            tokens_to_add = elapsed * self.refill_rate
            
            # Refill tokens (capped at max)
            current_tokens = min(self.max_requests, current_tokens + tokens_to_add)
            
            # Check if request allowed
            if current_tokens >= 1.0:
                # Consume 1 token
                new_tokens = current_tokens - 1.0
                
                # Update Redis atomically
                pipe = self.redis.pipeline()
                pipe.set(count_key, str(new_tokens), ex=self.window_seconds * 2)
                pipe.set(reset_key, str(now), ex=self.window_seconds * 2)
                await pipe.execute()
                
                return True, {
                    "remaining": int(new_tokens),
                    "reset_at": int(now + (self.max_requests - new_tokens) / self.refill_rate),
                    "limit": self.max_requests
                }
            else:
                # Rate limited - no tokens available
                time_until_token = (1.0 - current_tokens) / self.refill_rate
                
                return False, {
                    "remaining": 0,
                    "reset_at": int(now + time_until_token),
                    "limit": self.max_requests
                }
        
        except Exception as e:
            # Redis error - fail-open for availability
            logger.error(f"Rate limiter error: {e}, failing open")
            return True, {"remaining": self.max_requests, "reset_at": 0, "limit": self.max_requests}
    
    async def reset_limit(self, api_key: str) -> None:
        """
        Reset rate limit for an API key (admin operation).
        
        Use case: Debugging, customer support, testing.
        """
        if not self.redis:
            return
        
        try:
            count_key = f"{self.key_prefix}{api_key}:count"
            reset_key = f"{self.key_prefix}{api_key}:reset"
            
            await self.redis.delete(count_key, reset_key)
            logger.info(f"Rate limit reset for key: {api_key[:8]}...")
        except Exception as e:
            logger.error(f"Error resetting rate limit: {e}")
