# Deploy Sentinel with Jina Integration to Fly.io

Write-Host "=== DEPLOYING SENTINEL WITH JINA EMBEDDINGS ===" -ForegroundColor Cyan
Write-Host ""

# Step 1: Set Jina API key secret
Write-Host "Step 1: Setting Jina API key in Fly.io secrets..." -ForegroundColor Yellow
$jinaKey = "jina_1cfa5bba8c4e460c859759792f7758e8Zt-xSkG53KLxYXEfEBKAI-ewYoqb"

# Check if fly CLI is available
$flyCmd = Get-Command fly -ErrorAction SilentlyContinue
if (-not $flyCmd) {
    Write-Host "ERROR: 'fly' command not found. Install Fly CLI first:" -ForegroundColor Red
    Write-Host "  Run: powershell -Command 'iwr https://fly.io/install.ps1 -useb | iex'"
    exit 1
}

# Set secrets
try {
    fly secrets set JINA_API_KEY="$jinaKey" --app sentinel-ai-gateway
    Write-Host "✓ Jina API key set" -ForegroundColor Green
} catch {
    Write-Host "ERROR setting secret: $_" -ForegroundColor Red
    exit 1
}
Write-Host ""

# Step 2: Deploy
Write-Host "Step 2: Deploying to Fly.io..." -ForegroundColor Yellow
try {
    fly deploy --app sentinel-ai-gateway
    Write-Host "✓ Deployed successfully" -ForegroundColor Green
} catch {
    Write-Host "ERROR deploying: $_" -ForegroundColor Red
    exit 1
}
Write-Host ""

# Step 3: Wait for app to start
Write-Host "Step 3: Waiting for app to start..." -ForegroundColor Yellow
Start-Sleep -Seconds 10
Write-Host ""

# Step 4: Test semantic matching
Write-Host "Step 4: Testing semantic matching..." -ForegroundColor Cyan
$baseUrl = "https://sentinel-ai-gateway.fly.dev"

# Clear cache first
Write-Host "Clearing cache..." -ForegroundColor Yellow
try {
    $clearResp = Invoke-RestMethod -Uri "$baseUrl/v1/cache/clear" -Method DELETE
    Write-Host "✓ Cleared $($clearResp.deleted_keys) keys"
} catch {
    Write-Host "Note: Cache clear endpoint may not exist on old deployment"
}
Write-Host ""

# Test query 1
Write-Host "Query 1: 'What is machine learning?' (cache miss)..." -ForegroundColor Cyan
$body1 = @{
    prompt = "What is machine learning?"
    model = "llama-3.1-8b-instant"
    temperature = 0.7
    max_tokens = 100
    similarity_threshold = 0.75
    provider = "groq"
} | ConvertTo-Json

try {
    $resp1 = Invoke-RestMethod -Uri "$baseUrl/v1/query" -Method POST -Body $body1 -ContentType 'application/json'
    Write-Host "✓ Cache Hit: $($resp1.cache_hit)"
    Write-Host "  Response length: $($resp1.response.Length) chars"
} catch {
    Write-Host "ERROR: $_" -ForegroundColor Red
}
Write-Host ""

# Wait a bit
Start-Sleep -Seconds 2

# Test query 2 - Exact match
Write-Host "Query 2: Same prompt (exact match)..." -ForegroundColor Cyan
try {
    $resp2 = Invoke-RestMethod -Uri "$baseUrl/v1/query" -Method POST -Body $body1 -ContentType 'application/json'
    Write-Host "✓ Cache Hit: $($resp2.cache_hit) (expected: TRUE)"
    Write-Host "  Similarity: $($resp2.similarity_score)"
} catch {
    Write-Host "ERROR: $_" -ForegroundColor Red
}
Write-Host ""

# Wait a bit
Start-Sleep -Seconds 2

# Test query 3 - Semantic match
Write-Host "Query 3: 'Tell me about ML' (semantic match)..." -ForegroundColor Yellow
$body3 = @{
    prompt = "Tell me about ML"
    model = "llama-3.1-8b-instant"
    temperature = 0.7
    max_tokens = 100
    similarity_threshold = 0.75
    provider = "groq"
} | ConvertTo-Json

try {
    $resp3 = Invoke-RestMethod -Uri "$baseUrl/v1/query" -Method POST -Body $body3 -ContentType 'application/json'
    Write-Host "✓ Cache Hit: $($resp3.cache_hit) (expected: TRUE for semantic match)"
    Write-Host "  Similarity: $($resp3.similarity_score)"
    if ($resp3.matched_prompt) {
        Write-Host "  Matched: '$($resp3.matched_prompt)'"
    }
} catch {
    Write-Host "ERROR: $_" -ForegroundColor Red
}
Write-Host ""

# Final verdict
Write-Host "=== RESULT ===" -ForegroundColor Cyan
if ($resp2.cache_hit -and $resp3.cache_hit) {
    Write-Host "✅ SUCCESS! Both exact and semantic matching work on production!" -ForegroundColor Green
} elseif ($resp2.cache_hit) {
    Write-Host "⚠️  Exact match works, but semantic match failed" -ForegroundColor Yellow
    Write-Host "   This might be due to low similarity score (threshold: 0.75)" -ForegroundColor Yellow
    Write-Host "   Try with lower threshold (0.6) or more similar prompts" -ForegroundColor Yellow
} else {
    Write-Host "❌ FAILED - Check Fly.io logs for errors" -ForegroundColor Red
    Write-Host "   Run: fly logs --app sentinel-ai-gateway" -ForegroundColor Yellow
}
