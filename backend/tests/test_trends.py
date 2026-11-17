"""Acceptance tests for the annual monitoring trend comparability analysis.

Covers the required acceptance inputs (fixed points, mid-season migration
points, new high-elevation exploration points, partial-period downtime) and the
revision flow (late maintenance log, migration-date correction, determination
revocation) with stale propagation, recomputation, decomposition and brief
reproduction.
"""
from __future__ import annotations

import pytest


@pytest.fixture(scope="module", autouse=True)
def isolate_trend_runs(seeded):
    """Pin the season to its official seeded run and clear cross-file stale marks.

    Other test files assemble ad-hoc runs and revise determinations; those
    actions legitimately mark the seeded analysis stale. The trend acceptance
    tests need a deterministic baseline, so non-seeded runs are superseded and
    the seeded analysis is recomputed once before this module's tests.
    """
    from sqlalchemy import select

    from app.db import SessionLocal
    from app.models import SurveyRun, TrendAnalysis
    from app.trends import run_analysis

    session = SessionLocal()
    try:
        runs = session.execute(
            select(SurveyRun).where(SurveyRun.status == "active")
        ).scalars().all()
        for run in runs:
            if not run.run_code.endswith("-01"):
                run.status = "superseded"
        analysis = session.execute(select(TrendAnalysis)).scalar_one()
        run_analysis(session, analysis, "pytest", note="测试隔离：固定到种子运行并重算")
        session.commit()
    finally:
        session.close()
    yield


def _analysis(client, auth):
    analyses = client.get("/api/trend-analyses", headers=auth).json()
    assert len(analyses) == 1
    return analyses[0]


def _detail(client, auth, analysis_id):
    return client.get(f"/api/trend-analyses/{analysis_id}", headers=auth).json()


def _trend_units(client, auth, analysis_id):
    return client.get(f"/api/trend-analyses/{analysis_id}/units", headers=auth).json()


def _row(rows, station_code, unit_date):
    return next(
        r for r in rows if r["station_code"] == station_code and r["unit_date"] == unit_date
    )


def test_annual_plans_reference_points_and_species(client, auth):
    plans = client.get("/api/annual-plans", headers=auth).json()
    assert [p["year"] for p in plans] == [2024, 2025, 2026]
    counts = {p["year"]: len(p["points"]) for p in plans}
    assert counts == {2024: 4, 2025: 7, 2026: 11}, "设备总数应连续三年增长"
    for plan in plans:
        species = {s["code"] for s in plan["target_species"]}
        assert "AILUROPODA" in species
        nocturnal = next(s for s in plan["target_species"] if s["code"] == "AILUROPODA")
        assert nocturnal["daily_windows"], "目标物种必须带可调查时段"
    plan2026 = next(p for p in plans if p["year"] == 2026)
    roles = {p["station_code"]: p["role"] for p in plan2026["points"]}
    assert roles["QSL-01"] == "core"
    assert roles["BHP-03"] == "exploration"


def test_trend_baseline_raw_vs_standardized(client, auth):
    analysis = _analysis(client, auth)
    assert analysis["status"] == "completed"
    detail = _detail(client, auth, analysis["id"])
    brief = detail["brief"]
    assert brief["version"] >= 1
    results = brief["results"]

    assert results["years"] == [2024, 2025, 2026]
    yearly = {y["year"]: y for y in results["yearly"]}
    efforts = [yearly[y]["effort_days"] for y in (2024, 2025, 2026)]
    assert efforts[0] < efforts[1] < efforts[2], "设备与样线扩充应体现为努力量增长"
    for year in (2024, 2025, 2026):
        assert yearly[year]["raw_rate"] is not None
        assert yearly[year]["standardized_rate"] is not None
    assert any(
        abs(yearly[y]["raw_rate"] - yearly[y]["standardized_rate"]) > 1e-6
        for y in (2024, 2025, 2026)
    ), "原始观测率与标准化结果必须同时给出且不完全相同"

    common = {s["stratum_key"] for s in results["strata"] if s["common"]}
    assert common == {
        "针阔混交林|MID|SPRING",
        "沟谷阔叶林|LOW|SPRING",
        "落叶阔叶林|LOW|SPRING",
    }
    insufficient = {r["stratum_key"]: r for r in results["insufficient_ranges"]}
    assert "高寒针叶林|HIGH|SPRING" in insufficient
    assert insufficient["高寒针叶林|HIGH|SPRING"]["missing_years"] == [2024, 2025]
    assert "不重叠" in insufficient["高寒针叶林|HIGH|SPRING"]["reason"]
    assert "外推" in insufficient["高寒针叶林|HIGH|SPRING"]["reason"]

    fixed = results["fixed_point_series"]
    assert fixed["points"] == ["QSL-01", "QSL-03", "YXG-03"]
    assert "独立参照" in fixed["note"] and "不得" in fixed["note"]
    fixed_rates = {y["year"]: y["rate"] for y in fixed["yearly"]}
    std_rates = {y["year"]: y["standardized_rate"] for y in results["yearly"]}
    assert any(
        abs(fixed_rates[y] - std_rates[y]) > 1e-6 for y in fixed_rates
    ), "固定点位序列与分层标准化是两条独立序列"

    independent = results["independent_observations"]
    assert len(independent) == 1
    assert independent[0]["station_code"] == "BHP-03"
    assert independent[0]["observations"] == 2
    assert independent[0]["effort_days"] < 3.0, "夜间停机必须扣减夜行物种努力量"
    assert "独立观测" in independent[0]["note"]

    assert any("不能解释为已确认的种群增长" in d for d in results["disclaimers"])
    assert any("同一设备编号" in d for d in results["disclaimers"])


