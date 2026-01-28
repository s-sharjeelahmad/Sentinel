# Deployment Guide

Complete guide for deploying Sentinel AI Gateway locally (Docker) and to production (Fly.io).

---

## Prerequisites

### Required Accounts & API Keys

1. **Groq API Key** (Free Tier: 20K tokens/min)

   - Sign up: https://console.groq.com
   - Create API key: Dashboard → API Keys → Create New Key
   - Copy key starting with `gsk_...`

2. **Jina AI API Key** (Free Tier: 1M tokens/month)

   - Sign up: https://jina.ai
   - Get API key: Dashboard → API Keys → Create New Key
   - Copy key starting with `jina_...`

3. **Fly.io Account** (Free Tier: $0/month for basic apps)
   - Sign up: https://fly.io/signup
   - Install Fly CLI: https://fly.io/docs/flyctl/install/

### Required Software

- **Docker** (for local deployment)

  - Windows: Docker Desktop
  - macOS: Docker Desktop
  - Linux: `sudo apt install docker.io docker-compose`

- **Fly CLI** (for production deployment)
  - Windows: `iwr https://fly.io/install.ps1 -useb | iex`
  - macOS: `brew install flyctl`
  - Linux: `curl -L https://fly.io/install.sh | sh`

---

## Local Deployment (Docker)

### Step 1: Clone Repository

```bash
git clone https://github.com/yourusername/sentinel.git
cd sentinel
```

### Step 2: Create Environment File

Create `.env` file in project root:

```env
# Required API Keys
GROQ_API_KEY=gsk_YOUR_GROQ_API_KEY_HERE
JINA_API_KEY=jina_YOUR_JINA_API_KEY_HERE

# Redis Connection
REDIS_URL=redis://redis:6379

# Optional: Logging Level
LOG_LEVEL=INFO
```

**Security Warning:** Never commit `.env` file to git. It's already in `.gitignore`.

### Step 3: Start Services

```bash
# Start Redis + Sentinel
docker-compose up -d

# View logs
docker-compose logs -f sentinel

# Stop services
docker-compose down
```

**Services Started:**

- Sentinel API: http://localhost:8000
- Redis: localhost:6379

### Step 4: Verify Deployment

```bash
# Health check
curl http://localhost:8000/health

# Test query
curl -X POST http://localhost:8000/v1/query \
  -H "Content-Type: application/json" \
  -d '{"prompt": "What is Docker?"}'

# Check metrics
curl http://localhost:8000/v1/metrics
```

**Expected Output:**

```json
{
  "status": "healthy",
  "redis": "connected",
  "timestamp": "2024-01-15T10:30:00Z"
}
```

---

## Production Deployment (Fly.io)

### Step 1: Install & Authenticate Fly CLI

```bash
# Install (if not already installed)
curl -L https://fly.io/install.sh | sh

# Login
flyctl auth login
```

### Step 2: Create Fly App

```bash
# Launch app (interactive setup)
flyctl launch

# You'll be prompted:
# - App name: sentinel-ai-gateway (or custom name)
# - Region: Select closest to your users (e.g., iad for US East)
# - PostgreSQL: No (we use Redis)
# - Deploy now: No (we need to set secrets first)
```

**Output:**

```
Created app 'sentinel-ai-gateway' in organization 'personal'
Admin URL: https://fly.io/apps/sentinel-ai-gateway
Hostname: sentinel-ai-gateway.fly.dev
```

### Step 3: Provision Redis

```bash
# Create Upstash Redis (free tier: 256MB)
flyctl redis create

# Prompts:
# - Name: sentinel-redis
# - Region: Same as app region
# - Plan: Free

# Output will show REDIS_URL - save this!
# redis://default:PASSWORD@fly-sentinel-redis.upstash.io
```

### Step 4: Set Environment Variables

```bash
# Set secrets (encrypted, never shown in logs)
flyctl secrets set GROQ_API_KEY=gsk_YOUR_GROQ_KEY_HERE
flyctl secrets set JINA_API_KEY=jina_YOUR_JINA_KEY_HERE
flyctl secrets set REDIS_URL=redis://default:PASSWORD@fly-sentinel-redis.upstash.io

# Verify secrets (shows names only, not values)
flyctl secrets list
```

