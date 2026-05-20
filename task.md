# Code Arena - 项目任务清单

> 需求文档详见 [requirements.md](requirements.md)
> 阶段 1-14 全部 🟢 已完成（2025-05-19 ~ 2026-05-20），归档至 [docs/archive/task_v1.0.md](docs/archive/task_v1.0.md)
> 以下为 V1.1 需求更新任务（基于审计节点 B 审计报告，2026-05-20）。

---

## 阶段 15: 核心算法升级

### Task 15.1: K 因子分段函数
**状态**: 🟢 已完成
**优先级**: P0
**依赖**: 无

#### 任务描述
将 Elo 计算中的固定 K=32 重构为基于用户历史提交总数的分段函数。

**需求公式** (requirements.md Section 3.2):
```
if N_sub ≤ 20:   K = 40
if N_sub ≥ 100:  K = 20
if 20 < N_sub < 100: K = 40 - (N_sub - 20) × 0.25  [线性插值]
```

**需要修改的文件**:
- `backend/app/services/elo_service.py` — `calculate_new_rating` 方法签名需接受 `submission_count` 参数，内部调用分段函数计算 K
- `backend/app/core/default_config.py` — `elo` 配置新增 `k_newbie: 40`, `k_veteran: 20`, `k_newbie_threshold: 20`, `k_veteran_threshold: 100`
- 所有调用 `calculate_new_rating` / `calculate_challenge_elo` 的调用方，需传入用户提交总数

**关键实现细节**:
1. 新增 `calculate_k_factor(submission_count: int, config: dict) -> float` 方法
2. `submission_count` 的计算：查询 `training_problem_records` + `challenge_sessions` + `contest_problem_records` 中该用户的所有提交记录总数（或使用 pp_records 的数量作为近似）
3. 配置项通过 `system_config` 表读取，保留 fallback 默认值
4. 管理员后台配置页面需展示新增的 K 因子参数

#### 测试要点（防Workaround验证清单）
- [ ] **K 分段 - ≤20次**: 提交 10 次的用户 K=40
- [ ] **K 分段 - ≥100次**: 提交 150 次的用户 K=20
- [ ] **K 分段 - 线性插值**: 提交 60 次的用户 K=30（精确验证）
- [ ] **K 分段 - 边界值 20**: 提交 20 次 K=40
- [ ] **K 分段 - 边界值 100**: 提交 100 次 K=20
- [ ] **配置可热更新**: 管理员修改 K 参数后新结算立即使用新值
- [ ] **默认 fallback**: system_config 无对应配置时使用默认值
- [ ] **现有结算不破坏**: 挑战/训练/比赛结算仍正确工作，只是 K 值变为动态
- [ ] **Elo 历史记录**: K 值变化后 elo_history 仍正确记录

#### 验收标准
1. K 因子根据提交数动态计算，公式精确匹配需求
2. 所有调用方正确传入 submission_count
3. 配置可通过管理员后台热更新
4. 现有功能无回归

---

### Task 15.2: S 值分级（完美 AC / 失误 AC）
**状态**: 🟢 已完成
**优先级**: P1
**依赖**: Task 15.1

#### 任务描述
在 Elo 结算中区分"完美 AC（首次提交通过）"和"失误 AC（含错误记录）"，实现需求中的 S 值分级。

**需求公式** (requirements.md Section 3.3):
```
完美 AC (首次提交通过): S = 1.0
失误 AC (含错误记录): S = max(0.7, 1.0 - 0.05 × N_errors)
放弃/未通过: S = 0.0
```
N_errors 包含 WA、TLE、RE、MLE 等所有非通过状态，等权计算。

**需要修改的文件**:
- `backend/app/services/elo_service.py` — 新增 `calculate_s_value(is_first_ac: bool, error_count: int) -> float` 方法
- `backend/app/services/challenge_service.py` — `_settle_challenge` 需计算 N_errors 并传入 S 值计算，不再硬编码 0/0.5/1.0
- `backend/app/services/training_service.py` — 训练结算同理
- `backend/app/services/contest_service.py` — 比赛结算同理

**关键实现细节**:
1. S 值取代现有的 `actual_score`（二元 0/1），变为连续值
2. 挑战模式中，两人各自有独立的 S 值（根据各自的错误次数）
3. PvP 挑战的胜负判定不变（AC 方胜），但 Elo 变化幅度受 S 值影响
4. 失误 AC 的最低 S=0.7（最多扣 30%）

#### 测试要点（防Workaround验证清单）
- [ ] **完美 AC**: 首次提交通过 S=1.0，Elo 变化 = K × (1.0 - P(AC))
- [ ] **失误 AC 1 次 WA**: S = max(0.7, 0.95) = 0.95
- [ ] **失误 AC 6 次 WA**: S = max(0.7, 0.70) = 0.70
- [ ] **失误 AC 10 次 WA**: S = max(0.7, 0.50) = 0.70（下限保护）
- [ ] **未通过**: S = 0.0
- [ ] **TLE/RE/MLE 计入**: 3次TLE+2次WA = N_errors=5, S = max(0.7, 0.75) = 0.75
- [ ] **挑战模式双端**: 两玩家各自根据错误次数独立计算 S
- [ ] **训练模式**: 训练提交同样应用 S 值
- [ ] **比赛模式**: 比赛提交同样应用 S 值

#### 验收标准
1. S 值公式精确匹配需求（max(0.7, 1.0 - 0.05 × N_errors)）
2. 所有模式（挑战/训练/比赛）正确应用 S 值
3. 完美 AC 和失误 AC 有明确的 Elo 差异
4. 提示衰减仍正常叠加（在 S 值之后应用）

---

### Task 15.3: PP 表现因子
**状态**: 🟢 已完成
**优先级**: P0
**依赖**: 无

#### 任务描述
在 PP 基础分计算中融入表现因子 `f(wa, t)`，使 PP 同时反映题目难度和做题质量。

**需求公式** (requirements.md Section 3.4.1):
```
base(rating) = 10 × √((problem_rating - 800) / 100)    [rating < 800 时为 0]
f(wa, t) = (1 - 0.03 × wa_count) × max(0.6, 1 - 0.01 × t_minutes)
P_i = base(rating) × f(wa, t)
```

**需要修改的文件**:
- `backend/app/models/pp_record.py` — 新增字段：`wa_count: int`, `time_spent_minutes: float`, `performance_factor: float`, `final_pp: float`（重命名 `base_pp` 或新增 `final_pp`）
- `backend/app/services/pp_service.py`:
  - `calculate_base_pp` → 新增 `calculate_performance_pp` 方法，接受 `wa_count` 和 `time_spent_minutes`
  - `record_pp` 方法签名需接受 `wa_count` 和 `time_spent` 参数
  - `aggregate_total_pp` 使用 `final_pp`（而非 `base_pp`）进行聚合
- 新增 Alembic 迁移
- 所有调用 `record_pp` 的地方需传入 wa_count 和 time_spent

**关键实现细节**:
1. `base_pp` 保留（纯难度部分），新增 `final_pp` = `base_pp × performance_factor`
2. `performance_factor` = `(1 - 0.03 × wa_count) × max(0.6, 1 - 0.01 × t_minutes)`
3. 聚合时按 `final_pp` 降序排列（而非 `base_pp`）
4. 已有记录不受影响（`performance_factor` 默认 1.0，`final_pp` 默认等于 `base_pp`）
5. 配置参数（0.03, 0.01, 0.6）通过 system_config 管理

#### 测试要点（防Workaround验证清单）
- [ ] **表现因子 - 完美表现**: wa=0, t=0min → f=1.0, P_i=base(rating)
- [ ] **表现因子 - 多次错误**: wa=10, t=0min → f=(1-0.3)×1.0=0.7
- [ ] **表现因子 - 长时间**: wa=0, t=40min → f=1.0×max(0.6, 0.6)=0.6
- [ ] **表现因子 - 下限保护**: wa=20, t=60min → f=(1-0.6)×0.6=0.24 → 实际应触发 max(0.6) → 重新计算：(0.4)×max(0.6, 0.4)=0.4×0.6=0.24 — 等等，下限 0.6 是对时间因子而言
- [ ] **精确计算**: wa=5, t=30min → f=(1-0.15)×max(0.6, 1-0.30)=0.85×0.70=0.595
- [ ] **rating=1200, wa=0, t=0**: P_i = 20 × 1.0 = 20.0
- [ ] **rating=2000, wa=3, t=15**: P_i = 34.64 × (0.91 × 0.85) = 34.64 × 0.7735 ≈ 26.79
- [ ] **聚合使用 final_pp**: Total_PP 排序和加权使用 final_pp 而非 base_pp
- [ ] **旧记录兼容**: 无 wa_count/time_spent 的旧记录 performance_factor=1.0
- [ ] **DB 迁移成功**: 新字段有默认值，迁移不破坏现有数据
- [ ] **提示不影响 PP**: 使用提示后 PP 计算仍不考虑提示

#### 验收标准
1. PP 表现因子公式精确匹配需求
2. 聚合使用 final_pp（含表现因子的值）
3. 旧数据兼容（默认 performance_factor=1.0）
4. 配置参数可热更新

---

## 阶段 16: M-Elo 系统

### Task 16.1: M-Elo 数据模型与服务层
**状态**: 🟢 已完成
**优先级**: P0
**依赖**: 无

#### 任务描述
实现 M-Elo（Multi-Elo）子系统：为每个用户-标签组合维护独立的子域等级分。

**需要新增的文件/修改**:

1. **数据模型** — 新增 `user_tag_elo` 表：
   ```
   user_tag_elo:
     id (UUID, PK)
     user_id (UUID, FK -> users.id, NOT NULL)
     tag (VARCHAR(100), NOT NULL)  -- CF tag 名称，如 "dp", "graphs"
     elo (INTEGER, DEFAULT 1200)   -- 该标签的 M-Elo
     total_submissions (INTEGER, DEFAULT 0)
     first_ac_at (TIMESTAMP, NULLABLE)  -- 首次 AC 时间，NULL 表示护盾激活中
     created_at (TIMESTAMP)
     updated_at (TIMESTAMP)
     UNIQUE(user_id, tag)
   ```

2. **Alembic 迁移** — 新建迁移文件

3. **服务层** — 新增 `backend/app/services/melo_service.py`:
   - `get_or_create_melo(db, user_id, tag) -> UserTagElo` — 获取或创建（初始继承 Global Elo）
   - `get_all_melos(db, user_id) -> list[UserTagElo]` — 获取用户所有标签 M-Elo
   - `update_melo(db, user_id, tag, elo_change)` — 更新 M-Elo
   - `is_shield_active(db, user_id, tag) -> bool` — 检查护盾状态（first_ac_at is NULL）
   - `deactivate_shield(db, user_id, tag)` — 首次 AC 后解除护盾

4. **API 端点** — 新增/修改 `backend/app/api/v1/training.py`:
   - `GET /training/melo` — 获取用户所有标签 M-Elo（用于雷达图）

5. **配置** — `default_config.py` 新增 M-Elo 相关配置：
   ```python
   "melo": {
       "initial_elo_inherit_global": true,
       "training_global_coefficient": 0.5,
       "training_melo_coefficient": 2.0,
   }
   ```

**关键实现细节**:
- M-Elo 初始值 = 用户当前 Global Elo（不是固定 1200）
- 护盾状态：`first_ac_at IS NULL` 表示护盾激活
- `total_submissions` 字段用于 K 因子分段计算（与 Global 的提交数分开还是合并？合并更简单——统一使用 Global 提交总数）

#### 测试要点（防Workaround验证清单）
- [ ] **创建 M-Elo**: 新用户-标签组合创建时 elo = 用户当前 Global Elo
- [ ] **唯一约束**: 同一用户同一标签只有一条记录
- [ ] **获取全部**: `get_all_melos` 返回用户所有标签记录
- [ ] **更新 Elo**: `update_melo` 正确增减 M-Elo
- [ ] **护盾 - 未 AC**: 新标签 `first_ac_at` 为 NULL，`is_shield_active` 返回 True
- [ ] **护盾 - 已 AC**: 首次 AC 后 `first_ac_at` 非空，`is_shield_active` 返回 False
- [ ] **护盾解除**: `deactivate_shield` 设置 `first_ac_at` 为当前时间
- [ ] **API 端点**: GET /training/melo 返回正确数据格式
- [ ] **DB 迁移成功**: 新表创建、索引正确
- [ ] **配置读取**: M-Elo 参数从 system_config 读取

#### 验收标准
1. M-Elo 数据模型完整（表 + 迁移）
2. CRUD 服务正确实现
3. 护盾状态判断准确
4. API 端点可访问

---

### Task 16.2: 学习护盾机制
**状态**: 🟢 已完成
**优先级**: P1
**依赖**: Task 16.1, Task 15.1

#### 任务描述
实现专题训练中的学习护盾：新标签首次 AC 前不扣 Elo。

**需求规则** (requirements.md FR-3.3):
- 用户首次接触的标签（`first_ac_at` IS NULL），开启护盾
- 护盾状态下，提交失败或主动放弃**不扣除** M-Elo 和 Global Elo
- 护盾在该标签首次 AC 后自动解除

**需要修改的文件**:
- `backend/app/services/training_service.py`:
  - `_calculate_training_elo` — 结算前检查护盾状态
  - `submit_problem` — AC 时调用 `deactivate_shield`
- `backend/app/services/melo_service.py` — 护盾相关方法已在 Task 16.1 中实现

**关键逻辑**:
1. 用户在训练中提交 → 检查该标签护盾状态
2. 如果护盾激活且 AC → 正常加 Elo + 解除护盾
3. 如果护盾激活且失败/放弃 → Elo 不变（跳过扣分）
4. 如果护盾已解除 → 正常结算

