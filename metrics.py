"""
Prometheus Metrics for Sentinel V2 - Observability instrumentation.

RESPONSIBILITY:
    Define and expose metrics for monitoring Sentinel's health and performance.
    Follows RED methodology: Rate, Errors, Duration.

WHY PROMETHEUS:
    - Industry standard for cloud-native monitoring (Kubernetes, Docker)
    - Pull-based: Prometheus scrapes /metrics endpoint (not push)
    - Supports Grafana dashboards, Alertmanager for alerts
    - Time-series database optimized for metrics

BACKEND PRINCIPLE: Observability
    Production systems must be instrumented. Metrics answer:
    - Is the system healthy? (error rate, latency)
    - Is it being used? (request rate, cache hit rate)
    - Is it costing money? (LLM costs)
    
    Without metrics, you're flying blind.

INTERVIEW QUESTION:
    "How do you monitor microservices in production?"
    
    Answer: "Prometheus for metrics, structured logs for debugging, tracing for
    distributed requests. Metrics give aggregate view (95th percentile latency),
    logs give specific failures (why did request X fail?)."

METRIC TYPES:
    - Counter: Monotonically increasing (requests, errors, costs)
    - Histogram: Distribution of values (latency, sizes)
    - Gauge: Current value that can go up/down (active connections, queue depth)

CARDINALITY WARNING:
    Labels create separate time series. High cardinality = expensive.
    - Good: status="200" (few values)
    - Bad: user_id="abc123" (millions of values)
    
    Rule: Keep label cardinality < 1000 per metric.
"""

from prometheus_client import Counter, Histogram, Gauge, REGISTRY
import logging

logger = logging.getLogger(__name__)


# =============================================================================
# RED METRICS (Rate, Errors, Duration)
# =============================================================================

# RATE: Request counter
# Labels: endpoint (which API route), status (HTTP status code)
# Use: Track request volume and error rate per endpoint
# Example queries:
#   - rate(sentinel_requests_total[5m]) → requests/second
#   - sentinel_requests_total{status="500"} → error count
sentinel_requests_total = Counter(
    "sentinel_requests_total",
    "Total HTTP requests to Sentinel API",
    labelnames=["endpoint", "status"],
    # Interview: Why label by endpoint and status?
    # Answer: Allows filtering (e.g., error rate for /v1/query specifically)
    # Cardinality: ~10 endpoints × ~10 status codes = 100 time series (safe)
)

# DURATION: Request latency histogram
# Labels: endpoint (which API route)
# Use: Track latency distribution (p50, p95, p99)
# Buckets: Tuned for typical API latency (ms to seconds)
sentinel_request_duration_seconds = Histogram(
    "sentinel_request_duration_seconds",
    "HTTP request latency in seconds",
    labelnames=["endpoint"],
    # Buckets: Customize based on your latency profile
    # Default: [.005, .01, .025, .05, .075, .1, .25, .5, .75, 1.0, 2.5, 5.0, 7.5, 10.0, INF]
    # Interview: Why histogram over average?
    # Answer: Averages hide outliers. p95/p99 show "worst case" user experience.
    # Histogram buckets allow percentile calculations in Prometheus queries.
    buckets=[
        0.01,   # 10ms - cache hits
        0.05,   # 50ms - semantic search
        0.1,    # 100ms
        0.25,   # 250ms
        0.5,    # 500ms
        1.0,    # 1s
        2.5,    # 2.5s
        5.0,    # 5s - typical LLM call
        10.0,   # 10s
        30.0,   # 30s - lock timeout
        float("inf")
    ]
    # TODO: Review these buckets after running in production
    # Adjust based on actual latency distribution
)


# =============================================================================
# CACHE METRICS
# =============================================================================

# Cache hit/miss counter
# Labels: type (exact, semantic, miss)
# Use: Calculate cache hit rate, identify cache effectiveness
# Example queries:
#   - sentinel_cache_hits_total{type="exact"} / sum(sentinel_cache_hits_total) → hit rate
#   - rate(sentinel_cache_hits_total{type="miss"}[5m]) → cache miss rate
sentinel_cache_hits_total = Counter(
    "sentinel_cache_hits_total",
    "Cache hit/miss counters by type",
    labelnames=["type"],
    # Types: "exact" (Redis key match), "semantic" (embedding similarity), "miss" (no match)
    # Interview: Why separate exact vs semantic?
    # Answer: Different performance characteristics. Exact = O(1), semantic = O(n).
    # Helps identify if semantic cache is providing value.
    # Cardinality: 3 time series (safe)
)


# =============================================================================
# COST METRICS
# =============================================================================

# LLM cost accumulator
# Labels: provider (groq, openai, etc), model (llama-3.1-8b-instant, etc)
# Use: Track cumulative spend, cost per request
# Example queries:
#   - increase(sentinel_llm_cost_usd_total[1d]) → daily spend
#   - sentinel_llm_cost_usd_total{provider="groq"} → total Groq spend
sentinel_llm_cost_usd_total = Counter(
    "sentinel_llm_cost_usd_total",
    "Cumulative LLM API costs in USD",
    labelnames=["provider", "model"],
    # Interview: Why track cost?
    # Answer: Cost visibility drives optimization. Can alert on spend spikes,
    # correlate cost with cache hit rate, justify caching ROI.
    # Cardinality: ~5 providers × ~20 models = 100 time series (safe)
)


