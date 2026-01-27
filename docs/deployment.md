# Deployment Guide - Sentinel

## Quick Start

**Local Development:**

```bash
docker-compose up -d
curl http://localhost:8001/health
```

**Cloud Deployment (Fly.io):**

```bash
fly deploy --vm-size shared-cpu-1x
```

---

## 1. Docker Compose (Local Development)

### Prerequisites

- Docker Desktop installed
- `.env` file with `GROQ_API_KEY`

### Commands

```bash
# Start services
docker-compose up -d

# View logs (use SERVICE NAME, not container name)
docker-compose logs sentinel --tail=50
docker-compose logs -f sentinel  # Follow live

# Check status
docker-compose ps

# Restart
docker-compose restart sentinel

# Stop and clean up
docker-compose down
docker-compose down -v  # Also remove volumes
```

### Troubleshooting

**Error: "no such service: sentinel-app"**

- ❌ Wrong: `docker-compose logs sentinel-app`
- ✅ Correct: `docker-compose logs sentinel`
- Why: Service name is `sentinel`, container name is `sentinel-app`

**Error: "REDIS_URL environment variable is required"**

- Add to `.env`: `REDIS_URL=redis://localhost:6379` (local)
- docker-compose automatically sets: `REDIS_URL=redis://redis:6379` (Docker)

---

## 2. Fly.io Deployment (FREE TIER - $0/month)

### What You Get Free

- 3 shared-cpu-1x machines (256MB RAM each)
- 160GB outbound data/month
- 3 Redis instances
- Global deployment
- **No forced upgrade - free forever**

### Initial Setup (One-Time)

```bash
# Install Fly CLI (Windows)
iwr https://fly.io/install.ps1 -useb | iex

# Create account (free, no credit card required)
fly auth signup

# Login
fly auth login
```

### Deploy

```bash
cd C:\Users\syeds\Desktop\Sentinel

# Launch app (creates fly.toml if not exists)
fly launch --no-deploy

# Set environment variable
fly secrets set GROQ_API_KEY=your_groq_api_key_here
fly secrets set REDIS_URL=redis://localhost:6379  # Fly provides Redis

# Deploy to free tier
fly deploy --vm-size shared-cpu-1x

# Check status
fly status

# View logs
fly logs
fly logs -n 100  # Last 100 lines

# Open in browser
fly open
```

### Fly.io Commands Reference

```bash
# View app info
fly info

# Scale (within free tier: 3 machines max)
fly scale count 2

# View secrets
fly secrets list

# SSH into machine
fly ssh console

# Check resource usage
fly dashboard

# Stop app (keeps config, free)
fly apps pause

# Resume
fly apps resume

# Delete app
fly apps destroy sentinel
```

### Cost Monitoring

```bash
# View current usage
fly dashboard

# Expected: $0/month on free tier
# Only charged if you manually scale beyond free tier limits
```

---

## 3. Alternative Free Options

### Railway (Alternative)

```bash
# Install Railway CLI
npm install -g @railway/cli

# Login
railway login

# Deploy
railway up

# Set env vars
railway variables set GROQ_API_KEY=your_key
railway variables set REDIS_URL=redis://redis:6379
```

**Railway vs Fly.io:**

- Railway: 1 machine, 1GB RAM
- Fly.io: 3 machines, 256MB each
- Both: $0/month unlimited

---

## 4. Production Best Practices

### Environment Variables

```bash
# Required
GROQ_API_KEY=gsk_...          # Groq API key
REDIS_URL=redis://redis:6379  # Redis connection

# Optional
LOG_LEVEL=INFO                # DEBUG, INFO, WARNING, ERROR
```

### Health Checks

```bash
# Local
curl http://localhost:8001/health

# Fly.io
curl https://sentinel.fly.dev/health

# Expected response
{"status":"healthy","version":"0.1.0"}
```

### Monitoring

```bash
# Check metrics
curl http://localhost:8001/v1/metrics

# Expected
{
  "total_requests": 150,
  "cache_hits": 120,
  "cache_misses": 30,
  "hit_rate_percent": 80.0,
  "stored_items": 25,
  "uptime_seconds": 3600
}
```

---

## 5. Docker Best Practices

### Service Names vs Container Names

| Command Type             | Use This                       |
| ------------------------ | ------------------------------ |
| `docker-compose logs`    | Service name: `sentinel`       |
| `docker-compose restart` | Service name: `sentinel`       |
| `docker logs`            | Container name: `sentinel-app` |
| `docker stop`            | Container name: `sentinel-app` |

### Clean Builds

```bash
# Force rebuild (after code changes)
docker-compose build --no-cache

# Rebuild and restart
docker-compose up -d --build

# Remove old images
docker system prune -a
```

### Volume Management

```bash
# List volumes
docker volume ls

# Remove unused volumes
docker volume prune

# Inspect Redis data
docker volume inspect sentinel_redis_data
```

---

## 6. Advanced: nginx Configuration

For custom VM deployments with nginx reverse proxy:

**File:** [`docs/advanced/nginx.conf`](advanced/nginx.conf)

```nginx
upstream sentinel_backend {
    server localhost:8001;
}

server {
    listen 80;
    server_name sentinel.example.com;

    location / {
        proxy_pass http://sentinel_backend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

**Not needed for Fly.io** (Fly handles SSL, load balancing automatically)

---

## 7. Rollback & Recovery

### Docker Compose

```bash
# View previous images
docker images sentinel-sentinel

# Stop current
docker-compose down

# Modify code
git checkout <previous-commit>

# Rebuild
docker-compose build
docker-compose up -d
```

### Fly.io

```bash
# List releases
fly releases

# Rollback to previous
fly releases rollback <release-number>

# Check status
fly status
```

---

## 8. Performance Tuning

### Embedding Model Caching

**Now optimized** - Model cached in Docker image at build time

- First request: Instant (was 90s)
- Image size: +90MB

### Redis Performance

```bash
# Connect to Redis
docker-compose exec redis redis-cli

# Check memory usage
INFO memory

# View cached keys
KEYS sentinel:cache:*

# Clear cache (if needed)
FLUSHDB
```

### Health Check Tuning

```yaml
# In docker-compose.yml
healthcheck:
  start_period: 60s # Wait 60s before first check
  interval: 30s # Check every 30s after startup
  timeout: 10s # Fail if no response in 10s
  retries: 3 # Mark unhealthy after 3 failures
```

---

## 9. Common Issues

| Problem                  | Solution                                              |
| ------------------------ | ----------------------------------------------------- |
| "no such service" error  | Use service name (`sentinel`), not container name     |
| Redis connection refused | Check `REDIS_URL` env var, use service name in Docker |
| Health check fails       | Increase `start_period` to 60s                        |
| Import errors            | Rebuild: `docker-compose build --no-cache`            |
| Old containers running   | `docker-compose down` before `up`                     |

---

## 10. Next Steps

1. ✅ Local testing complete
2. 🚀 Deploy to Fly.io free tier
3. 📊 Monitor metrics and cache hit rate
4. 🔧 Tune similarity threshold if needed (default: 0.75)
5. 📈 Scale within free tier (up to 3 machines)

**Ready to deploy!** All optimizations applied, deprecated code removed, production-ready.
