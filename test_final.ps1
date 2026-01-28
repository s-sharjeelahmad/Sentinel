# Simple semantic matching test with working model

$uri = "http://localhost:8000/v1/query"
$cache_uri = "http://localhost:8000/v1/cache"
$test_uri = "http://localhost:8000/v1/cache/test-embeddings"

Write-Host "=== SEMANTIC MATCHING TEST ===" -ForegroundColor Cyan
Write-Host ""

# Clear cache first
Write-Host "Step 1: Clearing cache..." -ForegroundColor Yellow
$clear_response = Invoke-RestMethod -Uri "$cache_uri/clear" -Method DELETE
Write-Host "✓ Cache cleared: $($clear_response.deleted_keys) keys removed"
Write-Host ""

# Test 1: Cache miss - first query
Write-Host "Step 2: First query (cache miss)..." -ForegroundColor Cyan
$body1 = @{
    prompt = "What is machine learning?"
    model = "llama-3.1-8b-instant"
    temperature = 0.7
    max_tokens = 100
    similarity_threshold = 0.75
    provider = "groq"
} | ConvertTo-Json

$response1 = Invoke-RestMethod -Uri $uri -Method POST -Body $body1 -ContentType 'application/json'
Write-Host "Cache Hit: $($response1.cache_hit) (expected: FALSE)"
if ($response1.error) {
    Write-Host "ERROR: $($response1.error)"
} else {
    Write-Host "Response length: $($response1.response.Length) chars"
}
Write-Host ""

# Wait and show cached items
Write-Host "Step 3: Checking what's in cache..." -ForegroundColor Yellow
Start-Sleep -Seconds 1
$cache_info = Invoke-RestMethod -Uri "$cache_uri/all" -Method GET
Write-Host "Total cached: $($cache_info.total_cached)"
Write-Host "Embeddings stored: $($cache_info.embeddings_stored)"
if ($cache_info.cached_items) {
    foreach ($item in $cache_info.cached_items) {
        Write-Host "  ✓ Prompt: '$($item.prompt)'"
        Write-Host "    Embedding: $($item.embedding_type) | Shape: $($item.embedding_shape) | Dtype: $($item.embedding_dtype)"
    }
}
Write-Host ""

# Test 2: Exact match
Write-Host "Step 4: Testing exact match (same prompt)..." -ForegroundColor Cyan
Start-Sleep -Seconds 1
$body2 = @{
    prompt = "What is machine learning?"
    model = "llama-3.1-8b-instant"
    temperature = 0.7
    max_tokens = 100
    similarity_threshold = 0.75
    provider = "groq"
} | ConvertTo-Json

$response2 = Invoke-RestMethod -Uri $uri -Method POST -Body $body2 -ContentType 'application/json'
Write-Host "Cache Hit: $($response2.cache_hit) (expected: TRUE)" -ForegroundColor ([bool]$response2.cache_hit ? 'Green' : 'Red')
Write-Host "Similarity Score: $($response2.similarity_score) (expected: 1.0)"
Write-Host ""

# Test 3: DEBUG - Check similarity scores for similar prompt
Write-Host "Step 5: Debug - Checking similarity scores..." -ForegroundColor Yellow
Start-Sleep -Seconds 1
$debug_body = @{
    prompt = "Tell me about machine learning concepts"
    model = "llama-3.1-8b-instant"
    temperature = 0.7
    max_tokens = 100
    similarity_threshold = 0.75
    provider = "groq"
} | ConvertTo-Json

$debug_response = Invoke-RestMethod -Uri $test_uri -Method POST -Body $debug_body -ContentType 'application/json'
if ($debug_response.error) {
    Write-Host "ERROR: $($debug_response.error)"
} else {
    Write-Host "Query: '$($debug_response.query_prompt)'"
    Write-Host "Query embedding: $($debug_response.query_embedding_dim) dimensions"
    Write-Host "Threshold: $($debug_response.similarity_threshold)"
    Write-Host ""
    Write-Host "Similarity vs cached items:"
    foreach ($score in $debug_response.similarity_scores) {
        $status = if ($score.above_threshold) { "✅ ABOVE" } else { "❌ below" }
        $simScore = "{0:F3}" -f $score.similarity
        Write-Host "  $simScore - '$($score.cached_prompt)' $status"
    }
}
Write-Host ""

# Test 4: Actual semantic match
Write-Host "Step 6: Testing semantic match (similar prompt)..." -ForegroundColor Yellow
Start-Sleep -Seconds 1
$body3 = @{
    prompt = "Tell me about machine learning concepts"
    model = "llama-3.1-8b-instant"
    temperature = 0.7
    max_tokens = 100
    similarity_threshold = 0.75
    provider = "groq"
} | ConvertTo-Json

$response3 = Invoke-RestMethod -Uri $uri -Method POST -Body $body3 -ContentType 'application/json'
Write-Host "Cache Hit: $($response3.cache_hit)" -ForegroundColor ([bool]$response3.cache_hit ? 'Green' : 'Red')
Write-Host "Similarity Score: $($response3.similarity_score)"
if ($response3.matched_prompt) {
    Write-Host "Matched Prompt: '$($response3.matched_prompt)'"
}
Write-Host ""

# Final result
Write-Host "=== FINAL RESULT ===" -ForegroundColor Cyan
if ($response2.cache_hit -eq $true -and $response3.cache_hit -eq $true) {
    Write-Host "✅ BOTH EXACT AND SEMANTIC MATCHING WORK!" -ForegroundColor Green
} elseif ($response2.cache_hit -eq $true) {
    Write-Host "✓ Exact matching works" -ForegroundColor Green
    Write-Host "❌ Semantic matching NOT working" -ForegroundColor Red
    Write-Host "   Check similarity scores above - they may be below threshold" -ForegroundColor Yellow
} else {
    Write-Host "❌ Even exact matching not working" -ForegroundColor Red
    Write-Host "   Check cache storage" -ForegroundColor Yellow
}