#### 测试要点（防Workaround验证清单）
- [ ] **护盾 - 失败不扣分**: 新标签提交失败，Global Elo 和 M-Elo 不变
- [ ] **护盾 - 放弃不扣分**: 新标签放弃，Elo 不变
- [ ] **护盾 - AC 正常加分**: 新标签首次 AC，Elo 正常增加
- [ ] **护盾 - AC 后解除**: 首次 AC 后护盾消失
- [ ] **护盾解除后失败扣分**: 第二次提交失败，正常扣分
- [ ] **多标签独立护盾**: 标签 A 护盾解除不影响标签 B
- [ ] **Elo 历史记录**: 护盾跳过的结算不产生 elo_history 记录（或记录 reason="shield_skipped"）

#### 验收标准
1. 护盾逻辑精确匹配需求
2. 各标签护盾独立
3. 护盾跳过结算时无 Elo 变化
4. 首次 AC 后护盾正确解除

---

### Task 16.3: 专题训练权重极化结算
**状态**: 🟢 已完成
**优先级**: P1
**依赖**: Task 16.1, Task 15.1

#### 任务描述
修改专题训练的 Elo 结算：Global Elo 增长系数 0.5，M-Elo 增长系数 2.0。

**需求规则** (requirements.md FR-3.4):
- 专题训练 AC 题目时，Global Elo 变化量 × 0.5
- 专题训练 AC 题目时，对应标签 M-Elo 变化量 × 2.0

**需要修改的文件**:
- `backend/app/services/training_service.py`:
  - `_calculate_training_elo` — 分别计算 Global Elo 变化（×0.5）和 M-Elo 变化（×2.0）
  - `submit_problem` — 同时更新 Global Elo 和 M-Elo

**关键逻辑**:
1. 计算基础 Elo 变化 Δ = K × (S - P(AC))
2. Global Elo 变化 = Δ × 0.5
3. M-Elo 变化 = Δ × 2.0（P(AC) 使用 M-Elo 计算）
4. 两者的 P(AC) 分别使用对应的 Rating 值

#### 测试要点（防Workaround验证清单）
- [ ] **Global Elo 衰减**: 训练 AC 后 Global Elo 增长为正常值的 50%
- [ ] **M-Elo 增强**: 训练 AC 后 M-Elo 增长为正常值的 200%
- [ ] **Global Elo 扣分也衰减**: 训练失败时 Global Elo 扣分也为 50%
- [ ] **M-Elo P(AC)**: M-Elo 的 P(AC) 使用 M-Elo 值而非 Global Elo
- [ ] **系数可配置**: 0.5 和 2.0 通过 system_config 管理
- [ ] **Elo 历史记录**: 分别记录 Global 和 M-Elo 的变化

#### 验收标准
1. 权重极化系数精确匹配需求（Global ×0.5, M-Elo ×2.0）
2. Global Elo 和 M-Elo 分别使用各自的 Rating 值
3. 系数可配置

---

### Task 16.4: 标签分流抽取
**状态**: 🟢 已完成
**优先级**: P1
**依赖**: Task 16.1

#### 任务描述
修改专题训练的题目抽取逻辑：基于用户在该特定标签的 M-Elo，而非 Global Elo。

**需求规则** (requirements.md FR-3.2):
- 题目抽取基于用户在该特定标签的 M-Elo
- 区间规则与 PvE 随机挑战一致：[M-Elo - 100, M-Elo + 200]

**需要修改的文件**:
- `backend/app/services/training_service.py`:
  - `get_topic_detail` 或新增 `get_adaptive_problem` 方法
  - 题目抽取使用 M-Elo 而非 Global Elo

**关键逻辑**:
1. 获取用户在该标签的 M-Elo
2. 在 [M-Elo - 100, M-Elo + 200] 范围内随机抽取未解题
3. 兜底策略与 PvE 模式一致（最多 3 轮扩大）

#### 测试要点（防Workaround验证清单）
- [ ] **使用 M-Elo**: 抽取区间基于 M-Elo 值
- [ ] **区间正确**: [M-Elo - 100, M-Elo + 200]
- [ ] **兜底策略**: 范围内无题时逐步扩大
- [ ] **未解题过滤**: 不抽取已解决的题目
- [ ] **M-Elo 动态**: 随着训练 M-Elo 变化，后续题目难度跟随变化

#### 验收标准
1. 题目抽取基于 M-Elo
2. 区间和兜底策略正确
3. 随 M-Elo 动态调整

---

## 阶段 17: PvE 随机挑战与越级奖励

### Task 17.1: PvE 单人随机挑战后端
**状态**: 🟢 已完成
**优先级**: P1
**依赖**: Task 15.1, Task 15.3

#### 任务描述
新增 PvE 单人随机挑战模式：用户无对手，系统基于 Global Elo 随机分配未解题。

**需求规则** (requirements.md FR-2.1):
- 题目抽取区间：[Elo - 100, Elo + 200]
- 兜底：逐步扩大范围最多 3 轮
- 无对手，单人解题

**需要新增/修改的文件**:

1. **数据模型** — 新增 `pve_challenge_sessions` 表（或复用现有 challenge_sessions 并加 mode 字段）:
   ```
   pve_challenge_sessions:
     id (UUID, PK)
     user_id (UUID, FK -> users.id)
     problem_id (VARCHAR(50))
     problem_rating (INTEGER)
     status (VARCHAR(20)) -- 'active', 'completed', 'quit'
     error_count (INTEGER, DEFAULT 0)  -- WA/TLE/RE/MLE 次数
     time_spent (FLOAT) -- 秒
     hints_used (INTEGER, DEFAULT 0)
     elo_change (INTEGER)
     pp_change (FLOAT)
     created_at (TIMESTAMP)
     completed_at (TIMESTAMP)
   ```

2. **服务层** — 新增 `backend/app/services/pve_challenge_service.py`:
   - `start_challenge(db, user, cf_service)` — 随机抽题并创建会话
   - `submit_result(db, session_id, result)` — 提交结算
   - `quit_challenge(db, session_id)` — 放弃
   - `_select_random_problem(user_elo, cf_service, solved_problems)` — 题目抽取（含 3 轮兜底）

3. **API 端点** — 新增 `backend/app/api/v1/pve_challenge.py`:
   - `POST /pve-challenge/start` — 开始挑战
   - `GET /pve-challenge/{id}` — 获取详情
   - `POST /pve-challenge/{id}/submit` — 提交结果
   - `POST /pve-challenge/{id}/quit` — 放弃
   - `GET /pve-challenge/history` — 历史记录

4. **Alembic 迁移**

#### 测试要点（防Workaround验证清单）
- [ ] **题目区间**: 抽取的题目 rating 在 [Elo-100, Elo+200] 范围内
- [ ] **未解题过滤**: 不抽取已解决的题目
- [ ] **兜底第1轮**: 无题时扩大到 [Elo-200, Elo+300]
- [ ] **兜底第2轮**: 扩大到 [Elo-300, Elo+400]
- [ ] **兜底第3轮**: 仍无题返回提示"暂无合适题目"
- [ ] **结算 - AC**: 正确计算 Elo（使用 S 值）、PP（使用表现因子）、代币
- [ ] **结算 - 放弃 0 提交**: Elo 完全不变
- [ ] **结算 - 放弃 1-2 提交**: Elo 降 5~10（随机值）
- [ ] **结算 - 放弃 3+ 提交**: 按正常失败处理（非固定 -5~-10）
- [ ] **会话状态机**: active → completed / quit，不可逆
- [ ] **同时仅一个活跃会话**: 有活跃会话时不允许开始新挑战

#### 验收标准
1. PvE 挑战全流程完整（开始→解题→结算/放弃）
2. 题目抽取区间和兜底策略正确
3. Elo/PP/代币结算正确（使用新公式）
4. API 端点完整可用

---

### Task 17.2: PvE 挑战前端页面
**状态**: 🟢 已完成
**优先级**: P1
**依赖**: Task 17.1

#### 任务描述
实现 PvE 随机挑战的前端页面和交互流程。

**需要新增/修改的文件**:
- `frontend/src/pages/challenge/PvEChallengePage.tsx` — 新页面
- `frontend/src/pages/ChallengePage.tsx` — 添加 PvE 入口（与 PvP 并列）
- `frontend/src/services/pveChallengeApi.ts` — API 客户端
- `frontend/src/stores/pveChallengeStore.ts` — 状态管理

**UI 需求**:
1. 挑战入口：在 ChallengePage 中新增 "Random Challenge (Solo)" 按钮，与 PvP 排位并列
2. 盲盒效果：题目展示时隐藏 Rating 和 Tags（显示 "???"）
3. 解题中：显示题目链接、计时器、提交按钮
4. 结算页面：揭晓 Rating 和 Tags，显示 Elo/PP/代币变化

#### 测试要点（防Workaround验证清单）
- [ ] **PvE 入口**: ChallengePage 显示两个模式入口（PvE + PvP）
- [ ] **盲盒 - Rating 隐藏**: 解题过程中 Rating 显示为 "???"
- [ ] **盲盒 - Tags 隐藏**: 解题过程中 Tags 不显示
- [ ] **盲盒 - 结算揭晓**: AC 或放弃后显示真实 Rating 和 Tags
- [ ] **结算动画**: Elo/PP/代币变化有动画效果
- [ ] **越级提示**: 触发越级奖励时有特殊动效

#### 验收标准
1. PvE 挑战前端流程完整
2. 盲盒效果正确隐藏/揭晓
3. 与 PvP 模式并列展示
4. 动画效果流畅

---

### Task 17.3: 越级奖励系统
**状态**: 🟢 已完成
**优先级**: P1
**依赖**: Task 15.3, Task 17.1

#### 任务描述
实现越级奖励：当用户 AC 了难度高于 Elo + 150 的题目时，给予 PP 乘数奖励。

**需求规则** (requirements.md Section 3.5):
| 难度超出范围 | PP 乘数 |
|-------------|---------|
| +150 ~ +249 | ×1.2 |
| +250 ~ +349 | ×1.5 |
| +350 以上 | ×2.0 |

**需要修改的文件**:
- `backend/app/services/pp_service.py` — `record_pp` 方法需接受 `user_elo` 参数，计算越级乘数
- `backend/app/services/pve_challenge_service.py` — 结算时传入 user_elo
- `backend/app/services/challenge_service.py` — PvP 结算也传入 user_elo
- `backend/app/services/training_service.py` — 训练结算也传入 user_elo
- `backend/app/models/pp_record.py` — 可选新增 `overkill_multiplier` 字段

**关键逻辑**:
1. 获取用户当前 Elo
2. 计算 `gap = problem_rating - user_elo`
3. 如果 gap > 150，应用对应乘数到 PP 获取量
4. 乘数仅影响 PP，不影响 Elo
5. 触发成就事件（前端动画）

#### 测试要点（防Workaround验证清单）
- [ ] **越级 +160**: PP ×1.2
- [ ] **越级 +300**: PP ×1.5
- [ ] **越级 +400**: PP ×2.0
- [ ] **越级 +150 边界**: gap=150 不触发（需 >150）
- [ ] **越级 +250**: PP ×1.5（不是 1.2）
- [ ] **不越级 +100**: PP ×1.0（无加成）
- [ ] **不影响 Elo**: 越级奖励不改变 Elo 结算
- [ ] **各模式均生效**: PvE/PvP/训练/比赛都检查越级
- [ ] **成就事件**: 触发越级时产生事件（用于前端动画）

#### 验收标准
1. 越级 PP 乘数阶梯正确
2. 仅影响 PP 不影响 Elo
3. 所有模式均支持
4. 触发成就事件

---

## 阶段 18: 混合 AI 虚拟比赛

### Task 18.1: Bot 生成与赛况模拟引擎
**状态**: 🟢 已完成
**优先级**: P1
**依赖**: Task 15.1

#### 任务描述
实现虚拟比赛中的 AI Bot 生成和赛况模拟：生成 N 个 Bot，按分钟级模拟过题，实时推送到前端。

**需求规则** (requirements.md FR-4.1, FR-4.2):
- 生成 N 个 Bot（如 50），Elo 围绕用户 Global Elo 呈正态分布
- 按分钟级根据 P(AC) 公式模拟各 Bot 过题
- 人类与 Bot 在同一排行榜

**需要新增的文件**:

1. **数据模型** — 新增 `contest_bots` 表（或 contest_sessions 中增加 bots JSONB 字段）:
   ```
   contest_bots:
     id (UUID, PK)
     contest_id (UUID, FK -> contest_sessions.id)
     bot_name (VARCHAR(50))
     bot_elo (INTEGER)
     problems_solved (INTEGER, DEFAULT 0)
     solved_problem_ids (JSONB) -- 已解决的题目 ID 列表
     total_attempts (INTEGER, DEFAULT 0)
   ```

2. **服务层** — 新增 `backend/app/services/contest_simulation_service.py`:
   - `generate_bots(db, user_elo, count=50) -> list[ContestBot]` — 生成 Bot（正态分布 Elo）
   - `start_simulation(contest_id)` — 启动模拟任务
   - `tick_simulation(contest_id)` — 每分钟执行一次，模拟各 Bot 过题
   - `_simulate_bot_tick(bot, problems, time_elapsed) -> list[str]` — 单 Bot 本轮过题

3. **实时推送** — 新增 WebSocket 端点:
   - `backend/app/api/v1/contest_ws.py` — WebSocket 连接，推送排行榜更新
   - 使用 FastAPI WebSocket + 后台 asyncio.Task 实现定时 tick

4. **修改** `backend/app/services/contest_service.py`:
   - `start_contest` — 同时生成 Bot
   - `get_contest_status` — 返回包含 Bot 的排行榜
   - `end_contest` — 停止模拟

