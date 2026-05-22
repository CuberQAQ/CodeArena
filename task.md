# Code Arena - 项目任务清单

> 需求文档详见 [requirements.md](requirements.md)
> 阶段 1-14 全部 🟢 已完成（2025-05-19 ~ 2026-05-20），归档至 [docs/archive/task_v1.0.md](docs/archive/task_v1.0.md)
> 阶段 15-27 全部 🟢 已完成（2026-05-20 ~ 2026-05-21），详见 V1.1 任务清单。
> 以下为 V1.2 需求更新任务（用户体验增强 + 时间 Elo 模型，2026-05-21）。

---

## 阶段 28: 核心基础设施 — 提交追踪改造 + 时间 Elo 模型

### Task 28.1: CF API 提交追踪改造 (FR-15)
**状态**: 🟢 已完成
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
**状态**: 🟢 已完成
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
**状态**: 🟢 已完成
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
**状态**: 🟢 已完成（在 Task 28.1 中一并实现）
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
**状态**: 🟢 已完成
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
**状态**: 🟢 已完成
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
**状态**: 🟢 已完成
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
**状态**: 🟢 已完成
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
**状态**: 🟢 已完成
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
**状态**: 🟢 已完成
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
**状态**: 🟢 已完成
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
**状态**: 🟢 已完成
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
**状态**: 🟢 已完成
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
**状态**: 🟢 已完成
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
**状态**: 🟢 已完成
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
**状态**: 🟢 已完成
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
**状态**: 🟢 已完成
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
**状态**: 🟢 已完成
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

---

## Bug 修复 (2026-05-21)

### Bug Fix 33.1: Avatar 未上传时返回默认头像
**状态**: 🟢 已完成
**优先级**: P2
**依赖**: 无

#### 根因分析
`Avatar` 组件（`frontend/src/components/Avatar.tsx:31`）对未上传头像的用户**无条件**请求 `/api/v1/auth/avatar/{userId}`，后端找不到文件返回 404。组件通过 `onError` 回退到占位符，UI 不受影响，但每次页面加载都产生不必要的 404 请求。

#### 需要修改的文件
- `backend/app/api/v1/auth.py` — `get_avatar` endpoint：当头像文件不存在时，动态生成一个 SVG 默认头像（用户名首字母 + 背景色）返回 `image/svg+xml`，而非抛出 404
- `backend/app/services/avatar_service.py` — 新增 `generate_default_avatar(user_id) -> BytesIO` 方法，根据 user_id 查询用户名，生成首字母 SVG

#### 关键实现细节
1. **默认头像生成**：在 `avatar_service.py` 中新增 `generate_default_avatar(db, user_id)` 方法。查询 User 表获取 username，取首字母，生成 SVG（圆形背景 + 首字母文字）。背景色根据 user_id 哈希从预设调色板中选择，确保同一用户颜色一致
2. **endpoint 修改**：`get_avatar` 中，当 `get_avatar_path()` 返回 None 时，不再抛 `NotFoundException`，而是调用 `generate_default_avatar()` 返回 `Response(content=svg_content, media_type="image/svg+xml")`
3. **前端无需改动**：Avatar 组件的 img 标签直接接收 SVG，降级逻辑保留作为容错

#### 测试要点
- [ ] **未上传头像**: 请求 `/api/v1/auth/avatar/{user_id}` 返回 200 + SVG
- [ ] **已上传头像**: 返回实际 JPG 头像（行为不变）
- [ ] **SVG 内容**: 包含用户名首字母，背景色与 user_id 关联
- [ ] **控制台无 404**: 页面加载时不再出现 avatar 404 错误
- [ ] **缓存友好**: 默认 SVG 返回合理的 Cache-Control 头

---

### Bug Fix 33.2: ProblemViewer 移除无效 iframe，改为外跳链接
**状态**: 🟢 已完成
**优先级**: P2
**依赖**: 无

#### 根因分析
`ProblemViewer` 组件在非盲盒模式下使用 iframe 嵌入 Codeforces 题目页，但 Codeforces 设置了 `X-Frame-Options: SAMEORIGIN` + `CSP frame-ancestors 'self'`，**禁止跨域嵌入**。iframe 始终显示空白，用户体验差。同时本项目的 Nginx CSP 策略也缺少 `frame-src`，导致 CSP 违规错误。

#### 需要修改的文件
- `frontend/src/components/ProblemViewer.tsx` — 移除 iframe 模式，非盲盒模式改为展示"在新标签页打开题目"卡片（类似盲盒模式但去掉盲盒文案），直接显示题目链接
- `frontend/src/locales/en/common.json` — 更新 ProblemViewer 相关翻译文案
- `frontend/src/locales/zh/common.json` — 同上

#### 关键实现细节
1. **统一为外跳链接模式**：移除 iframe 分支，非盲盒和盲盒模式统一使用"在新标签页打开"的卡片样式。非盲盒模式可额外展示题目链接（contestId/index 信息）
2. **UI 调整**：使用与盲盒模式类似的卡片布局（居中图标 + 链接），但文案区分：非盲盒显示"在 Codeforces 上查看题目"而非盲盒的"在 Codeforces 上查看未知题目"
3. **移除 loading 状态**：不再需要 iframe 的 loading spinner
4. **Nginx CSP 无需修改**：移除 iframe 后不再有 CSP 违规

#### 测试要点
- [ ] **非盲盒模式**: 显示"在 Codeforces 上查看题目"卡片 + 外跳链接
- [ ] **盲盒模式**: 行为不变，显示"在新标签页打开题目"
- [ ] **链接正确**: 点击外跳链接在正确的新标签页打开 CF 题目
- [ ] **无 CSP 错误**: 浏览器控制台不再有 CSP 违规错误
- [ ] **无 iframe 相关错误**: 不再有 codeforces iframe 加载错误
- [ ] **各模式页面**: FreePlay、Training、Contest 的 ProblemViewer 正常工作

---

## 审计修复 (2026-05-21)

### Task 34.1: Training K 因子 + M-Elo 全 tag 更新
**状态**: 🟢 已完成
**优先级**: P0
**依赖**: 无

#### 根因分析
审计发现 Training 服务两个问题：
1. 使用硬编码 `k_train = 8` 而非需求 3.2 定义的分段 K 因子函数，其他 4 种模式均使用 `EloService.calculate_k_factor`
2. 仅更新 `primary_tag` 的 M-Elo，不遍历 `problem_tags` 所有 tag，其他模式使用 `batch_update_melo_for_problem`

#### 需要修改的文件
- `backend/app/services/training_service.py` — `_calculate_training_elo` 方法（行 1365-1466）：
  - 替换 `k_train = 8` 为 `k = EloService.calculate_k_factor(submission_count, config)` 调用
  - 需要先通过 ConfigService 获取 K 因子配置参数
  - 注意：替换后 global_elo_change 和 melo_change 的公式中用 `k` 替代 `k_train`
  - 将单一 `update_melo` 调用替换为 `batch_update_melo_for_problem`，遍历 problem_tags 所有 tag
  - 注意：melo_change 计算需要遍历所有 tags 时可能需要调整（当前仅计算 primary_tag 的 expected score）

#### 关键实现细节
1. **K 因子替换**：需要获取 user 的 submission_count。参考 `pve_challenge_service.py:184-185` 的调用方式。
2. **M-Elo 全 tag**：将行 1459-1460 的 `MEloService.update_melo(db, user.id, primary_tag, melo_change)` 替换为 `MEloService.batch_update_melo_for_problem(db, user.id, problem_tags, melo_change, coefficient=melo_coeff)` 形式。但注意：`batch_update_melo_for_problem` 内部对每个 tag 独立计算 expected score 和 M-Elo 变化，所以 `melo_change` 不应在外部计算而应让 batch 方法自行计算。参考 PvE（`pve_challenge_service.py:308-329`）的实现方式。
3. **返回值调整**：`melo_change` 字段可能需要返回总的 M-Elo 变化量

#### 测试要点
- [ ] **K 因子一致性**: Training 使用分段 K 因子，与 PvE/PvP/FreePlay/Contest 一致
- [ ] **M-Elo 全 tag**: 一道有 dp+greedy 标签的训练题，两个 tag 的 M-Elo 都被更新
- [ ] **训练系数不变**: Global ×0.5, M-Elo ×2.0 保持不变
- [ ] **现有训练结算不破坏**: AC/失败/退出的结算逻辑正确

---

### Task 34.2: EC Final 奖牌映射修复 (FR-10.1, D-31)
**状态**: 🟢 已完成
**优先级**: P0
**依赖**: 无

#### 根因分析
`medal_service.py` 的 `_FLAT_MEDAL_MAP` 缺少 EC Final 层级（阈值与 WF/Regional 重叠），导致 EC Final 奖牌永远不可达。需求已更新为 D-31 "最高金牌归属"规则。

#### 需要修改的文件
- `backend/app/services/medal_service.py` — 更新 `_FLAT_MEDAL_MAP`：
  ```
  (2800, "world_finals", "gold"),
  (2600, "ec_final", "gold"),       # 新增
  (2200, "regional", "gold"),       # 原 2400→WF bronze, 2200→Regional gold 合并
  (1600, "provincial", "gold"),
  (1400, "provincial", "silver"),
  (1200, "provincial", "bronze"),
  ```

#### 测试要点
- [ ] **2800+**: World Finals Gold
- [ ] **2600-2799**: EC Final Gold（之前错误地映射为 WF Silver）
- [ ] **2200-2599**: Regional Gold（之前 2400-2599 映射为 WF Bronze）
- [ ] **1600-2199**: Provincial Gold
- [ ] **1400-1599**: Provincial Silver
- [ ] **1200-1399**: Provincial Bronze
- [ ] **< 1200**: Unranked

---

### Task 34.3: 比赛结算页面奖牌展示
**状态**: 🟢 已完成
**优先级**: P1
**依赖**: 无

#### 根因分析
后端 `award_contest_medal` 在比赛结算时正确发牌，但 `ContestDetailPage` 无 MedalBadge 展示，用户看不到获得的奖牌。

#### 需要修改的文件
- `frontend/src/pages/ContestDetailPage.tsx` — 在比赛结算结果区域添加 MedalBadge 组件展示

#### 关键实现细节
1. 比赛结算后，从 API 获取用户获得的奖牌信息
2. 在结算结果展示区（EloChange 附近）添加 MedalBadge 展示
3. 使用现有的 `MedalBadge` 组件

#### 测试要点
- [ ] **比赛结算后**: 结算区域展示获得的奖牌（金/银/铜）
- [ ] **无奖牌**: PR < 1200 时不展示奖牌
- [ ] **奖牌信息正确**: 级别和类型与 PR 对应

---

### Task 34.4: EloHistory 新增 time_factor 字段
**状态**: 🟢 已完成
**优先级**: P1
**依赖**: 无

#### 根因分析
需求 Section 5 明确要求 EloHistory 记录 time_factor 值，但模型缺少该字段。

#### 需要修改的文件
- `backend/app/models/elo_history.py` — 新增 `time_factor = Column(Float, nullable=True)` 字段
- `backend/migrations/versions/` — 新增 migration 添加 time_factor 列
- 所有写入 EloHistory 的位置 — 在 settlement 流程中写入 time_factor 值：
  - `backend/app/services/pve_challenge_service.py`
  - `backend/app/services/challenge_service.py`
  - `backend/app/services/training_service.py`
  - `backend/app/services/free_play_service.py`
  - `backend/app/services/contest_service.py`

#### 测试要点
- [ ] **数据库 migration**: 新增列成功
- [ ] **写入正确**: AC 时 time_factor 值写入 EloHistory
- [ ] **S=0 时**: time_factor=1.0 写入
- [ ] **现有数据**: 旧记录 time_factor 为 NULL（nullable）

