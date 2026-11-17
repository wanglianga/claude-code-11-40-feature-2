"""Annual survey plans and multi-year trend comparability analysis endpoints."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import (
    AnnualSurveyPlan,
    AnnualSurveyPlanPoint,
    Station,
    TrendAnalysis,
    TrendAnalysisUnit,
    TrendBrief,
    User,
)
from ..schemas import AnnualPlanIn, MigrationCorrectionIn, TrendAnalysisIn
from ..security import get_current_user, require_roles
from ..serializers import (
    annual_plan_out,
    trend_analysis_out,
    trend_brief_out,
    trend_unit_out,
)
from ..services import DomainError, correct_migration_date
from ..trends import create_analysis, run_analysis

router = APIRouter(tags=["trends"])


def _get_analysis(db: Session, analysis_id: int) -> TrendAnalysis:
    analysis = db.get(TrendAnalysis, analysis_id)
    if analysis is None:
        raise HTTPException(404, "趋势分析不存在")
    return analysis


def _current_brief(db: Session, analysis: TrendAnalysis) -> TrendBrief | None:
    if analysis.current_brief_id:
        return db.get(TrendBrief, analysis.current_brief_id)
    return None


# ---------------------------------------------------------------- annual plans
@router.get("/annual-plans")
def list_plans(db: Session = Depends(get_db), _=Depends(get_current_user)):
    plans = db.execute(select(AnnualSurveyPlan).order_by(AnnualSurveyPlan.year)).scalars().all()
    return [annual_plan_out(p) for p in plans]


@router.post("/annual-plans")
def create_plan(
    data: AnnualPlanIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("researcher", "auditor")),
):
    existing = db.execute(
        select(AnnualSurveyPlan).where(AnnualSurveyPlan.plan_code == data.plan_code)
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(409, "计划编号已存在")
    station_ids = {p.station_id for p in data.points}
    found = {
        s.id
        for s in db.execute(select(Station.id).where(Station.id.in_(station_ids))).scalars()
    } if station_ids else set()
    missing = station_ids - found
    if missing:
        raise HTTPException(404, f"站点不存在：{sorted(missing)}")
    plan = AnnualSurveyPlan(
        plan_code=data.plan_code,
        year=data.year,
        season_code=data.season_code,
        label=data.label,
        target_species=data.target_species,
        status="active",
        note=data.note,
        created_by=user.username,
    )
    db.add(plan)
    db.flush()
    for point in data.points:
        db.add(
            AnnualSurveyPlanPoint(
                plan_id=plan.id,
                station_id=point.station_id,
                role=point.role,
                note=point.note,
            )
        )
    db.commit()
    db.refresh(plan)
    return annual_plan_out(plan)


# -------------------------------------------------------------- trend analysis
@router.get("/trend-analyses")
def list_analyses(db: Session = Depends(get_db), _=Depends(get_current_user)):
    analyses = db.execute(select(TrendAnalysis).order_by(TrendAnalysis.id)).scalars().all()
    result = []
    for analysis in analyses:
        result.append(trend_analysis_out(analysis, _current_brief(db, analysis)))
    return result


@router.post("/trend-analyses")
def create(
    data: TrendAnalysisIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("researcher", "auditor")),
):
    try:
        analysis = create_analysis(
            db,
            species_code=data.species_code,
            plan_ids=data.plan_ids,
            label=data.label,
            actor=user.username,
        )
    except ValueError as exc:
        db.rollback()
        raise HTTPException(400, str(exc)) from exc
    db.commit()
    return trend_analysis_out(analysis, _current_brief(db, analysis))


@router.get("/trend-analyses/{analysis_id}")
def analysis_detail(analysis_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    analysis = _get_analysis(db, analysis_id)
    brief = _current_brief(db, analysis)
    data = trend_analysis_out(analysis, brief)
    data["brief"] = trend_brief_out(brief, include_payload=True) if brief else None
    return data


@router.get("/trend-analyses/{analysis_id}/units")
def analysis_units(analysis_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    analysis = _get_analysis(db, analysis_id)
    rows = db.execute(
        select(TrendAnalysisUnit)
        .where(TrendAnalysisUnit.analysis_id == analysis.id)
        .order_by(TrendAnalysisUnit.year, TrendAnalysisUnit.station_code, TrendAnalysisUnit.id)
    ).scalars().all()
    return [trend_unit_out(r) for r in rows]


@router.get("/trend-analyses/{analysis_id}/briefs")
def analysis_briefs(analysis_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    analysis = _get_analysis(db, analysis_id)
    briefs = db.execute(
        select(TrendBrief)
        .where(TrendBrief.analysis_id == analysis.id)
        .order_by(TrendBrief.version.desc())
    ).scalars().all()
    return [trend_brief_out(b) for b in briefs]


@router.get("/trend-analyses/{analysis_id}/briefs/{version}")
def analysis_brief_version(
    analysis_id: int, version: int, db: Session = Depends(get_db), _=Depends(get_current_user)
):
    analysis = _get_analysis(db, analysis_id)
    brief = db.execute(
        select(TrendBrief)
        .where(TrendBrief.analysis_id == analysis.id)
        .where(TrendBrief.version == version)
    ).scalar_one_or_none()
    if brief is None:
        raise HTTPException(404, "简报版本不存在")
    return trend_brief_out(brief, include_payload=True)


@router.post("/trend-analyses/{analysis_id}/recompute")
def recompute(
    analysis_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("researcher", "auditor")),
):
    analysis = _get_analysis(db, analysis_id)
    brief = run_analysis(db, analysis, user.username, note="手动重算")
    db.commit()
    return {
        "analysis": trend_analysis_out(analysis, brief),
        "brief": trend_brief_out(brief, include_payload=True),
    }


# ------------------------------------------------------- point archive edits
@router.post("/stations/{station_id}/migration-correction")
def migration_correction(
    station_id: int,
    data: MigrationCorrectionIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("researcher", "auditor")),
):
    try:
        corrected = date.fromisoformat(data.corrected_date)
    except ValueError as exc:
        raise HTTPException(422, "日期格式应为 YYYY-MM-DD") from exc
    try:
        result = correct_migration_date(
            db,
            station_id=station_id,
            corrected_date=corrected,
            reason=data.reason,
            actor=user.username,
        )
    except DomainError as exc:
        db.rollback()
        raise HTTPException(exc.status_code, exc.message) from exc
    db.commit()
    return result