**Bot 模拟逻辑**:
1. 每个 Bot 每分钟尝试一道题
2. 使用 P(AC) = 1 / (1 + 10^((problem_rating - bot_elo) / 400)) 判断是否 AC
3. Bot 按题目顺序尝试，已 AC 的题跳过
4. 人类玩家与 Bot 的解题进度汇总为统一排行榜

#### 测试要点（防Workaround验证清单）
- [ ] **Bot 生成数量**: 默认生成 50 个 Bot
- [ ] **Bot Elo 正态分布**: 均值 ≈ 用户 Elo，标准差合理（如 σ=200）
- [ ] **Bot 名称**: 生成有趣的虚拟名称
- [ ] **模拟 tick**: 每分钟正确触发一次
- [ ] **Bot 过题概率**: 高 Elo Bot 过难题概率更高，与 P(AC) 公式一致
- [ ] **排行榜排序**: 人类和 Bot 混合排序，解题数优先
- [ ] **WebSocket 推送**: 排行榜变化时前端实时收到更新
- [ ] **比赛结束停止**: 比赛结束时模拟任务正确停止
- [ ] **断线重连**: 用户 WebSocket 断开后可重新连接继续接收

#### 验收标准
1. Bot 生成正确（数量、分布、名称）
2. 模拟引擎按分钟运行
3. WebSocket 实时推送排行榜
4. 比赛结束后模拟正确停止

---

### Task 18.2: 表现分 (PR) 反推计算
**状态**: 🟢 已完成
**优先级**: P1
**依赖**: Task 18.1

#### 任务描述
实现赛后表现分 (Performance Rating) 的二分查找计算，并以此大幅更新 Global Elo。

**需求规则** (requirements.md FR-4.3):
- 结合玩家最终名次和所有参与 Bot 的初始 Elo 阵列
- 通过二分查找计算 PR
- 以 PR 为基准大幅更新 Global Elo

**需要新增/修改的文件**:
- `backend/app/services/contest_simulation_service.py` — 新增 `calculate_performance_rating` 方法
- `backend/app/services/contest_service.py` — 修改 `end_contest` 使用 PR 结算

**PR 计算逻辑**:
1. 获取所有 Bot 的 Elo 列表 + 玩家的解题数
2. 二分查找一个 PR 值，使得：在所有选手（Bot + 玩家）中，PR 作为玩家 Elo 时，玩家的期望排名 ≈ 实际排名
3. 二分查找范围：[0, 4000]，精度 ±1
4. 最终 Elo 变化 = K × (PR - current_elo) / 400（大幅更新）

#### 测试要点（防Workaround验证清单）
- [ ] **PR 计算 - 冠军**: 玩家解题数最高时 PR 远高于所有 Bot Elo
- [ ] **PR 计算 - 末位**: 玩家 0 解题时 PR 低于所有 Bot Elo
- [ ] **PR 计算 - 中游**: 玩家中等表现时 PR 在 Bot Elo 均值附近
- [ ] **二分收敛**: PR 值在合理范围内收敛（±1 精度）
- [ ] **Elo 大幅更新**: PR 结算产生的 Elo 变化大于普通挑战
- [ ] **边界情况**: 只有 1 个 Bot 或 0 个 Bot 时不崩溃
- [ ] **Elo 历史记录**: reason="contest_pr"

#### 验收标准
1. PR 二分查找算法正确
2. Elo 更新幅度合理
3. 边界情况安全处理

---

### Task 18.3: AI 比赛前端集成
**状态**: 🟢 已完成
**优先级**: P1
**依赖**: Task 18.1

#### 任务描述
修改比赛前端页面，集成 Bot 排行榜和 WebSocket 实时更新。

**需要修改的文件**:
- `frontend/src/pages/ContestPage.tsx` — 排行榜展示 Bot 和玩家
- `frontend/src/services/contestApi.ts` — 新增 WebSocket 连接
- `frontend/src/stores/contestStore.ts` — 新增排行榜实时状态

**UI 需求**:
1. 比赛进行中：实时排行榜（人类高亮 + Bot 按解题数排序）
2. 排行榜每分钟自动更新
3. 结算页面：显示 PR 值和最终 Elo 变化

#### 测试要点（防Workaround验证清单）
- [ ] **WebSocket 连接**: 比赛开始后自动连接
- [ ] **排行榜实时更新**: Bot 过题后排行榜即时变化
- [ ] **玩家高亮**: 人类玩家在排行榜中视觉突出
- [ ] **PR 显示**: 结算页面显示 PR 值
- [ ] **断线重连**: WebSocket 断开后自动重连
- [ ] **性能**: 50 个 Bot 排行榜渲染流畅

#### 验收标准
1. 实时排行榜正确渲染
2. WebSocket 连接稳定
3. 结算显示 PR 值
4. 性能流畅

---

## 阶段 19: 补全与打磨

### Task 19.1: Elo 衰减串联修复
**状态**: 🟢 已完成
**优先级**: P2
**依赖**: 无

#### 任务描述
修复提示 Elo 衰减未串联到实际结算的 bug。

**当前问题**:
- `hint_attenuation` 配置存在（0.75, 0.50, 0.25）
- `calculate_challenge_elo` 支持衰减参数
- 但 `_settle_challenge` 调用时未传入 `hints_used_challenger` 参数

**需要修改的文件**:
- `backend/app/services/challenge_service.py` — `_settle_challenge` 从 session 读取 `hints_used_challenger`/`hints_used_opponent` 并传入

#### 测试要点（防Workaround验证清单）
- [ ] **1 级提示衰减**: 使用 1 级提示 AC，Elo 增益 ×0.75
- [ ] **2 级提示衰减**: 使用 2 级提示 AC，Elo 增益 ×0.50
- [ ] **3 级提示衰减**: 使用 3 级提示 AC，Elo 增益 ×0.25
- [ ] **PP 不受影响**: 使用提示后 PP 计算不变
- [ ] **失败不衰减**: 负 Elo 变化不受提示衰减影响

#### 验收标准
1. 提示 Elo 衰减在所有模式中正确串联
2. PP 不受影响
3. 负值不变

---

### Task 19.2: 挑战/比赛尝试奖励补全
**状态**: 🟢 已完成
**优先级**: P2
**依赖**: 无

#### 任务描述
在挑战和比赛模式中补全"尝试奖励"代币——未 AC 但有提交尝试时也应获得代币。

**当前问题**:
- 尝试奖励分级已定义（灰2/绿3/蓝4/紫5/黄红6）
- 训练模式正确发放
- 挑战和比赛模式未发放

**需要修改的文件**:
- `backend/app/services/challenge_service.py` — 失败方也发放尝试奖励
- `backend/app/services/contest_service.py` — 未 AC 的题目也发放尝试奖励

#### 测试要点（防Workaround验证清单）
- [ ] **挑战 - 失败方尝试奖励**: 挑战失败但有提交时获得对应难度尝试代币
- [ ] **比赛 - 未 AC 题目尝试奖励**: 比赛中尝试但未 AC 的题目发放尝试代币
- [ ] **AC 奖励分级精确值**: 灰10/绿20/蓝30/紫40/黄红50，各难度奖励值正确
- [ ] **长时间加成(>20min)**: 用时超过 20 分钟并 AC 时额外获得时间加成代币（灰5/绿10/蓝15/紫20/黄红25）
- [ ] **每日上限 120**: AC奖励+尝试奖励+时间加成合计不超过每日 120 上限
- [ ] **交易记录**: 尝试奖励记入 token_transactions

#### 验收标准
1. 挑战和比赛模式正确发放尝试奖励
2. 每日上限生效
3. 交易记录完整

---

### Task 19.3: 雷达图 M-Elo 数据源
**状态**: 🟢 已完成
**优先级**: P2
**依赖**: Task 16.1

#### 任务描述
将雷达图数据源从"完成率"切换为 M-Elo 值。

**需要修改的文件**:
- `frontend/src/components/charts/RadarChart.tsx` — 数据源切换
- `frontend/src/pages/dashboard/DashboardPage.tsx` — 调用新 API
- 对应后端 API 需返回 M-Elo 数据（Task 16.1 中已添加）

#### 测试要点（防Workaround验证清单）
- [ ] **数据源**: 雷达图各维度显示 M-Elo 值而非完成率
- [ ] **新标签**: 未做题的标签显示初始 M-Elo（继承的 Global Elo）
- [ ] **无数据**: 无任何 M-Elo 记录时显示友好空状态
- [ ] **动态 fullMark**: fullMark 动态适配（已有实现）

#### 验收标准
1. 雷达图展示 M-Elo 值
2. 无数据时有友好提示
3. 视觉效果与之前一致

---

### Task 19.4: 异步提交流追踪
**状态**: 🟢 已完成
**优先级**: P3
**依赖**: 无

#### 任务描述
实现后台异步轮询 CF API 追踪用户提交状态，替代当前的手动报告机制。

**需要新增的文件**:
- `backend/app/services/submission_tracker.py` — 提交状态追踪服务
- `backend/app/core/task_scheduler.py` — 后台任务调度（使用 APScheduler 或 asyncio.create_task）

**功能要求**:
1. 用户在系统内发起解题 → 记录预期提交
2. 后台定时轮询 CF API `user.status` 获取最新提交
3. 匹配提交记录 → 更新会话状态（Pending → AC/WA/TLE...）
4. 最终状态确定后触发结算

**注意**: 此为独立增强功能，不影响现有手动提交流程。可作为可选升级。

#### 测试要点（防Workaround验证清单）
- [ ] **提交匹配**: 从 CF API 获取的提交能正确匹配到系统内的解题会话
- [ ] **状态映射**: Pending → Pending, AC → AC, WA/TLE/RE → 失败
- [ ] **轮询频率**: 不超过 CF API 限流要求（最小 2 秒间隔）
- [ ] **幂等结算**: 同一提交不会重复结算
- [ ] **超时处理**: 长时间无最终状态的提交有超时机制

#### 验收标准
1. 后台轮询正确运行
2. 提交状态准确映射
3. 不超 CF API 限流
4. 幂等安全

---

## 任务依赖关系总览

```
阶段 15 (核心算法升级):
  15.1 K因子分段 ← 无依赖 (P0)
  15.2 S值分级 ← 15.1
  15.3 PP表现因子 ← 无依赖 (P0)

阶段 16 (M-Elo 系统):
  16.1 M-Elo数据模型 ← 无依赖 (P0)
  16.2 护盾机制 ← 16.1, 15.1
  16.3 权重极化 ← 16.1, 15.1
  16.4 标签分流抽取 ← 16.1

阶段 17 (PvE 挑战):
  17.1 PvE后端 ← 15.1, 15.3
  17.2 PvE前端 ← 17.1
  17.3 越级奖励 ← 15.3, 17.1

阶段 18 (AI 比赛):
  18.1 Bot+模拟引擎 ← 15.1
  18.2 PR反推 ← 18.1
  18.3 AI比赛前端 ← 18.1

阶段 19 (补全):
  19.1 Elo衰减串联 ← 无依赖
  19.2 尝试奖励 ← 无依赖
  19.3 雷达图M-Elo ← 16.1
  19.4 异步追踪 ← 无依赖
```

---

## 执行优先级

**第一波 (P0 - 基础, 可并行)**:
- 15.1 K因子分段
- 15.3 PP表现因子
- 16.1 M-Elo数据模型

**第二波 (P1 - 依赖第一波)**:
- 15.2 S值分级 ← 15.1
- 16.2 护盾 ← 16.1, 15.1
- 16.3 极化结算 ← 16.1, 15.1
- 16.4 标签抽取 ← 16.1
- 17.1 PvE后端 ← 15.1, 15.3
- 17.3 越级奖励 ← 15.3
- 18.1 Bot+模拟 ← 15.1

**第三波 (P1 - 前端, 依赖第二波)**:
- 17.2 PvE前端 ← 17.1
- 18.2 PR反推 ← 18.1
- 18.3 AI比赛前端 ← 18.1

**第四波 (P2 - 打磨)**:
- 19.1 Elo衰减串联
- 19.2 尝试奖励
- 19.3 雷达图M-Elo ← 16.1

**第五波 (P3 - 增强)**:
- 19.4 异步追踪

**最终 (P0 - E2E 验证)**:
- 20.1 Playwright E2E 集成测试 ← 所有 task 完成后

---

## 阶段 20: 端到端集成测试

### Task 20.1: Playwright E2E 全流程测试
**状态**: 🟢 已完成
**优先级**: P0
**依赖**: 所有前序 task 完成后

#### 任务描述
使用 Playwright 模拟真实用户行为，在浏览器中对所有核心功能进行端到端测试。项目已有 Playwright 基础设施（`frontend/tests/` 目录）。

**需要新增/修改的文件**:
- `frontend/tests/e2e/auth.spec.ts` — 注册/登录/Token 刷新流程
- `frontend/tests/e2e/pve-challenge.spec.ts` — PvE 随机挑战全流程（开始→盲盒→提交→结算→越级奖励动画）
- `frontend/tests/e2e/pvp-challenge.spec.ts` — PvP 排位赛匹配与结算
- `frontend/tests/e2e/training.spec.ts` — 专题训练（选题→AC→护盾→连击→星级→M-Elo 更新）
- `frontend/tests/e2e/contest.spec.ts` — 虚拟比赛（选赛制→Bot 生成→实时排行榜→PR 结算）
- `frontend/tests/e2e/economy.spec.ts` — 经济系统（AC 代币→尝试代币→提示购买→每日上限）
- `frontend/tests/e2e/dashboard.spec.ts` — 仪表盘（Elo 趋势图、PP 贡献图、M-Elo 雷达图）

**测试场景覆盖**:

1. **用户旅程 Happy Path**:
   - 新用户注册 → 登录 → 绑定 CF Handle → Dashboard 展示初始数据
   - PvE 随机挑战 → 盲盒隐藏 Rating/Tags → AC → 揭晓 → Elo/PP/代币更新 → 越级奖励触发
   - 专题训练 → 选标签 → 护盾保护（失败不扣分）→ 首次 AC 解除护盾 → 连击奖励 → 星级更新

2. **关键视觉验证**:
   - 盲盒模式：解题中 Rating 显示 "???"，结算后揭晓真实值
   - 雷达图：展示 M-Elo 值（非完成率）
   - 越级奖励：触发时有特殊动效
   - 比赛排行榜：Bot + 人类混合排序，实时更新

3. **边界场景**:
   - 无合适题目时的提示
   - 代币余额不足购买提示
   - 每日代币上限
   - 护盾状态下的失败不扣 Elo

**前置条件**:
- Docker 环境运行（frontend + backend + postgres）
- 测试专用 CF Handle 或 mock CF API 响应
- 测试数据清理机制（每个测试独立）

#### 测试要点（防Workaround验证清单）
- [ ] **注册→登录→Dashboard**: 新用户注册后能登录并看到 Dashboard
- [ ] **PvE 盲盒**: 挑战进行中 Rating 和 Tags 不可见，结算后可见
- [ ] **PvE 结算**: AC 后 Elo/PP/代币数值正确更新
- [ ] **越级奖励动效**: AC 高难度题时触发越级奖励视觉反馈
- [ ] **训练护盾**: 新标签首次失败后 Elo 不变
- [ ] **训练连击**: 连续递增难度完成题目触发连击奖励
- [ ] **比赛 Bot**: 比赛开始后排行榜包含 Bot
- [ ] **比赛 PR**: 结算页面显示 PR 值
- [ ] **提示系统**: 购买提示后代币扣除、Elo 衰减
- [ ] **雷达图 M-Elo**: 数据来自 M-Elo 而非完成率
- [ ] **每日代币上限**: 达到上限后不再获得

#### 验收标准
1. 所有 E2E 测试在 Docker 环境中通过
2. 覆盖所有核心用户旅程
3. 视觉验证（盲盒、动效、图表）通过
4. 测试间互不干扰（数据隔离）

---

## 阶段 21: 审计节点 C 修复

> 审计节点 C（最终合规审计）发现 3 个问题，以下为补充修复任务。

### Task 21.1: 成就事件系统
**状态**: 🟢 已完成
**优先级**: P1
**依赖**: Task 17.1, Task 17.3, Task 18.2

#### 任务描述
需求 Section 3.5 和 FR-2.3 要求越级奖励触发成就事件。当前无成就系统基础设施。

#### 实现内容
- 新增 `AchievementService`：成就类型枚举 + 检查方法
- PvE/挑战/比赛结算时生成成就事件（越级/夺冠/刷新个人PP）
- API 响应新增 `achievements` 字段
- 前端全屏成就弹窗动画（抽卡出货效果）

#### 测试要点
- [ ] 越级 AC 触发 OVERKILL_BONUS 成就
- [ ] 比赛夺冠触发 CONTEST_WIN 成就
- [ ] 刷新个人最高 PP 触发 PERSONAL_BEST_PP 成就
- [ ] 前端收到 achievements 数组时弹出成就卡片

---

### Task 21.2: 沉浸式成就动效完善
**状态**: 🟢 已完成
**优先级**: P2
**依赖**: Task 21.1

#### 任务描述
需求 6.2 要求"越级AC、比赛夺冠、刷新个人最高PP"有全局拦截式动效（类似抽卡出货切入）。

#### 实现内容
- 全屏弹窗组件：缩放弹入 + 金色边框 + 成就图标 + 背景模糊
- 三种成就类型有不同的视觉风格（越级=闪电/夺冠=奖杯/PP=星星）
- 使用 framer-motion AnimatePresence 动画

---

### Task 21.3: 三级提示内容修正
**状态**: 🟢 已完成
**优先级**: P3
**依赖**: 无

#### 任务描述
需求 FR-5.2 定义三级提示为"算法标签 → 核心转化思路 → 边界样例"，代码中 Level 3 实现为"接近完整解法"，与需求的"边界样例"不一致。

#### 修复方式
- 修改 `hint_service.py` 中 Level 3 提示的生成逻辑或模板
- 或通过管理员配置调整提示内容描述

---

### Task 21.4: 提示标签键名不匹配修复
**状态**: 🟢 已完成
**优先级**: P1
**依赖**: 无

#### 任务描述
`hint_content_service.py` 中 `_TAG_HINTS` 字典键使用空格（如 `"binary search"`、`"data structures"`），但 `generate_hint` 方法将 tag 中的空格替换为下划线后查找，导致 4 个多词标签（binary search、data structures、constructive algorithms、number theory）永远无法匹配，回退到通用提示。

#### 修复方式
统一 `_TAG_HINTS` 的键名格式，使其与 `generate_hint` 的查找逻辑一致（空格替换为下划线后的格式）。

---

## 阶段 22: 审计节点 C 修复（第二轮）

> 审计发现 4 个 FAIL + 3 个 PARTIAL 问题，以下为补充修复任务。

### Task 22.1: Elo 衰减串联到 PvE/训练/比赛模式
**状态**: 🟢 已完成
**优先级**: P0
**依赖**: 无

#### 任务描述
需求 FR-5.3 要求购买提示后 AC 的 Elo 涨幅按提示深度衰减（Level 1: ×0.75, Level 2: ×0.50, Level 3: ×0.25）。当前只有 PvP 挑战模式（`challenge_service.py`）正确串联了提示衰减。PvE 挑战、训练、比赛三个模式结算时完全忽略提示使用情况。

**需要修改的文件**:
- `backend/app/services/pve_challenge_service.py` — `submit_result` 方法：在计算 Elo 变化后，查询 `HintService.get_max_hint_level(db, user.id, session.problem_id)`，然后对正向 Elo 变化调用 `EloService.apply_hint_attenuation(elo_change, hint_level)`
- `backend/app/services/training_service.py` — `_calculate_training_elo` 方法：同样查询提示层级，对正向 `global_elo_change` 和 `melo_change` 分别应用衰减
- `backend/app/services/contest_service.py` — `_settle_with_pr` 方法：查询提示层级并应用衰减。需先确定如何追踪比赛中每道题的提示使用（当前比赛模型无 hint 字段，可通过 `HintService.get_max_hint_level` 按题目查询）

**关键实现细节**:
1. `EloService.apply_hint_attenuation(elo_change, hint_level)` 是现有的静态方法，仅对正向变化应用衰减
2. `HintService.get_max_hint_level(db, user_id, problem_id)` 查询 hint_purchases 表获取最高提示层级
3. 衰减系数从 `EloConfig.hint_attenuation` 读取：`{1: 0.75, 2: 0.50, 3: 0.25}`
4. PP 不受影响（已在各模式的 PP 计算中验证独立）
5. 负向 Elo 变化不受衰减影响

#### 测试要点（防Workaround验证清单）
- [ ] **PvE - 1 级提示衰减**: 使用 1 级提示 AC，Elo 增益 ×0.75
- [ ] **PvE - 2 级提示衰减**: 使用 2 级提示 AC，Elo 增益 ×0.50
- [ ] **PvE - 3 级提示衰减**: 使用 3 级提示 AC，Elo 增益 ×0.25
- [ ] **PvE - 无提示**: 不使用提示 AC，Elo 正常计算
- [ ] **PvE - 负值不衰减**: 失败时 Elo 扣分不受提示影响
- [ ] **训练 - 提示衰减**: 训练中使用提示 AC，Global Elo 和 M-Elo 的正向变化均受衰减
- [ ] **训练 - 护盾优先**: 护盾激活时失败不扣分（衰减逻辑不影响护盾保护）
- [ ] **比赛 - 提示衰减**: 比赛中 AC 使用了提示的题目，正向 Elo 变化受衰减
- [ ] **比赛 - PR 公式正确**: 衰减后 Elo 变化仍为 K × (PR - elo) / 400 × 衰减系数
- [ ] **所有模式 PP 不受影响**: 提示使用不影响 PP 计算

#### 验收标准
1. PvE、训练、比赛三个模式均正确应用提示 Elo 衰减
2. 仅正向 Elo 变化受衰减
3. PP 不受影响
4. 护盾逻辑不受衰减干扰

---

### Task 22.2: PvE 非 AC 尝试代币发放
**状态**: 🟢 已完成
**优先级**: P0
**依赖**: 无

#### 任务描述
需求 FR-5.1 要求"所有有效尝试均需产出一定比例的系统代币"。当前 PvE 挑战模式 `submit_result` 中代币奖励被 `if solved` 条件包裹，非 AC 的有效尝试不获得任何代币。其他模式（PvP 挑战、训练、比赛）已正确发放尝试代币。

**需要修改的文件**:
- `backend/app/services/pve_challenge_service.py` — `submit_result` 方法中代币发放逻辑

**关键实现细节**:
1. 当前代币逻辑在 `if solved and session.problem_rating > 0:` 块内
2. 需增加 `else` 分支：非 AC 时调用 `economy_svc.attempt_tokens_for_rating(session.problem_rating)` 获取尝试代币
3. 通过 `economy_svc.award_tokens` 发放（自动受每日上限约束）
4. 交易类型建议用 `"pve_attempt_reward"`

#### 测试要点（防Workaround验证清单）
- [ ] **非 AC 尝试代币**: PvE 挑战未 AC 但有提交，获得对应难度尝试代币（灰2/绿3/蓝4/紫5/黄红6）
- [ ] **AC 代币不变**: AC 时代币奖励（含时间加成）不变
- [ ] **0 提交退出不发放**: quit_challenge 中 0 提交退出不获得代币
- [ ] **每日上限生效**: 尝试代币受每日 120 上限约束
- [ ] **交易记录**: 尝试代币记录到 token_transactions

#### 验收标准
1. PvE 非 AC 有效尝试正确发放尝试代币
2. 分级精确值与需求一致
3. 每日上限生效

---

### Task 22.3: 比赛超时自动结束阶梯惩罚 + 成就 Elo 基准修复
**状态**: 🟢 已完成
**优先级**: P1
**依赖**: 无

#### 任务描述
两个中等问题合并修复：

**问题 A — 比赛超时缺少阶梯惩罚**: `contest_service.py` 的 `end_contest`（手动结束）正确实现了 0 提交/1-2 提交/3+ 提交的分支逻辑，但 `_auto_end_expired`（超时自动结束）对所有 `submissions > 0` 统一走 PR 结算，缺少 1-2 次提交的惩罚分支（-5 到 -10）。

**问题 B — 成就检测使用结算后 Elo**: PvE `submit_result` 和 PvP `_settle_challenge` 中，成就检测（`AchievementService.check_overkill`）在 `user.elo` 已被更新后调用，传入的是结算后的 Elo 值而非原始 Elo。这导致越级检测的基准 Elo 不一致。

**需要修改的文件**:
- `backend/app/services/contest_service.py` — `_auto_end_expired` 增加阶梯惩罚分支
- `backend/app/services/pve_challenge_service.py` — 成就检测使用原始 Elo
- `backend/app/services/challenge_service.py` — 成就检测使用原始 Elo

**关键实现细节**:

问题 A：
- `_auto_end_expired` 中 `if session.submissions == 0: elo_change = 0` 已存在
- 需增加 `elif session.submissions <= 2: elo_change = random.randint(-10, -5)` 并记录 EloHistory
- `else:` 保持现有 PR 结算

问题 B：
- PvE: 在 `user.elo = new_elo` 之前保存 `original_elo = user.elo`，将 `original_elo` 传给 `check_overkill`
- PvP: 在 `_settle_challenge` 中保存 `original_challenger_elo = challenger.elo`，将原始值传给 `check_overkill`

#### 测试要点（防Workaround验证清单）
- [ ] **超时 0 提交**: 比赛超时且 0 提交，Elo 不变
- [ ] **超时 1-2 提交**: 比赛超时且 1-2 次提交，Elo 降 5~10
- [ ] **超时 3+ 提交**: 比赛超时且 3+ 次提交，走 PR 结算
- [ ] **手动结束不受影响**: `end_contest` 逻辑不变
- [ ] **PvE 成就原始 Elo**: 越级检测使用结算前 Elo
- [ ] **PvP 成就原始 Elo**: 越级检测使用结算前 Elo

#### 验收标准
1. 比赛超时自动结束的阶梯惩罚与手动结束一致
2. 成就检测使用原始 Elo 值
3. 现有功能无回归

---

## 阶段 16: Bug 修复 (2026-05-20)

### Task 16-B1: Leaderboard 为空
**状态**: 🟢 已完成
**优先级**: P0
**依赖**: 无

#### 根因分析
前端 `LeaderboardPage.tsx` 调用 `GET /auth/leaderboard`，但后端 `backend/app/api/v1/auth.py` 中缺少该端点，导致前端 catch 块设置 users 为空数组。

#### 任务描述
在 `backend/app/api/v1/auth.py` 中添加 `GET /leaderboard` 端点，返回所有活跃用户按 Elo 降序排列。

**需要修改的文件**:
- `backend/app/api/v1/auth.py` — 新增 `/leaderboard` 端点

**关键实现细节**:
1. 查询 `users` 表，`WHERE is_active = True`，`ORDER BY elo DESC`，`LIMIT 100`
2. 返回字段：`id`, `username`, `cf_handle`, `elo`, `pp`, `tokens`, `rank`（序号）
3. 需要认证（`Depends(get_current_user)`）
4. 使用 `success_response` 包装返回

