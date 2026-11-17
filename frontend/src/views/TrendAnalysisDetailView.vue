<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '../api'
import type {
  TrendAnalysisDetail,
  TrendBrief,
  TrendUnitRow,
  TrendYearly,
} from '../types'
import StatusBadge from '../components/StatusBadge.vue'
import { fmtDateTime, fmtPct, TREND_FACTOR_LABEL, POINT_ROLE_LABEL } from '../format'
import { authState } from '../session'
import { useToast } from '../toast'

const route = useRoute()
const router = useRouter()
const { push: notify } = useToast()
const analysisId = Number(route.params.id)

const detail = ref<TrendAnalysisDetail | null>(null)
const units = ref<TrendUnitRow[]>([])
const briefs = ref<TrendBrief[]>([])
const loading = ref(true)
const error = ref('')
const tab = ref<'conclusion' | 'strata' | 'units' | 'briefs'>('conclusion')
const recomputing = ref(false)
const viewingBrief = ref<TrendBrief | null>(null)
const unitFilter = ref<'all' | 'included' | 'excluded'>('all')
const yearFilter = ref<number | ''>('')

const canEdit = computed(() => authState.isWriter.value)

async function load() {
  loading.value = true
  error.value = ''
  try {
    ;[detail.value, units.value, briefs.value] = await Promise.all([
      api.get<TrendAnalysisDetail>(`/trend-analyses/${analysisId}`),
      api.get<TrendUnitRow[]>(`/trend-analyses/${analysisId}/units`),
      api.get<TrendBrief[]>(`/trend-analyses/${analysisId}/briefs`),
    ])
  } catch (err) {
    error.value = err instanceof Error ? err.message : '加载失败'
  } finally {
    loading.value = false
  }
}

onMounted(load)

const results = computed(() => detail.value?.brief?.results ?? null)

const excludedUnits = computed(() => units.value.filter((u) => !u.included))
const includedUnits = computed(() => units.value.filter((u) => u.included))

const filteredUnits = computed(() => {
  let rows = units.value
  if (unitFilter.value === 'included') rows = rows.filter((u) => u.included)
  if (unitFilter.value === 'excluded') rows = rows.filter((u) => !u.included)
  if (yearFilter.value !== '') rows = rows.filter((u) => u.year === yearFilter.value)
  return rows
})

async function recompute() {
  recomputing.value = true
  try {
    await api.post(`/trend-analyses/${analysisId}/recompute`)
    notify('已按当前证据重算，分子分母同步更新')
    viewingBrief.value = null
    await load()
  } catch (err) {
    notify(err instanceof Error ? err.message : '重算失败', 'error')
  } finally {
    recomputing.value = false
  }
}

async function openBrief(version: number) {
  try {
    viewingBrief.value = await api.get<TrendBrief>(
      `/trend-analyses/${analysisId}/briefs/${version}`,
    )
  } catch (err) {
    notify(err instanceof Error ? err.message : '读取简报失败', 'error')
  }
}

function rate(value?: number | null, digits = 3): string {
  if (value === null || value === undefined) return '—'
  return value.toFixed(digits)
}

function signed(value?: number | null, digits = 4): string {
  if (value === null || value === undefined) return '—'
  return `${value > 0 ? '+' : ''}${value.toFixed(digits)}`
}

// ---------------- chart ----------------
const CHART_W = 640
const CHART_H = 200
const PAD = { l: 46, r: 14, t: 14, b: 26 }

const chartYears = computed(() => results.value?.years ?? [])
const chartMax = computed(() => {
  if (!results.value) return 1
  let max = 0.2
  for (const y of results.value.yearly) {
    max = Math.max(max, y.raw_rate ?? 0, y.standardized_rate ?? 0, y.interval?.[1] ?? 0)
  }
  for (const y of results.value.fixed_point_series.yearly) {
    max = Math.max(max, y.rate ?? 0)
  }
  return Math.min(1.2, max * 1.15)
})

