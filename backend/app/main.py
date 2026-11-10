"""FastAPI app. Run from backend/: uvicorn app.main:app --reload"""
import sys
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from pymongo.errors import PyMongoError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # for calc.py

from app import backups  # noqa: E402
from app.api import router  # noqa: E402
from app.db import get_db  # noqa: E402
from app.portfolio import build_portfolio  # noqa: E402
from app.profiles import Scope, get_scope  # noqa: E402
from app.profiles import router as profiles_router  # noqa: E402
from app.prices import held_instrument_ids, refresh_if_stale, refresh_prices  # noqa: E402


FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"


def daily_snapshot(db=Depends(get_db)):
    """First API use each day takes the daily snapshot. Failures are logged, not raised."""
    backups.ensure_daily(db)


app = FastAPI(title="Nivesh Control Room", dependencies=[Depends(daily_snapshot)])
app.include_router(router)
app.include_router(profiles_router)


@app.get("/api/health")
def health(db=Depends(get_db)):
    try:
        db.command("ping")
    except PyMongoError as exc:
        return JSONResponse(
            status_code=503,
            content={"status": "error", "mongo": "unreachable", "detail": str(exc)},
        )
    return {"status": "ok", "mongo": "ok", "db": db.name}


def _held(scope: Scope) -> set:
    return held_instrument_ids(scope.transactions.find({}, {"instrument_id": 1, "type": 1, "quantity": 1}))


@app.post("/api/prices/refresh")
def prices_refresh(scope: Scope = Depends(get_scope)):
    """Fetch now, for what the active profile holds (plus USDINR)."""
    return refresh_prices(scope.db, _held(scope))


@app.get("/api/portfolio")
def portfolio(scope: Scope = Depends(get_scope)):
    # Prices are shared, but only the active profile's holdings are refreshed here.
    refreshed = refresh_if_stale(scope.db, _held(scope))
    return {"refreshed": refreshed, **build_portfolio(scope)}


@app.get("/{path:path}", include_in_schema=False)
def frontend(path: str):
    """The built React app. Any other path gets index.html, so page links work directly."""
    if path == "api" or path.startswith("api/"):
        raise HTTPException(status_code=404, detail="Not found")
    index = FRONTEND_DIST / "index.html"
    if not index.is_file():
        return JSONResponse(
            status_code=503,
            content={"detail": "Frontend not built. Run: cd frontend && npm run build"},
        )
    file = (FRONTEND_DIST / path).resolve()
    if path and file.is_file() and file.is_relative_to(FRONTEND_DIST.resolve()):
        return FileResponse(file)
    return FileResponse(index)
