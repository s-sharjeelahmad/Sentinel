# FIX: Semantic Matching Not Working on Deployed App

## Problem
Your deployed app is still using **OLD CODE** (HuggingFace embeddings that were failing).
The Jina integration only exists locally, not on Fly.io yet.

## Solution: Redeploy with Jina

### Option 1: Deploy with Fly CLI (Recommended)

```powershell
# 1. Set Jina API key secret
fly secrets set JINA_API_KEY="jina_1cfa5bba8c4e460c859759792f7758e8Zt-xSkG53KLxYXEfEBKAI-ewYoqb" --app sentinel-ai-gateway

# 2. Deploy
fly deploy --app sentinel-ai-gateway

# 3. Test
powershell -ExecutionPolicy Bypass -File test_deployed.ps1
```

### Option 2: Deploy via GitHub (if auto-deploy is set up)

```bash
git add .
git commit -m "fix: integrate Jina embeddings API for semantic caching"
git push origin main
```

Then wait 2-3 minutes for auto-deployment.

### Option 3: Manual Fly.io Dashboard

1. Go to https://fly.io/dashboard
2. Select **sentinel-ai-gateway** app
3. Click **Secrets** → Add secret:
   - Name: `JINA_API_KEY`
   - Value: `jina_1cfa5bba8c4e460c859759792f7758e8Zt-xSkG53KLxYXEfEBKAI-ewYoqb`
4. Click **Deploy** → Deploy from GitHub or upload Dockerfile

---

## Why Semantic Matching Fails Now

Your deployed app has:
- ❌ OLD embeddings.py (HuggingFace API - returns 410 error)
- ❌ No JINA_API_KEY secret
- ❌ Old code without the `await` fix

After redeploying with Jina:
- ✅ NEW embeddings.py (Jina API - works reliably)
- ✅ JINA_API_KEY set in secrets
- ✅ Embeddings generated and stored
- ✅ Semantic matching works

---

## Verify After Deployment

Run this to test:
```powershell
powershell -ExecutionPolicy Bypass -File test_deployed.ps1
```

Expected result:
```
Test 1: First query...
Cache Hit: False (expected: FALSE - first query)

Test 2: Very similar prompt (lower threshold 0.65)...
Cache Hit: True
Similarity Score: 0.87

✅ SEMANTIC MATCHING WORKS!
   Similarity: 0.87
```

---

**Next Step: Redeploy the app using one of the options above.**