function xPos(year: number): number {
  const years = chartYears.value
  const i = years.indexOf(year)
  const span = Math.max(1, years.length - 1)
  return PAD.l + (i / span) * (CHART_W - PAD.l - PAD.r)
}

function yPos(value: number): number {
  return PAD.t + (1 - value / chartMax.value) * (CHART_H - PAD.t - PAD.b)
}

function linePath(values: Array<number | null>, years: number[]): string {
  const parts: string[] = []
  values.forEach((v, i) => {
    if (v === null) return
    parts.push(`${parts.length ? 'L' : 'M'}${xPos(years[i]).toFixed(1)},${yPos(v).toFixed(1)}`)
  })
  return parts.join(' ')
}

const stdLine = computed(() =>
  results.value
    ? linePath(
        results.value.yearly.map((y) => y.standardized_rate),
        results.value.years,
      )
    : '',
)
const rawLine = computed(() =>
  results.value
    ? linePath(
        results.value.yearly.map((y) => y.raw_rate),
        results.value.years,
      )
    : '',
)
const fixedLine = computed(() =>
  results.value
    ? linePath(
        results.value.fixed_point_series.yearly.map((y) => y.rate),
        results.value.years,
      )
    : '',
)
const intervalPolygon = computed(() => {
  if (!results.value) return ''
  const years = results.value.years
  const upper = results.value.yearly.map((y, i) =>
    y.interval ? `${xPos(years[i]).toFixed(1)},${yPos(y.interval[1]).toFixed(1)}` : '',
  )
  const lower = results.value.yearly
    .map((y, i) => (y.interval ? `${xPos(years[i]).toFixed(1)},${yPos(y.interval[0]).toFixed(1)}` : ''))
    .reverse()
  return [...upper, ...lower].filter(Boolean).join(' ')
})

const decomposition = computed(() => results.value?.decomposition ?? null)
const recomputedFor = computed(() => results.value?.recomputed_for ?? [])

function factorBadgeClass(factor: string): string {
  return { coverage: 'pending', effort: 'restricted', interpretation: 'under_review' }[factor] ?? 'neutral'
}
</script>

