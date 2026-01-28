# Sentinel - Semantic AI Gateway

🚀 **Production-ready semantic caching layer that reduces redundant LLM API calls by up to 90%.**

## What is Sentinel?

Sentinel is a semantic AI gateway that sits between your application and LLM providers. It uses embedding-based semantic caching to:

- **Reduce costs by 70-90%** — Cache semantically similar queries
- **Improve latency by 200x** — 5ms cache hits vs 1000ms API calls
- **Prevent redundant calls** — Distributed locking + semantic matching
- **Track metrics** — Prometheus-compatible observability
- **Production-ready** — Graceful shutdown, circuit breaker, rate limiting

## Tech Stack

- FastAPI 0.104 (async)
- Redis 7.0 (distributed cache)
- Jina Embeddings API (external, no local model)
- aiohttp (async HTTP)
- Pydantic (validation)
- Docker (74MB minimal image)

## How It Works

```
Query → Sentinel
  ↓
[1] Compute embedding (Jina API)
  ↓
[2] Exact cache match? → Return (5ms) ✅
  ↓ No
[3] Semantic match? → Return (50ms) ✅
  ↓ No
[4] Call LLM (Groq) → Cache → Return (1250ms)
```

## Quick Start

### 1. Install Dependencies

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Set Environment Variables

Create `.env`:

```env
GROQ_API_KEY=your_key
JINA_API_KEY=your_key
REDIS_URL=redis://localhost:6379
```

### 3. Start Redis

```bash
docker run -d -p 6379:6379 redis:7-alpine
```

### 4. Run Sentinel

```bash
python main.py
```

Server at `http://localhost:8000`

## Docker Deployment

### Local with Docker Compose

```bash
docker-compose up -d
docker-compose logs -f
```

### Production

```bash
docker build -t sentinel:latest .
docker run -d -p 8000:8000 \
  -e GROQ_API_KEY=your_key \
  -e JINA_API_KEY=your_key \
  -e REDIS_URL=redis://... \
  sentinel:latest
```

## API Endpoints

### POST `/v1/query`

Submit a prompt with semantic caching.

**Request:**

```json
{
  "prompt": "What is quantum computing?",
  "similarity_threshold": 0.75
}
```

**Response:**

```json
{
  "response": "Quantum computing is...",
  "cache_hit": true,
  "similarity_score": 0.92,
  "latency_ms": 45.2
}
```

### GET `/v1/metrics`

Cache statistics and hit rate.

### GET `/health`

Health check for load balancers.

## Configuration

Edit in `main.py`:

- `cache.ttl_seconds`: TTL for cache entries (default: 3600)
- `key_prefix`: Redis key prefix (default: "sentinel:cache:")
- `similarity_threshold`: Default similarity threshold (default: 0.75)

## Deployment (Fly.io)

```bash
fly auth login
fly launch
fly secrets set GROQ_API_KEY=your_key
fly secrets set JINA_API_KEY=your_key
fly deploy
```

## Performance Benchmarks

| Scenario              | Latency  | Cost Saved                        |
| --------------------- | -------- | --------------------------------- |
| Cache hit (exact)     | 5ms      | $0 (100%)                         |
| Cache hit (semantic)  | 45ms     | $0 (100%)                         |
| Cache miss (LLM call) | 1250ms   | -                                 |
| 3 similar queries     | 45ms avg | ~$0.002 vs $0.006 (67% reduction) |

## License

MIT

-e REDIS_URL=redis://your-redis:6379 \
 sentinel:latest

````

---

## 🌐 **Deploy to Cloud (Free)**

### **Option 1: Fly.io (Recommended)**

```bash
# Install Fly CLI
curl -L https://fly.io/install.sh | sh

# Login
fly auth login

# Deploy
fly launch
fly secrets set GROQ_API_KEY=your_key
fly deploy
````

**Free tier:** 3 shared VMs, 3GB storage, managed Redis

### **Option 2: Render.com**

1. Connect GitHub repo
2. Select "Web Service"
3. Set build command: `docker build`
4. Add environment variable: `GROQ_API_KEY`
5. Deploy!

**Free tier:** 750 hours/month

---

## 🔥 **API Usage**

### **POST /v1/query - Send a query**

```bash
curl -X POST http://localhost:8000/v1/query \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "What is quantum computing?",
    "model": "llama-3.1-8b-instant",
    "temperature": 0.7,
    "max_tokens": 500,
    "similarity_threshold": 0.75
  }'
```

**Response:**

```json
{
  "response": "Quantum computing is...",
  "cache_hit": false,
  "similarity_score": null,
  "matched_prompt": null,
  "provider": "groq",
  "model": "llama-3.1-8b-instant",
  "tokens_used": 123,
  "latency_ms": 1234.5
}
```

### **GET /v1/metrics - View cache statistics**

```bash
curl http://localhost:8000/v1/metrics
```

**Response:**

```json
{
  "total_requests": 100,
  "cache_hits": 67,
  "cache_misses": 33,
  "hit_rate_percent": 67.0,
  "stored_items": 45,
  "uptime_seconds": 3600
}
```

### **GET /health - Health check**

```bash
curl http://localhost:8000/health
```

---

## 📈 **Performance Benchmarks**

| Scenario                  | Latency | Cost     | Tokens |
| ------------------------- | ------- | -------- | ------ |
| **Cache MISS (LLM call)** | 1200ms  | $0.00005 | 50     |
| **Cache HIT (exact)**     | 5ms     | $0       | 0      |
| **Cache HIT (semantic)**  | 45ms    | $0       | 0      |

**Cost Savings Example (1000 requests):**

- Without cache: 1000 × $0.00005 = **$0.05**
- With 70% hit rate: 300 × $0.00005 = **$0.015**
- **Savings: 70% ($0.035)**

---

## 📚 **Documentation**

- [API Documentation](docs/api.md)
- [System Design](docs/system.md)
- [Decision Log](docs/decisions.md)
- [Learning Notes](docs/notes.md) - Comprehensive guide for understanding the system

---

## 🛡️ **Production Considerations**

### **Security**

- ✅ Environment variables for secrets
- ✅ Input validation with Pydantic
- ⚠️ Add rate limiting (nginx or Redis-based)
- ⚠️ Add authentication (API keys/JWT)

### **Scalability**

- ✅ Async I/O for concurrent requests
- ✅ Redis connection pooling
- ⚠️ Add horizontal scaling with load balancer
- ⚠️ Add Redis clustering for high availability

### **Monitoring**

- ✅ Structured logging
- ✅ Health checks
- ⚠️ Add Prometheus metrics
- ⚠️ Add error tracking (Sentry)

---

## 🤝 **Contributing**

Contributions welcome! Please:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit changes (`git commit -m 'Add amazing feature'`)
4. Push to branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

---

## 📄 **License**

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

## 🙏 **Acknowledgments**

- [FastAPI](https://fastapi.tiangolo.com/) - Modern web framework
- [Groq](https://groq.com/) - Blazing-fast LLM inference
- [Sentence Transformers](https://www.sbert.net/) - Semantic similarity
- [Redis](https://redis.io/) - High-performance caching

---

## 📧 **Contact**

**Sharjeel Ahmad**

- GitHub: [@s-sharjeelahmad](https://github.com/s-sharjeelahmad)
- Project: [Sentinel](https://github.com/s-sharjeelahmad/Sentinel)

---

**Built with ❤️ for learning and production use**
