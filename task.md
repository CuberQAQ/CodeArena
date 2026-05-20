# Code Arena - 项目任务清单

> 需求文档详见 [requirements.md](requirements.md)
> 阶段 1-14 全部 🟢 已完成（2025-05-19 ~ 2026-05-20），归档至 [docs/archive/task_v1.0.md](docs/archive/task_v1.0.md)
> 阶段 15-27 全部 🟢 已完成（2026-05-20 ~ 2026-05-21），详见 V1.1 任务清单。
> 以下为 V1.2 需求更新任务（用户体验增强 + 时间 Elo 模型，2026-05-21）。

---

## 阶段 28: 核心基础设施 — 提交追踪改造 + 时间 Elo 模型

### Task 28.1: CF API 提交追踪改造 (FR-15)
**状态**: 🔵 待开发
**优先级**: P0
**依赖**: 无

#### 任务描述
将提交状态追踪从"手动报告 + CF 轮询"改为"完全依赖 CF API 自动追踪"。废弃前端所有手动"已解决/未解决"按钮，所有 verdict、WA/TLE 次数、提交时间戳从 CF API `user.status` 自动采集。

#### 需求规格 (requirements.md FR-15)
- FR-15.1: 完全移除前端手动"已解决/未解决"按钮
- FR-15.2: 自动追踪流程（开始做题记录时间 → 用户 CF 提交 → 后台轮询匹配）
- FR-15.3: 精确数据采集（WA/TLE 次数、用时全部从 CF API 获取）

#### 需要修改的文件

**后端**:
- `backend/app/services/submission_tracker.py` — 核心改造：
  - `_settle_matched()` 中 `attempts=1, error_count=0` 的硬编码改为从 CF API 计算真实值
  - 新增方法：根据 tracking 记录的 problem_id + 时间窗口，调用 `CFApiService.get_user_status()` 获取该题所有提交，统计 WA/TLE 次数
  - `time_spent` 计算改为：最后一次 AC 提交的 `creationTimeSeconds` - `tracking.expected_at`（而非 `matched_at - expected_at`）
  - 将真实 `attempts` 和 `error_count` 传递给各 service 的 submit 方法
- `backend/app/services/cf_api_service.py` — 可能需要新增方法支持按题目筛选提交

**前端**:
- `frontend/src/pages/challenge/PvEChallengePage.tsx` — 移除"已解决/未解决"手动按钮（行 228-243），改为自动等待 CF API 结果的状态展示
- `frontend/src/pages/ChallengePage.tsx` — 移除"Report Your Result"面板中的手动按钮（行 405-449），改为自动等待状态
- `frontend/src/pages/TrainingDetailPage.tsx` — 移除"Report"按钮和内联提交面板（行 370-425），改为自动等待
- `frontend/src/pages/ContestDetailPage.tsx` — 移除"Report"按钮和内联提交面板（行 447-485），改为自动等待

#### 调用方清单
- 所有 4 个模式的 submit API endpoint（后端）的调用方式需适配：接收来自 submission_tracker 的自动结算数据而非前端手动参数
- 前端 4 个做题页面的 UI 交互流程

#### 反向集成清单
- CF API `user.status` 的调用频率需合理控制（受 2s/请求限制）
- 代币奖励计算依赖准确的 WA/TLE 次数
- PP 的 `f(wa, t)` 依赖准确的 wa_count 和 time_spent

#### 关键实现细节
1. **提交匹配增强**：当前 `submission_tracker.py` 通过 problem_id + 时间窗口匹配单条提交。改造后需获取时间窗口内该题的所有提交，统计非 AC verdict 数量作为 `error_count`
2. **前端状态展示**：移除手动按钮后，前端需展示"等待 CF 结果"的加载状态，并在收到结果后自动跳转到结算页面
3. **开始时间精确化**：`tracking.expected_at` 即为用户点击"开始做题"的时间，用作 solve_time 的起点
4. **超时处理**：保留现有的 2 小时超时机制

#### 测试要点
- [ ] **WA 计数准确**: 用户提交 3 次 WA 后 AC → error_count=3, attempts=4
- [ ] **TLE 计数准确**: 用户提交 2 次 TLE 后 AC → error_count=2
- [ ] **用时计算**: solve_time = AC提交时间 - 开始时间，精确到秒
- [ ] **自动结算**: 后台轮询匹配到最终 verdict 后自动触发结算，无需用户操作
- [ ] **手动按钮移除**: 4 个模式页面均无"已解决/未解决"按钮
- [ ] **等待状态展示**: 前端展示加载/等待状态，有轮询状态指示
- [ ] **S-value 正确**: error_count 准确后 S-value 计算正确（1.0 / max(0.7, 1-0.05×N)）
- [ ] **PP 正确**: wa_count 准确后 PP 的 f(wa,t) 计算正确
- [ ] **现有结算不破坏**: PvE/PvP/训练/比赛的结算逻辑不因数据来源变化而改变

---

### Task 28.2: Per-problem 期望时间模型 (FR-16.2, 16.3, 16.5-16.7)
**状态**: 🔵 待开发
**优先级**: P0
**依赖**: 无

#### 任务描述
实现 per-problem 实时期望时间计算模型。结算时从 CF API 拉取该题所属比赛的提交数据，按解题者 rating 分桶统计中位数解题时间，作为该题对特定 rating 用户的期望用时。

#### 需求规格 (requirements.md 3.6.2-3.6.6)
- 实时计算，不使用缓存
- 数据来源：`contest.status` + `contest.ratingChanges`
- 专注时间剥离：仅保留按顺序解题数据
- Rating 分桶：每 200 分一档
- 兜底：无比赛数据时退回 rating 维度通用模型