#### 测试要点（防Workaround验证清单）
- [ ] **认证用户可访问**: 带 token 请求返回 200 + 用户列表
- [ ] **未认证被拒绝**: 不带 token 返回 401
- [ ] **按 Elo 降序**: 返回列表按 elo 从高到低
- [ ] **不包含非活跃用户**: `is_active = False` 的用户不出现在列表
- [ ] **rank 正确**: rank 从 1 开始，与排序一致
- [ ] **前端正常展示**: 浏览器访问 leaderboard 页面能看到用户列表

#### 验收标准
1. Leaderboard 页面正常显示用户排名数据
2. 按 Elo 和 PP 排序均正常工作

---

### Task 16-B2: Training 页面 "Failed to load topics"
**状态**: 🟢 已完成
**优先级**: P0
**依赖**: 无

#### 根因分析
后端 `GET /training/topics` 端点存在且 API 直接测试正常（返回 12 topics）。前端通过 nginx 代理访问时可能出现认证 token 问题：
- 前端 api.ts 的 401 拦截器在收到 401 时清除 token 并重定向到登录页
- 如果用户 token 过期，页面 API 调用失败显示错误信息
- docker-compose.yml health check 路径错误（`/health` 应为 `/api/v1/health`），可能导致容器状态判断不准

**需要修改的文件**:
- `docker-compose.yml` — 修复 health check 路径

#### 测试要点（防Workaround验证清单）
- [ ] **登录后 Training 正常**: 用户登录后访问 training 页面能看到 topics 列表
- [ ] **Health check 正确**: `curl http://localhost:8000/api/v1/health` 返回 200
- [ ] **12 个 topics 全部展示**: 页面显示所有预定义 topic

#### 验收标准
1. Training 页面正常展示 12 个 topic 分类
2. 每个 topic 显示题目数量

---

### Task 16-B3: 登录页 "Invalid credentials"
**状态**: 🟢 已完成
**优先级**: P0
**依赖**: 无

#### 根因分析
后端 `POST /auth/login` API 直接测试正常（`test@example.com`/`Password123` 可登录）。通过 nginx 代理测试也正常。需确认：
1. 用户使用的具体凭据
2. 前端表单提交的数据格式是否正确
3. 是否存在 CORS 或其他网络层问题

#### 测试要点（防Workaround验证清单）
- [ ] **已知账户可登录**: `test@example.com`/`Password123` 通过前端登录成功
- [ ] **错误凭据正确提示**: 错误密码显示 "Invalid credentials"
- [ ] **注册后可登录**: 新注册账户能立即登录
- [ ] **登录后跳转**: 登录成功跳转到 /dashboard

#### 验收标准
1. 用户能通过前端正常登录
2. 错误凭据给出正确提示

---

## 阶段 23: Rating 对标 CF + Profile Elo Chart + i18n (2026-05-20)

> 需求文档: requirements.md Section 6.3 (i18n), 6.2 补充 (Profile Elo Chart), 6.4 (Rating 段位)

### Task 23.1: Rating 段位体系对标 Codeforces
**状态**: 🟢 已完成
**优先级**: P0
**依赖**: 无

#### 任务描述
将前端的 Rating 颜色、范围和段位名称从现有简化 6 档体系升级为 Codeforces 官方 10 档体系。

**需求规格** (requirements.md Section 6.4, FR-7.1):
| 段位英文名 | Rating 范围 | 颜色 (HEX) |
|-----------|------------|------------|
| Newbie | < 1200 | #808080 (灰) |
| Pupil | 1200–1399 | #008000 (绿) |
| Specialist | 1400–1599 | #03A89E (青) |
| Expert | 1600–1899 | #0000FF (蓝) |
| Candidate Master | 1900–2099 | #AA00AA (紫) |
| Master | 2100–2299 | #FF8C00 (橙) |
| International Master | 2300–2399 | #FF8C00 (橙) |
| Grandmaster | 2400–2599 | #FF0000 (红) |
| International Grandmaster | 2600–2999 | #FF0000 (红) |
| Legendary Grandmaster | ≥ 3000 | #FF0000 (红，首字母加粗/黑色) |

**需要修改的文件**:
- `frontend/src/utils/index.ts` — 重写 `getRatingColor()` 和 `getDifficultyLabel()`，颜色和段位精确对标 CF 标准；新增 `RATING_TIERS` 常量数组作为单一数据源
- `frontend/src/components/charts/DashboardCharts.tsx` — 更新 `difficultyDistribution` 中的硬编码段位名称和颜色（当前 "Yellow (CM)"、"Red (GM+)" 等不匹配新体系）
- `frontend/src/pages/ProfilePage.tsx` — Elo 卡片增加段位名称展示
- `frontend/src/pages/DashboardPage.tsx` — Elo 卡片增加段位名称展示
- `frontend/src/pages/LeaderboardPage.tsx` — 排名列表增加段位名称展示
- `backend/app/core/default_config.py` — `difficulty_tiers` 和 `hint_pricing` 的 rating 边界对齐 CF 段位边界（详见下方关键实现细节）
- 所有调用 `getRatingColor` / `getDifficultyLabel` 的文件确认兼容（无需改动逻辑，只改映射函数内部）:
  - `frontend/src/pages/ChallengePage.tsx`
  - `frontend/src/pages/TrainingDetailPage.tsx`
  - `frontend/src/pages/ContestDetailPage.tsx`
  - `frontend/src/pages/challenge/PvEChallengePage.tsx`
  - `frontend/src/components/charts/PPChart.tsx`
- `backend/app/services/economy_service.py` 或相关经济服务 — 确认 difficulty_tiers 边界更新后代币奖励计算正确

**关键实现细节**:
1. 新增 `RATING_TIERS` 常量数组，每项包含 `{ name, nameZh, min, color }`，作为所有段位相关逻辑的单一数据源
2. `getRatingColor(rating)` 返回值从 `DIFFICULTY_COLORS` 字典查找改为基于 `RATING_TIERS` 二分查找
3. `getDifficultyLabel(rating)` 改为返回英文名（后续 Task 23.3 接入 i18n 后用翻译 key 替代）
4. 新增 `getRatingTierInfo(rating)` 辅助函数，返回完整段位信息（名称、颜色、范围），供需要同时获取多项信息的调用方使用
5. `Legendary Grandmaster` 特殊样式：在展示段位名称的位置，首字母使用加粗/深色处理（通过 CSS 或返回特殊标记实现）
6. `DashboardCharts` 中 `difficultyDistribution` 的段位名称和颜色应从 `RATING_TIERS` 动态生成而非硬编码
7. 确保所有已有调用方（`getRatingColor(elo)` 等）行为正确更新——只要映射函数内部改了，调用方无需改动
8. **段位名称展示（FR-7.3 可达性修复）**：在以下位置的 Elo 数值旁展示段位名称：
   - `ProfilePage.tsx` — Elo Rating 卡片：显示 `1650 / Expert` 格式
   - `DashboardPage.tsx` — Elo 卡片：同上格式
   - `LeaderboardPage.tsx` — 排名列表中用户名旁展示段位名称
   调用 `getDifficultyLabel(rating)` 获取段位名称，后续 Task 23.3 会将其包裹 `t()` 实现国际化
9. **后端 difficulty_tiers 边界对齐 CF（FR-7.4）**：将 `default_config.py` 中的 `difficulty_tiers` 从当前 5 档调整为与 CF 段位边界对齐的 7 档：
   - gray: 800-1199（Newbie）
   - green: 1200-1399（Pupil）
   - cyan: 1400-1599（Specialist）
   - blue: 1600-1899（Expert）
   - purple: 1900-2099（Candidate Master）
   - orange: 2100-2399（Master + International Master）
   - red: 2400-9999（Grandmaster 及以上）
   对应的 `hint_pricing` 也需调整为 7 档，奖励数值可合并相邻档位（如 cyan 和 blue 可共享相近奖励）

#### 集成点追踪
**调用方清单**:
- `DashboardCharts.tsx:67-72` — `difficultyDistribution` 数组中硬编码了段位名称和颜色，需改为从 `RATING_TIERS` 动态生成
- `utils/index.ts` — 所有 import `getRatingColor` / `getDifficultyLabel` 的文件通过函数接口调用，函数签名不变，无需改动调用方

**反向集成清单**:
- 后端 `default_config.py` 中的 `difficulty_tiers`（代币奖励分级）和 `hint_pricing`（提示定价）的 rating 边界需从 5 档调整为 CF 对齐的 7 档
- 后端 `contest.tiers`（比赛分级 Beginner/Advanced/Master）作为独立赛事规则**不需要修改**
- 后端经济服务（代币发放、提示定价）需确认新的 7 档分级下计算正确
- i18n（Task 23.3）将在此基础上提取段位名称为翻译 key

**触发场景**:
- 用户查看 Dashboard、Profile、Leaderboard、Challenge、Training、Contest 页面中任何显示 rating 颜色/段位的元素

#### 测试要点（防Workaround验证清单）
- [ ] **颜色精确匹配**: 每个段位的 HEX 颜色值严格等于 CF 标准（#808080, #008000, #03A89E, #0000FF, #AA00AA, #FF8C00, #FF0000）
- [ ] **10 档完整覆盖**: rating=0 灰, rating=1200 绿, rating=1400 青, rating=1600 蓝, rating=1900 紫, rating=2100 橙, rating=2300 橙(IM), rating=2400 红, rating=2600 红(IGM), rating=3000 红(LGM)
- [ ] **边界值正确**: rating=1199 → Newbie, rating=1200 → Pupil, rating=2399 → IM, rating=2400 → GM, rating=2999 → IGM, rating=3000 → LGM
- [ ] **Legendary GM 特殊样式**: rating≥3000 的段位名称首字母有加粗/深色处理
- [ ] **Dashboard 图表更新**: 难度分布图使用新的段位名称和颜色
- [ ] **null/undefined 处理**: `getRatingColor(null)` 返回灰色, `getDifficultyLabel(null)` 返回 "Unrated"
- [ ] **无回归**: 所有现有页面（Leaderboard、Challenge、Training、Contest、Profile）的 rating 颜色展示正常
- [ ] **段位名称展示**: Profile、Dashboard、Leaderboard 页面的 Elo 旁正确显示段位名称
- [ ] **后端 difficulty_tiers 对齐**: 7 档分级边界匹配 CF 段位（800-1199, 1200-1399, 1400-1599, 1600-1899, 1900-2099, 2100-2399, 2400+）
- [ ] **后端 hint_pricing 对齐**: 提示定价与新的 7 档 difficulty_tiers 一一对应
- [ ] **代币奖励计算正确**: 各档位题目 AC/尝试的代币奖励在新分级下正确发放
- [ ] **管理后台配置**: 管理员配置页面正确展示新的 7 档参数

#### 验收标准
1. Rating 段位名称、颜色、范围精确匹配 Codeforces 10 档体系
2. `RATING_TIERS` 作为单一数据源，所有段位相关逻辑从中派生
3. 现有功能无回归

---

### Task 23.2: Profile 页 Elo Chart 接入
**状态**: 🟢 已完成
**优先级**: P1
**依赖**: 无

#### 任务描述
将 Profile 页面的 Elo History 占位符替换为已存在的 `EloChart` 组件，并确保数据正确加载。

**需求规格** (requirements.md Section 6.2):
> 个人资料页必须展示用户的 Elo 历史折线图（复用已有的 EloChart 组件），不得使用占位符。

**当前状态**:
- `ProfilePage.tsx:231-240` 使用占位符显示 "Chart placeholder"
- `EloChart` 组件 (`components/charts/EloChart.tsx`) 已完整实现，支持 7D/30D/All 筛选
- 后端 API `GET /api/v1/auth/elo-history` 已存在

**需要修改的文件**:
- `frontend/src/pages/ProfilePage.tsx` — 移除占位符（231-240行），导入 `EloChart` 组件，新增 elo-history 数据获取逻辑（`useState` + `useEffect` 调用 `api.get("/auth/elo-history")`），将数据传入 `EloChart`

**关键实现细节**:
1. 参照 `DashboardCharts.tsx` 中 `EloChart` 的使用方式（数据获取 + 传参）
2. 数据获取使用 `api.get("/auth/elo-history")`，返回 `EloHistoryPoint[]` 类型
3. 加载状态：数据未返回时显示 `LoadingSpinner`；无数据时 `EloChart` 自带空状态处理
4. 错误处理：获取失败时静默降级（不阻断整个 Profile 页），显示错误提示文案

#### 集成点追踪
**调用方清单**:
- `ProfilePage.tsx` — 替换 231-240 行的占位符

**反向集成清单**:
- 无需集成其他横切特性

**触发场景**:
- 用户访问 `/profile` 页面，在 Stats 卡片下方看到 Elo 历史折线图

#### 测试要点（防Workaround验证清单）
- [ ] **占位符已移除**: ProfilePage 中无 "Chart placeholder" 文本
- [ ] **EloChart 渲染**: 有 elo-history 数据时，折线图正确渲染（含时间筛选按钮 7D/30D/All）
- [ ] **空数据状态**: 无 elo-history 数据时，显示 "No Elo history yet" 提示
- [ ] **数据获取**: 页面加载时自动请求 `/auth/elo-history` 接口
- [ ] **加载状态**: 数据加载中显示 loading spinner
- [ ] **错误降级**: 接口失败不阻断整个页面，显示错误提示
- [ ] **交互正常**: 时间范围筛选（7D/30D/All）功能正常，Tooltip 显示 Elo 值和变化量
- [ ] **Tooltip 交互**: hover 折线图数据点时显示日期、Elo 值和变化量的 Tooltip 弹出框

#### 验收标准
1. Profile 页面展示真实 Elo 历史折线图，占位符已移除
2. 有数据/无数据/加载中/错误 四种状态均正确处理
3. 现有 Profile 功能（编辑、CF 绑定、Stats 卡片）无回归

---