---

### Task 34.5: 比赛模式移除 hint_attenuation
**状态**: 🟢 已完成
**优先级**: P1
**依赖**: 无

#### 根因分析
需求 3.6.4 规定"比赛模式不使用 hint_attenuation 机制"，但 `contest_service.py` 的 `_settle_with_pr` 方法（行 1103-1114）在 PR 结算时应用了 hint_attenuation。

#### 需要修改的文件
- `backend/app/services/contest_service.py` — 移除 `_settle_with_pr` 中行 1103-1114 的 hint_attenuation 逻辑

#### 测试要点
- [ ] **比赛使用提示**: AC 后 Elo 变化不受提示使用影响
- [ ] **其他模式不变**: PvE/PvP/Training/FreePlay 仍然应用 hint_attenuation
- [ ] **time_factor 仍生效**: 比赛模式 time_factor 继续生效

---

## 阶段 35: 站内题面展示系统 (FR-14)

### Task 35.1: 题面数据模型 + Migration (FR-14.1, 14.4)
**状态**: 🟢 已完成
**优先级**: P0
新建 `problem_statements` 数据库表，problem_id UNIQUE 约束 + contest_id/index 联合索引。

### Task 35.2: 题面爬取服务 + API (FR-14.2, 14.3, 14.5)
**状态**: 🟢 已完成
**优先级**: P0
**依赖**: Task 35.1
Playwright 爬取服务 + 按需缓存 API（GET /problem/{problem_id}/statement），爬取失败 503 + fallback_url 降级。

### Task 35.3: 前端题面展示组件 (FR-14.5, 14.6, 14.7)
**状态**: 🟢 已完成
**优先级**: P0
**依赖**: Task 35.2
ProblemStatementViewer 组件：KaTeX 渲染 LaTeX、样例复制、加载/错误状态、盲盒模式兼容。ProblemViewer 重写为精简封装。

### Task 35.4: 全模式接入题面展示 (FR-14.8)
**状态**: 🟢 已完成
**优先级**: P0
**依赖**: Task 35.3
5 个模式全部接入。PvP 替换 window.open 为 ProblemViewer。PvE 重构盲盒 UI 为 ProblemViewer blindBox 状态控制。训练/比赛/自由练习确认兼容。

---

## 阶段 36: 测试补全 — 后端高价值服务测试

> 目标：以发现和修复 bug 为最高优先级，补充后端关键服务缺失的测试。当前后端整体覆盖率 86%，但多个 API 路由层和高复杂度服务覆盖严重不足。

### Task 36.1: 修复前端 ProblemStatementViewer 失败测试
**状态**: 🟢 已完成
**优先级**: P0
**依赖**: 无

#### 问题分析
ProblemStatementViewer.test.tsx 有 9 个测试失败（超时），涉及：
- `renders problem title and index after loading` — waitFor 超时
- LaTeX 渲染测试 (3个) — KaTeX 脚本替换在 jsdom 中不工作
- `retries fetching when retry button is clicked` — 超时
- `copies sample input to clipboard on click` — navigator.clipboard mock 问题
- `shows copied feedback after copying` — 同上
- `applies custom className` / `does not render samples section when no samples` — 超时

这些失败可能暴露了组件在边界条件下的实际 bug（如：KaTeX 渲染降级、clipboard API 兼容性、异步状态管理）。

#### 需要修改的文件
- `frontend/src/components/__tests__/ProblemStatementViewer.test.tsx` — 修复测试 mock 和等待逻辑
- `frontend/src/components/ProblemStatementViewer.tsx` — 如果测试发现实际 bug 则修复组件

#### 测试要点
- [ ] 所有 28 个 ProblemStatementViewer 测试通过
- [ ] KaTeX 渲染测试正确验证数学公式渲染降级行为
- [ ] clipboard mock 正确模拟用户交互
- [ ] 异步加载状态转换在 jsdom 中稳定通过

---

### Task 36.2: 后端 API 路由层测试 — auth / training / challenge
**状态**: 🟢 已完成
**优先级**: P1
**依赖**: 无

#### 问题分析
多个 API 路由文件覆盖率极低：
- `app/api/v1/auth.py` — 44% (108行中60行未覆盖)：注册/登录/密码重置/token刷新等核心认证流程
- `app/api/v1/training.py` — 44% (78行中44行未覆盖)：训练 CRUD / 开始/结束 session
- `app/api/v1/challenge.py` — 49% (61行中31行未覆盖)：PvP 挑战创建/接受/拒绝/取消
- `app/api/v1/contest.py` — 56% (55行中24行未覆盖)：比赛创建/加入/排行榜
- `app/api/v1/free_play.py` — 56% (45行中20行未覆盖)：自由练习 CRUD
- `app/api/v1/medal.py` — 44% (39行中22行未覆盖)：奖牌查看/展示设置
- `app/api/v1/submission_tracking.py` — 53% (32行中15行未覆盖)：提交状态追踪

#### 需要修改的文件
- `backend/tests/test_auth_api.py` — auth 路由端到端测试
- `backend/tests/test_training_api.py` — training 路由测试
- `backend/tests/test_challenge_api.py` — challenge 路由测试
- `backend/tests/test_contest_api.py` — contest 路由测试
- `backend/tests/test_free_play_api.py` — free_play 路由测试
- `backend/tests/test_medal_api.py` — medal 路由测试
- `backend/tests/test_submission_tracking_api.py` — submission tracking 路由测试

#### 测试要点
- [ ] auth：注册→登录→token刷新→密码修改完整流程，含参数校验、重复注册、错误密码
- [ ] training：创建 topic / 开始 session / 提交解题 / 结束 session，含权限校验
- [ ] challenge：创建→接受→拒绝→取消完整生命周期，含并发冲突
- [ ] contest：创建→加入→实时状态→结束完整流程，含边界条件（人数上限、重复加入）
- [ ] free_play：创建 session / 提交解题 / 结束，含 Elo/PP 结算验证
- [ ] medal：查看奖牌柜 / 设置展示模式 / PP 排名查询
- [ ] submission_tracking：开始追踪 / 查询状态 / 超时处理
- [ ] 重点发现业务逻辑 bug：错误的 HTTP 状态码、缺失的权限校验、不一致的数据状态

---

### Task 36.3: 后端关键服务测试 — match_service / problem_scraper / rate_limiter
**状态**: 🟢 已完成
**优先级**: P1
**依赖**: 无

#### 问题分析
高复杂度服务覆盖不足：
- `app/services/match_service.py` — 89%（172行中19行未覆盖）：Redis 匹配队列 + 概率权重匹配算法，未覆盖的是错误路径和边界条件
- `app/services/problem_scraper_service.py` — 69%（143行中44行未覆盖）：Playwright 爬取服务，核心爬取路径未测试
- `app/utils/rate_limiter.py` — 34%（35行中23行未覆盖）：限流中间件几乎未测试
- `app/api/v1/contest_ws.py` — 23%（64行中49行未覆盖）：WebSocket 实时比赛更新
- `app/services/cf_handle_service.py` — 15%（97行中82行未覆盖）：CF 账号绑定核心逻辑
- `app/core/database.py` — 43%（14行中8行未覆盖）：数据库连接管理
- `app/core/redis.py` — 73%（30行中8行未覆盖）：Redis 连接管理

#### 需要修改的文件
- `backend/tests/test_match_service_extra.py` — match_service 边界条件和错误路径
- `backend/tests/test_problem_scraper.py` — 爬取服务 mock 测试
- `backend/tests/test_rate_limiter.py` — 限流中间件完整测试
- `backend/tests/test_contest_ws.py` — WebSocket 端点测试
- `backend/tests/test_cf_handle_service.py` — CF 账号绑定逻辑
- `backend/tests/test_db_redis.py` — 数据库/Redis 连接管理

#### 测试要点
- [ ] match_service：Redis 断连恢复、匹配概率计算边界（Elo 差异极大/极小）、并发匹配竞态
- [ ] problem_scraper：爬取超时、HTML 解析失败、缓存命中/过期、Playwright 进程异常
- [ ] rate_limiter：正常请求通过、超限返回 429、滑动窗口重置、不同限流策略
- [ ] contest_ws：连接建立/断开、实时更新推送、多客户端广播
- [ ] cf_handle_service：绑定/解绑/验证流程、CF API 调用失败、重复绑定
- [ ] 重点发现：并发安全 bug、资源泄漏、错误处理遗漏

---

## 阶段 37: 测试补全 — 前端 E2E + CI 集成

### Task 37.1: 前端 E2E 测试补全
**状态**: 🟢 已完成
**优先级**: P2
**依赖**: 无

#### 问题分析
现有 E2E 覆盖：auth / dashboard / training / admin / PvP challenge / contest (integration)
缺失的关键用户流程：
- 自由练习模式 (FreePlay) 完整流程
- 设置页面 / 个人资料页面
- CF 账号绑定流程
- 排行榜页面
- 导航栏交互
- 比赛模式完整 E2E（非 integration 层 mock）

#### 需要修改的文件
- `frontend/e2e/freeplay.spec.ts` — 自由练习 E2E
- `frontend/e2e/settings-profile.spec.ts` — 设置/个人资料 E2E
- `frontend/e2e/cf-bind.spec.ts` — CF 绑定 E2E
- `frontend/e2e/leaderboard.spec.ts` — 排行榜 E2E

#### 测试要点
- [ ] FreePlay：选择题目→查看题面→提交代码→查看结果→Elo/PP 更新
- [ ] 设置页面：修改个人信息、头像、CF handle 绑定/解绑
- [ ] 排行榜：查看 Elo/PP 排名、翻页、搜索用户
- [ ] 导航一致性：每个页面导航栏正确、面包屑可用

---

### Task 37.2: CI 集成测试配置
**状态**: 🟢 已完成
**优先级**: P2
**依赖**: Task 36.2, 36.3

#### 问题分析
当前 CI 只跑单元测试（pytest / vitest），缺少：
1. 后端 testcontainers 测试需要 PostgreSQL Docker 服务 → CI 上 pytest 默认跳过
2. 前端 E2E 测试（Playwright）未在 CI 中运行
3. backend-test job 缺少 `--cov` → 无法检查覆盖率门禁

#### 需要修改的文件
- `.github/workflows/ci.yml` — 添加 PostgreSQL service、Playwright E2E job、后端覆盖率门禁

#### 测试要点
- [ ] CI backend-test job 使用 PostgreSQL service container
- [ ] CI backend-test job 添加 `--cov` 覆盖率门禁
- [ ] CI 新增 frontend-e2e job，安装 Playwright + 浏览器，运行 E2E
- [ ] E2E 测试需要后端 API server → 使用 docker-compose service 或 mock server

---

## 阶段 38: 体验优化 — Bug 修复 + 快速改进

> 需求文档 V1.3 新增需求（2026-05-22）。Task 37.x 由其他 agent 负责，本阶段从 38 开始。

### Task 38.1: 做题计时器持久化 (FR-19)
**状态**: ⬜ 待开发
**优先级**: P0
**依赖**: 无

#### 任务描述
自由选题和专题训练的做题计时器基于 session 的 started_at 时间戳计算已用时间，刷新页面或重新进入时不归零。

#### 需求规格 (requirements.md FR-19)
- FR-19.1: session 记录 started_at 时间戳（精度秒级）
- FR-19.2: 计时器基于 started_at 计算 elapsed = now - started_at，跨页面连续
- FR-19.3: 适用自由选题 session 和专题训练 session