### Step 5: Deploy

```bash
# Deploy to Fly.io
flyctl deploy

# View deployment logs
flyctl logs
```

**Deployment Process:**

```
1. Building Docker image (multi-stage build: ~74MB)
2. Pushing to Fly.io registry
3. Creating VM (shared-cpu-1x, 256MB RAM)
4. Starting service on port 8000
5. Health check: GET /health
6. Deployment complete!
```

### Step 6: Verify Production Deployment

```bash
# Get app URL
flyctl info

# Health check
curl https://sentinel-ai-gateway.fly.dev/health

# Test query
curl -X POST https://sentinel-ai-gateway.fly.dev/v1/query \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Test deployment"}'
```

---

## Configuration Files

### docker-compose.yml

```yaml
version: "3.8"

services:
  redis:
    image: redis:7.0-alpine
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data
    command: redis-server --maxmemory 256mb --maxmemory-policy allkeys-lru

  sentinel:
    build: .
    ports:
      - "8000:8000"
    environment:
      - GROQ_API_KEY=${GROQ_API_KEY}
      - JINA_API_KEY=${JINA_API_KEY}
      - REDIS_URL=redis://redis:6379
    depends_on:
      - redis
    restart: unless-stopped

volumes:
  redis_data:
```

**Key Configurations:**

- Redis max memory: 256MB (prevents OOM)
- Eviction policy: LRU (least recently used)
- Auto-restart: Yes (unless manually stopped)

### Dockerfile

```dockerfile
# Stage 1: Build dependencies
FROM python:3.11-slim AS builder
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Stage 2: Runtime
FROM python:3.11-slim
WORKDIR /app

# Copy dependencies from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages

# Copy application code
COPY . .

# Expose port
EXPOSE 8000

# Run FastAPI with Uvicorn
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

**Optimizations:**

- Multi-stage build (reduces final image size by 60%)
- No cache (saves space)
- Slim base image (74MB final vs 200MB+ standard)

### fly.toml

```toml
app = "sentinel-ai-gateway"
primary_region = "iad"

[build]
  dockerfile = "Dockerfile"

[env]
  PORT = "8000"

[http_service]
  internal_port = 8000
  force_https = true
  auto_stop_machines = true
  auto_start_machines = true
  min_machines_running = 0

[[http_service.checks]]
  interval = "10s"
  timeout = "2s"
  grace_period = "5s"
  method = "GET"
  path = "/health"

[[vm]]
  cpu_kind = "shared"
  cpus = 1
  memory_mb = 256
```

**Key Settings:**

- Auto-stop: VM shuts down after 5 min idle (free tier benefit)
- Auto-start: VM starts on first request (~2s cold start)
- Health check: Every 10s, restarts if `/health` fails
- Min machines: 0 (saves costs, acceptable for low-traffic apps)

---

## Environment Variables Reference

| Variable       | Required | Default                | Description                              |
| -------------- | -------- | ---------------------- | ---------------------------------------- |
| `GROQ_API_KEY` | ✅       | -                      | Groq API key (starts with `gsk_`)        |
| `JINA_API_KEY` | ✅       | -                      | Jina API key (starts with `jina_`)       |
| `REDIS_URL`    | ✅       | redis://localhost:6379 | Redis connection string                  |
| `PORT`         | ❌       | 8000                   | HTTP server port                         |
| `LOG_LEVEL`    | ❌       | INFO                   | Logging level (DEBUG/INFO/WARNING/ERROR) |
| `CACHE_TTL`    | ❌       | 3600                   | Cache expiration (seconds)               |

**Example (Local):**

```env
GROQ_API_KEY=gsk_1234567890abcdef
JINA_API_KEY=jina_abcdef1234567890
REDIS_URL=redis://localhost:6379
LOG_LEVEL=DEBUG
```

**Example (Fly.io - set via CLI):**

```bash
flyctl secrets set GROQ_API_KEY=gsk_1234567890abcdef
flyctl secrets set JINA_API_KEY=jina_abcdef1234567890
flyctl secrets set REDIS_URL=redis://default:PASSWORD@fly-sentinel-redis.upstash.io
```

---

## Monitoring & Maintenance

### View Logs

**Local (Docker):**

```bash
# All services
docker-compose logs -f

