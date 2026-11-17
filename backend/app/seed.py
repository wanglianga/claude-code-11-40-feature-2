"""Deterministic seed data covering the acceptance scenarios.

Scenario map (station → what it demonstrates):
  QSL-01  完整有效调查，含可验证校时关系与迟到送达记录；连续三年固定点
  QSL-02  相机帧连续缺失且停机日志未覆盖 → 设备可用性待核
  QSL-03  两来源互斥判读且均低于置信门槛 → 保留冲突（2026）
  QSL-04  待判读占比过高（薄判读）
  YXG-01  轨迹仅擦过缓冲区边缘且定位精度大于缓冲区宽度 → 空间待核
  YXG-02  迟到判读修订改变目标物种出现 → 当前证书复审中、暂停趋势引用
  YXG-03  路线覆盖接近门槛 → 受限证书；概率估计仍支持 → 样本取舍分歧
  BHP-01  设备时间偏移超容差且无可验证校时 → 时间不满足季节窗口
  BHP-02  滑坡后季中迁至不同海拔（HIGH→MID），按事件发生时的站点版本判断
  YXG-04  滑坡季中迁址（季中迁移点），备用机时钟误差跨过迁点边界 → 素材排除
  BHP-03  新增高海拔探索点 + 夜间时段停机 → 仅发布独立观测

多年趋势验收数据：2024（4 站）→ 2025（7 站）→ 2026（11 站）设备总数连续增长；
固定点（QSL-01/QSL-03/YXG-03）、季中迁移点（BHP-02、YXG-04）、新增高海拔点（BHP-03）、
部分时段停机（YXG-04 夜间、BHP-03 夜间）齐备。
"""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select

from .config import RESERVE_TZ
from .db import SessionLocal, init_db
from .models import (
    AnnualSurveyPlan,
    AnnualSurveyPlanPoint,
    ArchiveRecord,
    Determination,
    ProbabilityModel,
    Rulebook,
    RulebookVersion,
    Station,
    StationVersion,
    SurveyRun,
    SurveyUnit,
    User,
    Zone,
)
from .security import hash_password
from .services import (
    build_run,
    create_trend_reference,
    ingest_record,
    revise_determination,
)
from .trends import create_analysis

SEASON = ("2026-04-01", "2026-04-30")
SURVEY_DATES = ["2026-04-10", "2026-04-11", "2026-04-12"]
LAT_M = 110_540.0
LON_M = 111_320.0

SEASONS = {
    2024: {
        "code": "2024-SPRING",
        "start": date(2024, 4, 1),
        "end": date(2024, 4, 30),
        "dates": ["2024-04-10", "2024-04-11", "2024-04-12"],
    },
    2025: {
        "code": "2025-SPRING",
        "start": date(2025, 4, 1),
        "end": date(2025, 4, 30),
        "dates": ["2025-04-10", "2025-04-11", "2025-04-12"],
    },
    2026: {
        "code": "2026-SPRING",
        "start": date(2026, 4, 1),
        "end": date(2026, 4, 30),
        "dates": SURVEY_DATES,
    },
}


def latlon(lat0: float, lon0: float, dx: float, dy: float) -> tuple[float, float]:
    lon = lon0 + math.degrees(dx / (LON_M * math.cos(math.radians(lat0))))
    lat = lat0 + math.degrees(dy / LAT_M)
    return lat, lon


def square_boundary(lat0: float, lon0: float, half: float) -> dict:
    ring_offsets = [
        (-half, -half),
        (half, -half),
        (half, half),
        (-half, half),
        (-half, -half),
    ]
    coords = []
    for dx, dy in ring_offsets:
        lat, lon = latlon(lat0, lon0, dx, dy)
        coords.append([round(lon, 7), round(lat, 7)])
    return {"type": "Polygon", "coordinates": [coords]}


def line_geojson(lat0: float, lon0: float, dx1: float, dy1: float, dx2: float, dy2: float) -> dict:
    lat1, lon1 = latlon(lat0, lon0, dx1, dy1)
    lat2, lon2 = latlon(lat0, lon0, dx2, dy2)
    return {
        "type": "LineString",
        "coordinates": [[round(lon1, 7), round(lat1, 7)], [round(lon2, 7), round(lat2, 7)]],
    }


def utc_iso(day: str, hour: int, minute: int = 0, plus_hours: float = 0.0) -> str:
    d = date.fromisoformat(day)
    base = datetime(d.year, d.month, d.day, hour, minute, tzinfo=RESERVE_TZ)
    return (base + timedelta(hours=plus_hours)).astimezone(timezone.utc).isoformat()