### Task 23.3: 前端国际化 (i18n) — 中英双语
**状态**: 🟢 已完成
**优先级**: P1
**依赖**: Task 23.1（段位名称需先更新为 CF 标准后再提取为翻译 key）

#### 任务描述
为前端实现完整的中英文国际化支持，覆盖所有页面和组件的硬编码文本。

**需求规格** (requirements.md Section 6.3, FR-6.1~6.4):
- 前端所有用户可见的硬编码文本支持中英文切换
- 语言偏好存储在 localStorage
- 导航栏提供语言切换控件，切换后无需刷新即生效
- 使用 react-i18next + i18next

**需要修改的文件**:
- `frontend/package.json` — 新增 `react-i18next`、`i18next` 依赖
- `frontend/src/main.tsx` — 导入并初始化 i18n 实例
- `frontend/src/locales/en/*.json` — 新建，英文翻译文件（按命名空间拆分）
- `frontend/src/locales/zh/*.json` — 新建，中文翻译文件
- `frontend/src/i18n.ts` — 新建，i18n 配置（语言检测、fallback、命名空间注册）
- `frontend/src/components/LanguageSwitcher.tsx` — 新建，语言切换控件
- `frontend/src/layouts/MainLayout.tsx` — 接入 LanguageSwitcher，提取导航文本
- `frontend/src/layouts/AuthLayout.tsx` — 提取文本
- `frontend/src/layouts/AdminLayout.tsx` — 提取文本
- `frontend/src/pages/LoginPage.tsx` — 提取文本
- `frontend/src/pages/RegisterPage.tsx` — 提取文本
- `frontend/src/pages/DashboardPage.tsx` — 提取文本
- `frontend/src/pages/ProfilePage.tsx` — 提取文本
- `frontend/src/pages/ChallengePage.tsx` — 提取文本
- `frontend/src/pages/TrainingPage.tsx` — 提取文本
- `frontend/src/pages/TrainingDetailPage.tsx` — 提取文本
- `frontend/src/pages/ContestPage.tsx` — 提取文本
- `frontend/src/pages/ContestDetailPage.tsx` — 提取文本
- `frontend/src/pages/LeaderboardPage.tsx` — 提取文本
- `frontend/src/pages/CFBindPage.tsx` — 提取文本
- `frontend/src/pages/AdminOverviewPage.tsx` — 提取文本
- `frontend/src/pages/AdminConfigPage.tsx` — 提取文本
- `frontend/src/pages/challenge/PvEChallengePage.tsx` — 提取文本
- `frontend/src/components/charts/EloChart.tsx` — 提取文本
- `frontend/src/components/charts/PPChart.tsx` — 提取文本
- `frontend/src/components/charts/StatsPanel.tsx` — 提取文本
- `frontend/src/components/charts/RadarChart.tsx` — 提取文本
- `frontend/src/components/charts/DashboardCharts.tsx` — 提取文本
- `frontend/src/components/LoadingSpinner.tsx` — 提取文本
- `frontend/src/components/ErrorBoundary.tsx` — 提取文本
- `frontend/src/utils/index.ts` — `getDifficultyLabel()` 改为返回翻译 key（由调用方通过 `t()` 转换），或改为接受 i18n 实例
- 所有动画组件 (`components/animations/*.tsx`) 中有硬编码文本的文件

**关键实现细节**:
1. **i18n 配置**:
   - 使用 `i18next-browser-languagedetector` 检测浏览器语言（优先级：localStorage > navigator > fallback 'en'）
   - 默认语言 'en'，fallback 'en'
   - 命名空间按功能模块拆分：`common`（通用）、`nav`（导航）、`auth`（认证）、`dashboard`、`challenge`、`training`、`contest`、`profile`、`leaderboard`、`admin`、`rating`（段位）

2. **翻译文件结构**:
   ```
   src/locales/
     en/
       common.json      # "Save", "Cancel", "Loading...", "Error", etc.
       nav.json         # "Dashboard", "Challenge", "Training", "Contest", etc.
       auth.json        # "Sign In", "Create Account", "Email", "Password", etc.
       dashboard.json   # Dashboard page texts
       challenge.json   # Challenge + PvE page texts
       training.json    # Training pages texts
       contest.json     # Contest pages texts
       profile.json     # Profile + CF Bind page texts
       leaderboard.json # Leaderboard page texts
       admin.json       # Admin pages texts
       rating.json      # Rating tier names (EN)
     zh/
       (同结构，中文翻译)
   ```

3. **LanguageSwitcher 组件**:
   - 显示当前语言图标/文字（如 "EN" / "中"）
   - 点击切换，使用 `i18next.changeLanguage()`
   - 放置于 MainLayout 右上角导航栏区域

4. **Rating 段位名称 i18n**:
   - `getDifficultyLabel()` 改为返回 i18n key（如 `rating:newbie`）
   - 所有调用 `getDifficultyLabel()` 的地方包裹 `t()` 转换
   - 或：`getDifficultyLabel()` 接受当前语言参数，直接返回对应语言文本
   - `rating.json` 包含 CF 10 档的中英文名称：
     ```json
     { "unrated": "Unrated" / "未评级", "newbie": "Newbie" / "新手", ... }
     ```

5. **提取原则**:
   - 所有 JSX 中的硬编码英文字符串替换为 `{t('namespace:key')}`
   - placeholder、title、aria-label 等属性中的字符串也需提取
   - 代码逻辑中的字符串（如 error message fallback）也需提取
   - `formatDate` 中的 locale "en-US" 应根据当前语言动态切换

#### 集成点追踪
**调用方清单**:
- 所有前端页面和组件中包含硬编码英文字符串的位置（约 18+ 文件，75-80 个字符串）

**反向集成清单**:
- Rating 段位名称（Task 23.1 产出的 `RATING_TIERS`）需集成到 `rating.json` 翻译文件
- `getDifficultyLabel()` 函数需改为 i18n 感知

**触发场景**:
- 用户点击导航栏语言切换按钮，整个 UI 即时切换语言
- 新用户首次访问，自动检测浏览器语言
- 刷新页面后语言偏好保持

#### 测试要点（防Workaround验证清单）
- [ ] **语言切换即时生效**: 点击语言切换按钮，所有页面文本立即切换，无需刷新
- [ ] **语言偏好持久化**: 切换语言后刷新页面，语言保持不变
- [ ] **默认语言**: 首次访问（无 localStorage）默认英文
- [ ] **英文翻译完整**: 切换到英文，所有页面无遗漏的硬编码中文或未翻译文本
- [ ] **中文翻译完整**: 切换到中文，所有页面无遗漏的硬编码英文文本
- [ ] **导航栏**: 侧边栏菜单项中英切换正确（Dashboard/仪表盘, Challenge/挑战, etc.）
- [ ] **认证页面**: 登录、注册页面的标题、按钮、表单标签、错误提示中英切换
- [ ] **Profile 页**: 所有文本中英切换（包括 Elo History、PP Ranking 区域）
- [ ] **Rating 段位名称**: 各页面中的段位名称随语言切换（Newbie/新手, Master/大师, etc.）
- [ ] **Dashboard**: 欢迎语、统计卡片、图表标题中英切换
- [ ] **Challenge 页面**: PvP + PvE 所有状态文本中英切换
- [ ] **Training/Contest 页面**: 标题、按钮、状态文本中英切换
- [ ] **Leaderboard 页面**: 表头、排名文本中英切换
- [ ] **Admin 页面**: 管理后台所有文本中英切换
- [ ] **错误/加载状态**: ErrorBoundary、LoadingSpinner 文本中英切换
- [ ] **EloChart**: "Elo Trend"、"7D/30D/All"、空状态提示中英切换
- [ ] **无遗漏**: 执行自动化 grep 验证 `grep -rn '"[A-Z][a-z]' frontend/src/ --include="*.tsx" | grep -v 'import\|className\|type\|interface\|const\|key\|id\|to="'` 确认无残留硬编码英文用户可见文本

#### 验收标准
1. react-i18next + i18next 正确初始化，LanguageSwitcher 在导航栏可用
2. 所有前端页面的用户可见文本均通过 i18n key 引用，无遗漏
3. 中英文翻译文件完整，切换即时生效，偏好持久化
4. Rating 段位名称随语言切换
5. 现有功能无回归

---

## 阶段 24: Bug 修复 — 训练性能/进度/比赛布局/Radar (2026-05-20)

### Task 24.1: 训练页面 CF API 调用优化
**状态**: 🟢 已完成
**优先级**: P0
**依赖**: 无

#### 根因分析
`list_topics` 对 12 个 topic 逐个串行调用 CF API（每次 2 秒 rate limit），冷启动需 24+ 秒。`get_progress` 和 `get_topic_detail` 有同类问题。

#### 任务描述
将 CF API 调用从"按 topic 逐个查询"改为"一次性获取全量题目，内存按 tags 分组"，将 12 次 CF API 调用降为 1 次。

**需要修改的文件**:
- `backend/app/services/training_service.py` — `list_topics`、`get_progress`、`get_topic_detail` 中的 `_fetch_topic_problems` 调用，改为一次性获取
- `backend/app/services/cf_service.py` — 确认 `get_problemset_problems` 不传 tags 时返回全量题目的行为

**关键实现细节**:
1. 新增缓存方法 `_fetch_all_problems(cf_service)` — 调用 `get_problemset_problems()` 不传 tags，缓存整个结果（key 为 `"all"`），TTL 30 分钟
2. `list_topics` 改为先获取全量题目，然后在内存中按 `PREDEFINED_TOPICS` 的 tags 过滤分组
3. `get_progress` 和 `get_topic_detail` 同理
4. 确保缓存 key 与旧的按 tag 缓存不冲突

#### 测试要点
- [ ] **冷启动性能**: 首次加载 training 页面，API 响应 < 5 秒
- [ ] **缓存命中**: 第二次加载走缓存，< 1 秒
- [ ] **题目数量正确**: 各专题的 total_problems 与之前一致
- [ ] **进度计算正确**: solved_count / completion_rate 与之前一致

---

### Task 24.2: 连胜(streak)改为连续 AC 数 + 显示修复
**状态**: 🟢 已完成
**优先级**: P1
**依赖**: 无

#### 根因分析
1. streak 定义为"rating 递增连胜"，用户做题顺序不严格递增导致始终为 0
2. 前端 `StreakEffect` 在 `streak < 1` 时返回 null，连 "0" 都不显示

#### 任务描述
将连胜定义改为"连续 AC 数"，并修复 streak=0 时的显示问题。

**需要修改的文件**:
- `backend/app/services/training_service.py` — `streak_count` 更新逻辑（约 700-729 行），移除 rating 递增判断，改为"每次 AC 时 +1，非 AC 时重置为 0"
- `frontend/src/components/animations/StreakEffect.tsx` — 修改条件，streak=0 时也显示（显示 "0 streak" 或最低显示值）

**关键实现细节**:
1. 后端：在 `solved=True` 分支内移除 `problem_rating > last_solved_rating` 条件，改为 `session.streak_count += 1`
2. 后端：在 `solved=False` 分支内新增 `session.streak_count = 0`（当前代码未在失败时重置 streak）
3. 前端：`StreakEffect` 在 `streak >= 0` 时都渲染（而非 `streak < 1` 返回 null）
4. 此 streak 变更仅影响专题训练模式，其他模式无 streak 概念

#### 测试要点
- [ ] **连续 AC 触发 streak**: 连续做对 3 题，streak=3
- [ ] **失败重置 streak**: streak=3 后做错 1 题，streak=0
- [ ] **streak=0 显示**: 训练详情页显示 "0" 或空 streak 状态（不隐藏组件）
- [ ] **streak=5 显示**: 连续 5 题 AC 后正确显示火焰效果

---

### Task 24.3: 专题进度改为 M-Elo 展示
**状态**: 🟢 已完成
**优先级**: P1
**依赖**: 无

#### 根因分析
进度分母使用 CF 全量题数（单专题上千道），用户做 10 题只有 0.x%。需改用 M-Elo 值作为专题掌握度指标。

#### 任务描述
将专题列表的进度展示从"solved_count / total_problems 百分比"改为基于 M-Elo 的掌握度展示。

**需要修改的文件**:
- `frontend/src/pages/TrainingPage.tsx` — 进度条/星星/百分比的展示逻辑
- `backend/app/services/training_service.py` — `list_topics` 返回数据中增加 M-Elo 信息，修改 `calculate_stars` 函数
- `backend/app/schemas/training.py` — TopicInfo schema 增加 M-Elo 字段
- `backend/app/api/v1/training.py` — 确认 list_topics 返回结构

**关键实现细节**:
1. 后端 `list_topics` 中增加 M-Elo 查询：使用批量查询 `get_all_melos` 一次获取所有 M-Elo 记录，然后在内存中按 tag 映射到各 topic（避免 12 次单独查询）
2. 返回数据中增加 `melo`、`shield_active` 字段
3. 新增 `calculate_stars_from_melo(melo)` 函数替代旧的 `calculate_stars(completion_rate)`，星星基于 M-Elo 区间：800-1000 → 1星, 1000-1200 → 2星, ...每 200 Elo 一星，共 7 星上限 (≥2200)
4. **所有 4 处 `calculate_stars` 调用点**均需切换到 `calculate_stars_from_melo`：`list_topics`(291行)、`get_topic_detail`(377行)、`get_progress`(988行)、`get_topic_progress`(1062行)
5. 前端进度条改为 M-Elo 展示：
   - 进度 = `max(0, min(100, (melo - 800) / (2200 - 800) * 100))`，以 800 为基线，2200 为满
   - 保留 solved_count 作为辅助信息展示（如 "已做 15 题"）
6. `shield_active=True` 的专题：M-Elo 等于继承的 Global Elo，显示为"未开始"状态（灰色进度条）

