# Comprehensive test for semantic matching with debug endpoints

$uri = "http://localhost:8000/v1/query"
$cache_uri = "http://localhost:8000/v1/cache"
$test_uri = "http://localhost:8000/v1/cache/test-embeddings"

Write-Host "=== SEMANTIC MATCHING TEST WITH DEBUG ===" -ForegroundColor Cyan
Write-Host ""

# Clear cache first
Write-Host "Clearing cache..." -ForegroundColor Yellow
$clear_response = Invoke-RestMethod -Uri "$cache_uri/clear" -Method DELETE
Write-Host "Cache cleared: $($clear_response.deleted_keys) keys removed"
Write-Host ""

# Test 1: Cache miss - first query
Write-Host "TEST 1: Cache Miss (First Query)" -ForegroundColor Cyan
$body1 = @{
    prompt               = "What is machine learning?"
    model                = "mixtral-8x7b-32768"
    temperature          = 0.7
    max_tokens           = 100
    similarity_threshold = 0.75
    provider             = "groq"
} | ConvertTo-Json

$response1 = Invoke-RestMethod -Uri $uri -Method POST -Body $body1 -ContentType 'application/json'
Write-Host "Cache Hit: $($response1.cache_hit) (expected: FALSE)"
Write-Host "Response preview: $($response1.response.Substring(0, [Math]::Min(80, $response1.response.Length)))..."
Write-Host ""

# Show cached items
Write-Host "Checking cached items after first query..." -ForegroundColor Yellow
Start-Sleep -Seconds 1
$cache_info = Invoke-RestMethod -Uri "$cache_uri/all" -Method GET
Write-Host "Total cached: $($cache_info.total_cached)"
Write-Host "Embeddings stored: $($cache_info.embeddings_stored)"
foreach ($item in $cache_info.cached_items) {
    Write-Host "  - Prompt: '$($item.prompt)...'"
    Write-Host "    Embedding type: $($item.embedding_type), Shape: $($item.embedding_shape), Dtype: $($item.embedding_dtype)"
}
Write-Host ""

# Test 2: Exact match
Write-Host "TEST 2: Exact Match (Same Prompt)" -ForegroundColor Cyan
Start-Sleep -Seconds 1
$body2 = @{
    prompt               = "What is machine learning?"
    model                = "mixtral-8x7b-32768"
    temperature          = 0.7
    max_tokens           = 100
    similarity_threshold = 0.75
    provider             = "groq"
} | ConvertTo-Json

$response2 = Invoke-RestMethod -Uri $uri -Method POST -Body $body2 -ContentType 'application/json'
Write-Host "Cache Hit: $($response2.cache_hit) (expected: TRUE)"
Write-Host "Similarity Score: $($response2.similarity_score) (expected: 1.0)"
Write-Host ""

# Test 3: DEBUG - Check similarity scores
Write-Host "TEST 3: Debug Embedding Test (Similar Prompt)" -ForegroundColor Yellow
Start-Sleep -Seconds 1
$debug_body = @{
    prompt               = "Tell me about machine learning concepts"
    model                = "mixtral-8x7b-32768"
    temperature          = 0.7
    max_tokens           = 100
    similarity_threshold = 0.75
    provider             = "groq"
} | ConvertTo-Json

$debug_response = Invoke-RestMethod -Uri $test_uri -Method POST -Body $debug_body -ContentType 'application/json'
Write-Host "Query: '$($debug_response.query_prompt)'"
Write-Host "Query embedding dimension: $($debug_response.query_embedding_dim)"
Write-Host "Threshold: $($debug_response.similarity_threshold)"
Write-Host ""
Write-Host "Similarity Scores vs Cached Items:"
foreach ($score in $debug_response.similarity_scores) {
    $above = if ($score.above_threshold) { "✅ ABOVE THRESHOLD" } else { "❌ below threshold" }
    Write-Host "  - '$($score.cached_prompt)...': $([Math]::Round($score.similarity, 3)) $above"
}
Write-Host ""

# Test 4: Actual semantic match
Write-Host "TEST 4: SEMANTIC MATCH (Similar Prompt)" -ForegroundColor Yellow
Start-Sleep -Seconds 1
$body3 = @{
    prompt               = "Tell me about machine learning concepts"
    model                = "mixtral-8x7b-32768"
    temperature          = 0.7
    max_tokens           = 100
    similarity_threshold = 0.75
    provider             = "groq"
} | ConvertTo-Json

$response3 = Invoke-RestMethod -Uri $uri -Method POST -Body $body3 -ContentType 'application/json'
Write-Host "Cache Hit: $($response3.cache_hit)" -ForegroundColor Yellow
Write-Host "Similarity Score: $($response3.similarity_score)" -ForegroundColor Yellow
Write-Host "Matched Prompt: '$($response3.matched_prompt)'" -ForegroundColor Yellow
Write-Host ""

if ($response3.cache_hit -eq $true) {
    Write-Host "✅ SEMANTIC MATCHING WORKS!" -ForegroundColor Green
}
else {
    Write-Host "❌ Semantic matching NOT working" -ForegroundColor Red
    Write-Host "Check debug output above for similarity scores" -ForegroundColor Red
}
