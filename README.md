# 自然保护区季节调查完整性与覆盖数据服务

面向自然保护区研究人员的**覆盖与调查有效性数据服务**：按「站点—样区—日期」组装调查单元，
逐项判断设备可用性、时间可信度、空间覆盖与素材判读是否满足规则册门槛，签发
**有效调查 / 受限调查 / 未有效调查 / 待核**证书，并并列展示经历史校准的检测概率估计。

在此之上，服务提供**年度监测趋势可比性分析**：按 生境×海拔带×季节 分层标准化比较多年观测率，
帮助研究人员区分观测变化来自动物活动本身，还是相机迁移、样线扩充与调查努力量变化；
固定点位序列作为独立参照序列，两者不拼接为一条趋势。

> 服务只交付覆盖与调查有效性数据。它**不派发巡护任务、不预约人员器材、不创建执法/捕捉/资源调度动作**，
> 也不把调查缺口转成行动指令。

---

## 1. 技术栈

| 层 | 技术 |
| --- | --- |
| 前端 | Vue 3.5 + TypeScript + Vue Router + Vite 7 |
| 后端 | FastAPI 0.163 + SQLAlchemy 2.1 + Shapely 2.2 |
| 数据库 | PostgreSQL 18（JSONB 存原始载荷 / 门槛快照 / 证书结论 / 趋势简报冻结输入） |
| 测试 | pytest（21 个用例，覆盖 7 个验收场景 + 修订/回溯 + 多年趋势可比性） |

## 2. 一键启动（Docker Compose）

```bash
cd <仓库根目录>
docker compose up --build
```

启动后：

- 前端：<http://localhost:8080>
- 后端 OpenAPI 文档：<http://localhost:8000/docs>
- 健康检查：<http://localhost:8000/api/health>

首次启动时后端容器会等待 PostgreSQL 就绪，自动建表并写入演示种子数据
（2024–2026 三个春季运行、11 个站点、66 个调查单元、3 个年度调查计划、
1 个已计算的大熊猫多年趋势分析）。

> 本版本对数据模型有破坏性变更（新增点位档案字段与趋势分析表）。升级已有数据库时请
> 先 `docker compose down -v` 清理数据卷再重新启动，或重建开发库后执行 `python -m app.seed`。

停止：`docker compose down`；连同数据卷清理：`docker compose down -v`。

## 3. 本地开发（不使用 Docker）

运行时已在容器内预装（Python 3.12 / Node 22 / PostgreSQL 18），也可用本机同版本。

### 3.1 数据库

```bash
# 数据库账号 ccdev / ccdev，端口 5432
createdb -h 127.0.0.1 -U ccdev survey_integrity        # 开发库
createdb -h 127.0.0.1 -U ccdev survey_integrity_test   # 测试库（pytest 使用）
```

### 3.2 后端

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

export DATABASE_URL='postgresql+psycopg://ccdev:ccdev@127.0.0.1:5432/survey_integrity'
.venv/bin/python -m app.seed                # 建表 + 写入演示数据（可重复执行，已有数据则跳过）
.venv/bin/uvicorn app.main:app --reload --port 8000
```

- API 根路径：`http://127.0.0.1:8000/api`
- Swagger UI：`http://127.0.0.1:8000/docs`
- OpenAPI JSON：`http://127.0.0.1:8000/openapi.json`

> 本项目为全栈应用（含业务前端页面），按任务约束同时提供可运行的 OpenAPI 3.x 文档与 Swagger UI，
> 便于接口对接与验收。

### 3.3 前端

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173 ，/api 代理到 http://127.0.0.1:8000
```

生产构建：`npm run build`（产物在 `frontend/dist`，可用任意静态服务器托管，`/api` 反代到后端）。

### 3.4 测试

```bash
cd backend
DATABASE_URL='postgresql+psycopg://ccdev:ccdev@127.0.0.1:5432/survey_integrity_test' \
  .venv/bin/python -m pytest -q
