"""
LLM Provider Interface and Implementations

This module defines the abstract LLMProvider interface and concrete implementations
for different LLM APIs (Groq, OpenAI, etc.).

Design Pattern: Strategy Pattern - enables swapping LLM providers without changing main.py
"""

import os
import time
import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any

import aiohttp

logger = logging.getLogger(__name__)


class LLMProvider(ABC):
    """
    Abstract base class for LLM providers.
    
    Defines the interface that all LLM implementations must follow.
    This enables easy swapping between Groq, OpenAI, Anthropic, etc.
    """
    
    @abstractmethod
    async def call(
        self,
        prompt: str,
        model: str = "default",
        temperature: float = 0.7,
        max_tokens: int = 500,
    ) -> Dict[str, Any]:
        """
        Call the LLM API.
        
        Args:
            prompt: User query/input
            model: Model identifier (e.g., "llama-3.1-8b-instant")
            temperature: Sampling temperature (0.0 = deterministic, 1.0 = random)
            max_tokens: Maximum tokens in response
            
        Returns:
            {
                "response": str,              # LLM's text response
                "tokens_used": int,           # Total tokens (input + output)
                "cost_usd": float,            # Cost in USD
                "latency_ms": float,          # Total latency in milliseconds
                "provider": str,              # Provider name (e.g., "groq")
                "model": str,                 # Model used
                "input_tokens": int,          # Input token count
                "output_tokens": int,         # Output token count
            }
        """
        pass


