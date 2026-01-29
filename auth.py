"""
Authentication Middleware - API key validation and authorization.

RESPONSIBILITY:
    Validate X-API-Key header on incoming requests.
    Enforce role-based access (user vs admin keys).
    Integrate with rate limiter to prevent abuse.

WHY MIDDLEWARE PATTERN:
    - Runs BEFORE endpoint handlers (early rejection)
    - Cross-cutting concern (all endpoints need auth)
    - DRY: Write once, protects all routes automatically
    - Fails fast: Invalid requests never reach business logic

BACKEND PRINCIPLE: Trust Boundary
    This is the FIRST line of defense. Everything after this point can
    assume the request is authenticated and authorized.
    
    Layers:
    1. Middleware: Authentication + rate limiting (this file)
    2. Endpoint: Request validation (Pydantic)
    3. Service: Business logic (QueryService)
    
    Each layer validates different concerns.

INTERVIEW QUESTION:
    "Where would you implement authentication in a web service?"
    
    Answer: "Middleware, not in endpoints. Middleware runs once per request,
    automatically protects all routes. Centralized = less bugs, easier auditing."

SECURITY NOTES:
    - API keys in headers (not URL params - prevents logging exposure)
    - Constant-time comparison (prevents timing attacks)
    - Keys truncated in logs (prevents leakage)
    - Admin keys for debug endpoints only
"""

import logging
import os
import secrets
from typing import Optional
from fastapi import Request, HTTPException, status
from fastapi.responses import JSONResponse

from rate_limiter import TokenBucketRateLimiter

logger = logging.getLogger(__name__)


class APIKeyAuth:
    """
    API key authentication with role-based access control.
    
    Supports two key types:
    - USER keys: Can access /v1/query, /health, /metrics
    - ADMIN keys: Can access everything including /v1/cache/* debug endpoints
    
    Keys stored in environment variables (production: use secret manager like AWS Secrets Manager)
    - SENTINEL_USER_KEYS: Comma-separated list of user API keys
    - SENTINEL_ADMIN_KEY: Single admin key (more privileged)
    
    Interview note: This is "API key auth", simplest form.
    Alternatives: OAuth2, JWT, mTLS (mutual TLS), HMAC signing.
    Trade-off: Simple but no key rotation, revocation, or granular permissions.
    """
    
    def __init__(self, rate_limiter: Optional[TokenBucketRateLimiter] = None):
        """
        Initialize auth with optional rate limiter.
        
        Why optional rate limiter?
        - Auth and rate limiting are separate concerns
        - Can use auth without rate limiting (testing)
        - Dependency injection pattern
        """
        self.rate_limiter = rate_limiter
        
        # Load API keys from environment
        # Production: Use AWS Secrets Manager, HashiCorp Vault, etc.
        self.user_keys = self._load_user_keys()
        self.admin_key = os.getenv("SENTINEL_ADMIN_KEY")
        
        if not self.user_keys and not self.admin_key:
            logger.warning("No API keys configured. Set SENTINEL_USER_KEYS or SENTINEL_ADMIN_KEY")
        else:
            logger.info(f"Loaded {len(self.user_keys)} user keys + admin key")
    
    def _load_user_keys(self) -> set[str]:
        """Load user API keys from environment variable."""
        keys_str = os.getenv("SENTINEL_USER_KEYS", "")
        if not keys_str:
            return set()
        
        # Parse comma-separated keys
        keys = {key.strip() for key in keys_str.split(",") if key.strip()}
        return keys
    
    def _validate_key(self, api_key: str) -> tuple[bool, str]:
        """
        Validate API key and return (is_valid, role).
        
        Returns:
            (True, "admin") if admin key
            (True, "user") if user key
            (False, "") if invalid
        
        Security: Use constant-time comparison to prevent timing attacks
        (secrets.compare_digest is constant-time)
        """
        # Check admin key first (higher privilege)
        if self.admin_key and secrets.compare_digest(api_key, self.admin_key):
            return True, "admin"
        
        # Check user keys
        for user_key in self.user_keys:
            if secrets.compare_digest(api_key, user_key):
                return True, "user"
        
        return False, ""
    
    async def authenticate_request(self, request: Request) -> dict:
        """
        Authenticate request via X-API-Key header.
        
        Returns:
            {"api_key": str, "role": str} if authenticated
        
        Raises:
            HTTPException(401) if missing/invalid key
            HTTPException(429) if rate limited
        
        Called by middleware on every request.
        
        Backend concept: Fail-fast
        - Invalid auth = immediate rejection (no business logic executed)
        - Saves resources, prevents abuse
        """
        # Extract API key from header
        api_key = request.headers.get("X-API-Key")
        
        if not api_key:
            client_host = request.client.host if request.client else "unknown"
            logger.warning(f"Missing API key: {client_host} {request.method} {request.url.path}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing X-API-Key header",
                headers={"WWW-Authenticate": "ApiKey"}
            )
        
        # Validate key
        is_valid, role = self._validate_key(api_key)
        
        if not is_valid:
            client_host = request.client.host if request.client else "unknown"
            logger.warning(f"Invalid API key: {api_key[:8]}... from {client_host}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid API key",
                headers={"WWW-Authenticate": "ApiKey"}
            )
        
        # Check rate limit (if configured)
        if self.rate_limiter:
            allowed, rate_info = await self.rate_limiter.check_rate_limit(api_key)
            
            if not allowed:
                logger.warning(f"Rate limited: {api_key[:8]}... ({rate_info['remaining']} remaining)")
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Rate limit exceeded",
                    headers={
                        "X-RateLimit-Limit": str(rate_info["limit"]),
                        "X-RateLimit-Remaining": str(rate_info["remaining"]),
                        "X-RateLimit-Reset": str(rate_info["reset_at"]),
                        "Retry-After": str(rate_info["reset_at"])
                    }
                )
            
            # Add rate limit info to response headers (informational)
            request.state.rate_limit_info = rate_info
        
        # Store auth info in request state (accessible in endpoints)
        request.state.api_key = api_key
        request.state.role = role
        
        logger.info(f"Authenticated: {api_key[:8]}... as {role}")
        
        return {"api_key": api_key, "role": role}
    
    def require_admin(self, request: Request) -> None:
        """
        Require admin role for endpoint.
        
        Usage in endpoint:
            @app.get("/admin-only")
            async def admin_endpoint(request: Request):
                auth.require_admin(request)
                ...
        
        Raises:
            HTTPException(403) if not admin
        
        Backend concept: Role-based access control (RBAC)
        - Different keys have different permissions
        - Admin keys can access debug/dangerous endpoints
        - User keys restricted to read-only operations
        """
        role = getattr(request.state, "role", None)
        
        if role != "admin":
            logger.warning(f"Forbidden: {request.url.path} requires admin, got {role}")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admin access required"
            )


