"""Annual monitoring trend comparability analysis.

The analyzer helps researchers judge whether a change in observations comes from
animal activity or from camera migration, transect expansion and effort changes:

* Effort is computed per target species' daily surveyable windows from the main
  service's certificates, actual operating days (device gate) and pending
  interpretation range (reading gate). A device that runs all day but fails at
  night does not give a nocturnal species a full effective day.
* Survey units are split into point segments by effective location and date when
  a point migrates mid-season; each material belongs to exactly one segment, and
  materials whose date is unknown or whose clock error crosses the migration
  boundary stay out of the cross-year comparison.
* The headline method is stratified standardization (habitat × elevation band ×
  season) over the commonly covered range; the continuous fixed-point series is
  kept as a separate reference and the two are never merged into one trend.
  Non-overlapping elevation bands/seasons are not extrapolated, and new
  exploration points are published as independent observations only.
* Late maintenance logs, migration-date corrections and determination revisions
  mark affected analyses stale via unit references; recomputation rebuilds both
  numerators and denominators and decomposes the trend change into coverage,
  effort and interpretation contributions. Old briefs keep their frozen inputs.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from sqlalchemy import func as sa_func
from sqlalchemy import select
from sqlalchemy.orm import Session

from .certificates import current_certificate
from .config import RESERVE_TZ, STATUS_LABELS, TREND_MIN_STRATUM_EFFORT_DAYS
from .models import (
    AnnualSurveyPlan,
    ArchiveRecord,
    AuditEvent,
    Determination,
    GateCheck,
    RulebookVersion,
    Station,
    StationVersion,
    SurveyRun,
    SurveyUnit,
    TrendAnalysis,
    TrendAnalysisUnit,
    TrendBrief,
    utcnow,
)
from .utils import canonical_hash, day_window, ensure_utc, hours_between, merge_intervals, parse_dt

Z_80 = 1.28

DISCLAIMERS = [
    "观测率是种群活动的代理指标，受覆盖范围、调查努力量与判读变化影响；"
    "观测率变化不等于种群规模变化，不能解释为已确认的种群增长。",
    "分层标准化趋势与固定点位参照序列是两条独立序列，不可拼接为单一趋势。",
    "不重叠的海拔带与季节不做外推；新增探索点仅发布独立观测，不纳入趋势。",
    "同一设备编号不代表同一调查点；照片数量不代表种群规模。",
]


# --------------------------------------------------------------------- helpers
def _parse_windows(species: dict[str, Any]) -> list[tuple[float, float]]:
    """Daily surveyable windows as (start_hour, end_hour) pairs, local time."""
    raw = species.get("daily_windows") or [["00:00", "24:00"]]
    windows: list[tuple[float, float]] = []
    for pair in raw:
        sh, sm = str(pair[0]).split(":")[:2]
        eh, em = str(pair[1]).split(":")[:2]
        windows.append((int(sh) + int(sm) / 60, int(eh) + int(em) / 60))
    return windows


def _window_intervals(day_start: datetime, windows: list[tuple[float, float]]):
    out = []
    for start_h, end_h in windows:
        if end_h <= start_h:  # wraps midnight: split at the day boundary
            out.append((day_start + timedelta(hours=start_h), day_start + timedelta(days=1)))
            out.append((day_start, day_start + timedelta(hours=end_h)))
        else:
            out.append((day_start + timedelta(hours=start_h), day_start + timedelta(hours=end_h)))
    return out


def _clip_intervals(intervals, start, end):
    clipped = []
    for s, e in intervals:
        s2, e2 = max(s, start), min(e, end)
        if e2 > s2:
            clipped.append((s2, e2))
    return clipped


def _strict_version(versions: list[StationVersion], day: date) -> StationVersion | None:
    """The point archive version effective on that date (no nearest-match fallback)."""
    for v in versions:
        if v.effective_from <= day and (v.effective_to is None or day <= v.effective_to):
            return v
    return None


def _band_for(rulebook: RulebookVersion, version: StationVersion) -> tuple[str, str]:
    mid = (version.elevation_min_m + version.elevation_max_m) / 2
    for band in rulebook.elevation_bands or []:
        if float(band["min_m"]) <= mid < float(band["max_m"]):
            return str(band["code"]), str(band.get("name", band["code"]))
    return "", ""


def _season_type(season_code: str) -> str:
    return season_code.split("-")[-1] if "-" in season_code else season_code


def _has_verified_calibration(rec: ArchiveRecord, calibrations: list[ArchiveRecord]) -> bool:
    event_time = ensure_utc(rec.event_time)
    for cal in calibrations:
        payload = cal.payload
        if payload.get("target_device") and payload["target_device"] != rec.source_device:
            continue
        if not payload.get("verified", False):
            continue
        valid_from = payload.get("valid_from")
        valid_to = payload.get("valid_to")
        if valid_from and event_time < parse_dt(valid_from):
            continue
        if valid_to and event_time > parse_dt(valid_to):
            continue
        return True
    return False


# ------------------------------------------------------------------ effort
def compute_unit_effort(
    db: Session,
    unit: SurveyUnit,
    gates: dict[str, GateCheck],
    species: dict[str, Any],
) -> dict[str, Any]:
    """Species-specific effective effort (in survey days) for one unit.

    Reads the main service's device gate (actual operating intervals: downtime
    records plus unexplained gaps) and reading gate (pending interpretation
    range). Only the species' daily surveyable windows count: night-time
    downtime reduces a nocturnal species' effort even when the device was
    available all day.
    """
    day_start, day_end = day_window(unit.unit_date)
    unavailable: list[tuple[datetime, datetime]] = []
    device = gates.get("device")
    downtime_ids: list[int] = []
    if device is not None:
        evidence_ids = [v for v in (device.evidence or []) if isinstance(v, int)]
        if evidence_ids:
            records = db.execute(
                select(ArchiveRecord).where(ArchiveRecord.id.in_(evidence_ids))
            ).scalars()
            for rec in records:
                if rec.record_type != "downtime_log":
                    continue
                payload = rec.payload
                if not payload.get("start") or not payload.get("end"):
                    continue
                downtime_ids.append(rec.id)
                unavailable.append((parse_dt(payload["start"]), parse_dt(payload["end"])))
        for gap in (device.measured or {}).get("unexplained_gaps") or []:
            if gap.get("start") and gap.get("end"):
                unavailable.append((parse_dt(gap["start"]), parse_dt(gap["end"])))
    unavailable = _clip_intervals(merge_intervals(unavailable), day_start, day_end)

    windows = _window_intervals(day_start, _parse_windows(species))
    window_hours = sum(hours_between(s, e) for s, e in windows)
    lost_hours = 0.0
    for ws, we in windows:
        for us, ue in unavailable:
            s2, e2 = max(ws, us), min(we, ue)
            if e2 > s2:
                lost_hours += hours_between(s2, e2)
    available_ratio = max(0.0, (window_hours - lost_hours) / window_hours) if window_hours else 0.0
    reading = gates.get("reading")
    pending_ratio = float((reading.measured or {}).get("pending_ratio", 0.0)) if reading else 0.0
    pending_ratio = min(1.0, max(0.0, pending_ratio))
    effort = available_ratio * (1.0 - pending_ratio)
    return {
        "effort_days": round(effort, 4),
        "window_hours": round(window_hours, 2),
        "lost_window_hours": round(lost_hours, 2),
        "available_window_ratio": round(available_ratio, 4),
        "pending_ratio": round(pending_ratio, 4),
        "downtime_record_ids": sorted(downtime_ids),
    }


# ------------------------------------------------------------- unit inputs
def _unit_materials(db: Session, gates: dict[str, GateCheck]) -> list[ArchiveRecord]:
    reading = gates.get("reading")
    ids = []
    if reading is not None:
        ids = [v for v in ((reading.measured or {}).get("material_evidence") or []) if isinstance(v, int)]
    if not ids:
        return []
    return list(db.execute(select(ArchiveRecord).where(ArchiveRecord.id.in_(ids))).scalars())


def _migration_boundaries(
    versions: list[StationVersion], season_start: date, season_end: date
) -> list[datetime]:
    boundaries = []
    for v in versions:
        if season_start < v.effective_from <= season_end:
            instant = datetime.combine(v.effective_from, time.min, tzinfo=RESERVE_TZ)
            boundaries.append(instant.astimezone(timezone.utc))
    return boundaries


def _excluded_materials(
    materials: list[ArchiveRecord],
    calibrations: list[ArchiveRecord],
    boundaries: list[datetime],
    tolerance_seconds: float,
) -> list[dict[str, Any]]:
    """Materials that must stay out of the cross-year comparison.

    A material is excluded when its date is unknown, or when its uncalibrated
    clock error interval straddles a mid-season migration boundary — in both
    cases the material cannot be attributed to exactly one point segment.
    """
    excluded = []
    for rec in materials:
        payload = rec.payload or {}
        if payload.get("date_unknown"):
            excluded.append(
                {
                    "record_id": rec.id,
                    "external_id": rec.external_id,
                    "reason": "素材日期未知，无法归属迁点前后的点段，暂不进入跨年比较",
                }
            )
            continue
        declared = payload.get("clock_offset_seconds")
        if declared is None or abs(float(declared)) <= tolerance_seconds:
            continue
        if _has_verified_calibration(rec, calibrations):
            continue
        event_time = ensure_utc(rec.event_time)
        delta = timedelta(seconds=abs(float(declared)))
        low, high = event_time - delta, event_time + delta
        if any(low <= boundary <= high for boundary in boundaries):
            excluded.append(
                {
                    "record_id": rec.id,
                    "external_id": rec.external_id,
                    "reason": (
                        f"设备时钟偏差 {abs(float(declared)):.0f}s 的可信区间跨过迁点边界，"
                        "无法唯一归属点段，暂不进入跨年比较"
                    ),
                }
            )
    return excluded


def build_unit_inputs(db: Session, analysis: TrendAnalysis, preferred_runs: dict[int, int] | None = None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Assemble the analysis inputs from the main service and the point archive.

    ``preferred_runs`` pins each plan to the survey run the analysis was built
    against (kept in the brief), so recomputation tracks the same run instead
    of drifting to newer runs assembled later for other purposes.
    """
    preferred_runs = preferred_runs or {}
    plans = {
        p.id: p
        for p in db.execute(
            select(AnnualSurveyPlan).where(AnnualSurveyPlan.id.in_(analysis.plan_ids))
        ).scalars()
    }
    years = sorted(analysis.years)
    species = None
    for plan in sorted(plans.values(), key=lambda p: p.year):
        for entry in plan.target_species or []:
            if entry.get("code") == analysis.species_code:
                species = entry
    if species is None:
        raise ValueError(f"年度计划中不存在目标物种 {analysis.species_code}")

    stations = {
        s.id: s for s in db.execute(select(Station)).scalars()
    }
    versions_by_station: dict[int, list[StationVersion]] = defaultdict(list)
    for v in db.execute(select(StationVersion)).scalars():
        versions_by_station[v.station_id].append(v)
    calibrations_by_station: dict[int, list[ArchiveRecord]] = defaultdict(list)
    for rec in db.execute(
        select(ArchiveRecord).where(ArchiveRecord.record_type == "time_calibration")
    ).scalars():
        calibrations_by_station[rec.station_id].append(rec)

    rows: list[dict[str, Any]] = []
    plan_meta: list[dict[str, Any]] = []
    warnings: list[str] = []
    for year in years:
        plan = next((p for p in plans.values() if p.year == year), None)
        if plan is None:
            warnings.append(f"{year} 年缺少年度调查计划，已跳过")
            continue
        run = None
        bound_run_id = preferred_runs.get(plan.id)
        if bound_run_id:
            bound = db.get(SurveyRun, bound_run_id)
            if bound is not None and bound.status == "active" and bound.season_code == plan.season_code:
                run = bound
        if run is None:
            run = db.execute(
                select(SurveyRun)
                .where(SurveyRun.season_code == plan.season_code)
                .where(SurveyRun.status == "active")
                .order_by(SurveyRun.id.desc())
            ).scalars().first()
        if run is None:
            warnings.append(f"{year} 年（{plan.season_code}）没有活动状态的调查运行，已跳过")
            continue
        plan_meta.append(
            {"plan_id": plan.id, "plan_code": plan.plan_code, "year": year, "run_id": run.id}
        )
        role_by_station = {pt.station_id: pt.role for pt in plan.points}
        units = list(
            db.execute(
                select(SurveyUnit)
                .where(SurveyUnit.run_id == run.id)
                .where(SurveyUnit.station_id.in_(list(role_by_station)))
                .order_by(SurveyUnit.station_id, SurveyUnit.unit_date)
            ).scalars()
        )
        for unit in units:
            rows.append(
                _build_one_unit(
                    db,
                    analysis,
                    unit,
                    year,
                    role_by_station[unit.station_id],
                    species,
                    stations,
                    versions_by_station,
                    calibrations_by_station,
                    run,
                )
            )
    return rows, {"plans": plan_meta, "warnings": warnings, "species": species}