# Sentinel only
docker-compose logs -f sentinel

# Last 100 lines
docker-compose logs --tail=100 sentinel
```

**Production (Fly.io):**

```bash
# Live tail
flyctl logs

# Last 200 lines
flyctl logs --lines=200

# Filter by severity
flyctl logs --level=error
```

### Scale Resources

**Fly.io (if needed):**

```bash
# Increase memory (if getting OOM errors)
flyctl scale memory 512

# Add more VMs (if high traffic)
flyctl scale count 2

# Check current status
flyctl status
```

**Cost Impact:**

- 256MB RAM: Free
- 512MB RAM: ~$2/month
- 2 VMs: Doubles cost

### Update Deployment

**Local:**

```bash
# Rebuild & restart
docker-compose up -d --build
```

**Production:**

```bash
# Pull latest code
git pull origin main

# Deploy new version
flyctl deploy

# Rollback if issues
flyctl releases list
flyctl releases rollback <VERSION>
```

### Backup & Restore Redis

**Backup (save cached data):**

```bash
# Local
docker exec sentinel-redis-1 redis-cli SAVE
docker cp sentinel-redis-1:/data/dump.rdb ./backup.rdb

# Fly.io (Upstash - automatic backups every 24h)
# No manual backup needed
```

**Restore:**

```bash
# Local
docker cp ./backup.rdb sentinel-redis-1:/data/dump.rdb
docker-compose restart redis
```

---

## Troubleshooting

### Issue: "Connection to Redis failed"

**Symptoms:**

```json
{
  "detail": "Cache service unavailable",
  "error_code": "REDIS_ERROR"
}
```

**Solutions:**

**Local:**

```bash
# Check if Redis is running
docker ps | grep redis

# If not running, start it
docker-compose up -d redis

# Test connection
redis-cli ping
# Should return: PONG
```

**Fly.io:**

```bash
# Check Redis status
flyctl redis status sentinel-redis

# Get connection string
flyctl redis status sentinel-redis --json | jq -r '.PrivateURL'

# Update secret if URL changed
flyctl secrets set REDIS_URL=redis://new-url-here
```

---

### Issue: "Jina API error" (503)

**Symptoms:**

```json
{
  "detail": "Embedding service unavailable",
  "error_code": "EMBEDDING_ERROR"
}
```

**Solutions:**

1. **Verify API Key:**

```bash
# Local
echo $JINA_API_KEY

# Fly.io
flyctl secrets list
```

2. **Test Jina API Directly:**

```bash
curl https://api.jina.ai/v1/embeddings \
  -H "Authorization: Bearer $JINA_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"input": "test", "model": "jina-embeddings-v3"}'
```

3. **Check Rate Limits:**

- Free tier: 1M tokens/month, 100 req/sec
- If exceeded, upgrade plan or wait for reset

---

### Issue: "Groq rate limit exceeded" (429)

**Symptoms:**

```json
{
  "detail": "Groq API error: rate limit exceeded",
  "error_code": "RATE_LIMIT_ERROR",
  "retry_after_seconds": 60
}
```

**Solutions:**

1. **Check Current Usage:**

- Visit https://console.groq.com/usage
- Free tier: 20K tokens/min, 5K requests/day

2. **Optimize Cache Hit Rate:**

```bash
# Check cache performance
curl http://localhost:8000/v1/metrics

# If hit rate < 40%, adjust similarity threshold
# Lower threshold = more cache hits
curl -X POST http://localhost:8000/v1/query \
  -d '{"prompt": "...", "similarity_threshold": 0.70}'
