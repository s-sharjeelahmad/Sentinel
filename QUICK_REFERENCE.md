# QUICK REFERENCE

## Common Commands

### Docker Compose (Local Dev)

```bash
docker-compose up -d              # Start all services
docker-compose logs sentinel      # View logs (use SERVICE name, not container name)
docker-compose ps                 # Check status
docker-compose down               # Stop everything
```

### Fly.io Deployment (Cloud)

```bash
flyctl deploy                      # Deploy (rebuilds if needed)
flyctl status                      # Check app health
flyctl logs                        # View live logs
flyctl secrets list                # List all environment variables
```

---

## FAQ

### Q: Docker error "no such service: sentinel-app"

**A:** Use service name with `docker-compose`:

- ✅ `docker-compose logs sentinel` (correct - service name)
- ❌ `docker-compose logs sentinel-app` (wrong - that's container name)

### Q: Can Fly.io be free forever?

**A:** Yes! Free tier = **$0/month unlimited**:

- 3 machines (256MB each)
- 160GB outbound/month
- 3 Redis instances
- No forced upgrade - stays free forever

### Q: Fly.io deployment keeps restarting

**A:** Check:

1. `flyctl logs` for errors (usually missing env vars or startup failures)
2. `flyctl secrets list` - verify all secrets are "Deployed" status
3. `flyctl machines restart <id>` - force restart after fixing issues

### Q: How do I configure the embedding API?

**A:** Set environment variables:

```bash
HF_API_TOKEN=hf_your_token_here    # HuggingFace Inference API token
REDIS_URL=...                       # Redis connection string
GROQ_API_KEY=...                    # Groq API key
```

---

## Architecture Quick View

```
Client App
    ↓
  Sentinel (FastAPI)
    ├─→ Check Redis cache (semantic match?)
    ├─→ Call HF Inference API (embeddings)
    ├─→ Call Groq API (LLM responses)
    ↓
  Return response + metadata
```

**Key metrics:**

- Cache hit (exact): 5ms
- Cache hit (semantic): 45ms
- Cache miss: 1200ms + embedding latency

---

## Deployment Summary

| Aspect       | Local          | Fly.io                              |
| ------------ | -------------- | ----------------------------------- |
| **Service**  | docker-compose | Free tier                           |
| **Cost**     | $0             | $0/month                            |
| **RAM**      | Varies         | 256MB ✓                             |
| **Database** | Local Redis    | Managed Redis ✓                     |
| **URL**      | localhost:8000 | https://sentinel-ai-gateway.fly.dev |
| **Uptime**   | Manual         | Auto-restart                        |

```bash
fly deploy --vm-size shared-cpu-1x  # Deploys to free tier
```

**Cost:** $0/month forever (unless you manually upgrade)

---

### 3. Series of Errors Explained

#### Error #1: "Conflict. Container name '/sentinel-redis' already in use"

**What:** Previous Docker container not cleaned up
**Why:** Stopped containers still take up the name
**Prevention:**

```bash
docker-compose down  # Always clean up before restarting
```

---

#### Error #2: "ModuleNotFoundError: No module named 'fastapi'"

**What:** Packages installed to wrong directory
**Why:** Used `pip install --user` (installs to `/root/.local`)

- Root user can access `/root/.local`
- Non-root user `sentinel` **cannot** access it
  **Prevention:**

```dockerfile
# ❌ WRONG
RUN pip install --user -r requirements.txt

# ✅ CORRECT
RUN pip install -r requirements.txt
```

Never use `--user` in Dockerfiles!

---

#### Error #3: "Error 111 connecting to localhost:6379"

**What:** App trying to reach Redis on wrong address
**Why:** In Docker, `localhost` = container itself, not the host
**Prevention:**

```python
# ❌ WRONG - hardcoded localhost
redis_url = "redis://localhost:6379"

# ✅ CORRECT - use environment variable
redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
```

In Docker network, use **service name**:

```yaml
# docker-compose.yml
sentinel:
  environment:
    REDIS_URL: redis://redis:6379 # 'redis' is the service name
```

---

#### Error #4: "Health check failed" (Container marked unhealthy)

**What:** App took too long to start
**Why:** Downloading 90MB embedding model took >40 seconds
**Prevention:**

```yaml
healthcheck:
  start_period: 60s # Give more time for long startup tasks
```

Or cache the model in Docker:

```dockerfile
RUN python -c "from sentence_transformers import SentenceTransformer; \
    SentenceTransformer('all-MiniLM-L6-v2')"
```

---

## How to Identify & Fix These Errors in Future

### Error Detection Checklist

| Error                | How to Spot                        | Where to Look                     | Fix                              |
| -------------------- | ---------------------------------- | --------------------------------- | -------------------------------- |
| Service not found    | `docker-compose logs service-name` | docker-compose.yml - service name | Use correct service name         |
| Import error         | `docker logs container-name`       | App startup logs                  | Check pip install flags          |
| Connection refused   | `docker logs container-name`       | Error 111 in logs                 | Use service name, not localhost  |
| Health check timeout | `docker ps` shows unhealthy        | `start_period` too short          | Increase healthcheck timeout     |
| Permission denied    | File access errors                 | Docker build logs                 | Check file ownership/permissions |

### Debugging Commands

```bash
# 1. Check service status
docker-compose ps

# 2. View logs (use service name)
docker-compose logs sentinel --tail 100

# 3. Check if containers are running
docker ps -a

# 4. Inspect a service
docker-compose exec sentinel bash

# 5. Check health details
docker inspect sentinel-app | Select-String -Pattern '"Health"' -Context 0,10

# 6. Test Redis connection
docker-compose exec redis redis-cli ping

# 7. Test app endpoint
curl http://localhost:8001/health
```

---

## File Updates Made

✅ **docker-compose.yml** - Removed deprecated `version` field
✅ **DOCKER_COMPOSE_GUIDE.md** - Created comprehensive guide
✅ **FLYIO_FREE_DEPLOYMENT.md** - Created deployment guide

---

## Current Status

### Running Services

```
✅ sentinel-app (healthy)
✅ sentinel-redis (healthy)
```

### Endpoints Working

```
✅ GET http://localhost:8001/health
✅ POST http://localhost:8001/v1/query
✅ GET http://localhost:8001/v1/metrics
```

### Docker Compose Syntax

```bash
# ✅ CORRECT NOW
docker-compose logs sentinel
docker-compose restart sentinel
docker-compose ps
docker-compose down

# ❌ INCORRECT (don't use)
docker-compose logs sentinel-app
```

---

## Next Steps

### Ready to Deploy to Fly.io?

1. **Install Fly CLI:**

   ```bash
   iwr https://fly.io/install.ps1 -useb | iex
   ```

2. **Login:**

   ```bash
   fly auth signup  # Create free account
   fly auth login   # Login
   ```

3. **Deploy:**

   ```bash
   cd C:\Users\syeds\Desktop\Sentinel
   fly deploy --vm-size shared-cpu-1x
   ```

4. **Set API Key:**

   ```bash
   fly secrets set GROQ_API_KEY=your_key_here
   ```

5. **Monitor:**
   ```bash
   fly logs
   fly status
   ```

**Cost:** $0/month forever ✅

---

## Key Learnings

1. **docker-compose uses service names, docker uses container names**

   - Always use service name with docker-compose commands

2. **Never hardcode localhost in containerized apps**

   - Use environment variables
   - In Docker, use service names

3. **Never use `--user` flag in Dockerfile pip installs**

   - Installs to user directory that container user can't access
   - Use system-wide installation

4. **Health checks need timeout for long startup tasks**

   - Embedding models, large downloads need more time
   - `start_period: 60s` for initialization

5. **Fly.io free tier is genuinely free forever**
   - No paid tier required
   - 3 shared machines included
   - Perfect for Sentinel

---