def _build_one_unit(
    db: Session,
    analysis: TrendAnalysis,
    unit: SurveyUnit,
    year: int,
    point_role: str,
    species: dict[str, Any],
    stations: dict[int, Station],
    versions_by_station: dict[int, list[StationVersion]],
    calibrations_by_station: dict[int, list[ArchiveRecord]],
    run: SurveyRun,
) -> dict[str, Any]:
    station = stations[unit.station_id]
    rulebook = db.get(RulebookVersion, unit.rulebook_version_id)
    gates = {
        g.gate: g
        for g in db.execute(select(GateCheck).where(GateCheck.unit_id == unit.id)).scalars()
    }
    cert = current_certificate(db, unit.id)
    versions = sorted(versions_by_station.get(unit.station_id, []), key=lambda v: v.effective_from)
    version = _strict_version(versions, unit.unit_date)

    reasons: list[str] = []
    included = True
    if point_role == "exploration":
        included = False
        reasons.append("新增探索点：仅发布独立观测，不纳入跨年趋势")
    if cert is None:
        included = False
        reasons.append("尚无调查证书，不进入趋势输入")
    elif cert.review_status == "under_review":
        included = False
        reasons.append("证书复审中：暂停趋势引用，待复审后重新签发")
    elif not cert.trend_eligible:
        included = False
        reasons.append(
            f"证书状态为{STATUS_LABELS.get(cert.status, cert.status)}：不符合趋势用途"
        )
    if version is None:
        included = False
        reasons.append("点位档案在该调查日无有效版本，无法确定分层归属")

    habitat = version.habitat if version else ""
    band, band_name = _band_for(rulebook, version) if (rulebook and version) else ("", "")
    if included and not band:
        included = False
        reasons.append("点位海拔超出规则册海拔带定义：不纳入分层，不外推")
    season_type = _season_type(run.season_code)
    stratum_key = f"{habitat}|{band}|{season_type}" if band else ""
    segment_key = f"{station.code}:v{version.version_number}" if version else station.code

    effort = compute_unit_effort(db, unit, gates, species)
    materials = _unit_materials(db, gates)
    boundaries = _migration_boundaries(versions, run.season_start, run.season_end)
    tolerance = float((rulebook.requirements or {}).get("time", {}).get("tolerance_seconds", 120))
    excluded = _excluded_materials(
        materials, calibrations_by_station.get(unit.station_id, []), boundaries, tolerance
    )
    excluded_ids = {e["record_id"] for e in excluded}

    min_conf = float((rulebook.requirements or {}).get("reading", {}).get("min_confidence", 0.7))
    material_ids = [m.id for m in materials if m.id not in excluded_ids]
    observations: list[Determination] = []
    if material_ids:
        observations = [
            d
            for d in db.execute(
                select(Determination)
                .where(Determination.material_record_id.in_(material_ids))
                .where(Determination.status == "active")
                .where(Determination.species_code == analysis.species_code)
                .where(Determination.verdict == "present")
            ).scalars()
            if d.confidence >= min_conf
        ]
    if included:
        status_label = STATUS_LABELS.get(cert.status, cert.status) if cert else ""
        reasons.insert(
            0,
            f"证书{status_label}、趋势用途可用；点段 {segment_key}；分层 {habitat}×{band_name or band}",
        )

    return {
        "unit_id": unit.id,
        "year": year,
        "station_id": station.id,
        "station_code": station.code,
        "station_name": station.name,
        "unit_date": unit.unit_date.isoformat(),
        "station_version_id": version.id if version else None,
        "version_number": version.version_number if version else None,
        "segment_key": segment_key,
        "point_role": point_role,
        "stratum_key": stratum_key,
        "habitat": habitat,
        "elevation_band": band,
        "included": included,
        "reasons": reasons,
        "effort_days": effort["effort_days"] if included or point_role == "exploration" else 0.0,
        "effort_detail": effort,
        "observation_count": len(observations) if included or point_role == "exploration" else 0,
        "certificate_id": cert.id if cert else None,
        "certificate_no": cert.certificate_no if cert else "",
        "determination_ids": sorted(d.id for d in observations),
        "material_ids": sorted(material_ids),
        "excluded_materials": excluded,
    }


