export type Status = 'valid' | 'restricted' | 'invalid' | 'pending' | 'under_review'
export type GateKey = 'device' | 'time' | 'space' | 'reading'

export interface User {
  id: number
  username: string
  display_name: string
  role: 'researcher' | 'auditor' | 'viewer'
}

export interface Gate {
  id: number
  gate: GateKey
  requirement_code: string
  status: 'pass' | 'restricted' | 'fail' | 'pending'
  measured: Record<string, any>
  threshold: Record<string, any>
  explanation: string
  rule_ref: string
  evidence: number[]
}

export interface Certificate {
  id: number
  unit_id: number
  run_id: number
  certificate_no: string
  version: number
  status: Status
  status_label: string
  absence_eligible: boolean
  trend_eligible: boolean
  review_status: 'normal' | 'under_review'
  review_status_label: string
  review_reason: string
  summary: string
  gate_snapshot: Array<Record<string, any>>
  conclusions: {
    absence_analysis?: {
      supported: boolean
      species_note: string
      confirmed_present: number
      confirmed_absent_readings: number
      pending_materials: number
      open_conflicts: number
      never_implies_absence: string[]
    }
    trend?: Record<string, any>
  }
  issued_at: string
  superseded_by_id: number | null
}

export interface EstimateVariant {
  key: string
  label: string
  probability: number
  low: number
  high: number
  passes: boolean
}

export interface ProbabilityEstimate {
  id: number
  unit_id: number
  model_id: number
  model_code: string
  model_name: string
  model_version: string
  model_status: string
  threshold: number
  probability: number
  interval_low: number
  interval_high: number
  threshold_pass: boolean
  conclusion: 'supports_partial' | 'below_threshold'
  variants: EstimateVariant[]
  assumptions: string[]
}

export interface Unit {
  id: number
  run_id: number
  station_id: number
  station_code: string
  station_name: string
  zone_id: number
  unit_date: string
  station_version_id: number
  rulebook_version_id: number
  model_version_id: number | null
  coverage_summary: Record<string, any>
  feature_vector: Record<string, any>
  gate_status: Record<GateKey, string>
  data_issues: Array<{ gate: string; gate_label: string; status: string; explanation: string }>
  assembled_at: string
  certificate: Certificate | null
  probability: ProbabilityEstimate | null
}

export interface TrendReference {
  id: number
  reference_code: string
  purpose: 'absence' | 'trend'
  purpose_label: string
  unit_id: number
  certificate_id: number | null
  status: 'active' | 'suspended' | 'revoked'
  snapshot: Record<string, any>
  created_by: string
  created_at: string
  suspended_reason: string
  suspended_at: string | null
  note: string
  station_code?: string
  station_name?: string
  unit_date?: string
}

export interface Determination {
  id: number
  material_record_id: number
  source: string
  species_code: string
  verdict: 'present' | 'absent' | 'uncertain'
  confidence: number
  analyst: string
  revision: number
  status: 'active' | 'superseded'
  notes: string
}

export interface EvidenceMaterial {
  id: number
  record_type: string
  record_type_label: string
  external_id: string
  event_time: string
  received_time: string
  source_device: string
  latitude: number | null
  longitude: number | null
  coord_precision_m: number | null
  payload: Record<string, any>
  payload_hash: string
  revision: number
  is_pending: boolean
  determinations: Determination[]
  conflicts: Array<{ id: number; sources: Array<Record<string, any>>; status: string }>
}

export interface UnitDetail extends Unit {
  station: StationDetail
  station_version: {
    id: number
    version_number: number
    buffer_width_m: number
    effective_from: string
    effective_to: string | null
    change_reason: string
    boundary: { type: string; coordinates: number[][][] }
  }
  rulebook: RulebookVersion
  gates: Gate[]
  certificate_history: Certificate[]
  conflicts: Array<{
    id: number
    species_code: string
    sources: Array<Record<string, any>>
    detail: string
    status: string
    resolution: string
    material_record_id: number
    detected_at: string
  }>
  trend_references: TrendReference[]
  evidence: {
    materials: EvidenceMaterial[]
    record_count: number
    determination_count: number
  }
  audit: AuditEntry[]
}

export interface Station {
  id: number
  code: string
  name: string
  zone_id: number
  zone: { code: string; name: string } | null
  latitude: number
  longitude: number
  elevation_min_m: number
  elevation_max_m: number
  status: string
  version_count: number
}