#### 测试要点
- [ ] **有 M-Elo 的专题**: 进度条基于 M-Elo 值正确展示
- [ ] **未开始的专题**: 显示"未开始"状态，灰色进度条
- [ ] **星星正确**: M-Elo 区间对应正确星数
- [ ] **solved_count 仍展示**: 作为辅助信息可见

---

### Task 24.4: 比赛卡片布局对齐
**状态**: 🟢 已完成
**优先级**: P2
**依赖**: 无

#### 根因分析
三个卡片（Beginner/Advanced/Master）信息行数量不同（beginner 无 min_elo 行），且无 `flex flex-col` + `mt-auto`，导致按钮高度不一致。

#### 任务描述
修复 ContestPage 三个比赛卡片的布局对齐问题。

**需要修改的文件**:
- `frontend/src/pages/ContestPage.tsx` — 卡片容器添加 flex 布局，按钮贴底

**关键实现细节**:
1. 卡片容器添加 `flex flex-col`，Button 添加 `mt-auto`
2. 标题区域添加 `min-h` 或 `whitespace-nowrap` 防止换行不一致
3. 统一信息行数量：beginner 也显示 "No minimum Elo" 或对应文案，保持三卡片等高

#### 测试要点
- [ ] **按钮对齐**: 三个卡片的按钮在同一水平线
- [ ] **图标对齐**: 三个卡片的图标在同一水平线
- [ ] **窄屏兼容**: sm 断点附近不出现布局错乱

---

### Task 24.5: Skill Radar 显示所有专题
**状态**: 🟢 已完成
**优先级**: P1
**依赖**: 无

#### 根因分析
后端 `get_melo` 端点只返回 `user_tag_elo` 表中已存在的记录，未练习过的专题不显示。应返回所有预定义专题的 M-Elo（未练习过的显示初始值）。

#### 任务描述
修改后端 `get_melo` 端点，确保返回所有预定义专题的 M-Elo 数据。

**需要修改的文件**:
- `backend/app/api/v1/training.py` — `get_melo` 端点（约 240-266 行）
- `backend/app/services/melo_service.py` — 可选：新增批量 get_or_create 方法

**关键实现细节**:
1. 在 `get_melo` 中，获取 `PREDEFINED_TOPICS` 的所有 primary tag 列表
2. 对每个 tag，调用 `MEloService.get_or_create_melo` 确保记录存在（未练习过的继承 Global Elo，shield_active=True）
3. 返回所有专题的 M-Elo 数据
4. 前端无需修改，已有处理 shield_active 的逻辑

#### 测试要点
- [ ] **新用户**: 只做过 1 个专题，radar 显示所有 12 个专题（11 个为初始值）
- [ ] **有数据用户**: 所有专题显示正确的 M-Elo 值
- [ ] **shield 状态**: 未练习过的专题 shield_active=True
- [ ] **性能**: 不会因创建过多记录而变慢

---

## 阶段 25: UI 打磨 + AI 模拟真实性

### Task 25.1: 比赛卡片按钮间距优化
**状态**: 🟢 已完成
**优先级**: P2
**依赖**: 无

#### 任务描述
比赛卡片（Beginner/Advanced/Master）按钮与上方信息行的间距不够，视觉上略显拥挤。

**需要修改的文件**:
- `frontend/src/pages/ContestPage.tsx` — Button 的 `mt-auto` 改为 `mt-auto pt-4` 或增加 `mt-6`

**关键实现细节**:
1. 将 Button 的 `className="mt-auto w-full"` 改为 `className="mt-auto w-full pt-4 border-t border-border/50"` 或类似的分隔效果，在按钮和信息行之间增加视觉分隔

#### 测试要点
- [ ] **间距可见**: 按钮与上方信息行之间有明显间距
- [ ] **三卡片一致**: 三个卡片按钮位置仍然对齐

---

### Task 25.2: 训练卡片去掉进度条改为段位徽章
**状态**: 🟢 已完成
**优先级**: P1
**依赖**: 无

#### 任务描述
专题训练卡片去掉进度条，改为展示 Codeforces 风格的段位徽章（彩色标签 + 段位名称 + M-Elo 数值）。

**需要修改的文件**:
- `frontend/src/pages/TrainingPage.tsx` — 移除进度条相关代码，添加段位徽章组件
- `frontend/src/locales/en/training.json` — 添加段位相关翻译 key
- `frontend/src/locales/zh/training.json` — 添加段位相关翻译 key

**关键实现细节**:
1. 移除 `meloToProgress` 函数和 `getProgressBarColor` 函数
2. 移除进度条 JSX（`<div className="mt-2 h-1.5 ...">` 及下方的百分比文字）
3. 新增段位徽章展示：使用 `getRatingTierInfo(melo)` 获取段位信息（名称、颜色），渲染为彩色标签
4. 徽章样式使用 inline style + CF 标准 HEX 颜色（来自 `RATING_TIERS` 的 `color` 属性），自动覆盖全部 10 个段位：
   - 背景色: 段位颜色 + 透明度（如 `color + "20"` 或 `color + "15"` 做浅化）
   - 文字色: 直接使用段位颜色
   - 圆角 pill 形状: `rounded-full px-2 py-0.5 text-xs font-semibold`
   - 不要使用硬编码的 Tailwind 类名（如 bg-green-100），以确保与 Task 23.1 的 CF 精确对标一致
5. `shield_active=True` 的专题显示灰色徽章（`#9ca3af`）+ "未开始" 文案
6. 徽章旁边显示 M-Elo 数值
7. 段位名称需要 i18n 支持，使用 `RATING_KEY_MAP` 映射到翻译 key（已存在于 `utils/index.ts`）
8. 保留星星评分和 solved_count 展示

**触发场景**: 用户访问 `/training` 页面

#### 测试要点
- [ ] **有 M-Elo 的专题**: 显示对应段位颜色的徽章 + 段位名称 + M-Elo 数值
- [ ] **未开始的专题**: 显示灰色徽章 + "未开始" 文案
- [ ] **段位颜色正确**: 各段位颜色与 Codeforces 一致
- [ ] **i18n**: 段位名称和"未开始"有中英文翻译
- [ ] **星星保留**: 星星评分仍然显示
- [ ] **进度条已移除**: 页面中不再有进度条

---

### Task 25.3: AI 做题速度按难度分档延迟
**状态**: 🟢 已完成
**优先级**: P1
**依赖**: 无

#### 根因分析
AI 机器人模拟存在三个叠加问题：
1. **每次 tick 同时尝试所有题目**: 每分钟每个机器人对全部未解题目独立投骰子，Elo=1600 的机器人在第 1 分钟期望解出 ~2.5 题
2. **tick 间隔仅 60 秒**: 120 分钟比赛有 120 次尝试机会
3. **无难度相关延迟**: AI 不区分简单题和难题，同时尝试所有题目

根因位置: `backend/app/services/contest_simulation_service.py:607-619`（`_simulate_bot_tick` 方法）

#### 任务描述
重构 AI 机器人模拟逻辑，使做题节奏更接近真实比赛：每 tick 每个机器人只专注 1 道题，解题时间与题目难度正相关。

**需要修改的文件**:
- `backend/app/services/contest_simulation_service.py` — 重构 `_simulate_bot_tick` 方法和模拟循环
- `backend/app/core/default_config.py` — 新增 AI 模拟相关配置参数

**关键实现细节**:
1. **每次 tick 每个机器人只尝试 1 道题**（而非所有题目）。选题策略：优先未解题目中 rating 最低的（模拟真实选手从易到难的做题顺序）
2. **tick 间隔从 60 秒改为可配置**（默认 30 秒），提取到 `default_config.py` 的 `contest.simulation` 配置中
3. **引入"读题+编码时间"概念**：每道题从"开始尝试"到"可能解出"需要经过若干 tick：
   - 简单题 (rating < 1200): 1-3 分钟（2-4 个 tick）
   - 中等题 (1200 ≤ rating < 1800): 3-8 分钟（6-16 个 tick）
   - 难题 (rating ≥ 1800): 8-15 分钟（16-30 个 tick）
   - 每个时间范围加入 ±30% 随机抖动
4. **实现方式**：为每个 bot 维护内存状态（dict，不持久化到 DB，避免 Alembic 迁移），包含 `current_problem`（正在做的题 ID）和 `ticks_remaining`（剩余 tick 数）。当 `ticks_remaining` 归零时，按 P(AC) 公式判定是否解出，然后选择下一题
5. **新增配置项**（`contest.simulation`）:
   - `tick_interval_seconds`: 30（默认 tick 间隔）
   - `bot_count`: 50（机器人数量，已有）
   - `focus_mode`: true（每次只做 1 题）
   - `difficulty_ticks`: 简单/中等/难的 tick 范围
6. **保留现有的 P(AC) 公式和 time_factor 机制**，仅在"何时投骰子"上改变行为

**调用方清单**:
- `contest_simulation_service.py:_run_simulation_loop` (line ~200-255) — 模拟主循环，需调整 tick 间隔
- `contest_simulation_service.py:_simulate_bot_tick` (line ~580-627) — 核心解题逻辑，需重构为"聚焦一题"模式
- `contest_simulation_service.py:generate_bots` (line ~80-160) — Bot 生成，可能需要增加 `current_problem` 和 `ticks_remaining` 字段
- `backend/app/models/contest.py` — ContestBot 模型，可能需要新增字段（或使用内存状态）

**反向集成清单**:
- PR 结算逻辑 (`contest_service.py`) 依赖机器人的 solved_problem_ids，确保重构后该字段更新正确
- WebSocket 排行榜推送依赖 `tick_simulation` 的返回值，确保新逻辑仍正确推送更新

#### 测试要点
- [ ] **简单题延迟**: AI 不会在比赛第 1 分钟就解出所有简单题
- [ ] **难度递增**: 难题的解题时间明显长于简单题
- [ ] **单题专注**: 每个 bot 每次 tick 最多解出 1 道题
- [ ] **P(AC) 公式不变**: Elo 高的 bot 解难题概率仍高于 Elo 低的 bot
- [ ] **PR 结算正常**: 比赛结束后 PR 和 Elo 结算仍然正确
- [ ] **WebSocket 排行榜**: 排行榜仍然实时更新
- [ ] **配置可热更新**: tick 间隔和难度参数可通过 admin config 页面调整

---

## 阶段 26: PvP 挑战模式致命 Bug 修复 (2026-05-20)

> 诊断报告确认 PvP 模式存在三个致命缺陷：
> 1. 多 worker 内存状态不共享，匹配成功率约 1/16
> 2. 前后端结果协议断裂，胜负/Elo/Token 展示全部错误
> 3. 页面刷新后无法恢复比赛，无恢复入口
>
> 修复方案：引入 Redis 共享状态 + 后端视角转换 + 对标 Contest 恢复机制

### Task 26.1: Redis 基础设施 + 匹配状态迁移
**状态**: 🟢 已完成
**优先级**: P0
**依赖**: 无

#### 任务描述
引入 Redis 作为共享状态存储，将 `MatchService._queue` 和 `_pending_matches` 从进程内存迁移到 Redis，解决多 worker 环境下状态不共享的根本问题。

**根因**: `MatchService._queue`（`match_service.py:86`）和 `_pending_matches`（`challenge_service.py:75`）都是模块级全局变量，每个 Gunicorn worker 独立一份。生产环境 4 worker 下，匹配成功率约 1/16。

**需要修改/新增的文件**:

1. `docker-compose.yml` + `docker-compose.prod.yml` — 新增 Redis 服务容器
2. `backend/app/core/redis.py` — 新建，Redis 连接管理（连接池、配置）
3. `backend/app/core/config.py` — 新增 Redis URL 配置项
4. `backend/app/services/match_service.py` — `_queue` 从内存 dict 迁移到 Redis Sorted Set（按 Elo 排序）
5. `backend/app/services/challenge_service.py` — `_pending_matches` 从内存 dict 迁移到 Redis Hash，设置 TTL 5 分钟
6. `.env.example` — 新增 `REDIS_URL` 环境变量

**关键实现细节**:
1. Redis 连接使用 `redis.asyncio` 异步客户端，连接池模式
2. `_queue` 用 Redis Sorted Set 实现，score 为用户 Elo，member 为用户 ID 的 JSON 序列化（含 user_id、elo、joined_at）
3. `_pending_matches` 用 Redis Hash 实现，key 为 `pending_match:{session_id}`，value 为匹配详情 JSON，TTL 5 分钟
4. 匹配操作使用 Lua 脚本保证原子性（如 `try_match` 中读取 + 移除队列成员 + 创建 pending 记录需原子执行）
5. 匹配算法（概率权重：close 50% / challenge 25% / consolidate 15% / far 10%）逻辑不变，仅数据源从内存改为 Redis
6. Redis 不可用时降级处理：日志告警，返回服务不可用错误

**调用方清单**:
- `challenge_service.py:join_queue`（~L100） — 调用 `match_svc.join_queue`，需适配 Redis 版本
- `challenge_service.py:get_queue_status`（~L185） — 读取 `_pending_matches` 和 DB，需改为 Redis 读取
- `challenge_service.py:start_challenge`（~L280） — 读取 `_pending_matches` 确认状态，需改为 Redis 读取
- `challenge_service.py:submit_result`（~L340） — 清除 `_pending_matches`，需改为 Redis 删除
- `challenge_service.py:quit_challenge`（~L530） — 清除 `_pending_matches`，需改为 Redis 删除
- `match_service.py` 全部公开方法 — `join_queue`、`leave_queue`、`try_match`、`try_match_any`、`get_queue_status`

**反向集成清单**:
- 无横切特性集成，纯基础设施变更

**触发场景**:
- 用户点击"寻找对手"加入匹配队列
- 匹配成功后双方确认开始
- 退出匹配队列或退出比赛

