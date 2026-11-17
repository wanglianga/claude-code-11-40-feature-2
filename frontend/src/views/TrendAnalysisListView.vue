<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api'
import type { AnnualPlan, TrendAnalysis } from '../types'
import StatusBadge from '../components/StatusBadge.vue'
import { fmtDateTime, TREND_FACTOR_LABEL } from '../format'
import { authState } from '../session'
import { useToast } from '../toast'

const { push: notify } = useToast()

const router = useRouter()
const analyses = ref<TrendAnalysis[]>([])
const plans = ref<AnnualPlan[]>([])
const loading = ref(true)
const error = ref('')
const creating = ref(false)
const createForm = ref({ species_code: '', label: '' })

const canEdit = computed(() => ['researcher', 'auditor'].includes(authState.user.value?.role ?? ''))

async function load() {
  loading.value = true
  error.value = ''
  try {
    ;[analyses.value, plans.value] = await Promise.all([
      api.get<TrendAnalysis[]>('/trend-analyses'),
      api.get<AnnualPlan[]>('/annual-plans'),
    ])
  } catch (err) {
    error.value = err instanceof Error ? err.message : '加载失败'
  } finally {
    loading.value = false
  }
}

onMounted(load)

const speciesOptions = computed(() => {
  const seen = new Map<string, string>()
  for (const plan of plans.value) {
    for (const sp of plan.target_species) seen.set(sp.code, sp.name)
  }
  return [...seen.entries()].map(([code, name]) => ({ code, name }))
})

const planYears = computed(() => plans.value.map((p) => p.year).join(' / '))

async function create() {
  const species = createForm.value.species_code
  if (!species) {
    notify('请选择目标物种', 'error')
    return
  }
  creating.value = true
  try {
    const analysis = await api.post<TrendAnalysis>('/trend-analyses', {
      species_code: species,
      plan_ids: plans.value.map((p) => p.id),
      label:
        createForm.value.label ||
        `${speciesOptions.value.find((s) => s.code === species)?.name ?? species} 多年可比性分析`,
    })
    notify('分析已创建并完成首次计算')
    router.push(`/trend-analysis/${analysis.id}`)
  } catch (err) {
    notify(err instanceof Error ? err.message : '创建失败', 'error')
  } finally {
    creating.value = false
  }
}

function statusBadge(status: string) {
  return status === 'completed'
    ? { status: 'valid', label: '已完成' }
    : { status: 'pending', label: '待重算' }
}
</script>

