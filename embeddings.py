"""
Sentinel Embeddings Module
Convert text to semantic embeddings for similarity comparison.

Uses Hugging Face Inference API (external, no local model needed).
"""

import logging
import os
import aiohttp
from typing import Optional
import numpy as np

logger = logging.getLogger(__name__)


class EmbeddingModel:
    """
    Wrapper for Hugging Face Inference API embeddings.
    
    Purpose:
    - Convert prompts to embedding vectors via API
    - Compare embeddings via cosine similarity
    - Support semantic caching (find similar cached responses)
    
    Advantages:
    - No local model storage (saves 90MB)
    - Instant startup (no model download)
    - Works on 256MB Fly.io machine
    - Free tier available (HuggingFace account)
    """
    
    def __init__(self, model_name: str = "sentence-transformers/all-MiniLM-L6-v2"):
        """
        Initialize Hugging Face Inference API embeddings.
        
        Args:
            model_name: HF model identifier (using API endpoint)
        """
        self.model_name = model_name
        self.api_token = os.getenv("HF_API_TOKEN")
        if not self.api_token:
            raise ValueError("HF_API_TOKEN environment variable required for embeddings API")
        
        self.api_url = f"https://api-inference.huggingface.co/models/{model_name}"
        self.embedding_dim = 384  # all-MiniLM-L6-v2 dimension
        self.session: Optional[aiohttp.ClientSession] = None
    
    async def load(self) -> None:
        """Initialize async session."""
        try:
            self.session = aiohttp.ClientSession()
            logger.info(f"✅ Embedding model configured (HF API: {self.model_name})")
        except Exception as e:
            logger.error(f"❌ Failed to configure embedding model: {e}")
            raise
    
    async def embed(self, text: str) -> np.ndarray:
        """
        Convert text to embedding vector via HF Inference API.
        
        Args:
            text: The text to embed (prompt or cached response)
            
        Returns:
            numpy array of shape (384,) for all-MiniLM-L6-v2
            
        Example:
            embedding = await model.embed("What is machine learning?")
            # embedding.shape = (384,)
        """
        if not self.session:
            raise RuntimeError("Model not loaded. Call load() first.")
        
        try:
            headers = {"Authorization": f"Bearer {self.api_token}"}
            payload = {"inputs": text}
            
            async with self.session.post(self.api_url, json=payload, headers=headers) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    raise Exception(f"API error {resp.status}: {error_text}")
                
                result = await resp.json()
                
            # API returns list of embeddings (one per input)
            if isinstance(result, list) and len(result) > 0:
                embedding = np.array(result[0], dtype=np.float32)
            else:
                raise ValueError(f"Unexpected API response: {result}")
            
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