<template>
  <div>
    <div v-if="loading" class="loading">加载中…</div>
    <div v-else-if="error" class="callout danger">{{ error }}</div>

    <template v-else-if="detail && results">
      <div class="page-head">
        <div>
          <div class="eyebrow">Trend Analysis · {{ detail.analysis_code }}</div>
          <h1>{{ detail.label }}</h1>
          <p class="page-sub">
            {{ detail.species_name }}（{{ detail.species_code }}）· {{ detail.years.join(' / ') }} ·
            {{ results.method_label }}。观测率是活动代理指标，不等于种群规模。
          </p>
        </div>
        <div class="toolbar">
          <StatusBadge
            :status="detail.status === 'completed' ? 'valid' : 'pending'"
            :label="detail.status_label"
          />
          <button
            v-if="canEdit"
            class="btn primary sm"
            :disabled="recomputing || detail.status !== 'stale'"
            :title="detail.status === 'stale' ? '按当前证据重算分子与分母' : '当前结果已是最新'"
            @click="recompute"
          >
            {{ recomputing ? '重算中…' : '按当前证据重算' }}
          </button>
        </div>
      </div>

      <div v-if="detail.status === 'stale'" class="callout warn" style="margin-bottom: 14px">
        <div class="callout-title">待重算：{{ detail.stale_reasons.length }} 项修订待回传</div>
        <div v-for="(reason, i) in detail.stale_reasons" :key="i" class="small" style="margin-top: 4px">
          <span class="badge" :class="factorBadgeClass(reason.factor)">{{ TREND_FACTOR_LABEL[reason.factor] }}</span>
          {{ reason.reason }}
          <span class="tiny muted">
            涉及层：{{ reason.affected_strata.join('、') || '—' }}；年份：{{ reason.affected_years.join('、') }}
          </span>
        </div>
        <div class="tiny" style="margin-top: 6px">
          修订期间新趋势保持待重算；历史简报仍可复现旧输入。重算将同时重建分子（观测次数）与分母（有效努力量），不会只更新其一。
        </div>
      </div>

      <div class="tabs">
        <button class="tab" :class="{ active: tab === 'conclusion' }" @click="tab = 'conclusion'">全区结论</button>
        <button class="tab" :class="{ active: tab === 'strata' }" @click="tab = 'strata'">分层样本与权重</button>
        <button class="tab" :class="{ active: tab === 'units' }" @click="tab = 'units'">
          单元与排除点位（{{ units.length }}）
        </button>
        <button class="tab" :class="{ active: tab === 'briefs' }" @click="tab = 'briefs'">
          简报与修订分解（v{{ detail.brief?.version }}）
        </button>
      </div>

      <!-- ==================== 全区结论 ==================== -->
      <template v-if="tab === 'conclusion'">
        <div class="grid grid-2-1">
          <div class="card">
            <div class="card-head">
              <h2>标准化观测率趋势（{{ results.species.name }}）</h2>
              <span class="chip">80% 区间</span>
            </div>
            <svg :viewBox="`0 0 ${CHART_W} ${CHART_H}`" style="width: 100%; display: block">
              <line
                v-for="tick in 4"
                :key="tick"
                :x1="PAD.l" :x2="CHART_W - PAD.r"
                :y1="yPos((chartMax / 4) * tick)" :y2="yPos((chartMax / 4) * tick)"
                stroke="#e6e3d8" stroke-width="1"
              />
              <polygon :points="intervalPolygon" fill="rgba(31,77,63,0.10)" />
              <path :d="stdLine" fill="none" stroke="var(--pine)" stroke-width="2.4" />
              <path :d="rawLine" fill="none" stroke="var(--amber)" stroke-width="1.6" stroke-dasharray="5 4" />
              <path :d="fixedLine" fill="none" stroke="var(--slate)" stroke-width="1.6" stroke-dasharray="2 3" />
              <g v-for="(y, i) in results.yearly" :key="y.year">
                <circle :cx="xPos(y.year)" :cy="yPos(y.standardized_rate ?? 0)" r="3.4" fill="var(--pine)" />
                <text :x="xPos(y.year)" :y="CHART_H - 8" text-anchor="middle" font-size="11" fill="#7b877f">{{ y.year }}</text>
              </g>
            </svg>
            <div class="legend" style="margin-top: 6px">
              <span><span class="swatch" style="background: var(--pine)"></span>分层标准化观测率（主结果）</span>
              <span><span class="swatch" style="background: var(--amber)"></span>原始观测率（未标准化，仅对照）</span>
              <span><span class="swatch" style="background: var(--slate)"></span>固定点位序列（独立参照，不拼接）</span>
            </div>
            <div class="table-wrap" style="margin-top: 12px">
              <table>
                <thead>
                  <tr>
                    <th>年份</th>
                    <th class="num">有效努力量（相机日）</th>
                    <th class="num">确认观测</th>
                    <th class="num">原始观测率</th>
                    <th class="num">标准化观测率</th>
                    <th class="num">80% 区间</th>
                    <th class="num">纳入单元</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="y in results.yearly" :key="y.year">
                    <td class="mono">{{ y.year }}</td>
                    <td class="num mono">{{ y.effort_days.toFixed(2) }}</td>
                    <td class="num mono">{{ y.observations }}</td>
                    <td class="num mono">{{ rate(y.raw_rate) }}</td>
                    <td class="num mono" style="font-weight: 600">{{ rate(y.standardized_rate) }}</td>
                    <td class="num mono tiny">
                      {{ y.interval ? `[${y.interval[0].toFixed(3)}, ${y.interval[1].toFixed(3)}]` : '—' }}
                    </td>
                    <td class="num mono">{{ y.included_units }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>

          <div class="stack">
            <div class="card">
              <div class="card-head"><h2>趋势判读</h2></div>
              <div class="stat" style="margin-bottom: 8px">
                <div class="stat-value" style="font-size: 22px">
                  {{ results.trend.direction }}
                  <span class="small muted" v-if="results.trend.slope_per_year !== null">
                    {{ signed(results.trend.slope_per_year) }}/年
                  </span>
                </div>
                <div class="stat-label" v-if="results.trend.slope_interval">
                  斜率 80% 区间 [{{ results.trend.slope_interval[0].toFixed(4) }},
                  {{ results.trend.slope_interval[1].toFixed(4) }}]
                </div>
              </div>
              <div class="callout warn">
                <div class="callout-title">解释边界</div>
                {{ results.trend.interpretation }}
              </div>
              <div class="stack-sm" style="margin-top: 10px">
                <div v-for="(d, i) in results.disclaimers" :key="i" class="tiny muted">· {{ d }}</div>
              </div>
            </div>

            <div class="card">
              <div class="card-head"><h2>固定点位参照序列</h2></div>
              <div class="tiny muted" style="margin-bottom: 8px">{{ results.fixed_point_series.note }}</div>
              <div class="pill-row" style="margin-bottom: 8px">
                <span v-for="p in results.fixed_point_series.points" :key="p" class="chip">{{ p }}</span>
              </div>
              <div class="table-wrap">
                <table>
                  <thead>
                    <tr><th>年份</th><th class="num">努力量</th><th class="num">观测</th><th class="num">观测率</th></tr>
                  </thead>
                  <tbody>
                    <tr v-for="y in results.fixed_point_series.yearly" :key="y.year">
                      <td class="mono">{{ y.year }}</td>
                      <td class="num mono">{{ y.effort_days.toFixed(2) }}</td>
                      <td class="num mono">{{ y.observations }}</td>
                      <td class="num mono">{{ rate(y.rate) }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
              <div class="tiny muted" style="margin-top: 6px">
                斜率 {{ signed(results.fixed_point_series.slope_per_year) }}/年 ·
                样本直接可比，但排除新覆盖生境，固定点失效后序列中断。
              </div>
            </div>

            <div class="card" v-if="results.independent_observations.length">
              <div class="card-head"><h2>新增探索点 · 独立观测</h2></div>
              <div class="table-wrap">
                <table>
                  <thead>
                    <tr><th>年份</th><th>点位</th><th class="num">努力量</th><th class="num">观测</th></tr>
                  </thead>
                  <tbody>
                    <tr v-for="row in results.independent_observations" :key="row.station_code + row.year">
                      <td class="mono">{{ row.year }}</td>
                      <td>{{ row.station_code }} · {{ row.station_name }}</td>
                      <td class="num mono">{{ row.effort_days.toFixed(2) }}</td>
                      <td class="num mono">{{ row.observations }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
              <div class="tiny muted" style="margin-top: 6px">
                新增探索点只发布独立观测，不纳入跨年趋势与分层标准化。
              </div>
            </div>
          </div>
        </div>
      </template>

      <!-- ==================== 分层样本与权重 ==================== -->
      <template v-if="tab === 'strata'">
        <div class="card" style="margin-bottom: 14px">
          <div class="card-head">
            <h2>分层样本与权重（生境 × 海拔带 × 季节）</h2>
            <span class="card-note">权重按共同覆盖范围内的汇总努力量估计</span>
          </div>
          <div class="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>层</th>
                  <th class="num">权重</th>
                  <th v-for="year in results.years" :key="year" class="num">{{ year }}<br />努力量/观测/率</th>
                  <th>覆盖判定</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="s in results.strata" :key="s.stratum_key">
                  <td>
                    <div>{{ s.habitat }} · {{ s.elevation_band }}</div>
                    <div class="tiny muted mono">{{ s.stratum_key }}</div>
                  </td>
                  <td class="num mono">{{ s.common ? fmtPct(s.weight, 1) : '—' }}</td>
                  <td v-for="year in results.years" :key="year" class="num mono small">
                    <template v-if="s.per_year[String(year)]">
                      {{ s.per_year[String(year)]!.effort_days.toFixed(2) }} /
                      {{ s.per_year[String(year)]!.observations }} /
                      {{ rate(s.per_year[String(year)]!.rate) }}
                    </template>
                    <span v-else class="muted">无覆盖</span>
                  </td>
                  <td>
                    <span v-if="!s.common" class="badge invalid">不足以比较</span>
                    <span v-else-if="s.coverage_flag === 'insufficient_effort'" class="badge restricted">覆盖不足</span>
                    <span v-else class="badge valid">覆盖充分</span>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <div class="callout info" style="margin-top: 10px">
            覆盖不足的层保留在标准化中但不确定范围更大；不共同覆盖的层只做并列展示，不做外推。
          </div>
        </div>

        <div class="card" v-if="results.insufficient_ranges.length">
          <div class="card-head"><h2>不足以比较的范围（不外推）</h2></div>
          <div class="table-wrap">
            <table>
              <thead>
                <tr><th>层</th><th>有覆盖年份</th><th>缺失年份</th><th>处理</th></tr>
              </thead>
              <tbody>
                <tr v-for="r in results.insufficient_ranges" :key="r.stratum_key">
                  <td>{{ r.habitat }} · {{ r.elevation_band }}</td>
                  <td class="mono">{{ r.years_present.join('、') }}</td>
                  <td class="mono">{{ r.missing_years.join('、') }}</td>
                  <td class="small">{{ r.reason }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </template>

      <!-- ==================== 单元与排除点位 ==================== -->
      <template v-if="tab === 'units'">
        <div class="card">
          <div class="card-head">
            <h2>调查单元纳入情况</h2>
            <div class="toolbar">
              <select v-model="unitFilter" class="select" style="width: 140px">
                <option value="all">全部</option>
                <option value="included">仅纳入</option>
                <option value="excluded">仅排除</option>
              </select>
              <select v-model="yearFilter" class="select" style="width: 120px">
                <option value="">全部年份</option>
                <option v-for="year in results.years" :key="year" :value="year">{{ year }}</option>
              </select>
            </div>
          </div>
          <div class="grid grid-3" style="margin-bottom: 12px">
            <div class="card tight"><div class="stat">
              <div class="stat-value" style="color: var(--pine)">{{ includedUnits.length }}</div>
              <div class="stat-label">纳入单元（符合趋势用途）</div>
            </div></div>
            <div class="card tight"><div class="stat">
              <div class="stat-value" style="color: var(--rust)">{{ excludedUnits.length }}</div>
              <div class="stat-label">排除点位（含探索点独立观测）</div>
            </div></div>
            <div class="card tight"><div class="stat">
              <div class="stat-value">
                {{ units.filter((u) => u.excluded_materials.length).length }}
              </div>
              <div class="stat-label">含跨界排除素材的单元</div>
            </div></div>
          </div>
          <div class="table-wrap" style="max-height: 520px; overflow-y: auto">
            <table>
              <thead>
                <tr>
                  <th>点位 / 日期</th>
                  <th>点段</th>
                  <th>层</th>
                  <th class="num">努力量</th>
                  <th class="num">观测</th>
                  <th class="num">权重</th>
                  <th>纳入理由 / 排除原因</th>
                  <th>证书</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="u in filteredUnits" :key="u.id">
                  <td>
                    <div>{{ u.station_code }}</div>
                    <div class="tiny muted mono">{{ u.unit_date }}</div>
                    <div class="tiny muted">{{ POINT_ROLE_LABEL[u.point_role] ?? u.point_role }}</div>
                  </td>
                  <td class="mono tiny">{{ u.segment_key }}</td>
                  <td class="small">
                    <template v-if="u.stratum_key">{{ u.habitat }} · {{ u.elevation_band }}</template>
                    <span v-else class="muted">—</span>
                  </td>
                  <td class="num mono">{{ u.included || u.point_role === 'exploration' ? u.effort_days.toFixed(2) : '—' }}</td>
                  <td class="num mono">{{ u.included || u.point_role === 'exploration' ? u.observation_count : '—' }}</td>
                  <td class="num mono">{{ u.included && u.weight ? u.weight.toFixed(4) : '—' }}</td>
                  <td class="small" style="max-width: 320px">
                    <div v-for="(r, i) in u.reasons" :key="i" :style="u.included ? '' : 'color: var(--rust)'">{{ r }}</div>
                    <div v-for="m in u.excluded_materials" :key="m.record_id" class="tiny" style="color: var(--amber)">
                      素材 {{ m.external_id }}：{{ m.reason }}
                    </div>
                  </td>
                  <td class="tiny mono">
                    <router-link v-if="u.unit_id" :to="'/units/' + u.unit_id">{{ u.certificate_no || '单元' }}</router-link>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </template>

      <!-- ==================== 简报与修订分解 ==================== -->
      <template v-if="tab === 'briefs'">
        <div class="grid grid-2-1">
          <div class="stack">
            <div class="card" v-if="decomposition">
              <div class="card-head">
                <h2>趋势变化分解（v{{ (detail.brief?.version ?? 1) - 1 }} → v{{ detail.brief?.version }}）</h2>
              </div>
              <div class="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>年份</th>
                      <th class="num">修订前</th>
                      <th class="num">修订后</th>
                      <th class="num">覆盖 Δ</th>
                      <th class="num">努力量 Δ</th>
                      <th class="num">判读 Δ</th>
                      <th class="num">合计 Δ</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="row in decomposition.per_year" :key="row.year">
                      <td class="mono">{{ row.year }}</td>
                      <td class="num mono">{{ rate(row.before) }}</td>
                      <td class="num mono">{{ rate(row.after) }}</td>
                      <td class="num mono">{{ signed(row.delta_coverage) }}</td>
                      <td class="num mono">{{ signed(row.delta_effort) }}</td>
                      <td class="num mono">{{ signed(row.delta_interpretation) }}</td>
                      <td class="num mono" style="font-weight: 600">{{ signed(row.delta_total) }}</td>
                    </tr>
                    <tr>
                      <td class="mono">斜率</td>
                      <td class="num mono">{{ signed(decomposition.slope.before) }}</td>
                      <td class="num mono">{{ signed(decomposition.slope.after) }}</td>
                      <td class="num mono">{{ signed(decomposition.slope.delta_coverage) }}</td>
                      <td class="num mono">{{ signed(decomposition.slope.delta_effort) }}</td>
                      <td class="num mono">{{ signed(decomposition.slope.delta_interpretation) }}</td>
                      <td class="num mono">—</td>
                    </tr>
                  </tbody>
                </table>
              </div>
              <div class="tiny muted" style="margin-top: 6px">{{ decomposition.note }}</div>

              <div class="table-wrap" style="margin-top: 12px" v-if="decomposition.changed_units.length">
                <table>
                  <thead>
                    <tr><th>变化单元</th><th>因子</th><th>修订前</th><th>修订后</th></tr>
                  </thead>
                  <tbody>
                    <tr v-for="u in decomposition.changed_units" :key="u.unit_id">
                      <td>
                        <router-link :to="'/units/' + u.unit_id">{{ u.station_code }}</router-link>
                        <span class="tiny muted mono"> {{ u.unit_date }}</span>
                      </td>
                      <td>
                        <span v-for="f in u.factors" :key="f" class="badge" :class="factorBadgeClass(f)" style="margin-right: 4px">
                          {{ TREND_FACTOR_LABEL[f] }}
                        </span>
                      </td>
                      <td class="small">
                        <template v-if="u.before">
                          {{ u.before.included ? '纳入' : '排除' }} · {{ u.before.stratum_key || '—' }} ·
                          努力量 {{ u.before.effort_days.toFixed(2) }} · 观测 {{ u.before.observation_count }}
                          <div class="tiny muted mono">{{ u.before.certificate_no }}</div>
                        </template>
                        <span v-else class="muted">不在旧简报</span>
                      </td>
                      <td class="small">
                        <template v-if="u.after">
                          {{ u.after.included ? '纳入' : '排除' }} · {{ u.after.stratum_key || '—' }} ·
                          努力量 {{ u.after.effort_days.toFixed(2) }} · 观测 {{ u.after.observation_count }}
                          <div class="tiny muted mono">{{ u.after.certificate_no }}</div>
                        </template>
                        <span v-else class="muted">不在新简报</span>
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>
            <div class="card" v-else>
              <div class="empty">当前为首版简报，尚无修订分解。发生维护日志补录、迁点日期纠正或判读修订后，重算将给出 覆盖 / 努力量 / 判读 三类因子的差异。</div>
            </div>

            <div class="card" v-if="recomputedFor.length">
              <div class="card-head"><h2>本次重算回传的修订</h2></div>
              <div v-for="(reason, i) in recomputedFor" :key="i" class="small" style="margin-bottom: 6px">
                <span class="badge" :class="factorBadgeClass(reason.factor)">{{ TREND_FACTOR_LABEL[reason.factor] }}</span>
                {{ reason.reason }}
                <span class="tiny muted">{{ fmtDateTime(reason.at) }} · {{ reason.actor }}</span>
              </div>
            </div>
          </div>

          <div class="card">
            <div class="card-head"><h2>简报历史（可复现旧输入）</h2></div>
            <div class="stack-sm">
              <div v-for="b in briefs" :key="b.id" class="brief-row" :class="{ current: b.status === 'current' }">
                <div>
                  <div>
                    <b>v{{ b.version }}</b>
                    <span class="badge" :class="b.status === 'current' ? 'valid' : 'neutral'" style="margin-left: 6px">
                      {{ b.status === 'current' ? '当前' : '历史' }}
                    </span>
                  </div>
                  <div class="tiny muted">{{ fmtDateTime(b.created_at) }} · {{ b.created_by }}</div>
                  <div class="tiny muted" v-if="b.note">{{ b.note }}</div>
                  <div class="hash">输入哈希 {{ b.input_hash.slice(0, 16) }}…</div>
                </div>
                <button class="btn ghost sm" @click="openBrief(b.version)">复现输入</button>
              </div>
            </div>
          </div>
        </div>

        <div class="card" style="margin-top: 14px" v-if="viewingBrief">
          <div class="card-head">
            <h2>简报 v{{ viewingBrief.version }} 的冻结输入（{{ viewingBrief.status === 'current' ? '当前' : '历史复现' }}）</h2>
            <button class="btn ghost sm" @click="viewingBrief = null">收起</button>
          </div>
          <div class="tiny muted" style="margin-bottom: 8px">
            该简报签发时的逐单元输入（努力量、观测次数、证书编号、判读 id）原样保留，结果可由这些输入复现；后续修订不回写历史简报。
          </div>
          <div class="table-wrap" style="max-height: 380px; overflow-y: auto">
            <table>
              <thead>
                <tr>
                  <th>点位 / 日期</th><th>层</th><th class="num">努力量</th><th class="num">观测</th>
                  <th>证书</th><th>判读 id</th><th>状态</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="u in viewingBrief.inputs?.units ?? []" :key="u.unit_id">
                  <td>
                    {{ u.station_code }} <span class="tiny muted mono">{{ u.unit_date }}</span>
                  </td>
                  <td class="tiny mono">{{ u.stratum_key || '—' }}</td>
                  <td class="num mono">{{ u.included || u.point_role === 'exploration' ? u.effort_days.toFixed(2) : '—' }}</td>
                  <td class="num mono">{{ u.included || u.point_role === 'exploration' ? u.observation_count : '—' }}</td>
                  <td class="tiny mono">{{ u.certificate_no || '—' }}</td>
                  <td class="tiny mono">{{ u.determination_ids.join(', ') || '—' }}</td>
                  <td>
                    <span class="badge" :class="u.included ? 'valid' : 'neutral'">
                      {{ u.included ? '纳入' : '排除' }}
                    </span>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </template>
    </template>
  </div>
</template>

<style scoped>
.brief-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 8px 10px;
  border: 1px solid var(--line);
  border-radius: 8px;
}
.brief-row.current { border-color: var(--pine-mid); background: #f6faf7; }
</style>
