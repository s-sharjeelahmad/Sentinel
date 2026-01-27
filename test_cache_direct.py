"""Quick inline test of the Sentinel cache without HTTP."""

# Import the cache directly from main.py
from main import ExactMatchCache

print("=" * 60)
print("SENTINEL CACHE TEST - Direct Python Testing")
print("=" * 60)

# Create cache instance
cache = ExactMatchCache()

# Test 1: Cache miss
print("\n[Test 1] First request (CACHE MISS expected)")
print("-" * 60)
response1, is_hit1 = cache.get("What is quantum computing?")
print(f"  Prompt: 'What is quantum computing?'")
print(f"  Cache Hit: {is_hit1}")
print(f"  Response: {response1}")
print(f"  ✓ Expected: Hit=False, Response=None")

# Test 2: Store in cache
print("\n[Test 2] Store response in cache")
print("-" * 60)
cache.set("What is quantum computing?", "Quantum computing uses quantum bits...")
print(f"  Stored: 'What is quantum computing?' -> 'Quantum computing uses...'")
print(f"  ✓ Response cached")

# Test 3: Cache hit
print("\n[Test 3] Second request with same prompt (CACHE HIT expected)")
print("-" * 60)
response2, is_hit2 = cache.get("What is quantum computing?")
print(f"  Prompt: 'What is quantum computing?'")
print(f"  Cache Hit: {is_hit2}")
print(f"  Response: {response2}")
print(f"  ✓ Expected: Hit=True, Response='Quantum computing uses...'")

# Test 4: Different prompt (cache miss)
print("\n[Test 4] Different prompt (CACHE MISS expected)")
print("-" * 60)
response3, is_hit3 = cache.get("Explain machine learning")
print(f"  Prompt: 'Explain machine learning'")
print(f"  Cache Hit: {is_hit3}")
print(f"  Response: {response3}")
print(f"  ✓ Expected: Hit=False, Response=None")

# Test 5: Store another response
print("\n[Test 5] Store another response")
print("-" * 60)
cache.set("Explain machine learning", "Machine learning is a subset of AI...")
print(f"  Stored: 'Explain machine learning' -> 'Machine learning is...'")
print(f"  ✓ Response cached")

# Test 6: Cache hit for second prompt
print("\n[Test 6] Retrieve second cached prompt (CACHE HIT expected)")
print("-" * 60)
response4, is_hit4 = cache.get("Explain machine learning")
print(f"  Prompt: 'Explain machine learning'")
print(f"  Cache Hit: {is_hit4}")
print(f"  Response: {response4}")
print(f"  ✓ Expected: Hit=True, Response='Machine learning is...'")

# Test 7: Show metrics
print("\n[Test 7] Cache metrics")
print("-" * 60)
stats = cache.stats()
print(f"  Total Requests: {stats['total_requests']}")
print(f"  Cache Hits: {stats['cache_hits']}")
print(f"  Cache Misses: {stats['cache_misses']}")
print(f"  Hit Rate: {stats['hit_rate_percent']}%")
print(f"  Stored Items: {stats['stored_items']}")

# Verify results
print("\n" + "=" * 60)
print("TEST RESULTS SUMMARY")
print("=" * 60)

all_pass = (
    is_hit1 == False and  # First should miss (1st request)
    is_hit2 == True and   # Same prompt should hit (2nd request)
    is_hit3 == False and  # Different prompt should miss (3rd request)
    is_hit4 == True and   # Second prompt should hit (4th request)
    stats['cache_hits'] == 2 and
    stats['cache_misses'] == 2 and
    stats['stored_items'] == 2
)

if all_pass:
    print("✅ ALL TESTS PASSED!")
    print("  - Cache miss/hit logic works correctly")
    print("  - Metrics tracking is accurate")
    print("  - Storage is working")
else:
    print("❌ TESTS FAILED!")
    print(f"  Hits: {is_hit1}, {is_hit2}, {is_hit3}, {is_hit4}")
    print(f"  Stats: {stats}")

print("=" * 60)
