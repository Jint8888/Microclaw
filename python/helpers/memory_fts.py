"""FTS5 full-text search module for memory indexing and querying.

This module provides an FTS5Manager class that manages SQLite FTS5 virtual tables
for full-text search capabilities. It supports content indexing, MATCH queries
with boolean operators, and ranked result retrieval.
"""

import sqlite3
from typing import Any, Dict, List, Optional, Tuple


class FTS5Manager:
    """Manager for FTS5 full-text search operations.

    This class provides an interface for creating and managing FTS5 virtual tables,
    indexing content, and performing full-text searches with ranking.

    Attributes:
        _conn: SQLite database connection.
        _table_name: Name of the FTS5 virtual table.
        _columns: List of column names in the FTS5 table.

    Example:
        >>> import sqlite3
        >>> conn = sqlite3.connect(':memory:')
        >>> fts = FTS5Manager(conn)
        >>> fts.create_index()
        >>> fts.insert('Hello world', metadata='greeting')
        >>> results = fts.search('hello')
        >>> print(len(results) > 0)
        True
    """

    def __init__(
        self,
        conn: sqlite3.Connection,
        table_name: str = "memory_fts",
        columns: Optional[List[str]] = None,
        tokenizer: str = "porter"
    ):
        """Initialize the FTS5Manager.

        Args:
            conn: SQLite database connection.
            table_name: Name for the FTS5 virtual table. Defaults to 'memory_fts'.
            columns: List of column names to index. Defaults to ['content', 'metadata'].
            tokenizer: FTS5 tokenizer to use. Defaults to 'porter' for stemming.

        Raises:
            ValueError: If table_name is empty or columns list is empty.
        """
        if not table_name:
            raise ValueError("table_name cannot be empty")

        self._conn = conn
        self._table_name = table_name
        self._columns = columns if columns else ["content", "metadata"]
        self._tokenizer = tokenizer

        if not self._columns:
            raise ValueError("columns list cannot be empty")

    def create_index(self) -> None:
        """Create the FTS5 virtual table if it doesn't exist.

        Creates an FTS5 virtual table with the configured columns and tokenizer.
        FTS5 tables do not support data types or PRIMARY KEY declarations.

        Note:
            This method is idempotent - calling it multiple times is safe.
        """
        columns_str = ", ".join(self._columns)
        cursor = self._conn.cursor()
        cursor.execute(f"""
            CREATE VIRTUAL TABLE IF NOT EXISTS {self._table_name}
            USING fts5({columns_str}, tokenize='{self._tokenizer}')
        """)
        self._conn.commit()

    def insert(self, content: str, metadata: str = "", rowid: Optional[int] = None) -> int:
        """Insert content into the FTS5 index.

        Args:
            content: The main text content to index.
            metadata: Optional metadata associated with the content.
            rowid: Optional explicit rowid. If not provided, SQLite auto-generates one.

        Returns:
            The rowid of the inserted row.

        Raises:
            sqlite3.Error: If insertion fails.
        """
        cursor = self._conn.cursor()

        if rowid is not None:
            cursor.execute(
                f"INSERT INTO {self._table_name} (rowid, content, metadata) VALUES (?, ?, ?)",
                (rowid, content, metadata)
            )
        else:
            cursor.execute(
                f"INSERT INTO {self._table_name} (content, metadata) VALUES (?, ?)",
                (content, metadata)
            )

        self._conn.commit()
        return cursor.lastrowid

    def insert_batch(self, items: List[Tuple[str, str]]) -> List[int]:
        """Insert multiple content items into the FTS5 index.

        Args:
            items: List of (content, metadata) tuples to insert.

        Returns:
            List of rowids for the inserted rows.

        Raises:
            sqlite3.Error: If insertion fails.
        """
        cursor = self._conn.cursor()
        rowids = []

        for content, metadata in items:
            cursor.execute(
                f"INSERT INTO {self._table_name} (content, metadata) VALUES (?, ?)",
                (content, metadata)
            )
            rowids.append(cursor.lastrowid)

        self._conn.commit()
        return rowids

    def search(
        self,
        query: str,
        limit: int = 10,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """Search the FTS5 index using MATCH operator.

        Performs a full-text search using FTS5's MATCH operator with BM25 ranking.
        Supports boolean operators (AND, OR, NOT) and phrase queries.

        Args:
            query: The search query. Supports FTS5 query syntax:
                   - Simple terms: 'hello world' (implicit AND)
                   - Boolean: 'hello OR world', 'hello NOT world'
                   - Phrase: '"hello world"'
                   - Prefix: 'hel*'
            limit: Maximum number of results to return. Defaults to 10.
            offset: Number of results to skip. Defaults to 0.

        Returns:
            List of dictionaries containing:
                - rowid: The row identifier
                - content: The indexed content
                - metadata: Associated metadata
                - rank: BM25 relevance score (lower is better)

        Note:
            Empty query strings return an empty list without raising an exception.
        """
        # Handle empty query gracefully
        if not query or not query.strip():
            return []

        cursor = self._conn.cursor()

        try:
            # Use bm25() for ranking - lower scores indicate better matches
            cursor.execute(f"""
                SELECT rowid, content, metadata, bm25({self._table_name}) as rank
                FROM {self._table_name}
                WHERE {self._table_name} MATCH ?
                ORDER BY rank
                LIMIT ? OFFSET ?
            """, (query, limit, offset))

            results = []
            for row in cursor.fetchall():
                results.append({
                    "rowid": row[0],
                    "content": row[1],
                    "metadata": row[2],
                    "rank": row[3]
                })

            return results

        except sqlite3.OperationalError as e:
            # Handle invalid FTS5 query syntax gracefully
            if "fts5: syntax error" in str(e).lower():
                return []
            raise

    def search_column(
        self,
        column: str,
        query: str,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Search a specific column in the FTS5 index.

        Args:
            column: The column name to search in.
            query: The search query.
            limit: Maximum number of results to return.

        Returns:
            List of result dictionaries (same format as search()).

        Raises:
            ValueError: If the column name is not in the indexed columns.
        """
        if column not in self._columns:
            raise ValueError(f"Column '{column}' not in indexed columns: {self._columns}")

        # Use column filter syntax: column:query
        column_query = f"{column}:{query}"
        return self.search(column_query, limit=limit)

    def delete(self, rowid: int) -> bool:
        """Delete a row from the FTS5 index.

        Args:
            rowid: The rowid of the row to delete.

        Returns:
            True if a row was deleted, False if no row with that rowid exists.
        """
        cursor = self._conn.cursor()
        cursor.execute(
            f"DELETE FROM {self._table_name} WHERE rowid = ?",
            (rowid,)
        )
        self._conn.commit()
        return cursor.rowcount > 0

    def update(self, rowid: int, content: str, metadata: str = "") -> bool:
        """Update a row in the FTS5 index.

        Args:
            rowid: The rowid of the row to update.
            content: The new content.
            metadata: The new metadata.

        Returns:
            True if a row was updated, False if no row with that rowid exists.
        """
        cursor = self._conn.cursor()
        cursor.execute(
            f"UPDATE {self._table_name} SET content = ?, metadata = ? WHERE rowid = ?",
            (content, metadata, rowid)
        )
        self._conn.commit()
        return cursor.rowcount > 0

    def get_by_rowid(self, rowid: int) -> Optional[Dict[str, Any]]:
        """Retrieve a row by its rowid.

        Args:
            rowid: The rowid to look up.

        Returns:
            Dictionary with rowid, content, and metadata if found, None otherwise.
        """
        cursor = self._conn.cursor()
        cursor.execute(
            f"SELECT rowid, content, metadata FROM {self._table_name} WHERE rowid = ?",
            (rowid,)
        )
        row = cursor.fetchone()

        if row:
            return {
                "rowid": row[0],
                "content": row[1],
                "metadata": row[2]
            }
        return None

    def count(self) -> int:
        """Return the number of rows in the FTS5 index.

        Returns:
            The total number of indexed rows.
        """
        cursor = self._conn.cursor()
        cursor.execute(f"SELECT COUNT(*) FROM {self._table_name}")
        return cursor.fetchone()[0]

    def clear(self) -> None:
        """Delete all rows from the FTS5 index.

        This removes all indexed content but keeps the table structure intact.
        """
        cursor = self._conn.cursor()
        cursor.execute(f"DELETE FROM {self._table_name}")
        self._conn.commit()

    def drop(self) -> None:
        """Drop the FTS5 virtual table.

        This permanently removes the table and all indexed content.
        """
        cursor = self._conn.cursor()
        cursor.execute(f"DROP TABLE IF EXISTS {self._table_name}")
        self._conn.commit()

    def optimize(self) -> None:
        """Optimize the FTS5 index.

        Merges all individual b-trees in the index into a single large b-tree,
        which can improve query performance.
        """
        cursor = self._conn.cursor()
        cursor.execute(f"INSERT INTO {self._table_name}({self._table_name}) VALUES('optimize')")
        self._conn.commit()

    def rebuild(self) -> None:
        """Rebuild the FTS5 index.

        Discards the entire full-text index and rebuilds it from scratch.
        Useful after bulk modifications.
        """
        cursor = self._conn.cursor()
        cursor.execute(f"INSERT INTO {self._table_name}({self._table_name}) VALUES('rebuild')")
        self._conn.commit()

    @property
    def table_name(self) -> str:
        """Return the FTS5 table name."""
        return self._table_name

    @property
    def columns(self) -> List[str]:
        """Return the list of indexed columns."""
        return self._columns.copy()

    @property
    def connection(self) -> sqlite3.Connection:
        """Return the SQLite connection."""
        return self._conn

    def table_exists(self) -> bool:
        """Check if the FTS5 table exists.

        Returns:
            True if the table exists, False otherwise.
        """
        cursor = self._conn.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (self._table_name,)
        )
        return cursor.fetchone() is not None

    def __len__(self) -> int:
        """Return the number of indexed rows."""
        return self.count()

    def __repr__(self) -> str:
        """Return a string representation of the FTS5Manager."""
        return f"FTS5Manager(table='{self._table_name}', columns={self._columns})"
