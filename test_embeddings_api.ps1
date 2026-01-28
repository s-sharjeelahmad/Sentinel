# Test LightweightEmbeddings API
$body = @{
    input = "What is machine learning?"
    model = "bge-m3"
} | ConvertTo-Json

Write-Host "Testing LightweightEmbeddings API..." -ForegroundColor Cyan

try {
    $response = Invoke-RestMethod -Uri "https://lh0x00-lightweight-embeddings.hf.space/v1/embeddings" -Method POST -Body $body -ContentType "application/json" -TimeoutSec 30
    Write-Host "SUCCESS!" -ForegroundColor Green
    Write-Host "Response has data: $($response.data -ne $null)"
    Write-Host "Embedding dimension: $($response.data[0].embedding.Count)"
}
catch {
    Write-Host "FAILED!" -ForegroundColor Red
    Write-Host "Error: $_"
    Write-Host "Status: $($_.Exception.Response.StatusCode)"
}
