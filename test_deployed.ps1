# Quick diagnostic test for deployed Sentinel

$baseUrl = "https://sentinel-ai-gateway.fly.dev"

Write-Host "=== SEMANTIC MATCHING DIAGNOSTIC TEST ===" -ForegroundColor Cyan
Write-Host ""

# Test with VERY similar prompts and lower threshold
Write-Host "Test 1: First query..." -ForegroundColor Yellow
$body1 = @{
    prompt = "What is artificial intelligence?"
    model = "llama-3.1-8b-instant"
    temperature = 0.7
    max_tokens = 50
    similarity_threshold = 0.65
    provider = "groq"
} | ConvertTo-Json

try {
    $resp1 = Invoke-RestMethod -Uri "$baseUrl/v1/query" -Method POST -Body $body1 -ContentType 'application/json' -TimeoutSec 30
    Write-Host "Cache Hit: $($resp1.cache_hit) (expected: FALSE - first query)"
    if ($resp1.error) {
        Write-Host "ERROR: $($resp1.error)" -ForegroundColor Red
        exit
    }
} catch {
    Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "Response: $($_.Exception.Response)" -ForegroundColor Red
    exit
}
Write-Host ""

Start-Sleep -Seconds 3

# Test 2: Very similar prompt
Write-Host "Test 2: Very similar prompt (lower threshold 0.65)..." -ForegroundColor Yellow
$body2 = @{
    prompt = "What is AI?"
    model = "llama-3.1-8b-instant"
    temperature = 0.7
    max_tokens = 50
    similarity_threshold = 0.65
    provider = "groq"
} | ConvertTo-Json

try {
    $resp2 = Invoke-RestMethod -Uri "$baseUrl/v1/query" -Method POST -Body $body2 -ContentType 'application/json' -TimeoutSec 30
    Write-Host "Cache Hit: $($resp2.cache_hit)"
    Write-Host "Similarity Score: $($resp2.similarity_score)"
    if ($resp2.matched_prompt) {
        Write-Host "Matched Prompt: '$($resp2.matched_prompt)'"
    }
    
    if ($resp2.cache_hit) {
        Write-Host ""
        Write-Host "✅ SEMANTIC MATCHING WORKS!" -ForegroundColor Green
        Write-Host "   Similarity: $($resp2.similarity_score)" -ForegroundColor Green
    } else {
        Write-Host ""
        Write-Host "❌ Semantic matching NOT working" -ForegroundColor Red
        Write-Host "   Possible reasons:" -ForegroundColor Yellow
        Write-Host "   1. Jina API key not set in Fly.io" -ForegroundColor Yellow
        Write-Host "   2. Embeddings failing (check logs)" -ForegroundColor Yellow
        Write-Host "   3. Old code deployed (missing await fix)" -ForegroundColor Yellow
    }
} catch {
    Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
}