#### 需要修改的文件
- `backend/app/models/free_play_session.py` — 确认 started_at 字段已存在（当前模型已有）
- `backend/app/models/training_session.py` — 确认/新增 started_at 字段
- `backend/app/services/free_play_service.py` — start_session() 确保 started_at = utcnow
- `backend/app/services/training_service.py` — start session 时记录 started_at
- `frontend/src/pages/FreePlaySessionPage.tsx` — useElapsedTime 改为接受初始值：从后端 session 的 started_at 计算 elapsed
- `frontend/src/pages/TrainingDetailPage.tsx` — 同上，计时器从 started_at 恢复
- `backend/migrations/versions/` — 若 training_session 缺少 started_at 则新增 migration

#### 调用方清单
- FreePlaySessionPage 加载时获取 session 数据（含 started_at）
- TrainingDetailPage 加载时获取 session 数据（含 started_at）

#### 反向集成清单
- started_at 同时用于 time_spent 计算（结算时 time_spent = completed_at - started_at），确保一致
- 后端 session GET API 返回 started_at 字段供前端使用

#### 关键实现细节
1. **FreePlaySession** 模型已有 `started_at` 字段，只需确认 start_session 时正确写入
2. **TrainingSession** 需确认是否有 started_at；若没有，新增 Column(DateTime) 并在 migration 中设置默认值 = created_at
3. **useElapsedTime 改造**：接受 initialSeconds 参数，初始化时 setElapsed(initialSeconds) 而非 setElapsed(0)
4. **session API 返回**：前端加载已有 session 时，从 API 响应获取 started_at，计算 Math.floor((Date.now() - new Date(started_at).getTime()) / 1000) 作为 initialSeconds

#### 测试要点
- [ ] **自由选题刷新**: 开始做题 → 刷新页面 → 计时器从上次时间继续
- [ ] **训练刷新**: 开始训练做题 → 刷新页面 → 计时器从上次时间继续
- [ ] **自由选题重新进入**: 关闭页面 → 重新进入 session → 计时器正确恢复
- [ ] **新 session**: 新建 session 时计时器从 0 开始
- [ ] **结算时间一致**: time_spent 与前端计时器显示一致

---

### Task 38.2: CF 全球排名用户展示修复 (FR-18.5)
**状态**: 🟢 已完成
**优先级**: P0
**依赖**: 无

#### 任务描述
全球排名页面正常展示 CF 采样用户数据，CA 用户和 CF 用户混合排行。

#### 需求规格 (requirements.md FR-18.5)
- 全球排名中的 CF 采样用户正常显示
- CF 用户展示估算 PP 和 CF rating
- 排序：PP 降序，同 PP 时 CA 用户优先

#### 需要修改的文件
- `backend/app/services/ranking_service.py` — 排查 get_global_ranking() 数据查询逻辑
- `backend/app/services/cf_ranking_service.py` — 排查采样数据是否正确存储
- `backend/app/models/cf_sample_user.py` — 确认模型和数据完整性
- `backend/app/api/v1/ranking.py` — 确认 API 端点返回 CF 用户数据
- `frontend/src/pages/GlobalRankingPage.tsx` — 确认前端正确渲染 CF 用户

#### 调用方清单
- GlobalRankingPage 组件调用 GET /ranking/global API
- CF 采样管道 cf_ranking_service.run_sampling_pipeline()

#### 关键实现细节
1. **排查方向**：
   - cf_sample_users 表是否有数据（采样管道是否执行过）
   - ranking_service 查询是否正确 JOIN cf_sample_users
   - API 响应格式前端是否正确解析
   - 前端渲染条件是否过滤掉了 CF 用户
2. **修复验证**：确保 global ranking 页面同时展示 CA 和 CF 用户

#### 测试要点
- [ ] **CF 用户可见**: 全球排名页面包含 CF 采样用户
- [ ] **混合排序**: CA 和 CF 用户按 PP 混合排序
- [ ] **CA 优先**: 同 PP 时 CA 用户排在前面
- [ ] **CF 用户信息**: CF 用户显示估算 PP 和 CF rating
- [ ] **国家筛选**: CF 用户也参与国家筛选

---

### Task 38.3: 自由选题改为出 3 道题 (FR-8.2, 8.3)
**状态**: 🟢 已完成
**优先级**: P1
**依赖**: 无

#### 任务描述
手动筛选和自适应推荐均返回 3 道难度梯度上升的题目，前端以卡片形式并排展示。

#### 需求规格 (requirements.md FR-8.2, 8.3)
- FR-8.2: 手动筛选返回 3 道，rating 均匀分布，不足 3 题返回实际数量
- FR-8.3: 自适应推荐返回 3 道，梯度 ±100 / +100~200 / +200~300

#### 需要修改的文件
- `backend/app/services/free_play_service.py` —
  - `search_problems()`: 返回 3 道题而非 1 道，rating 均匀分布
  - `recommend_problem()`: 返回 3 道推荐题，难度梯度上升
  - 响应模型调整：FreePlaySearchResponse / FreePlayRecommendResponse 改为列表
- `backend/app/api/v1/free_play.py` — 适配新的响应格式
- `frontend/src/pages/FreePlayPage.tsx` — 展示 3 道题卡片并排，标注 Easy/Medium/Hard，用户选择一道开始
- `frontend/src/pages/FreePlaySessionPage.tsx` — 无变化（session 仍针对单道题）
- `frontend/src/locales/` — 新增 Easy/Medium/Hard 翻译

#### 调用方清单
- FreePlayPage 调用 search/recommend API
- 用户选择其中一道题后调用 start_session

#### 反向集成清单
- 结算逻辑不变（仍然是单题结算）
- session 创建仍然针对单道题

#### 关键实现细节
1. **手动筛选 3 题**：获取所有符合条件的题后，按 rating 排序，均匀取 3 道（低/中/高）。如 30 道符合题，取第 1/15/30 或等间隔取
2. **自适应推荐 3 题**：确定推荐 tag 后，在三个难度范围分别搜索：
   - 简单: [M-Elo-100, M-Elo+100]
   - 中等: [M-Elo+100, M-Elo+200]
   - 困难: [M-Elo+200, M-Elo+300]
   每个范围取一道，不足则范围向外扩展
3. **前端展示**：3 张卡片并排，每张显示题目名、rating（带颜色）、难度标签（Easy/Medium/Hard）、CF tags。用户点击任意一张开始做题
4. **去重**：3 道题不能包含已 AC 的题目，3 道题之间不能重复

#### 测试要点
- [ ] **手动筛选 3 题**: 搜索结果返回 3 道，rating 梯度上升
- [ ] **手动筛选不足 3 题**: 范围内只有 1-2 题 → 返回实际数量
- [ ] **自适应推荐 3 题**: 3 道题难度分别为 ±100 / +100~200 / +200~300
- [ ] **前端 3 卡片展示**: 并排显示，标注 Easy/Medium/Hard
- [ ] **选择题目**: 点击任意卡片进入做题 session
- [ ] **去重**: 不包含已 AC 题，3 道互不重复

---

### Task 38.4: 算法标签与技能名称中文化 (FR-21)
**状态**: 🟢 已完成
**优先级**: P1
**依赖**: 无

#### 任务描述
12 个算法专题拥有双语名称，前端根据语言偏好展示中文或英文名。

#### 需求规格 (requirements.md FR-21)
- FR-21.1: 每个专题拥有中英文名称
- FR-21.2: 段位名称中英文对照
- FR-21.3: 标签名称通过 i18n 获取

#### 需要修改的文件
- `backend/app/services/training_service.py` — PREDEFINED_TOPICS 每项增加 name_zh 字段
- `frontend/src/locales/en/` — 新增专题名称英文翻译
- `frontend/src/locales/zh/` — 新增专题名称中文翻译
- `frontend/src/pages/TrainingPage.tsx` — 专题卡片使用 i18n key 展示名称
- `frontend/src/pages/TrainingDetailPage.tsx` — 专题详情使用 i18n 名称
- `frontend/src/components/charts/RadarChart.tsx` — 雷达维度名使用 i18n
- 其他展示标签名的前端组件 — 统一使用 i18n

#### 调用方清单
- TrainingPage 专题卡片
- TrainingDetailPage 专题标题
- RadarChart 维度标签
- Profile 页技能勋章墙

#### 关键实现细节
1. **后端 name_zh**：在 PREDEFINED_TOPICS 每项增加 `"name_zh": "动态规划"` 字段，API 响应中同时返回 name 和 name_zh
2. **前端 i18n**：在翻译文件中增加 `topic_dp: "动态规划"` / `topic_dp: "Dynamic Programming"` 的映射
3. **展示统一**：所有展示标签名的位置使用 `t('topic_dp')` 而非硬编码英文名
4. **段位中文化**：段位名称翻译已有（Newbie/新手 等），确认翻译完整

#### 测试要点
- [ ] **训练页中文**: 切换中文后专题名显示中文
- [ ] **训练页英文**: 切换英文后专题名显示英文
- [ ] **雷达图中文**: 雷达维度名随语言切换
- [ ] **详情页**: 专题详情页标题随语言切换
- [ ] **段位中文化**: 所有段位名称中英文正确

---

## 阶段 39: 比赛赛制改造

### Task 39.1: 比赛赛制后端改造 (FR-4.4)
**状态**: ⬜ 待开发
**优先级**: P1
**依赖**: 无

#### 任务描述
比赛分级改为 5 级赛制：Beginner(Div4)/Pupil(Div3)/Advanced(Div2)/Master(Div1)/Blitz(短时赛)，展示名沿用风格化名称，底层 Div 编号对齐 CF。

#### 需求规格 (requirements.md FR-4.4)
- 5 级赛制表（见 requirements.md）
- 高 rating 用户可降级参加低 Div
- Blitz 短时赛：60min/3-4 题/无门槛

#### 需要修改的文件
- `backend/app/services/contest_service.py` —
  - TIER_CONFIGS 重构为 5 级，增加 div 编号字段
  - 新增 "pupil" 和 "blitz" tier 配置
  - rated 规则：高 rating 用户参加低 Div 不 rated（或按 CF 规则）
  - Blitz 题目选择逻辑：根据参赛群体平均 rating 动态调整
  - rated 范围检查逻辑调整
- `backend/app/api/v1/contest.py` — API 适配新 tier
- `backend/app/api/v1/contest_ws.py` — WebSocket 适配

#### 调用方清单
- ContestPage 调用创建比赛 API
- ContestDetailPage 实时状态
- 比赛结算 PR 计算

#### 反向集成清单
- 比赛结算（PR → Elo 更新）逻辑不变
- 比赛奖牌发放不变（与组别无关）
- Bot 生成逻辑适配新 tier 范围
- M-Elo 更新不变

#### 关键实现细节
1. **TIER_CONFIGS 重构**：
   ```python
   TIER_CONFIGS = {
       "beginner": {"div": 4, "name": "Beginner Contest", "max_elo": 1399, "duration_minutes": 120, "problem_count": 6, "rating_range": [800, 1400]},
       "pupil": {"div": 3, "name": "Pupil Contest", "max_elo": 1599, "duration_minutes": 120, "problem_count": 6, "rating_range": [800, 1600]},
       "advanced": {"div": 2, "name": "Advanced Contest", "max_elo": 2099, "duration_minutes": 120, "problem_count": 5, "rating_range": [1200, 2200]},
       "master": {"div": 1, "name": "Master Contest", "min_elo": 1900, "duration_minutes": 120, "problem_count": 5, "rating_range": [1600, 3000]},
       "blitz": {"div": None, "name": "Blitz Contest", "duration_minutes": 60, "problem_count": 3, "rating_range": "dynamic"},
   }
   ```
2. **Rated 规则**：用户 rating 在 tier 的 rated 范围内时 rated，否则可参加但不 rated（rating 不变）
3. **Blitz 题目选择**：根据报名用户的平均 rating 确定题目 rating 范围（如平均 1500 → 题目 [1000, 2000]）
4. **现有数据兼容**：已有的 contest_session 记录的 tier 值需兼容（beginner/advanced/master 仍然有效）