```

测试会重建测试库的 `public` schema 并写入种子数据，**不会影响开发库**。

## 4. 测试账号

| 账号 | 密码 | 角色 | 权限 |
| --- | --- | --- | --- |
| `yq.li` | `Survey#2026` | 研究人员 researcher | 组装运行、登记/撤回趋势引用、修订记录与判读、处置冲突、重新签发证书、新建/重算趋势分析、纠正迁点日期 |
| `m.cao` | `Audit#2026` | 审核员 auditor | 同上（用于复核类操作与审计） |
| `l.lin` | `View#2026` | 只读访客 viewer | 只读查看所有数据 |

## 5. 业务模型与判定口径

### 5.1 调查单元

覆盖组装器按 `站点 × 样区 × 调查日`（规则册 `schedule.survey_dates`）生成调查单元。
每个单元固定引用：站点版本、规则册版本、概率模型版本，并把四类门槛的判定与证据记录 id 一并留存。

### 5.2 四类门槛

| 门槛 | 判定要点 | 典型结论 |
| --- | --- | --- |
| `device` 设备可用性 | 心跳间隔、连续图像帧序列（`frame_seq` 跳号）、停机日志覆盖；未解释缺口 → **待核** | 帧缺失且停机日志未覆盖 → 设备待核 |
| `time` 时间可信度 | 设备时间与可信源偏差 vs 容差（120s）；**存在可验证校时关系**才可回算；迟到送达只记录不改事件时间 | 偏移超容差且无校时 → 未满足 |
| `space` 空间覆盖 | 巡护轨迹对规则册路线段的覆盖、进入缓冲区深度、**定位精度半径 vs 缓冲区宽度**；按事件时间的站点版本取边界 | 仅擦过缓冲边缘且精度 > 缓冲宽度 → 空间待核 |
| `reading` 素材判读 | 达置信门槛的判读数、待判读占比、互斥判读冲突 | 互斥且均低于门槛 → 保留冲突、判读待核 |

### 5.3 证书状态与用途

| 状态 | 含义 | 正式未发现结论 | 趋势输入 |
| --- | --- | --- | --- |
| 有效调查 `valid` | 四类门槛均通过且无未决冲突 | ✅ | ✅ |
| 受限调查 `restricted` | 主要门槛通过但存在受限项 | ❌ | ✅ |
| 未有效调查 `invalid` | 存在未满足门槛 | ❌ | ❌ |
| 待核 `pending` | 存在待核实证据 | ❌ | ❌ |
| 复审中 `under_review` | 判读修订改变出现判定后签发的复审版本 | ❌ | ❌（暂停新引用） |

证书快照（门槛判定 + 结论）在签发时深拷贝保存；后续重算不会改写已签发证书。
复审会**新增一个证书版本**并把旧证书标记为被替代，旧运行仍可看到原证书原貌。

### 5.4 规则证书 vs 概率估计

- **规则证书**：逐项门槛，可向监管人员解释；接近门槛的部分路线会被排除，样本更少。
- **概率估计**：`DET-LOGIT` 检测概率模型（logistic，特征为设备可用比例、路线覆盖、达门槛判读数、待判读比例、
  缓冲区内素材比例、精度是否可信），时间可信与无冲突是**门控特征**（不满足则覆盖值为 0）。
  结果带 80% 敏感区间、校准集切换（pivot 偏移）与阈值上浮敏感性。
- 概率结果**仅用于趋势研究**，界面与接口均标注「模型推算，不是已确认的实地覆盖」，
  接口 `purpose=trend_only`，不会写入证书用途。

### 5.5 七个验收场景（种子数据）

