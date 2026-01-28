"""LLM Provider Interface and Implementations - Strategy pattern for swappable LLM APIs."""

import os
import time
import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any

import aiohttp

logger = logging.getLogger(__name__)


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
    REQUEST_TIMEOUT_SEC = 10.0
    POOL_TIMEOUT_SEC = 30.0
    
    def __init__(self):
        """Initialize Groq provider with API key from environment."""
        self.api_key = os.getenv("GROQ_API_KEY")
        if not self.api_key:
            logger.warning("GROQ_API_KEY not set. Get key from https://console.groq.com")
        
        self.session: Optional[aiohttp.ClientSession] = None
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
        """Call Groq API with exponential backoff retry logic for rate limiting."""
        if not self.api_key:
            raise RuntimeError("GROQ_API_KEY not set. export GROQ_API_KEY=your_key")
        
        if self.session is None:
            await self.connect()
        
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
                raise
            
            except aiohttp.ClientConnectorError as e:
                logger.error(f"Connection error (attempt {attempt+1}/{self.MAX_RETRIES}): {e}")
                if attempt < self.MAX_RETRIES - 1:
                    await asyncio.sleep(backoff_sec)
                    backoff_sec *= 2
                else:
                    raise
            
            except asyncio.TimeoutError as e:
                logger.error(f"Timeout (attempt {attempt+1}/{self.MAX_RETRIES}): {e}")
                if attempt < self.MAX_RETRIES - 1:
                    await asyncio.sleep(backoff_sec)
                    backoff_sec *= 2
                else:
                    raise
            
            except Exception as e:
                logger.error(f"Error: {type(e).__name__}: {e}")
                raise
        
        raise RuntimeError("Max retries exceeded")
    
    async def _call_groq_api(self, prompt: str, model: str, temperature: float, max_tokens: int) -> Dict[str, Any]:
        """Make HTTP request to Groq API."""
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        payload = {"model": model, "messages": [{"role": "user", "content": prompt}], "temperature": temperature, "max_tokens": max_tokens}
        
        try:
            async with self.session.post(self.GROQ_API_URL, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=self.REQUEST_TIMEOUT_SEC)) as response:
                if response.status == 401:
                    raise ValueError("Invalid API key (401)")
                elif response.status == 429:
                    raise ValueError("Rate limited (429)")
                elif response.status >= 400:
                    error_text = await response.text()
                    raise ValueError(f"HTTP {response.status}: {error_text}")
                
                response_json = await response.json()
                if "choices" not in response_json or not response_json["choices"]:
                    raise ValueError("Invalid response: missing choices")
                
                return response_json
        except aiohttp.ClientConnectorError as e:
            logger.error(f"Network error: {e}")
            raise
        except asyncio.TimeoutError:
            logger.error(f"Request timeout after {self.REQUEST_TIMEOUT_SEC}s")
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
