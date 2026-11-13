import string

import pandas as pd
import pytest

from src import MovieStorage
import main

def test_movies_persist(client, test_storage, uploaded_movies):
    reopened = MovieStorage(test_storage.db_path)
    df = reopened.get()

    expected_titles = pd.read_csv("fixtures/sample_movies.csv")["title"].tolist()
    assert reopened.count_movies() == 20
    assert len(df) == 20
    assert df.columns.tolist() == ["title", "release_year", "rating", "genre"]
    assert df["title"].tolist() == expected_titles

    storage_ids = [row["id"] for row in reopened.select_columns(["title"], limit=100)]
    api_ids = [row["id"] for row in client.get("/movies", params={"limit": 100}).json()["data"]]
    assert storage_ids == list(range(1, 21))
    assert api_ids == list(range(1, 21))


def test_cache_and_processing(client, uploaded_movies, processing_body):
    # TODO 1: each limit gets its own cached response
    first_responses = {}
    for limit in (100, 1):
        response = client.get("/movies", params={"limit": limit})
        assert response.status_code == 200
        assert main.cache.get(limit) == response.json()
        first_responses[limit] = response.json()

    # TODO 2: a repeat request returns the same response
    repeat = client.get("/movies", params={"limit": 100})
    assert repeat.status_code == 200
    assert repeat.json() == first_responses[100]

    # TODO 3: processing reports 20 -> 16 and clears the old cache entries
    processed = client.post("/movies/process", json=processing_body)
    assert processed.status_code == 200
    report = processed.json()
    assert report["validation_rows_removed"] == 0
    assert report["cleaning_report"]["rows_before"] == 20
    assert report["cleaning_report"]["rows_after"] == 16
    assert main.cache.get(100) is None
    assert main.cache.get(1) is None

    # TODO 4: new data, renumbered IDs, and a new cache entry
    after = client.get("/movies", params={"limit": 100})
    assert after.status_code == 200
    body = after.json()
    assert body["total_rows"] == 16
    expected_titles = [f"Movie {letter}" for letter in string.ascii_uppercase[:16]]
    assert [row["title"] for row in body["data"]] == expected_titles
    assert [row["id"] for row in body["data"]] == list(range(1, 17))
    assert main.cache.get(100) == body

def test_cache_hit_skips_database(client, uploaded_movies, monkeypatch):
    # TODO 1: the first request fills the cache
    first = client.get("/movies", params={"limit": 100})
    assert first.status_code == 200
    expected = first.json()

    # TODO 2: make any database read fail the test
    def fail_if_called(*args, **kwargs):
        pytest.fail("The database was queried on a cache hit")

    monkeypatch.setattr(main.storage, "select_columns", fail_if_called)
    monkeypatch.setattr(main.storage, "count_movies", fail_if_called)

    # TODO 3: the same request should be answered from the cache
    second = client.get("/movies", params={"limit": 100})
    assert second.status_code == 200
    assert second.json() == expected