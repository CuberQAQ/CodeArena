# Code Arena - 项目任务清单

## 需求文档

### 项目概述
竞技编程游戏化平台（Code Arena），集成 Codeforces API，提供随机挑战、专题训练、虚拟组赛三种核心玩法，配合 Elo 评级、PP 系统、经济与提示系统，以及数据可视化和沉浸式动画。

### 技术栈
- 前端: React + Tailwind CSS + shadcn/ui
- 后端: Python FastAPI
- 数据库: PostgreSQL
- 架构: 前后端分离，RESTful API
- 部署: Docker

### 核心数学模型
- **初始 Elo**: 1200
- **所有 Elo/PP 参数为可配置项**: 管理员页面热更新，与配置文件同步

### PP 系统
- **单题基础 PP 公式**: `P_i = sqrt((rating - 800) / 100) * 10`
  - rating < 800 时 P_i = 0
  - rating = 800 => 0 PP, 1200 => 20 PP, 1500 => 26.46 PP, 2000 => 34.64 PP, 2500 => 41.23 PP, 3000 => 46.90 PP, 3500 => 51.96 PP
- **总 PP 计算**: 取 PP 最高的前 100 题，按基础 PP 降序排列，第 n 题权重为 0.95^(n-1)，累加
  - Total PP = SUM(i=1 to 100) P_i * 0.95^(i-1)
- **提示对 PP 无影响**: PP 获取不受提示使用影响

### 核心玩法

1. **随机挑战 - 概率加权匹配**:
   - Elo +/-100 以内: 权重 50%
   - Elo +100~+300: 权重 25%（挑战区）
   - Elo -100~-300: 权重 15%（巩固区）
   - +/-300 以外: 权重 10%（惊喜/极限区）

2. **专题训练 - 自由选择+连击奖励**:
   - 专题内题目自由选择
   - 按完成率评星级(0-5星)
   - 连续从低到高完成可获额外连击奖励

3. **虚拟组赛 - 动态配置+分级赛制**:
   - 新手赛（Elo < 1400）: 90min/4题，800-1400
   - 进阶赛（Elo 1400-1800）: 120min/5题，1200-2000
   - 大师赛（Elo > 1800）: 150min/6题，1600-2600

4. **失败处理 - 阶梯惩罚**:
   - 提交 0 次退出 = 未参与，Elo 不变
   - 提交 1-2 次后退出 = Elo 小降(-5到-10)
   - 提交 3 次以上 = 正常失败处理

### 经济系统

1. **代币产出 - 阶梯产出**:
   - 灰(800-1099): AC=10, 尝试=2
   - 绿(1100-1399): AC=20, 尝试=3
   - 蓝(1400-1699): AC=30, 尝试=4
   - 紫(1700-1999): AC=40, 尝试=5
   - 黄/红(2000+): AC=50, 尝试=6
   - 长时间尝试(>20min)额外加成
   - 每日上限 120 代币

2. **提示定价 - 难度浮动定价**:
   - 灰: 3/10/20 (累计33)
   - 绿: 5/15/30 (累计50)
   - 蓝: 8/20/40 (累计68)
   - 紫: 10/25/50 (累计85)
   - 黄/红: 15/30/60 (累计105)
   - 逐级解锁，不可跳级

3. **提示惩罚 - 指数衰减**（仅影响 Elo 增益，不影响 PP）:
   - 一级提示: 75% Elo 增益
   - 二级提示: 50% Elo 增益
   - 三级提示: 25% Elo 增益

### CF API 集成
- 不存储题库，每次通过 CF API 实时获取
- 用户注册时验证 CF Handle
- 需防限流机制
- CF API 文档: https://codeforces.com/apiHelp

---

## 阶段 1: 项目基础设施

### Task 1.1: 项目目录结构搭建
**状态**: 🟢 已完成 (2025-05-19)
**优先级**: P0
**依赖**: 无

#### 任务描述
创建完整的项目目录结构，包含前端和后端的基础框架。

**需要创建的目录和文件**:
```
code-arena/
  frontend/
    src/
      components/     # UI组件
      pages/          # 页面
      hooks/          # 自定义hooks
      services/       # API调用
      stores/         # 状态管理
      utils/          # 工具函数
      types/          # TypeScript类型定义
      styles/         # 全局样式
    public/
    package.json
    tsconfig.json
    vite.config.ts
    tailwind.config.ts
    index.html
  backend/
    app/
      api/            # API路由
        v1/
      core/           # 核心配置
      models/         # 数据模型
      schemas/        # Pydantic schemas
      services/       # 业务逻辑
      utils/          # 工具函数
      middleware/     # 中间件
    tests/
    requirements.txt
    pyproject.toml
    alembic.ini
    migrations/       # 数据库迁移
  docker-compose.yml
  Dockerfile.frontend
  Dockerfile.backend
  .env.example
  .gitignore
```

**具体要求**:
- 前端使用 Vite + React + TypeScript，配置 Tailwind CSS 和 shadcn/ui
- 后端使用 FastAPI，配置 uvicorn，结构化为多层架构
- 创建 .env.example 包含所有需要的环境变量模板
- 创建 .gitignore 覆盖 Python 和 Node.js 的忽略规则

#### 测试要点（防Workaround验证清单）
- [ ] **结构完整性**: 所有上述目录和文件都存在
- [ ] **前端可启动**: `npm install && npm run dev` 能正常启动（显示默认页面）
- [ ] **后端可启动**: `pip install -r requirements.txt && uvicorn app.main:app` 能正常启动
- [ ] **Tailwind 配置正确**: 前端页面能正确应用 Tailwind 类名
- [ ] **TypeScript 配置正确**: 无 TS 编译错误
- [ ] **环境变量模板完整**: .env.example 包含数据库连接、CF API、JWT_SECRET 等所有必要变量

#### 验收标准
1. 目录结构与上述规格完全一致
2. 前端 npm install 后 npm run dev 可启动，localhost 可访问
3. 后端 pip install 后 uvicorn 可启动，localhost:8000/docs 可访问 Swagger UI
4. .env.example 列出所有环境变量

#### 技术备注
- 前端端口默认 5173，后端端口默认 8000
- shadcn/ui 使用 `npx shadcn@latest init` 初始化

---

### Task 1.2: Docker 配置
**状态**: 🟢 已完成 (2025-05-19)
**优先级**: P0
**依赖**: Task 1.1

#### 任务描述
创建完整的 Docker 开发和部署配置，包括前端、后端和 PostgreSQL 的容器化。

**需要创建/修改的文件**:
- `Dockerfile.frontend` - 前端多阶段构建（build + nginx 服务）
- `Dockerfile.backend` - 后端 Python 镜像
- `docker-compose.yml` - 编排三个服务: frontend, backend, db(postgres)
- `nginx.conf`（如需要）- 前端 SPA 路由和 API 代理

**具体要求**:
- PostgreSQL 容器: 使用官方 postgres:16 镜像，配置持久化卷
- 后端容器: 基于 python:3.12-slim，安装依赖，暴露 8000 端口
- 前端容器: 多阶段构建，第一阶段 npm build，第二阶段 nginx 服务静态文件
- docker-compose 中配置服务依赖关系（backend depends_on db）
- 配置健康检查
- 环境变量通过 .env 文件注入
- 开发模式下前端支持热重载（volume mount）

#### 测试要点（防Workaround验证清单）
- [ ] **完整构建**: `docker-compose build` 无错误完成
- [ ] **全部启动**: `docker-compose up -d` 三个服务全部 running
- [ ] **数据库连接**: 后端容器能成功连接 PostgreSQL
- [ ] **前端访问**: 浏览器可访问前端页面
- [ ] **后端 API**: 可访问后端 /docs Swagger 页面
- [ ] **数据持久化**: 停止并重启容器后数据不丢失
- [ ] **健康检查**: docker ps 显示 healthy 状态
- [ ] **开发热重载**: 修改前端代码后自动更新（开发模式）

#### 验收标准
1. `docker-compose up -d` 后所有服务正常启动
2. 前端、后端、数据库三者可互相通信
3. 数据库数据持久化正常
4. 停止再启动后数据不丢失

#### 技术备注
- 使用 docker-compose 的 healthcheck 确保 backend 在 db 就绪后才连接
- 开发环境使用 volume mount 实现热重载

---

### Task 1.3: 数据库 Schema 设计与迁移
**状态**: 🟢 已完成 (2025-05-19)
**优先级**: P0
**依赖**: Task 1.2

#### 任务描述
设计并实现完整的 PostgreSQL 数据库 Schema，使用 SQLAlchemy ORM + Alembic 迁移。

**数据表设计**:

1. **users** - 用户表
   - id (UUID, PK)
   - username (VARCHAR(50), UNIQUE, NOT NULL)
   - email (VARCHAR(255), UNIQUE, NOT NULL)
   - password_hash (VARCHAR(255), NOT NULL)
   - cf_handle (VARCHAR(100), UNIQUE) -- CF 绑定 handle
   - cf_handle_verified (BOOLEAN, DEFAULT FALSE)
   - elo (INTEGER, DEFAULT 1200)
   - pp (FLOAT, DEFAULT 0)
   - tokens (INTEGER, DEFAULT 0) -- 代币余额
   - daily_tokens_earned (INTEGER, DEFAULT 0) -- 今日已获取代币
   - daily_tokens_reset_at (TIMESTAMP) -- 代币重置时间
   - created_at (TIMESTAMP)
   - updated_at (TIMESTAMP)
   - last_login_at (TIMESTAMP)
   - is_active (BOOLEAN, DEFAULT TRUE)
   - is_admin (BOOLEAN, DEFAULT FALSE)