# --------------------------------------------------------------- aggregation
def _rate(obs: float, effort: float) -> float | None:
    return round(obs / effort, 4) if effort > 0 else None


def _slope(years: list[int], rates: dict[int, float | None]) -> tuple[float | None, float]:
    pts = [(y, rates[y]) for y in years if rates.get(y) is not None]
    if len(pts) < 2:
        return None, 0.0
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    x_bar = sum(xs) / len(xs)
    y_bar = sum(ys) / len(ys)
    sxx = sum((x - x_bar) ** 2 for x in xs)
    if sxx == 0:
        return None, 0.0
    slope = sum((x - x_bar) * (y - y_bar) for x, y in pts) / sxx
    return round(slope, 4), sxx


def aggregate_rows(
    rows: list[dict[str, Any]], years: list[int]
) -> dict[str, Any]:
    """Core aggregation: per-year raw rates, stratified standardized rates and
    the separate fixed-point reference series. Used both for the live results
    and for the counterfactual hybrids in the revision decomposition."""
    included = [r for r in rows if r["included"]]
    strata: dict[str, dict[str, Any]] = {}
    for row in included:
        st = strata.setdefault(
            row["stratum_key"],
            {
                "stratum_key": row["stratum_key"],
                "habitat": row["habitat"],
                "elevation_band": row["elevation_band"],
                "by_year": defaultdict(lambda: {"effort": 0.0, "obs": 0}),
            },
        )
        bucket = st["by_year"][row["year"]]
        bucket["effort"] += row["effort_days"]
        bucket["obs"] += row["observation_count"]

    stratum_list = []
    for st in strata.values():
        years_present = [y for y in years if st["by_year"].get(y, {}).get("effort", 0.0) > 0]
        st["years_present"] = years_present
        st["common"] = len(years_present) == len(years)
        st["pooled_effort"] = sum(st["by_year"].get(y, {}).get("effort", 0.0) for y in years)
        stratum_list.append(st)

    common = [st for st in stratum_list if st["common"]]
    total_common_effort = sum(st["pooled_effort"] for st in common)
    weights = {
        st["stratum_key"]: (st["pooled_effort"] / total_common_effort if total_common_effort else 0.0)
        for st in common
    }

    yearly: dict[int, dict[str, Any]] = {}
    for year in years:
        rows_y = [r for r in included if r["year"] == year]
        effort_y = sum(r["effort_days"] for r in rows_y)
        obs_y = sum(r["observation_count"] for r in rows_y)
        std_rate = 0.0
        var = 0.0
        for st in common:
            bucket = st["by_year"].get(year)
            if not bucket or bucket["effort"] <= 0:
                continue
            r_sy = bucket["obs"] / bucket["effort"]
            w = weights[st["stratum_key"]]
            std_rate += w * r_sy
            var += (w**2) * (r_sy * (1 - r_sy) / bucket["effort"])
        se = var**0.5
        yearly[year] = {
            "year": year,
            "effort_days": round(effort_y, 3),
            "observations": obs_y,
            "raw_rate": _rate(obs_y, effort_y),
            "standardized_rate": round(std_rate, 4) if common else None,
            "se": round(se, 4),
            "interval": [
                round(max(0.0, std_rate - Z_80 * se), 4),
                round(min(1.0, std_rate + Z_80 * se), 4),
            ]
            if common
            else None,
            "included_units": len(rows_y),
        }

    std_rates = {y: yearly[y]["standardized_rate"] for y in years}
    slope, sxx = _slope(years, std_rates)
    slope_se = None
    if slope is not None and sxx:
        x_bar = sum(years) / len(years)
        var_slope = sum(
            ((y - x_bar) / sxx) ** 2 * (yearly[y]["se"] ** 2)
            for y in years
            if yearly[y]["standardized_rate"] is not None
        )
        slope_se = var_slope**0.5
    slope_interval = (
        [round(slope - Z_80 * slope_se, 4), round(slope + Z_80 * slope_se, 4)]
        if slope is not None and slope_se is not None
        else None
    )
    if slope is None or slope_interval is None or (
        slope_interval[0] <= 0 <= slope_interval[1]
    ):
        direction = "变化不确定"
    else:
        direction = "上升" if slope > 0 else "下降"

    # Fixed-point reference series: core points with a single archive version
    # across the whole window. Kept fully separate from the standardized trend.
    fixed_rows = [r for r in included if r["point_role"] == "core" and r.get("fixed_point")]
    fixed_yearly: dict[int, dict[str, Any]] = {}
    for year in years:
        rows_y = [r for r in fixed_rows if r["year"] == year]
        effort_y = sum(r["effort_days"] for r in rows_y)
        obs_y = sum(r["observation_count"] for r in rows_y)
        fixed_yearly[year] = {
            "year": year,
            "effort_days": round(effort_y, 3),
            "observations": obs_y,
            "rate": _rate(obs_y, effort_y),
            "units": len(rows_y),
        }
    fixed_rates = {y: fixed_yearly[y]["rate"] for y in years}
    fixed_slope, _ = _slope(years, fixed_rates)

    return {
        "yearly": yearly,
        "standardized": {
            "rates": std_rates,
            "slope_per_year": slope,
            "slope_interval": slope_interval,
            "direction": direction,
            "weights": weights,
        },
        "strata": stratum_list,
        "fixed": {"yearly": fixed_yearly, "slope_per_year": fixed_slope},
    }


