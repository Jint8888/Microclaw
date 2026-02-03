"""sqlite-vec vector storage module for embedding storage and KNN queries.

This module provides a VectorStore class that integrates with sqlite-vec extension
for storing and querying vector embeddings. It uses the enable->load->disable pattern
for secure extension loading and supports KNN (K-Nearest Neighbors) queries.

Note: This module prefers pysqlite3-binary over standard sqlite3 because
pysqlite3-binary includes SQLite with extension loading support enabled.
"""

# Try pysqlite3 first (has extension loading support)
# Fall back to standard sqlite3 if not available
try:
    import pysqlite3 as sqlite3
    PYSQLITE3_AVAILABLE = True
except ImportError:
    import sqlite3
    PYSQLITE3_AVAILABLE = False

from typing import Any, Dict, List, Optional, Tuple, Union

try:
    import sqlite_vec
    from sqlite_vec import serialize_float32
    SQLITE_VEC_AVAILABLE = True
except ImportError:
    SQLITE_VEC_AVAILABLE = False
    sqlite_vec = None
    serialize_float32 = None



class VectorStoreError(Exception):
    """Base exception for VectorStore errors."""
    pass


class ExtensionNotAvailableError(VectorStoreError):
    """Raised when sqlite-vec extension is not available."""
    pass


class DatabaseNotInitializedError(VectorStoreError):
    """Raised when attempting operations before initialization."""
    pass