2. **elo_history** - Elo 变动历史
   - id (UUID, PK)
   - user_id (UUID, FK -> users.id)
   - elo_before (INTEGER)
   - elo_after (INTEGER)
   - elo_change (INTEGER)
   - reason (VARCHAR(50)) -- 'challenge_win', 'challenge_lose', 'training', 'contest', 'quit_early'
   - reference_id (UUID) -- 关联的挑战/训练/比赛ID
   - created_at (TIMESTAMP)

3. **pp_records** - PP 记录（用户每道题的 PP）
   - id (UUID, PK)
   - user_id (UUID, FK -> users.id)
   - cf_problem_id (VARCHAR(50)) -- 格式: "contestId_problemIndex" 如 "1234_A"
   - problem_rating (INTEGER)
   - base_pp (FLOAT)
   - solved_at (TIMESTAMP)
   - hints_used (INTEGER, DEFAULT 0)

4. **challenge_sessions** - 随机挑战会话
   - id (UUID, PK)
   - challenger_id (UUID, FK -> users.id)
   - opponent_id (UUID, FK -> users.id)
   - problem_id (VARCHAR(50))
   - problem_rating (INTEGER)
   - challenger_submissions (INTEGER, DEFAULT 0)
   - opponent_submissions (INTEGER, DEFAULT 0)
   - challenger_solved (BOOLEAN)
   - opponent_solved (BOOLEAN)
   - challenger_time (FLOAT) -- 解决用时(秒)
   - opponent_time (FLOAT)
   - status (VARCHAR(20)) -- 'active', 'completed', 'quit'
   - result (VARCHAR(20)) -- 'win', 'lose', 'draw', 'challenger_quit', 'opponent_quit'
   - elo_change (INTEGER)
   - hints_used_challenger (INTEGER, DEFAULT 0)
   - hints_used_opponent (INTEGER, DEFAULT 0)
   - created_at (TIMESTAMP)
   - completed_at (TIMESTAMP)

5. **topic_categories** - 专题分类
   - id (UUID, PK)
   - name (VARCHAR(100), UNIQUE)
   - slug (VARCHAR(100), UNIQUE)
   - description (TEXT)
   - cf_tags (JSONB) -- 关联的 CF tags 列表
   - display_order (INTEGER)

6. **training_sessions** - 专题训练会话
   - id (UUID, PK)
   - user_id (UUID, FK -> users.id)
   - topic_id (UUID, FK -> topic_categories.id)
   - problems_solved (INTEGER, DEFAULT 0)
   - total_problems (INTEGER)
   - streak_count (INTEGER, DEFAULT 0) -- 连击数
   - status (VARCHAR(20)) -- 'active', 'completed', 'abandoned'
   - created_at (TIMESTAMP)
   - completed_at (TIMESTAMP)

7. **training_problem_records** - 训练题目完成记录
   - id (UUID, PK)
   - session_id (UUID, FK -> training_sessions.id)
   - user_id (UUID, FK -> users.id)
   - topic_id (UUID, FK -> topic_categories.id)
   - problem_id (VARCHAR(50))
   - problem_rating (INTEGER)
   - solved (BOOLEAN)
   - attempts (INTEGER, DEFAULT 0)
   - time_spent (FLOAT) -- 秒
   - hints_used (INTEGER, DEFAULT 0)
   - solved_at (TIMESTAMP)

8. **contest_sessions** - 虚拟比赛会话
   - id (UUID, PK)
   - user_id (UUID, FK -> users.id)
   - contest_tier (VARCHAR(20)) -- 'beginner', 'advanced', 'master'
   - problems (JSONB) -- 题目列表
   - total_problems (INTEGER)
   - problems_solved (INTEGER, DEFAULT 0)
   - submissions (INTEGER, DEFAULT 0)
   - time_limit (INTEGER) -- 分钟
   - started_at (TIMESTAMP)
   - ended_at (TIMESTAMP)
   - status (VARCHAR(20)) -- 'active', 'completed', 'quit'
   - elo_change (INTEGER)

9. **contest_problem_records** - 比赛题目记录
   - id (UUID, PK)
   - contest_id (UUID, FK -> contest_sessions.id)
   - problem_id (VARCHAR(50))
   - problem_rating (INTEGER)
   - solved (BOOLEAN)
   - attempts (INTEGER, DEFAULT 0)
   - time_spent (FLOAT)
   - solved_at (TIMESTAMP)

10. **token_transactions** - 代币交易记录
    - id (UUID, PK)
    - user_id (UUID, FK -> users.id)
    - amount (INTEGER) -- 正为获得，负为消费
    - type (VARCHAR(30)) -- 'reward_ac', 'reward_attempt', 'reward_time_bonus', 'hint_purchase', 'streak_bonus', 'daily_reset'
    - reference_type (VARCHAR(30)) -- 'challenge', 'training', 'contest', 'hint'
    - reference_id (UUID)
    - balance_after (INTEGER)
    - created_at (TIMESTAMP)

11. **hint_purchases** - 提示购买记录
    - id (UUID, PK)
    - user_id (UUID, FK -> users.id)
    - problem_id (VARCHAR(50))
    - problem_rating (INTEGER)
    - hint_level (INTEGER) -- 1, 2, 3
    - tokens_cost (INTEGER)
    - created_at (TIMESTAMP)

12. **system_config** - 系统配置表（支持热更新）
    - id (UUID, PK)
    - config_key (VARCHAR(100), UNIQUE)
    - config_value (JSONB)
    - description (TEXT)
    - updated_at (TIMESTAMP)
    - updated_by (UUID, FK -> users.id)

**具体要求**:
- 所有 UUID 主键使用 PostgreSQL 的 uuid-ossp 扩展自动生成
- 所有时间字段使用 UTC，TIMESTAMP WITH TIME ZONE
- 外键设置 ON DELETE CASCADE（适用于子记录）或 ON DELETE SET NULL（适用于引用）
- 在 cf_handle, elo, pp 字段上创建索引
- 在 pp_records 上创建复合索引 (user_id, base_pp DESC) 用于快速计算总 PP
- 在 elo_history 上创建索引 (user_id, created_at DESC)
- 在 challenge_sessions 上创建索引 (challenger_id, created_at DESC) 和 (opponent_id, created_at DESC)
- 配置 Alembic 迁移，创建初始迁移文件

#### 测试要点（防Workaround验证清单）
- [ ] **迁移执行**: `alembic upgrade head` 无错误
- [ ] **所有表存在**: 查询 information_schema 确认 12 张表全部创建
- [ ] **所有字段正确**: 每张表的字段名、类型、约束与设计一致
- [ ] **外键约束**: 尝试插入无效外键数据应失败
- [ ] **唯一约束**: username, email, cf_handle 的唯一约束生效
- [ ] **默认值**: 新用户 elo 默认 1200, tokens 默认 0, pp 默认 0
- [ ] **索引存在**: 检查所有指定索引是否创建
- [ ] **UUID 自动生成**: 插入数据不指定 id 时自动生成 UUID
- [ ] **CASCADE 删除**: 删除用户时关联记录正确处理
- [ ] **迁移可回滚**: `alembic downgrade -1` 可正常回滚

#### 验收标准
1. Alembic 迁移成功执行，12 张表全部创建
2. 所有字段类型、约束、索引与设计一致
3. 外键关系正确
4. 默认值正确
5. 迁移可回滚

#### 技术备注
- 使用 SQLAlchemy 2.0 声明式风格
- 使用 AsyncSession 支持异步数据库操作
- Alembic 配置 async 模式

---

### Task 1.4: 基础 API 框架搭建
**状态**: 🟢 已完成 (2025-05-19)
**优先级**: P0
**依赖**: Task 1.3

#### 任务描述
搭建后端 FastAPI 基础框架，包括中间件、异常处理、配置管理、数据库连接和基础路由结构。

**需要创建的模块**:

1. **app/core/config.py** - 配置管理
   - 使用 pydantic-settings 的 BaseSettings
   - 从环境变量读取配置（数据库URL、JWT密钥、CF API URL等）
   - 支持 .env 文件

2. **app/core/database.py** - 数据库连接
   - SQLAlchemy async engine 和 sessionmaker
   - get_db 依赖注入函数
   - 数据库连接池配置

3. **app/core/security.py** - 安全工具
   - JWT token 生成和验证
   - 密码哈希（bcrypt）
   - get_current_user 依赖

