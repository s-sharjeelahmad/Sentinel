"""Embeddings via Jina API - Semantic caching support."""

import logging
import os
import aiohttp
from typing import Optional
import numpy as np

logger = logging.getLogger(__name__)


class EmbeddingModel:
    """Jina Embeddings API wrapper."""
    
    def __init__(self, model_name: str = "jina-embeddings-v3"):
        self.model_name = model_name
        self.api_token = os.getenv("JINA_API_KEY")
        if not self.api_token:
            raise ValueError("JINA_API_KEY environment variable required")
        
        self.api_url = "https://api.jina.ai/v1/embeddings"
        self.embedding_dim = 1024
        self.session: Optional[aiohttp.ClientSession] = None
    
    async def load(self) -> None:
        """Initialize async session."""
        try:
            self.session = aiohttp.ClientSession()
            logger.info(f"✅ Embedding model configured (Jina: {self.model_name})")
        except Exception as e:
            logger.error(f"❌ Failed to configure embedding model: {e}")
            raise
    
    async def embed(self, text: str) -> np.ndarray:
        """Convert text to embedding vector.
        if not self.session:
            raise RuntimeError("Model not loaded. Call load() first.")
        
        try:
            headers = {
                "Authorization": f"Bearer {self.api_token}",
                "Content-Type": "application/json"
            }
            payload = {
                "input": [text],  # Jina accepts list of strings
                "model": self.model_name
            }
            
            async with self.session.post(self.api_url, json=payload, headers=headers, timeout=30) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    raise Exception(f"Jina API error {resp.status}: {error_text}")
                
                result = await resp.json()
                
            # Jina returns: {"data": [{"embedding": [...], "index": 0, "object": "embedding"}]}
            if isinstance(result, dict) and "data" in result and len(result["data"]) > 0:
                embedding_data = result["data"][0]["embedding"]
                embedding = np.array(embedding_data, dtype=np.float32)
            else:
                raise ValueError(f"Unexpected API response format: {result}")
            
            return embedding
        except Exception as e:
            logger.error(f"Error embedding text: {e}")
            raise
    
    async def close(self) -> None:
        """Close async session."""
        if self.session:
            await self.session.close()
    
    def cosine_similarity(self, embedding1: np.ndarray, embedding2: np.ndarray) -> float:
        """Compute cosine similarity between two embeddings [-1, 1]."""
        # Cosine similarity = (A · B) / (||A|| × ||B||)
        # numpy handles this efficiently
        dot_product = np.dot(embedding1, embedding2)
        norm1 = np.linalg.norm(embedding1)
        norm2 = np.linalg.norm(embedding2)
        
        if norm1 == 0 or norm2 == 0:
            return 0.0
        
        similarity = dot_product / (norm1 * norm2)
        return float(similarity)  # Convert to Python float
    
    def find_similar(
        self,
        query_embedding: np.ndarray,
        cached_embeddings: list[dict],
        threshold: float = 0.75,
    ) -> Optional[dict]:
        """Find best cached embedding above threshold, returns dict with embedding, prompt, response, and similarity score."""
        if not cached_embeddings:
            return None
        
        best_match = None
        best_similarity = 0.0
        
        for item in cached_embeddings:
            similarity = self.cosine_similarity(query_embedding, item["embedding"])
            
            if similarity > best_similarity:
                best_similarity = similarity
                best_match = item
        
        # Return only if above threshold
        if best_similarity >= threshold:
            best_match["similarity"] = best_similarity
            return best_match
        
        return None


# Global embedding model instance
embedding_model = EmbeddingModel()