# code, name, zone, lat, lon, half-size m, buffer m, elev range, habitat, 2026 scenario
STATIONS = [
    ("QSL-01", "青松岭主监测站", "QS", 31.050000, 103.620000, 120, 30, (1850, 2050), "针阔混交林", "clean"),
    ("QSL-02", "青松岭北梁相机站", "QS", 31.066000, 103.641000, 120, 30, (1900, 2100), "针阔混交林", "frame_gap"),
    ("QSL-03", "青松岭西沟站", "QS", 31.041000, 103.602000, 120, 30, (1800, 1990), "落叶阔叶林", "conflict"),
    ("QSL-04", "青松岭东南站", "QS", 31.032000, 103.650000, 120, 30, (1750, 1930), "落叶阔叶林", "thin_reading"),
    ("YXG-01", "云溪沟西站", "YX", 30.980000, 103.540000, 120, 30, (1700, 1880), "沟谷阔叶林", "edge"),
    ("YXG-02", "云溪沟东站", "YX", 30.992000, 103.560500, 120, 30, (1720, 1900), "落叶阔叶林", "late_revision"),
    ("YXG-03", "云溪沟下坝站", "YX", 30.970500, 103.522000, 120, 40, (1620, 1790), "沟谷阔叶林", "partial_route"),
    ("BHP-01", "北坡高寒相机站", "BH", 31.120000, 103.700000, 110, 35, (2600, 2820), "高寒针叶林", "clock_drift"),
    ("BHP-02", "北坡垭口迁移站", "BH", 31.135000, 103.718000, 100, 30, (2500, 2760), "高寒针叶林", "migration"),
    ("YXG-04", "云溪沟滑坡迁址站", "YX", 30.965000, 103.548000, 120, 30, (1700, 1860), "沟谷阔叶林", "migration_night"),
    ("BHP-03", "北坡雪线探索站", "BH", 31.150000, 103.740000, 100, 30, (3050, 3250), "高山流石滩灌丛", "night_downtime"),
]

ZONES = [
    ("QS", "青松岭样区", "落叶阔叶林与针阔混交林过渡带，主监测样区。"),
    ("YX", "云溪沟样区", "沿沟谷布设的巡护路线样区，坡度较大。"),
    ("BH", "北坡高海拔样区", "高海拔针叶林与灌丛样区，冬季相机供电紧张。"),
]

# 站点首次进入年度调查计划的年份（设备总数连续三年增长：4 → 7 → 11）
FIRST_YEAR = {
    "QSL-01": 2024, "QSL-03": 2024, "YXG-01": 2024, "YXG-03": 2024,
    "QSL-04": 2025, "YXG-02": 2025, "YXG-04": 2025,
    "QSL-02": 2026, "BHP-01": 2026, "BHP-02": 2026, "BHP-03": 2026,
}

# 各站逐年的数据场景（2026 列与 STATIONS 中一致）
SCENARIOS = {
    "QSL-01": {2024: "clean", 2025: "clean", 2026: "clean"},
    "QSL-02": {2026: "frame_gap"},
    "QSL-03": {2024: "clean", 2025: "clean", 2026: "conflict"},
    "QSL-04": {2025: "thin_reading", 2026: "thin_reading"},
    "YXG-01": {2024: "edge", 2025: "edge", 2026: "edge"},
    "YXG-02": {2025: "clean", 2026: "late_revision"},
    "YXG-03": {2024: "partial_route", 2025: "partial_route", 2026: "partial_route"},
    "BHP-01": {2026: "clock_drift"},
    "BHP-02": {2026: "migration"},
    "YXG-04": {2025: "clean", 2026: "migration_night"},
    "BHP-03": {2026: "night_downtime"},
}

# 大熊猫（AILUROPODA）确认出现判读的帧位（idx 对应当日第 idx 个常规帧，避免与轮替缺位判读同帧）
PRESENTS = {
    ("QSL-01", 2024): {"2024-04-10": [0], "2024-04-11": [3]},
    ("QSL-01", 2025): {"2025-04-10": [0], "2025-04-11": [3], "2025-04-12": [1]},
    ("QSL-01", 2026): {"2026-04-11": [0, 3], "2026-04-12": [1, 4]},
    ("YXG-03", 2024): {"2024-04-11": [0]},
    ("YXG-03", 2025): {"2025-04-11": [0]},
    ("YXG-03", 2026): {"2026-04-10": [0], "2026-04-12": [3]},
    ("QSL-03", 2024): {"2024-04-10": [1]},
    ("QSL-03", 2025): {"2025-04-10": [1], "2025-04-12": [0]},
    ("QSL-03", 2026): {"2026-04-12": [1]},
    ("YXG-02", 2025): {"2025-04-10": [0], "2025-04-11": [3]},
    ("YXG-02", 2026): {"2026-04-10": [0]},
    ("YXG-04", 2025): {"2025-04-11": [0], "2025-04-12": [1]},
    ("YXG-04", 2026): {"2026-04-10": [0], "2026-04-12": [1]},
    ("BHP-03", 2026): {"2026-04-10": [0], "2026-04-11": [3]},
}

TARGET_SPECIES = [
    {"code": "LOPHOPHORUS", "name": "绿尾虹雉", "min_detections": 3},
    {"code": "BUDORCAS", "name": "羚牛", "min_detections": 3},
    {"code": "AILUROPODA", "name": "大熊猫", "min_detections": 1},
]