4. **app/middleware/** - 中间件
   - CORS 中间件配置
   - 请求日志中间件
   - 速率限制中间件基础

5. **app/core/exceptions.py** - 全局异常处理
   - 自定义异常类（AppException, NotFoundException, UnauthorizedException 等）
   - 全局异常处理器，统一错误响应格式

6. **app/api/v1/__init__.py** - API 路由注册
   - 创建 APIRouter 挂载各模块路由
   - 统一 API 前缀 /api/v1

7. **app/main.py** - 应用入口
   - FastAPI 实例创建
   - 中间件注册
   - 路由挂载
   - lifespan 事件处理（数据库连接初始化/关闭）

8. **统一响应格式**:
   ```python
   # 成功响应
   {"success": true, "data": {...}, "message": "..."}
   # 错误响应
   {"success": false, "error": {"code": "...", "message": "..."}, "detail": "..."}
   ```

#### 测试要点（防Workaround验证清单）
- [ ] **服务启动**: uvicorn 启动无错误
- [ ] **Swagger 可访问**: /docs 页面正常显示
- [ ] **CORS 配置**: 前端域名在允许列表中
- [ ] **异常处理**: 触发各种异常时返回统一格式
- [ ] **配置加载**: 环境变量正确读取到 Settings 对象
- [ ] **数据库连接**: get_db 能正常获取数据库会话
- [ ] **JWT 工具**: token 生成和验证正常工作
- [ ] **密码哈希**: bcrypt 哈希和验证正常工作
- [ ] **路由前缀**: 所有 API 路径以 /api/v1 开头
- [ ] **健康检查**: /api/v1/health 返回 200

#### 验收标准
1. FastAPI 应用正常启动
2. Swagger UI 可访问且显示所有已注册路由
3. 全局异常处理返回统一格式
4. CORS 配置允许前端域名
5. 健康检查端点正常

#### 技术备注
- 使用 async/await 全异步架构
- 使用 httpx 作为异步 HTTP 客户端（用于 CF API 调用）

---

## 阶段 2: 核心算法模块

### Task 2.1: Elo 计算引擎
**状态**: 🟢 已完成 (2025-05-19)
**优先级**: P0
**依赖**: Task 1.4

#### 任务描述
实现完整的 Elo 评级计算引擎，支持所有业务场景的 Elo 变动计算。

**需要创建的文件**:
- `app/services/elo_service.py` - Elo 计算核心逻辑

**功能要求**:

1. **标准 Elo 对战计算**（随机挑战场景）:
   ```
   Expected_A = 1 / (1 + 10^((Rating_B - Rating_A) / 400))
   New_Rating_A = Rating_A + K * (Actual_A - Expected_A)
   ```
   - K 值可配置（默认 32）
   - 胜利 Actual=1, 失败 Actual=0, 平局 Actual=0.5

2. **退出惩罚计算**:
   - 提交 0 次: Elo 不变
   - 提交 1-2 次: 随机 -5 到 -10
   - 提交 3 次以上: 正常失败处理

3. **提示惩罚 Elo 衰减**:
   - 一级提示: Elo 增益 * 0.75
   - 二级提示: Elo 增益 * 0.50
   - 三级提示: Elo 增益 * 0.25
   - 注意: 衰减只应用于增益（正值），失败惩罚不减少

4. **Elo 变动记录**:
   - 每次变动写入 elo_history 表
   - 包含变动原因和关联的会话 ID

5. **M-Elo 计算**（比赛 Elo）:
   - 虚拟组赛中使用，基于解题数和用时综合计算
   - 具体公式: 参考标准 Elo，但使用解题比例作为得分
   - 解题比例 = solved_problems / total_problems
   - 额外奖励: 用时少奖励更高（具体系数可配置）

6. **所有参数可配置**:
   - K 值、衰减系数、退出惩罚范围等通过 system_config 表读取
   - 提供默认值作为 fallback

#### 测试要点（防Workaround验证清单）
- [ ] **标准对战 - 同分**: 双方 1200 vs 1200，胜方应得约 16 分
- [ ] **标准对战 - 差距大**: 1200 vs 1800，低分胜应得更多（约 25+），高分胜应得很少（约 3-5）
- [ ] **退出 0 提交**: Elo 完全不变
- [ ] **退出 1 提交**: Elo 下降 5-10 之间
- [ ] **退出 2 提交**: Elo 下降 5-10 之间
- [ ] **退出 3+ 提交**: 按正常失败处理（非固定 -5~-10）
- [ ] **提示衰减 - 一级**: 增益 20 变为 15
- [ ] **提示衰减 - 二级**: 增益 20 变为 10
- [ ] **提示衰减 - 三级**: 增益 20 变为 5
- [ ] **提示衰减不减少失败惩罚**: 失败 -16 使用提示后仍为 -16
- [ ] **M-Elo 计算**: 正确使用解题比例和用时因素
- [ ] **配置读取**: 从 system_config 读取参数而非硬编码
- [ ] **历史记录**: 每次变动都正确写入 elo_history
- [ ] **并发安全**: 多次并发计算不会导致数据不一致

#### 验收标准
1. 标准 Elo 计算结果与数学公式精确匹配（误差 < 0.01）
2. 所有退出惩罚场景正确
3. 提示衰减只应用于增益
4. M-Elo 计算逻辑正确
5. 所有参数通过配置系统读取
6. 历史记录完整

#### 技术备注
- 所有计算使用精确浮点运算，存储时取整
- 提供单元测试覆盖所有计算场景
- 配置缓存避免每次计算都查询数据库

---

### Task 2.2: PP 计算引擎
**状态**: 🟢 已完成 (2025-05-19)
**优先级**: P0
**依赖**: Task 1.4

#### 任务描述
实现 PP (Performance Points) 计算引擎，包括单题基础 PP 计算和总 PP 聚合。

**需要创建的文件**:
- `app/services/pp_service.py` - PP 计算核心逻辑

**功能要求**:

1. **单题基础 PP 计算**:
   ```python
   def calculate_base_pp(problem_rating: int) -> float:
       if problem_rating < 800:
           return 0.0
       return math.sqrt((problem_rating - 800) / 100) * 10
   ```
   - rating < 800: 0 PP
   - rating = 800: 0 PP
   - rating = 1200: 20 PP
   - rating = 1500: 26.46 PP
   - rating = 2000: 34.64 PP
   - rating = 3500: 51.96 PP

2. **总 PP 聚合计算**:
   - 获取用户所有已解题目的最高 PP（同一题取最高 rating 版本）
   - 按基础 PP 降序排列
   - 取前 100 题
   - 第 n 题权重 0.95^(n-1)
   - 总 PP = SUM(P_i * 0.95^(i-1))
   - 结果保留 2 位小数

3. **PP 记录管理**:
   - 用户首次解决某题时创建 pp_record
   - 如果同一题后来以更高 rating 解决（如 rating 变化），更新记录
   - 提示使用不影响 PP 值（但需记录提示使用次数）
   - 总 PP 变动时更新 users.pp 字段

4. **PP 排名计算**:
   - 提供按 PP 排名的查询方法
   - 支持分页
   - 缓存排名结果（5 分钟刷新）

**验证点 - 预期结果**:
- 全部解 100 题 rating=1200 的题: Total PP = 20 * SUM(0.95^(i-1), i=1..100) = 20 * (1-0.95^100)/(1-0.95) = 20 * 19.87 = 397.40
- 全部解 100 题 rating=2000 的题: Total PP = 34.64 * 19.87 = 688.33
- 混合难度: 前 50 题 rating=2000, 后 50 题 rating=1200 = 34.64 * (1-0.95^50)/0.05 + 20 * 0.95^50 * (1-0.95^50)/0.05 = 626.38 + 7.21 = 633.59

#### 测试要点（防Workaround验证清单）
- [ ] **基础 PP - 边界值 800**: calculate_base_pp(800) == 0.0
- [ ] **基础 PP - 边界值 799**: calculate_base_pp(799) == 0.0
- [ ] **基础 PP - 标准值 1200**: calculate_base_pp(1200) 约等于 20.0
- [ ] **基础 PP - 高值 3500**: calculate_base_pp(3500) 约等于 51.96
- [ ] **总 PP - 单题**: 解 1 题 rating=2000 => 34.64
- [ ] **总 PP - 100题同难度**: 与上述公式计算结果匹配
- [ ] **总 PP - 不足100题**: 取实际题目数计算
- [ ] **总 PP - 超过100题**: 只取前 100 题
- [ ] **总 PP - 排序验证**: 确认按 PP 降序排列后加权
- [ ] **重复题目**: 同一题多次解决不重复计数
- [ ] **题目更新**: 同一题以更高 rating 解决时 PP 更新
- [ ] **提示不影响 PP**: 使用提示后 PP 值不变
- [ ] **用户 PP 字段同步**: users.pp 与实际计算一致
- [ ] **排名查询**: 返回正确的排名顺序

#### 验收标准
1. 基础 PP 计算与公式精确匹配
2. 总 PP 计算与手动计算结果一致（误差 < 0.01）
3. 重复题目处理正确
4. 提示使用不影响 PP
5. 排名功能正常

#### 技术备注
- 使用 PostgreSQL 的窗口函数优化排名查询
- PP 聚合计算可能较耗时，考虑缓存策略

---

### Task 2.3: 配置管理系统
**状态**: 🟢 已完成 (2025-05-19)
**优先级**: P0
**依赖**: Task 1.4

#### 任务描述
实现基于数据库的系统配置管理，支持管理员热更新所有可配置参数。

**需要创建的文件**:
- `app/services/config_service.py` - 配置管理服务
- `app/core/default_config.py` - 默认配置值定义

**功能要求**:

1. **配置项定义** (default_config.py):
   ```python
   DEFAULT_CONFIG = {
       "elo": {
           "initial_elo": 1200,
           "k_factor": 32,
           "divisor": 400,
           "quit_penalty_min": 5,
           "quit_penalty_max": 10,
           "hint_decay": [0.75, 0.50, 0.25],
       },
       "pp": {
           "base_formula_coefficient": 10,
           "base_formula_offset": 800,
           "decay_factor": 0.95,
           "max_problems": 100,
       },
       "challenge": {
           "weight_within_100": 0.50,
           "weight_challenge_zone": 0.25,  # +100~+300
           "weight_consolidation_zone": 0.15,  # -100~-300
           "weight_surprise_zone": 0.10,  # +/-300+
       },
       "economy": {
           "daily_token_cap": 120,
           "time_bonus_threshold_minutes": 20,
           "difficulty_tiers": {
               "gray": {"min": 800, "max": 1099, "ac_reward": 10, "attempt_reward": 2},
               "green": {"min": 1100, "max": 1399, "ac_reward": 20, "attempt_reward": 3},
               "blue": {"min": 1400, "max": 1699, "ac_reward": 30, "attempt_reward": 4},
               "purple": {"min": 1700, "max": 1999, "ac_reward": 40, "attempt_reward": 5},
               "yellow_red": {"min": 2000, "max": 9999, "ac_reward": 50, "attempt_reward": 6},
           },
           "hint_pricing": {
               "gray": [3, 10, 20],
               "green": [5, 15, 30],
               "blue": [8, 20, 40],
               "purple": [10, 25, 50],
               "yellow_red": [15, 30, 60],
           },
       },
       "contest": {
           "tiers": {
               "beginner": {"max_elo": 1400, "duration_minutes": 90, "problems": 4, "rating_range": [800, 1400]},
               "advanced": {"min_elo": 1400, "max_elo": 1800, "duration_minutes": 120, "problems": 5, "rating_range": [1200, 2000]},
               "master": {"min_elo": 1800, "duration_minutes": 150, "problems": 6, "rating_range": [1600, 2600]},
           }
       },
       "cf_api": {
           "base_url": "https://codeforces.com/api",
           "request_interval_seconds": 2,
           "max_retries": 3,
           "cache_ttl_seconds": 300,
       }
   }
   ```

2. **配置服务** (config_service.py):
   - `get_config(key: str) -> Any`: 获取配置项，优先从数据库读取，fallback 到默认值
   - `set_config(key: str, value: Any, admin_id: UUID)`: 更新配置项
   - `get_all_config() -> dict`: 获取所有配置
   - `reset_config(key: str, admin_id: UUID)`: 重置为默认值
   - `initialize_defaults()`: 首次启动时将默认配置写入数据库

3. **配置缓存**:
   - 使用内存缓存，TTL 60 秒
   - 配置更新时立即清除缓存
   - 避免每次请求都查询数据库

4. **配置验证**:
   - 更新配置时验证值的合理性（范围检查、类型检查）
   - 防止无效配置导致系统异常

#### 测试要点（防Workaround验证清单）
- [ ] **默认配置加载**: 首次启动时数据库写入所有默认配置
- [ ] **配置读取**: get_config 返回正确值
- [ ] **配置更新**: set_config 后 get_config 返回新值
- [ ] **配置持久化**: 重启服务后配置仍然保留更新值
- [ ] **缓存生效**: 连续读取不走数据库（验证查询次数）
- [ ] **缓存失效**: 更新后立即读取到新值
- [ ] **Fallback**: 数据库无配置时返回默认值
- [ ] **重置**: reset_config 后返回默认值
- [ ] **验证 - 无效值**: 设置超出范围的值应被拒绝
- [ ] **验证 - 类型错误**: 设置错误类型应被拒绝
- [ ] **嵌套 key**: get_config("elo.k_factor") 正确返回嵌套值
- [ ] **审计记录**: 更新配置时记录 updated_by 和 updated_at

#### 验收标准
1. 默认配置完整加载到数据库
2. 配置 CRUD 操作正常
3. 缓存机制正确（命中/失效）
4. 配置验证防止无效值
5. 嵌套 key 支持正常

#### 技术备注
- 配置 key 使用点号分隔的路径（如 "elo.k_factor"）
- JSONB 字段存储灵活结构
- 缓存使用简单的 dict + TTL，无需 Redis

---

## 阶段 3: 用户系统

### Task 3.1: 用户注册与认证
**状态**: 🟢 已完成 (2025-05-19)
**优先级**: P0
**依赖**: Task 1.4

#### 任务描述
实现完整的用户注册、登录、JWT 认证系统。

**需要创建的文件**:
- `app/api/v1/auth.py` - 认证路由
- `app/schemas/auth.py` - 请求/响应 Schema
- `app/services/auth_service.py` - 认证业务逻辑

**API 端点**:

1. **POST /api/v1/auth/register**
   - 请求: `{ username, email, password }`
   - 验证: username 3-50字符, email 格式, password 8+字符含大小写和数字
   - 返回: 用户信息 + JWT token

2. **POST /api/v1/auth/login**
   - 请求: `{ email, password }`
   - 返回: JWT token (access_token + refresh_token)
   - access_token 过期时间 24h, refresh_token 过期时间 7d

3. **POST /api/v1/auth/refresh**
   - 请求: `{ refresh_token }`
   - 返回: 新的 access_token

4. **GET /api/v1/auth/me**
   - 需要 JWT 认证
   - 返回: 当前用户完整信息

5. **PUT /api/v1/auth/profile**
   - 需要 JWT 认证
   - 请求: `{ username?, email? }`
   - 返回: 更新后的用户信息

**功能要求**:
- 密码使用 bcrypt 哈希，salt rounds >= 12
- JWT 使用 RS256 或 HS256 算法
- refresh_token 存储在数据库中（支持撤销）
- 登录时记录 last_login_at
- 注册时自动创建默认配置

#### 测试要点（防Workaround验证清单）
- [ ] **注册 - 正常**: 合法输入成功注册
- [ ] **注册 - 重复用户名**: 返回 409 错误
- [ ] **注册 - 重复邮箱**: 返回 409 错误
- [ ] **注册 - 弱密码**: 返回验证错误
- [ ] **注册 - 短用户名**: 返回验证错误
- [ ] **注册 - 默认值**: elo=1200, pp=0, tokens=0
- [ ] **登录 - 正确凭证**: 返回 token
- [ ] **登录 - 错误密码**: 返回 401
- [ ] **登录 - 不存在用户**: 返回 401（不透露用户是否存在）
- [ ] **Token 刷新**: refresh_token 能获取新 access_token
- [ ] **过期 Token**: 过期 token 被拒绝
- [ ] **获取个人信息**: /me 返回完整用户数据
- [ ] **更新用户名**: 成功更新
- [ ] **密码哈希**: 数据库中不存储明文密码

#### 验收标准
1. 注册、登录、token 刷新流程完整
2. 输入验证严格
3. JWT 认证中间件正常工作
4. 密码安全存储

---

### Task 3.2: CF Handle 绑定与验证
**状态**: [ ] 未开始
**优先级**: P1
**依赖**: Task 3.1

#### 任务描述
实现 Codeforces Handle 绑定功能，通过 CF API 验证 Handle 的有效性。

**需要创建的文件**:
- `app/api/v1/cf_handle.py` - CF Handle 路由
- `app/services/cf_handle_service.py` - CF Handle 业务逻辑

**API 端点**:

1. **POST /api/v1/cf-handle/bind**
   - 请求: `{ cf_handle }`
   - 验证: 调用 CF API `user.info` 确认 handle 存在
   - 返回: CF 用户基本信息（rating, maxRating, avatar 等）

2. **POST /api/v1/cf-handle/verify**
   - 请求: `{ cf_handle, verification_code }`
   - 验证方式: 用户在 CF 个人 bio 中写入验证码，系统检查是否匹配
   - 返回: 验证结果

3. **GET /api/v1/cf-handle/info/{handle}**
   - 公开端点，查询 CF 用户信息
   - 返回: rating, maxRating, avatar, rank 等

4. **DELETE /api/v1/cf-handle/unbind**
   - 需要认证
   - 解绑当前用户的 CF Handle

**功能要求**:
- 绑定前检查 handle 是否已被其他用户绑定
- CF API 调用需要错误处理（网络超时、handle 不存在等）
- 验证码为 8 位随机字符串
- CF Handle 验证状态: unbound -> pending_verification -> verified

#### 测试要点（防Workaround验证清单）
- [ ] **绑定 - 正常 Handle**: 调用真实 CF API 验证存在
- [ ] **绑定 - 不存在 Handle**: 返回错误
- [ ] **绑定 - 重复绑定**: 同一 handle 不能绑定两个用户
- [ ] **绑定 - 已绑定用户**: 已绑定的用户可以更新 handle
- [ ] **验证 - 正确验证码**: bio 中包含验证码时验证通过
- [ ] **验证 - 错误验证码**: 验证失败
- [ ] **查询 - 公开信息**: 不登录也能查询 CF 用户信息
- [ ] **解绑**: 解绑后 cf_handle 和 cf_handle_verified 重置
- [ ] **API 超时处理**: CF API 超时时返回友好错误
- [ ] **CF API 限流处理**: 收到 429 时适当重试

#### 验收标准
1. CF Handle 绑定和验证流程完整
2. CF API 调用正确处理成功和失败情况
3. 验证码机制安全可靠
4. 并发绑定同一 handle 时不会数据不一致

---

## 阶段 4: CF API 集成

### Task 4.1: CF API 客户端与防限流
**状态**: [ ] 未开始
**优先级**: P0
**依赖**: Task 1.4

#### 任务描述
实现 CF API 的 HTTP 客户端封装，包含请求限流、缓存、重试和错误处理机制。

**需要创建的文件**:
- `app/services/cf_api_service.py` - CF API 客户端
- `app/utils/rate_limiter.py` - 限流器

**功能要求**:

1. **CF API 方法封装**:
   - `get_user_info(handles: list[str])` - 批量获取用户信息
   - `get_user_status(handle: str, count: int)` - 获取用户提交记录
   - `get_problemset_problems(tags: list[str])` - 按标签获取题目
   - `get_contest_standings(contest_id: int)` - 获取比赛排名
   - `get_user_rating(handle: str)` - 获取用户 rating 变化

2. **防限流机制**:
   - 请求间隔最小 2 秒（可配置）
   - 使用令牌桶限流器
   - 收到 429 响应时指数退避重试
   - 最大重试 3 次（可配置）
   - 请求间隔使用 asyncio.sleep 非阻塞

3. **缓存策略**:
   - 使用内存缓存（TTL 5 分钟，可配置）
   - 题目列表缓存 TTL 较长（30 分钟）
   - 用户提交记录缓存 TTL 较短（1 分钟）
   - 缓存 key 包含完整请求参数

4. **错误处理**:
   - 网络超时: 30 秒超时，返回友好错误
   - CF API 返回 "FAILED" 或错误: 解析错误信息
   - Handle 不存在: 返回明确的错误类型
   - 限流: 自动重试

#### 测试要点（防Workaround验证清单）
- [ ] **用户信息获取**: 调用 get_user_info 返回正确数据
- [ ] **提交记录获取**: 调用 get_user_status 返回提交列表
- [ ] **题目列表获取**: 调用 get_problemset_problems 返回题目
- [ ] **限流 - 间隔**: 连续两次请求间隔 >= 2 秒
- [ ] **限流 - 令牌桶**: 短时间多次请求不超出限制
- [ ] **重试 - 429**: 收到限流响应后自动重试
- [ ] **重试 - 超时**: 超时后重试
- [ ] **重试 - 最大次数**: 超过最大重试次数后放弃
- [ ] **缓存命中**: 相同请求第二次走缓存
- [ ] **缓存过期**: TTL 过期后重新请求
- [ ] **错误处理 - 不存在 handle**: 返回明确错误
- [ ] **错误处理 - 网络故障**: 返回友好错误

#### 验收标准
1. 所有 CF API 方法正确封装
2. 限流机制有效
3. 缓存减少不必要的 API 调用
4. 错误处理完善

#### 技术备注
- CF API 文档: https://codeforces.com/apiHelp
- 使用 httpx.AsyncClient 作为 HTTP 客户端
- 限流器使用 asyncio.Lock 保证线程安全

---

## 阶段 5: 核心玩法 A - 随机挑战

### Task 5.1: 随机挑战匹配与出题
**状态**: [ ] 未开始
**优先级**: P0
**依赖**: Task 2.1, Task 4.1

#### 任务描述
实现随机挑战的完整流程：匹配对手、选择题目、开始挑战。

**需要创建的文件**:
- `app/api/v1/challenge.py` - 挑战路由
- `app/schemas/challenge.py` - Schema
- `app/services/challenge_service.py` - 挑战业务逻辑
- `app/services/match_service.py` - 匹配服务

**API 端点**:

1. **POST /api/v1/challenge/queue** - 加入匹配队列
2. **DELETE /api/v1/challenge/queue** - 离开匹配队列
3. **GET /api/v1/challenge/status** - 查询匹配状态
4. **POST /api/v1/challenge/start** - 确认开始（匹配成功后）
5. **GET /api/v1/challenge/{id}** - 获取挑战详情
6. **POST /api/v1/challenge/{id}/submit** - 提交结果
7. **POST /api/v1/challenge/{id}/quit** - 退出挑战

**匹配算法 - 概率加权**:
1. 从匹配队列中收集所有等待玩家
2. 对每个候选对手，按 Elo 差距分配权重:
   - 差距 <= 100: 权重 0.50
   - 差距 100~300（挑战区）: 权重 0.25
   - 差距 100~300（巩固区）: 权重 0.15
   - 差距 > 300: 权重 0.10
3. 按权重随机选择一个对手
4. 根据两人 Elo 平均值，从 CF API 获取合适难度的题目
5. 题目难度 = 双方 Elo 平均值 +/- 随机偏移（偏移范围可配置）

**挑战流程**:
1. 用户加入队列 -> 等待匹配
2. 匹配成功 -> 双方收到通知（WebSocket 或轮询）
3. 双方确认 -> 题目揭示
4. 双方各自在 CF 上提交
5. 系统通过 CF API 轮询检测提交结果
6. 先解决者获胜，或超时判定

#### 测试要点（防Workaround验证清单）
- [ ] **匹配 - 同分匹配**: 两个 1200 Elo 的玩家能匹配到一起
- [ ] **匹配 - 概率分布**: 100 次匹配中，+/-100 内的匹配占比约 50%
- [ ] **匹配 - 无对手**: 队列无其他人时保持等待
- [ ] **匹配 - 多人队列**: 多人等待时正确加权选择
- [ ] **出题 - 难度合适**: 题目难度在双方 Elo 平均值附近
- [ ] **出题 - 题目未重复**: 不出双方最近解决过的题
- [ ] **提交结果检测**: CF API 检测到 AC 时正确更新状态
- [ ] **退出 - 0 提交**: Elo 不变
- [ ] **退出 - 1 提交**: Elo 降 5-10
- [ ] **退出 - 3+ 提交**: 正常失败处理
- [ ] **Elo 更新**: 挑战结束后双方 Elo 正确更新
- [ ] **PP 更新**: 解决题目后 PP 正确更新
- [ ] **代币发放**: 正确发放挑战代币
- [ ] **离开队列**: 成功离开后不再被匹配
- [ ] **挑战历史**: 完整记录挑战过程

#### 验收标准
1. 匹配算法按概率权重正确工作
2. 出题难度合适
3. 挑战全流程完整（匹配->出题->提交->结算）
4. Elo/PP/代币正确更新
5. 退出惩罚正确执行

---

## 阶段 6: 核心玩法 B - 专题训练

### Task 6.1: 专题训练系统
**状态**: [ ] 未开始
**优先级**: P1
**依赖**: Task 2.1, Task 2.2, Task 4.1

#### 任务描述
实现专题训练系统，包括专题分类、题目展示、连击奖励和星级评价。

**需要创建的文件**:
- `app/api/v1/training.py` - 训练路由
- `app/schemas/training.py` - Schema
- `app/services/training_service.py` - 训练业务逻辑

**API 端点**:

1. **GET /api/v1/training/topics** - 获取所有专题列表
2. **GET /api/v1/training/topics/{id}** - 获取专题详情（含题目列表）
3. **POST /api/v1/training/start** - 开始训练会话
   - 请求: `{ topic_id }`
4. **GET /api/v1/training/session/{id}** - 获取训练会话状态
5. **POST /api/v1/training/session/{id}/submit** - 提交某题完成
   - 请求: `{ problem_id, solved, attempts, time_spent }`
6. **POST /api/v1/training/session/{id}/abandon** - 放弃训练
7. **GET /api/v1/training/progress** - 获取用户在所有专题的进度
8. **GET /api/v1/training/progress/{topic_id}** - 获取某专题详细进度

**功能要求**:

1. **专题分类**:
   - 预定义专题（对应 CF tags）: dp, greedy, math, graphs, strings, data_structures, binary_search, sorting, constructive, number_theory, trees, geometry 等
   - 每个专题包含该 tag 下的所有题目（从 CF API 获取）
   - 题目按难度排序展示

2. **自由选择**:
   - 用户可在专题内自由选择任意题目
   - 不需要按顺序完成

3. **连击奖励**:
   - 用户连续从低难度到高难度完成题目时触发连击
   - 连击条件: 下一题 rating > 上一题 rating
   - 连击奖励: 连击数 * 5 代币（上限 50 代币/次训练）
   - 连击中断条件: 跳过、放弃、或下一题 rating 不高于上一题

4. **星级评价**:
   - 0 星: 0% 完成
   - 1 星: > 0% 且 <= 20%
   - 2 星: > 20% 且 <= 40%
   - 3 星: > 40% 且 <= 60%
   - 4 星: > 60% 且 <= 80%
   - 5 星: > 80%

5. **进度追踪**:
   - 记录每道题的解决状态、尝试次数、用时
   - 专题完成率 = 已解决 / 总题目数
   - 跨会话保留进度

#### 测试要点（防Workaround验证清单）
- [ ] **专题列表**: 返回所有预定义专题
- [ ] **题目获取**: 专题下的题目从 CF API 正确获取
- [ ] **自由选择**: 可以选择专题内任意题目
- [ ] **连击 - 触发**: 连续完成递增难度的题目触发连击
- [ ] **连击 - 奖励**: 连击代币 = 连击数 * 5
- [ ] **连击 - 中断**: 选择低难度题目后连击中断
- [ ] **连击 - 上限**: 单次训练连击奖励不超过 50
- [ ] **星级 - 0 星**: 完成率 0%
- [ ] **星级 - 5 星**: 完成率 > 80%
- [ ] **星级 - 边界**: 完成率恰好 20% 时为 1 星（不是 2 星）
- [ ] **进度 - 跨会话**: 新会话能看到之前已解决的题目
- [ ] **进度 - 记录**: 每道题的 attempts 和 time_spent 正确记录
- [ ] **PP 更新**: 解决题目后 PP 正确计算
- [ ] **Elo 更新**: 训练解决题目后 Elo 小幅增加（可配置）
- [ ] **代币发放**: AC 奖励和尝试奖励正确发放

#### 验收标准
1. 专题和题目正确展示
2. 自由选择和连击机制正确
3. 星级评价准确
4. 进度跨会话保留
5. 奖励（代币、PP、Elo）正确发放

---

## 阶段 7: 核心玩法 C - 虚拟组赛

### Task 7.1: 虚拟组赛系统
**状态**: [ ] 未开始
**优先级**: P1
**依赖**: Task 2.1, Task 4.1

#### 任务描述
实现虚拟组赛系统，包括分级赛制、计时、结算。

**需要创建的文件**:
- `app/api/v1/contest.py` - 比赛路由
- `app/schemas/contest.py` - Schema
- `app/services/contest_service.py` - 比赛业务逻辑

**API 端点**:

1. **GET /api/v1/contest/tiers** - 获取可参加的赛制（根据用户 Elo）
2. **POST /api/v1/contest/start** - 开始比赛
   - 请求: `{ tier }` (beginner/advanced/master)
3. **GET /api/v1/contest/{id}** - 获取比赛状态
4. **POST /api/v1/contest/{id}/submit** - 提交题目结果
   - 请求: `{ problem_id, solved, attempts, time_spent }`
5. **POST /api/v1/contest/{id}/end** - 主动结束比赛
6. **GET /api/v1/contest/history** - 获取比赛历史
7. **GET /api/v1/contest/{id}/result** - 获取比赛结果详情

**赛制配置**:

| 赛制 | Elo 范围 | 时长 | 题目数 | 题目难度 |
|------|----------|------|--------|----------|
| 新手赛 | < 1400 | 90min | 4 | 800-1400 |
| 进阶赛 | 1400-1800 | 120min | 5 | 1200-2000 |
| 大师赛 | > 1800 | 150min | 6 | 1600-2600 |

**功能要求**:

1. **赛制准入**:
   - 检查用户 Elo 是否符合赛制要求
   - 可以参加低于自己级别的赛制（如 1600 参加新手赛），但不能参加高于级别的

2. **题目选择**:
   - 从 CF API 获取指定难度范围的题目
   - 题目难度在范围内均匀分布（如新手赛: 800, 1000, 1200, 1400 各一题）
   - 避免用户已解决的题目

3. **计时系统**:
   - 开始时间精确记录
   - 每次获取状态时计算剩余时间
   - 超时自动结束

4. **结算系统**:
   - 解题数作为主要得分
   - 用时作为次要排名因素
   - Elo 变动使用 M-Elo 公式（Task 2.1 中定义）
   - 退出惩罚:
     - 0 提交: Elo 不变
     - 1-2 提交: -5~-10
     - 3+ 提交: 按解题比例计算

#### 测试要点（防Workaround验证清单）
- [ ] **赛制准入 - 新手**: Elo 1300 可参加新手赛
- [ ] **赛制准入 - 降级**: Elo 1600 可参加新手赛
- [ ] **赛制准入 - 越级**: Elo 1300 不能参加进阶赛
- [ ] **题目 - 难度分布**: 新手赛 4 题难度大致均匀分布在 800-1400
- [ ] **题目 - 不重复**: 不出现已解决的题目
- [ ] **计时 - 精确**: 剩余时间精确到秒
- [ ] **计时 - 超时**: 超时自动结束比赛
- [ ] **结算 - 全部解决**: Elo 大幅增加
- [ ] **结算 - 部分解决**: Elo 按比例变化
- [ ] **结算 - 0 解题**: Elo 下降
- [ ] **退出 - 0 提交**: Elo 不变
- [ ] **退出 - 1 提交**: Elo 降 5-10
- [ ] **退出 - 3+ 提交**: 正常失败处理
- [ ] **PP 更新**: 比赛中解决的题目 PP 正确计算
- [ ] **代币发放**: 每道 AC 的题目代币正确发放
- [ ] **比赛历史**: 可查看所有历史比赛和结果
- [ ] **进行中比赛**: 同时只能有一场进行中的比赛

#### 验收标准
1. 三个赛制正确配置
2. 准入控制正确
3. 计时准确
4. 结算和 Elo 变动正确
5. 奖励正确发放

---

## 阶段 8: 经济与提示系统

### Task 8.1: 代币经济系统
**状态**: [ ] 未开始
**优先级**: P1
**依赖**: Task 5.1, Task 6.1, Task 7.1

#### 任务描述
实现完整的代币经济系统，包括产出、消费、每日上限和交易记录。

**需要创建的文件**:
- `app/services/economy_service.py` - 代币经济服务
- `app/api/v1/economy.py` - 代币 API 路由

**API 端点**:

1. **GET /api/v1/economy/balance** - 获取当前代币余额
2. **GET /api/v1/economy/transactions** - 获取交易记录（分页）
3. **GET /api/v1/economy/daily-status** - 获取今日代币获取状态

**代币产出规则**:

| 难度 | AC 奖励 | 尝试奖励 | 时间加成 |
|------|---------|----------|----------|
| 灰(800-1099) | 10 | 2 | >20min 额外 +5 |
| 绿(1100-1399) | 20 | 3 | >20min 额外 +10 |
| 蓝(1400-1699) | 30 | 4 | >20min 额外 +15 |
| 紫(1700-1999) | 40 | 5 | >20min 额外 +20 |
| 黄/红(2000+) | 50 | 6 | >20min 额外 +25 |

- **尝试奖励**: 未 AC 但有提交尝试时获得
- **时间加成**: 用时超过 20 分钟并最终 AC 时额外获得
- **每日上限**: 120 代币
- **每日重置**: UTC 0:00 重置 daily_tokens_earned

**代币消费场景**:
- 购买提示（按提示定价表）
- 后续可扩展其他消费场景

#### 测试要点（防Workaround验证清单）
- [ ] **AC 奖励 - 各难度**: 灰 10, 绿 20, 蓝 30, 紫 40, 黄/红 50
- [ ] **尝试奖励 - 各难度**: 灰 2, 绿 3, 蓝 4, 紫 5, 黄/红 6
- [ ] **时间加成 - >20min**: 各难度正确加成
- [ ] **时间加成 - <=20min**: 不获得加成
- [ ] **每日上限**: 达到 120 后不再获得
- [ ] **每日重置**: UTC 0:00 后重置
- [ ] **余额更新**: 每次交易后 balance 正确
- [ ] **交易记录**: 每笔交易都有完整记录
- [ ] **余额不足**: 消费超过余额时拒绝
- [ ] **并发安全**: 同时多笔交易不会超限
- [ ] **连击奖励**: 训练连击代币正确发放
- [ ] **负数防护**: 余额不允许为负数

#### 验收标准
1. 所有代币产出规则正确实现
2. 每日上限和重置机制正常
3. 交易记录完整准确
4. 并发安全

---

### Task 8.2: 提示系统
**状态**: [ ] 未开始
**优先级**: P1
**依赖**: Task 8.1

#### 任务描述
实现题目提示系统，包括提示内容管理、分级解锁、定价和 Elo 衰减。

**需要创建的文件**:
- `app/api/v1/hints.py` - 提示路由
- `app/services/hint_service.py` - 提示业务逻辑
- `app/services/hint_content_service.py` - 提示内容生成/管理

**API 端点**:

1. **GET /api/v1/hints/{problem_id}/status** - 获取题目提示状态
   - 返回: 已解锁提示级别、各级价格、Elo 衰减预览
2. **POST /api/v1/hints/{problem_id}/unlock** - 解锁下一级提示
   - 请求: `{ level }` (1/2/3)
   - 验证: 不可跳级，必须按 1->2->3 顺序解锁
3. **GET /api/v1/hints/{problem_id}/content/{level}** - 获取提示内容
   - 验证: 只有已解锁的级别才能查看
4. **GET /api/v1/hints/{problem_id}/history** - 获取该题提示使用历史

**提示定价**:

| 难度 | 一级 | 二级 | 三级 | 累计 |
|------|------|------|------|------|
| 灰 | 3 | 10 | 20 | 33 |
| 绿 | 5 | 15 | 30 | 50 |
| 蓝 | 8 | 20 | 40 | 68 |
| 紫 | 10 | 25 | 50 | 85 |
| 黄/红 | 15 | 30 | 60 | 105 |

**提示内容策略**:
- 一级提示: 思路方向/算法类别（如"考虑使用动态规划"）
- 二级提示: 具体方法/关键状态定义
- 三级提示: 接近完整的解题思路

**Elo 衰减**（应用于当次挑战/训练/比赛的 Elo 增益）:
- 一级提示: Elo 增益 * 0.75
- 二级提示: Elo 增益 * 0.50
- 三级提示: Elo 增益 * 0.25
- PP 不受影响

#### 测试要点（防Workaround验证清单）
- [ ] **解锁 - 按顺序**: 一级 -> 二级 -> 三级
- [ ] **解锁 - 跳级失败**: 直接解锁二级应被拒绝
- [ ] **解锁 - 重复**: 重复解锁同一级应被拒绝（不扣费）
- [ ] **定价 - 各难度**: 灰/绿/蓝/紫/黄红价格正确
- [ ] **扣费**: 解锁后代币余额正确减少
- [ ] **余额不足**: 代币不足时拒绝解锁
- [ ] **Elo 衰减 - 一级**: 增益 * 0.75
- [ ] **Elo 衰减 - 二级**: 增益 * 0.50
- [ ] **Elo 衰减 - 三级**: 增益 * 0.25
- [ ] **Elo 衰减 - 不影响 PP**: PP 计算不因使用提示而改变
- [ ] **Elo 衰减 - 不减少失败惩罚**: 负 Elo 变动不因提示而减少
- [ ] **提示内容**: 正确返回对应级别的提示
- [ ] **未解锁拒绝**: 未解锁的提示内容不可查看
- [ ] **交易记录**: 提示购买记入 token_transactions
- [ ] **购买记录**: hint_purchases 表正确记录

#### 验收标准
1. 提示分级解锁机制正确
2. 定价准确
3. Elo 衰减只影响增益
4. PP 不受影响
5. 代币扣除正确

---

## 阶段 9: 前端 UI 基础框架与组件库

### Task 9.1: 前端基础框架与路由
**状态**: [ ] 未开始
**优先级**: P1
**依赖**: Task 1.1

#### 任务描述
搭建前端 React 应用基础框架，包括路由、布局、全局状态和通用组件。

**需要创建/修改的文件**:
- `frontend/src/App.tsx` - 路由配置
- `frontend/src/layouts/` - 布局组件
- `frontend/src/stores/auth.ts` - 认证状态管理
- `frontend/src/services/api.ts` - API 客户端封装
- `frontend/src/components/ui/` - shadcn/ui 组件

**页面路由**:
```
/                    - 首页/登录
/register           - 注册
/dashboard          - 仪表盘
/challenge          - 随机挑战
/training           - 专题训练
/training/:id       - 专题详情
/contest            - 虚拟组赛
/contest/:id        - 比赛进行中
/profile            - 个人资料
/profile/cf-bind    - CF Handle 绑定
/leaderboard        - 排行榜
/admin              - 管理后台
/admin/config       - 配置管理
```

**布局组件**:
- AuthLayout: 登录/注册页布局
- MainLayout: 主布局（侧边栏 + 顶部导航 + 内容区）
- AdminLayout: 管理后台布局

**通用组件**:
- LoadingSpinner: 加载状态
- ErrorBoundary: 错误边界
- ProtectedRoute: 路由守卫（需登录）
- AdminRoute: 管理员路由守卫

**API 客户端**:
- axios 实例，自动附加 JWT token
- 401 自动跳转登录
- 统一错误处理

#### 测试要点（防Workaround验证清单）
- [ ] **路由 - 所有页面**: 每个路由都能正确渲染对应页面
- [ ] **路由守卫**: 未登录访问 /dashboard 跳转到 /
- [ ] **管理员守卫**: 非管理员访问 /admin 被拒绝
- [ ] **布局**: 各布局正确渲染
- [ ] **API 客户端**: JWT token 自动附加
- [ ] **401 处理**: token 过期自动跳转登录
- [ ] **错误边界**: 组件崩溃时显示错误页面而非白屏
- [ ] **响应式**: 基础响应式布局正常

#### 验收标准
1. 所有路由可访问
2. 路由守卫正常工作
3. 布局组件正确渲染
4. API 客户端正确封装

---

### Task 9.2: 核心页面实现
**状态**: [ ] 未开始
**优先级**: P1
**依赖**: Task 9.1

#### 任务描述
实现所有核心页面的完整 UI，包括登录注册、仪表盘、挑战、训练、比赛、个人资料等。

**需要创建的文件（按页面）**:

1. **登录/注册页面** (`frontend/src/pages/auth/`)
   - 登录表单: 邮箱 + 密码
   - 注册表单: 用户名 + 邮箱 + 密码 + 确认密码
   - 表单验证和错误提示

2. **仪表盘** (`frontend/src/pages/dashboard/`)
   - 用户信息卡片（Elo, PP, 代币）
   - 最近活动
   - 快捷入口（挑战、训练、比赛）
   - Elo 趋势小图

3. **随机挑战页面** (`frontend/src/pages/challenge/`)
   - 匹配等待动画
   - 挑战进行中界面（题目展示、计时器、提交状态）
   - 结果展示

4. **专题训练页面** (`frontend/src/pages/training/`)
   - 专题列表（网格布局，每个专题卡片显示星级、进度）
   - 专题详情（题目列表，难度标记，完成状态）
   - 训练会话界面

5. **虚拟组赛页面** (`frontend/src/pages/contest/`)
   - 赛制选择卡片
   - 比赛进行中界面（题目列表、计时器、解题进度）
   - 结果展示

6. **个人资料页面** (`frontend/src/pages/profile/`)
   - 基本信息展示和编辑
   - CF Handle 绑定
   - Elo 历史
   - PP 排名

7. **排行榜页面** (`frontend/src/pages/leaderboard/`)
   - Elo 排行
   - PP 排行
   - 搜索用户

**UI 规范**:
- 使用 shadcn/ui 组件库
- Tailwind CSS 自定义主题（暗色主题为主，配合游戏化风格）
- 所有颜色使用 CSS 变量，便于主题切换
- 所有交互有 loading 状态
- 错误状态有友好提示

#### 测试要点（防Workaround验证清单）
- [ ] **登录表单**: 输入验证、提交、错误提示
- [ ] **注册表单**: 完整验证、提交成功跳转
- [ ] **仪表盘**: 所有数据正确展示
- [ ] **挑战流程**: 完整的匹配->进行->结果 UI
- [ ] **训练流程**: 专题列表->详情->训练完整流程
- [ ] **比赛流程**: 选赛制->进行->结果完整流程
- [ ] **个人资料**: 信息展示和编辑
- [ ] **CF 绑定**: 绑定流程完整
- [ ] **排行榜**: 排序正确、分页正常
- [ ] **暗色主题**: 所有页面暗色主题正常
- [ ] **响应式**: 移动端基本可用
- [ ] **Loading 状态**: 所有异步操作有加载指示
- [ ] **错误提示**: API 错误有友好提示

#### 验收标准
1. 所有页面完整实现
2. 所有表单验证正确
3. 所有流程端到端可操作
4. 暗色主题统一
5. 响应式基本适配

---

## 阶段 10: 数据可视化

### Task 10.1: 数据可视化组件
**状态**: [ ] 未开始
**优先级**: P2
**依赖**: Task 9.2

#### 任务描述
实现核心数据可视化组件，包括雷达图、趋势图和统计面板。

**需要创建的文件**:
- `frontend/src/components/charts/EloChart.tsx` - Elo 趋势图
- `frontend/src/components/charts/RadarChart.tsx` - 能力雷达图
- `frontend/src/components/charts/PPChart.tsx` - PP 贡献图
- `frontend/src/components/charts/StatsPanel.tsx` - 统计面板
- `frontend/src/pages/dashboard/` - 集成到仪表盘

**可视化组件**:

1. **Elo 趋势图**:
   - X 轴: 时间
   - Y 轴: Elo 值
   - 显示 Elo 变化曲线
   - 标注关键事件（挑战、比赛等）
   - 支持时间范围选择（7天/30天/全部）

2. **能力雷达图**:
   - 维度: DP, Greedy, Math, Graph, String, DS 等（按专题分）
   - 值: 各专题的完成率或解题数
   - 与 Elo 同级用户的平均值对比
   - 使用 recharts 或 chart.js

3. **PP 贡献图**:
   - 显示前 20 题 PP 贡献的柱状图
   - 每根柱子标注题目难度和基础 PP
   - 颜色按难度等级区分

4. **统计面板**:
   - 总解题数
   - 各难度解题数分布
   - 挑战胜率
   - 比赛参与次数和平均排名
   - 代币获取/消费统计

#### 测试要点（防Workaround验证清单）
- [ ] **Elo 趋势图 - 数据正确**: 坐标点与 Elo 历史数据匹配
- [ ] **Elo 趋势图 - 时间范围**: 切换范围正确过滤数据
- [ ] **Elo 趋势图 - 事件标注**: 关键事件正确显示
- [ ] **雷达图 - 维度正确**: 各专题维度正确映射
- [ ] **雷达图 - 数据正确**: 数值与实际完成率匹配
- [ ] **雷达图 - 对比线**: 同级平均值正确展示
- [ ] **PP 贡献图 - 顺序**: 按 PP 降序排列
- [ ] **PP 贡献图 - 颜色**: 难度颜色区分正确
- [ ] **统计面板 - 解题数**: 数字与实际数据匹配
- [ ] **统计面板 - 分布**: 各难度分布正确
- [ ] **空数据处理**: 无数据时显示友好提示而非空白
- [ ] **响应式**: 图表在移动端可正常查看

#### 验收标准
1. 四种可视化组件正确渲染
2. 数据与后端一致
3. 交互（时间范围切换等）正常
4. 空数据处理友好

#### 技术备注
- 推荐使用 recharts（与 React 生态契合度高）
- 图表需要动态响应容器大小

---

## 阶段 11: 沉浸式动画与视觉反馈系统

### Task 11.1: 动画与视觉反馈
**状态**: [ ] 未开始
**优先级**: P2
**依赖**: Task 9.2

#### 任务描述
实现游戏化的视觉反馈系统，包括 Elo 变化动画、代币获取动画、连击效果等。

**需要创建的文件**:
- `frontend/src/components/animations/EloChange.tsx` - Elo 变化动画
- `frontend/src/components/animations/CoinAnimation.tsx` - 代币动画
- `frontend/src/components/animations/StreakEffect.tsx` - 连击效果
- `frontend/src/components/animations/LevelUpEffect.tsx` - 升级/段位变化效果
- `frontend/src/hooks/useAnimation.ts` - 动画 Hook

**动画效果**:

1. **Elo 变化动画**:
   - 数字滚动效果（+16, -8 等）
   - 上升为绿色，下降为红色
   - Elo 条/进度条动画
   - 段位变化时全屏特效

2. **代币获取动画**:
   - 代币图标从题目飞向余额
   - 数字跳动更新
   - 连续获取时累积动画

3. **连击效果**:
   - 连击数递增动画（x2, x3, x4...）
   - 屏幕边缘发光效果
   - 连击数越高效果越强烈

4. **题目难度颜色编码**:
   - 灰: #999999
   - 绿: #00AA00
   - 蓝: #6666FF
   - 紫: #CC00CC
   - 黄: #FFBB00
   - 红: #FF0000

5. **匹配等待动画**:
   - 脉冲动画
   - 匹配成功时的"READY"效果

6. **AC (Accepted) 庆祝效果**:
   - 彩纸/粒子效果
   - "Accepted!" 大字展示
   - 配合代币获取动画

#### 测试要点（防Workaround验证清单）
- [ ] **Elo 动画 - 上升**: 绿色数字滚动上升
- [ ] **Elo 动画 - 下降**: 红色数字滚动下降
- [ ] **Elo 动画 - 段位变化**: 触发全屏特效
- [ ] **代币动画**: 飞行效果和数字跳动
- [ ] **连击动画**: 连击数递增显示
- [ ] **难度颜色**: 各难度颜色正确
- [ ] **匹配等待**: 脉冲动画流畅
- [ ] **AC 庆祝**: 粒子效果触发
- [ ] **prefers-reduced-motion**: 尊重用户系统设置，减少动画
- [ ] **性能**: 动画不导致页面卡顿

#### 验收标准
1. 所有动画效果流畅
2. 视觉反馈及时准确
3. 尊重 prefers-reduced-motion
4. 不影响页面性能

#### 技术备注
- 使用 CSS 动画和 framer-motion
- 粒子效果可使用 canvas 或 css 粒子库
- 所有动画需要 prefers-reduced-motion 适配

---

## 阶段 12: 管理员后台与配置热更新

### Task 12.1: 管理员后台
**状态**: [ ] 未开始
**优先级**: P1
**依赖**: Task 2.3, Task 9.2

#### 任务描述
实现管理员后台页面，支持系统配置热更新和用户管理。

**需要创建的文件**:
- `frontend/src/pages/admin/ConfigPage.tsx` - 配置管理页面
- `frontend/src/pages/admin/UsersPage.tsx` - 用户管理页面
- `frontend/src/pages/admin/DashboardPage.tsx` - 管理员仪表盘
- `app/api/v1/admin.py` - 管理员 API 路由
- `app/services/admin_service.py` - 管理员业务逻辑

**API 端点**:

1. **GET /api/v1/admin/config** - 获取所有配置
2. **PUT /api/v1/admin/config/{key}** - 更新配置项
3. **POST /api/v1/admin/config/{key}/reset** - 重置配置为默认值
4. **GET /api/v1/admin/users** - 获取用户列表（分页、搜索）
5. **PUT /api/v1/admin/users/{id}/toggle-active** - 启用/禁用用户
6. **PUT /api/v1/admin/users/{id}/toggle-admin** - 设置/取消管理员
7. **GET /api/v1/admin/stats** - 系统统计信息

**配置管理页面功能**:
- 分类展示所有配置项（Elo、PP、挑战、经济、比赛、CF API）
- 每个配置项显示: 名称、当前值、默认值、描述
- 支持在线编辑和保存
- 保存后即时生效（清除后端缓存）
- 一键重置为默认值
- 修改历史记录

**用户管理页面功能**:
- 用户列表（分页、搜索）
- 查看用户详情
- 启用/禁用用户
- 设置管理员权限

**管理员仪表盘**:
- 总用户数、活跃用户数
- 挑战/训练/比赛统计
- 系统运行状态

#### 测试要点（防Workaround验证清单）
- [ ] **配置读取**: 页面正确展示所有配置项
- [ ] **配置更新**: 修改后保存成功，返回新值
- [ ] **配置即时生效**: 修改 Elo K 值后，新挑战使用新值
- [ ] **配置重置**: 重置后返回默认值
- [ ] **配置验证**: 无效值被前端和后端同时拒绝
- [ ] **用户列表**: 分页、搜索正常
- [ ] **用户禁用**: 禁用用户无法登录
- [ ] **管理员设置**: 设置管理员后可访问后台
- [ ] **权限控制**: 非管理员无法访问管理 API
- [ ] **系统统计**: 数据准确

#### 验收标准
1. 配置 CRUD 完整
2. 配置热更新即时生效
3. 用户管理功能完整
4. 权限控制严格

---

## 阶段 13: 集成测试与部署

### Task 13.1: 端到端集成测试
**状态**: [ ] 未开始
**优先级**: P0
**依赖**: 所有前序任务

#### 任务描述
编写端到端集成测试，覆盖所有核心业务流程。

**需要创建的文件**:
- `backend/tests/integration/test_auth_flow.py`
- `backend/tests/integration/test_challenge_flow.py`
- `backend/tests/integration/test_training_flow.py`
- `backend/tests/integration/test_contest_flow.py`
- `backend/tests/integration/test_economy_flow.py`
- `backend/tests/integration/test_hint_flow.py`
- `backend/tests/integration/test_pp_elo_flow.py`

**集成测试场景**:

1. **注册-登录-绑定 CF 完整流程**
2. **随机挑战完整流程**: 匹配 -> 出题 -> 提交 -> 结算 -> Elo/PP/代币更新
3. **专题训练完整流程**: 选择专题 -> 开始训练 -> 解题 -> 连击奖励 -> PP 更新
4. **虚拟组赛完整流程**: 选择赛制 -> 比赛 -> 提交 -> 结算 -> Elo 更新
5. **经济系统完整流程**: AC 获取代币 -> 购买提示 -> 余额减少 -> 每日重置
6. **PP 聚合完整测试**: 解多题 -> 验证 PP 排序和加权
7. **配置热更新**: 修改配置 -> 新操作使用新配置

#### 测试要点（防Workaround验证清单）
- [ ] **端到端 - 注册到挑战**: 完整用户旅程
- [ ] **端到端 - 经济循环**: 赚取代币 -> 消费代币
- [ ] **端到端 - PP 累积**: 解多题后 PP 正确累积
- [ ] **并发 - 双人挑战**: 两个用户同时匹配
- [ ] **并发 - 代币竞争**: 同时获取代币不超每日上限
- [ ] **数据一致性**: 所有操作后数据库状态一致
- [ ] **API 兼容性**: 前端所有 API 调用正确

#### 验收标准
1. 所有集成测试通过
2. 端到端流程无阻塞
3. 数据一致性保证
4. 并发场景安全

---

### Task 13.2: 部署配置与文档
**状态**: [ ] 未开始
**优先级**: P1
**依赖**: Task 13.1

#### 任务描述
完善部署配置，编写部署文档和运维指南。

**需要创建/修改的文件**:
- `docker-compose.prod.yml` - 生产环境 compose
- `docker-compose.yml` - 更新为开发环境
- `.env.example` - 更新所有环境变量
- `docs/deployment.md` - 部署文档

**部署要求**:
- 生产环境使用非 root 用户运行
- 数据库密码通过环境变量注入
- 前端构建优化（代码分割、压缩）
- 后端 Gunicorn + Uvicorn workers
- Nginx 反向代理
- 健康检查端点
- 日志收集配置

#### 测试要点（防Workaround验证清单）
- [ ] **生产构建**: docker-compose -f docker-compose.prod.yml build 成功
- [ ] **生产启动**: 所有服务正常启动
- [ ] **环境变量**: 所有必需变量都有默认值或文档说明
- [ ] **非 root 用户**: 容器内进程非 root
- [ ] **健康检查**: /api/v1/health 返回正常
- [ ] **前端优化**: 检查 bundle size 合理
- [ ] **日志**: 关键操作有日志输出

#### 验收标准
1. 生产环境一键部署
2. 部署文档完整
3. 安全配置到位
4. 监控和日志完善

---

## 任务依赖关系总览

```
阶段 1 (基础设施):
  1.1 项目结构 -> 1.2 Docker -> 1.3 数据库 -> 1.4 API 框架

阶段 2 (核心算法, 依赖 1.4):
  2.1 Elo 引擎 (依赖 1.4)
  2.2 PP 引擎 (依赖 1.4)
  2.3 配置系统 (依赖 1.4)

阶段 3 (用户系统, 依赖 1.4):
  3.1 认证系统 (依赖 1.4)
  3.2 CF Handle (依赖 3.1)

阶段 4 (CF API):
  4.1 CF API 客户端 (依赖 1.4)

阶段 5-7 (核心玩法, 依赖 阶段2 + 阶段4):
  5.1 随机挑战 (依赖 2.1, 4.1)
  6.1 专题训练 (依赖 2.1, 2.2, 4.1)
  7.1 虚拟组赛 (依赖 2.1, 4.1)

阶段 8 (经济系统, 依赖 阶段5-7):
  8.1 代币系统 (依赖 5.1, 6.1, 7.1)
  8.2 提示系统 (依赖 8.1)

阶段 9 (前端):
  9.1 前端框架 (依赖 1.1)
  9.2 核心页面 (依赖 9.1)

阶段 10-12 (增强功能):
  10.1 数据可视化 (依赖 9.2)
  11.1 动画系统 (依赖 9.2)
  12.1 管理后台 (依赖 2.3, 9.2)

阶段 13 (测试部署):
  13.1 集成测试 (依赖所有)
  13.2 部署 (依赖 13.1)
```

---

## 执行优先级

**P0 - 必须首先完成** (阶段 1-5):
1.1 -> 1.2 -> 1.3 -> 1.4 -> 2.1 -> 2.2 -> 2.3 -> 3.1 -> 4.1 -> 5.1

**P1 - 核心功能** (阶段 6-9, 12):
可并行开发: 6.1, 7.1, 8.1, 9.1
顺序: 8.2 (依赖 8.1), 9.2 (依赖 9.1), 12.1 (依赖 2.3 + 9.2)

**P2 - 增强功能** (阶段 10-11):
10.1, 11.1 可并行

**最终** (阶段 13):
13.1 -> 13.2