#### 需要修改的文件
- `backend/app/services/elo_service.py` — 新增 `TimeFactorService` 类：
  - `calculate_expected_time(db, problem_id, problem_rating, user_rating) -> float`：返回 T_expected（分钟）
  - `_fetch_contest_submissions(contest_id) -> list`：调用 CF API 获取比赛提交
  - `_fetch_rating_changes(contest_id) -> dict`：获取参与者 rating
  - `_calculate_focused_times(submissions, rating_changes) -> dict`：按解题者 rating 分桶，计算中位专注时间
  - `_fallback_expected_time(problem_rating, user_rating) -> float`：兜底通用模型
- `backend/app/services/cf_api_service.py` — 确保支持 `contest.status` 和 `contest.ratingChanges` API 调用（可能已存在）

#### 调用方清单
- Task 28.3 会在所有模式的结算中调用 `TimeFactorService.calculate_expected_time()`
- Task 30.3 时间轴组件会通过前端 API 调用获取时间预测数据

#### 关键实现细节
1. **专注时间剥离算法**：对每个解题者，按 `relativeTimeSeconds` 排序其 AC 提交，`focused_time(C) = AC_time(C) - AC_time(prev)`。只保留顺序解题的数据点（即只保留 AC_time 递增的序列）。跳题情况（如先 AC C 再 AC B）中 B 的数据不纳入。
2. **分桶策略**：按解题者当时的 rating（`ratingChanges` 中 `oldRating` 到 `newRating` 的均值或取 `oldRating`），每 200 分一档（如 1200-1399, 1400-1599 等）。每桶至少需要 5 个数据点才可信。
3. **T_expected 计算**：用户 rating 所在桶的中位数专注时间。若该桶数据不足，向相邻桶扩展。
4. **兜底通用模型**：若无比赛数据，使用简单公式如 `T_expected = 10 + (problem_rating - 800) / 50`（分钟），可根据实际数据调整。
5. **CF API 调用优化**：需要知道题目的 `contestId` 才能调用 `contest.status`。需从 problem_id 映射到 contestId（现有 `cf_api_service.py` 的题库数据中包含此信息）。单次结算最多调用 2 次 CF API（`contest.status` + `contest.ratingChanges`），需考虑 2s 限速。

#### 测试要点
- [ ] **顺序解题时间剥离**: 解题者 AC A(10min) B(25min) C(50min) → focused_time(B)=15, focused_time(C)=25
- [ ] **非顺序数据剔除**: 解题者先 AC C(50min) 再 AC B(70min) → B 的数据不纳入
- [ ] **Rating 分桶正确**: 解题者 rating 1350 → 归入 1200-1399 桶
- [ ] **中位数计算**: 桶内数据 [10, 15, 18, 25, 100] → 中位数 18
- [ ] **数据不足扩展**: 桶内 < 5 个数据点 → 向相邻桶扩展
- [ ] **兜底模型**: 无比赛数据的题目 → 使用 rating 通用公式
- [ ] **API 限速处理**: 连续结算不触发 CF 限速

---

### Task 28.3: 时间因子集成到所有模式 Elo 结算 (FR-16.4)
**状态**: 🔵 待开发
**优先级**: P0
**依赖**: Task 28.2

#### 任务描述
将时间因子 (time_factor) 集成到所有 4 种模式的 Elo 结算中。修改 requirements.md 3.3 节的 Elo 公式为 `R_new = R_old + K × (S - P(AC)) × hint_attenuation × time_factor`。

#### 需求规格 (requirements.md 3.6.4)
- `effective_time = solve_time + WA_count × 20`（罚时 20min/WA）
- `time_factor = T_expected / max(T_effective, T_expected)`，范围 [0.5, 1.5]
- S=0 时不乘 time_factor
- 对所有模式一视同仁，同步应用于 M-Elo

#### 需要修改的文件
- `backend/app/services/elo_service.py` — 新增 `calculate_time_factor(effective_time, expected_time, s_value) -> float`
- `backend/app/services/pve_challenge_service.py` — 结算逻辑（行 172）加入 time_factor
- `backend/app/services/challenge_service.py` — `process_challenge_result` 和 inline 结算加入 time_factor
- `backend/app/services/training_service.py` — `_calculate_training_elo`（行 1201）加入 time_factor
- `backend/app/services/contest_service.py` — `_settle_with_pr`（行 971）加入 time_factor

#### 调用方清单
- 所有 4 个模式 service 的结算函数
- submission_tracker 自动结算路径

#### 反向集成清单
- M-Elo 更新也需要乘 time_factor（在 Task 29.1 实现时集成）
- 前端结算结果展示需包含 time_factor 信息

#### 关键实现细节
1. **effective_time 计算**：`solve_time`（分钟）+ `error_count × 20`。其中 `error_count` 来自 Task 28.1 的改造后的准确数据。
2. **time_factor 应用条件**：仅当 S > 0（即成功 AC）时计算并应用 time_factor。S=0 时 time_factor = 1.0（不生效）。
3. **与 hint_attenuation 的关系**：两者独立叠加。最终 Elo 变化 = `K × (S - P(AC)) × hint_attenuation × time_factor`。
4. **各模式适配点**：
   - PvE: 行 172 的 `new_elo = round(user.elo + k_factor * (s_value - expected_score))` → 加入 `* hint_attenuation * time_factor`
   - PvP: `process_challenge_result` 中每个玩家的 Elo 变化
   - 训练: 行 1201 的 `global_elo_change = round(k_train * (s_value - global_expected) * global_coeff)` → 加入 `* hint_attenuation * time_factor`
   - 比赛: 行 971 的 `elo_change = round(k * (pr - elo_before) / 400)` → 加入 `* time_factor`（比赛不使用 hint_attenuation 机制）
5. **EloHistory 记录**：在 elo_history 中记录 time_factor 值，便于审计和调试