# 年度计划中的目标物种：含可调查时段（夜间物种不能把白天有效日整套过来）
PLAN_SPECIES = [
    {"code": "AILUROPODA", "name": "大熊猫", "activity": "nocturnal",
     "daily_windows": [["18:00", "24:00"], ["00:00", "06:00"]], "min_detections": 1},
    {"code": "LOPHOPHORUS", "name": "绿尾虹雉", "activity": "diurnal",
     "daily_windows": [["05:00", "19:00"]], "min_detections": 3},
    {"code": "BUDORCAS", "name": "羚牛", "activity": "diurnal",
     "daily_windows": [["06:00", "20:00"]], "min_detections": 3},
]

# YXG-04 迁址后的新点位（东侧约 350m、海拔抬升至 2050m 台地）
YXG04_V2_LAT, YXG04_V2_LON = latlon(30.965000, 103.548000, 350, 180)
YXG04_V2_ELEV = (2050, 2210)


def requirements(survey_dates: list[str]) -> dict:
    return {
        "device": {
            "target_available_hours": 20,
            "min_available_hours": 12,
            "target_available_ratio": 0.83,
            "min_available_ratio": 0.5,
            "max_heartbeat_gap_hours": 6,
            "min_gap_hours": 1,
        },
        "time": {"tolerance_seconds": 120, "late_delivery_hours": 24},
        "space": {
            "target_route_coverage_ratio": 0.8,
            "min_route_coverage_ratio": 0.5,
            "edge_penetration_m": 5,
            "min_in_buffer_ratio": 0.5,
        },
        "reading": {
            "min_confidence": 0.7,
            "max_pending_ratio": 0.25,
            "min_available_observations": 3,
        },
        "schedule": {
            "survey_dates": survey_dates,
            "elevation_band_check": "required",
            "season_window_strict": True,
        },
    }


def route_segments(station_code: str, lat: float, lon: float, half: float, year: int) -> list[dict]:
    segments = [
        {
            "code": f"SEG-{station_code}-A",
            "name": f"{station_code} 主巡护路线",
            "geometry": line_geojson(lat, lon, -80, 0, 80, 0),
            "station_codes": [station_code],
            "elevation_band_m": [1600, 2200],
        }
    ]
    if station_code == "BHP-02":
        segments.append(
            {
                "code": "SEG-BHP-02-B",
                "name": "北坡垭口迁移后新增路线",
                "geometry": line_geojson(lat, lon, 120, 0, 280, 0),
                "station_codes": [station_code],
                "elevation_band_m": [2100, 2400],
                "valid_from": "2026-04-12",
            }
        )
        segments[0]["valid_to"] = "2026-04-11"
    if station_code == "YXG-04" and year >= 2026:
        segments[0]["valid_to"] = "2026-04-11"
        segments.append(
            {
                "code": "SEG-YXG-04-B",
                "name": "云溪沟滑坡迁址后台地路线",
                "geometry": line_geojson(YXG04_V2_LAT, YXG04_V2_LON, -80, 0, 80, 0),
                "station_codes": [station_code],
                "elevation_band_m": [2000, 2300],
                "valid_from": "2026-04-12",
            }
        )
    return segments


def seed_users(db) -> None:
    users = [
        ("yq.li", "李延青", "researcher", "Survey#2026"),
        ("m.cao", "曹敏", "auditor", "Audit#2026"),
        ("l.lin", "林岚", "viewer", "View#2026"),
    ]
    for username, display, role, password in users:
        if db.execute(select(User).where(User.username == username)).scalar_one_or_none():
            continue
        db.add(
            User(
                username=username,
                display_name=display,
                role=role,
                password_hash=hash_password(password),
            )
        )
    db.flush()


