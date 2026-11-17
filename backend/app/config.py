import os
from datetime import timedelta, timezone

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://ccdev:ccdev@127.0.0.1:5432/survey_integrity",
)
SECRET_KEY = os.getenv("SECRET_KEY", "dev-only-survey-integrity-secret")
TOKEN_TTL_HOURS = int(os.getenv("TOKEN_TTL_HOURS", "12"))
API_PREFIX = "/api"

# The reserve operates on China Standard Time (UTC+8, no DST).
RESERVE_TZ = timezone(timedelta(hours=8))
RESERVE_TZ_LABEL = "Asia/Shanghai (UTC+8)"

# Certificate / review vocabulary (kept in one place so UI and API agree).
STATUS_VALID = "valid"           # 有效调查
STATUS_RESTRICTED = "restricted"  # 受限调查
STATUS_INVALID = "invalid"       # 未有效调查
STATUS_PENDING = "pending"       # 待核

STATUS_LABELS = {
    STATUS_VALID: "有效调查",
    STATUS_RESTRICTED: "受限调查",
    STATUS_INVALID: "未有效调查",
    STATUS_PENDING: "待核",
    "under_review": "复审中",
}

GATE_LABELS = {
    "device": "设备可用性",
    "time": "时间可信度",
    "space": "空间覆盖",
    "reading": "素材判读",
}

RECORD_TYPE_LABELS = {
    "camera_event": "相机事件",
    "patrol_track": "巡护轨迹",
    "device_heartbeat": "设备心跳",
    "downtime_log": "停机日志",
    "species_determination": "物种判读",
    "station_metadata": "站点元数据",
    "time_calibration": "时间校准",
}

# ---- 年度趋势可比性分析 ----
POINT_ROLE_LABELS = {
    "core": "连续固定点",
    "expansion": "样线扩充点",
    "exploration": "新增探索点",
}

TREND_STATUS_LABELS = {
    "completed": "已完成",
    "stale": "待重算",
}

# 趋势变化分解的三类因子：覆盖（点位/分层变化）、努力量（有效调查时段）、判读（观测次数）。
TREND_FACTOR_LABELS = {
    "coverage": "覆盖",
    "effort": "努力量",
    "interpretation": "判读",
}

# 分层覆盖不足阈值：层内有效努力量低于该值时，只给出大不确定范围，不进入标准化。
TREND_MIN_STRATUM_EFFORT_DAYS = 2.0