| 站点 | 场景 | 期望结果 |
| --- | --- | --- |
| `QSL-01` 青松岭主监测站 | 完整调查 + 可验证校时 + 迟到送达 | 有效调查，可用于正式未发现结论 |
| `QSL-02` 青松岭北梁相机站 | 有心跳但帧连续缺失，停机日志未覆盖 | 设备可用性**待核**，不判未出现 |
| `QSL-03` 青松岭西沟站 | 两来源互斥判读且均低于 0.70 | 判读**待核**，保留冲突 |
| `QSL-04` 青松岭东南站 | 待判读占比过高（薄判读） | 判读待核；概率估计偏低 |
| `YXG-01` 云溪沟西站 | 轨迹只擦过缓冲边缘，精度 40m > 缓冲 30m | 空间**待核** |
| `YXG-02` 云溪沟东站 | 迟到判读修订：未出现 → 出现 | 当前证书**复审中**，旧引用暂停，旧证书保留 |
| `YXG-03` 云溪沟下坝站 | 路线覆盖 60%（接近门槛 50%/目标 80%） | 受限调查；概率估计仍过阈值 → 样本取舍分歧 |
| `BHP-01` 北坡高寒相机站 | 设备时钟偏移 900s 且无可验证校时 | 时间**未满足** → 未有效调查 |
| `BHP-02` 北坡垭口迁移站 | 4/11 迁移边界与路线段变更 | 4/11 用 v1、4/12 用 v2，各自判定 |

### 5.6 年度趋势可比性分析

种子数据覆盖连续三年（2024 → 2025 → 2026，设备总数 4 → 7 → 11），用于回答：
某种动物的观测变化究竟来自活动变化，还是相机迁移、样线扩充与调查努力量变化。

**数据链路**

| 环节 | 口径 |
| --- | --- |
| 点位档案 | 站点版本保存位置（边界/质心）、生境、迁移生效日期与坐标精度；同一设备编号不代表同一调查点 |
| 年度调查计划 | 引用当季点位（连续固定点 / 样线扩充点 / 新增探索点）与目标物种（含每日可调查时段） |
| 努力量计算 | 读取主服务的调查证书（趋势用途）、实际运行日（设备门槛的停机/未解释缺口区间）与待判读范围（判读门槛 pending 占比），**按目标物种的可调查时段折算**：设备白天正常运行但夜间故障时，夜行物种只能拿到夜间时段的努力量 |
| 趋势输入 | 只消费趋势用途符合的调查单元（证书有效/受限且非复审中），逐单元保存纳入理由；排除单元也保存排除原因 |

**两种序列，不拼接**

- **分层标准化（主结果）**：按 生境×海拔带×季节 分层，对共同覆盖范围内的层以汇总努力量估计权重，
  逐年给出标准化观测率与 80% 区间；覆盖不足的层保留但不确定范围更大；
  不重叠的海拔带与季节**不做外推**，标为「不足以比较」。
- **固定点位参照序列**：仅使用多年连续运行的固定点位，样本直接可比，
  但排除新覆盖生境、固定点失效后序列中断；作为**单独参照**展示，不与分层标准化拼成一条趋势。
- **新增探索点**（如 BHP-03 雪线站）只发布独立观测，不纳入趋势。

**季中迁移与素材归属**

- 迁点发生在季中时，调查单元按有效位置和日期拆成迁前/迁后点段，分属不同层；
  同一素材只归属其中一个单元。
- 素材日期未知、或设备时钟误差的可信区间跨过迁点边界的，暂不进入跨年比较
  （种子中 YXG-04 备用机帧即此例）。

**修订回传与简报**

- 迟到维护日志（改变有效努力量）、迁点日期纠正（改变分层归属）、判读修订/撤销（改变观测次数）
  会通过单元引用关系找出受影响的层与年度对比，把分析标记为**待重算**；
  重算同时重建分子与分母，不会只更新分子却保留旧分母。
- 历史简报冻结签发时的逐单元输入（努力量、观测、证书编号、判读 id），始终可复现旧输入；
  重算生成新简报版本，并给出趋势变化中由**覆盖、努力量、判读**分别引起的差异分解。
- 观测率是种群活动的代理指标：界面与报告均标注「观测率变化不能解释为已确认的种群增长」。

