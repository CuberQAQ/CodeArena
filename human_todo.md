# 待用户决策事项

> 以下为开发过程中需要用户介入的决策点。
> Claude 会继续执行不阻塞的其他任务。

---

## 1. SettingsPage 实现方案

**问题**：前端当前无独立的 SettingsPage。Task 30.2 需要展示模式切换（奖牌制/CF段位制），需要一个设置页面入口。

**需要确认**：
- 新建独立 `/settings` 路由页面，还是嵌入 ProfilePage？
- 导航栏入口放在哪里？
- `display_mode` 存储在服务端（user_settings 表，需 API）还是前端 localStorage 即可？

**当前决策**：新建 `/settings` 页面 + 服务端存储（user_settings 表）+ 导航栏头像下拉菜单入口。如果用户有不同偏好请在回来后告知。

---

## 2. 排行榜奖牌展示策略

**问题**：排行榜显示多人信息时，"展示体系切换"的语义不清晰——是看每个用户各自的设置，还是看当前浏览者的全局设置？

**当前决策**：排行榜按当前浏览者的 display_mode 设置统一展示（即切换后所有人统一显示奖牌或统一显示 CF 段位）。如果需要每用户独立展示请告知。

---

## 3. Dashboard 奖牌制下的 Elo 数值展示

**问题**：切换到奖牌制后，Dashboard 是否仍显示 Elo 数字？还是完全替换为奖牌牌面？

**当前决策**：奖牌牌面 + 保留 Elo 数字展示（卡片上同时显示奖牌图标和 Elo 数值）。如果需要完全替换请告知。

---

## 4. EC Final 奖牌阈值重叠问题

**问题**：FR-10.1 定义的奖牌阈值中，EC Final 的阈值与 World Finals 和 Regional 重叠：
- EC Final gold (≥2600) = World Finals silver (≥2600)
- EC Final silver (≥2400) = World Finals bronze (≥2400)
- EC Final bronze (≥2200) = Regional gold (≥2200)

**当前决策**：使用扁平化的非重叠阈值映射，EC Final 不作为独立 tier 出现在映射中。实际映射为：
- ≥2800: WF gold, ≥2600: WF silver, ≥2400: WF bronze
- ≥2200: Regional gold, ≥2000: Regional silver, ≥1800: Regional bronze
- ≥1600: Provincial gold, ≥1400: Provincial silver, ≥1200: Provincial bronze

MEDAL_TIERS 常量保留 EC Final 定义（供前端展示用），但 `_rating_to_medal` 使用扁平列表。如果希望 EC Final 作为独立 tier 出现，需要调整其阈值使其不与 WF/Regional 重叠（如 EF gold ≥2500, silver ≥2300, bronze ≥2100）。

---

## 5. 自由选题退出惩罚 (FR-4.6 vs FreePlay)

**问题**：Task 29.2 测试发现 `quit_session` 不应用 FR-4.6 的分级退出惩罚（0次提交无变化、1-2次-5到-10、3+次正常失败），当前 `elo_change=0, penalty=0`。代码注释 "No Elo penalty for quitting free play (no opponent affected)"。

**需要确认**：
- 自由选题模式退出是否需要应用 FR-4.6 的分级惩罚？
- 如果不惩罚，需要在 requirements.md 中明确豁免
- 如果要惩罚，需要修改 quit_session 接受 submissions 参数并计算惩罚

**当前决策**：暂不修改，等待用户决策。

---

## 6. 比赛模式缺少成就事件 (审计节点 C 发现)

**问题**：审计发现比赛模式（contest_service）没有触发越级成就事件和个人最高 PP 成就事件。其他 4 个模式（PvE/PvP/自由选题/训练）都有。

**影响**：FR-3.5 规定"触发越级奖励时需触发成就事件"，比赛模式应同样触发。

**建议修复**：在 `contest_service.py` 的 `_settle_with_pr` 中添加越级成就检测。

**当前状态**：暂未修复，等待用户确认是否需要。

---

## 7. Training/Contest 页面未集成 ProblemViewer iframe (审计节点 C 发现)

**问题**：FR-14.1 要求非盲盒模式通过 iframe 嵌入 CF 题目页。ProblemViewer 组件已实现且集成到 FreePlay，但 TrainingDetailPage 和 ContestDetailPage 仍仅提供外部链接。

**影响**：训练和比赛模式下用户需要切换到 CF 网站看题，体验不一致。

**当前状态**：暂未修复，等待用户确认是否需要。
