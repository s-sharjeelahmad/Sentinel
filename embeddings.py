"""
Sentinel Embeddings Module
Convert text to semantic embeddings for similarity comparison.

Uses Jina Embeddings API (free tier, enterprise-grade reliability).
"""

import logging
import os
import aiohttp
from typing import Optional
import numpy as np

logger = logging.getLogger(__name__)


class EmbeddingModel:
    """
    Wrapper for Jina Embeddings API.
    
    Purpose:
    - Convert prompts to embedding vectors via remote API
    - Compare embeddings via cosine similarity
    - Support semantic caching (find similar cached responses)
    
    Advantages:
    - Reliable, enterprise-grade service
    - Free tier: 1M tokens/month (more than enough for MVP)
    - Zero maintenance, no self-hosting
    - Fast, accurate embeddings
    - Works on 256MB Fly.io machine
    """
    
    def __init__(self, model_name: str = "jina-embeddings-v3"):
        """
        Initialize Jina Embeddings API.
        
        Args:
            model_name: Jina model identifier (jina-embeddings-v3, jina-embeddings-v2-base-en, etc.)
        """
        self.model_name = model_name
        self.api_token = os.getenv("JINA_API_KEY")
        if not self.api_token:
            raise ValueError("JINA_API_KEY environment variable required for embeddings API")
        
        self.api_url = "https://api.jina.ai/v1/embeddings"
        self.embedding_dim = 1024  # jina-embeddings-v3 dimension
        self.session: Optional[aiohttp.ClientSession] = None
    
    async def load(self) -> None:
        """Initialize async session."""
        try:
            self.session = aiohttp.ClientSession()
            logger.info(f"✅ Embedding model configured (Jina API: {self.model_name})")
        except Exception as e:
            logger.error(f"❌ Failed to configure embedding model: {e}")
            raise
    
    async def embed(self, text: str) -> np.ndarray:
        """
        Convert text to embedding vector via Jina API.
        
        Args:
            text: The text to embed (prompt or cached response)
            
        Returns:
            numpy array of shape (1024,) for jina-embeddings-v3
            
        Example:
            embedding = await model.embed("What is machine learning?")
            # embedding.shape = (1024,)
        """
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
        """
        Compute cosine similarity between two embeddings.
        
        Range: [-1, 1]
        - 1.0 = identical vectors (perfect match)
        - 0.5 = somewhat similar
        - 0.0 = orthogonal (no similarity)
        - -1.0 = opposite direction (rare in practice)
        
        Args:
            embedding1: First embedding vector
            embedding2: Second embedding vector
            
        Returns:
            Cosine similarity score (0.0 to 1.0 in practice)
            
        Example:
            emb1 = await model.embed("What is AI?")
            emb2 = await model.embed("Tell me about AI")
            score = model.cosine_similarity(emb1, emb2)
            # score ≈ 0.95 (very similar!)
        """
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
        """
        Find best matching cached embedding above threshold.
        
        Args:
            query_embedding: Embedding of current prompt
            cached_embeddings: List of {"embedding": np.ndarray, "prompt": str, "response": str}
            threshold: Minimum similarity to consider a match (0.0 to 1.0)
            
        Returns:
            Dict with best match: {"embedding": ..., "prompt": ..., "response": ..., "similarity": float}
            Or None if no match above threshold
            
        Example:
            match = model.find_similar(query_embedding, cached_embeddings, threshold=0.75)
            if match:
                print(f"Found similar cached response (similarity={match['similarity']:.2f})")
                return match["response"]
        """
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