#### 测试要点
- [ ] **5 级赛制创建**: 可创建 5 种类型的比赛
- [ ] **Div 编号**: beginner=Div4, pupil=Div3, advanced=Div2, master=Div1, blitz=无
- [ ] **Rated 规则**: rating 1300 参加 beginner → rated；rating 1800 参加 beginner → 不 rated
- [ ] **Blitz 题目**: 题目难度根据参赛群体动态调整
- [ ] **Blitz 时长**: 60 分钟比赛
- [ ] **高 rating 降级**: 2000 rating 用户可参加 advanced(Div2)
- [ ] **结算不变**: PR 计算和奖牌发放逻辑不受影响
- [ ] **现有比赛兼容**: 已有比赛数据不受影响

---

### Task 39.2: 比赛赛制前端适配 (FR-4.4)
**状态**: ⬜ 待开发
**优先级**: P1
**依赖**: Task 39.1

#### 任务描述
前端比赛页面适配 5 级赛制，展示 5 种比赛类型卡片。

#### 需要修改的文件
- `frontend/src/pages/ContestPage.tsx` —
  - 展示 5 种比赛类型卡片（增加 Pupil 和 Blitz）
  - 每张卡片显示展示名、Div 编号、rated 范围、时长、题数
  - Eligibility 检查适配新 rated 规则
  - Blitz 卡片特殊样式（闪电图标、短时标识）
- `frontend/src/pages/ContestDetailPage.tsx` — 适配新 tier 参数
- `frontend/src/locales/` — 新增比赛类型翻译

#### 测试要点
- [ ] **5 种卡片**: 页面展示 5 种比赛类型
- [ ] **Eligibility**: 各 tier 准入判断正确
- [ ] **Blitz 展示**: 短时赛卡片有特殊样式
- [ ] **Div 编号展示**: 卡片上显示 Div 1/2/3/4
- [ ] **i18n**: 比赛类型名称中英文正确

---

## 阶段 40: 训练 UX 重构

### Task 40.1: 训练 UX 后端改造 — 精选题 + 推荐 (FR-3.5)
**状态**: ⬜ 待开发
**优先级**: P1
**依赖**: 无

#### 任务描述
训练系统后端增加精选题列表 API 和智能推荐 API，支持"推荐做题"和"题目列表"双模式。

#### 需求规格 (requirements.md FR-3.5)
- 推荐做题模式：基于 M-Elo 自动推荐一道题
- 题目列表模式：返回 20-30 道精选题，支持加载更多和难度筛选
- 推荐专题区域：基于用户水平推荐 2-3 个专题

#### 需要修改的文件
- `backend/app/services/training_service.py` —
  - 新增 `get_curated_problems(db, topic_id, user_id, limit=20, offset=0, min_rating=None, max_rating=None)` 方法
  - 新增 `recommend_training_problem(db, topic_id, user_id)` 方法
  - 新增 `get_recommended_topics(db, user_id, limit=3)` 方法
  - 精选逻辑：按 rating 分段，每段选 AC 率高的代表题
- `backend/app/api/v1/training.py` — 新增 API 端点：
  - `GET /training/topics/{id}/curated-problems` — 精选题列表
  - `GET /training/topics/{id}/recommend` — 推荐一道题
  - `GET /training/recommended-topics` — 推荐专题

#### 调用方清单
- 前端训练详情页调用推荐和精选题 API
- 前端训练首页调用推荐专题 API

#### 反向集成清单
- 推荐逻辑依赖 M-Elo 数据
- 精选题依赖 CF API 题库数据
- 结算逻辑不变

#### 关键实现细节
1. **精选题逻辑**：获取某 tag 的所有题目 → 按 rating 排序 → 按 rating 分段（每 200 分一段）→ 每段选 3-5 道代表题（优先选 AC 率高的、有比赛出处的）→ 合并返回 20-30 道
2. **推荐逻辑**：基于用户在该 tag 的 M-Elo，在 [M-Elo-100, M-Elo+100] 范围内选一道未做题
3. **推荐专题**：按各 tag 的 M-Elo 升序排列（最弱的排前面），取前 3 个
4. **渐进式解锁**：精选题 API 支持 offset 参数，初始加载 20 道，加载更多时 +20

#### 测试要点
- [ ] **精选题数量**: 返回 20-30 道
- [ ] **精选题难度递进**: rating 从低到高排列
- [ ] **推荐题水平匹配**: 推荐题 rating 接近用户 M-Elo
- [ ] **推荐专题**: 返回用户最弱的 2-3 个专题
- [ ] **加载更多**: offset 参数正确翻页
- [ ] **难度筛选**: min_rating/max_rating 过滤正确

---

### Task 40.2: 训练 UX 前端重构 (FR-3.5)
**状态**: 🟢 已完成
**优先级**: P1
**依赖**: Task 40.1, Task 38.4

#### 任务描述
重构训练页面前端：卡片信息精简、双模式（推荐做题 + 题目列表）切换、学习路径引导、实时反馈。

#### 需要修改的文件
- `frontend/src/pages/TrainingPage.tsx` —
  - 卡片精简：只展示中文名 + 进度百分比；hover 展示 M-Elo/已完成数
  - 推荐专题区域：顶部展示 2-3 个推荐专题卡片
  - "今日训练目标"提示文案
- `frontend/src/pages/TrainingDetailPage.tsx` —
  - 双模式切换 UI（推荐模式 / 列表模式 tab）
  - 推荐模式：分屏布局（左题面，右信息面板 + SolvingTimeline + 计时器）+ "换一道"按钮
  - 列表模式：精选题列表，按难度递进，支持"加载更多"和难度筛选
  - 使用 i18n 展示中文专题名
- `frontend/src/locales/` — 新增训练 UX 翻译

#### 调用方清单
- 训练首页用户选择专题
- 训练详情页用户做题

#### 反向集成清单
- SolvingTimeline 组件复用
- ProblemViewer / ProblemStatementViewer 复用
- 计时器使用 Task 38.1 持久化后的逻辑

#### 关键实现细节
1. **卡片精简**：移除当前的 CF tags 展示、冗余的星级/奖牌细节。一级只显示：中文名 + 进度条 + M-Elo 数值
2. **推荐专题区**：卡片上方展示"推荐训练"横幅，显示 2-3 个推荐专题，带理由文案（如"你的动态规划 M-Elo 最低，建议优先练习"）
3. **双模式 tab**：默认"推荐做题"tab，可切换"题目列表"tab
4. **推荐模式分屏**：左侧 ProblemStatementViewer 占 60%，右侧信息面板占 40%（含 SolvingTimeline、计时器、连续 AC、streak、预计 token）
5. **列表模式**：每道题显示 rating（带颜色）、难度标签、已做/未做状态。点击题目进入做题
6. **"换一道"按钮**：调用推荐 API 获取新题，不创建新 session

#### 测试要点
- [ ] **卡片精简**: 每张卡片只显示核心信息
- [ ] **推荐专题**: 首页顶部展示推荐专题
- [ ] **双模式切换**: 推荐和列表模式切换流畅
- [ ] **推荐模式分屏**: 左题面右信息面板布局正确
- [ ] **列表模式精选题**: 显示 20-30 道，难度递进
- [ ] **加载更多**: 点击加载更多追加题目
- [ ] **换一道**: 点击后获取新推荐题
- [ ] **i18n**: 专题名和 UI 文案中英文切换
- [ ] **计时器持久化**: 刷新后计时器不归零

---

## 阶段 41: 排名整合 + 雷达 + UX 打磨

### Task 41.1: 排名页面整合 (FR-20)
**状态**: 🟢 已完成
**优先级**: P1
**依赖**: Task 38.2（CF 用户展示修复后才有意义）

#### 任务描述
合并 Leaderboard 和 Global Ranking 为统一排名页面 /ranking，双标签页切换。

#### 需求规格 (requirements.md FR-20)
- FR-20.1: 统一排名页面，双标签页（全球排名 + 站内排名）
- FR-20.2: 导航栏只有一个排名入口

#### 需要修改的文件
- `frontend/src/pages/GlobalRankingPage.tsx` — 重构为统一排名页面，路由改为 /ranking
  - 合并 LeaderboardPage 的功能到站内排名 tab
  - 全球排名 tab：CA + CF 混合排行
  - 站内排名 tab：仅 CA 用户，支持按 PP/ELO 排序
- `frontend/src/pages/LeaderboardPage.tsx` — 废弃或重定向到 /ranking
- `frontend/src/App.tsx` 或路由配置 — /leaderboard → 重定向 /ranking，/global-ranking → 重定向 /ranking
- 导航栏配置 — 移除重复入口，只保留一个"排名"导航项

#### 调用方清单
- 导航栏链接
- 直接 URL 访问 /leaderboard 或 /global-ranking

#### 关键实现细节
1. **页面结构**：统一 RankingPage，顶部两个 tab：
   - "全球排名" tab：复用当前 GlobalRankingPage 的全球排名部分（CA + CF 混排）
   - "站内排名" tab：复用当前 LeaderboardPage 的功能（CA 用户排行，按 PP/ELO 排序）
2. **路由**：/ranking 为新路由，/leaderboard 和 /global-ranking 做 301 重定向
3. **导航栏**：只保留一个"排名"入口，图标用 Globe 或 Trophy

#### 测试要点
- [ ] **统一入口**: 导航栏只有一个排名链接
- [ ] **全球排名 tab**: CA + CF 混合排行正常
- [ ] **站内排名 tab**: 仅 CA 用户，PP/ELO 排序
- [ ] **旧路由重定向**: /leaderboard → /ranking, /global-ranking → /ranking
- [ ] **国家筛选**: 两个 tab 均支持
- [ ] **分页**: 两个 tab 均支持

---

### Task 41.2: 技能雷达维度收归 (FR-22)
**状态**: 🟢 已完成
**优先级**: P2
**依赖**: Task 38.4（标签中文化后才有完整维度名）

#### 任务描述
雷达图从 12 个专题维度收归为 8 个核心维度，每个维度聚合一个或多个子专题的 M-Elo。

#### 需求规格 (requirements.md FR-22)
- FR-22.1: 8 个核心维度定义
- FR-22.2: 聚合规则（加权平均）
- FR-22.3: 训练专题保持 12 个
- FR-22.4: 无数据维度显示默认值

#### 需要修改的文件
- `frontend/src/components/charts/RadarChart.tsx` —
  - 新增维度映射配置：8 个核心维度 → 对应的 CF tags
  - 获取 M-Elo 数据后按映射聚合
  - 维度名使用 i18n 中英文展示
- 后端 API（如 M-Elo 数据是按 tag 返回的，聚合在前端做即可）

#### 关键实现细节
1. **维度映射**：
   ```typescript
   const RADAR_DIMENSIONS = [
     { key: "dp", label_zh: "动态规划", label_en: "Dynamic Programming", tags: ["dp"] },
     { key: "graphs", label_zh: "图论", label_en: "Graph Theory", tags: ["graphs", "trees"] },
     { key: "math", label_zh: "数学", label_en: "Mathematics", tags: ["math", "number theory"] },
     { key: "ds", label_zh: "数据结构", label_en: "Data Structures", tags: ["data structures"] },
     { key: "strings", label_zh: "字符串", label_en: "Strings", tags: ["strings"] },
     { key: "greedy", label_zh: "贪心与构造", label_en: "Greedy & Constructive", tags: ["greedy", "constructive algorithms"] },
     { key: "search", label_zh: "搜索与排序", label_en: "Search & Sorting", tags: ["binary search", "sortings"] },
     { key: "geometry", label_zh: "计算几何", label_en: "Geometry", tags: ["geometry"] },
   ]
   ```
