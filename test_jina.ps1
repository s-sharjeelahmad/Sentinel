# Test Jina Embeddings Integration

$uri = "http://localhost:8000/v1/query"
$cache_uri = "http://localhost:8000/v1/cache"
$test_uri = "http://localhost:8000/v1/cache/test-embeddings"

Write-Host "=== SEMANTIC CACHING TEST WITH JINA API ===" -ForegroundColor Cyan
Write-Host ""

# Clear cache
Write-Host "Step 1: Clear cache..." -ForegroundColor Yellow
$clear_response = Invoke-RestMethod -Uri "$cache_uri/clear" -Method DELETE
Write-Host "Cleared: $($clear_response.deleted_keys) keys"
Write-Host ""

# Test 1: First query (cache miss)
Write-Host "Step 2: First query (cache miss)..." -ForegroundColor Cyan
$body1 = @{
    prompt               = "What is machine learning?"
    model                = "llama-3.1-8b-instant"
    temperature          = 0.7
    max_tokens           = 100
    similarity_threshold = 0.75
    provider             = "groq"
} | ConvertTo-Json

try {
    $response1 = Invoke-RestMethod -Uri $uri -Method POST -Body $body1 -ContentType 'application/json'
    Write-Host "Cache Hit: $($response1.cache_hit)"
    Write-Host "Response length: $($response1.response.Length) chars"
    if ($response1.error) {
        Write-Host "ERROR: $($response1.error)" -ForegroundColor Red
    }
}
catch {
    Write-Host "ERROR: $($_)" -ForegroundColor Red
}
Write-Host ""

# Show cache
Write-Host "Step 3: Check cache storage..." -ForegroundColor Yellow
Start-Sleep -Seconds 1
try {
    $cache_info = Invoke-RestMethod -Uri "$cache_uri/all" -Method GET
    Write-Host "Total cached: $($cache_info.total_cached)"
    Write-Host "Embeddings stored: $($cache_info.embeddings_stored)"
    if ($cache_info.cached_items) {
        foreach ($item in $cache_info.cached_items) {
            Write-Host "  Prompt: '$($item.prompt)'"
            Write-Host "  Embedding: $($item.embedding_type), dtype: $($item.embedding_dtype)"
        }
    }
}
catch {
    Write-Host "ERROR getting cache: $_" -ForegroundColor Red
}
Write-Host ""

# Test 2: Exact match
Write-Host "Step 4: Test exact match..." -ForegroundColor Green
Start-Sleep -Seconds 1
try {
    $response2 = Invoke-RestMethod -Uri $uri -Method POST -Body $body1 -ContentType 'application/json'
    Write-Host "Cache Hit: $($response2.cache_hit)"
    Write-Host "Similarity: $($response2.similarity_score)"
}
catch {
    Write-Host "ERROR: $_" -ForegroundColor Red
}
Write-Host ""

# Test 3: Debug similarity scores
Write-Host "Step 5: Debug similarity scores..." -ForegroundColor Yellow
Start-Sleep -Seconds 1
$debug_body = @{
    prompt               = "Tell me about machine learning concepts"
    model                = "llama-3.1-8b-instant"
    temperature          = 0.7
    max_tokens           = 100
    similarity_threshold = 0.75
    provider             = "groq"
} | ConvertTo-Json

try {
    $debug_response = Invoke-RestMethod -Uri $test_uri -Method POST -Body $debug_body -ContentType 'application/json'
    if ($debug_response.error) {
        Write-Host "ERROR: $($debug_response.error)" -ForegroundColor Red
    }
    else {
        Write-Host "Query: $($debug_response.query_prompt)"
        Write-Host "Embedding dimension: $($debug_response.query_embedding_dim)"
        Write-Host "Threshold: $($debug_response.similarity_threshold)"
        Write-Host ""
        Write-Host "Similarity scores:"
        foreach ($score in $debug_response.similarity_scores) {
            $status = if ($score.above_threshold) { "PASS" } else { "FAIL" }
            $sim = [Math]::Round($score.similarity, 3)
            Write-Host "  $sim - $($score.cached_prompt) [$status]"
        }
    }
}
catch {
    Write-Host "ERROR: $_" -ForegroundColor Red
}
Write-Host ""

# Test 4: Semantic match
Write-Host "Step 6: Test semantic match..." -ForegroundColor Green
Start-Sleep -Seconds 1
try {
    $response3 = Invoke-RestMethod -Uri $uri -Method POST -Body $debug_body -ContentType 'application/json'
    Write-Host "Cache Hit: $($response3.cache_hit)"
    Write-Host "Similarity: $($response3.similarity_score)"
}
catch {
    Write-Host "ERROR: $_" -ForegroundColor Red
}
Write-Host ""

# Final result
Write-Host "=== SUMMARY ===" -ForegroundColor Cyan
if ($response2.cache_hit -and $response3.cache_hit) {
    Write-Host "SUCCESS: Both exact and semantic matching work!" -ForegroundColor Green
}
elseif ($response2.cache_hit) {
    Write-Host "Exact match: OK" -ForegroundColor Green
    Write-Host "Semantic match: NOT WORKING - Check similarity scores above" -ForegroundColor Yellow
}
else {
    Write-Host "FAILED: Check logs and Jina API key" -ForegroundColor Red
}