async def auth_middleware(request: Request, call_next, auth: APIKeyAuth):
    """
    FastAPI middleware for authentication.
    
    Runs on EVERY request before endpoint handler.
    
    Flow:
    1. Extract X-API-Key header
    2. Validate key (user vs admin)
    3. Check rate limit
    4. If all pass: proceed to endpoint
    5. If any fail: return 401/429/403
    
    Interview question: "Why middleware instead of decorator on each endpoint?"
    Answer: "Middleware = centralized, harder to forget. Decorator = must remember
    to add to each endpoint, easy to miss one (security hole)."
    
    Excluded routes:
    - /health (load balancer health checks don't have API keys)
    - / (root connectivity check)
    - /metrics (Prometheus scraping)
    - /v1/metrics (JSON metrics for monitoring)
    - OpenAPI docs (if enabled)
    """
    # Skip auth for health check and root (public endpoints)
    if request.url.path in ["/", "/health", "/metrics", "/v1/metrics", "/docs", "/openapi.json"]:
        return await call_next(request)
    
    # Authenticate request
    try:
        await auth.authenticate_request(request)
    except HTTPException as exc:
        # Return auth error immediately (fail-fast)
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
            headers=exc.headers or {}
        )
    
    # Proceed to endpoint
    response = await call_next(request)
    
    # Add rate limit headers to response (if available)
    if hasattr(request.state, "rate_limit_info"):
        info = request.state.rate_limit_info
        response.headers["X-RateLimit-Limit"] = str(info["limit"])
        response.headers["X-RateLimit-Remaining"] = str(info["remaining"])
        response.headers["X-RateLimit-Reset"] = str(info["reset_at"])
    
    return response