## 6. 验证方式（均已实际执行）

### 6.1 自动化测试

```bash
cd backend
DATABASE_URL='postgresql+psycopg://ccdev:ccdev@127.0.0.1:5432/survey_integrity_test' \
  .venv/bin/python -m pytest -q
# 21 passed
```
覆盖：

- `tests/test_scenarios.py`：7 个验收场景 + 校时放行 + 引用用途限制 + 回溯链完整性 + 无派工动作断言
- `tests/test_revisions.py`：判读修订触发复审与新证书版本、档案记录修订保留哈希链、
  单元证据全链可回溯、重算运行不改变旧证书
- `tests/test_trends.py`：多年趋势验收——年度计划点位与物种时段、原始观测率与标准化结果、
  分层权重与不足以比较范围、固定点/季中迁移点/新增高海拔点/部分时段停机、
  物种时段努力量折算、迁点边界素材排除、样本归属互斥；
  修订流（补录维护 → 纠正迁点日期 → 撤销判读 → 重新签发 → 重算）验证待重算传播、
  分母随证据变化、报告引用准确、历史简报复现旧输入、覆盖/努力量/判读分解

### 6.2 前端构建与类型检查

```bash
cd frontend
npx vue-tsc --noEmit     # 0 error
npm run build            # 构建成功
```

### 6.3 趋势验收流（本轮实际执行，API 级）

按验收输入（固定点 QSL-01/QSL-03/YXG-03、季中迁移点 BHP-02/YXG-04、新增高海拔点 BHP-03、
部分时段停机 YXG-04/BHP-03 夜间停机）执行：

1. `GET /api/trend-analyses/1`：原始观测率 0.444 → 0.667 → 0.655，标准化结果 0.430 → 0.703 → 0.719；
   高寒针叶林层标为「不足以比较（不重叠，不外推）」；BHP-03 仅独立观测（努力量 2.25 相机日，
   夜间停机已扣减）；YXG-04 备用机帧因时钟误差跨迁点边界被排除。
2. 补录维护：`POST /api/records`（QSL-01 2026-04-10 夜间 21:30–23:00 停机，迟到送达）
   → 分析转为「待重算」，受影响层=针阔混交林×MID、年份=2026（factor=effort）。
3. 纠正迁点日期：`POST /api/stations/{BHP-02}/migration-correction`（4/12 → 4/11）
   → 待重算（factor=coverage）。
4. 撤销一条判读：`POST /api/determinations/{id}/revoke`（QSL-01 4/11 大熊猫出现判读）
   → 单元转入复审、分析待重算（factor=interpretation）；随后 `POST /api/units/{id}/certificates/reissue`
   重新签发（CERT-…-V3，趋势用途恢复）。
5. `POST /api/trend-analyses/1/recompute` → 简报 v2：QSL-01 4/10 努力量 1.0 → 0.875（分母随证据变化）、
   QSL-01 4/11 观测 2 → 1、BHP-02 4/11 层归属 HIGH → MID；
   分解给出 2026 年 覆盖 −0.047 / 努力量 +0.005 / 判读 −0.054（合计 −0.096），
   趋势斜率 0.145 → 0.094/年；样本归属仍互斥。
6. `GET /api/trend-analyses/1/briefs/1`：历史简报原样保留旧输入（努力量 1.0、旧证书号、旧分层），
   可复现；v2 引用重新签发后的证书编号，不再引用被撤销的判读。

### 6.4 端到端界面验证（历史执行记录）

上一轮交付曾用 headless Chromium + Playwright 逐页截图核对（本轮环境无浏览器，
以 6.2 构建检查与 6.3/6.5 API 冒烟为准）：

