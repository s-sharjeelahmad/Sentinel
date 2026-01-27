"""
Sentinel Embeddings Module
Convert text to semantic embeddings for similarity comparison.
"""

import logging
from typing import Optional
import numpy as np

logger = logging.getLogger(__name__)


class EmbeddingModel:
    """
    Wrapper for transformers-based embedding model.
    
    Purpose:
    - Convert prompts to embedding vectors
    - Compare embeddings via cosine similarity
    - Support semantic caching (find similar cached responses)
    
    Model Choice:
    - "sentence-transformers/all-MiniLM-L6-v2" via HF transformers
    - 384 dimensions, ~60MB, fast (on CPU)
    - Accuracy: Good for general Q&A
    - Tradeoff: Speed vs accuracy (could use larger models if needed)
    """
    
    def __init__(self, model_name: str = "sentence-transformers/all-MiniLM-L6-v2"):
        """
        Initialize embedding model.
        
        Args:
            model_name: Hugging Face model identifier
        """
        self.model_name = model_name
        self.model = None
        self.tokenizer = None
        self.embedding_dim = 384  # Dimension of embeddings from all-MiniLM-L6-v2
    
    def load(self) -> None:
        """Load model and tokenizer from disk or download first time."""
        try:
            from transformers import AutoModel, AutoTokenizer
            logger.info(f"Loading embedding model: {self.model_name}")
            self.tokenizer = AutoTokenizer.from_pretrained(self.model_name)
            self.model = AutoModel.from_pretrained(self.model_name)
            logger.info(f"✅ Embedding model loaded ({self.embedding_dim} dimensions)")
        except Exception as e:
            logger.error(f"❌ Failed to load embedding model: {e}")
            raise
    
    def embed(self, text: str) -> np.ndarray:
        """
        Convert text to embedding vector.
        
        Args:
            text: The text to embed (prompt or cached response)
            
        Returns:
            numpy array of shape (384,) for all-MiniLM-L6-v2
            
        Example:
            embedding = model.embed("What is machine learning?")
            # embedding.shape = (384,)
        """
        if not self.model or not self.tokenizer:
            raise RuntimeError("Model not loaded. Call load() first.")
        
        try:
            import torch
            # Tokenize
            inputs = self.tokenizer(text, return_tensors="pt", truncation=True, max_length=128)
            # Compute embeddings (mean pooling of token embeddings)
            with torch.no_grad():
                outputs = self.model(**inputs)
                # Mean pooling: average all token embeddings
                embeddings = outputs.last_hidden_state.mean(dim=1)
            
            return embeddings[0].numpy()
        except Exception as e:
            logger.error(f"Error embedding text: {e}")
            raise
    
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
            emb1 = model.embed("What is AI?")
            emb2 = model.embed("Tell me about AI")
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
