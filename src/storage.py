import logging
import sqlite3
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

# Match this to the MOVIE_COLUMNS already defined in your file
MOVIE_COLUMNS = ["title", "genre", "year", "rating"]


def get_connection(db_path):
    """Return a fresh connection with rows accessible by column name."""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    return connection


def initialize_database(db_path):
    """Create the movie table if it does not exist."""
    connection = get_connection(db_path)
    try:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS movies (
                id INTEGER PRIMARY KEY,
                title TEXT NOT NULL,
                genre TEXT,
                year INTEGER,
                rating REAL
            )
            """
        )
        connection.commit()
    finally:
        connection.close()


class MovieStorage:
    def __init__(self, db_path="data/movies.db"):
        self.db_path = db_path
        initialize_database(self.db_path)

    def _validate_columns(self, columns):
        """Raise ValueError unless columns is a non-empty list of known movie columns."""
        if not columns:
            logger.error("Select at least one column")
            raise ValueError("Select at least one column")

        for column in columns:
            if column not in MOVIE_COLUMNS:
                logger.error(f"Unsupported column: {column}")
                raise ValueError(f"Unsupported column: {column}")

    def save(self, df):
        """Replace all movie rows in one transaction."""
        movies = df[MOVIE_COLUMNS]
        rows = list(
            movies.astype(object)
            .where(movies.notna(), None)
            .itertuples(index=False, name=None)
        )

        column_list = ", ".join(MOVIE_COLUMNS)
        placeholders = ", ".join(["?"] * len(MOVIE_COLUMNS))
        insert_sql = f"INSERT INTO movies ({column_list}) VALUES ({placeholders})"

        connection = get_connection(self.db_path)
        try:
            connection.execute("DELETE FROM movies")
            connection.executemany(insert_sql, rows)
            connection.commit()
            logger.debug(f"Saved {len(rows)} movie row(s)")
        except sqlite3.Error:
            connection.rollback()
            logger.error("Saving movies failed; changes rolled back")
            raise
        finally:
            connection.close()

    def get(self):
        """Return the four movie columns as a DataFrame, ordered by id."""
        column_list = ", ".join(MOVIE_COLUMNS)
        connection = get_connection(self.db_path)
        try:
            rows = connection.execute(
                f"SELECT {column_list} FROM movies ORDER BY id"
            ).fetchall()
        finally:
            connection.close()

        df = pd.DataFrame(rows, columns=MOVIE_COLUMNS)
        logger.debug(f"Loaded {len(df)} movie row(s)")
        return df

    def select_columns(self, columns, limit=5):
        """Return id plus the requested movie columns, ordered by id."""
        self._validate_columns(columns)

        selected_columns = ", ".join(["id"] + columns)
        connection = get_connection(self.db_path)
        try:
            rows = connection.execute(
                f"SELECT {selected_columns} FROM movies ORDER BY id LIMIT ?",
                (limit,),
            ).fetchall()
            records = [dict(row) for row in rows]
            logger.debug(f"Selected {['id'] + columns}: {len(records)} row(s)")
            return records
        finally:
            connection.close()

    def count_movies(self):
        """Return the number of stored movies using SQL COUNT(*)."""
        connection = get_connection(self.db_path)
        try:
            count = connection.execute("SELECT COUNT(*) FROM movies").fetchone()[0]
        finally:
            connection.close()

        logger.debug(f"Counted {count} movie(s)")
        return count

    def query_movies(self, columns, min_rating, limit):
        """Return selected fields from matching movies using SQL."""
        self._validate_columns(columns)

        selected_columns = ", ".join(["id"] + columns)
        connection = get_connection(self.db_path)
        try:
            rows = connection.execute(
                f"SELECT {selected_columns} FROM movies "
                "WHERE rating >= ? "
                "ORDER BY rating DESC, id ASC "
                "LIMIT ?",
                (min_rating, limit),
            ).fetchall()
        finally:
            connection.close()

        records = [dict(row) for row in rows]
        logger.debug(
            f"Queried {['id'] + columns} with rating >= {min_rating}: {len(records)} row(s)"
        )
        return records