def test_species_window_effort_and_migration_split(client, auth):
    analysis = _analysis(client, auth)
    rows = _trend_units(client, auth, analysis["id"])

    # 季中迁移点 YXG-04：2026 年被拆成迁前/迁后两个点段，分属不同层。
    yxg4_2026 = [r for r in rows if r["station_code"] == "YXG-04" and r["year"] == 2026]
    segments = {r["segment_key"] for r in yxg4_2026}
    assert segments == {"YXG-04:v1", "YXG-04:v2"}
    by_segment = {r["segment_key"]: r for r in yxg4_2026}
    assert by_segment["YXG-04:v1"]["stratum_key"] == "沟谷阔叶林|LOW|SPRING"
    assert by_segment["YXG-04:v2"]["stratum_key"] == "针阔混交林|MID|SPRING"

    # 部分时段停机：夜间停机只扣减夜行物种的夜间时段，不是完整白天有效日。
    day1 = _row(rows, "YXG-04", "2026-04-10")
    assert 0.7 < day1["effort_days"] < 0.85, "夜间 2.5h 停机应使夜行物种努力量约为 0.79"
    yxg4_2025 = [r for r in rows if r["station_code"] == "YXG-04" and r["year"] == 2025]
    assert all(r["effort_days"] == 1.0 for r in yxg4_2025)

    # 备用机帧时钟误差跨过迁点边界：排除出跨年比较，且不计入任何点段。
    boundary_unit = _row(rows, "YXG-04", "2026-04-11")
    assert len(boundary_unit["excluded_materials"]) == 1
    assert "迁点边界" in boundary_unit["excluded_materials"][0]["reason"]
    excluded_id = boundary_unit["excluded_materials"][0]["record_id"]
    for row in rows:
        assert excluded_id not in (row["material_ids"] or [])

    # 探索点不进入趋势，只发布独立观测。
    bhp3 = [r for r in rows if r["station_code"] == "BHP-03"]
    assert bhp3 and all(not r["included"] for r in bhp3)
    assert all("独立观测" in r["reasons"][0] for r in bhp3)


def test_sample_attribution_has_no_duplicates(client, auth):
    analysis = _analysis(client, auth)
    rows = _trend_units(client, auth, analysis["id"])
    seen: dict[int, str] = {}
    for row in rows:
        if not row["included"]:
            continue
        for material_id in row["material_ids"] or []:
            assert material_id not in seen, (
                f"素材 {material_id} 同时归属 {seen.get(material_id)} 与 "
                f"{row['station_code']} {row['unit_date']}，样本归属必须互斥"
            )
            seen[material_id] = f"{row['station_code']}:{row['unit_date']}"