def seed_catalog(db):
    zone_map = {}
    for code, name, desc in ZONES:
        zone = Zone(code=code, name=name, description=desc)
        db.add(zone)
        db.flush()
        zone_map[code] = zone

    station_map = {}
    for code, name, zone_code, lat, lon, half, buffer_m, elev, habitat, scenario in STATIONS:
        zone = zone_map[zone_code]
        first_year = FIRST_YEAR[code]
        station = Station(
            code=code,
            name=name,
            zone_id=zone.id,
            latitude=lat,
            longitude=lon,
            elevation_min_m=elev[0],
            elevation_max_m=elev[1],
            status="active",
        )
        db.add(station)
        db.flush()
        if scenario == "migration":
            v1 = StationVersion(
                station_id=station.id,
                version_number=1,
                boundary=square_boundary(lat, lon, half),
                buffer_width_m=buffer_m,
                centroid_lat=lat,
                centroid_lon=lon,
                elevation_min_m=elev[0],
                elevation_max_m=elev[1],
                habitat=habitat,
                coord_precision_m=10.0,
                effective_from=date(first_year, 1, 1),
                effective_to=date(2026, 4, 11),
                change_reason="迁移前边界",
            )
            v2 = StationVersion(
                station_id=station.id,
                version_number=2,
                boundary=square_boundary(lat, lon, half * 1.7),
                buffer_width_m=buffer_m,
                centroid_lat=lat,
                centroid_lon=lon,
                elevation_min_m=2100,
                elevation_max_m=2350,
                habitat="针阔混交林",
                coord_precision_m=10.0,
                effective_from=date(2026, 4, 12),
                effective_to=None,
                change_reason="2026-04-11 滑坡后设备迁至垭口东侧低海拔台地，边界向东扩展 70%",
            )
            db.add_all([v1, v2])
        elif scenario == "migration_night":
            v1 = StationVersion(
                station_id=station.id,
                version_number=1,
                boundary=square_boundary(lat, lon, half),
                buffer_width_m=buffer_m,
                centroid_lat=lat,
                centroid_lon=lon,
                elevation_min_m=elev[0],
                elevation_max_m=elev[1],
                habitat=habitat,
                coord_precision_m=8.0,
                effective_from=date(first_year, 1, 1),
                effective_to=date(2026, 4, 11),
                change_reason="迁址前沟谷点位",
            )
            v2 = StationVersion(
                station_id=station.id,
                version_number=2,
                boundary=square_boundary(YXG04_V2_LAT, YXG04_V2_LON, half),
                buffer_width_m=buffer_m,
                centroid_lat=YXG04_V2_LAT,
                centroid_lon=YXG04_V2_LON,
                elevation_min_m=YXG04_V2_ELEV[0],
                elevation_max_m=YXG04_V2_ELEV[1],
                habitat="针阔混交林",
                coord_precision_m=8.0,
                effective_from=date(2026, 4, 12),
                effective_to=None,
                change_reason="2026-04-11 滑坡损毁原点位，设备迁址至东侧 2050m 台地",
            )
            db.add_all([v1, v2])
        else:
            db.add(
                StationVersion(
                    station_id=station.id,
                    version_number=1,
                    boundary=square_boundary(lat, lon, half),
                    buffer_width_m=buffer_m,
                    centroid_lat=lat,
                    centroid_lon=lon,
                    elevation_min_m=elev[0],
                    elevation_max_m=elev[1],
                    habitat=habitat,
                    coord_precision_m=15.0 if code == "BHP-03" else 8.0,
                    effective_from=date(first_year, 1, 1),
                    effective_to=None,
                    change_reason="初始建站边界",
                )
            )
        db.flush()
        station_map[code] = station
    return zone_map, station_map


def seed_rulebooks(db) -> dict[int, RulebookVersion]:
    """One rulebook master per season; thresholds identical across years so the
    multi-year comparison uses a consistent measuring stick."""
    versions: dict[int, RulebookVersion] = {}
    stations_by_year = {
        year: [spec for spec in STATIONS if FIRST_YEAR[spec[0]] <= year] for year in SEASONS
    }
    for year, season in SEASONS.items():
        master = Rulebook(
            code=f"RB-SPRING-{year}",
            name=f"{year} 春季调查最低要求规则册",
            zone_id=None,
            description="覆盖设备可用、时间可信、空间经过与判读充分四类门槛；按站点—样区—日期形成调查单元。",
        )
        db.add(master)
        db.flush()
        segments = []
        for code, _name, _zc, lat, lon, half, _buf, _elev, _hab, _sc in stations_by_year[year]:
            segments.extend(route_segments(code, lat, lon, half, year))
        v1 = RulebookVersion(
            rulebook_id=master.id,
            version_number=1,
            label=f"{year} 春季正式版",
            season_code=season["code"],
            season_start=season["start"],
            season_end=season["end"],
            status="active" if year == 2026 else "retired",
            target_species=TARGET_SPECIES,
            requirements=requirements(season["dates"]),
            route_segments=segments,
            elevation_bands=[
                {"code": "LOW", "name": "低海拔沟谷", "min_m": 1500, "max_m": 1900},
                {"code": "MID", "name": "中海拔针阔混交", "min_m": 1900, "max_m": 2400},
                {"code": "HIGH", "name": "高海拔针叶灌丛", "min_m": 2400, "max_m": 3000},
            ],
            notes="正式未发现结论只使用本规则册签发的证书。",
        )
        db.add(v1)
        versions[year] = v1
        if year == 2026:
            draft_reqs = requirements(season["dates"])
            draft_reqs["reading"]["min_available_observations"] = 4
            draft_reqs["reading"]["max_pending_ratio"] = 0.15
            v2 = RulebookVersion(
                rulebook_id=master.id,
                version_number=2,
                label="2026 春季修订草案（未启用）",
                season_code=season["code"],
                season_start=season["start"],
                season_end=season["end"],
                status="draft",
                target_species=TARGET_SPECIES,
                requirements=draft_reqs,
                route_segments=segments,
                elevation_bands=v1.elevation_bands,
                notes="草案提高判读门槛，待规则复核后启用。",
            )
            db.add(v2)
    db.flush()
    return versions