class GroqProvider(LLMProvider):
    """
    Groq API Provider Implementation
    
    Groq is a fast LLM inference API with generous free tier:
    - Free tier: 20,000 tokens/min
    - Models: llama-3.1-8b-instant, LLaMA2, etc.
    - Latency: ~500-1500ms (very fast!)
    
    Cost: ~$0.0005 per 1K tokens (competitive pricing)
    """
    
    # Groq API Configuration
    GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
    
    # Pricing (as of 2026)
    INPUT_COST_PER_1K_TOKENS = 0.00005    # $0.05 per 1M tokens
    OUTPUT_COST_PER_1K_TOKENS = 0.00015   # $0.15 per 1M tokens
    
    # Retry Configuration
    MAX_RETRIES = 3
    INITIAL_BACKOFF_SEC = 1.0  # Start with 1 second
    
    # Request Configuration
    REQUEST_TIMEOUT_SEC = 10.0
    POOL_TIMEOUT_SEC = 30.0
    
    def __init__(self):
        """Initialize Groq provider with API key from environment."""
        self.api_key = os.getenv("GROQ_API_KEY")
        if not self.api_key:
            logger.warning(
                "GROQ_API_KEY environment variable not set. "
                "Groq API calls will fail. Get key from https://console.groq.com"
            )
        
        self.session: Optional[aiohttp.ClientSession] = None
        logger.info("✅ GroqProvider initialized")
    
    async def connect(self):
        """Create aiohttp session for connection pooling."""
        if self.session is None:
            self.session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(
                    total=self.POOL_TIMEOUT_SEC,
                    connect=10,
                    sock_read=10
                )
            )
            logger.info("✅ Groq connection pool created")
    
    async def disconnect(self):
        """Close aiohttp session."""
        if self.session:
            await self.session.close()
            logger.info("✅ Groq connection pool closed")
    
    async def call(
        self,
        prompt: str,
        model: str = "llama-3.1-8b-instant",  # Free tier model
        temperature: float = 0.7,
        max_tokens: int = 500,
    ) -> Dict[str, Any]:
        """
        Call Groq API with error handling and retry logic.
        
        Implements exponential backoff for rate limiting (429 errors).
        """
        if not self.api_key:
            raise RuntimeError(
                "GROQ_API_KEY not configured. "
                "Set environment variable: export GROQ_API_KEY=your_key"
            )
        
        # Ensure session is initialized
        if self.session is None:
            await self.connect()
        
        start_time = time.perf_counter()
        
        # Retry loop with exponential backoff
        backoff_sec = self.INITIAL_BACKOFF_SEC
        
        for attempt in range(self.MAX_RETRIES):
            try:
                response_data = await self._call_groq_api(
                    prompt=prompt,
                    model=model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                
                latency_ms = (time.perf_counter() - start_time) * 1000
                
                # Extract usage info
                usage = response_data.get("usage", {})
                input_tokens = usage.get("prompt_tokens", 0)
                output_tokens = usage.get("completion_tokens", 0)
                total_tokens = usage.get("total_tokens", 0)
                
                # Calculate cost
                cost_usd = self._calculate_cost(input_tokens, output_tokens)
                
                # Extract response text
                response_text = response_data["choices"][0]["message"]["content"]
                
                logger.info(
                    f"✅ Groq API call successful | "
                    f"model={model} | "
                    f"tokens_in={input_tokens} tokens_out={output_tokens} | "
                    f"cost=${cost_usd:.6f} | "
                    f"latency={latency_ms:.0f}ms"
                )
                
                return {
                    "response": response_text,
                    "tokens_used": total_tokens,
                    "cost_usd": cost_usd,
                    "latency_ms": latency_ms,
                    "provider": "groq",
                    "model": model,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                }
            
            except aiohttp.ClientSSLError as e:
                logger.error(f"❌ SSL error calling Groq: {e}")
                raise
            
            except aiohttp.ClientConnectorError as e:
                logger.error(f"❌ Connection error (attempt {attempt+1}/{self.MAX_RETRIES}): {e}")
                if attempt < self.MAX_RETRIES - 1:
                    await asyncio.sleep(backoff_sec)
                    backoff_sec *= 2  # Exponential backoff
                else:
                    raise
            
            except asyncio.TimeoutError as e:
                logger.error(f"❌ Timeout (attempt {attempt+1}/{self.MAX_RETRIES}): {e}")
                if attempt < self.MAX_RETRIES - 1:
                    await asyncio.sleep(backoff_sec)
                    backoff_sec *= 2
                else:
                    raise
            
            except Exception as e:
                logger.error(f"❌ Unexpected error: {type(e).__name__}: {e}")
                raise
        
        raise RuntimeError("Max retries exceeded")
    
    async def _call_groq_api(
        self,
        prompt: str,
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> Dict[str, Any]:
        """
        Make actual HTTP request to Groq API.
        
        Raises:
            - aiohttp.ClientError: Network/connection errors
            - asyncio.TimeoutError: Request timeout
            - ValueError: API error response (4xx/5xx)
        """
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        
        payload = {
            "model": model,
            "messages": [
                {"role": "user", "content": prompt}
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        
        try:
            async with self.session.post(
                self.GROQ_API_URL,
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=self.REQUEST_TIMEOUT_SEC),
            ) as response:
                
                # Handle HTTP errors
                if response.status == 401:
                    raise ValueError("Invalid API key (401 Unauthorized)")
                elif response.status == 429:
                    raise ValueError("Rate limited (429 Too Many Requests)")
                elif response.status >= 400:
                    error_text = await response.text()
                    raise ValueError(f"HTTP {response.status}: {error_text}")
                
                # Parse response
                response_json = await response.json()
                
                # Validate response structure
                if "choices" not in response_json or not response_json["choices"]:
                    raise ValueError("Invalid response format: missing choices")
                
                return response_json
        
        except aiohttp.ClientConnectorError as e:
            logger.error(f"Network connectivity error: {e}")
            raise
        except asyncio.TimeoutError:
            logger.error(f"Request timed out after {self.REQUEST_TIMEOUT_SEC}s")
            raise
    
    def _calculate_cost(self, input_tokens: int, output_tokens: int) -> float:
        """
        Calculate cost based on token usage.
        
        Groq pricing model:
        - Input: $0.00005 per 1K tokens
        - Output: $0.00015 per 1K tokens
        
        Example:
        - 100 input tokens + 50 output tokens
        - Cost = (100/1000)*0.00005 + (50/1000)*0.00015 = $0.000010
        """
        input_cost = (input_tokens / 1000) * self.INPUT_COST_PER_1K_TOKENS
        output_cost = (output_tokens / 1000) * self.OUTPUT_COST_PER_1K_TOKENS
        return input_cost + output_cost


# Global instance (will be initialized in main.py)
llm_provider: Optional[LLMProvider] = None


async def initialize_llm_provider() -> LLMProvider:
    """Factory function to create and initialize LLM provider."""
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
