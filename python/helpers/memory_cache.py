"""Embedding cache module with LRU caching and SHA-256 text hashing.

This module provides an EmbeddingCache class that caches embedding computations
to avoid redundant API calls. It uses SHA-256 hashing for text keys and
implements LRU (Least Recently Used) eviction when the cache reaches capacity.
"""

import hashlib
from collections import OrderedDict
from typing import Callable, Dict, List, Tuple


class EmbeddingCache:
    """Embedding cache using LRU caching with text hashing.

    This class wraps an embedding function and caches its results to avoid
    redundant computations. Long texts are hashed using SHA-256 to ensure
    hashability and consistent key sizes.

    Attributes:
        _embed_fn: The embedding function to wrap.
        _cache: OrderedDict storing cached embeddings (LRU order).
        _maxsize: Maximum number of entries in the cache.
        _hits: Number of cache hits.
        _misses: Number of cache misses.

    Example:
        >>> def my_embed_fn(text: str) -> List[float]:
        ...     return [0.1, 0.2, 0.3]  # Simulated embedding
        >>> cache = EmbeddingCache(my_embed_fn, maxsize=100)
        >>> embedding = cache.get_embedding("Hello world")
        >>> info = cache.cache_info()
        >>> print(info['size'])
        1
    """

    def __init__(self, embed_fn: Callable[[str], List[float]], maxsize: int = 1000):
        """Initialize the embedding cache.

        Args:
            embed_fn: A callable that takes a string and returns a list of floats
                     representing the embedding vector.
            maxsize: Maximum number of embeddings to cache. Defaults to 1000.

        Raises:
            ValueError: If maxsize is less than 1.
        """
        if maxsize < 1:
            raise ValueError("maxsize must be at least 1")

        self._embed_fn = embed_fn
        self._cache: OrderedDict[str, Tuple[float, ...]] = OrderedDict()
        self._maxsize = maxsize
        self._hits = 0
        self._misses = 0

    def _hash_text(self, text: str) -> str:
        """Hash text using SHA-256 to ensure hashability.

        This converts potentially long texts into fixed-size hash keys,
        ensuring consistent cache key sizes regardless of input length.

        Args:
            text: The text to hash.

        Returns:
            A hexadecimal string representation of the SHA-256 hash.
        """
        return hashlib.sha256(text.encode('utf-8')).hexdigest()

    def get_embedding(self, text: str) -> List[float]:
        """Get embedding for text, using cache if available.

        If the embedding for the given text is already cached, returns the
        cached result. Otherwise, computes the embedding using the wrapped
        function, caches it, and returns the result.

        Args:
            text: The text to get an embedding for.

        Returns:
            A list of floats representing the embedding vector.

        Note:
            Empty text will still be processed and cached.
        """
        text_hash = self._hash_text(text)

        if text_hash in self._cache:
            self._hits += 1
            # Move to end to mark as recently used
            self._cache.move_to_end(text_hash)
            return list(self._cache[text_hash])

        self._misses += 1

        # Compute new embedding
        embedding = self._embed_fn(text)

        # Store as tuple for immutability
        self._cache[text_hash] = tuple(embedding)

        # LRU eviction: remove oldest if over capacity
        if len(self._cache) > self._maxsize:
            self._cache.popitem(last=False)

        return embedding

    def cache_info(self) -> Dict[str, int]:
        """Return cache statistics.

        Returns:
            A dictionary containing:
                - size: Current number of cached entries.
                - maxsize: Maximum cache capacity.
                - hits: Number of cache hits.
                - misses: Number of cache misses.
        """
        return {
            "size": len(self._cache),
            "maxsize": self._maxsize,
            "hits": self._hits,
            "misses": self._misses,
        }

    def cache_clear(self) -> None:
        """Clear the cache and reset statistics.

        This removes all cached embeddings and resets hit/miss counters to zero.
        """
        self._cache.clear()
        self._hits = 0
        self._misses = 0

    def __contains__(self, text: str) -> bool:
        """Check if an embedding for the given text is cached.

        Args:
            text: The text to check.

        Returns:
            True if the embedding is cached, False otherwise.
        """
        text_hash = self._hash_text(text)
        return text_hash in self._cache

    def __len__(self) -> int:
        """Return the current number of cached entries."""
        return len(self._cache)
