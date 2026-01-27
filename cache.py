"""
Sentinel Cache Layer
Exact-match in-memory cache for LLM responses.
"""

from typing import Optional


class ExactMatchCache:
    """
    In-memory cache using exact string matching.
    
    v0: Simple dictionary-based cache for exact matches.
    v1 (future): Replace with semantic embeddings for fuzzy matching.
    """
    
    def __init__(self) -> None:
        """Initialize empty cache with hit/miss counters."""
        self._cache: dict[str, str] = {}
        self._hits: int = 0
        self._misses: int = 0
    
    def get(self, prompt: str) -> tuple[Optional[str], bool]:
        """
        Retrieve cached response if prompt exists.
        
        Args:
            prompt: The user's query
            
        Returns:
            (response_text, is_hit)
            - response_text: Cached response or None if not found
            - is_hit: True if found in cache, False otherwise
        """
        if prompt in self._cache:
            self._hits += 1
            return self._cache[prompt], True
        
        self._misses += 1
        return None, False
    
    def set(self, prompt: str, response: str) -> None:
        """Store a prompt-response pair in cache."""
        self._cache[prompt] = response
    
    def stats(self) -> dict:
        """Return cache statistics for monitoring."""
        total = self._hits + self._misses
        hit_rate = (self._hits / total * 100) if total > 0 else 0
        
        return {
            "total_requests": total,
            "cache_hits": self._hits,
            "cache_misses": self._misses,
            "hit_rate_percent": round(hit_rate, 2),
            "stored_items": len(self._cache),
        }