# =============================================================================
# CONCURRENCY METRICS
# =============================================================================

# Active locks gauge
# No labels (global metric)
# Use: Monitor concurrency, identify lock contention
# Example queries:
#   - sentinel_active_locks → current lock count
#   - max_over_time(sentinel_active_locks[5m]) → peak concurrency
sentinel_active_locks = Gauge(
    "sentinel_active_locks",
    "Number of currently held distributed locks",
    # Interview: Why gauge instead of counter?
    # Answer: Gauge can go up and down (locks acquired and released).
    # Counter only increases. Gauge tracks "current state" like memory usage.
    # Cardinality: 1 time series (no labels)
)


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def record_request(endpoint: str, status: int, duration_seconds: float) -> None:
    """
    Record request metrics (counter + duration histogram).
    
    Call this from middleware after each request completes.
    
    Args:
        endpoint: API route (e.g., "/v1/query")
        status: HTTP status code (200, 401, 500, etc)
        duration_seconds: Request latency in seconds
    
    Interview: Why helper function instead of calling metrics directly?
    Answer: Encapsulation. If we change metric implementation, only update here.
    Also ensures consistent labeling (typos in labels = separate time series).
    """
    sentinel_requests_total.labels(endpoint=endpoint, status=str(status)).inc()
    sentinel_request_duration_seconds.labels(endpoint=endpoint).observe(duration_seconds)


def record_cache_hit(hit_type: str) -> None:
    """
    Record cache hit/miss.
    
    Args:
        hit_type: "exact", "semantic", or "miss"
    
    Call this from QueryService when checking cache.
    """
    if hit_type not in ["exact", "semantic", "miss"]:
        logger.warning(f"Invalid cache hit type: {hit_type}")
        return
    
    sentinel_cache_hits_total.labels(type=hit_type).inc()


def record_llm_cost(provider: str, model: str, cost_usd: float) -> None:
    """
    Record LLM API cost.
    
    Args:
        provider: LLM provider (e.g., "groq", "openai")
        model: Model name (e.g., "llama-3.1-8b-instant")
        cost_usd: Cost in USD
    
    Call this after LLM call completes.
    """
    sentinel_llm_cost_usd_total.labels(provider=provider, model=model).inc(cost_usd)


def increment_active_locks() -> None:
    """Increment active lock count when lock acquired."""
    sentinel_active_locks.inc()


def decrement_active_locks() -> None:
    """Decrement active lock count when lock released."""
    sentinel_active_locks.dec()


# =============================================================================
# TESTING & VERIFICATION
# =============================================================================

"""
TESTING LOCALLY:

1. Start Sentinel:
   python main.py

2. Make some requests:
   curl -X POST http://localhost:8000/v1/query \\
     -H "X-API-Key: your_key" \\
     -H "Content-Type: application/json" \\
     -d '{"prompt":"test"}'

3. Scrape metrics:
   curl http://localhost:8000/metrics

4. Verify metrics appear:
   - Search for "sentinel_requests_total" (should show count)
   - Search for "sentinel_request_duration_seconds" (should show buckets)
   - Search for "sentinel_cache_hits_total" (should show hit/miss counts)

PROMETHEUS QUERIES (for Grafana):

# Request rate (requests/second over 5 minutes)
rate(sentinel_requests_total[5m])

# Error rate (5xx errors as percentage)
sum(rate(sentinel_requests_total{status=~"5.."}[5m])) / sum(rate(sentinel_requests_total[5m])) * 100

# 95th percentile latency
histogram_quantile(0.95, rate(sentinel_request_duration_seconds_bucket[5m]))

# Cache hit rate
sum(rate(sentinel_cache_hits_total{type!="miss"}[5m])) / sum(rate(sentinel_cache_hits_total[5m])) * 100

# Daily LLM spend
increase(sentinel_llm_cost_usd_total[1d])

# Peak concurrent locks
max_over_time(sentinel_active_locks[5m])

ALERTING EXAMPLES (Alertmanager):

# Alert if error rate > 5%
alert: HighErrorRate
expr: sum(rate(sentinel_requests_total{status=~"5.."}[5m])) / sum(rate(sentinel_requests_total[5m])) > 0.05

# Alert if p95 latency > 5s
alert: HighLatency
expr: histogram_quantile(0.95, rate(sentinel_request_duration_seconds_bucket[5m])) > 5

# Alert if cache hit rate < 50%
alert: LowCacheHitRate
expr: sum(rate(sentinel_cache_hits_total{type!="miss"}[5m])) / sum(rate(sentinel_cache_hits_total[5m])) < 0.5

CARDINALITY CHECK:

# Count time series per metric
curl http://localhost:8000/metrics | grep "sentinel_" | wc -l

# Should be < 500 time series total
# If too high: Remove labels or reduce label value diversity
"""

# Export metrics for main.py to use
__all__ = [
    "sentinel_requests_total",
    "sentinel_request_duration_seconds",
    "sentinel_cache_hits_total",
    "sentinel_llm_cost_usd_total",
    "sentinel_active_locks",
    "record_request",
    "record_cache_hit",
    "record_llm_cost",
    "increment_active_locks",
    "decrement_active_locks",
    "REGISTRY",
]
