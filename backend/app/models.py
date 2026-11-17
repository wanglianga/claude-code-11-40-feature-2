from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    display_name: Mapped[str] = mapped_column(String(128))
    role: Mapped[str] = mapped_column(String(32), default="researcher")  # researcher | auditor | viewer
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Zone(Base):
    __tablename__ = "zones"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str] = mapped_column(Text, default="")

    stations: Mapped[list["Station"]] = relationship(back_populates="zone")


class Station(Base):
    __tablename__ = "stations"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(128))
    zone_id: Mapped[int] = mapped_column(ForeignKey("zones.id"))
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    elevation_min_m: Mapped[float] = mapped_column(Float)
    elevation_max_m: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(32), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    zone: Mapped[Zone] = relationship(back_populates="stations")
    versions: Mapped[list["StationVersion"]] = relationship(
        back_populates="station", order_by="StationVersion.version_number"
    )


class StationVersion(Base):
    __tablename__ = "station_versions"
    __table_args__ = (UniqueConstraint("station_id", "version_number", name="uq_station_version"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    station_id: Mapped[int] = mapped_column(ForeignKey("stations.id"), index=True)
    version_number: Mapped[int] = mapped_column(Integer)
    boundary: Mapped[dict[str, Any]] = mapped_column(JSONB)  # GeoJSON Polygon
    buffer_width_m: Mapped[float] = mapped_column(Float)
    centroid_lat: Mapped[float] = mapped_column(Float)
    centroid_lon: Mapped[float] = mapped_column(Float)
    elevation_min_m: Mapped[float] = mapped_column(Float)
    elevation_max_m: Mapped[float] = mapped_column(Float)
    habitat: Mapped[str] = mapped_column(String(64), default="")
    coord_precision_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    effective_from: Mapped[date] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    change_reason: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    station: Mapped[Station] = relationship(back_populates="versions")


class Rulebook(Base):
    __tablename__ = "rulebooks"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(128))
    zone_id: Mapped[int | None] = mapped_column(ForeignKey("zones.id"), nullable=True)
    description: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    versions: Mapped[list["RulebookVersion"]] = relationship(
        back_populates="rulebook", order_by="RulebookVersion.version_number"
    )


class RulebookVersion(Base):
    __tablename__ = "rulebook_versions"
    __table_args__ = (UniqueConstraint("rulebook_id", "version_number", name="uq_rulebook_version"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    rulebook_id: Mapped[int] = mapped_column(ForeignKey("rulebooks.id"), index=True)
    version_number: Mapped[int] = mapped_column(Integer)
    label: Mapped[str] = mapped_column(String(128))
    season_code: Mapped[str] = mapped_column(String(32))
    season_start: Mapped[date] = mapped_column(Date)
    season_end: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(32), default="active")  # draft | active | retired
    target_species: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    requirements: Mapped[dict[str, Any]] = mapped_column(JSONB)
    route_segments: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    elevation_bands: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    rulebook: Mapped[Rulebook] = relationship(back_populates="versions")


class ArchiveRecord(Base):
    __tablename__ = "archive_records"
    __table_args__ = (
        Index("ix_archive_station_event", "station_id", "event_time"),
        Index("ix_archive_type_event", "record_type", "event_time"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    record_type: Mapped[str] = mapped_column(String(32), index=True)
    external_id: Mapped[str] = mapped_column(String(128), index=True)
    station_id: Mapped[int] = mapped_column(ForeignKey("stations.id"))
    zone_id: Mapped[int] = mapped_column(ForeignKey("zones.id"))
    station_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("station_versions.id"), nullable=True
    )
    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    received_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source_device: Mapped[str] = mapped_column(String(64))
    device_type: Mapped[str] = mapped_column(String(32), default="camera")
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    coord_precision_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    payload_hash: Mapped[str] = mapped_column(String(64))
    revision: Mapped[int] = mapped_column(Integer, default=1)
    record_status: Mapped[str] = mapped_column(String(32), default="active")
    superseded_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("archive_records.id"), nullable=True
    )
    created_by: Mapped[str] = mapped_column(String(64), default="ingest")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    revisions: Mapped[list["RecordRevision"]] = relationship(
        back_populates="record", order_by="RecordRevision.revision_number"
    )


class RecordRevision(Base):
    __tablename__ = "record_revisions"

    id: Mapped[int] = mapped_column(primary_key=True)
    record_id: Mapped[int] = mapped_column(ForeignKey("archive_records.id"), index=True)
    revision_number: Mapped[int] = mapped_column(Integer)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    payload_hash: Mapped[str] = mapped_column(String(64))
    received_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    changed_by: Mapped[str] = mapped_column(String(64))
    change_reason: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    record: Mapped[ArchiveRecord] = relationship(back_populates="revisions")


class Determination(Base):
    __tablename__ = "determinations"
    __table_args__ = (Index("ix_det_material_status", "material_record_id", "status"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    material_record_id: Mapped[int] = mapped_column(ForeignKey("archive_records.id"))
    source_record_id: Mapped[int | None] = mapped_column(
        ForeignKey("archive_records.id"), nullable=True
    )
    source: Mapped[str] = mapped_column(String(64))  # analyst | model | partner
    species_code: Mapped[str] = mapped_column(String(64), index=True)
    verdict: Mapped[str] = mapped_column(String(32))  # present | absent | uncertain
    confidence: Mapped[float] = mapped_column(Float)
    analyst: Mapped[str] = mapped_column(String(64), default="")
    revision: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(32), default="active")  # active | superseded | revoked
    superseded_by_id: Mapped[int | None] = mapped_column(ForeignKey("determinations.id"), nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SurveyRun(Base):
    __tablename__ = "survey_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_code: Mapped[str] = mapped_column(String(64), unique=True)
    label: Mapped[str] = mapped_column(String(128))
    season_code: Mapped[str] = mapped_column(String(32))
    season_start: Mapped[date] = mapped_column(Date)
    season_end: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(32), default="active")  # active | superseded
    rulebook_version_id: Mapped[int] = mapped_column(ForeignKey("rulebook_versions.id"))
    model_version_id: Mapped[int | None] = mapped_column(ForeignKey("probability_models.id"), nullable=True)
    created_by: Mapped[str] = mapped_column(String(64), default="system")
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    units: Mapped[list["SurveyUnit"]] = relationship(back_populates="run")


class SurveyUnit(Base):
    __tablename__ = "survey_units"
    __table_args__ = (
        UniqueConstraint("run_id", "station_id", "zone_id", "unit_date", name="uq_survey_unit"),
        Index("ix_unit_station_date", "station_id", "unit_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("survey_runs.id"), index=True)
    station_id: Mapped[int] = mapped_column(ForeignKey("stations.id"))
    zone_id: Mapped[int] = mapped_column(ForeignKey("zones.id"))
    unit_date: Mapped[date] = mapped_column(Date)
    station_version_id: Mapped[int] = mapped_column(ForeignKey("station_versions.id"))
    rulebook_version_id: Mapped[int] = mapped_column(ForeignKey("rulebook_versions.id"))
    model_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("probability_models.id"), nullable=True
    )
    assembled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    coverage_summary: Mapped[dict[str, Any]] = mapped_column(JSONB)
    feature_vector: Mapped[dict[str, Any]] = mapped_column(JSONB)
    gate_status: Mapped[dict[str, Any]] = mapped_column(JSONB)
    data_issues: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)

    run: Mapped[SurveyRun] = relationship(back_populates="units")
    gates: Mapped[list["GateCheck"]] = relationship(back_populates="unit")
    certificate: Mapped["Certificate | None"] = relationship(back_populates="unit", uselist=False)


class GateCheck(Base):
    __tablename__ = "gate_checks"

    id: Mapped[int] = mapped_column(primary_key=True)
    unit_id: Mapped[int] = mapped_column(ForeignKey("survey_units.id"), index=True)
    gate: Mapped[str] = mapped_column(String(16))
    requirement_code: Mapped[str] = mapped_column(String(64))
    evaluation_round: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(32))  # pass | restricted | fail | pending
    measured: Mapped[dict[str, Any]] = mapped_column(JSONB)
    threshold: Mapped[dict[str, Any]] = mapped_column(JSONB)
    explanation: Mapped[str] = mapped_column(Text)
    rule_ref: Mapped[str] = mapped_column(String(128))
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    unit: Mapped[SurveyUnit] = relationship(back_populates="gates")


class Certificate(Base):
    __tablename__ = "certificates"
    __table_args__ = (Index("ix_cert_unit_status", "unit_id", "status"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    unit_id: Mapped[int] = mapped_column(ForeignKey("survey_units.id"), index=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("survey_runs.id"), index=True)
    certificate_no: Mapped[str] = mapped_column(String(64), unique=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(32))  # valid | restricted | invalid | pending
    absence_eligible: Mapped[bool] = mapped_column(Boolean, default=False)
    trend_eligible: Mapped[bool] = mapped_column(Boolean, default=False)
    review_status: Mapped[str] = mapped_column(String(32), default="normal")  # normal | under_review
    review_reason: Mapped[str] = mapped_column(Text, default="")
    summary: Mapped[str] = mapped_column(Text)
    gate_snapshot: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    conclusions: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    superseded_by_id: Mapped[int | None] = mapped_column(ForeignKey("certificates.id"), nullable=True)

    unit: Mapped[SurveyUnit] = relationship(back_populates="certificate")


class ReadingConflict(Base):
    __tablename__ = "reading_conflicts"

    id: Mapped[int] = mapped_column(primary_key=True)
    unit_id: Mapped[int] = mapped_column(ForeignKey("survey_units.id"), index=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("survey_runs.id"), index=True)
    material_record_id: Mapped[int] = mapped_column(ForeignKey("archive_records.id"))
    station_id: Mapped[int] = mapped_column(ForeignKey("stations.id"))
    zone_id: Mapped[int] = mapped_column(ForeignKey("zones.id"))
    species_code: Mapped[str] = mapped_column(String(64))
    sources: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    detail: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="open")  # open | resolved
    resolution: Mapped[str] = mapped_column(Text, default="")
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ProbabilityModel(Base):
    __tablename__ = "probability_models"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(128))
    version: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32), default="active")  # active | under_review | retired
    threshold: Mapped[float] = mapped_column(Float)
    calibration_sets: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    parameters: Mapped[dict[str, Any]] = mapped_column(JSONB)
    threshold_review: Mapped[dict[str, Any]] = mapped_column(JSONB)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ProbabilityEstimate(Base):
    __tablename__ = "probability_estimates"

    id: Mapped[int] = mapped_column(primary_key=True)
    unit_id: Mapped[int] = mapped_column(ForeignKey("survey_units.id"), index=True)
    model_id: Mapped[int] = mapped_column(ForeignKey("probability_models.id"))
    probability: Mapped[float] = mapped_column(Float)
    interval_low: Mapped[float] = mapped_column(Float)
    interval_high: Mapped[float] = mapped_column(Float)
    threshold_pass: Mapped[bool] = mapped_column(Boolean)
    conclusion: Mapped[str] = mapped_column(String(32))  # supports_partial | below_threshold
    variants: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    assumptions: Mapped[list[str]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TrendReference(Base):
    __tablename__ = "trend_references"

    id: Mapped[int] = mapped_column(primary_key=True)
    reference_code: Mapped[str] = mapped_column(String(64), unique=True)
    purpose: Mapped[str] = mapped_column(String(32))  # absence | trend
    unit_id: Mapped[int] = mapped_column(ForeignKey("survey_units.id"))
    certificate_id: Mapped[int | None] = mapped_column(ForeignKey("certificates.id"), nullable=True)
    probability_estimate_id: Mapped[int | None] = mapped_column(
        ForeignKey("probability_estimates.id"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(32), default="active")  # active | suspended | revoked
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_by: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    suspended_reason: Mapped[str] = mapped_column(Text, default="")
    suspended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    note: Mapped[str] = mapped_column(Text, default="")


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(64), index=True)
    entity_id: Mapped[int] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(64))
    actor: Mapped[str] = mapped_column(String(64))
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AnnualSurveyPlan(Base):
    """Annual survey plan: which points are surveyed this season and for which species.

    Target species entries carry the species' daily surveyable windows so effort can
    be computed against the hours the species is actually detectable, not against a
    generic 24h device day.
    """

    __tablename__ = "annual_survey_plans"

    id: Mapped[int] = mapped_column(primary_key=True)
    plan_code: Mapped[str] = mapped_column(String(64), unique=True)
    year: Mapped[int] = mapped_column(Integer, index=True)
    season_code: Mapped[str] = mapped_column(String(32))
    label: Mapped[str] = mapped_column(String(128))
    target_species: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(32), default="active")  # active | retired
    note: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[str] = mapped_column(String(64), default="system")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    points: Mapped[list["AnnualSurveyPlanPoint"]] = relationship(
        back_populates="plan", order_by="AnnualSurveyPlanPoint.id"
    )