#### 测试要点
- [ ] **快速解题加成**: effective_time < T_expected → time_factor > 1 → Elo 额外加成
- [ ] **慢速解题削弱**: effective_time > T_expected → time_factor < 1 → Elo 削弱
- [ ] **上限 1.5**: 即使极快解题 time_factor 不超过 1.5
- [ ] **下限 0.5**: 即使极慢解题 time_factor 不低于 0.5
- [ ] **S=0 不乘**: 失败/退出时 time_factor = 1.0，不生效
- [ ] **罚时计算**: 3 次 WA → effective_time 增加 60min
- [ ] **提示衰减叠加**: 使用 Level 2 提示 + 快速解题 → ×0.50 × 1.3 = ×0.65
- [ ] **PvE/PvP/训练/比赛全模式**: 各模式结算均正确应用 time_factor

---

### Task 28.4: 前端提交流程重构 — 自动追踪 UI (FR-15.1)
**状态**: 🔵 待开发
**优先级**: P1
**依赖**: Task 28.1

#### 任务描述
重构前端 4 个做题页面的 UI 流程，移除手动报告按钮，改为展示"等待 CF 结果"的自动追踪状态。新增轮询状态指示器和解题时间轴占位。

#### 需要修改的文件
- `frontend/src/pages/challenge/PvEChallengePage.tsx` — 移除手动按钮，新增自动追踪状态 UI
- `frontend/src/pages/ChallengePage.tsx` — 移除"Report Your Result"面板，新增自动追踪状态
- `frontend/src/pages/TrainingDetailPage.tsx` — 移除"Report"按钮和内联提交面板，新增自动追踪
- `frontend/src/pages/ContestDetailPage.tsx` — 移除"Report"按钮和内联提交面板，新增自动追踪

#### 关键实现细节
1. **自动追踪流程 UI**：用户提交代码后，前端开始轮询 `/submission-tracking/status`，展示加载状态。匹配到结果后自动触发结算展示。
2. **结算展示增强**：结算结果中新增 time_factor 相关信息的展示（如"快速解题加成 ×1.3"）。
3. **保持现有流程**：用户仍通过 CF 页面（iframe 或新标签页）查看题目和提交代码，只是不再需要回来手动报告结果。

#### 测试要点
- [ ] **4 个模式页面无手动按钮**: PvE/PvP/训练/比赛页面均无"已解决/未解决"按钮
- [ ] **自动追踪状态展示**: 提交后展示加载状态和轮询指示
- [ ] **结算自动触发**: CF API 匹配到结果后自动展示结算（Elo 变化、PP 等）
- [ ] **超时处理**: 长时间未匹配到结果时的提示

---

## 阶段 29: M-Elo 覆盖 + 自由选题模式

### Task 29.1: M-Elo 全模式覆盖 (FR-9)
**状态**: 🔵 待开发
**优先级**: P0
**依赖**: Task 28.3

#### 任务描述
将 M-Elo 更新从仅训练模式扩展到所有模式（PvP、PvE、自由选题、比赛）。所有模式做完题后，提取题目所有 CF tag，对每个 tag 执行 M-Elo 更新。Learning Shield 跨模式生效。

#### 需求规格 (requirements.md FR-9)
- FR-9.1: 所有模式提取题目 CF tag，更新 M-Elo
- FR-9.2: 训练保留权重极化，其他模式普通系数
- FR-9.3: Learning Shield 跨模式生效
- FR-9.4: 前端雷达图等联动更新

#### 需要修改的文件
- `backend/app/services/pve_challenge_service.py` — 结算时新增 M-Elo 更新：提取 `session.problem_tags`（JSON 字段），对每个 tag 调用 `MEloService.update_melo()`，权重 ×1.0
- `backend/app/services/challenge_service.py` — PvP 结算时新增 M-Elo 更新：需获取题目 tags（当前 `challenge_session` 不存储 tags，需补充），对每个 tag 更新双方 M-Elo
- `backend/app/services/contest_service.py` — 比赛结算时新增 M-Elo 更新：获取每道题 tags，更新 M-Elo
- `backend/app/services/melo_service.py` — 确认 `update_melo()` 方法支持通用调用（当前仅被 training 调用），新增 `batch_update_melo_for_problem(db, user_id, problem_tags, elo_change, coefficient)` 便利方法
- `backend/app/models/challenge_session.py` — 新增 `problem_tags` JSONB 字段（存储题目标签，PvP 模式需要）
- `frontend/src/components/charts/RadarChart.tsx` — 确认数据源自动更新（当前从 API 获取，无需前端改动）
- `frontend/src/pages/TrainingPage.tsx` — 确认训练卡片 M-Elo 数据更新

#### 调用方清单
- PvE 结算: `pve_challenge_service.py` `submit_result()` 和 `quit_session()`
- PvP 结算: `challenge_service.py` `_settle_challenge()`
- 训练结算: `training_service.py` `_calculate_training_elo()` — 已有 M-Elo 更新，确认不变
- 比赛结算: `contest_service.py` `_settle_with_pr()` 和每题 submit

#### 反向集成清单
- M-Elo 更新需应用 time_factor（来自 Task 28.3）
- 分技能奖牌（FR-10.3）基于 M-Elo 实时计算，数据变更后奖牌自动更新
- 雷达图、训练页面需展示最新 M-Elo

#### 关键实现细节
1. **题目 tags 获取**：PvE 已有 `session.problem_tags` 字段。PvP 和比赛需在创建 session 时存储题目 tags。
2. **M-Elo 更新公式**：`M-Elo_new = M-Elo_old + K × (S - P(AC_melo)) × time_factor × hint_attenuation × coefficient`。P(AC) 基于 tag M-Elo 和 problem_rating 计算（非 Global Elo）。
3. **多 tag 处理**：一道题可能有多个 tag（如 dp + greedy），对每个 tag 独立更新 M-Elo。
4. **Learning Shield**：调用 `MEloService.is_shield_active()` 检查，shield 激活时跳过 Elo 扣除（包含 Global Elo 和 M-Elo）。首次 AC 时调用 `MEloService.deactivate_shield()`。
5. **训练模式不变**：训练模式保留现有的 `_calculate_training_elo` 逻辑（Global ×0.5, M-Elo ×2.0），不修改。