2. **聚合计算**：核心维度的 value = 其 tags 对应 M-Elo 的平均值。若某 tag 无数据，跳过。若所有 tags 都无数据，使用 Global Elo 或 1200
3. **训练专题不变**：训练页面仍显示 12 个子专题卡片

#### 测试要点
- [ ] **8 维度展示**: 雷达图显示 8 个维度
- [ ] **聚合正确**: 图论 = avg(graphs M-Elo, trees M-Elo)
- [ ] **无数据维度**: 缺少数据的维度显示默认值
- [ ] **维度名 i18n**: 切换语言维度名跟随切换
- [ ] **训练页不变**: 训练页仍展示 12 个子专题

---

### Task 41.3: 整体 UX 打磨 (FR-23)
**状态**: 🟢 已完成
**优先级**: P2
**依赖**: Task 41.1（排名整合后统一导航）

#### 任务描述
统一导航栏、页面标题面包屑、loading 状态、错误提示、响应式布局、深色模式适配。

#### 需求规格 (requirements.md FR-23)
- FR-23.1: 导航项不重复
- FR-23.2: 所有页面有清晰标题和返回路径
- FR-23.3: 统一 loading/skeleton
- FR-23.4: 统一错误信息样式
- FR-23.5: 关键页面移动端可用
- FR-23.6: 深色模式适配。若项目当前无深色模式基础设施（无 dark: class 策略、无主题切换），则先搭建 Tailwind dark mode class 策略 + CSS 变量体系 + 主题切换开关（位于设置页或导航栏）

#### 需要修改的文件
- `frontend/src/components/layout/MainLayout.tsx` — 导航栏配置更新
- `frontend/src/components/layout/` — 统一面包屑组件
- `frontend/src/components/ui/` — 统一 loading/skeleton/error 组件
- 各页面组件 — 标题和面包屑接入
- `frontend/src/index.css` 或 `tailwind.config.js` — 深色模式样式检查

#### 测试要点
- [ ] **导航无重复**: 每类功能只有一个导航入口
- [ ] **面包屑**: 各页面有面包屑导航
- [ ] **loading 统一**: 各页面使用统一的 skeleton/loading 组件
- [ ] **错误提示**: 错误信息用户友好，不显示技术栈
- [ ] **移动端**: 关键页面在 375px 宽度下可用
- [ ] **深色模式**: 所有新改动在深色模式下样式正确

---

## 阶段 42: 运维 — CF 排行榜数据爬取

### Task 42.1: CF 排行榜管线执行与调试
**状态**: ⬜ 进行中
**优先级**: P0
**依赖**: 无

#### 任务描述
执行 `POST /admin/cf-ranking/pipeline` 管线，爬取 CF 全球排行榜用户数据并存入 `cf_sample_users` 表。调试管线运行过程中的所有错误，直到爬取成功。

#### 关键文件
- `backend/app/api/v1/admin.py` — 触发端点
- `backend/app/services/cf_ranking_service.py` — 爬取逻辑
- `backend/app/services/cf_api_service.py` — CF API 调用
- `backend/app/services/pp_service.py` — 等效 PP 计算
- `backend/app/models/cf_sample_user.py` — 数据模型

#### 管线流程
1. `POST /admin/cf-ranking/pipeline` 触发
2. 获取 CF 所有 rated 用户 (`/user.ratedList`)
3. 按 200 分 rating 桶分层采样（每桶 100 人）
4. 对每个采样用户回放提交历史计算等效 PP
5. 多项式回归拟合 (rating → PP)
6. 存入 `cf_sample_users` 表

#### 约束
- 禁止 workaround 和降级方案
- 遇到错误必须找到根因并修复
- CF API 有 2s/请求 限制，管线运行时间较长（预计 1-2 小时）

---

## 阶段 43: 质量工程体系 — 工业顶级基础设施建设

> 目标：构建工业顶级的质量保障体系。五重 CI 门禁 + property-based testing + 真实环境集成测试 + 变异测试 + 自动化横切矩阵。让任何 agent 审计都无法给出 A 以下评价。

### Task 43.1: 统一测试 Fixture 体系 — 自动同步测试模型
**状态**: ⬜ 待开发
**优先级**: P0
**依赖**: 无

#### 任务描述
当前后端测试存在双轨制：`tests/` 用 SQLite 内存库 + 手动定义的 `_Test*` model（31个文件），`tests/integration/` 用 testcontainers PostgreSQL。每次生产 model 变更都需要手动同步 `_Test*` model，已多次失败（`started_at`、`overkill_multiplier`）。

需要建立自动化的测试模型同步机制，彻底消除手动同步。

#### 需要修改的文件
- `backend/tests/conftest.py` — 新增统一 fixture 体系：
  - `generate_test_model(production_model)` — 从生产 SQLAlchemy model 自动生成 SQLite 兼容的测试 model（剔除 PostgreSQL 特有类型如 JSONB、UUID server_default，替换为 SQLite 兼容类型）
  - `schema_consistency_check()` — CI 中断言：测试 model 的字段集合是生产 model 字段集合的子集
- 所有使用 `_Test*` model 的测试文件 — 迁移到自动生成的 model
- `backend/pyproject.toml` — 添加 `@pytest.mark.integration` 标记配置

#### 关键实现细节
1. **自动生成策略**：遍历生产 model 的 `__table__.columns`，对每个 Column：
   - UUID → String(36)（SQLite 不支持原生 UUID）
   - JSONB / JSON → JSON（SQLAlchemy 的 JSON 在 SQLite 中用 TEXT 实现，够用）
   - ARRAY → String（存 JSON 字符串）
   - DateTime(timezone=True) → DateTime
   - ForeignKey → 仅保留列定义，去掉约束
   - server_default → 去掉（SQLite 不支持）
2. **一致性断言**：CI 中新增一个测试文件 `tests/test_schema_sync.py`，遍历所有 `_Test*` model 和对应的生产 model，断言字段名集合完全一致
3. **迁移策略**：先写好 `generate_test_model`，然后逐文件替换 `_Test*` 类定义为 `generate_test_model(ProductionModel)` 调用

#### 测试要点
- [ ] **自动生成正确**: 生成的测试 model 字段集合与生产 model 一致
- [ ] **SQLite 兼容**: 自动生成的 model 能在 SQLite 内存库中 create_all 不报错
- [ ] **现有测试不破坏**: 替换后 2171 个现有测试全部通过
- [ ] **schema 一致性断言**: 新增字段后 CI 自动失败提示同步
- [ ] **integration 标记**: integration 测试用 `@pytest.mark.integration` 标记

---

### Task 43.2: CI 五重质量门禁 — 安全扫描 + 类型检查
**状态**: 🟢 已完成
**优先级**: P0
**依赖**: 无

#### 任务描述
当前 CI 只有 lint + test，缺少安全扫描和类型检查。添加五重质量门禁。

#### 需要修改的文件
- `.github/workflows/ci.yml` — 新增和修改 CI jobs：
  - `backend-test`: 确认覆盖率门禁生效（`--cov-fail-under` 已在 pyproject.toml addopts 中）
  - `backend-security`: 新增 job — `bandit -r app/ -ll` + `pip-audit`
  - `backend-typecheck`: 新增 job — `mypy app/ --ignore-missing-imports --no-error-summary`（首次运行允许有 error，但 job 不 fail；后续逐步收紧）
  - `frontend-test`: 确认覆盖率门禁 `--cov-fail-under=80` 生效
  - `frontend-security`: 新增 step — `npm audit --audit-level=high`
- `.pre-commit-config.yaml` — 新增 `detect-secrets` hook 阻止密钥提交
- `backend/requirements.txt` — 添加 `bandit>=1.8`、`pip-audit`、`mypy>=1.11`
- `backend/mypy.ini` 或 `backend/pyproject.toml` — mypy 配置

#### 测试要点
- [ ] **bandit 扫描通过**: 无高危安全问题
- [ ] **pip-audit 通过**: 依赖无已知漏洞
- [ ] **npm audit 通过**: 前端依赖无高危漏洞
- [ ] **mypy 运行不 crash**: 类型检查可以运行（允许有 error 但不 fail CI）
- [ ] **detect-secrets**: 测试提交密钥时被 pre-commit 阻止

---

### Task 43.3: 前端覆盖率排除清零 + 覆盖率提升
**状态**: 🟢 已完成
**优先级**: P0
**依赖**: 无

#### 任务描述
当前前端覆盖率排除列表有 14 项，其中包含核心页面（TrainingDetailPage）和核心图表组件（EloChart、PPChart、RadarChart、StatsPanel）。排除这些组件让覆盖率数字失去意义。

需要为所有被排除的组件编写测试，然后清空排除列表，并将覆盖率门禁提升到 90%。

#### 需要修改的文件
- `frontend/vitest.config.ts` — 清空 exclude 列表，提升 thresholds 到 90%
- `frontend/src/components/charts/__tests__/EloChart.test.tsx` — EloChart 渲染 smoke test
- `frontend/src/components/charts/__tests__/PPChart.test.tsx` — PPChart 渲染 smoke test
- `frontend/src/components/charts/__tests__/RadarChart.test.tsx` — RadarChart 渲染 smoke test
- `frontend/src/components/charts/__tests__/StatsPanel.test.tsx` — StatsPanel 渲染 smoke test
- 其他被排除的组件测试

#### 关键实现细节
1. **图表组件测试策略**：图表依赖 canvas/SVG 渲染，在 jsdom 中无法完全渲染。测试重点：
   - 组件能 mount 不 crash
   - props 变化时组件正确更新（rerender）
   - 空数据/undefined props 不 crash
   - 关键 DOM 元素存在性检查（标题、容器 div）
2. **TrainingDetailPage**：已有测试文件，直接从 exclude 移除
3. **覆盖率提升路径**：先写测试确认覆盖率 ≥ 90%，再修改 thresholds

#### 测试要点
- [ ] **所有排除项清零**: vitest.config.ts 的 exclude 列表为空或只含必要的纯配置文件
- [ ] **覆盖率 ≥ 90%**: lines/functions/branches/statements 全部 ≥ 90%
- [ ] **图表 smoke test**: 4 个图表组件 mount 不 crash
- [ ] **TrainingDetailPage 测试**: 现有 12 个测试通过

---

### Task 43.4: 核心算法 Property-Based Testing + 变异测试
**状态**: 🟢 已完成
**优先级**: P1
**依赖**: 无

#### 任务描述
当前核心算法（Elo、PP、TimeFactor）的测试用例是手写边界值，无法穷举。用 hypothesis 做 property-based testing 自动生成海量测试输入验证数学不变量。用 mutmut 做变异测试验证测试的有效性。

#### 需要修改的文件
- `backend/requirements.txt` — 添加 `hypothesis>=6.100`、`mutmut>=2.5`
- `backend/tests/test_elo_property.py` — Elo 公式 property-based testing：
  - 任意 rating 变化后，rating 始终在 [0, 5000] 范围
  - S=1 时 Elo 必增，S=0 时 Elo 必减（给定 P(AC) < 1）
  - K 因子分段函数连续
  - hint_attenuation 始终 ≤ 1.0
  - time_factor 始终在 [0.5, 1.5]
- `backend/tests/test_pp_property.py` — PP 公式 property-based testing：
  - PP 值始终 ≥ 0
  - 相同 rating 的题，WA 越多 PP 越低
  - 相同 WA 数，rating 越高 PP 越高
  - f(wa, t) 单调递减（wa 增加）
- `backend/tests/test_time_factor_property.py` — TimeFactor property-based testing：
  - time_factor ∈ [0.5, 1.5]
  - effective_time < expected_time → time_factor > 1
  - effective_time > expected_time → time_factor < 1
  - S=0 → time_factor = 1.0
  - 罚时线性增加

