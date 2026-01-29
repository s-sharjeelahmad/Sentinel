"""LLM Provider Interface and Implementations - Strategy pattern for swappable LLM APIs."""

import os
import time
import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any
from enum import Enum

import aiohttp

from exceptions import LLMProviderError, CircuitBreakerOpenError

logger = logging.getLogger(__name__)


class CircuitBreakerState(Enum):
    """Circuit breaker state machine."""
    CLOSED = "closed"          # Normal operation
    OPEN = "open"              # Failing - reject all requests
    HALF_OPEN = "half_open"    # Testing - allow 1 request


class CircuitBreaker:
    """Simple circuit breaker for LLM API calls."""
    
    def __init__(self, failure_threshold: int = 5, cooldown_sec: int = 60):
        """Initialize circuit breaker."""
        self.failure_threshold = failure_threshold
        self.cooldown_sec = cooldown_sec
        self.state = CircuitBreakerState.CLOSED
        self.failure_count = 0
        self.last_failure_time = None
    
    async def call(self, coro):
        """Execute coroutine with circuit breaker protection."""
        if self.state == CircuitBreakerState.OPEN:
            # Check if cooldown period has elapsed
            if self.last_failure_time and time.time() - self.last_failure_time > self.cooldown_sec:
                self.state = CircuitBreakerState.HALF_OPEN
                logger.info("Circuit breaker: HALF_OPEN - attempting recovery")
            else:
                # BOUNDARY: Raise domain exception, not HTTP response
                # API layer maps this to 503 Service Unavailable
                raise CircuitBreakerOpenError("Circuit breaker OPEN - LLM API unavailable")
        
        try:
            result = await coro
            
            # Success - close circuit
            if self.state == CircuitBreakerState.HALF_OPEN:
                self.state = CircuitBreakerState.CLOSED
                self.failure_count = 0
                logger.info("Circuit breaker: CLOSED - recovered")
            
            return result
        
        except Exception as e:
            self.failure_count += 1
            self.last_failure_time = time.time()
            
            if self.failure_count >= self.failure_threshold:
                self.state = CircuitBreakerState.OPEN
                logger.error(f"Circuit breaker: OPEN - {self.failure_count} consecutive failures")
            
            raise


class LLMProvider(ABC):
    """Abstract base class for LLM providers. Enables swapping between Groq, OpenAI, Anthropic, etc."""
    
    @abstractmethod
    async def call(self, prompt: str, model: str = "default", temperature: float = 0.7, max_tokens: int = 500) -> Dict[str, Any]:
        """Call LLM API. Returns dict with response, tokens_used, cost_usd, latency_ms, provider, model, input_tokens, output_tokens."""
        pass