#### 测试要点
- [ ] **PvE M-Elo 更新**: PvE 做 DP 题 → DP tag M-Elo 变化
- [ ] **PvP M-Elo 更新**: PvP 双方做 DP 题 → 双方 DP M-Elo 变化
- [ ] **比赛 M-Elo 更新**: 比赛做多道题 → 各 tag M-Elo 变化
- [ ] **多 tag 独立更新**: 一道 dp+greedy 题 → dp 和 greedy 两个 M-Elo 各自更新
- [ ] **Shield 跨模式**: PvE 中首次 AC dp tag → shield 解除 → 之后 PvP 中 dp 失败开始扣 M-Elo
- [ ] **训练系数不变**: 训练模式仍使用 Global ×0.5, M-Elo ×2.0
- [ ] **其他模式系数**: PvE/PvP/比赛使用 ×1.0
- [ ] **雷达图联动**: 做完题后雷达图数据更新

---

### Task 29.2: 自由选题后端服务 + API (FR-8.2, 8.3, 8.5)
**状态**: 🔵 待开发
**优先级**: P1
**依赖**: Task 29.1

#### 任务描述
实现自由选题模式的后端服务，包括手动筛选选题、自适应推荐选题、结算逻辑。

#### 需求规格 (requirements.md FR-8)
- FR-8.2: 手动筛选（rating 范围 + 标签多选）
- FR-8.3: 自适应推荐（加权随机模型）
- FR-8.5: 结算（Elo + M-Elo + PP + 代币，同 PvE，无训练极化）

#### 需要修改的文件
- `backend/app/services/free_play_service.py` — **新建**，Free Play 核心服务：
  - `search_problems(db, user_id, min_rating, max_rating, tags) -> Problem`：手动筛选
  - `recommend_problem(db, user_id) -> Problem`：自适应推荐（加权随机选 tag → 按 M-Elo 选难度范围）
  - `start_session(db, user, problem_id) -> FreePlaySession`
  - `submit_result(db, user, session_id, ...) -> dict`：结算（复用 PvE 结算逻辑但无盲盒）
  - `quit_session(db, user, session_id)`
- `backend/app/models/free_play_session.py` — **新建**，数据模型
- `backend/app/api/v1/free_play.py` — **新建**，API 路由
- `backend/app/api/v1/router.py` — 注册 free_play router
- `backend/migrations/versions/` — 新增 migration

#### 反向集成清单
- 结算需调用 M-Elo 更新（Task 29.1 的 `batch_update_melo_for_problem`）
- 结算需应用 time_factor（Task 28.3）
- 结算需调用 PP 服务、代币服务、提示服务
- 解题时间轴（Task 30.3）需获取 session 数据

#### 关键实现细节
1. **手动筛选**：调用 `CFApiService` 获取题库，按 rating 范围和 tags 过滤，排除用户已做题（从 `pp_records` 查询），随机选一道。
2. **自适应推荐**：获取用户所有 tag 的 M-Elo，按 `w(tag) = max_melo - melo(tag) + baseline`（baseline 如 100）计算权重，加权随机选 tag。在该 tag 的 [M-Elo-100, M-Elo+200] 范围内选未做题。无合适题则重新抽 tag（最多 3 轮）。
3. **结算**：与 PvE 完全一致（S-value、越级奖励、提示衰减），但使用普通系数（无训练极化）。调用 `batch_update_melo_for_problem` 更新 M-Elo。
4. **FreePlaySession 模型**：类似 PvEChallengeSession，含 problem_id, problem_rating, problem_tags, status, error_count, time_spent, hints_used, elo_change, pp_change 等。

#### 测试要点
- [ ] **手动筛选**: rating [1400,1600] + tag dp → 返回符合条件的题
- [ ] **无匹配**: rating [3500,3600] → 提示无合适题目
- [ ] **自适应推荐**: 用户 DP M-Elo 1300（最低） → DP tag 被选中的概率最高
- [ ] **自适应不强标签也被选**: 高 M-Elo tag 也有非零概率被选中
- [ ] **结算 Elo**: 自由选题 AC → Elo 变化正确
- [ ] **结算 M-Elo**: AC 后对应 tag M-Elo 更新
- [ ] **结算 PP/代币**: PP 和代币计算正确
- [ ] **越级奖励**: 高难度题 AC 触发越级 PP 加成

---

### Task 29.3: 自由选题前端页面 (FR-8.1, 8.4)
**状态**: 🔵 待开发
**优先级**: P1
**依赖**: Task 29.2, Task 29.4

#### 任务描述
实现自由选题模式的前端页面，包括筛选/推荐界面、做题界面（iframe + 时间轴）、结算展示。

#### 需要修改的文件
- `frontend/src/pages/FreePlayPage.tsx` — **新建**，自由选题页面
- `frontend/src/pages/FreePlaySessionPage.tsx` — **新建**（或合并到 FreePlayPage），做题中页面
- `frontend/src/services/api.ts` — 新增 Free Play API 调用
- `frontend/src/locales/en/` + `frontend/src/locales/zh/` — 新增 free_play 翻译命名空间
- `frontend/src/App.tsx` 或路由配置 — 注册 `/free-play` 路由
- 导航栏配置 — 新增 Free Play 入口

