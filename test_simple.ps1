# Test semantic matching with working endpoints

$uri = "http://localhost:8000/v1/query"
$cache_uri = "http://localhost:8000/v1/cache"
$test_uri = "http://localhost:8000/v1/cache/test-embeddings"

Write-Host "=== SEMANTIC MATCHING TEST ===" -ForegroundColor Cyan
Write-Host ""

# Clear cache first
Write-Host "Step 1: Clearing cache..." -ForegroundColor Yellow
$clear_response = Invoke-RestMethod -Uri "$cache_uri/clear" -Method DELETE
Write-Host "Cache cleared: $($clear_response.deleted_keys) keys removed"
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
Write-Host "Cache Hit: $($response1.cache_hit)"
if ($response1.error) {
    Write-Host "ERROR: $($response1.error)"
} else {
    Write-Host "Response length: $($response1.response.Length) chars"
}
Write-Host ""

# Show cached items
Write-Host "Step 3: Checking cache..." -ForegroundColor Yellow
Start-Sleep -Seconds 1
$cache_info = Invoke-RestMethod -Uri "$cache_uri/all" -Method GET
Write-Host "Total cached: $($cache_info.total_cached)"
Write-Host "Embeddings stored: $($cache_info.embeddings_stored)"
if ($cache_info.cached_items) {
    foreach ($item in $cache_info.cached_items) {
        Write-Host "  Prompt: '$($item.prompt)'"
        Write-Host "  Embedding: $($item.embedding_type), Shape: $($item.embedding_shape), Dtype: $($item.embedding_dtype)"
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
Write-Host "Cache Hit: $($response2.cache_hit) (expected: TRUE)"
Write-Host "Similarity Score: $($response2.similarity_score)"
Write-Host ""

# Test 3: DEBUG similarity scores
Write-Host "Step 5: Debug - Similarity scores..." -ForegroundColor Yellow
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
    Write-Host "Query: $($debug_response.query_prompt)"
    Write-Host "Threshold: $($debug_response.similarity_threshold)"
    foreach ($score in $debug_response.similarity_scores) {
        $status = if ($score.above_threshold) { "PASS" } else { "FAIL" }
        Write-Host "  $([Math]::Round($score.similarity, 3)) - $($score.cached_prompt) [$status]"
    }
}
Write-Host ""

# Test 4: Semantic match
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
Write-Host "Cache Hit: $($response3.cache_hit)"
Write-Host "Similarity Score: $($response3.similarity_score)"
Write-Host ""

# Final result
Write-Host "=== RESULTS ===" -ForegroundColor Cyan
Write-Host "Exact match (Test 2): $($response2.cache_hit)"
Write-Host "Semantic match (Test 4): $($response3.cache_hit)"
