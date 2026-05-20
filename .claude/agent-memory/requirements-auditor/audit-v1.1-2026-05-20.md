---
name: audit-v1.1-2026-05-20
description: 需求V1.1 B节点变更影响审计结果摘要
metadata:
  type: project
---

## 审计日期：2026-05-20
## 需求版本：V1.1

### 核心发现
- 8 项 PASS，7 项 PARTIAL，8 项 NOT_FOUND，2 项 FAIL
- 合规率：31%（仅 PASS 项 / 总需求项数）

### 需要新增的功能（NOT_FOUND）：8 项
1. FR-3.1 M-Elo 子能力实体（数据模型+服务）
2. FR-3.3 护盾机制（首次 AC 前不扣 Elo）
3. FR-2.3 / Model 3.5 越级奖励（PP 乘数 + 成就事件）
4. FR-4.1 虚拟 Bot 生成
5. FR-4.2 赛况模拟引擎（按分钟级 Bot 过题模拟）
6. FR-4.3 表现分 (PR) 反推（二分查找）
7. FR-2.1 PvE 随机挑战（单人模式）
8. FR-1.2 异步 CF 状态追踪

### 需要修改的功能（PARTIAL + FAIL）：9 项
1. Model 3.2 K因子分段函数（FAIL - 当前固定 K=32）
2. Model 3.3 S 值分级（PARTIAL - 无完美 AC / 失误 AC 区分）
3. Model 3.4 PP 表现因子（PARTIAL - 缺 f(wa, t) 表现因子）
4. FR-3.4 专题训练系数（PARTIAL - K_train=8 固定值）
5. FR-3.2 标签分流抽取（PARTIAL - 使用 Global Elo 而非 M-Elo）
6. FR-2.2 盲盒 UI（FAIL - 前端展示 rating 和 tags）
7. FR-5.1 虚拟代币（PARTIAL - 缺尝试奖励）
8. FR-5.3 Elo 衰减惩罚（PARTIAL - 衰减逻辑未串联到结算流程）
9. 雷达图数据源（PARTIAL - 显示完成率而非 M-Elo 值）

### 关键代码位置
- Elo 服务: `backend/app/services/elo_service.py`
- PP 服务: `backend/app/services/pp_service.py`
- 挑战服务: `backend/app/services/challenge_service.py`
- 训练服务: `backend/app/services/training_service.py`
- 比赛服务: `backend/app/services/contest_service.py`
- 经济服务: `backend/app/services/economy_service.py`
- 提示服务: `backend/app/services/hint_service.py`
- 用户模型: `backend/app/models/user.py`
- 默认配置: `backend/app/core/default_config.py`
- 前端挑战页: `frontend/src/pages/ChallengePage.tsx`
- 前端雷达图: `frontend/src/components/charts/RadarChart.tsx`