1. 登录 `yq.li / Survey#2026` → 站点覆盖总览：矩阵单元、门槛分布与「需关注的调查单元」联动。
2. 进入 `QSL-02` 单元：设备门槛显示「待核」，并列出未覆盖的帧缺失区间与小时数。
3. 进入 `YXG-01`：空间门槛「待核」，说明「精度 40m > 缓冲宽度 30m」。
4. 进入 `QSL-03`：判读「待核 · 1 项冲突未决」；冲突页展示两来源互斥结论并可记录处置。
5. 进入 `YXG-02`：证书「复审中」，趋势引用「已暂停」，证书历史含 v1（原签发）与 v2（复审）。
6. 进入 `BHP-01`：时间门槛「未满足」，说明无可验证校时关系。
7. `规则证书 vs 概率估计`：并列对照行与阈值敏感性表正确联动。
8. `单元回溯链`：原始事件 → 覆盖条件 → 版本 → 证书 → 趋势引用五段齐全，记录含 64 位哈希。
9. 浏览器控制台无报错。

本轮经 API 复核的对应数据：2026 运行 33 个矩阵单元、15 有效 / 4 受限 / 3 未有效 / 11 待核；
并列对照 22 行（15 一致支持、7 概率支持 · 规则排除）。

### 6.5 API 冒烟

```bash
TOKEN=$(curl -s -X POST http://127.0.0.1:8000/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"yq.li","password":"Survey#2026"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["token"])')

curl -s http://127.0.0.1:8000/api/runs -H "Authorization: Bearer $TOKEN"
curl -s http://127.0.0.1:8000/api/runs/1/overview -H "Authorization: Bearer $TOKEN"
curl -s http://127.0.0.1:8000/api/units/1/trace -H "Authorization: Bearer $TOKEN"
curl -s http://127.0.0.1:8000/api/annual-plans -H "Authorization: Bearer $TOKEN"
curl -s http://127.0.0.1:8000/api/trend-analyses -H "Authorization: Bearer $TOKEN"
curl -s http://127.0.0.1:8000/api/trend-analyses/1 -H "Authorization: Bearer $TOKEN"
curl -s http://127.0.0.1:8000/api/trend-analyses/1/units -H "Authorization: Bearer $TOKEN"
```

## 7. 界面

| 页面 | 说明 |
| --- | --- |
| 站点覆盖总览 | 站点 × 调查日矩阵、门槛分布、需关注单元、最近数据活动 |
| 单元详情 | 规则证书 vs 概率估计并列；四门槛证据；原始证据表；证书历史；审计；引用登记 |
| 规则证书 vs 概率估计 | 逐单元并列对照、分歧分类、阈值敏感性、单单元敏感度复算 |
| 趋势输入清单 | 按用途/状态筛选引用，显示引用时证书快照与概率区间 |
| 年度趋势对比（列表） | 分析状态（完成/待重算）、趋势方向、年度计划点位与物种可调查时段；新建分析 |
| 年度趋势对比（详情） | 全区结论（原始 vs 标准化 vs 固定点序列）→ 下钻分层样本与权重、不足以比较范围、排除点位与独立观测、单元级纳入理由；简报历史复现旧输入、覆盖/努力量/判读分解 |
| 单元回溯链 | 原始事件 → 覆盖条件 → 规则/模型/站点版本 → 证书 → 趋势引用 |
| 观测档案 | 类型/站点/编号检索，原始载荷、哈希、修订历史、载荷修订 |
| 判读冲突 | 未决冲突的来源、置信度、处置记录 |
| 样区规则册与模型 | 规则册四类门槛、路线段、海拔带；模型校准集、权重、阈值复核 |