```

3. **Upgrade Groq Plan (if needed):**

- Pay-as-you-go: $0.05–$0.15 per 1M tokens

---

### Issue: High Memory Usage (Docker)

**Symptoms:**

```
Out of memory: Killed process 1234 (uvicorn)
```

**Solutions:**

1. **Limit Redis Memory:**

```yaml
# docker-compose.yml
redis:
  command: redis-server --maxmemory 128mb --maxmemory-policy allkeys-lru
```

2. **Clear Old Cache:**

```bash
curl -X DELETE http://localhost:8000/v1/cache/clear
```

3. **Monitor Memory:**

```bash
docker stats sentinel-sentinel-1
```

---

### Issue: Slow Cold Starts (Fly.io)

**Symptoms:**

- First request after idle takes 2-5 seconds

**Solutions:**

1. **Keep Warm (costs money):**

```toml
# fly.toml
[http_service]
  min_machines_running = 1  # Keep 1 VM always on
```

Cost: ~$2/month

2. **Accept Cold Starts:**

- Free tier benefit (saves money)
- Only affects first request after 5 min idle

---

## Cost Breakdown

### Free Tier (Recommended for Testing)

| Service       | Cost         | Limits                          |
| ------------- | ------------ | ------------------------------- |
| Groq API      | $0/month     | 20K tokens/min, 5K req/day      |
| Jina API      | $0/month     | 1M tokens/month, 100 req/sec    |
| Fly.io (VM)   | $0/month     | 256MB RAM, 3 shared CPUs        |
| Upstash Redis | $0/month     | 256MB storage, 10K commands/day |
| **Total**     | **$0/month** | Enough for 100-500 requests/day |

### Production (Typical Usage)

**Scenario: 10,000 requests/day, 50% cache hit rate**

| Service       | Cost            | Calculation                                               |
| ------------- | --------------- | --------------------------------------------------------- |
| Groq API      | $3.00/month     | 5K LLM calls/day × 150 tokens avg × 30 days × $0.00015/1K |
| Jina API      | $0/month        | Free tier sufficient (150K tokens/month)                  |
| Fly.io (VM)   | $2.00/month     | 512MB RAM (if needed)                                     |
| Upstash Redis | $0/month        | Free tier sufficient                                      |
| **Total**     | **$5.00/month** |                                                           |

**Compare to No Caching:**

- Groq API alone: $6.00/month (10K calls × 150 tokens × 30 × $0.00015)
- Savings: 40% cost reduction

---

## Security Best Practices

### 1. Protect API Keys

**Never:**

- ❌ Commit `.env` file to git
- ❌ Log API keys in console
- ❌ Hardcode keys in source code

**Always:**

- ✅ Use environment variables
- ✅ Use Fly.io secrets (encrypted)
- ✅ Rotate keys every 90 days

### 2. Add Authentication (Future)

**Current:** Public API (anyone can use)

**Recommended for Production:**

```python
# Add API key middleware
@app.middleware("http")
async def check_api_key(request: Request, call_next):
    api_key = request.headers.get("X-API-Key")
    if api_key != os.getenv("SENTINEL_API_KEY"):
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    return await call_next(request)
```

### 3. Rate Limiting (Future)

**Prevent abuse:**

```python
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter

@app.post("/v1/query")
@limiter.limit("10/minute")
async def query(request: Request, ...):
    ...
```

---

## Next Steps

✅ **Completed:**

- Local deployment working
- Production deployment on Fly.io
- Environment variables configured
- Monitoring logs and metrics

📋 **Recommended:**

- [ ] Set up uptime monitoring (e.g., UptimeRobot)
- [ ] Configure alerts for errors (e.g., Sentry)
- [ ] Add API key authentication
- [ ] Implement rate limiting
- [ ] Set up CI/CD (GitHub Actions → Fly.io auto-deploy)

---

## Support & Resources

**Documentation:**

- Groq API: https://console.groq.com/docs
- Jina API: https://jina.ai/docs
- Fly.io: https://fly.io/docs

**Status Pages:**

- Groq: https://status.groq.com
- Jina: https://status.jina.ai
- Fly.io: https://status.flyio.net

**Community:**

- Groq Discord: https://discord.gg/groq
- Fly.io Community: https://community.fly.io
