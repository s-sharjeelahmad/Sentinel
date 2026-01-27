"""
Sentinel API Models
Request/Response schemas using Pydantic.
"""

from pydantic import BaseModel, ConfigDict, Field


class QueryRequest(BaseModel):
    """Schema for POST /v1/query requests."""
    
    prompt: str = Field(..., min_length=1, description="User query/instruction")
    provider: str = Field(default="groq", description="LLM provider")
    model: str = Field(default="llama-3.1-8b-instant", description="Model identifier")
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(default=500, ge=1, le=4000)
    similarity_threshold: float = Field(
        default=0.75,
        ge=0.0,
        le=1.0,
        description="Minimum embedding similarity (0.0-1.0) to consider a cached response valid"
    )
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "prompt": "What is quantum computing?",
                "provider": "groq",
                "model": "llama-3.1-8b-instant",
                "temperature": 0.7,
                "max_tokens": 500,
                "similarity_threshold": 0.75
            }
        }
    )


class QueryResponse(BaseModel):
    """Schema for POST /v1/query responses."""
    
    response: str
    cache_hit: bool
    similarity_score: float | None
    matched_prompt: str | None
    provider: str
    model: str
    tokens_used: int
    latency_ms: float


class HealthResponse(BaseModel):
    """Schema for GET /health responses."""
    
    status: str
    version: str


class MetricsResponse(BaseModel):
    """Schema for GET /v1/metrics responses."""
    
    total_requests: int
    cache_hits: int
    cache_misses: int
    hit_rate_percent: float
    stored_items: int
    uptime_seconds: int
