# Movie Database API

DS 3500 · MP3

A FastAPI service that stores a movie collection in SQLite. You upload a CSV of movies, browse and search them through the API, and clean them with the validation and processing pipeline from the earlier mini-projects. The data lives in a database file, so it survives server restarts, and the most common read request is cached so repeated calls don't touch the database.

## Project structure

```text
mp3-movie-api/
├── main.py                 # FastAPI app and all endpoints
├── requirements.txt
├── data/
│   └── movies.db           # SQLite database, created automatically on first run
├── fixtures/
│   └── sample_movies.csv   # 20-row sample collection used by the tests
├── src/                    # MP3 package: storage, models, and caching
│   ├── __init__.py
│   ├── cache.py            # MovieCache: in-memory cache for GET /movies
│   ├── database.py         # SQLite connection and table setup
│   ├── middleware.py       # request logging middleware
│   ├── models.py           # Pydantic request and response models
│   ├── storage.py          # MovieStorage and MOVIE_COLUMNS
│   └── utils.py
├── data_pipeline/          # validation and cleaning pipeline reused from MP1/MP2
│   ├── __init__.py
│   ├── data_loaders.py
│   ├── data_output.py
│   ├── data_processor.py
│   ├── data_validator.py
│   └── utils.py
└── tests/
    ├── conftest.py         # shared fixtures: temporary database, fresh cache, sample upload
    └── test_api.py
```

`main.py` coordinates the work and the two packages hold the implementation. `src` handles everything specific to this project: storing movies in SQLite, describing request and response shapes, and caching. `data_pipeline` is the reusable cleaning code: it validates required and numeric columns, then removes duplicates, missing values, and outliers according to a configuration.

## Setup

The project needs Python 3.11 or newer, which pandas 3 requires. From the repository root, create a virtual environment, activate it, and install the dependencies:

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

On Windows, activate the environment with `venv\Scripts\activate` instead. Your terminal prompt should start with `(venv)` once it's active.

## Running the server

Start the server from the repository root, the folder that contains `main.py`:

```bash
python -m uvicorn main:app --reload
```

The API runs at `http://127.0.0.1:8000`. Open `http://127.0.0.1:8000/docs` for interactive documentation where you can try every endpoint in the browser. `--reload` restarts the server whenever you save a file, which is convenient while developing but also clears the cache, since the cache lives in memory.

## Movie data format

Every movie has four fields, defined once as `MOVIE_COLUMNS` in `src/storage.py`:

| Column | Type | Description |
| :--- | :--- | :--- |
| `title` | text | Movie title (required) |
| `release_year` | integer | Year of release |
| `rating` | decimal | Rating from 0 to 10 |
| `genre` | text | Genre, such as Drama or Comedy |

An uploaded CSV must have exactly these four columns, in any order. SQLite adds an `id` to each movie, numbered from 1 in the order the rows appear in the file. Missing values are stored as `NULL` and returned as `null` in JSON.

A valid file starts like this:

```csv
title,release_year,rating,genre
Movie A,2020,8.0,Drama
Movie B,2021,8.5,Comedy
```

## Endpoints

| Method | Path | Purpose |
| :--- | :--- | :--- |
| `GET` | `/health` | Check that the service is running |
| `POST` | `/upload` | Upload a movie CSV, replacing the stored collection |
| `GET` | `/movies` | Return up to `limit` movies and the total count (cached) |
| `GET` | `/movies/search` | Return selected fields for movies at or above a minimum rating |
| `POST` | `/movies/process` | Validate and clean the stored movies using a configuration |

### `POST /upload`

Uploads a CSV file and replaces whatever collection was stored before, so uploading the same file twice still leaves 20 movies, not 40. The file is rejected with status `400` if it isn't a `.csv`, can't be parsed, doesn't have exactly the four movie columns, or has a header but no data rows. A rejected upload leaves the stored movies untouched.

```bash
curl -X POST -F "file=@fixtures/sample_movies.csv" http://127.0.0.1:8000/upload
```

```json
{"filename": "sample_movies.csv", "rows": 20, "columns": 4,
 "column_names": ["title", "release_year", "rating", "genre"]}
```

### `GET /movies`