def build_results(
    rows: list[dict[str, Any]],
    years: list[int],
    meta: dict[str, Any],
) -> dict[str, Any]:
    core = aggregate_rows(rows, years)

    strata_table = []
    insufficient = []
    for st in sorted(core["strata"], key=lambda s: s["stratum_key"]):
        weight = core["standardized"]["weights"].get(st["stratum_key"], 0.0)
        per_year = {}
        min_effort = None
        for y in years:
            bucket = st["by_year"].get(y)
            if bucket and bucket["effort"] > 0:
                per_year[str(y)] = {
                    "effort_days": round(bucket["effort"], 3),
                    "observations": bucket["obs"],
                    "rate": _rate(bucket["obs"], bucket["effort"]),
                }
                min_effort = bucket["effort"] if min_effort is None else min(min_effort, bucket["effort"])
            else:
                per_year[str(y)] = None
        coverage_flag = "adequate"
        if st["common"] and (min_effort is None or min_effort < TREND_MIN_STRATUM_EFFORT_DAYS):
            coverage_flag = "insufficient_effort"
        entry = {
            "stratum_key": st["stratum_key"],
            "habitat": st["habitat"],
            "elevation_band": st["elevation_band"],
            "common": st["common"],
            "weight": round(weight, 4),
            "coverage_flag": coverage_flag,
            "years_present": st["years_present"],
            "per_year": per_year,
        }
        strata_table.append(entry)
        if not st["common"]:
            missing = [y for y in years if y not in st["years_present"]]
            insufficient.append(
                {
                    "stratum_key": st["stratum_key"],
                    "habitat": st["habitat"],
                    "elevation_band": st["elevation_band"],
                    "years_present": st["years_present"],
                    "missing_years": missing,
                    "reason": (
                        f"该层仅在 {st['years_present']} 年有有效覆盖，"
                        "跨年范围不重叠，不做外推，不纳入标准化"
                    ),
                }
            )

    # Independent observations: exploration points never enter the trend.
    independent: dict[tuple, dict[str, Any]] = {}
    for row in rows:
        if row["point_role"] != "exploration":
            continue
        key = (row["year"], row["station_code"])
        bucket = independent.setdefault(
            key,
            {
                "year": row["year"],
                "station_code": row["station_code"],
                "station_name": row["station_name"],
                "effort_days": 0.0,
                "observations": 0,
                "units": 0,
                "note": "新增探索点：仅发布独立观测，不纳入跨年趋势与分层标准化",
            },
        )
        bucket["effort_days"] += row["effort_days"]
        bucket["observations"] += row["observation_count"]
        bucket["units"] += 1
    for bucket in independent.values():
        bucket["effort_days"] = round(bucket["effort_days"], 3)

    fixed_points = sorted(
        {r["station_code"] for r in rows if r["included"] and r.get("fixed_point")}
    )
    excluded_rows = [r for r in rows if not r["included"] and r["point_role"] != "exploration"]
    species = meta["species"]
    results = {
        "method": "stratified_standardization",
        "method_label": "生境×海拔带×季节分层标准化（固定点位序列单独参照）",
        "species": {
            "code": species.get("code"),
            "name": species.get("name"),
            "activity": species.get("activity", ""),
            "daily_windows": species.get("daily_windows"),
        },
        "years": years,
        "yearly": [core["yearly"][y] for y in years],
        "trend": {
            "slope_per_year": core["standardized"]["slope_per_year"],
            "slope_interval": core["standardized"]["slope_interval"],
            "direction": core["standardized"]["direction"],
            "interpretation": (
                "标准化观测率的年际变化同时携带覆盖、努力量与判读变化的影响；"
                "即使方向统计上可辨，也只能解读为观测率变化，不能解释为已确认的种群增长。"
            ),
        },
        "strata": strata_table,
        "insufficient_ranges": insufficient,
        "fixed_point_series": {
            "note": "固定点位序列为独立参照：样本直接可比但排除新覆盖生境，"
            "且在固定点失效后序列中断；不得与分层标准化趋势拼接为一条序列。",
            "points": fixed_points,
            "yearly": [core["fixed"]["yearly"][y] for y in years],
            "slope_per_year": core["fixed"]["slope_per_year"],
        },
        "independent_observations": sorted(
            independent.values(), key=lambda b: (b["year"], b["station_code"])
        ),
        "excluded_unit_count": len(excluded_rows),
        "warnings": meta.get("warnings", []),
        "disclaimers": DISCLAIMERS,
    }
    return results