def seed_model(db) -> ProbabilityModel:
    # Coverage score is a normalised weighted sum of coverage features (max ~0.85);
    # time trust and unresolved conflicts gate it to zero. Weights and the pivot were
    # calibrated so that route-shortfall units sit just above the 0.80 threshold while
    # thin-reading units sit just below it, which is what makes the rule/probability
    # comparison and the calibration-set sensitivity meaningful.
    model = ProbabilityModel(
        code="DET-LOGIT",
        name="检测概率 logistic 校准模型",
        version="1.3.0",
        status="active",
        threshold=0.80,
        calibration_sets=[
            {"label": "2019-2024 历史样本 (n=486)", "pivot_delta": 0.0, "n": 486},
            {"label": "2019-2023 历史样本 (n=402)", "pivot_delta": 0.04, "n": 402},
        ],
        parameters={
            "pivot": 0.62,
            "slope": 9.0,
            "weights": {
                "device_available_ratio": 0.14,
                "route_coverage_ratio": 0.13,
                "observation_count": 0.19,
                "pending_material_ratio": 0.17,
                "in_buffer_ratio": 0.14,
                "precision_ok": 0.08,
            },
            "gating_features": ["time_ok", "conflict_free"],
            "interval_z": 1.28,
            "interval_scale": 0.55,
        },
        threshold_review={
            "cadence": "每季复核",
            "last_review": "2026-03-25",
            "owner": "监测数据组",
            "next_review": "2026-07-01",
            "note": "阈值复核成本高，调整需同时登记校准集与影响样本数。",
        },
        notes="仅用于趋势研究的覆盖价值估算；不作为正式未发现结论依据。",
    )
    db.add(model)
    db.flush()
    return model


def _record(
    db,
    *,
    station,
    record_type,
    external_id,
    event_time,
    payload,
    device,
    received_time=None,
    lat=None,
    lon=None,
    precision=None,
    actor="seed",
):
    ingest_record(
        db,
        {
            "record_type": record_type,
            "external_id": external_id,
            "station_id": station.id,
            "event_time": event_time,
            "received_time": received_time or event_time,
            "source_device": device,
            "device_type": "camera" if record_type != "patrol_track" else "gps",
            "latitude": lat,
            "longitude": lon,
            "coord_precision_m": precision,
            "payload": payload,
        },
        actor,
    )


def _frame_latlon(station, code, dx, dy):
    return latlon(station.latitude, station.longitude, dx, dy)


def emit_device_day(db, station, scenario, day: str, station_version_lat=None, station_version_lon=None):
    lat0 = station_version_lat or station.latitude
    lon0 = station_version_lon or station.longitude
    code = station.code
    device = f"CAM-{code}"
    # Heartbeats every two hours, with the reserve's normal power budget.
    for hour in range(0, 24, 2):
        _record(
            db,
            station=station,
            record_type="device_heartbeat",
            external_id=f"HB-{code}-{day.replace('-', '')}-{hour:02d}",
            event_time=utc_iso(day, hour),
            payload={
                "battery_pct": 78 - (hour % 6),
                "temperature_c": 4.5,
                "firmware": "3.2.1",
                "heartbeat_seq": hour // 2 + 1,
            },
            device=device,
        )

    # Frame sequence is the key device-health signal: a jump means missing frames.
    if scenario == "frame_gap":
        frame_plan = [(6, 1), (8, 2), (14, 9), (16, 10)]
    elif scenario == "thin_reading":
        frame_plan = [(6, 1), (8, 2), (14, 3), (16, 4)]
    else:
        frame_plan = [(6, 1), (8, 2), (10, 3), (12, 4), (14, 5), (16, 6)]

    # 迁址后的调查日：帧与轨迹都落在 v2 台地点位。
    frame_anchor = (station.latitude, station.longitude)
    if scenario == "migration_night" and day == "2026-04-12":
        frame_anchor = (YXG04_V2_LAT, YXG04_V2_LON)

    frames = []
    for idx, (hour, seq) in enumerate(frame_plan):
        lat, lon = latlon(frame_anchor[0], frame_anchor[1], -60 + idx * 24, 8)
        payload = {
            "frame_seq": seq,
            "image_ref": f"s3://reserve-cam/{code}/{day}/IMG_{seq:04d}.jpg",
            "camera_id": device,
            "exposure_mode": "auto",
        }
        if scenario == "clock_drift":
            payload["clock_offset_seconds"] = 900
            payload["clock_note"] = "设备自检发现 RTC 偏移，未完成校时"
        _record(
            db,
            station=station,
            record_type="camera_event",
            external_id=f"IMG-{code}-{day.replace('-', '')}-{seq:04d}",
            event_time=utc_iso(day, hour),
            received_time=(
                utc_iso(day, hour, plus_hours=30)
                if scenario == "late_revision" and idx == 0
                else utc_iso(day, hour, 5)
            ),
            payload=payload,
            device=device,
            lat=lat,
            lon=lon,
            precision=8.0,
        )
        frames.append({"external_id": f"IMG-{code}-{day.replace('-', '')}-{seq:04d}", "idx": idx})

    # 备用机帧：时钟误差跨过迁点边界（仅 YXG-04 迁址前最后一晚）。
    if scenario == "migration_night" and day == "2026-04-11":
        lat, lon = latlon(station.latitude, station.longitude, 40, -12)
        _record(
            db,
            station=station,
            record_type="camera_event",
            external_id=f"IMG-{code}-{day.replace('-', '')}-B001",
            event_time=utc_iso(day, 23, 52),
            received_time=utc_iso(day, 23, 57),
            payload={
                "frame_seq": 7,
                "image_ref": f"s3://reserve-cam/{code}/{day}/IMG_B001.jpg",
                "camera_id": f"CAM-{code}-B",
                "exposure_mode": "auto",
                "clock_offset_seconds": 900,
                "clock_note": "备用机 RTC 漂移约 15 分钟，无可验证校时关系",
            },
            device=f"CAM-{code}-B",
            lat=lat,
            lon=lon,
            precision=12.0,
        )
        frames.append({"external_id": f"IMG-{code}-{day.replace('-', '')}-B001", "idx": 6, "boundary": True})

    # Documented downtime, except on the day with the unexplained frame gap.
    if scenario == "migration_night":
        downtime = (21, 0, 23, 30, "夜间红外补光灯故障检修（部分时段停机）")
    elif scenario == "night_downtime":
        downtime = (20, 0, 23, 0, "夜间供电切换停机（部分时段停机）")
    else:
        downtime = (10, 15, 12, 15, "计划维护：更换电池与存储卡")
    if scenario != "frame_gap":
        sh, sm, eh, em, reason = downtime
        _record(
            db,
            station=station,
            record_type="downtime_log",
            external_id=f"DT-{code}-{day.replace('-', '')}",
            event_time=utc_iso(day, sh, sm),
            payload={
                "start": utc_iso(day, sh, sm),
                "end": utc_iso(day, eh, em),
                "reason": reason,
                "operator": "巡护一组",
                "camera_id": device,
            },
            device=device,
        )

    # Patrol track: how the route was actually walked.
    if scenario == "edge":
        geometry = line_geojson(lat0, lon0, -300, 149, 300, 149)
        precision = 40.0
        observer = "巡护三组"
    elif scenario == "partial_route":
        geometry = line_geojson(lat0, lon0, -48, 0, 48, 0)
        precision = 9.0
        observer = "巡护二组"
    elif scenario == "migration" and day == "2026-04-12":
        geometry = line_geojson(lat0, lon0, 120, 0, 280, 0)
        precision = 7.0
        observer = "巡护四组"
    elif scenario == "migration_night" and day == "2026-04-12":
        geometry = line_geojson(YXG04_V2_LAT, YXG04_V2_LON, -80, 0, 80, 0)
        precision = 7.0
        observer = "巡护四组"
    else:
        geometry = line_geojson(lat0, lon0, -80, 0, 80, 0)
        precision = 9.0
        observer = "巡护一组"

    _record(
        db,
        station=station,
        record_type="patrol_track",
        external_id=f"TRK-{code}-{day.replace('-', '')}",
        event_time=utc_iso(day, 7),
        received_time=utc_iso(day, 19),
        payload={
            "geometry": geometry,
            "observer": observer,
            "route_code": f"SEG-{code}-A",
            "distance_km": 6.4,
            "elevation_gain_m": 320,
        },
        device=f"GPS-{code}",
        precision=precision,
    )
    return frames