#### 关键实现细节
1. **筛选界面**：rating 范围双滑块 + 12 个预设标签 chip（多选）+ "更多标签"按钮弹出全量 CF 标签弹窗（可搜索）+ "自适应推荐"按钮。
2. **做题界面**：iframe 嵌入 CF 题目页 + 侧边时间轴（Task 30.3 组件）+ 计时器 + 自动追踪状态。
3. **结算展示**：复用 PvE 的结算动画（EloChange、CoinAnimation、AchievementPopup 等）。

#### 测试要点
- [ ] **筛选 UI**: rating 滑块和标签选择正常工作
- [ ] **更多标签弹窗**: 弹出全量 CF 标签列表，可搜索选择
- [ ] **自适应推荐**: 点击后自动推荐一道题
- [ ] **iframe 展示**: CF 题目页面在 iframe 中正常加载
- [ ] **时间轴展示**: 侧边展示实时 Elo 预测
- [ ] **i18n**: 中英文切换正常

---

### Task 29.4: 站内看题 iframe 组件 (FR-14)
**状态**: 🔵 待开发
**优先级**: P1
**依赖**: 无

#### 任务描述
实现通用的 iframe 嵌入组件，用于非盲盒模式下的站内看题。同时为盲盒模式提供"在新标签页打开"链接。

#### 需求规格 (requirements.md FR-14)
- FR-14.1: 非盲盒模式（自由选题、训练、比赛）通过 iframe 嵌入 CF 题目页
- FR-14.2: 盲盒模式（PvE）提供"在新标签页打开"链接

#### 需要修改的文件
- `frontend/src/components/ProblemViewer.tsx` — **新建**，通用题目查看组件：
  - Props: `contestId`, `index`, `blindBox: boolean`
  - 非盲盒：渲染 iframe `src=https://codeforces.com/problemset/problem/{contestId}/{index}`
  - 盲盒：渲染"在新标签页打开题目"链接
- `frontend/src/pages/FreePlaySessionPage.tsx` — 使用 `<ProblemViewer blindBox={false} />`
- `frontend/src/pages/TrainingDetailPage.tsx` — 使用 `<ProblemViewer blindBox={false} />`
- `frontend/src/pages/ContestDetailPage.tsx` — 使用 `<ProblemViewer blindBox={false} />`
- `frontend/src/pages/challenge/PvEChallengePage.tsx` — 使用 `<ProblemViewer blindBox={true} />`

#### 测试要点
- [ ] **iframe 加载**: CF 题目页在 iframe 中正常渲染
- [ ] **盲盒模式**: 不显示 iframe，显示外跳链接
- [ ] **加载状态**: iframe 加载中展示 loading 指示
- [ ] **加载失败**: iframe 加载失败时的错误处理

---

## 阶段 30: XCPC 奖牌系统 + 解题时间轴

### Task 30.1: 奖牌系统后端 (FR-10.1-10.5)
**状态**: 🔵 待开发
**优先级**: P1
**依赖**: Task 29.1（M-Elo 全模式覆盖后分技能奖牌才有意义）

#### 任务描述
实现 XCPC 奖牌制的后端计算逻辑、数据库存储和 API。

#### 需求规格 (requirements.md FR-10)
- FR-10.1: 奖牌等级映射表
- FR-10.2: 整体奖牌（Global Elo → 实时计算）
- FR-10.3: 分技能奖牌（各 tag M-Elo → 实时计算）
- FR-10.4: 比赛赛后发牌（PR → 对照映射表，与组别无关）
- FR-10.5: 比赛奖牌永久记录

#### 需要修改的文件
- `backend/app/services/medal_service.py` — **新建**，奖牌服务：
  - `MEDAL_TIERS` 常量：映射表定义
  - `calculate_overall_medal(elo) -> {level, type}`：整体奖牌
  - `calculate_skill_medal(melo) -> {level, type}`：分技能奖牌
  - `award_contest_medal(db, user_id, contest_session_id, pr) -> ContestMedal|None`：比赛发牌
  - `get_user_medal_stats(db, user_id) -> dict`：奖牌柜统计
- `backend/app/models/contest_medal.py` — **新建**，比赛奖牌记录模型
- `backend/app/models/user_settings.py` — **新建**，用户设置模型（display_mode: medal/cf_tier）
- `backend/app/services/contest_service.py` — `_settle_with_pr()` 中结算后调用 `award_contest_medal`。注意 `_settle_with_pr` 有多个调用路径（正常结算 + 超时结算），所有路径均需触发发牌。建议将发牌逻辑封装在 `_settle_with_pr` 方法内部（return 之前），避免遗漏。
- `backend/app/api/v1/medal.py` — **新建**，奖牌 API（获取奖牌、奖牌统计）
- `backend/app/api/v1/auth.py` — 新增用户设置 API（切换展示模式）
- `backend/app/api/v1/router.py` — 注册 medal router
- `backend/migrations/versions/` — 新增 migration（contest_medal 表、user_settings 表、User 表新增 avatar 相关字段）

#### 调用方清单
- `contest_service.py` `_settle_with_pr()` — 比赛结算后调用发牌
- 前端 Dashboard、Profile、训练页面 — 通过 API 获取奖牌数据
- 前端设置页面 — 切换展示模式

#### 反向集成清单
- 整体奖牌依赖 Global Elo（实时计算，无需持久化）
- 分技能奖牌依赖各 tag M-Elo（实时计算，Task 29.1 确保数据准确）
- 比赛奖牌依赖 PR（比赛结算时已有）
- 展示体系切换依赖 user_settings

#### 关键实现细节
1. **映射表**：
   ```
   MEDAL_TIERS = [
     {"level": "world_finals", "gold": 2800, "silver": 2600, "bronze": 2400},
     {"level": "ec_final", "gold": 2600, "silver": 2400, "bronze": 2200},
     {"level": "regional", "gold": 2200, "silver": 2000, "bronze": 1800},
     {"level": "provincial", "gold": 1600, "silver": 1400, "bronze": 1200},
   ]
   ```
   注意：后端仅返回 `level` key（如 "regional"），前端通过 i18n 翻译为"区域赛"/"Regional"。
