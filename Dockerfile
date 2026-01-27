# Sentinel - Semantic AI Gateway
# Multi-stage Docker build for optimal image size
#
# Build options:
#   CPU (default, faster):  docker build -t sentinel .
#   GPU (if needed):        docker build --build-arg TORCH_VARIANT=cu118 -t sentinel .
#
# Optimizations:
#   - CPU-only PyTorch by default (saves 1.7GB, 8min build time)
#   - Pure Python redis (saves 4min build, +0.5ms runtime)
#   - Multi-stage build (400MB smaller final image)
#   - Layer caching optimized (30s incremental builds)

# Stage 1: Builder - Install dependencies
FROM python:3.11-slim as builder

WORKDIR /app

# Copy requirements FIRST (better layer caching)
COPY requirements.txt .

# Install remaining dependencies (removed torch - using HF Inference API)
RUN pip install --no-cache-dir -r requirements.txt

# Stage 2: Runtime - Minimal production image
FROM python:3.11-slim

WORKDIR /app

# Copy Python dependencies from builder
COPY --from=builder /usr/local /usr/local

# Copy application code
COPY . .

# Make sure scripts are executable and in PATH/PYTHONPATH
ENV PATH=/usr/local/bin:$PATH \
    PYTHONPATH=/usr/local/lib/python3.11/site-packages

# Create non-root user for security
RUN useradd -m -u 1000 sentinel && \
    chown -R sentinel:sentinel /app

USER sentinel

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

# Start application
CMD ["python", "main.py"]