Returns up to `limit` movies in `id` order, along with `total_rows`, the number of movies stored in total. `limit` defaults to 100 and must be at least 1.

```bash
curl "http://127.0.0.1:8000/movies?limit=2"
```

```json
{
  "data": [
    {"id": 1, "title": "Movie A", "release_year": 2020, "rating": 8.0, "genre": "Drama"},
    {"id": 2, "title": "Movie B", "release_year": 2021, "rating": 8.5, "genre": "Comedy"}
  ],
  "total_rows": 20
}
```

### `GET /movies/search`

Returns `id` plus the requested fields for every movie whose rating is at least `min_rating`, sorted from highest rating to lowest, with ties broken by `id`. To request several fields, repeat the `columns` parameter rather than separating names with commas. In `/docs`, use **Add string item** to add each one.

| Parameter | Default | Rules |
| :--- | :--- | :--- |
| `columns` | `["title"]` | Each must be one of the four movie columns |
| `min_rating` | `0` | Between 0 and 10 |
| `limit` | `100` | At least 1 |

```bash
curl "http://127.0.0.1:8000/movies/search?columns=title&columns=rating&min_rating=8.5&limit=2"
```

An unknown column name returns `400` with a message naming the column. A search with no matches returns an empty list, not an error.

### `POST /movies/process`

Runs the cleaning pipeline on the stored movies and saves the result in their place. Validation runs first: it checks that the required columns exist and removes rows whose numeric columns contain values that aren't numbers. Processing then removes duplicates, rows with missing values, and outliers, depending on which steps the configuration enables.

The request body is a configuration with a `validation` section and a `processing` section:

```bash
curl -X POST http://127.0.0.1:8000/movies/process \
  -H "Content-Type: application/json" \
  -d '{
    "validation": {
      "required_columns": ["title", "release_year", "rating", "genre"],
      "numeric_columns": ["release_year", "rating"]
    },
    "processing": {
      "remove_duplicates": true,
      "missing": {"enabled": true, "axis": "rows"},
      "outliers": {"enabled": true, "columns": ["rating"], "method": "iqr", "threshold": 1.5}
    }
  }'
```

Every field has a default, so omitted settings fall back to: no required or numeric columns, duplicate removal on, missing-row removal on, and outlier removal off. Outliers can be detected with `"iqr"` or `"zscore"`, and missing values can be removed by `"rows"` or `"columns"`.

The response reports what validation removed and what the cleaning steps removed, separately. On the sample data, validation removes nothing, and cleaning removes one duplicate, one row with a missing value, and two rating outliers:

```json
{
  "validation_rows_removed": 0,
  "cleaning_report": {
    "rows_before": 20, "rows_after": 16, "rows_removed": 4,
    "columns_before": 4, "columns_after": 4, "columns_removed": 0
  }
}
```

The request fails with `400` if no movies have been uploaded yet, if a required column is missing, or if the configuration uses an unsupported axis or outlier method. Because processing replaces the whole collection, the remaining movies are renumbered from 1.

## Storage and caching

Movies are stored in `data/movies.db` by `MovieStorage`. Every save happens in a single transaction: the old rows are deleted and the new ones inserted together, and if anything fails, the transaction rolls back and the previous collection stays in place. Because the data is in a file, stopping and restarting the server keeps every movie. Deleting `data/movies.db` resets the collection, and the table is created again on the next start.

`GET /movies` responses are cached in memory, one entry per `limit` value. The first request for a given limit reads from the database and stores the response; repeat requests with that limit are answered from the cache without querying the database. Uploading or processing clears the whole cache, so the next request always reflects the current data. Search results are not cached.

## Running the tests

With the virtual environment active, run the tests from the repository root:

```bash
python -m pytest tests -v
```

Each test gets its own temporary database and a fresh cache through the fixtures in `tests/conftest.py`, so the tests never touch `data/movies.db` and can run in any order. They check that uploaded movies persist in the database file with IDs 1 through 20, that `GET /movies` caches one response per limit and that processing clears it, that processing the sample turns 20 movies into 16, and that a cached request is answered without reading the database.

The tests read `fixtures/sample_movies.csv` using a relative path, so run them from the repository root.