2. **calculate_overall_medal(rating)**：从高到低遍历 MEDAL_TIERS，找到第一个满足条件的（rating ≥ gold → 金，≥ silver → 银，≥ bronze → 铜）。返回 `{level: "regional", type: "gold"}`。rating < 1200 返回 `{level: "unranked"}`。
3. **award_contest_medal**：计算 PR 对应的奖牌，若获得则插入 `contest_medal` 记录。同一比赛不重复发牌。
4. **get_user_medal_stats**：按 level 分组统计各牌获得次数，如 `{"regional": {"gold": 3, "silver": 1}, "provincial": {"gold": 2}}`。

#### 测试要点
- [ ] **整体奖牌映射**: Elo 2100 → 区域赛银牌；Elo 1500 → 省赛银牌；Elo 1100 → 未入段
- [ ] **分技能奖牌映射**: M-Elo(DP)=1800 → 区域赛铜牌
- [ ] **比赛发牌 PR 对照**: PR 2200 → 区域赛金牌（不论 Beginner/Advanced/Master）
- [ ] **比赛不发牌**: PR 1100 → 无牌
- [ ] **奖牌永久记录**: 同一比赛不重复发，历史记录持久化
- [ ] **奖牌统计**: 多次比赛后统计正确
- [ ] **升降级实时**: Elo 变动后整体奖牌自动更新

---

### Task 30.2: 奖牌系统前端展示 + 设置切换 (FR-10.6, 10.7)
**状态**: 🔵 待开发
**优先级**: P1
**依赖**: Task 30.1

#### 任务描述
实现奖牌系统的前端展示，包括 Dashboard 大号牌面、Profile 奖牌柜 + 技能勋章墙、训练页面牌面、排行榜牌面，以及设置中的展示体系切换。

#### 需求规格 (requirements.md FR-10.6, 10.7)
- FR-10.6: 设置中切换奖牌制/CF 段位制，默认奖牌制
- FR-10.7: 奖牌文案中英文

#### 需要修改的文件
- `frontend/src/components/medal/` — **新建目录**：
  - `MedalBadge.tsx` — 奖牌徽章组件（金/银/铜 + 级别名称）
  - `MedalCabinet.tsx` — 奖牌柜组件（按级别分组统计）
  - `SkillMedalWall.tsx` — 技能勋章墙（12 个标签各自牌面）
- `frontend/src/pages/DashboardPage.tsx` — 替换现有 Elo 卡片为奖牌展示（根据用户 display_mode 设置）
- `frontend/src/pages/ProfilePage.tsx` — 新增奖牌柜 + 技能勋章墙
- `frontend/src/pages/TrainingPage.tsx` — 每个主题卡片新增牌面显示
- `frontend/src/pages/LeaderboardPage.tsx` — 排行榜展示奖牌/段位（根据 display_mode）
- `frontend/src/pages/SettingsPage.tsx` — **新建或扩展**，展示模式切换
- `frontend/src/locales/en/` + `frontend/src/locales/zh/` — 新增 medal 翻译命名空间

#### 测试要点
- [ ] **Dashboard 奖牌展示**: 默认展示奖牌，切换后展示 CF 段位
- [ ] **Profile 奖牌柜**: 按级别分组展示比赛奖牌统计
- [ ] **Profile 技能勋章墙**: 12 个标签各自牌面
- [ ] **训练页面牌面**: 每个主题卡片显示牌面
- [ ] **设置切换**: 切换后所有页面同步更新
- [ ] **i18n**: 奖牌文案中英文正确

---

### Task 30.3: 解题时间轴组件 (FR-17)
**状态**: 🔵 待开发
**优先级**: P2
**依赖**: Task 28.2（per-problem 期望时间模型）

#### 任务描述
实现做题过程中的实时 Elo 预测时间轴组件。根据 per-problem 期望时间模型，动态展示不同用时对应的预期 Elo 变化。

#### 需求规格 (requirements.md FR-17)
- FR-17.1: 实时 Elo 预测时间轴
- FR-17.2: 每分钟动态更新
- FR-17.3: PvE/自由选题/PvP 必须展示，训练/比赛可选

#### 需要修改的文件
- `frontend/src/components/SolvingTimeline.tsx` — **新建**，时间轴组件
- `backend/app/api/v1/free_play.py` 或独立路由 — 新增 API：`GET /time-factor-prediction?problem_id=&user_elo=` → 返回不同时间点的 time_factor 和预测 Elo 变化
- `frontend/src/pages/FreePlaySessionPage.tsx` — 嵌入时间轴
- `frontend/src/pages/challenge/PvEChallengePage.tsx` — 嵌入时间轴
- `frontend/src/pages/ChallengePage.tsx` — 嵌入时间轴

#### 关键实现细节
1. **后端 API**：返回一组时间点（如 5min, 10min, 15min, 20min, 30min, 45min, 60min）对应的 time_factor 和预测 Elo 变化。前端每分钟请求一次更新"当前状态"标记位置。
2. **前端组件**：竖向时间轴，每个节点显示用时和预测 Elo 变化（绿色正/红色负），当前时间位置高亮。

#### 测试要点
- [ ] **时间轴展示**: 不同时间点对应的 Elo 变化正确显示
- [ ] **动态更新**: 每分钟当前标记后移
- [ ] **T_expected 标注**: 期望用时位置特殊标注
- [ ] **API 数据正确**: 后端返回的 time_factor 与结算时使用的一致

---

## 阶段 31: 用户个性化 — 头像 + 个人卡片 + 签到

