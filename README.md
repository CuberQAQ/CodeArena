# Code Arena

将算法竞赛练习转化为游戏化体验的在线竞技编程平台。基于 Codeforces API 构建四种游戏模式，通过 Elo 评级、成就系统和代币经济激励用户持续练习。

## 游戏模式

| 模式 | 说明 |
|------|------|
| PvP 挑战 | 1v1 实时对战，匹配相近实力的对手 |
| PvE 挑战 | 随机难度盲盒，匹配当前 Elo ± 200 的题目 |
| 专题训练 | 按算法专题定向练习，新手学习护盾保护 Elo |
| 虚拟比赛 | 模拟 CF Div.1-5 比赛，与 AI 选手同场竞技 |

## 核心特性

- **多维评级体系** — Elo + M-Elo（按专题细分）+ PP（Performance Points）衰减加权排名
- **智能题目匹配** — 基于 Elo 的难度区间匹配，K-factor 动态调整，Overkill 奖励
- **实时提交通道** — WebSocket 判定推送 + Patchright 浏览器自动化远程提交至 Codeforces
- **提示与经济系统** — 三级提示体系（逐步解锁），代币奖励与消费闭环
- **成就与奖牌** — XCPC 风格多级奖牌，8 维算法能力雷达图
- **全球排名** — 混合 CF 用户采样估算的全局排行榜
- **PWA 支持** — 离线缓存，可安装至桌面

## 技术栈

### 后端

- **框架**：FastAPI (Python 3.11+)
- **数据库**：PostgreSQL 16 + SQLAlchemy ORM
- **缓存/队列**：Redis
- **后台任务**：Celery（提交状态轮询、超时结算）
- **认证**：JWT (python-jose)
- **浏览器自动化**：Patchright（Codeforces 远程提交）
- **测试**：pytest + pytest-asyncio + Hypothesis (Property-based Testing)

### 前端

- **框架**：React 19 + TypeScript
- **构建**：Vite + vite-plugin-pwa
- **UI**：Tailwind CSS 4 + shadcn/ui + Framer Motion
- **状态管理**：Zustand
- **路由**：React Router DOM v7
- **国际化**：i18next（中/英双语）
- **图表**：Recharts
- **测试**：Vitest + Playwright E2E + React Testing Library

### 基础设施

- Docker Compose 多服务编排（backend / frontend / PostgreSQL / Redis / nginx）
- nginx 反向代理 + 静态资源托管
- 健康检查与结构化日志

## 快速开始

```bash
# 克隆仓库
git clone https://github.com/CuberQAQ/CodeArena.git
cd CodeArena

# 复制环境变量
cp .env.example .env

# 启动开发环境
docker compose -f docker-compose.dev.yml up --build
```

访问 `http://localhost` 即可使用。

## 项目结构

```
code-arena/
├── backend/                # FastAPI 后端
│   ├── app/
│   │   ├── api/v1/         # REST API 路由
│   │   ├── models/         # SQLAlchemy 数据模型
│   │   ├── schemas/        # Pydantic 请求/响应模式
│   │   └── services/       # 业务逻辑层
│   ├── migrations/         # Alembic 数据库迁移
│   └── tests/              # pytest 测试套件
├── frontend/               # React 前端
│   └── src/
│       ├── components/     # UI 组件
│       ├── pages/          # 页面组件
│       ├── services/       # API 调用层
│       ├── stores/         # Zustand 状态管理
│       └── locales/        # i18n 翻译文件
├── nginx.conf              # 反向代理配置
└── docker-compose.yml      # 服务编排
```

## Agent 驱动开发

本项目采用多角色 Agent 协作开发流程，实现需求→任务→实现→测试→审计的全链路自动化闭环：

- **feature-engineer** — 按 requirements.md 实现功能，交付生产级代码
- **professional-test-engineer** — 以需求文档为标准验证交付物
- **requirements-auditor** — 逐条比对需求与代码实现的一致性
- **bug-diagnostician** — 诊断 bug 根因、追踪调用链、评估影响范围

每个任务独立调度 Agent，通过集成点追踪与可达性自检保障 50+ 独立任务的需求覆盖率。

## License

MIT