# ------------------------------------------------------------------ run/book
def _fixed_point_flags(
    rows: list[dict[str, Any]], versions_by_station: dict[int, list[StationVersion]]
) -> None:
    """Mark rows that belong to continuous fixed points (core role every year,
    single archive version across the analysis window)."""
    role_by_station_year: dict[int, set[int]] = defaultdict(set)
    for row in rows:
        if row["point_role"] == "core":
            role_by_station_year[row["station_id"]].add(row["year"])
    years = {row["year"] for row in rows}
    for row in rows:
        versions = versions_by_station.get(row["station_id"], [])
        row["fixed_point"] = (
            row["point_role"] == "core"
            and role_by_station_year.get(row["station_id"], set()) == years
            and len(versions) == 1
        )


def compute_analysis(db: Session, analysis: TrendAnalysis) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    preferred: dict[int, int] = {}
    if analysis.current_brief_id:
        old = db.get(TrendBrief, analysis.current_brief_id)
        if old is not None:
            preferred = {
                int(p["plan_id"]): int(p["run_id"])
                for p in (old.inputs or {}).get("plans", [])
                if p.get("plan_id") and p.get("run_id")
            }
    rows, meta = build_unit_inputs(db, analysis, preferred)
    versions_by_station: dict[int, list[StationVersion]] = defaultdict(list)
    for v in db.execute(select(StationVersion)).scalars():
        versions_by_station[v.station_id].append(v)
    _fixed_point_flags(rows, versions_by_station)
    years = sorted(analysis.years)
    results = build_results(rows, years, meta)
    # Per-unit display weight within each year (common strata only).
    weights = results["strata"]
    weight_by_key = {s["stratum_key"]: s["weight"] for s in weights}
    for row in rows:
        if not row["included"]:
            row["weight"] = 0.0
            continue
        w_s = weight_by_key.get(row["stratum_key"], 0.0)
        stratum_effort = sum(
            r["effort_days"]
            for r in rows
            if r["included"] and r["year"] == row["year"] and r["stratum_key"] == row["stratum_key"]
        )
        row["weight"] = round(w_s * row["effort_days"] / stratum_effort, 6) if stratum_effort else 0.0
    inputs = {
        "plans": meta["plans"],
        "units": rows,
        "generated_at": utcnow().isoformat(),
    }
    return rows, {"inputs": inputs, "results": results}