#### 关键实现细节
1. **hypothesis 策略**：
   - `st.floats(min_value=0, max_value=5000)` — rating
   - `st.floats(min_value=0.0, max_value=1.0)` — S-value / P(AC)
   - `st.integers(min_value=0, max_value=100)` — WA count
   - `st.floats(min_value=0, max_value=1000)` — time in minutes
2. **不变量示例**：
   ```python
   @given(rating=st.floats(0, 5000), k=st.floats(1, 40), s=st.floats(0, 1), expected=st.floats(0.01, 0.99))
   def test_elo_change_bounded(rating, k, s, expected):
       change = k * (s - expected)
       assert abs(change) <= k  # Elo 变化不超过 K
   ```
3. **变异测试**：仅对 elo_service.py、pp_service.py、time_factor_service.py 运行，目标变异分数 > 85%

#### 测试要点
- [ ] **Elo 不变量**: 10000+ 随机输入全部满足不变量
- [ ] **PP 不变量**: 单调性、非负性在随机输入下成立
- [ ] **TimeFactor 不变量**: 值域、方向性在随机输入下成立
- [ ] **变异分数**: 核心算法变异分数 > 85%

---

### Task 43.5: 真实环境集成测试 — 用户生命周期 + 并发安全
**状态**: 🔄 进行中
**优先级**: P1
**依赖**: Task 43.1（统一 fixture 体系）

#### 任务描述
当前所有后端测试基于 SQLite mock，从未验证过 PostgreSQL 环境下的真实行为。添加关键路径的真实集成测试。

#### 需要修改的文件
- `backend/tests/integration/test_full_lifecycle.py` — 完整用户生命周期：
  - 注册 → 登录 → 开始 PvE 挑战 → 提交 AC → 验证 Elo/PP/Token 更新
  - 注册 → 开始训练 session → 解题 → 结束 → 验证 M-Elo 更新
  - 注册 → 查看排行榜 → 验证排名正确
- `backend/tests/integration/test_concurrent_safety.py` — 并发安全：
  - 双扣款防护：并发 10 次 token 扣减，验证余额只减一次
  - 匹配队列竞态：两个用户同时匹配，验证不会匹配到同一个人两次
  - Elo 并发结算：同一用户同时在两个 session 结算，验证最终 Elo 一致

#### 关键实现细节
1. **testcontainers PostgreSQL**：已有 `tests/integration/conftest.py` 中的 session-scoped PostgreSQL container
2. **并发测试**：使用 `asyncio.gather()` 并发执行多个 service 调用
3. **断言策略**：
   - Token 扣减：`initial_tokens - expected_cost == final_tokens`
   - Elo 一致性：最终 Elo 只被更新一次，不是两次
   - 匹配唯一性：每个匹配对只出现一次

#### 测试要点
- [ ] **完整生命周期**: 注册→做题→结算→排行榜，所有数据一致
- [ ] **并发 token**: 10 次并发扣减后余额正确
- [ ] **并发 Elo**: 并发结算后 Elo 只更新一次
- [ ] **匹配唯一性**: 并发匹配不产生重复对
- [ ] **在 CI 中运行**: backend-integration job 使用 PostgreSQL service container

---

### Task 43.6: contest_ws WebSocket 集成测试
**状态**: 🔄 进行中
**优先级**: P1
**依赖**: Task 43.1

#### 任务描述
`contest_ws.py` (124行) 当前覆盖率 23%，是比赛模式核心的实时通信端点。需要用真实 Redis pub/sub 测试。

#### 需要修改的文件
- `backend/tests/integration/test_contest_ws.py` — WebSocket 集成测试：
  - 连接建立和断开
  - 比赛开始广播
  - 解题实时推送
  - 比赛结束广播
  - 多客户端同时连接

#### 关键实现细节
1. **测试工具**：使用 FastAPI TestClient 的 `websocket_connect` 上下文管理器
2. **Redis 替代**：使用 `fakeredis.aioredis.FakeRedis` 或 testcontainers Redis
3. **消息验证**：验证消息格式包含 `type`、`data`、`timestamp` 字段

#### 测试要点
- [ ] **连接建立**: WebSocket 握手成功
- [ ] **消息格式**: 服务端推送消息格式正确
- [ ] **广播**: 一个用户解题，所有连接的客户端收到更新
- [ ] **断开清理**: 客户端断开后不再收到消息
- [ ] **覆盖率**: contest_ws.py 覆盖率从 23% 提升到 > 80%

---

### Task 43.7: 全栈 E2E CI Pipeline + 横切特性矩阵
**状态**: 🔄 进行中
**优先级**: P1
**依赖**: Task 43.5

#### 任务描述
建立完整的全栈 E2E CI pipeline，并实现自动化的横切特性矩阵验证。

#### 需要修改的文件
- `.github/workflows/ci.yml` — 新增 `frontend-integration` job：
  - 使用 Docker Compose 启动后端（FastAPI + PostgreSQL + Redis）
  - 等待所有服务就绪（health check）
  - Playwright 指向 `http://localhost:8000`
  - 运行 `e2e/integration/` 下的 5 个 spec 文件
- `backend/tests/test_crosscut_matrix.py` — 横切特性矩阵自动验证：
  - 遍历所有游戏模式的结算代码
  - 验证每个模式都调用了 Elo/PP/Token/Achievement 相关函数
  - 生成矩阵报告

#### 关键实现细节
1. **Docker Compose CI**：
   ```yaml
   frontend-integration:
     runs-on: ubuntu-latest
     services:
       postgres: ...
       redis: ...
     steps:
       - run: docker compose up -d backend
       - run: npx playwright test --project=integration
   ```
2. **横切矩阵检查**：AST 遍历每个模式的结算函数，查找特定的函数调用模式（如 `elo_service.update_elo`、`pp_service.calculate_pp`、`economy_service.award_tokens`），生成矩阵并断言所有格子都有值

#### 测试要点
- [ ] **全栈 E2E 在 CI 中运行**: 5 个 integration spec 全部通过
- [ ] **横切矩阵完整**: 每个横切特性 × 每个模式 = 都有对应调用
- [ ] **矩阵报告可读**: CI 输出清晰的矩阵表格

---

### Task 43.8: 质量度量体系 — Codecov + 变异分数 + 执行时间
**状态**: ⬜ 待开发
**优先级**: P2
**依赖**: Task 43.2, 43.4

#### 任务描述
建立完整的质量度量可观测体系。

#### 需要修改的文件
- `.github/workflows/ci.yml` — 添加 Codecov 上传步骤、变异测试报告步骤
- `codecov.yml` — Codecov 配置（覆盖率目标、PR 评论）
- `backend/tests/test_quality_metrics.py` — CI 中生成质量度量报告

#### 关键实现细节
1. **Codecov 集成**：
   ```yaml
   - uses: codecov/codecov-action@v4
     with:
       files: backend/coverage.json,frontend/coverage/coverage-final.json
       fail_ci_if_error: false
   ```
2. **变异测试**：仅核心算法文件，CI 中标记为允许失败（不阻塞 PR），但结果上传为 artifact
3. **执行时间追踪**：CI 输出中记录每个测试文件的执行时间，超阈值发出警告

#### 测试要点
- [ ] **Codecov PR 评论**: 每个 PR 自动评论覆盖率变化
- [ ] **变异报告**: 变异测试结果可作为 CI artifact 下载
- [ ] **执行时间**: 测试超时自动警告

---

## 阶段 44: Bug 修复 — 排行榜 UI (已归档)

### Task 44.1: 修复排行榜页面标题不随 Tab 切换更新
**状态**: 🟢 已完成
**优先级**: P0
**依赖**: 无

#### Bug 描述
排行榜页面 (`/ranking`) 切换到 Arena 标签页时，页面标题始终显示 "Global Ranking" 及全球排名描述，未随标签页切换而更新。

#### 根因分析
`RankingPage.tsx` 中 `<PageHeader title={t("title")} description={t("description")} />` 使用了固定的 i18n key `"title"` 和 `"description"`，未根据 `activeTab` 状态动态切换。

#### 需要修改的文件
- `frontend/src/pages/RankingPage.tsx` — PageHeader 组件的 title/description 根据 activeTab 动态切换
- `frontend/src/locales/en/ranking.json` — 新增 `arenaTitle` 和 `arenaDescription` key
- `frontend/src/locales/zh/ranking.json` — 新增对应的中文翻译

#### 关键实现细节
1. PageHeader 的 title 根据 activeTab 切换：
   - `"global"` → `t("title")` / `t("description")`
   - `"arena"` → `t("arenaTitle")` / `t("arenaDescription")`
2. 新增 i18n key：
   - `arenaTitle`: "Arena Ranking" / "竞技场排名"
   - `arenaDescription`: "CodeArena users only, ranked by verified PP or Elo." / "仅 CodeArena 用户，按真实 PP 或 Elo 排名。"

#### 测试要点
- [ ] Global 标签页标题显示 "Global Ranking"
- [ ] Arena 标签页标题显示 "Arena Ranking"
- [ ] 标题随 Tab 切换实时更新
- [ ] 中英文翻译均正确

---

## 阶段 45: Bug 修复与优化 — 渲染/Bot速度/排名模型/结算展示

### Task 45.1: 修复公式重复渲染
**状态**: 🔵 待开始
**优先级**: P0
**依赖**: 无

#### Bug 描述
比赛题目中数学公式（LaTeX/KaTeX）在页面上渲染了两份：一份是 KaTeX 渲染后的可视化公式，另一份是原始 LaTeX 源码或旧 MathJax 渲染结果。

#### 根因分析
`renderCfHtml` 函数（ProblemStatementViewer.tsx:136-178）处理了 `MathJax_Preview` span 的剥离（第 140 行），但**未处理 `.tex-span` 元素**。CF 的 HTML 中，部分题目同时包含 `<span class="tex-span">`（MathJax 已渲染的输出）和 `<script type="math/tex">`（LaTeX 源码）。`renderCfHtml` 将 `<script>` 替换为 KaTeX 输出后，`.tex-span` 中的旧渲染结果仍然存在，导致公式出现两份。

此外，`$$$...$$$` 正则使用非贪婪 `(.*?)`，默认 `.` 不匹配换行符，可能导致跨行公式匹配失败。

#### 需要修改的文件
- `frontend/src/components/ProblemStatementViewer.tsx` — `renderCfHtml` 函数

#### 关键实现细节
1. 在第 140 行 `MathJax_Preview` 剥离之后，增加剥离 `.tex-span` 元素：
   ```typescript
   result = result.replace(/<span class="tex-span"[^>]*>[\s\S]*?<\/span>/g, "");
   ```
2. 将 `$$$...$$$` 的正则改为支持跨行：使用 `[\s\S]` 替代 `.`，或使用 `s` flag
3. 确认 `<script type="math/tex">` 的正则已使用 `[\s\S]`（当前已正确）

#### 测试要点
- [ ] 包含 `$$$...$$$` 公式的题目不重复渲染
- [ ] 包含 `<script type="math/tex">` 的题目不重复渲染
- [ ] 跨行公式能正确匹配和渲染
- [ ] `.tex-span` 元素被正确剥离

---

### Task 45.2: 修复题号重复显示
**状态**: 🔵 待开始
**优先级**: P0
**依赖**: 无

#### Bug 描述
所有题目的标题题号重复两次，如 "B - B. Two Tables" 或 "A. A. Theatre Square"。

#### 根因分析
CF API 返回的 `name` 字段已包含题号前缀（如 "B. Two Tables"），前端渲染时又额外拼接了 `problem.index`，导致重复。