def test_revision_flow_recomputes_denominators_and_decomposes(client, auth):
    analysis = _analysis(client, auth)
    analysis_id = analysis["id"]
    baseline = _detail(client, auth, analysis_id)["brief"]
    baseline_version = baseline["version"]
    base_units = {u["unit_id"]: u for u in baseline["inputs"]["units"]}

    def base_row(station, day):
        return next(
            u for u in baseline["inputs"]["units"]
            if u["station_code"] == station and u["unit_date"] == day
        )

    base_effort_qsl01_d1 = base_row("QSL-01", "2026-04-10")["effort_days"]
    base_obs_qsl01_d2 = base_row("QSL-01", "2026-04-11")["observation_count"]
    base_cert_qsl01_d2 = base_row("QSL-01", "2026-04-11")["certificate_no"]
    base_stratum_bhp02_d2 = base_row("BHP-02", "2026-04-11")["stratum_key"]
    assert base_stratum_bhp02_d2 == "高寒针叶林|HIGH|SPRING"

    # ---- 1) 补录维护：迟到停机日志改变有效努力量 --------------------------
    stations = {s["code"]: s["id"] for s in client.get("/api/stations", headers=auth).json()}
    maintenance = client.post(
        "/api/records",
        headers=auth,
        json={
            "record_type": "downtime_log",
            "external_id": "DT-QSL-01-20260410-N1",
            "station_id": stations["QSL-01"],
            "event_time": "2026-04-10T13:30:00+00:00",
            "received_time": "2026-05-25T02:10:00+00:00",
            "source_device": "CAM-QSL-01",
            "payload": {
                "start": "2026-04-10T13:30:00+00:00",
                "end": "2026-04-10T15:00:00+00:00",
                "reason": "迟到补录：夜间红外补光灯故障检修 21:30-23:00",
                "operator": "巡护一组",
                "camera_id": "CAM-QSL-01",
            },
        },
    )
    assert maintenance.status_code == 200, maintenance.text
    assert maintenance.json()["effort_affected_units"], "迟到维护日志必须回传到调查单元"
    stale = _analysis(client, auth)
    assert stale["status"] == "stale", "修订期间新趋势保持待重算"
    effort_reason = next(r for r in stale["stale_reasons"] if r["factor"] == "effort")
    assert "针阔混交林|MID|SPRING" in effort_reason["affected_strata"]
    assert effort_reason["affected_years"] == [2026]

    # ---- 2) 纠正迁点日期：BHP-02 迁移生效日 4/12 → 4/11 -------------------
    corrected = client.post(
        f"/api/stations/{stations['BHP-02']}/migration-correction",
        headers=auth,
        json={"corrected_date": "2026-04-11", "reason": "现场复核：设备实际于 4 月 11 日完成迁址"},
    )
    assert corrected.status_code == 200, corrected.text
    assert corrected.json()["affected_unit_ids"]
    stale = _analysis(client, auth)
    coverage_reason = next(r for r in stale["stale_reasons"] if r["factor"] == "coverage")
    assert 2026 in coverage_reason["affected_years"]

    # ---- 3) 撤销一条判读：QSL-01 2026-04-11 的大熊猫出现判读 --------------
    trend_rows = _trend_units(client, auth, analysis_id)
    qsl01_d2 = _row(trend_rows, "QSL-01", "2026-04-11")
    unit_detail = client.get(f"/api/units/{qsl01_d2['unit_id']}", headers=auth).json()
    present_det = next(
        d
        for m in unit_detail["evidence"]["materials"]
        for d in m["determinations"]
        if d["species_code"] == "AILUROPODA" and d["verdict"] == "present" and d["status"] == "active"
    )
    revoked = client.post(
        f"/api/determinations/{present_det['id']}/revoke",
        headers=auth,
        json={"reason": "复核确认该帧为光线伪影，撤销大熊猫出现判读"},
    )
    assert revoked.status_code == 200, revoked.text
    assert qsl01_d2["unit_id"] in revoked.json()["units_under_review"]
    stale = _analysis(client, auth)
    assert any(r["factor"] == "interpretation" for r in stale["stale_reasons"])

    # 复审后重新签发证书，单元恢复趋势用途（观测次数已减少）。
    reissued = client.post(
        f"/api/units/{qsl01_d2['unit_id']}/certificates/reissue", headers=auth
    )
    assert reissued.status_code == 200, reissued.text
    assert reissued.json()["trend_eligible"] is True

    # ---- 4) 重算：分子分母一起按当前证据重建 ------------------------------
    recomputed = client.post(f"/api/trend-analyses/{analysis_id}/recompute", headers=auth)
    assert recomputed.status_code == 200, recomputed.text
    brief2 = recomputed.json()["brief"]
    assert brief2["version"] == baseline_version + 1
    assert recomputed.json()["analysis"]["status"] == "completed"

    new_units = {u["unit_id"]: u for u in brief2["inputs"]["units"]}

    def new_row(station, day):
        return next(
            u for u in brief2["inputs"]["units"]
            if u["station_code"] == station and u["unit_date"] == day
        )

    # 分母随证据变化：维护日志使 QSL-01 D1 有效努力量下降。
    new_effort_qsl01_d1 = new_row("QSL-01", "2026-04-10")["effort_days"]
    assert new_effort_qsl01_d1 < base_effort_qsl01_d1
    # 撤销判读使观测次数减少（分子），且单元未被静默剔除。
    assert new_row("QSL-01", "2026-04-11")["observation_count"] == base_obs_qsl01_d2 - 1
    assert new_row("QSL-01", "2026-04-11")["included"] is True
    # 迁点日期纠正使 BHP-02 D2 从 HIGH 层移到 MID 层。
    assert new_row("BHP-02", "2026-04-11")["stratum_key"] == "针阔混交林|MID|SPRING"
    # 报告引用准确：新简报引用重新签发后的证书，且不再引用被撤销的判读。
    assert new_row("QSL-01", "2026-04-11")["certificate_no"] != base_cert_qsl01_d2
    assert present_det["id"] not in new_row("QSL-01", "2026-04-11")["determination_ids"]

    # ---- 5) 趋势变化分解：覆盖 / 努力量 / 判读 ----------------------------
    decomposition = brief2["results"]["decomposition"]
    per_year = {row["year"]: row for row in decomposition["per_year"]}
    y2026 = per_year[2026]
    assert y2026["delta_effort"] != 0, "维护日志必须体现为努力量因子"
    assert y2026["delta_coverage"] != 0, "迁点纠正必须体现为覆盖因子"
    assert y2026["delta_interpretation"] != 0, "撤销判读必须体现为判读因子"
    assert (
        abs(
            y2026["delta_coverage"]
            + y2026["delta_effort"]
            + y2026["delta_interpretation"]
            - y2026["delta_total"]
        )
        < 1e-3
    )
    changed = {u["unit_id"]: u for u in decomposition["changed_units"]}
    assert "effort" in changed[base_row("QSL-01", "2026-04-10")["unit_id"]]["factors"]
    assert "interpretation" in changed[base_row("QSL-01", "2026-04-11")["unit_id"]]["factors"]
    assert "coverage" in changed[base_row("BHP-02", "2026-04-11")["unit_id"]]["factors"]
    assert len(brief2["results"]["recomputed_for"]) == 3

    # ---- 6) 历史简报仍可复现旧输入 ----------------------------------------
    briefs = client.get(f"/api/trend-analyses/{analysis_id}/briefs", headers=auth).json()
    assert briefs[0]["version"] == baseline_version + 1
    assert baseline_version in [b["version"] for b in briefs]
    old_brief = client.get(
        f"/api/trend-analyses/{analysis_id}/briefs/{baseline_version}", headers=auth
    ).json()
    assert old_brief["status"] == "superseded"
    old_qsl01_d1 = next(
        u for u in old_brief["inputs"]["units"]
        if u["station_code"] == "QSL-01" and u["unit_date"] == "2026-04-10"
    )
    assert old_qsl01_d1["effort_days"] == base_effort_qsl01_d1
    old_qsl01_d2 = next(
        u for u in old_brief["inputs"]["units"]
        if u["station_code"] == "QSL-01" and u["unit_date"] == "2026-04-11"
    )
    assert old_qsl01_d2["certificate_no"] == base_cert_qsl01_d2
    assert old_qsl01_d2["observation_count"] == base_obs_qsl01_d2
    assert old_brief["input_hash"] == baseline["input_hash"]
    assert old_brief["input_hash"] != brief2["input_hash"]

    # 重算后样本归属依然互斥（迁点纠正不会造成双重归属）。
    rows_after = _trend_units(client, auth, analysis_id)
    seen: set[int] = set()
    for row in rows_after:
        if not row["included"]:
            continue
        for material_id in row["material_ids"] or []:
            assert material_id not in seen
            seen.add(material_id)


def test_observation_rate_is_not_reported_as_population_growth(client, auth):
    analysis = _analysis(client, auth)
    detail = _detail(client, auth, analysis["id"])
    results = detail["brief"]["results"]
    assert "不能解释为已确认的种群增长" in results["trend"]["interpretation"]
    assert any("不等于种群规模" in d or "不能解释为已确认的种群增长" in d for d in results["disclaimers"])
    # 固定点位序列与分层标准化不得拼成一条趋势。
    assert "不得与分层标准化趋势拼接" in results["fixed_point_series"]["note"]