def _decomposition(
    old_units: list[dict[str, Any]], new_units: list[dict[str, Any]], years: list[int]
) -> dict[str, Any]:
    """Split the standardized-trend change into coverage / effort / interpretation.

    Sequential counterfactuals: start from the old brief's inputs, first swap in
    the new coverage (strata membership, inclusion, weights), then the new
    effort, then the new observation counts. Each step's delta in the
    standardized rate is attributed to that factor; the three steps sum exactly
    to the total change by construction.
    """
    old_by_id = {u["unit_id"]: u for u in old_units}

    def hybrid(with_coverage: bool, with_effort: bool, with_obs: bool) -> list[dict[str, Any]]:
        rows = []
        for unit in new_units:
            row = dict(unit)
            old = old_by_id.get(unit["unit_id"])
            if old is not None:
                if not with_effort:
                    row["effort_days"] = old["effort_days"]
                if not with_obs:
                    row["observation_count"] = old["observation_count"]
            rows.append(row)
        return rows

    base_old = aggregate_rows(old_units, years)
    step_coverage = aggregate_rows(hybrid(True, False, False), years)
    step_effort = aggregate_rows(hybrid(True, True, False), years)
    step_new = aggregate_rows(new_units, years)

    def std(series, year):
        value = series["yearly"][year]["standardized_rate"]
        return value if value is not None else 0.0

    per_year = []
    for year in years:
        a = std(base_old, year)
        b = std(step_coverage, year)
        c = std(step_effort, year)
        d = std(step_new, year)
        per_year.append(
            {
                "year": year,
                "before": round(a, 4),
                "after": round(d, 4),
                "delta_total": round(d - a, 4),
                "delta_coverage": round(b - a, 4),
                "delta_effort": round(c - b, 4),
                "delta_interpretation": round(d - c, 4),
            }
        )

    def slope_of(series):
        return series["standardized"]["slope_per_year"] or 0.0

    slope_old = slope_of(base_old)
    changed_units = []
    new_by_id = {u["unit_id"]: u for u in new_units}
    for unit_id in sorted(set(old_by_id) | set(new_by_id)):
        old = old_by_id.get(unit_id)
        new = new_by_id.get(unit_id)
        factors = []
        if (old is None) != (new is None) or (
            old and new
            and (
                old["stratum_key"] != new["stratum_key"]
                or old["included"] != new["included"]
                or old["segment_key"] != new["segment_key"]
            )
        ):
            factors.append("coverage")
        if old and new and abs(old["effort_days"] - new["effort_days"]) > 1e-6:
            factors.append("effort")
        if old and new and old["observation_count"] != new["observation_count"]:
            factors.append("interpretation")
        if old is None or new is None:
            factors = factors or ["coverage"]
        if not factors:
            continue
        ref = new or old
        changed_units.append(
            {
                "unit_id": unit_id,
                "station_code": ref["station_code"],
                "year": ref["year"],
                "unit_date": ref["unit_date"],
                "factors": factors,
                "before": (
                    {
                        "included": old["included"],
                        "stratum_key": old["stratum_key"],
                        "effort_days": old["effort_days"],
                        "observation_count": old["observation_count"],
                        "certificate_no": old["certificate_no"],
                    }
                    if old
                    else None
                ),
                "after": (
                    {
                        "included": new["included"],
                        "stratum_key": new["stratum_key"],
                        "effort_days": new["effort_days"],
                        "observation_count": new["observation_count"],
                        "certificate_no": new["certificate_no"],
                    }
                    if new
                    else None
                ),
            }
        )
    return {
        "note": "按 覆盖 → 努力量 → 判读 顺序做反事实分解，三步之和等于总变化；"
        "顺序不同数值会略有差异，分解用于归因解释而非精确分摊。",
        "per_year": per_year,
        "slope": {
            "before": round(slope_old, 4),
            "after": round(slope_of(step_new), 4),
            "delta_coverage": round(slope_of(step_coverage) - slope_old, 4),
            "delta_effort": round(slope_of(step_effort) - slope_of(step_coverage), 4),
            "delta_interpretation": round(slope_of(step_new) - slope_of(step_effort), 4),
        },
        "changed_units": changed_units,
    }


