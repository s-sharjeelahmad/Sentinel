"""
Domain exceptions for Sentinel service layer.

WHY THIS FILE EXISTS:
    Service layer must be transport-agnostic (doesn't know about HTTP).
    API layer owns HTTP semantics (status codes, headers, response format).
    
    Exceptions define the SERVICE/API BOUNDARY:
    - Service raises domain exceptions
    - API catches and maps to HTTP status codes
    
INTERVIEW POINT:
    "Why separate exceptions from HTTP responses?"
    Answer: "Service layer should work in any transport (HTTP, gRPC, CLI).
    HTTP details belong in the API layer only."

BACKEND PRINCIPLE: Separation of Concerns
    - Domain logic: What failed and why (exception type + message)
    - Transport logic: How to communicate that to client (status code)
"""


class SentinelError(Exception):
    """Base exception for all Sentinel domain errors."""
    pass


class LLMProviderError(SentinelError):
    """
    LLM API call failed (Groq, OpenAI, etc.).
    
    Maps to: 502 Bad Gateway
    Why: Upstream service (LLM API) returned error or timeout.
    """
    pass


class CircuitBreakerOpenError(SentinelError):
    """
    Circuit breaker is open - LLM API is failing repeatedly.
    
    Maps to: 503 Service Unavailable
    Why: System is protecting itself from cascading failure.
    Client should: Retry with exponential backoff.
    """
    pass


class EmbeddingServiceError(SentinelError):
    """
    Embedding API call failed (Jina, OpenAI, etc.).
    
    Maps to: 502 Bad Gateway
    Why: Upstream embedding service returned error or timeout.
    
    GRACEFUL DEGRADATION:
    Service layer catches this internally and falls back to exact cache only.
    Only raised if both semantic search AND exact cache fail.
    """
    pass


class CacheError(SentinelError):
    """
    Redis cache operation failed.
    
    Maps to: 503 Service Unavailable
    Why: Cache is down, system can't guarantee cost-effective operation.
    
    TRADE-OFF:
    Could fail-open (serve expensive LLM calls), but that defeats the purpose.
    Failing closed forces ops team to fix cache quickly.
    """
    pass


class ShutdownInProgressError(SentinelError):
    """
    Server is shutting down gracefully.
    
    Maps to: 503 Service Unavailable
    Why: System is draining active requests, not accepting new ones.
    
    NOTE: This is raised by middleware (API layer), not service layer.
    Included here for completeness.
    """
    pass