#### 测试要点（防Workaround验证清单）
- [ ] **单 worker 匹配**: 单 worker 下匹配流程完整（加入队列 → 匹配 → 确认 → 开始）
- [ ] **多 worker 匹配**: 4 worker 下两个用户能稳定匹配成功（不再依赖路由到同一 worker）
- [ ] **队列状态查询**: 加入队列后 `get_queue_status` 正确返回排队状态
- [ ] **离开队列**: 用户离开队列后 Redis 中无残留数据
- [ ] **pending TTL**: 匹配后 5 分钟内未确认，pending 记录自动过期
- [ ] **原子性**: 两个用户同时被匹配时不会出现重复 session
- [ ] **Redis 不可用降级**: Redis 连接失败时返回 503 而非崩溃
- [ ] **现有匹配算法不变**: close/challenge/consolidate/far 权重概率不变
- [ ] **前端无感知**: 前端 API 调用和返回格式不变

#### 验收标准
1. 多 worker 环境下匹配成功率 100%（不再受 worker 路由影响）
2. Redis 连接稳定，原子操作正确
3. 前端无需修改即可正常使用匹配功能

---

### Task 26.2: 后端视角转换 + 前端结果展示修复
**状态**: 🟢 已完成
**优先级**: P0
**依赖**: 无（与 Task 26.1 并行）

#### 任务描述
修复后端 API 返回用户视角的胜负结果、Elo 变化、Token 奖励，同时修复前端对结果的展示逻辑。

**根因**:
1. 后端 `_settle_challenge` 返回 `challenger_win`/`opponent_win`，前端期望 `win`/`loss`/`draw`
2. `elo_change` 和 `tokens_earned` 始终返回 challenger 视角，opponent 看到错误数据
3. 前端结果页固定显示 `challenger_time`/`challenger_submissions`，不区分角色

**需要修改的文件**:

后端:
- `backend/app/services/challenge_service.py`:
  - `_settle_challenge`（~L670）— 新增 `submitting_user_id` 参数，返回该用户视角数据
  - `get_challenge_detail`（~L850）— 根据请求用户返回视角转换后的 `result`、`elo_change`
  - `submit_result`（~L340）— 响应中 `result`/`elo_change`/`tokens_earned` 为当前用户视角
  - API 响应层新增视角转换：DB 原值 `challenger_win`/`opponent_win`/`draw` → 用户视角 `win`/`loss`/`draw`

前端:
- `frontend/src/pages/ChallengePage.tsx`:
  - `start_challenge` 返回 `no_match` 时（~L120）不进入 `in_progress`，显示错误提示
  - 验证 `session_id` 不为空/undefined（~L122）
  - 结果页（~L466）适配新的 `win`/`loss`/`draw` 值
  - 结果页统计数据（~L545）根据当前用户角色显示对应字段

**关键实现细节**:

后端视角转换:
1. DB `ChallengeSession.result` 保持原值（`challenger_win`/`opponent_win`/`draw`），视角转换仅在 API 响应层
2. 新增辅助方法 `_result_for_user(session: ChallengeSession, user_id: UUID) -> str`：
   - `draw` → `draw`
   - `challenger_win` + user_id == challenger_id → `win`
   - `challenger_win` + user_id == opponent_id → `loss`
   - `opponent_win` + user_id == opponent_id → `win`
   - `opponent_win` + user_id == challenger_id → `loss`
   - `challenger_quit` + user_id == challenger_id → `quit`
   - `challenger_quit` + user_id == opponent_id → `win`
   - `opponent_quit` + user_id == opponent_id → `quit`
   - `opponent_quit` + user_id == challenger_id → `win`
3. `opponent_elo_change` 存储：新增 `opponent_elo_change` 字段到 `ChallengeSession` 模型（含 migration），`_settle_challenge` 中同时存储两个用户的 elo_change。当前 DB 仅存 `session.elo_change = challenger_elo_change`，opponent 的 elo_change 被丢弃。新增字段后 `get_challenge_detail` 和 `submit_result` 响应根据用户角色返回对应值
4. `opponent_tokens_earned` 同理：新增字段或使用 JSON 存储，确保 API 返回当前用户的 token 奖励
5. `ChallengeDetail` schema 新增 `is_challenger: bool` 字段，前端据此切换统计展示
6. 统计数据（time/submissions）返回双方数据（`challenger_time`/`opponent_time`/`challenger_submissions`/`opponent_submissions`），前端根据 `is_challenger` 选择显示

前端适配:
1. `start_challenge` 调用后检查 `status` 字段，`no_match` 时回到 `matched` 或 `idle` 状态
2. 验证 `session_id` 存在后才进入 `in_progress`
3. 结果页使用 `result === "win"` / `result === "loss"` / `result === "draw"` / `result === "quit"` 判断
4. 后端返回 `is_challenger: bool` 字段，前端据此选择 `challenger_time`/`opponent_time` 等字段展示

**调用方清单**:
- `challenge_service.py:submit_result` — 调用 `_settle_challenge`，需传入 user_id
- `challenge_service.py:get_challenge_detail` — 返回详情，需做视角转换
- `challenge_service.py:quit_challenge` — 退出结果也需视角转换
- `ChallengePage.tsx:handleStart`（~L120）— 需增加 status 检查
- `ChallengePage.tsx:handleSubmit`（~L350）— 提交结果展示需适配
- `ChallengePage.tsx` 结果页（~L466）— 判断逻辑需适配

**反向集成清单**:
- Elo 结算逻辑不变（K 因子、S 值、提示衰减等横切特性不受影响）
- 代币奖励逻辑不变
- PP 计算不变

**触发场景**:
- 两人对战完成，查看胜负结果
- 查看挑战详情页（Elo 变化、统计信息）
- 退出比赛查看惩罚

#### 测试要点（防Workaround验证清单）
- [ ] **challenger 胜利**: challenger 调用 API 返回 `result=win`，`elo_change > 0`
- [ ] **challenger 失败**: challenger 调用 API 返回 `result=loss`，`elo_change < 0`
- [ ] **opponent 胜利**: opponent 调用 API 返回 `result=win`，`elo_change > 0`
- [ ] **opponent 失败**: opponent 调用 API 返回 `result=loss`，`elo_change < 0`
- [ ] **平局**: 双方都返回 `result=draw`
- [ ] **退出**: 退出者返回 `result=quit`，对手返回 `result=win`
- [ ] **tokens_earned 正确**: 各用户看到自己的 token 奖励
- [ ] **前端 start_challenge 错误处理**: `no_match` 时不进入做题，显示错误提示
- [ ] **前端 session_id 校验**: `session_id` 为空时不请求 `GET /challenge/undefined`
- [ ] **前端结果页**: challenger 和 opponent 看到各自的胜负、Elo、时间、提交数
- [ ] **DB 原值不变**: ChallengeSession.result 仍为 `challenger_win`/`opponent_win`/`draw`

#### 验收标准
1. 两个用户各自看到正确的胜负结果、Elo 变化、Token 奖励
2. 前端不再因 `no_match` 而进入做题状态
3. DB 存储格式不变，视角转换仅在 API 响应层

---

### Task 26.3: 比赛恢复机制
**状态**: 🟢 已完成
**优先级**: P0
**依赖**: Task 26.1（Redis 迁移完成后匹配才能正常工作）, Task 26.4（需要 problem_name 字段恢复题面）

#### 任务描述
对标 Contest 模式实现 PvP 挑战的比赛恢复机制：新增专用 API、前端路由、Dashboard 恢复入口、ChallengePage 自动恢复。

**根因**: `ChallengePage` 用 `useState` 保存 `sessionId`，刷新即丢失。Dashboard 无 PvP 恢复入口。后端 `get_queue_status` 查询了 pending 状态但不处理。

**需要新增/修改的文件**:

后端:
- `backend/app/api/v1/challenge.py` — 新增 `GET /challenge/active` 端点
- `backend/app/services/challenge_service.py` — 新增 `get_active_challenge` 方法

前端:
- `frontend/src/App.tsx` 或路由配置 — 新增 `/challenge/:sessionId` 路由
- `frontend/src/pages/ChallengePage.tsx` — 支持通过 URL `sessionId` 加载比赛 + 挂载时调用 `/challenge/active` 检查
- `frontend/src/pages/DashboardPage.tsx` — 新增 PvP 活跃挑战恢复横幅

**关键实现细节**:

后端:
1. `GET /challenge/active`：查询当前用户 `status IN ('active')` 的 ChallengeSession，返回 session 概要（id、problem_id、problem_name、created_at、opponent 信息），无活跃会话返回 null
2. `get_challenge_detail` 需支持返回完整题目信息（需 Task 26.4 的 `problem_name` 字段，或临时从 CF API 补充获取）
3. 恢复的 session 需要返回 `is_challenger` 角色标识

前端:
1. 新增路由 `/challenge/:sessionId`，参数可选（无参数时显示 idle 页面，有参数时加载对应 session）
2. ChallengePage 挂载逻辑：
   - 有 URL `sessionId` → 直接加载该 session
   - 无 URL `sessionId` → 调用 `/challenge/active` 检查
   - 有活跃 session → 恢复到 `in_progress` 状态
   - 无活跃 session → 显示 `idle`
3. 恢复计时器：从 `session.created_at` 计算 `elapsed = now - created_at`（秒），不从 0 开始
4. DashboardPage 新增恢复横幅：类似 Contest 的 "Resume Contest" 横幅，检测到活跃 PvP 时显示 "Resume Challenge" 按钮跳转到 `/challenge/:sessionId`
5. 恢复后正常进入做题/提交/结算流程

**调用方清单**:
- `DashboardPage.tsx`（~L79）— 已有 `GET /contest/active` 调用，需新增 `GET /challenge/active`
- `ChallengePage.tsx` — 挂载时新增恢复检查逻辑
- `App.tsx` 路由配置 — 新增 `/challenge/:sessionId` 路由

**反向集成清单**:
- 需集成 i18n（横幅文字需翻译）
- 无其他横切特性依赖

**触发场景**:
- 用户刷新挑战页面
- 用户在 Dashboard 页面看到有进行中的 PvP 挑战
- 用户通过 URL 直接访问 `/challenge/{sessionId}`

#### 测试要点（防Workaround验证清单）
- [ ] **刷新页面恢复**: 比赛进行中刷新页面，自动恢复到做题状态
- [ ] **关闭浏览器恢复**: 关闭浏览器后重新打开，从 Dashboard 点击恢复
- [ ] **计时器恢复**: 恢复后计时器从正确时间继续（非从 0 开始）
- [ ] **Dashboard 横幅**: 有活跃挑战时显示"继续挑战"按钮
- [ ] **Dashboard 无活跃**: 无活跃挑战时不显示横幅
- [ ] **URL 直接访问**: `/challenge/{sessionId}` 直接加载对应比赛
- [ ] **无活跃时 idle**: 无活跃挑战时页面显示 idle 状态
- [ ] **i18n**: 恢复横幅文字有中英文翻译

#### 验收标准
1. 刷新页面或关闭浏览器后能恢复进行中的 PvP 比赛
2. Dashboard 有恢复入口
3. 计时器正确恢复
4. 对标 Contest 模式的恢复体验

---

### Task 26.4: 僵尸 Session 清理 + 题目信息持久化
**状态**: 🟢 已完成
**优先级**: P1
**依赖**: 无（与 Task 26.1/26.2 并行）

#### 任务描述
两部分：1) 清理数据库中无法恢复的僵尸 session；2) 在 ChallengeSession 中持久化题目名称，确保恢复时能显示完整题面。

**需要新增/修改的文件**:

1. `backend/migrations/versions/` — 新增迁移：
   - ChallengeSession 新增 `problem_name` 字段（VARCHAR, nullable）
   - 将所有 `status IN ('pending', 'active')` 的 session 标记为 `cancelled`（一次性清理）
2. `backend/app/models/challenge.py` — ChallengeSession 模型新增 `problem_name` 字段
3. `backend/app/services/challenge_service.py`:
   - 创建 session 时保存 `problem_name`
   - `get_challenge_detail` 返回 `problem_name`

**关键实现细节**:
1. `problem_name` 可空，兼容迁移前已存在的 session
2. 创建 session 时从 CF 题目数据中获取 `problem_name` 并存入 DB
3. 迁移中的僵尸清理：`UPDATE challenge_sessions SET status='cancelled', result='expired' WHERE status IN ('pending', 'active')`
4. 被清理的 session 不进行 Elo 结算、不扣代币
5. 清理仅在迁移执行时运行一次

#### 测试要点（防Workaround验证清单）
- [ ] **僵尸清理**: 迁移后所有 pending/active session 状态变为 cancelled
- [ ] **已完成不受影响**: completed 状态的 session 不被清理
- [ ] **problem_name 存储**: 新建 session 时 problem_name 正确保存
- [ ] **detail 返回 problem_name**: `get_challenge_detail` 返回 problem_name
- [ ] **旧数据兼容**: 无 problem_name 的旧 session 返回 null 不报错
- [ ] **迁移幂等**: 重复执行迁移不报错

#### 验收标准
1. 僵尸 session 清理完成
2. 新建 session 持久化题目名称
3. 恢复比赛时能显示题目名称

---

### 任务依赖关系

```
阶段 26 (PvP 修复):
  26.1 Redis + 匹配迁移 ← 无依赖 (P0)
  26.2 视角转换 + 前端修复 ← 无依赖 (P0, 与 26.1 并行)
  26.4 僵尸清理 + 题目持久化 ← 无依赖 (P1, 与 26.1/26.2 并行)
  26.3 比赛恢复 ← 26.1 + 26.4 (P0)
```

**建议执行顺序**: 26.1 + 26.2 + 26.4 并行开发 → 26.3