### Task 31.1: 头像上传系统 (FR-11)
**状态**: 🔵 待开发
**优先级**: P2
**依赖**: 无

#### 任务描述
实现用户头像本地上传、服务端存储、全站展示功能。

#### 需求规格 (requirements.md FR-11)
- FR-11.1: 本地上传（JPG/PNG, ≤2MB, 自动裁剪正方形）
- FR-11.2: Dashboard/Profile/排行榜/比赛排行榜统一展示

#### 需要修改的文件
- `backend/app/api/v1/auth.py` — 新增 `POST /avatar` 上传接口 + `GET /avatar/{user_id}` 获取接口
- `backend/app/models/user.py` — 新增 `avatar_path` 字段
- `backend/app/services/auth_service.py` — 头像上传逻辑（文件存储、裁剪）
- `backend/migrations/versions/` — User 表新增 avatar_path
- `frontend/src/components/Avatar.tsx` — **新建**，通用头像组件（含默认占位图）
- `frontend/src/pages/ProfilePage.tsx` — 新增头像上传/修改入口
- `frontend/src/pages/DashboardPage.tsx` — 使用 Avatar 组件
- `frontend/src/pages/LeaderboardPage.tsx` — 使用 Avatar 组件
- `frontend/src/pages/ContestDetailPage.tsx` — 比赛排行榜使用 Avatar 组件
- 前端静态资源 — 默认头像占位图

#### 测试要点
- [ ] **上传成功**: JPG/PNG ≤2MB 上传成功
- [ ] **文件过大**: >2MB 返回错误
- [ ] **自动裁剪**: 非正方形图片裁剪为正方形
- [ ] **全站展示**: 所有展示用户信息的位置显示头像
- [ ] **默认头像**: 未上传时显示默认占位图

---

### Task 31.2: 每日签到系统 (FR-13)
**状态**: 🔵 待开发
**优先级**: P2
**依赖**: 无

#### 任务描述
实现每日签到功能，包含代币奖励、连续签到加成、补签机制。

#### 需求规格 (requirements.md FR-13)
- FR-13.1: 基础 10 代币/天，连续 7 天 15 代币，连续 30 天 20 代币；每周补签 2 次（基础 10，不加成）
- FR-13.2: Dashboard 展示签到状态和连续天数
- FR-13.3: 签到代币受每日上限 120 约束

#### 需要修改的文件
- `backend/app/services/checkin_service.py` — **新建**，签到服务：
  - `check_in(db, user_id) -> dict`：签到逻辑（判断今日是否已签、连续天数、补签额度）
  - `get_checkin_status(db, user_id) -> dict`：获取签到状态
- `backend/app/models/check_in.py` — **新建**，签到记录模型
- `backend/app/api/v1/checkin.py` — **新建**，签到 API
- `backend/app/api/v1/router.py` — 注册 checkin router
- `backend/migrations/versions/` — 新增 check_in 表
- `frontend/src/pages/DashboardPage.tsx` — 新增签到区域（今日状态、连续天数、签到/补签按钮）
- `frontend/src/services/api.ts` — 新增签到 API 调用

#### 关键实现细节
1. **连续天数计算**：查询最近一次签到记录，若为昨天则连续天数+1，若为今天则已签，否则重置为1。
2. **补签判断**：查询本周（周一至周日）的补签次数，若 < 2 则允许补签。补签日期填充为昨天（即补签的是"昨天没签"）。
3. **代币发放**：根据连续天数确定奖励金额，调用 `EconomyService` 发放代币。代币受每日上限约束。

#### 测试要点
- [ ] **首次签到**: 连续天数=1，获得 10 代币
- [ ] **连续 7 天**: 获得 15 代币
- [ ] **连续 30 天**: 获得 20 代币
- [ ] **重复签到**: 同一天不能签两次
- [ ] **断签重置**: 隔一天未签 → 连续天数重置为 1
- [ ] **补签**: 补签后连续天数恢复 +1，但奖励为基础 10
- [ ] **补签限制**: 每周最多补签 2 次
- [ ] **代币上限**: 签到获得代币后不超每日 120 上限

---

### Task 31.3: 个人卡片导出 (FR-12)
**状态**: 🔵 待开发
**优先级**: P3
**依赖**: Task 31.1（头像）, Task 30.2（奖牌展示）

#### 任务描述
实现个人资料卡片导出为 PNG 图片的功能。包含头像、ID、奖牌/段位、Elo、PP 及排名、技能奖牌、解题数、签到天数。

#### 需求规格 (requirements.md FR-12)
- 导出为 PNG，客户端生成（html2canvas 或 canvas API）
- 内容：头像、用户名、CF Handle、奖牌/段位、Elo、PP+排名、技能奖牌概览、解题数、签到天数

#### 需要修改的文件
- `frontend/src/components/ProfileCard.tsx` — **新建**，个人卡片组件
- `frontend/src/pages/ProfilePage.tsx` — 新增"导出卡片"按钮
- 前端新增 html2canvas 依赖（`frontend/package.json`）

#### 测试要点
- [ ] **卡片内容完整**: 包含所有要求的字段
- [ ] **PNG 导出**: 点击按钮后下载 PNG 图片
- [ ] **展示模式适配**: 奖牌制/CF段位制下卡片内容不同
- [ ] **技能奖牌展示**: 12 个标签牌面正确显示

---

### Task 31.4: Profile 页 PP 排名展示
**状态**: 🔵 待开发
**优先级**: P2
**依赖**: Task 30.1（奖牌系统后端包含 PP 排名数据）

#### 任务描述
在 Profile 页展示用户的 PP 全球排名和"全球前 X%"数据。