class GroqProvider(LLMProvider):
    """Groq API Provider - Fast LLM inference with generous free tier (20,000 tokens/min)."""
    
    GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
    INPUT_COST_PER_1K_TOKENS = 0.00005
    OUTPUT_COST_PER_1K_TOKENS = 0.00015
    MAX_RETRIES = 3
    INITIAL_BACKOFF_SEC = 1.0
    REQUEST_TIMEOUT_SEC = 30.0  # Phase 5: Increased to 30s (from 10s) to avoid timeout on slow requests
    POOL_TIMEOUT_SEC = 30.0
    
    def __init__(self):
        """Initialize Groq provider with API key from environment and circuit breaker."""
        self.api_key = os.getenv("GROQ_API_KEY")
        if not self.api_key:
            logger.warning("GROQ_API_KEY not set. Get key from https://console.groq.com")
        
        self.session: Optional[aiohttp.ClientSession] = None
        self.circuit_breaker = CircuitBreaker(failure_threshold=5, cooldown_sec=60)  # Phase 5: Circuit breaker
        logger.info("GroqProvider initialized")
    
    async def connect(self):
        """Create aiohttp session for connection pooling."""
        if self.session is None:
            self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.POOL_TIMEOUT_SEC, connect=10, sock_read=10))
            logger.info("Groq connection pool created")
    
    async def disconnect(self):
        """Close aiohttp session."""
        if self.session:
            await self.session.close()
            logger.info("Groq connection pool closed")
    
    async def call(self, prompt: str, model: str = "llama-3.1-8b-instant", temperature: float = 0.7, max_tokens: int = 500) -> Dict[str, Any]:
        """Call Groq API with exponential backoff retry logic and circuit breaker protection."""
        if not self.api_key:
            # CONFIGURATION ERROR: This should be caught at startup, not here
            # But if it happens, raise domain exception
            raise LLMProviderError("GROQ_API_KEY not set. export GROQ_API_KEY=your_key")
        
        if self.session is None:
            await self.connect()
        
        # Phase 5: Wrap with circuit breaker - fail fast if LLM is known to be broken
        return await self.circuit_breaker.call(
            self._call_with_retries(prompt=prompt, model=model, temperature=temperature, max_tokens=max_tokens)
        )
    
    async def _call_with_retries(self, prompt: str, model: str, temperature: float, max_tokens: int) -> Dict[str, Any]:
        """Call Groq API with exponential backoff retry logic."""
        
        start_time = time.perf_counter()
        backoff_sec = self.INITIAL_BACKOFF_SEC
        
        for attempt in range(self.MAX_RETRIES):
            try:
                response_data = await self._call_groq_api(prompt=prompt, model=model, temperature=temperature, max_tokens=max_tokens)
                
                latency_ms = (time.perf_counter() - start_time) * 1000
                usage = response_data.get("usage", {})
                input_tokens = usage.get("prompt_tokens", 0)
                output_tokens = usage.get("completion_tokens", 0)
                total_tokens = usage.get("total_tokens", 0)
                cost_usd = self._calculate_cost(input_tokens, output_tokens)
                response_text = response_data["choices"][0]["message"]["content"]
                
                logger.info(f"Groq API call | model={model} | tokens={total_tokens} | cost=${cost_usd:.6f}")
                
                return {"response": response_text, "tokens_used": total_tokens, "cost_usd": cost_usd, "latency_ms": latency_ms, "provider": "groq", "model": model, "input_tokens": input_tokens, "output_tokens": output_tokens}
            
            except aiohttp.ClientSSLError as e:
                logger.error(f"SSL error: {e}")
                # SSL errors are not retryable - fail immediately
                raise LLMProviderError(f"SSL error connecting to LLM API: {e}") from e
            
            except aiohttp.ClientConnectorError as e:
                logger.error(f"Connection error (attempt {attempt+1}/{self.MAX_RETRIES}): {e}")
                if attempt < self.MAX_RETRIES - 1:
                    await asyncio.sleep(backoff_sec)
                    backoff_sec *= 2
                else:
                    # Exhausted retries - wrap in domain exception
                    raise LLMProviderError(f"LLM API unreachable after {self.MAX_RETRIES} attempts: {e}") from e
            
            except asyncio.TimeoutError as e:
                logger.error(f"Timeout (attempt {attempt+1}/{self.MAX_RETRIES}): {e}")
                if attempt < self.MAX_RETRIES - 1:
                    await asyncio.sleep(backoff_sec)
                    backoff_sec *= 2
                else:
                    # Exhausted retries - wrap in domain exception
                    raise LLMProviderError(f"LLM API timeout after {self.MAX_RETRIES} attempts (>{self.REQUEST_TIMEOUT_SEC}s each)") from e
            
            except Exception as e:
                # Unexpected errors (ValueError from API response parsing, etc.)
                logger.error(f"Error: {type(e).__name__}: {e}")
                raise LLMProviderError(f"LLM API call failed: {e}") from e
        
        # Should never reach here, but if we do, it's a provider error
        raise LLMProviderError("Max retries exceeded")
    
    async def _call_groq_api(self, prompt: str, model: str, temperature: float, max_tokens: int) -> Dict[str, Any]:
        """Make HTTP request to Groq API."""
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        payload = {"model": model, "messages": [{"role": "user", "content": prompt}], "temperature": temperature, "max_tokens": max_tokens}
        
        try:
            async with self.session.post(self.GROQ_API_URL, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=self.REQUEST_TIMEOUT_SEC)) as response:
                if response.status == 401:
                    # Configuration error - API key is wrong
                    raise LLMProviderError("Invalid API key (401)")
                elif response.status == 429:
                    # Rate limit - let retry logic handle this
                    raise LLMProviderError("Rate limited (429)")
                elif response.status >= 400:
                    error_text = await response.text()
                    # Upstream error - map to domain exception
                    raise LLMProviderError(f"HTTP {response.status}: {error_text}")
                
                response_json = await response.json()
                if "choices" not in response_json or not response_json["choices"]:
                    # Malformed response
                    raise LLMProviderError("Invalid response: missing choices")
                
                return response_json
        except aiohttp.ClientConnectorError as e:
            logger.error(f"Network error: {e}")
            # Re-raise as-is, retry logic will catch and wrap it
            raise
        except asyncio.TimeoutError:
            logger.error(f"Request timeout after {self.REQUEST_TIMEOUT_SEC}s")
            # Re-raise as-is, retry logic will catch and wrap it
            raise
    
    def _calculate_cost(self, input_tokens: int, output_tokens: int) -> float:
        """Calculate cost from token usage. Groq: $0.00005 per 1K input, $0.00015 per 1K output."""
        input_cost = (input_tokens / 1000) * self.INPUT_COST_PER_1K_TOKENS
        output_cost = (output_tokens / 1000) * self.OUTPUT_COST_PER_1K_TOKENS
        return input_cost + output_cost


llm_provider: Optional[LLMProvider] = None


async def initialize_llm_provider() -> LLMProvider:
    """Create and initialize LLM provider."""
    global llm_provider
    
    llm_provider = GroqProvider()
    await llm_provider.connect()
    return llm_provider


async def cleanup_llm_provider():
    """Cleanup LLM provider resources."""
    global llm_provider
    
    if llm_provider:
        await llm_provider.disconnect()
        llm_provider = None