def emit_determinations(db, station, scenario, day: str, frames, presents=()) -> None:
    from .services import add_determination

    code = station.code
    for frame in frames:
        idx = frame["idx"]
        material = db.execute(
            select(ArchiveRecord).where(ArchiveRecord.external_id == frame["external_id"])
        ).scalar_one()
        species = TARGET_SPECIES[idx % len(TARGET_SPECIES)]["code"]
        if frame.get("boundary"):
            add_determination(
                db,
                material_record_id=material.id,
                source="analyst",
                species_code="AILUROPODA",
                verdict="uncertain",
                confidence=0.41,
                analyst="周冕",
                notes="备用机画面昏暗且时钟未校，无法确认，留待复核",
                actor="seed",
            )
            continue
        if scenario == "thin_reading" and idx < 2:
            add_determination(
                db,
                material_record_id=material.id,
                source="analyst",
                species_code=species,
                verdict="uncertain",
                confidence=0.44,
                analyst="周冕",
                notes="光线不足，仅能确认为空帧，未达置信门槛",
                actor="seed",
            )
            continue
        if scenario == "conflict" and day == "2026-04-11" and idx == 2:
            add_determination(
                db,
                material_record_id=material.id,
                source="analyst",
                species_code=species,
                verdict="present",
                confidence=0.58,
                analyst="周冕",
                notes="形态疑似，未见清晰体侧斑纹",
                actor="seed",
            )
            add_determination(
                db,
                material_record_id=material.id,
                source="partner",
                species_code=species,
                verdict="absent",
                confidence=0.49,
                analyst="合作机构判读模型",
                notes="无相似目标特征",
                actor="seed",
            )
            continue
        if scenario == "late_revision" and day == "2026-04-11" and idx == 1:
            add_determination(
                db,
                material_record_id=material.id,
                source="analyst",
                species_code=species,
                verdict="absent",
                confidence=0.82,
                analyst="周冕",
                notes="初判未见目标物种",
                actor="seed",
            )
            continue
        add_determination(
            db,
            material_record_id=material.id,
            source="analyst",
            species_code=species,
            verdict="absent",
            confidence=round(0.78 + 0.03 * idx, 2),
            analyst="周冕",
            notes="逐帧判读，无可确认目标特征",
            actor="seed",
        )
        if idx in presents:
            add_determination(
                db,
                material_record_id=material.id,
                source="analyst",
                species_code="AILUROPODA",
                verdict="present",
                confidence=round(0.8 + 0.02 * idx, 2),
                analyst="周冕",
                notes="夜间红外影像确认大熊猫个体经过画面",
                actor="seed",
            )