class AnnualSurveyPlanPoint(Base):
    """One surveyed point in an annual plan.

    role: core (连续固定点) | expansion (样线扩充点) | exploration (新增探索点).
    Exploration points are published as independent observations only and never
    enter the cross-year trend.
    """

    __tablename__ = "annual_survey_plan_points"
    __table_args__ = (
        UniqueConstraint("plan_id", "station_id", name="uq_plan_point"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("annual_survey_plans.id"), index=True)
    station_id: Mapped[int] = mapped_column(ForeignKey("stations.id"))
    role: Mapped[str] = mapped_column(String(32), default="expansion")
    note: Mapped[str] = mapped_column(Text, default="")

    plan: Mapped[AnnualSurveyPlan] = relationship(back_populates="points")
    station: Mapped[Station] = relationship()


class TrendAnalysis(Base):
    """A multi-year comparability analysis for one species.

    status: completed | stale. Revisions to maintenance logs, migration dates or
    determinations mark the analysis stale (待重算) with the affected strata/years
    recorded in stale_reasons; the current brief keeps serving its frozen inputs
    until a recompute produces a new brief version.
    """

    __tablename__ = "trend_analyses"

    id: Mapped[int] = mapped_column(primary_key=True)
    analysis_code: Mapped[str] = mapped_column(String(64), unique=True)
    label: Mapped[str] = mapped_column(String(128))
    species_code: Mapped[str] = mapped_column(String(64), index=True)
    species_name: Mapped[str] = mapped_column(String(128), default="")
    method: Mapped[str] = mapped_column(String(64), default="stratified_standardization")
    plan_ids: Mapped[list[int]] = mapped_column(JSONB)
    years: Mapped[list[int]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(32), default="completed")
    stale_reasons: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    current_brief_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_by: Mapped[str] = mapped_column(String(64), default="system")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TrendAnalysisUnit(Base):
    """Current-brief input row: one survey unit's place in the analysis.

    Kept relational (not only inside the brief JSON) so that revisions can find
    affected strata and year comparisons by following unit/station references.
    Rows are replaced on every recompute; historical inputs stay frozen inside
    their TrendBrief.
    """

    __tablename__ = "trend_analysis_units"
    __table_args__ = (
        UniqueConstraint("analysis_id", "unit_id", name="uq_trend_analysis_unit"),
        Index("ix_trend_unit_refs", "analysis_id", "station_id", "year"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    analysis_id: Mapped[int] = mapped_column(ForeignKey("trend_analyses.id"), index=True)
    unit_id: Mapped[int] = mapped_column(ForeignKey("survey_units.id"), index=True)
    year: Mapped[int] = mapped_column(Integer)
    unit_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    station_id: Mapped[int] = mapped_column(ForeignKey("stations.id"))
    station_code: Mapped[str] = mapped_column(String(32))
    station_version_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    segment_key: Mapped[str] = mapped_column(String(64), default="")
    point_role: Mapped[str] = mapped_column(String(32), default="expansion")
    stratum_key: Mapped[str] = mapped_column(String(128), default="")
    habitat: Mapped[str] = mapped_column(String(64), default="")
    elevation_band: Mapped[str] = mapped_column(String(32), default="")
    included: Mapped[bool] = mapped_column(Boolean, default=False)
    reasons: Mapped[list[str]] = mapped_column(JSONB, default=list)
    effort_days: Mapped[float] = mapped_column(Float, default=0.0)
    observation_count: Mapped[int] = mapped_column(Integer, default=0)
    weight: Mapped[float] = mapped_column(Float, default=0.0)
    certificate_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    certificate_no: Mapped[str] = mapped_column(String(64), default="")
    determination_ids: Mapped[list[int]] = mapped_column(JSONB, default=list)
    material_ids: Mapped[list[int]] = mapped_column(JSONB, default=list)
    excluded_materials: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)


class TrendBrief(Base):
    """One frozen edition of an analysis' inputs and results.

    Old briefs are never mutated: they keep the exact per-unit inputs (effort,
    observations, certificate numbers, determination ids) that produced their
    results, so a historical brief can always reproduce its own inputs.
    """

    __tablename__ = "trend_briefs"
    __table_args__ = (
        UniqueConstraint("analysis_id", "version", name="uq_trend_brief_version"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    analysis_id: Mapped[int] = mapped_column(ForeignKey("trend_analyses.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), default="current")  # current | superseded
    input_hash: Mapped[str] = mapped_column(String(64))
    inputs: Mapped[dict[str, Any]] = mapped_column(JSONB)
    results: Mapped[dict[str, Any]] = mapped_column(JSONB)
    note: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[str] = mapped_column(String(64), default="system")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
