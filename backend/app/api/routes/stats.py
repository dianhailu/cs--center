"""Daily stats endpoints for the agent console."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, get_auth
from app.db import get_db
from app.services import stats as stats_svc

router = APIRouter(prefix="/stats", tags=["stats"])


@router.get("/daily")
def get_daily_stats(
    from_: str = Query(..., alias="from", description="YYYY-MM-DD (Asia/Jakarta)"),
    to: str = Query(..., description="YYYY-MM-DD (Asia/Jakarta)"),
    auth: AuthContext = Depends(get_auth),
    db: Session = Depends(get_db),
) -> dict:
    """Daily unique people + consultation counts.

    See ``app.services.stats`` module docstring for metric definitions.
    Days are bounded in Asia/Jakarta (same as history learn).
    """
    try:
        from_day = stats_svc.parse_ymd(from_)
        to_day = stats_svc.parse_ymd(to)
    except ValueError as exc:
        raise HTTPException(400, "invalid date; use YYYY-MM-DD") from exc
    try:
        days = stats_svc.daily_stats(
            db, auth.workspace_id, from_day=from_day, to_day=to_day
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {
        "timezone": stats_svc.TZ_NAME,
        "from": from_day.isoformat(),
        "to": to_day.isoformat(),
        "days": days,
    }


@router.get("/daily/categories")
def get_daily_categories_query(
    date: str = Query(..., description="YYYY-MM-DD (Asia/Jakarta)"),
    auth: AuthContext = Depends(get_auth),
    db: Session = Depends(get_db),
) -> dict:
    """Category breakdown for one day (query form: ?date=)."""
    return _categories_for(db, auth, date)


@router.get("/daily/{day}/categories")
def get_daily_categories_path(
    day: str,
    auth: AuthContext = Depends(get_auth),
    db: Session = Depends(get_db),
) -> dict:
    """Category breakdown for one day (path form)."""
    return _categories_for(db, auth, day)


def _categories_for(db: Session, auth: AuthContext, day_str: str) -> dict:
    try:
        day = stats_svc.parse_ymd(day_str)
    except ValueError as exc:
        raise HTTPException(400, "invalid date; use YYYY-MM-DD") from exc
    return stats_svc.category_breakdown(db, auth.workspace_id, day=day)