def seed_archive(db, zone_map, station_map) -> None:
    for code, name, zone_code, lat, lon, half, buffer_m, elev, habitat, scenario_2026 in STATIONS:
        station = station_map[code]
        first_year = FIRST_YEAR[code]
        band = "LOW" if elev[1] <= 1900 else ("MID" if elev[1] <= 2400 else ("HIGH" if elev[1] <= 3000 else "ALPINE"))
        metadata_payload = {
            "station_code": code,
            "zone_code": zone_code,
            "elevation_band": band,
            "habitat": habitat,
            "buffer_width_m": buffer_m,
            "access": "徒步 3.2km",
        }
        version = db.execute(
            select(StationVersion)
            .where(StationVersion.station_id == station.id)
            .order_by(StationVersion.version_number)
        ).scalars().first()
        if version is not None:
            metadata_payload["station_version"] = version.version_number
        ingest_record(
            db,
            {
                "record_type": "station_metadata",
                "external_id": f"META-{code}-V1",
                "station_id": station.id,
                "event_time": datetime(first_year, 3, 28, 16, 0, tzinfo=timezone.utc).isoformat(),
                "received_time": datetime(first_year, 3, 28, 16, 5, tzinfo=timezone.utc).isoformat(),
                "source_device": "reserve-gis",
                "device_type": "metadata",
                "payload": metadata_payload,
            },
            "seed",
        )
        if scenario_2026 in {"migration", "migration_night"}:
            second_payload = dict(metadata_payload)
            second_payload["station_version"] = 2
            second_payload["note"] = "迁移后站点边界更新，事件时间决定适用版本"
            ingest_record(
                db,
                {
                    "record_type": "station_metadata",
                    "external_id": f"META-{code}-V2",
                    "station_id": station.id,
                    "event_time": datetime(2026, 4, 12, 3, 0, tzinfo=timezone.utc).isoformat(),
                    "received_time": datetime(2026, 4, 12, 3, 6, tzinfo=timezone.utc).isoformat(),
                    "source_device": "reserve-gis",
                    "device_type": "metadata",
                    "payload": second_payload,
                },
                "seed",
            )
        if scenario_2026 == "clean":
            _record(
                db,
                station=station,
                record_type="time_calibration",
                external_id=f"CAL-{code}-01",
                event_time=utc_iso("2026-04-09", 9),
                payload={
                    "target_device": f"CAM-{code}",
                    "offset_seconds": 300,
                    "verified": True,
                    "valid_from": utc_iso("2026-04-09", 9),
                    "valid_to": utc_iso("2026-05-01", 9),
                    "source": "保护区 NTP 参考站校时单 CT-2026-041",
                    "method": "现场对时，回算 300s 偏移",
                },
                device="reserve-timesync",
            )
        if scenario_2026 == "migration_night":
            _record(
                db,
                station=station,
                record_type="time_calibration",
                external_id=f"CAL-{code}-01",
                event_time=utc_iso("2026-04-09", 9),
                payload={
                    "target_device": f"CAM-{code}",
                    "offset_seconds": 300,
                    "verified": True,
                    "valid_from": utc_iso("2026-04-09", 9),
                    "valid_to": utc_iso("2026-05-01", 9),
                    "source": "保护区 NTP 参考站校时单 CT-2026-042",
                    "method": "现场对时，回算 300s 偏移（仅主机，备用机未校）",
                },
                device="reserve-timesync",
            )
        for year in (2024, 2025, 2026):
            if year < first_year:
                continue
            scenario = SCENARIOS[code][year]
            for day in SEASONS[year]["dates"]:
                frames = emit_device_day(db, station, scenario, day)
                presents = PRESENTS.get((code, year), {}).get(day, ())
                emit_determinations(db, station, scenario, day, frames, presents)
        db.flush()


def seed_runs(db, rulebooks: dict[int, RulebookVersion], model: ProbabilityModel):
    runs = {}
    for year, rulebook in rulebooks.items():
        station_ids = [
            station.id
            for station in db.execute(select(Station)).scalars()
            if FIRST_YEAR[station.code] <= year
        ]
        runs[year] = build_run(
            db,
            rulebook_version=rulebook,
            model=model,
            station_ids=station_ids,
            label=f"{year} 春季调查覆盖组装",
            actor="yq.li",
        )
        db.flush()
    return runs


def _unit(db, run, station_code: str, day: str) -> SurveyUnit:
    station = db.execute(select(Station).where(Station.code == station_code)).scalar_one()
    return db.execute(
        select(SurveyUnit)
        .where(SurveyUnit.run_id == run.id)
        .where(SurveyUnit.station_id == station.id)
        .where(SurveyUnit.unit_date == date.fromisoformat(day))
    ).scalar_one()