涉及 3 处：
1. **题目列表**（ContestDetailPage.tsx:551）：`{problem.index} - {problem.name}` → "B - B. Two Tables"
2. **题目详情标题**（ProblemStatementViewer.tsx:319）：`{index}. {statement.title}` → "A. A. Theatre Square"（爬虫 `.header .title` 已含题号）
3. **结算摘要**（ContestDetailPage.tsx:753）：同位置 1

#### 需要修改的文件
- `frontend/src/pages/ContestDetailPage.tsx` — 题目列表和结算摘要的题号显示
- `frontend/src/components/ProblemStatementViewer.tsx` — 题目详情标题

#### 关键实现细节
1. 创建工具函数 `stripIndexPrefix`，从 name/title 中移除已有的题号前缀：
   ```typescript
   function stripIndexPrefix(name: string): string {
     return name.replace(/^[A-Z]\d*\.\s*/, "");
   }
   ```
2. ContestDetailPage.tsx:551 改为 `{problem.index} - {stripIndexPrefix(problem.name)}`
3. ProblemStatementViewer.tsx:319 改为 `{index}. {stripIndexPrefix(statement.title)}`
4. ContestDetailPage.tsx:753 同位置 1 的修改

#### 测试要点
- [ ] 题目列表显示 "B - Two Tables" 而非 "B - B. Two Tables"
- [ ] 题目详情标题显示 "A. Theatre Square" 而非 "A. A. Theatre Square"
- [ ] 结算摘要中题号不重复
- [ ] 所有模式的题目页面（Contest、FreePlay、Training、PvE）均不重复

---

### Task 45.3: 移除未解决题目的错误旋转图标
**状态**: 🔵 待开始
**优先级**: P1
**依赖**: 无

#### Bug 描述
比赛页面中每个未解决问题的右侧有一个永久旋转的 Loader2 图标，永远不会消失，给用户造成"一直在加载"的误导。

#### 根因分析
ContestDetailPage.tsx:570-572 对每个 `solved === false` 的题目**无条件显示**旋转 Loader2 图标。该图标语义错误：它不是"加载中"状态指示器，而是被误用为"未解决"状态标记。页面上方已有专门的 Auto-tracking info 区域（第 512-520 行）用旋转 Loader2 表示正在等待 CF 结果，题目列表中的旋转图标是冗余且误导的。

#### 需要修改的文件
- `frontend/src/pages/ContestDetailPage.tsx` — 题目列表行

#### 关键实现细节
1. 移除 ContestDetailPage.tsx:570-572 的无条件 Loader2：
   ```tsx
   // 删除以下代码：
   {!problem.solved && (
     <Loader2 className="size-4 animate-spin text-primary" />
   )}
   ```
2. 已有 `Circle` 图标（第 547 行）表示未解决状态，无需额外指示器
3. 如需表示"等待追踪结果"，可仅在正在追踪时显示（有 activeTracking 状态时），而非所有未解决题目

#### 测试要点
- [ ] 未解决题目不显示旋转图标
- [ ] 已解决题目仍显示绿色 CheckCircle2
- [ ] Auto-tracking info 区域的 loading 状态不受影响
- [ ] 题目列表交互（点击选择题目）正常

---

### Task 45.4: 重构 Bot 做题速度模型 — CF 真实数据拟合
**状态**: 🔵 待开始
**优先级**: P0
**依赖**: 无

#### Bug 描述
比赛机器人做题速度完全不合理，严重过快。所有 bot 在比赛前 15-38 分钟就尝试完所有题目（120 分钟比赛），且不考虑 bot Elo 与题目 rating 的差距。不是所有 bot 都应能做出所有题。

#### 根因分析
当前 tick 范围太小（easy 2-4 ticks × 30s = 1-2 分钟），且 ticks 仅取决于题目难度，不取决于 bot Elo 与题目 rating 的关系。800 Elo 的 bot 和 1600 Elo 的 bot 在同一 800 分题目上花费相同时间。bot 在失败后直接跳到下一题（不重试），进一步加速了进度。

数学验证：7 题（4 easy + 3 medium），平均 53 ticks = 26 分钟全部尝试完，比赛还有 94 分钟无操作。

#### 需要修改的文件
- `backend/app/services/contest_simulation_service.py` — bot tick 计算和模拟逻辑
- `backend/app/core/default_config.py` — difficulty_ticks 配置
- `backend/tests/test_contest_simulation.py` — 现有 1607 行测试中有多处直接测试 `_get_tick_range_for_rating`，函数签名变更后需同步重构

#### 关键实现细节
1. **基于 CF 真实数据拟合模型**：复用 `TimeFactorService`（time_factor_service.py）已有的 CF 数据获取和 rating 分桶逻辑。该服务已实现 `_fetch_contest_submissions`、`_fetch_rating_changes`、`_calculate_focused_times`、`_rating_bucket` 等方法，可直接复用减少约 200 行重复代码。具体方法：
   - 复用 TimeFactorService 的 CF API 数据获取和分桶统计
   - 构建模型：`solve_time = f(bot_elo, problem_rating)`，使用 CF 真实数据拟合参数

2. **CF 拟合参数生命周期**（不阻塞用户请求）：
   - **触发时机**：应用启动时异步预计算（不阻塞用户请求）+ 后台定时任务每日刷新
   - **存储位置**：内存缓存（模块级变量或 `lru_cache`），设置 24 小时过期
   - **降级切换**：参数不存在或过期时，自动使用 Elo 差距缩放公式（关键实现细节第 6 点）
   - **不阻塞用户**：CF 拟合参数计算绝不在 `create_contest` 同步路径中执行

3. **tick 计算改造**：`_get_tick_range_for_rating` 改为基于 bot Elo 和题目 rating 的函数：
   ```python
   def _get_ticks_for_bot_problem(bot_elo, problem_rating, total_minutes, n_problems, tick_interval):
       # 基于 CF 拟合模型计算预期解题时间
       expected_time = cf_fitted_model(bot_elo, problem_rating)
       ticks = int(expected_time * 60 / tick_interval)
       # 添加随机扰动
       ticks = max(1, ticks + random.randint(-ticks//4, ticks//4))
       return ticks
   ```

4. **失败重试**：bot 在 P(AC) 失败后，应有一定概率重试当前题目（而非直接跳到下一题）。高 Elo bot 重试概率更高：
   ```python
   retry_prob = 0.3 * min(1.0, bot_elo / problem_rating)  # 能力越强越倾向重试
   if random.random() < retry_prob:
       # 重新排队当前题目（增加 ticks）
   ```

5. **P(AC) 不确保所有题都能做**：当 bot Elo 远低于题目 rating 时（如 800 Elo 面对 2000 题目），bot 应直接放弃（标记为 impossible），不再尝试：
   ```python
   if problem_rating > bot_elo + 800:  # rating 差距超过 800
       # 该 bot 不会尝试这道题
       continue
   ```

6. **CF 数据拟合 API 调用**：复用 `CFApiService` 已有的速率限制（令牌桶 2s/请求）。需要新增 `contest.list` API 方法。

7. **渐进式方案**（降级方案 — 当 CF 拟合参数不可用时自动使用）：使用 Elo 差距缩放：
   ```python
   elo_ratio = problem_rating / max(bot_elo, 800)
   base_ticks = problem_rating / 60  # 每 60 rating 约 1 tick
   scaled_ticks = base_ticks * elo_ratio * (total_minutes * 60 / tick_interval / n_problems)
   ```

#### 调用方清单
- `tick_simulation()`（contest_simulation_service.py）— 需要使用新的 tick 计算逻辑
- `_simulate_bot_tick()`（contest_simulation_service.py）— `_get_tick_range_for_rating` 的直接调用者（line 802），需传递 `bot_elo` 参数
- `_get_tick_range_for_rating()` — 需要重构或替换
- `generate_bots()` — bot 生成逻辑无需修改

#### 反向集成清单
- 横切特性无影响：Bot 行为变更不影响 Elo/PP/代币/成就的计算公式，只影响 bot 的模拟时间线
- WebSocket 推送频率不变（仍每 30 秒一个 tick）

#### 测试要点
- [ ] 120 分钟比赛中，bot 在比赛全程都有活动（不会在前 30 分钟全部完成）
- [ ] 低 Elo bot 不能做出高 rating 题目
- [ ] 高 Elo bot 做低 rating 题比低 Elo bot 快
- [ ] 不是所有 bot 都能做对所有题目
- [ ] 比赛排行榜呈现自然的渐进增长趋势（而非早期全部完成）
- [ ] 不同比赛等级（beginner/advanced/master）的 bot 行为差异合理
- [ ] 闪电战（60 分钟，4 题）的 bot 行为也合理
- [ ] CF API 不可用时自动降级到 Elo 差距缩放公式
- [ ] bot 重试机制：高 Elo bot 重试概率高于低 Elo bot
- [ ] 极端 Elo 值（bot_elo=0 或 4000）不崩溃

---

### Task 45.5: 修复全球排名 UI — 前xx%与国家重合 + 手机名字不可见
**状态**: 🔵 待开始
**优先级**: P1
**依赖**: 无

#### Bug 描述
5a: 全球排名列表中"前xx%"文字与国家代号在视觉上重叠。5b: 手机端访问时玩家名字被压缩到几乎不可见。

#### 根因分析
**5a**: grid 最后一列仅 3rem 宽，无法容纳"前xx%"+图标（约 60-70px），溢出到国家列。涉及 GlobalRankingPage.tsx 和 RankingPage.tsx 的所有 grid-cols 定义（每文件 3 处）。

**5b**: 固定列总宽 264px（3.5+5+5+3rem），在 320px 手机上名字列被压缩到 0px。GlobalRankingPage 缺少 `overflow-x-auto`。

#### 需要修改的文件
- `frontend/src/pages/GlobalRankingPage.tsx` — grid 列定义、响应式布局
- `frontend/src/pages/RankingPage.tsx` — 同上

#### 关键实现细节
1. **修复 5a**：将最后一列从 `3rem` 增大到 `5.5rem`，同步更新表头和数据行的所有 grid-cols 模板（每文件 3 处）：
   - 修改前：`grid-cols-[3.5rem_1fr_5rem_5rem_3rem]`
   - 修改后：`grid-cols-[3.5rem_1fr_5rem_5rem_5.5rem]`
   - Arena tab 同理：末列从 `3rem` → `5.5rem`

2. **修复 5b**：添加响应式 grid-cols，手机端隐藏次要列：
   ```tsx
   // 手机端 3 列：排名 + 名字 + PP
   // sm+ 端 5 列：排名 + 名字 + PP + 国家 + 前xx%
   className="grid grid-cols-[2.5rem_1fr_4rem] sm:grid-cols-[3.5rem_1fr_5rem_5rem_5.5rem]"
   ```
   - 国家列和前xx%列在手机端使用 `hidden sm:flex`
   - 给 GlobalRankingPage 添加 `overflow-x-auto` 兜底

3. **同步修改位置**（每文件 3 处 grid-cols，两个文件共 6 处）：
   - 加载态 skeleton 行
   - 表头行
   - 数据行

#### 测试要点
- [ ] "前xx%"和国家代号不重叠
- [ ] 手机端玩家名字可读（至少显示部分+省略号）
- [ ] Desktop 端布局不受影响
- [ ] 两个页面（GlobalRankingPage 和 RankingPage）表现一致
- [ ] Arena tab 和 Global tab 都正确

---

### Task 45.6: 重构全球排名估算 — 回归+CDF 模型
**状态**: 🔵 待开始
**优先级**: P1
**依赖**: 无

#### Bug 描述
玩家全球排名基于采样用户（~1600）排名，而非以 CF 全量用户（~30万）为基数估算。排名百分位严重失真。