export interface StationDetail extends Station {
  versions: Array<{
    id: number
    version_number: number
    boundary: { type: string; coordinates: number[][][] }
    buffer_width_m: number
    centroid: { lat: number; lon: number }
    effective_from: string
    effective_to: string | null
    change_reason: string
  }>
}

export interface RulebookVersion {
  id: number
  rulebook_code: string
  rulebook_name: string
  version_number: number
  label: string
  season_code: string
  season_start: string
  season_end: string
  status: string
  target_species: Array<{ code: string; name: string; min_detections: number }>
  requirements: Record<string, any>
  route_segments: Array<Record<string, any>>
  elevation_bands: Array<Record<string, any>>
  notes: string
}

export interface ProbabilityModel {
  id: number
  code: string
  name: string
  version: string
  status: string
  threshold: number
  calibration_sets: Array<{ label: string; pivot_delta: number; n: number }>
  parameters: Record<string, any>
  threshold_review: Record<string, any>
  notes: string
  estimate_count?: number
}

export interface Run {
  id: number
  run_code: string
  label: string
  season_code: string
  season_start: string
  season_end: string
  status: string
  rulebook_version_id: number
  model_version_id: number | null
  created_by: string
  created_at: string
  unit_count: number
  status_counts: Record<string, number>
  open_conflicts: number
  trend_references: number
}

export interface ComparisonRow {
  unit_id: number
  station_code: string
  station_name: string
  date: string
  rule_status: Status
  absence_eligible: boolean
  probability: number | null
  interval: [number, number] | null
  threshold: number | null
  threshold_pass: boolean | null
  divergence: 'both_support' | 'probability_supports_rule_blocks' | 'rule_supports_probability_below'
}

export interface Overview {
  run: Run
  rulebook: RulebookVersion
  model: {
    id: number
    code: string
    version: string
    threshold: number
    status: string
    calibration_sets: Array<Record<string, any>>
  } | null
  unit_count: number
  station_count: number
  date_count: number
  dates: string[]
  status_counts: Record<string, number>
  gate_counts: Record<GateKey, Record<string, number>>
  stations: Array<Station & { units: Array<Record<string, any>> }>
  comparison_rows: ComparisonRow[]
  open_conflicts: number
  active_trend_references: number
  recent_activity: AuditEntry[]
}

export interface Conflict {
  id: number
  unit_id: number
  run_id: number
  material_record_id: number
  material_external_id: string | null
  station_code: string | null
  station_name: string | null
  unit_date: string | null
  species_code: string
  sources: Array<{
    source: string
    analyst: string
    verdict: string
    confidence: number
    determination_id: number
  }>
  detail: string
  status: 'open' | 'resolved'
  resolution: string
  detected_at: string
  resolved_at: string | null
}

export interface AuditEntry {
  id: number
  entity_type: string
  entity_id: number
  action: string
  actor: string
  detail: Record<string, any>
  created_at: string
}

export interface ArchiveRecord {
  id: number
  record_type: string
  record_type_label: string
  external_id: string
  station_id: number
  station_code: string | null
  event_time: string
  received_time: string
  source_device: string
  device_type: string
  latitude: number | null
  longitude: number | null
  coord_precision_m: number | null
  payload: Record<string, any>
  payload_hash: string
  revision: number
  record_status: string
  revisions?: Array<{
    id: number
    revision_number: number
    payload: Record<string, any>
    payload_hash: string
    received_time: string
    changed_by: string
    change_reason: string
    created_at: string
  }>
  determinations?: Determination[]
  used_by_units?: number[]
}

// ---------- 年度趋势可比性分析 ----------
export interface AnnualPlanPoint {
  id: number
  station_id: number
  station_code: string
  station_name: string
  role: 'core' | 'expansion' | 'exploration'
  role_label: string
  note: string
}

export interface AnnualPlan {
  id: number
  plan_code: string
  year: number
  season_code: string
  label: string
  target_species: Array<{
    code: string
    name: string
    activity?: string
    daily_windows?: string[][]
    min_detections?: number
  }>
  status: string
  note: string
  points: AnnualPlanPoint[]
  created_by: string
  created_at: string
}