def run_analysis(db: Session, analysis: TrendAnalysis, actor: str, note: str = "") -> TrendBrief:
    rows, computed = compute_analysis(db, analysis)
    inputs = computed["inputs"]
    results = computed["results"]

    old_brief = db.get(TrendBrief, analysis.current_brief_id) if analysis.current_brief_id else None
    resolved_reasons = list(analysis.stale_reasons or [])
    if old_brief is not None:
        results["decomposition"] = _decomposition(
            old_brief.inputs.get("units", []), inputs["units"], sorted(analysis.years)
        )
        results["recomputed_for"] = resolved_reasons
        old_brief.status = "superseded"

    # Replace the relational input rows (they always mirror the current brief).
    for stale_row in db.execute(
        select(TrendAnalysisUnit).where(TrendAnalysisUnit.analysis_id == analysis.id)
    ).scalars():
        db.delete(stale_row)
    db.flush()
    for row in inputs["units"]:
        db.add(
            TrendAnalysisUnit(
                analysis_id=analysis.id,
                unit_id=row["unit_id"],
                year=row["year"],
                unit_date=date.fromisoformat(row["unit_date"]) if row.get("unit_date") else None,
                station_id=row["station_id"],
                station_code=row["station_code"],
                station_version_id=row["station_version_id"],
                segment_key=row["segment_key"],
                point_role=row["point_role"],
                stratum_key=row["stratum_key"],
                habitat=row["habitat"],
                elevation_band=row["elevation_band"],
                included=row["included"],
                reasons=row["reasons"],
                effort_days=row["effort_days"],
                observation_count=row["observation_count"],
                weight=row["weight"],
                certificate_id=row["certificate_id"],
                certificate_no=row["certificate_no"],
                determination_ids=row["determination_ids"],
                material_ids=row["material_ids"],
                excluded_materials=row["excluded_materials"],
            )
        )
    version = (old_brief.version + 1) if old_brief else 1
    brief = TrendBrief(
        analysis_id=analysis.id,
        version=version,
        status="current",
        input_hash=canonical_hash(inputs),
        inputs=inputs,
        results=results,
        note=note,
        created_by=actor,
    )
    db.add(brief)
    db.flush()
    analysis.current_brief_id = brief.id
    analysis.status = "completed"
    analysis.stale_reasons = []
    db.add(
        AuditEvent(
            entity_type="trend_analysis",
            entity_id=analysis.id,
            action="trend_analysis.recomputed" if old_brief else "trend_analysis.created",
            actor=actor,
            detail={
                "brief_version": version,
                "input_hash": brief.input_hash,
                "resolved_reasons": resolved_reasons,
                "note": note,
            },
        )
    )
    return brief