#### 根因分析
1. `ranking.py:30` 中 `total = len(items)` — items 长度 = Arena 用户 + 采样 CF 用户（几千），而非 CF 全量用户
2. `cf_ranking_service.py:539` 管线获取了 `rated_list`（全量），但 `len(rated_list)` 从未记录或传递
3. `auth.py:288-312` pp-rank 端点的 `total_users` 仅统计 Arena 活跃用户
4. 排名展示为"在采样用户中的排名"而非"估算的全球排名"

#### 需要修改的文件
- `backend/app/services/cf_ranking_service.py` — 管线增加全量用户数存储、CDF 构建、PP→rating 反向转换
- `backend/app/models/cf_pipeline_metadata.py` — 新建模型存储管线元数据（替代在 CFSampleUser 中加特殊行）
- `backend/migrations/versions/xxxx_add_cf_pipeline_metadata_table.py` — 新建 migration
- `backend/app/api/v1/ranking.py` — 排名 API 使用 CDF 估算百分位，每个 CA 用户附带 estimated_percentile
- `backend/app/api/v1/auth.py` — pp-rank 端点使用全球基数，增加 calibrated 字段
- `frontend/src/types/index.ts` — PPRankData、RankingPageData 类型同步更新
- `frontend/src/pages/GlobalRankingPage.tsx` — 百分位展示改用后端返回值
- `frontend/src/pages/ProfilePage.tsx` — 适配 pp-rank 新字段
- `frontend/src/locales/zh/ranking.json` — 新增"排名数据未校准"翻译
- `frontend/src/locales/en/ranking.json` — 新增"Ranking data not calibrated"翻译

#### 关键实现细节
1. **新建 `cf_pipeline_metadata` 表**（明确方案，不用 CFSampleUser 特殊行）：
   ```python
   class CFPipelineMetadata(Base):
       __tablename__ = "cf_pipeline_metadata"
       id: Mapped[int] = mapped_column(primary_key=True)
       sample_batch: Mapped[int]
       total_rated_users: Mapped[int]         # CF 全量 rated 用户数
       rating_histogram: Mapped[dict]          # {bucket_midpoint: count}
       regression_coefficients: Mapped[list]   # 复用现有回归结果
       created_at: Mapped[datetime]
   ```
   每次管线运行时写入一行，查询时取最新 batch 的记录。

2. **PP→rating 反向转换**（CDF 估算链路的关键环节）：当前回归模型是 `rating → PP` 的正向映射（多项式 degree=2），需实现反向映射。由于 degree=2（二次多项式），使用求根公式：
   ```python
   def _pp_to_rating(pp: float, coeffs: list[float]) -> int | None:
       """反向求解 PP 对应的等效 CF rating。coeffs = [a2, a1, a0]，即 a2*x^2 + a1*x + a0 = pp"""
       a2, a1, a0 = coeffs
       # a2*x^2 + a1*x + (a0 - pp) = 0
       discriminant = a1**2 - 4*a2*(a0 - pp)
       if discriminant < 0:
           return None
       # 取正根（rating > 0）
       x = (-a1 + math.sqrt(discriminant)) / (2*a2)
       return max(0, round(x))
   ```
   如果 degree ≠ 2（配置可变），降级使用二分搜索（rating 范围 0-5000）。

3. **构建 CDF 函数**：
   ```python
   def _build_cdf(rating_histogram: dict[int, int], total_users: int) -> Callable[[int], float]:
       """Given rating histogram, return function: rating -> percentile (0-1)."""
       sorted_buckets = sorted(rating_histogram.items())
       cumulative = 0
       breakpoints = []
       for bucket_mid, count in sorted_buckets:
           cumulative += count
           breakpoints.append((bucket_mid, cumulative / total_users))
       def cdf(rating: int) -> float:
           # 低于最低桶 → percentile = 该桶以下占比
           # 高于最高桶 → percentile = 1.0
           # 中间值 → 线性插值
           ...
       return cdf
   ```
   边界处理：rating < 800 时返回 1.0（最低 rank），rating > 4000 时返回 0.0（最高 rank）。PP=0 的用户不估算全球排名（返回 None）。

4. **排名 API 改造**：
   - `GET /ranking/global`：
     - total 改为 CF 全量用户数 + Arena 用户数
     - 每个 CA 用户条目附带 `estimated_percentile: float | None` 字段（通过 PP→rating→CDF 计算）
     - CF 采样用户的百分位也通过 CDF 估算（用其 cf_rating 直接查 CDF）
     - 响应增加 `calibrated: bool` 字段（metadata 存在时为 true）
     - 保持混合列表展示（但 total 和 percent 基于全球基数）
   - `GET /auth/pp-rank`：
     - `total_users` 改为 CF 全量用户数 + Arena 用户数
     - 用户排名通过 CDF 估算
     - 增加 `calibrated: bool` 字段

5. **前端适配**：
   - GlobalRankingPage.tsx 的百分位不再使用前端公式 `((computedRank / total) * 100)`，改为使用后端返回的 `estimated_percentile`
   - ProfilePage.tsx 的 top_percent 使用 pp-rank 返回值（语义从"Arena 百分位"变为"全球百分位"）
   - 当 `calibrated === false` 时，显示降级提示"排名数据未校准"（tooltip 或 inline 文本）

6. **降级方案**：管线未运行或无元数据时：
   - `calibrated = false`
   - `total_users` 回退到 Arena 用户数
   - 排名计算回退到当前行为
   - 前端显示降级提示

#### 调用方清单
- `GET /ranking/global`（ranking.py）— 需使用 CDF 估算百分位
- `GET /ranking/arena`（ranking.py）— 不受影响（Arena 专用）
- `GET /auth/pp-rank`（auth.py）— 需使用全球基数
- 前端 `GlobalRankingPage.tsx` — 如 API 返回格式有变需适配

#### 反向集成清单
- 无横切特性影响：排名估算逻辑独立于 Elo/PP/代币/成就的计算

#### 测试要点
- [ ] 管线运行后 `total_rated_users` 被正确存储
- [ ] CDF 函数在边界值（rating 800 和 4000）返回合理百分位
- [ ] Arena 用户的全球排名通过模型估算，而非简单排序位置
- [ ] 全球排行榜 total 显示 CF 全量用户数量级（~30万）
- [ ] pp-rank 端点返回的全球排名和百分位基于 CF 全量用户
- [ ] 降级情况（管线未运行）下回退到 Arena 用户数，不报错

---

### Task 45.7: 增强比赛结算展示 — 分组卡片布局
**状态**: 🔵 待开始
**优先级**: P1
**依赖**: 无

#### Bug 描述
比赛结算页面只显示 elo 变化值（如 "+15"），缺少 PP、global elo 绝对值、m elo 和排名等完整信息。应该包含这些数据并采用合理的布局避免臃肿。

#### 根因分析
**后端**：`ContestResult` schema（contest.py:92-108）只返回 `elo_change` 差值，缺少 `elo_before`、`elo_after`、`pp_before`、`pp_after`、`pp_change`、`melo_summary`、`rank` 等字段。虽然 `_settle_with_pr` 方法中计算了 `elo_before` 和 `elo_after`，但没有传回 ContestResult。

**前端**：ContestDetailPage.tsx:664-692 只渲染 4 个简单卡片（解题数、总题数、提交次数、elo 变化），缺少其他指标。

#### 需要修改的文件
- `backend/app/schemas/contest.py` — ContestResult schema 新增字段
- `backend/app/services/contest_service.py` — `end_contest` 和 `get_contest_result` 填充新字段
- `frontend/src/types/index.ts` — ContestResult 类型同步更新
- `frontend/src/pages/ContestDetailPage.tsx` — 结算区域重新设计为分组卡片布局

#### 关键实现细节
1. **后端 Schema 扩展**（contest.py）：
   ```python
   class ContestResult(BaseModel):
       # ... 现有字段 ...
       elo_before: int | None = None
       elo_after: int | None = None
       pp_before: float | None = None
       pp_after: float | None = None
       pp_change: float | None = None
       rank: int | None = None         # 本次比赛排名
       total_participants: int | None = None
       melo_changes: list[dict] | None = None  # [{tag, before, after, change}]
   ```

2. **后端数据填充**（contest_service.py）：
   - 在 `end_contest`（line 707-722）和 `get_contest_result` 中：
     - `elo_before`：从 EloHistory 查询结算前值（或 `user.elo - session.elo_change`）
     - `elo_after`：从当前 user.elo 获取
     - **PP 前值**：采用方案 B（不修改 ContestSession，无需 migration）— 在 `end_contest` 开始时快照 `user.pp` 作为 `pp_before`（此时 PP 已包含比赛中所有题目的更新），结算完成后 `pp_after = user.pp`（此时两者相同，因为比赛结算不再修改 PP）。若需展示"比赛期间 PP 变化"，改为从 PPRecord 查询本次比赛题目贡献的 PP 总和（复用 `_settle_with_pr` 中成就检测的逻辑，contest_service.py:1279-1290）
     - `rank`：从 leaderboard 排序得到（`end_contest` 已有此逻辑，contest_service.py:682-689）。`get_contest_result` 需新增 leaderboard 查询或从 bot 表计算
     - `total_participants`：bot 数量 + 1
     - **M-Elo 变化**：在 `submit_problem` 调用 `batch_update_melo_for_problem` 后，将返回的 `dict[str, int]`（tag → change）存入 `ContestProblemRecord` 的新 JSON 字段 `melo_changes`。结算时汇总所有题目的 `melo_changes`，从 `UserTagElo` 当前值减去累计变化得到 `before`。需要在 `ContestProblemRecord` 模型中新增 `melo_changes` JSON 字段并创建 migration

3. **前端布局设计**（分组卡片）：
   ```
   ┌──────────────────────────────────────────────────────┐
   │                    比赛结果概览                        │
   │  解题 3/7  │  提交 5 次  │  排名 #12/51  │  ⏱ 45min  │
   ├─────────────────────────┬────────────────────────────┤
   │     评分变化             │       PP 变化              │
   │  Global Elo             │  PP                        │
   │  1520 → 1535 (+15)      │  42.5 → 45.2 (+2.7)      │
   │                         │                            │
   │  Performance Rating     │  M-Elo 变化                │
   │  1680                   │  dp: 1400→1420 (+20)      │
   │                         │  math: 1300→1310 (+10)    │
   └─────────────────────────┴────────────────────────────┘
   ```
   - 顶部一行：解题数、提交数、排名、用时（4 个小卡片）
   - 下方左右两组：
     - 左组：Global Elo（前值→后值，变化高亮）+ Performance Rating
     - 右组：PP（前值→后值，变化高亮）+ M-Elo 各 tag 变化摘要
   - 响应式断点（使用 Tailwind）：
     - 移动端（<sm）：单列堆叠，所有卡片上下排列
     - 平板/桌面（sm+）：顶部统计行 `grid-cols-2 sm:grid-cols-4`，下方 `grid-cols-1 sm:grid-cols-2`
   - 奖牌和成就信息保留在现有位置

#### 调用方清单
- `GET /contest/{id}/result`（contest.py）— API 返回扩展字段
- `POST /contest/{id}/end`（contest.py）— 结算时填充新字段
- `contestStore.ts` — 前端数据接收

#### 反向集成清单
- PP 前值需要从 start_contest 开始记录
- M-Elo 变化需要查询 melo_history 表（如存在）或从 session 的题目记录反推
- 代币奖励信息可考虑一并展示（如果当前未展示）

#### 测试要点
- [ ] 结算页面显示 Global Elo 绝对值（如 1520 → 1535）
- [ ] 结算页面显示 PP 绝对值和变化量
- [ ] 结算页面显示 Performance Rating
- [ ] 结算页面显示本次比赛排名
- [ ] 结算页面显示 M-Elo 各 tag 变化摘要
- [ ] 手机端布局合理（左右组改为上下）
- [ ] 奖牌和成就信息正常显示
- [ ] 0 提交惩罚情况也正确显示