class VectorStore:
    """Vector storage using sqlite-vec for embedding storage and KNN queries.

    This class provides an interface for storing and querying vector embeddings
    using the sqlite-vec extension. It follows the secure initialization pattern:
    enable_load_extension -> load -> disable_load_extension.

    Attributes:
        _conn: SQLite database connection with sqlite-vec loaded.
        _table_name: Name of the vec0 virtual table.
        _dimensions: Number of dimensions in the embedding vectors.
        _initialized: Whether the store has been initialized.

    Example:
        >>> import sqlite3
        >>> conn = sqlite3.connect(':memory:')
        >>> store = VectorStore(conn, dimensions=384)
        >>> store.create_index()
        >>> store.insert(1, [0.1, 0.2, 0.3, ...])  # 384-dim vector
        >>> results = store.search([0.1, 0.2, 0.3, ...], k=5)
        >>> print(len(results))
        1
    """

    def __init__(
        self,
        conn: Optional[sqlite3.Connection] = None,
        db_path: str = ":memory:",
        table_name: str = "memory_vec",
        dimensions: int = 384
    ):
        """Initialize the VectorStore.

        Args:
            conn: Existing SQLite connection. If None, creates a new connection.
            db_path: Path to SQLite database file. Used only if conn is None.
                    Defaults to ':memory:' for in-memory database.
            table_name: Name for the vec0 virtual table. Defaults to 'memory_vec'.
            dimensions: Number of dimensions for embedding vectors. Defaults to 384.

        Raises:
            ExtensionNotAvailableError: If sqlite-vec is not installed.
            ValueError: If table_name is empty or dimensions < 1.
        """
        if not SQLITE_VEC_AVAILABLE:
            raise ExtensionNotAvailableError(
                "sqlite-vec extension is not available. "
                "Install it with: pip install sqlite-vec"
            )

        if not table_name:
            raise ValueError("table_name cannot be empty")

        if dimensions < 1:
            raise ValueError("dimensions must be at least 1")

        self._table_name = table_name
        self._dimensions = dimensions
        self._initialized = False

        # Create or use existing connection
        if conn is None:
            self._conn = sqlite3.connect(db_path)
            self._owns_connection = True
        else:
            self._conn = conn
            self._owns_connection = False

        # Load sqlite-vec extension using enable->load->disable pattern
        self._load_extension()

    def _load_extension(self) -> None:
        """Load the sqlite-vec extension securely.

        Uses the enable->load->disable pattern for security:
        1. Enable extension loading
        2. Load sqlite-vec
        3. Disable extension loading to prevent further modifications

        Raises:
            VectorStoreError: If extension loading fails.
        """
        try:
            self._conn.enable_load_extension(True)
            sqlite_vec.load(self._conn)
            self._conn.enable_load_extension(False)  # Security: disable after loading
            self._initialized = True
        except Exception as e:
            raise VectorStoreError(f"Failed to load sqlite-vec extension: {e}")

    def create_index(self) -> None:
        """Create the vec0 virtual table for vector storage.

        Creates a vec0 virtual table with the configured dimensions.
        This method is idempotent - calling it multiple times is safe.

        Raises:
            DatabaseNotInitializedError: If the extension is not loaded.
        """
        self._ensure_initialized()

        cursor = self._conn.cursor()
        cursor.execute(f"""
            CREATE VIRTUAL TABLE IF NOT EXISTS {self._table_name}
            USING vec0(embedding float[{self._dimensions}])
        """)
        self._conn.commit()

    def insert(self, rowid: int, embedding: List[float]) -> None:
        """Insert a vector into the store.

        Args:
            rowid: Integer row identifier. Must be unique.
            embedding: List of floats representing the embedding vector.
                      Must have exactly `dimensions` elements.

        Raises:
            DatabaseNotInitializedError: If the store is not initialized.
            ValueError: If embedding dimensions don't match.
            sqlite3.Error: If insertion fails (e.g., duplicate rowid).
        """
        self._ensure_initialized()
        self._validate_embedding(embedding)

        cursor = self._conn.cursor()
        cursor.execute(
            f"INSERT INTO {self._table_name} (rowid, embedding) VALUES (?, ?)",
            (rowid, serialize_float32(embedding))
        )
        self._conn.commit()

    def insert_batch(self, items: List[Tuple[int, List[float]]]) -> None:
        """Insert multiple vectors into the store.

        Args:
            items: List of (rowid, embedding) tuples.

        Raises:
            DatabaseNotInitializedError: If the store is not initialized.
            ValueError: If any embedding dimensions don't match.
            sqlite3.Error: If insertion fails.
        """
        self._ensure_initialized()

        cursor = self._conn.cursor()
        for rowid, embedding in items:
            self._validate_embedding(embedding)
            cursor.execute(
                f"INSERT INTO {self._table_name} (rowid, embedding) VALUES (?, ?)",
                (rowid, serialize_float32(embedding))
            )
        self._conn.commit()

    def search(
        self,
        query_embedding: List[float],
        k: int = 10
    ) -> List[Dict[str, Any]]:
        """Perform KNN search for similar vectors.

        Uses the MATCH operator with k parameter for efficient KNN queries.

        Args:
            query_embedding: The query vector to find similar vectors for.
            k: Number of nearest neighbors to return. Defaults to 10.

        Returns:
            List of dictionaries containing:
                - rowid: The row identifier
                - distance: Euclidean distance from query vector (lower is better)

        Raises:
            DatabaseNotInitializedError: If the store is not initialized.
            ValueError: If query embedding dimensions don't match.
        """
        self._ensure_initialized()
        self._validate_embedding(query_embedding)

        if k < 1:
            return []

        cursor = self._conn.cursor()
        cursor.execute(f"""
            SELECT rowid, distance
            FROM {self._table_name}
            WHERE embedding MATCH ?
            AND k = ?
        """, (serialize_float32(query_embedding), k))

        results = []
        for row in cursor.fetchall():
            results.append({
                "rowid": row[0],
                "distance": row[1]
            })

        return results

    def search_with_threshold(
        self,
        query_embedding: List[float],
        k: int = 10,
        max_distance: Optional[float] = None
    ) -> List[Dict[str, Any]]:
        """Perform KNN search with optional distance threshold.

        Args:
            query_embedding: The query vector to find similar vectors for.
            k: Maximum number of nearest neighbors to return.
            max_distance: Optional maximum distance threshold. Results with
                         distance greater than this are filtered out.

        Returns:
            List of result dictionaries (same format as search()).
        """
        results = self.search(query_embedding, k)

        if max_distance is not None:
            results = [r for r in results if r["distance"] <= max_distance]

        return results

    def delete(self, rowid: int) -> bool:
        """Delete a vector by its rowid.

        Args:
            rowid: The rowid of the vector to delete.

        Returns:
            True if a row was deleted, False if no row with that rowid exists.
        """
        self._ensure_initialized()

        cursor = self._conn.cursor()
        cursor.execute(
            f"DELETE FROM {self._table_name} WHERE rowid = ?",
            (rowid,)
        )
        self._conn.commit()
        return cursor.rowcount > 0

    def update(self, rowid: int, embedding: List[float]) -> bool:
        """Update a vector in the store.

        Note: vec0 tables may not support UPDATE directly. This implementation
        uses DELETE + INSERT as a fallback pattern.

        Args:
            rowid: The rowid of the vector to update.
            embedding: The new embedding vector.

        Returns:
            True if the update succeeded, False if no row with that rowid exists.
        """
        self._ensure_initialized()
        self._validate_embedding(embedding)

        # Check if row exists
        if not self.exists(rowid):
            return False

        # Delete and re-insert (vec0 update pattern)
        self.delete(rowid)
        self.insert(rowid, embedding)
        return True

    def exists(self, rowid: int) -> bool:
        """Check if a vector with the given rowid exists.

        Args:
            rowid: The rowid to check.

        Returns:
            True if a vector with that rowid exists, False otherwise.
        """
        self._ensure_initialized()

        cursor = self._conn.cursor()
        cursor.execute(
            f"SELECT 1 FROM {self._table_name} WHERE rowid = ?",
            (rowid,)
        )
        return cursor.fetchone() is not None

    def count(self) -> int:
        """Return the number of vectors in the store.

        Returns:
            The total number of stored vectors.
        """
        self._ensure_initialized()

        cursor = self._conn.cursor()
        cursor.execute(f"SELECT COUNT(*) FROM {self._table_name}")
        return cursor.fetchone()[0]

    def clear(self) -> None:
        """Delete all vectors from the store.

        This removes all stored vectors but keeps the table structure intact.
        """
        self._ensure_initialized()

        cursor = self._conn.cursor()
        cursor.execute(f"DELETE FROM {self._table_name}")
        self._conn.commit()

    def drop(self) -> None:
        """Drop the vec0 virtual table.

        This permanently removes the table and all stored vectors.
        """
        self._ensure_initialized()

        cursor = self._conn.cursor()
        cursor.execute(f"DROP TABLE IF EXISTS {self._table_name}")
        self._conn.commit()

    def get_version(self) -> str:
        """Get the sqlite-vec extension version.

        Returns:
            Version string of the sqlite-vec extension.
        """
        self._ensure_initialized()

        cursor = self._conn.cursor()
        cursor.execute("SELECT vec_version()")
        return cursor.fetchone()[0]

    def table_exists(self) -> bool:
        """Check if the vec0 table exists.

        Returns:
            True if the table exists, False otherwise.
        """
        self._ensure_initialized()

        cursor = self._conn.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (self._table_name,)
        )
        return cursor.fetchone() is not None

    def _ensure_initialized(self) -> None:
        """Ensure the store is initialized before operations.

        Raises:
            DatabaseNotInitializedError: If the store is not initialized.
        """
        if not self._initialized:
            raise DatabaseNotInitializedError(
                "VectorStore is not initialized. "
                "The sqlite-vec extension may not have loaded correctly."
            )

    def _validate_embedding(self, embedding: List[float]) -> None:
        """Validate embedding dimensions.

        Args:
            embedding: The embedding to validate.

        Raises:
            ValueError: If embedding dimensions don't match expected dimensions.
        """
        if len(embedding) != self._dimensions:
            raise ValueError(
                f"Embedding has {len(embedding)} dimensions, "
                f"expected {self._dimensions}"
            )

    def close(self) -> None:
        """Close the database connection if owned by this instance.

        Only closes the connection if it was created by this VectorStore instance.
        If an external connection was provided, it is left open.
        """
        if self._owns_connection and self._conn:
            self._conn.close()
            self._conn = None
            self._initialized = False

    @property
    def table_name(self) -> str:
        """Return the vec0 table name."""
        return self._table_name

    @property
    def dimensions(self) -> int:
        """Return the number of embedding dimensions."""
        return self._dimensions

    @property
    def connection(self) -> sqlite3.Connection:
        """Return the SQLite connection."""
        return self._conn

    @property
    def is_initialized(self) -> bool:
        """Return whether the store is initialized."""
        return self._initialized

    def __len__(self) -> int:
        """Return the number of stored vectors."""
        return self.count()

    def __contains__(self, rowid: int) -> bool:
        """Check if a vector with the given rowid exists."""
        return self.exists(rowid)

    def __repr__(self) -> str:
        """Return a string representation of the VectorStore."""
        return (
            f"VectorStore(table='{self._table_name}', "
            f"dimensions={self._dimensions}, "
            f"initialized={self._initialized})"
        )

    def __enter__(self) -> "VectorStore":
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit - closes connection if owned."""
        self.close()