def create_analysis(
    db: Session, *, species_code: str, plan_ids: list[int], label: str, actor: str
) -> TrendAnalysis:
    plans = list(
        db.execute(select(AnnualSurveyPlan).where(AnnualSurveyPlan.id.in_(plan_ids))).scalars()
    )
    if len(plans) != len(set(plan_ids)):
        raise ValueError("年度调查计划不存在或重复")
    plans.sort(key=lambda p: p.year)
    species_name = ""
    for plan in plans:
        for entry in plan.target_species or []:
            if entry.get("code") == species_code:
                species_name = entry.get("name", "")
    if not species_name:
        raise ValueError(f"年度计划中不存在目标物种 {species_code}")
    count = db.execute(select(sa_func.count()).select_from(TrendAnalysis)).scalar_one()
    years = [p.year for p in plans]
    analysis = TrendAnalysis(
        analysis_code=f"TA-{species_code}-{years[0]}-{years[-1]}-{count + 1:02d}",
        label=label,
        species_code=species_code,
        species_name=species_name,
        method="stratified_standardization",
        plan_ids=[p.id for p in plans],
        years=years,
        status="stale",
        created_by=actor,
    )
    db.add(analysis)
    db.flush()
    brief = run_analysis(db, analysis, actor, note="首次计算")
    analysis.current_brief_id = brief.id
    return analysis


def mark_analyses_stale(
    db: Session,
    *,
    unit_ids: list[int],
    reason: str,
    factor: str,
    actor: str,
) -> list[TrendAnalysis]:
    """Mark analyses whose current inputs reference the affected units as stale.

    The affected strata and year comparisons are found by following the unit
    references, so a revision never updates a numerator while silently keeping
    the old denominator: the whole analysis waits for recompute.
    """
    if not unit_ids:
        return []
    rows = list(
        db.execute(
            select(TrendAnalysisUnit).where(TrendAnalysisUnit.unit_id.in_(sorted(set(unit_ids))))
        ).scalars()
    )
    by_analysis: dict[int, list[TrendAnalysisUnit]] = defaultdict(list)
    for row in rows:
        by_analysis[row.analysis_id].append(row)
    affected: list[TrendAnalysis] = []
    for analysis_id, group in by_analysis.items():
        analysis = db.get(TrendAnalysis, analysis_id)
        if analysis is None:
            continue
        entry = {
            "reason": reason,
            "factor": factor,
            "affected_strata": sorted({r.stratum_key for r in group if r.stratum_key}),
            "affected_years": sorted({r.year for r in group}),
            "unit_ids": sorted({r.unit_id for r in group}),
            "actor": actor,
            "at": utcnow().isoformat(),
        }
        analysis.status = "stale"
        analysis.stale_reasons = list(analysis.stale_reasons or []) + [entry]
        db.add(
            AuditEvent(
                entity_type="trend_analysis",
                entity_id=analysis.id,
                action="trend_analysis.marked_stale",
                actor=actor,
                detail=entry,
            )
        )
        affected.append(analysis)
    return affected
