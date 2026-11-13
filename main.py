import io
import logging
from pathlib import Path
import json


import pandas as pd
from fastapi import FastAPI, File, HTTPException, Query, UploadFile

from src import MOVIE_COLUMNS, MovieStorage
from data_pipeline import create_cleaning_report, process_data, validate_dataframe
from src import (
    HealthResponse,
    MOVIE_COLUMNS,
    MovieCache,
    MovieDataResponse,
    MovieProcessingReport,
    MovieStorage,
    MovieUploadInfo,
    ProcessConfig,
)

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger(__name__)

app = FastAPI(title="Movie Database API")
storage = MovieStorage()

cache = MovieCache()

app = FastAPI(title="Movie Database API", version="1.0.0")
@app.get("/health", response_model=HealthResponse)
def health_check():
    """Return the application status and version."""
    return {"status": "ok", "version": app.version}

def get(self, limit):
    """Return the cached response dictionary, or None."""
    key = self.make_key(limit)
    cached = self.client.get(key)
    if cached is None:
        logger.debug(f"Cache MISS: {key}")
        return None
    logger.debug(f"Cache HIT: {key}")
    return json.loads(cached)

def set(self, limit, response):
    """Cache the response dictionary for 90 seconds."""
    self.client.set(self.make_key(limit), json.dumps(response), ex=90)

def invalidate(self):
    """Remove all cached movie retrievals."""
    self.client.flushdb()
    logger.debug("Invalidated movie cache")

@app.get("/movies", response_model=MovieDataResponse)
def get_movies(limit: int = Query(default=100, ge=1)):
    """Return up to limit stored movies and the total count."""
    cached = cache.get(limit)
    if cached is not None:
        logger.info(f"Cache hit: limit={limit}")
        return cached

    records = storage.select_columns(MOVIE_COLUMNS, limit=limit)
    total_rows = storage.count_movies()
    response = {"data": records, "total_rows": total_rows}

    cache.set(limit, response)
    logger.info(f"Returned {len(records)} of {total_rows} movie(s)")
    return response

    # Part 1: read from the database
    records = storage.select_columns(MOVIE_COLUMNS, limit=limit)
    total_rows = storage.count_movies()
    response = {"data": records, "total_rows": total_rows}

    # TODO 2: cache the response, then log and return it
    cache.set(limit, response)
    logger.info(f"Returned {len(records)} of {total_rows} movie(s)")
    return response

@app.post("/upload", response_model=MovieUploadInfo)
async def upload_movies(file: UploadFile = File(...)):
    """Validate a movie CSV and replace the stored collection."""
    # TODO 1: same checks as MP2
    suffix = Path(file.filename or "").suffix.lower()
    if suffix != ".csv":
        logger.warning(f"Rejected upload '{file.filename}': not a CSV file")
        raise HTTPException(status_code=400, detail="Only CSV files are accepted")

    contents = await file.read()
    try:
        df = pd.read_csv(io.BytesIO(contents))
    except (pd.errors.EmptyDataError, pd.errors.ParserError, UnicodeDecodeError) as e:
        logger.warning(f"Could not parse '{file.filename}': {e}")
        raise HTTPException(status_code=400, detail=f"Could not read CSV: {e}") from e

    # TODO 2: quick validation
    missing = [col for col in MOVIE_COLUMNS if col not in df.columns]
    extra = [col for col in df.columns if col not in MOVIE_COLUMNS]
    if missing or extra:
        message = f"Columns must be exactly {MOVIE_COLUMNS}. Missing: {missing}, unexpected: {extra}"
        logger.warning(f"Rejected '{file.filename}': {message}")
        raise HTTPException(status_code=400, detail=message)

    if df.empty:
        logger.warning(f"Rejected '{file.filename}': no data rows")
        raise HTTPException(status_code=400, detail="The CSV has no data rows")

    df = df[MOVIE_COLUMNS]

    # TODO 3: save and report
    storage.save(df)
    cache.invalidate()  # Add this line.
    logger.info(f"Saved {len(df)} movie(s) from '{file.filename}'")
    return {
        "filename": file.filename,
        "rows": len(df),
        "columns": len(df.columns),
        "column_names": df.columns.tolist(),
    }


@app.post("/movies/process", response_model=MovieProcessingReport)
def process_movies(config: ProcessConfig):
    """Validate and clean the stored movies using the given configuration."""
    # TODO 1: get the stored movies
    df = storage.get()
    if df.empty:
        logger.warning("Rejected processing: no movies stored")
        raise HTTPException(status_code=400, detail="No movies stored. Upload a CSV first.")

    # TODO 2: validate and process, as in MP2
    settings = config.model_dump()
    validation = settings["validation"]
    try:
        validated = validate_dataframe(
            df,
            required_columns=validation["required_columns"],
            numeric_columns=validation["numeric_columns"],
        )
        processed = process_data(validated, settings)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    validation_rows_removed = len(df) - len(validated)
    cleaning_report = create_cleaning_report(validated, processed)
    logger.info(
        f"Processed movies: validation removed {validation_rows_removed} row(s), "
        f"cleaning removed {cleaning_report['rows_removed']} row(s)"
    )

    # TODO 3: replace the stored movies with the result
    storage.save(processed)
    cache.invalidate()  # Add this line.
    return {
        "validation_rows_removed": validation_rows_removed,
        "cleaning_report": cleaning_report,
    }

@app.get("/movies/search", response_model=list[dict])
def query_movies(
    columns: list[str] = Query(default=["title"]),
    min_rating: float = Query(default=0, ge=0, le=10),
    limit: int = Query(default=100, ge=1)
):
    """Return id plus the selected fields for movies at or above min_rating."""
    try:
        records = storage.query_movies(columns, min_rating, limit)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    logger.info(f"Searched movies: columns={columns}, rows={len(records)}")
    return records