## 8. 主要 API

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/auth/login` | 登录，返回 HMAC 签名令牌 |
| GET | `/api/runs` | 运行列表（含状态计数、未决冲突数） |
| POST | `/api/runs` | 按规则册/模型/站点组装新运行 |
| GET | `/api/runs/{id}/overview` | 总览：矩阵、门槛分布、对照行、活动 |
| GET | `/api/runs/{id}/units` | 单元列表（可按站点/证书状态/门槛过滤） |
| GET | `/api/units/{id}` | 单元详情：门槛、证书、概率、证据、冲突、审计 |
| GET | `/api/units/{id}/trace` | 可回查的五段回溯链 |
| GET | `/api/units/{id}/records` | 单元引用的原始记录（含修订） |
| POST | `/api/units/{id}/trend-references` | 登记 `absence` / `trend` 引用（含用途校验） |
| POST | `/api/units/{id}/certificates/reissue` | 复审后重新签发证书 |
| GET/POST | `/api/records`、`/api/records/{id}/revisions` | 档案检索、载荷修订（哈希 + 修订号）；停机日志回传单元并标记趋势待重算 |
| POST | `/api/determinations`、`/api/determinations/{id}/revisions` | 判读新增/修订（触发复审） |
| POST | `/api/determinations/{id}/revoke` | 撤销判读（保留行、不再计入证据，触发复审与趋势待重算） |
| GET/POST | `/api/conflicts`、`/api/conflicts/{id}/resolve` | 冲突列表与处置 |
| GET/POST | `/api/trend-references`、`/api/trend-references/{id}/revoke` | 引用列表与撤回 |
| POST | `/api/probability/models/{id}/evaluate` | 概率复算（可选校准集偏移，只读不签署） |
| GET | `/api/probability/models/{id}/threshold-sensitivity` | 阈值敏感性 |
| GET/POST | `/api/annual-plans` | 年度调查计划（当季点位与角色、目标物种可调查时段） |
| GET/POST | `/api/trend-analyses` | 趋势分析列表 / 新建并完成首次计算 |
| GET | `/api/trend-analyses/{id}` | 当前简报：全区结论、分层权重、不足以比较范围、独立观测 |
| GET | `/api/trend-analyses/{id}/units` | 单元级输入：纳入理由/排除原因、努力量、观测、权重、排除素材 |
| GET | `/api/trend-analyses/{id}/briefs`、`.../briefs/{version}` | 简报历史与冻结输入复现 |
| POST | `/api/trend-analyses/{id}/recompute` | 按当前证据重算（分子分母同步），生成分解 |
| POST | `/api/stations/{id}/migration-correction` | 纠正点位迁移生效日期（回传覆盖因子） |
| GET | `/api/rulebooks`、`/api/models`、`/api/stations`、`/api/zones`、`/api/audit` | 规则册、模型、站点、样区、审计 |

## 9. 目录结构

```
backend/
  app/
    main.py            # FastAPI 应用与路由装配
    models.py          # 23 张表（档案、修订、判读、规则册、单元、门槛、证书、冲突、模型、引用、审计、年度计划、趋势分析与简报）
    coverage.py        # 覆盖组装器：四类门槛判定与证据留存
    certificates.py    # 有效性裁定：状态、用途、复审版本
    probability.py     # 检测概率模型（含门控特征与敏感区间）
    trends.py          # 趋势分析器：物种时段努力量、点段拆分、分层标准化、固定点序列、待重算传播与分解
    services.py        # 组装运行、记录/判读修订与撤销、引用、冲突处置、重签发、维护日志回传、迁点日期纠正
    seed.py            # 确定性种子数据（7 个验收场景 + 三年趋势验收数据）
    routers/           # auth / catalog / surveys / records / probability / trends
  tests/               # 21 个 pytest 用例
frontend/
  src/views/           # 10 个业务页面（含年度趋势对比列表与详情）
  src/components/      # 状态徽章、概率区间条、提示
docker-compose.yml     # db + backend + frontend 一键启动
```

## 10. 数据与合规说明

- 数据库中的 `ccdev` 账号仅用于隔离开发/测试，不作为生产配置。
- 所有时间以保护区当地时区（UTC+8）解释、UTC 存储；时间校准关系仅在有 `verified: true` 且落在
  有效区间内时才用于回算事件时间。
- 服务端不包含任何派工、预约、执法、捕捉或资源调度接口；测试 `test_service_emits_no_dispatch_actions`
  会校验 OpenAPI 路径与总览响应中不出现相关动作。