def seed_references_and_revision(db, run: SurveyRun) -> None:
    create_trend_reference(
        db,
        unit_id=_unit(db, run, "QSL-01", "2026-04-10").id,
        purpose="absence",
        actor="yq.li",
        note="青松岭主站 D1 规则证书完整，用于正式未发现结论引用。",
    )
    for day in SURVEY_DATES:
        create_trend_reference(
            db,
            unit_id=_unit(db, run, "YXG-03", day).id,
            purpose="trend",
            actor="yq.li",
            note="路线覆盖接近门槛，规则受限但概率估计支持，作为趋势参考样本。",
        )
    create_trend_reference(
        db,
        unit_id=_unit(db, run, "BHP-02", "2026-04-12").id,
        purpose="trend",
        actor="yq.li",
        note="迁移后新边界单元，设备与空间均满足。",
    )
    late_unit = _unit(db, run, "YXG-02", "2026-04-11")
    create_trend_reference(
        db,
        unit_id=late_unit.id,
        purpose="trend",
        actor="yq.li",
        note="云溪沟东站 D2 早期趋势引用，待迟到判读复核。",
    )

    # Late determination revision: absent → present, which invalidates the
    # earlier certificate's absence use and suspends the trend reference.
    material = db.execute(
        select(ArchiveRecord).where(ArchiveRecord.external_id == "IMG-YXG-02-20260411-0002")
    ).scalar_one()
    det = db.execute(
        select(Determination)
        .where(Determination.material_record_id == material.id)
        .order_by(Determination.id)
    ).scalars().first()
    revise_determination(
        db,
        det.id,
        verdict="present",
        confidence=0.86,
        reason="迟到判读复核：重看原片后确认目标物种出现在画面右侧，初判遗漏。",
        actor="m.cao",
    )


def seed_plans(db, station_map) -> list[AnnualSurveyPlan]:
    """Annual survey plans: the season's points (with roles) and target species."""
    roles = {
        2024: [("QSL-01", "core"), ("QSL-03", "core"), ("YXG-01", "core"), ("YXG-03", "core")],
        2025: [
            ("QSL-01", "core"), ("QSL-03", "core"), ("YXG-01", "core"), ("YXG-03", "core"),
            ("QSL-04", "expansion"), ("YXG-02", "expansion"), ("YXG-04", "expansion"),
        ],
        2026: [
            ("QSL-01", "core"), ("QSL-03", "core"), ("YXG-01", "core"), ("YXG-03", "core"),
            ("QSL-04", "expansion"), ("YXG-02", "expansion"), ("YXG-04", "expansion"),
            ("QSL-02", "expansion"), ("BHP-01", "expansion"), ("BHP-02", "expansion"),
            ("BHP-03", "exploration"),
        ],
    }
    notes = {
        ("YXG-04", 2026): "滑坡迁址点：季中迁移，前后点段分层归属",
        ("BHP-02", 2026): "滑坡迁址点：季中迁移至低海拔台地",
        ("BHP-03", 2026): "新增高海拔探索点：仅发布独立观测",
        ("YXG-01", 2024): "连续固定点（空间待核年份不进入趋势）",
    }
    plans = []
    for year, points in roles.items():
        plan = AnnualSurveyPlan(
            plan_code=f"PLAN-{year}-SPRING",
            year=year,
            season_code=SEASONS[year]["code"],
            label=f"{year} 春季年度调查计划",
            target_species=PLAN_SPECIES,
            status="active",
            note=(
                f"{year} 年当季点位 {len(points)} 个；目标物种含可调查时段定义，"
                "努力量按物种时段计算。"
            ),
            created_by="yq.li",
        )
        db.add(plan)
        db.flush()
        for code, role in points:
            db.add(
                AnnualSurveyPlanPoint(
                    plan_id=plan.id,
                    station_id=station_map[code].id,
                    role=role,
                    note=notes.get((code, year), ""),
                )
            )
        plans.append(plan)
    db.flush()
    return plans


def seed_trend_analysis(db, plans: list[AnnualSurveyPlan]) -> None:
    create_analysis(
        db,
        species_code="AILUROPODA",
        plan_ids=[p.id for p in plans],
        label="大熊猫春季观测率多年可比性分析（2024–2026）",
        actor="yq.li",
    )


def main() -> None:
    init_db()
    db = SessionLocal()
    try:
        existing = db.execute(select(SurveyRun)).scalars().first()
        if existing:
            print("seed: data already present, skipping")
            return
        seed_users(db)
        zone_map, station_map = seed_catalog(db)
        rulebooks = seed_rulebooks(db)
        model = seed_model(db)
        seed_archive(db, zone_map, station_map)
        runs = seed_runs(db, rulebooks, model)
        seed_references_and_revision(db, runs[2026])
        plans = seed_plans(db, station_map)
        seed_trend_analysis(db, plans)
        db.commit()
        total_units = sum(len(run.units) for run in runs.values())
        print(f"seed: runs {[run.run_code for run in runs.values()]} with {total_units} survey units")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
