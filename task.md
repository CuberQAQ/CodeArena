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