export interface TrendStaleReason {
  reason: string
  factor: 'coverage' | 'effort' | 'interpretation'
  affected_strata: string[]
  affected_years: number[]
  unit_ids: number[]
  actor: string
  at: string
}

export interface TrendAnalysis {
  id: number
  analysis_code: string
  label: string
  species_code: string
  species_name: string
  method: string
  plan_ids: number[]
  years: number[]
  status: 'completed' | 'stale'
  status_label: string
  stale_reasons: TrendStaleReason[]
  current_brief_id: number | null
  current_brief_version: number | null
  trend_direction: string | null
  trend_slope_per_year: number | null
  created_by: string
  created_at: string
}

export interface TrendYearly {
  year: number
  effort_days: number
  observations: number
  raw_rate: number | null
  standardized_rate: number | null
  se: number
  interval: [number, number] | null
  included_units: number
}

export interface TrendStratum {
  stratum_key: string
  habitat: string
  elevation_band: string
  common: boolean
  weight: number
  coverage_flag: 'adequate' | 'insufficient_effort'
  years_present: number[]
  per_year: Record<string, { effort_days: number; observations: number; rate: number | null } | null>
}

export interface TrendDecomposition {
  note: string
  per_year: Array<{
    year: number
    before: number
    after: number
    delta_total: number
    delta_coverage: number
    delta_effort: number
    delta_interpretation: number
  }>
  slope: {
    before: number
    after: number
    delta_coverage: number
    delta_effort: number
    delta_interpretation: number
  }
  changed_units: Array<{
    unit_id: number
    station_code: string
    year: number
    unit_date: string
    factors: string[]
    before: Record<string, any> | null
    after: Record<string, any> | null
  }>
}

export interface TrendResults {
  method: string
  method_label: string
  species: { code: string; name: string; activity: string; daily_windows: string[][] }
  years: number[]
  yearly: TrendYearly[]
  trend: {
    slope_per_year: number | null
    slope_interval: [number, number] | null
    direction: string
    interpretation: string
  }
  strata: TrendStratum[]
  insufficient_ranges: Array<{
    stratum_key: string
    habitat: string
    elevation_band: string
    years_present: number[]
    missing_years: number[]
    reason: string
  }>
  fixed_point_series: {
    note: string
    points: string[]
    yearly: Array<{ year: number; effort_days: number; observations: number; rate: number | null; units: number }>
    slope_per_year: number | null
  }
  independent_observations: Array<{
    year: number
    station_code: string
    station_name: string
    effort_days: number
    observations: number
    units: number
    note: string
  }>
  excluded_unit_count: number
  warnings: string[]
  disclaimers: string[]
  decomposition?: TrendDecomposition
  recomputed_for?: TrendStaleReason[]
}

export interface TrendUnitInput {
  unit_id: number
  year: number
  station_id: number
  station_code: string
  station_name: string
  unit_date: string
  station_version_id: number | null
  version_number: number | null
  segment_key: string
  point_role: string
  stratum_key: string
  habitat: string
  elevation_band: string
  included: boolean
  reasons: string[]
  effort_days: number
  observation_count: number
  weight: number
  certificate_id: number | null
  certificate_no: string
  determination_ids: number[]
  material_ids: number[]
  excluded_materials: Array<{ record_id: number; external_id: string; reason: string }>
}

export interface TrendBrief {
  id: number
  analysis_id: number
  version: number
  status: 'current' | 'superseded'
  input_hash: string
  note: string
  created_by: string
  created_at: string
  inputs?: { plans: Array<Record<string, any>>; units: TrendUnitInput[]; generated_at: string }
  results?: TrendResults
}

export interface TrendAnalysisDetail extends TrendAnalysis {
  brief: TrendBrief | null
}

export interface TrendUnitRow {
  id: number
  analysis_id: number
  unit_id: number
  year: number
  unit_date: string | null
  station_id: number
  station_code: string
  station_version_id: number | null
  segment_key: string
  point_role: string
  point_role_label: string
  stratum_key: string
  habitat: string
  elevation_band: string
  included: boolean
  reasons: string[]
  effort_days: number
  observation_count: number
  weight: number
  certificate_id: number | null
  certificate_no: string
  determination_ids: number[]
  material_ids: number[]
  excluded_materials: Array<{ record_id: number; external_id: string; reason: string }>
}