<template>
  <div>
    <div class="page-head">
      <div>
        <div class="eyebrow">Annual Trend Comparability</div>
        <h1>年度趋势可比性分析</h1>
        <p class="page-sub">
          按 生境×海拔带×季节 分层标准化比较多年观测率，区分观测变化来自动物活动还是相机迁移、
          样线扩充与努力量变化；固定点位序列作为独立参照，两者不拼接。新增探索点只发布独立观测，
          不重叠的海拔带与季节不外推。
        </p>
      </div>
    </div>

    <div v-if="error" class="callout danger">{{ error }}</div>
    <div v-if="loading" class="loading">加载中…</div>

    <template v-else>
      <div class="grid grid-3" style="margin-bottom: 14px">
        <div class="card tight">
          <div class="stat">
            <div class="stat-value">{{ analyses.length }}</div>
            <div class="stat-label">趋势分析</div>
          </div>
        </div>
        <div class="card tight">
          <div class="stat">
            <div class="stat-value" style="color: var(--slate)">
              {{ analyses.filter((a) => a.status === 'stale').length }}
            </div>
            <div class="stat-label">待重算（修订待回传）</div>
          </div>
        </div>
        <div class="card tight">
          <div class="stat">
            <div class="stat-value">{{ plans.length }}</div>
            <div class="stat-label">年度调查计划（{{ planYears }}）</div>
          </div>
        </div>
      </div>

      <div class="card" style="margin-bottom: 14px">
        <div class="card-head">
          <h2>分析列表</h2>
          <div class="toolbar" v-if="canEdit && plans.length >= 2">
            <select v-model="createForm.species_code" class="select" style="width: 180px">
              <option value="" disabled>选择目标物种</option>
              <option v-for="sp in speciesOptions" :key="sp.code" :value="sp.code">
                {{ sp.name }}（{{ sp.code }}）
              </option>
            </select>
            <button class="btn primary sm" :disabled="creating" @click="create">
              {{ creating ? '计算中…' : '新建分析（全部年度计划）' }}
            </button>
          </div>
        </div>
        <div v-if="!analyses.length" class="empty">尚无趋势分析。选择目标物种后新建。</div>
        <div v-else class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>分析</th>
                <th>目标物种</th>
                <th>年份</th>
                <th>方法</th>
                <th>趋势方向</th>
                <th>状态</th>
                <th>简报</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="a in analyses" :key="a.id">
                <td>
                  <div>{{ a.label }}</div>
                  <div class="tiny muted mono">{{ a.analysis_code }}</div>
                </td>
                <td>{{ a.species_name }}<div class="tiny muted mono">{{ a.species_code }}</div></td>
                <td class="mono small">{{ a.years.join(' → ') }}</td>
                <td class="small">分层标准化<br /><span class="tiny muted">固定点位单独参照</span></td>
                <td>
                  <span class="badge" :class="a.trend_direction === '上升' ? 'restricted' : 'neutral'">
                    {{ a.trend_direction ?? '—' }}
                  </span>
                  <div v-if="a.trend_slope_per_year !== null" class="tiny muted mono">
                    {{ a.trend_slope_per_year > 0 ? '+' : '' }}{{ a.trend_slope_per_year?.toFixed(3) }}/年
                  </div>
                </td>
                <td>
                  <StatusBadge :status="statusBadge(a.status).status" :label="statusBadge(a.status).label" />
                  <div v-if="a.stale_reasons.length" class="tiny" style="color: var(--rust); max-width: 240px">
                    {{ a.stale_reasons.length }} 项修订待回传：
                    {{ [...new Set(a.stale_reasons.map((r) => TREND_FACTOR_LABEL[r.factor]))].join('、') }}
                  </div>
                </td>
                <td class="small">
                  <div>v{{ a.current_brief_version }}</div>
                  <div class="tiny muted">{{ fmtDateTime(a.created_at) }}</div>
                </td>
                <td class="right">
                  <button class="btn ghost sm" @click="router.push(`/trend-analysis/${a.id}`)">下钻</button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <div class="card">
        <div class="card-head"><h2>年度调查计划</h2></div>
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>计划</th>
                <th>年份</th>
                <th>点位（固定 / 扩充 / 探索）</th>
                <th>目标物种（可调查时段）</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="plan in plans" :key="plan.id">
                <td>
                  <div>{{ plan.label }}</div>
                  <div class="tiny muted mono">{{ plan.plan_code }}</div>
                </td>
                <td class="mono">{{ plan.year }}</td>
                <td class="small">
                  <span class="chip">{{ plan.points.filter((p) => p.role === 'core').length }} 固定</span>
                  <span class="chip">{{ plan.points.filter((p) => p.role === 'expansion').length }} 扩充</span>
                  <span class="chip">{{ plan.points.filter((p) => p.role === 'exploration').length }} 探索</span>
                  <div class="tiny muted" style="margin-top: 4px">
                    {{ plan.points.map((p) => p.station_code).join('、') }}
                  </div>
                </td>
                <td class="small">
                  <div v-for="sp in plan.target_species" :key="sp.code">
                    {{ sp.name }}
                    <span class="tiny muted mono">
                      {{ (sp.daily_windows ?? []).map((w) => w.join('-')).join('、') }}
                    </span>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div class="callout pine" style="margin-top: 12px">
          <div class="callout-title">口径提示</div>
          观测率是种群活动的代理指标：同一设备编号不代表同一调查点，照片数量不代表种群规模；
          观测率变化不能解释为已确认的种群增长。
        </div>
      </div>
    </template>
  </div>
</template>
