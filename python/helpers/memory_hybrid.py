"""Hybrid retrieval module combining FTS5 full-text search and vector similarity.

This module provides a HybridRetriever class that combines results from FTS5
full-text search and sqlite-vec vector search using weighted scoring and
Reciprocal Rank Fusion (RRF) for optimal retrieval performance.
"""

import sqlite3
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from python.helpers.memory_fts import FTS5Manager
from python.helpers.memory_sqlite_vec import VectorStore, SQLITE_VEC_AVAILABLE


class HybridRetrieverError(Exception):
    """Base exception for HybridRetriever errors."""
    pass


class HybridRetriever:
    """Hybrid retriever combining FTS5 and vector search.

    This class provides a unified interface for hybrid retrieval that combines
    lexical (FTS5) and semantic (vector) search results. It supports multiple
    fusion strategies including weighted scoring and Reciprocal Rank Fusion (RRF).

    Attributes:
        _fts_manager: FTS5Manager instance for full-text search.
        _vector_store: VectorStore instance for vector similarity search.
        _embed_fn: Optional function to generate embeddings from text.

    Example:
        >>> import sqlite3
        >>> conn = sqlite3.connect(':memory:')
        >>> fts = FTS5Manager(conn)
        >>> fts.create_index()
        >>> vec = VectorStore(conn, dimensions=384)
        >>> vec.create_index()
        >>> hybrid = HybridRetriever(fts, vec)
        >>> # Insert content with both FTS and vector
        >>> fts.insert('Hello world', metadata='greeting', rowid=1)
        >>> vec.insert(1, [0.1] * 384)
        >>> # Hybrid search
        >>> results = hybrid.search('hello', [0.1] * 384, k=5)
    """

    def __init__(
        self,
        fts_manager: FTS5Manager,
        vector_store: VectorStore,
        embed_fn: Optional[Callable[[str], List[float]]] = None
    ):
        """Initialize the HybridRetriever.

        Args:
            fts_manager: FTS5Manager instance for full-text search.
            vector_store: VectorStore instance for vector search.
            embed_fn: Optional function that takes text and returns embedding vector.
                     If provided, enables text-only search by auto-generating embeddings.

        Raises:
            ValueError: If fts_manager or vector_store is None.
        """
        if fts_manager is None:
            raise ValueError("fts_manager cannot be None")
        if vector_store is None:
            raise ValueError("vector_store cannot be None")

        self._fts_manager = fts_manager
        self._vector_store = vector_store
        self._embed_fn = embed_fn

    def search(
        self,
        query: str,
        query_embedding: Optional[List[float]] = None,
        k: int = 10,
        fts_weight: float = 0.3,
        vec_weight: float = 0.7,
        fusion_method: str = "weighted"
    ) -> List[Dict[str, Any]]:
        """Perform hybrid search combining FTS5 and vector results.

        Executes both FTS5 full-text search and vector KNN search, then combines
        the results using the specified fusion method.

        Args:
            query: Text query for FTS5 search.
            query_embedding: Vector embedding for similarity search. If None and
                           embed_fn was provided, generates embedding from query.
            k: Number of results to return. Defaults to 10.
            fts_weight: Weight for FTS5 results (0.0 to 1.0). Defaults to 0.3.
            vec_weight: Weight for vector results (0.0 to 1.0). Defaults to 0.7.
            fusion_method: Method for combining results:
                          - "weighted": Weighted score combination (default)
                          - "rrf": Reciprocal Rank Fusion

        Returns:
            List of dictionaries containing:
                - rowid: The row identifier
                - score: Combined relevance score (higher is better)
                - fts_score: Normalized FTS5 score (if matched)
                - vec_score: Normalized vector score (if matched)
                - source: List of sources ("fts", "vec", or both)

        Note:
            If one search type returns no results, returns results from the other.
            If both return no results, returns an empty list.
        """
        # Handle empty query
        if not query and query_embedding is None:
            return []

        # Generate embedding if needed and possible
        if query_embedding is None and self._embed_fn is not None and query:
            query_embedding = self._embed_fn(query)

        # Retrieve more results than needed for better fusion
        fetch_k = k * 2

        # Execute searches
        fts_results = self._search_fts(query, fetch_k) if query else []
        vec_results = self._search_vec(query_embedding, fetch_k) if query_embedding else []

        # Handle edge cases where one search returns no results
        if not fts_results and not vec_results:
            return []
        if not fts_results:
            return self._format_vec_only_results(vec_results, k)
        if not vec_results:
            return self._format_fts_only_results(fts_results, k)

        # Fuse results
        if fusion_method == "rrf":
            combined = self._reciprocal_rank_fusion(fts_results, vec_results, k=60)
        else:
            combined = self._weighted_fusion(
                fts_results, vec_results, fts_weight, vec_weight
            )

        # Return top k results
        return combined[:k]

    def search_fts_only(
        self,
        query: str,
        k: int = 10
    ) -> List[Dict[str, Any]]:
        """Perform FTS5-only search.

        Args:
            query: Text query for full-text search.
            k: Number of results to return.

        Returns:
            List of result dictionaries with normalized scores.
        """
        if not query:
            return []

        fts_results = self._search_fts(query, k)
        return self._format_fts_only_results(fts_results, k)

    def search_vec_only(
        self,
        query_embedding: List[float],
        k: int = 10
    ) -> List[Dict[str, Any]]:
        """Perform vector-only search.

        Args:
            query_embedding: Vector embedding for similarity search.
            k: Number of results to return.

        Returns:
            List of result dictionaries with normalized scores.
        """
        if not query_embedding:
            return []

        vec_results = self._search_vec(query_embedding, k)
        return self._format_vec_only_results(vec_results, k)

    def _search_fts(self, query: str, limit: int) -> List[Dict[str, Any]]:
        """Execute FTS5 search.

        Args:
            query: Text query.
            limit: Maximum results to return.

        Returns:
            List of FTS5 results with rowid and rank.
        """
        return self._fts_manager.search(query, limit=limit)

    def _search_vec(
        self,
        query_embedding: List[float],
        k: int
    ) -> List[Dict[str, Any]]:
        """Execute vector KNN search.

        Args:
            query_embedding: Query vector.
            k: Number of neighbors to find.

        Returns:
            List of vector results with rowid and distance.
        """
        return self._vector_store.search(query_embedding, k=k)

    def _normalize_fts_scores(
        self,
        results: List[Dict[str, Any]]
    ) -> List[Tuple[int, float]]:
        """Normalize FTS5 BM25 scores to 0-1 range.

        BM25 scores are negative (lower is better), so we invert and normalize.

        Args:
            results: FTS5 search results.

        Returns:
            List of (rowid, normalized_score) tuples where higher is better.
        """
        if not results:
            return []

        # BM25 scores are negative, lower (more negative) is better
        ranks = [r["rank"] for r in results]
        min_rank = min(ranks)
        max_rank = max(ranks)

        normalized = []
        for r in results:
            if max_rank == min_rank:
                # All same score, give equal weight
                score = 1.0
            else:
                # Invert and normalize: best rank (most negative) -> 1.0
                score = (max_rank - r["rank"]) / (max_rank - min_rank)
            normalized.append((r["rowid"], score))

        return normalized

    def _normalize_vec_scores(
        self,
        results: List[Dict[str, Any]]
    ) -> List[Tuple[int, float]]:
        """Normalize vector distances to 0-1 scores.

        Distances are positive (lower is better), so we invert and normalize.

        Args:
            results: Vector search results.

        Returns:
            List of (rowid, normalized_score) tuples where higher is better.
        """
        if not results:
            return []

        distances = [r["distance"] for r in results]
        min_dist = min(distances)
        max_dist = max(distances)

        normalized = []
        for r in results:
            if max_dist == min_dist:
                # All same distance, give equal weight
                score = 1.0
            else:
                # Invert: smallest distance -> highest score
                score = 1.0 - (r["distance"] - min_dist) / (max_dist - min_dist)
            normalized.append((r["rowid"], score))

        return normalized

    def _weighted_fusion(
        self,
        fts_results: List[Dict[str, Any]],
        vec_results: List[Dict[str, Any]],
        fts_weight: float,
        vec_weight: float
    ) -> List[Dict[str, Any]]:
        """Combine results using weighted score fusion.

        Args:
            fts_results: FTS5 search results.
            vec_results: Vector search results.
            fts_weight: Weight for FTS5 scores.
            vec_weight: Weight for vector scores.

        Returns:
            List of combined results sorted by weighted score.
        """
        # Normalize scores
        fts_normalized = dict(self._normalize_fts_scores(fts_results))
        vec_normalized = dict(self._normalize_vec_scores(vec_results))

        # Get all unique rowids
        all_rowids = set(fts_normalized.keys()) | set(vec_normalized.keys())

        # Calculate weighted scores
        combined = []
        for rowid in all_rowids:
            fts_score = fts_normalized.get(rowid, 0.0)
            vec_score = vec_normalized.get(rowid, 0.0)

            # Weighted combination
            total_score = (fts_weight * fts_score) + (vec_weight * vec_score)

            sources = []
            if rowid in fts_normalized:
                sources.append("fts")
            if rowid in vec_normalized:
                sources.append("vec")

            combined.append({
                "rowid": rowid,
                "score": total_score,
                "fts_score": fts_score,
                "vec_score": vec_score,
                "source": sources
            })

        # Sort by combined score (descending)
        combined.sort(key=lambda x: x["score"], reverse=True)
        return combined

    def _reciprocal_rank_fusion(
        self,
        fts_results: List[Dict[str, Any]],
        vec_results: List[Dict[str, Any]],
        k: int = 60
    ) -> List[Dict[str, Any]]:
        """Combine results using Reciprocal Rank Fusion (RRF).

        RRF score = sum(1 / (k + rank_i)) for each result list.
        This method is effective for combining ranking signals from
        different retrieval systems.

        Args:
            fts_results: FTS5 search results (assumed already ranked).
            vec_results: Vector search results (assumed already ranked by distance).
            k: RRF constant (default 60, as per original RRF paper).

        Returns:
            List of combined results sorted by RRF score.
        """
        scores: Dict[int, Dict[str, Any]] = {}

        # Process FTS results (already ranked by BM25)
        for rank, result in enumerate(fts_results):
            rowid = result["rowid"]
            rrf_score = 1.0 / (k + rank + 1)

            if rowid not in scores:
                scores[rowid] = {
                    "rowid": rowid,
                    "score": 0.0,
                    "fts_score": 0.0,
                    "vec_score": 0.0,
                    "source": []
                }

            scores[rowid]["score"] += rrf_score
            scores[rowid]["fts_score"] = rrf_score
            scores[rowid]["source"].append("fts")

        # Process vector results (already ranked by distance, ascending)
        for rank, result in enumerate(vec_results):
            rowid = result["rowid"]
            rrf_score = 1.0 / (k + rank + 1)

            if rowid not in scores:
                scores[rowid] = {
                    "rowid": rowid,
                    "score": 0.0,
                    "fts_score": 0.0,
                    "vec_score": 0.0,
                    "source": []
                }

            scores[rowid]["score"] += rrf_score
            scores[rowid]["vec_score"] = rrf_score
            if "vec" not in scores[rowid]["source"]:
                scores[rowid]["source"].append("vec")

        # Sort by RRF score (descending)
        combined = list(scores.values())
        combined.sort(key=lambda x: x["score"], reverse=True)
        return combined

    def _format_fts_only_results(
        self,
        fts_results: List[Dict[str, Any]],
        k: int
    ) -> List[Dict[str, Any]]:
        """Format FTS-only results to match hybrid output format.

        Args:
            fts_results: FTS5 search results.
            k: Maximum results to return.

        Returns:
            List of formatted results.
        """
        normalized = self._normalize_fts_scores(fts_results)

        results = []
        for rowid, score in normalized[:k]:
            results.append({
                "rowid": rowid,
                "score": score,
                "fts_score": score,
                "vec_score": 0.0,
                "source": ["fts"]
            })

        return results

    def _format_vec_only_results(
        self,
        vec_results: List[Dict[str, Any]],
        k: int
    ) -> List[Dict[str, Any]]:
        """Format vector-only results to match hybrid output format.

        Args:
            vec_results: Vector search results.
            k: Maximum results to return.

        Returns:
            List of formatted results.
        """
        normalized = self._normalize_vec_scores(vec_results)

        results = []
        for rowid, score in normalized[:k]:
            results.append({
                "rowid": rowid,
                "score": score,
                "fts_score": 0.0,
                "vec_score": score,
                "source": ["vec"]
            })

        return results

    def insert(
        self,
        rowid: int,
        content: str,
        embedding: List[float],
        metadata: str = ""
    ) -> None:
        """Insert content into both FTS5 and vector stores.

        Convenience method for adding content to both search indexes atomically.

        Args:
            rowid: Integer row identifier (must be unique).
            content: Text content for FTS5 indexing.
            embedding: Vector embedding for similarity search.
            metadata: Optional metadata for FTS5.

        Raises:
            ValueError: If rowid already exists in either store.
        """
        # Insert into FTS5
        self._fts_manager.insert(content, metadata=metadata, rowid=rowid)

        # Insert into vector store
        self._vector_store.insert(rowid, embedding)

    def insert_with_embedding(
        self,
        rowid: int,
        content: str,
        metadata: str = ""
    ) -> None:
        """Insert content and auto-generate embedding.

        Requires embed_fn to be set during initialization.

        Args:
            rowid: Integer row identifier.
            content: Text content to index.
            metadata: Optional metadata.

        Raises:
            HybridRetrieverError: If embed_fn is not configured.
        """
        if self._embed_fn is None:
            raise HybridRetrieverError(
                "Cannot auto-generate embeddings: embed_fn not configured"
            )

        embedding = self._embed_fn(content)
        self.insert(rowid, content, embedding, metadata)

    def delete(self, rowid: int) -> bool:
        """Delete content from both FTS5 and vector stores.

        Args:
            rowid: The rowid to delete.

        Returns:
            True if deleted from at least one store, False if not found.
        """
        fts_deleted = self._fts_manager.delete(rowid)
        vec_deleted = self._vector_store.delete(rowid)
        return fts_deleted or vec_deleted

    def get_content(self, rowid: int) -> Optional[Dict[str, Any]]:
        """Retrieve content by rowid from FTS5 store.

        Args:
            rowid: The rowid to look up.

        Returns:
            Dictionary with content and metadata if found, None otherwise.
        """
        return self._fts_manager.get_by_rowid(rowid)

    def count(self) -> Dict[str, int]:
        """Return counts from both stores.

        Returns:
            Dictionary with 'fts' and 'vec' counts.
        """
        return {
            "fts": self._fts_manager.count(),
            "vec": self._vector_store.count()
        }

    def clear(self) -> None:
        """Clear all content from both stores."""
        self._fts_manager.clear()
        self._vector_store.clear()

    @property
    def fts_manager(self) -> FTS5Manager:
        """Return the FTS5Manager instance."""
        return self._fts_manager

    @property
    def vector_store(self) -> VectorStore:
        """Return the VectorStore instance."""
        return self._vector_store

    @property
    def has_embed_fn(self) -> bool:
        """Return whether an embedding function is configured."""
        return self._embed_fn is not None

    def __repr__(self) -> str:
        """Return a string representation of the HybridRetriever."""
        return (
            f"HybridRetriever("
            f"fts={self._fts_manager.table_name}, "
            f"vec={self._vector_store.table_name}, "
            f"embed_fn={'set' if self._embed_fn else 'none'})"
        )