#### 需要修改的文件
- `frontend/src/pages/ProfilePage.tsx` — 替换现有 PP Ranking 占位区域为真实数据展示
- `backend/app/api/v1/auth.py` 或 `leaderboard.py` — 新增 PP 排名查询 API

#### 测试要点
- [ ] **PP 排名展示**: Profile 页显示 PP 全球排名数字
- [ ] **全球前 X%**: 显示百分比
- [ ] **无排名处理**: 未上榜时的展示

---

## 阶段 32: CF 全球排名

### Task 32.1: CF 数据采样 + 回归管道 (FR-18.1, 18.2)
**状态**: 🔵 待开发
**优先级**: P2
**依赖**: 无

#### 任务描述
实现从 CF API 采样用户数据、计算等效 PP、拟合回归模型的批处理管道。

#### 需求规格 (requirements.md FR-18.1, 18.2)
- 分层抽样：每 200 rating 分档，每档约 100 人
- 样本用户计算等效 PP（使用 CodeArena PP 公式）
- 回归模型：CF rating → 估算 PP + 噪音

#### 需要修改的文件
- `backend/app/services/cf_ranking_service.py` — **新建**，CF 全球排名服务：
  - `run_sampling_pipeline(db)`：执行完整采样管道
  - `_sample_users(rated_list) -> list`：分层抽样
  - `_calculate_equivalent_pp(handle) -> float`：拉取提交记录，计算等效 PP
  - `_fit_regression_model(samples) -> function`：拟合回归
  - `_estimate_pp(cf_rating, model) -> float`：估算 PP + 噪音
- `backend/app/models/cf_sample_user.py` — **新建**，CF 抽样用户缓存模型
- `backend/app/api/v1/admin.py` — 新增手动触发采样管道的管理员 API
- `backend/migrations/versions/` — 新增 cf_sample_users 表

#### 关键实现细节
1. **采样管道流程**：`user.ratedList` → 按 rating 分层 → 每档随机 100 人 → 批量 `user.status` 获取提交 → 计算 PP → 存储。
2. **等效 PP 计算**：对每个样本用户的 AC 提交，提取 problem_rating、WA 次数（统计非 OK verdict）、时间（提交时间差），代入 `base(rating) × f(wa,t)` 公式，再按 0.95 衰减聚合。需注意 CF 没有精确的"开始做题时间"，需近似。
3. **回归模型**：简单的线性或多项式回归（如 `PP = a × rating + b` 或 `PP = a × rating^2 + b × rating + c`）。使用 numpy 或纯 Python 实现。
4. **噪音**：在回归估算 PP 上加 ±(0.5%~2%) 的随机噪音。
5. **API 限速**：1000-2000 个用户，每人一次 `user.status` 调用，2s/请求 → 约 1-2 小时完成。需支持中断恢复。
6. **月度刷新**：通过 cron 或管理员手动触发。清理旧数据，重新采样。

#### 测试要点
- [ ] **分层抽样正确**: 每个 rating 档有约 100 人
- [ ] **等效 PP 计算**: 对已知用户验证 PP 计算结果合理
- [ ] **回归模型拟合**: 回归曲线与样本数据拟合
- [ ] **噪音添加**: 同 rating 用户 PP 不完全相同
- [ ] **API 限速遵守**: 2s 间隔，不触发 CF 限速
- [ ] **中断恢复**: 管道中断后可从断点继续

---

### Task 32.2: 全球排名后端 API (FR-18.3)
**状态**: 🔵 待开发
**优先级**: P2
**依赖**: Task 32.1

#### 任务描述
实现全球排名的后端 API，支持混合排行和 CodeArena 专属排行，支持地区筛选。

#### 需要修改的文件
- `backend/app/api/v1/ranking.py` — **新建**，全球排名 API：
  - `GET /ranking/global`：混合排行（CA 用户精确 PP + CF 用户估算 PP）
  - `GET /ranking/arena`：CodeArena 专属排行
  - 参数：`sort_by` (pp/elo), `country`, `page`, `page_size`
- `backend/app/api/v1/router.py` — 注册 ranking router

#### 关键实现细节
1. **混合排行**：CodeArena 用户使用真实 PP（从 User 表），CF 抽样用户使用估算 PP（从 cf_sample_users 表），合并排序。CA 用户标记"认证"。
2. **地区筛选**：CF 用户的 country 从 `user.info` 获取并存储在 cf_sample_users 表中。CA 用户的 country 可从 Profile 或 CF Handle 关联获取。
3. **分页**：标准分页，默认每页 50 条。

#### 测试要点
- [ ] **混合排行**: CA 用户和 CF 用户正确混排
- [ ] **CA 专属排行**: 仅显示 CA 用户
- [ ] **地区筛选**: 按国家过滤正确
- [ ] **认证标记**: CA 用户有认证标识
- [ ] **分页**: 翻页正常

---

### Task 32.3: 全球排名前端 UI (FR-18.3, 18.4)
**状态**: 🔵 待开发
**优先级**: P2
**依赖**: Task 32.2

#### 任务描述
实现全球排名前端 UI，包含混合/专属双 tab、地区筛选、认证标记、全球前 X% 展示。

#### 需要修改的文件
- `frontend/src/pages/GlobalRankingPage.tsx` — **新建**（或扩展现有 LeaderboardPage）
- `frontend/src/services/api.ts` — 新增排名 API 调用
- 导航栏 — 新增全球排名入口（或合并到现有排行榜）
- `frontend/src/locales/` — 新增翻译

#### 测试要点
- [ ] **双 tab 切换**: 混合排行和 CA 专属排行正确切换
- [ ] **地区筛选**: 选择国家后过滤正确
- [ ] **认证标记**: CA 用户有视觉标识
- [ ] **全球前 X%**: CA 用户旁显示百分比
- [ ] **分页**: 翻页正常
- [ ] **i18n**: 中英文切换正确
