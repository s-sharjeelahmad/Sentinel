"""Sentinel API Models - Request/Response schemas using Pydantic."""

from pydantic import BaseModel, ConfigDict, Field


class QueryRequest(BaseModel):
    """POST /v1/query request schema."""
    
    prompt: str = Field(..., min_length=1)
    provider: str = Field(default="groq")
    model: str = Field(default="llama-3.1-8b-instant")
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(default=500, ge=1, le=4000)
    similarity_threshold: float = Field(default=0.75, ge=0.0, le=1.0, description="Min embedding similarity for cache match")
    
    model_config = ConfigDict(
        json_schema_extra={"example": {"prompt": "What is quantum computing?", "provider": "groq", "model": "llama-3.1-8b-instant", "temperature": 0.7, "max_tokens": 500, "similarity_threshold": 0.75}}
    )


class QueryResponse(BaseModel):
    """POST /v1/query response schema."""
    
    response: str
    cache_hit: bool
    similarity_score: float | None
    matched_prompt: str | None
    provider: str
    model: str
    tokens_used: int
    latency_ms: float


class HealthResponse(BaseModel):
    """GET /health response schema."""
    
    status: str
    version: str


class MetricsResponse(BaseModel):
    """GET /v1/metrics response schema."""
    
    total_requests: int
    cache_hits: int
    cache_misses: int
    hit_rate_percent: float
    stored_items: int
    uptime_seconds: int
