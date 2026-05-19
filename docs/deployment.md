# Code Arena - 部署文档

## 环境要求

| 组件         | 最低版本     | 说明                   |
|--------------|-------------|------------------------|
| Docker       | 24.0+       | 容器运行时             |
| Docker Compose | v2.20+    | 服务编排（docker compose 命令） |
| 内存         | 2 GB+       | 推荐用于生产环境       |
| 磁盘         | 10 GB+      | 数据库持久化 + Docker 镜像 |
| CPU          | 2 核+       | 推荐用于生产环境       |

## 快速开始

```bash
# 1. 克隆仓库
git clone <repository-url> code-arena
cd code-arena

# 2. 创建并编辑环境变量
cp .env.example .env

# 3. 生成安全的 JWT 密钥（选择一种方式）
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
# 或: openssl rand -hex 48

# 4. 编辑 .env，设置以下必填变量
#    POSTGRES_PASSWORD=<strong-password>
#    JWT_SECRET=<generated-secret>
#    DATABASE_URL=postgresql+asyncpg://postgres:<strong-password>@db:5432/code_arena

# 5. 一键启动生产环境
docker compose -f docker-compose.prod.yml up -d --build

# 6. 查看服务状态
docker compose -f docker-compose.prod.yml ps

# 7. 查看日志
docker compose -f docker-compose.prod.yml logs -f
```

启动完成后，访问 `http://<your-server-ip>` 即可使用。

## 环境变量说明

### 必填变量

| 变量               | 说明                                    | 示例                                        |
|--------------------|----------------------------------------|---------------------------------------------|
| `POSTGRES_PASSWORD` | PostgreSQL 数据库密码                   | `myS3cur3P@ssw0rd!`                        |
| `JWT_SECRET`        | JWT 令牌签名密钥                        | `openssl rand -hex 48` 生成                 |
| `DATABASE_URL`      | 数据库连接 URL                          | `postgresql+asyncpg://postgres:pwd@db:5432/code_arena` |

### 可选变量

| 变量                    | 默认值                                  | 说明                                   |
|-------------------------|----------------------------------------|----------------------------------------|
| `APP_NAME`              | `Code Arena`                           | 应用名称                               |
| `DEBUG`                 | `false`                                | 调试模式，生产环境必须为 false          |
| `POSTGRES_USER`         | `postgres`                             | 数据库用户名                           |
| `POSTGRES_DB`           | `code_arena`                           | 数据库名称                             |
| `DB_PORT`               | `5432`                                 | 数据库端口（仅容器内部）                |
| `CF_API_BASE_URL`       | `https://codeforces.com/api`           | Codeforces API 地址                    |
| `JWT_ALGORITHM`         | `HS256`                                | JWT 签名算法                           |
| `JWT_EXPIRATION_MINUTES`| `1440`                                 | Access Token 过期时间（分钟）           |
| `CORS_ORIGINS`          | `http://localhost,http://localhost:80` | CORS 允许的来源，逗号分隔               |
| `FRONTEND_URL`          | `http://localhost`                     | 前端 URL                               |
| `FRONTEND_PORT`         | `80`                                   | 前端对外端口                           |
| `GUNICORN_WORKERS`      | `4`                                    | Gunicorn worker 数量                    |
| `LOG_LEVEL`             | `info`                                 | 日志级别: debug/info/warning/error      |

## 生产部署步骤

### 1. 服务器准备

```bash
# 安装 Docker（Ubuntu/Debian）
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER

# 重新登录使 docker 组生效
exit
# 重新 SSH 登录

# 验证安装
docker --version
docker compose version
```

### 2. 部署应用

```bash
# 上传代码到服务器（选择一种方式）
# 方式 1: Git clone
git clone <repository-url> /opt/code-arena

# 方式 2: rsync
rsync -avz --exclude node_modules --exclude .git ./ user@server:/opt/code-arena/

# 进入项目目录
cd /opt/code-arena

# 配置环境变量
cp .env.example .env
nano .env  # 编辑并设置密码和密钥

# 构建并启动
docker compose -f docker-compose.prod.yml up -d --build
```

### 3. 验证部署

```bash
# 检查所有服务状态
docker compose -f docker-compose.prod.yml ps

# 所有服务应显示 "healthy"
# 预期输出:
#   db       running (healthy)
#   backend  running (healthy)
#   frontend running (healthy)

# 测试健康检查端点
curl -f http://localhost/api/v1/health

# 查看后端日志
docker compose -f docker-compose.prod.yml logs backend

# 查看前端日志
docker compose -f docker-compose.prod.yml logs frontend

# 查看数据库日志
docker compose -f docker-compose.prod.yml logs db
```

### 4. 验证非 root 用户

```bash
# 检查后端进程用户
docker compose -f docker-compose.prod.yml exec backend whoami
# 预期输出: appuser

# 检查前端 nginx 进程用户
docker compose -f docker-compose.prod.yml exec frontend whoami
# 预期输出: nginx
```

### 5. 配置 HTTPS（推荐）

推荐使用 Caddy 或 Nginx 作为外部反向代理来处理 TLS 终止。

**使用 Caddy（推荐，自动 HTTPS）：**

```bash
# 创建 Caddyfile
cat > /opt/Caddyfile << 'EOF'
your-domain.com {
    reverse_proxy localhost:80
}
EOF

# 启动 Caddy
docker run -d --name caddy \
  --network host \
  -v /opt/Caddyfile:/etc/caddy/Caddyfile \
  -v caddy_data:/data \
  -v caddy_config:/config \
  caddy:latest
```

更新 `.env` 中的 CORS 和 URL 设置：
```
FRONTEND_URL=https://your-domain.com
CORS_ORIGINS=https://your-domain.com
```

然后重启服务：
```bash
docker compose -f docker-compose.prod.yml restart
```

## 更新部署

```bash
cd /opt/code-arena

# 拉取最新代码
git pull origin main

# 重新构建并启动（自动处理零停机）
docker compose -f docker-compose.prod.yml up -d --build

# 如果需要完全重建
docker compose -f docker-compose.prod.yml down
docker compose -f docker-compose.prod.yml up -d --build
```

## 常见问题排查

### 服务无法启动

```bash
# 查看具体错误日志
docker compose -f docker-compose.prod.yml logs <service-name>

# 常见原因:
# 1. .env 文件不存在或缺少必填变量
# 2. 端口被占用
# 3. 磁盘空间不足
```

### 数据库连接失败

```bash
# 检查数据库是否健康
docker compose -f docker-compose.prod.yml exec db pg_isready -U postgres

# 检查 DATABASE_URL 是否正确
# 确保 DATABASE_URL 中的密码与 POSTGRES_PASSWORD 一致
# 确保主机名为 "db"（Docker 内部网络名）
```

### 前端无法访问后端 API

```bash
# 检查前端 nginx 配置中的代理目标
docker compose -f docker-compose.prod.yml exec frontend cat /etc/nginx/conf.d/default.conf

# 确保 backend 服务已启动且健康
docker compose -f docker-compose.prod.yml ps backend

# 测试容器间网络连通性
docker compose -f docker-compose.prod.yml exec frontend curl -f http://backend:8000/api/v1/health
```

### 健康检查失败

```bash
# 查看健康检查日志
docker inspect --format='{{json .State.Health}}' <container-id> | python3 -m json.tool

# 后端: 确认 curl 可访问
docker compose -f docker-compose.prod.yml exec backend curl -f http://localhost:8000/api/v1/health

# 前端: 确认 nginx 正常
docker compose -f docker-compose.prod.yml exec frontend curl -f http://localhost:80/
```

### 端口冲突

```bash
# 检查端口占用
sudo lsof -i :80
sudo lsof -i :5432

# 修改 .env 中的端口
FRONTEND_PORT=8080
DB_PORT=5433

# 重启服务
docker compose -f docker-compose.prod.yml up -d
```

### 容器日志排查

```bash
# 实时查看所有日志
docker compose -f docker-compose.prod.yml logs -f

# 查看最近 100 行日志
docker compose -f docker-compose.prod.yml logs --tail 100 backend

# 查看特定时间段的日志
docker compose -f docker-compose.prod.yml logs --since 30m backend
```

## 备份与恢复

### 数据库备份

```bash
# 创建备份目录
mkdir -p /opt/backups

# 手动备份
docker compose -f docker-compose.prod.yml exec db \
  pg_dump -U postgres code_arena > /opt/backups/code_arena_$(date +%Y%m%d_%H%M%S).sql

# 压缩备份
gzip /opt/backups/code_arena_$(date +%Y%m%d_%H%M%S).sql
```

### 自动每日备份（Cron）

```bash
# 编辑 crontab
crontab -e

# 添加每日凌晨 2 点自动备份
0 2 * * * cd /opt/code-arena && docker compose -f docker-compose.prod.yml exec -T db pg_dump -U postgres code_arena | gzip > /opt/backups/code_arena_$$(date +\%Y\%m\%d).sql.gz

# 保留最近 30 天备份，自动清理旧备份
0 3 * * * find /opt/backups -name "code_arena_*.sql.gz" -mtime +30 -delete
```

### 数据库恢复

```bash
# 停止后端服务（避免写入冲突）
docker compose -f docker-compose.prod.yml stop backend

# 解压备份文件
gunzip /opt/backups/code_arena_YYYYMMDD_HHMMSS.sql.gz

# 恢复数据
cat /opt/backups/code_arena_YYYYMMDD_HHMMSS.sql | \
  docker compose -f docker-compose.prod.yml exec -T db \
  psql -U postgres code_arena

# 重启后端
docker compose -f docker-compose.prod.yml start backend
```

### Docker 卷备份

```bash
# 备份 PostgreSQL 数据卷
docker run --rm -v code_arena_pgdata:/data -v /opt/backups:/backup \
  alpine tar czf /backup/pgdata_$(date +%Y%m%d).tar.gz -C /data .
```

## 监控和日志

### 日志配置

生产环境使用 `json-file` 日志驱动，配置如下：

| 服务     | 最大文件大小 | 最大文件数 |
|----------|-------------|-----------|
| db       | 10 MB       | 3         |
| backend  | 50 MB       | 5         |
| frontend | 10 MB       | 3         |

### 查看日志

```bash
# 实时跟踪日志
docker compose -f docker-compose.prod.yml logs -f backend

# 查看最近 200 行
docker compose -f docker-compose.prod.yml logs --tail 200 backend

# 查看错误日志
docker compose -f docker-compose.prod.yml logs backend 2>&1 | grep -i error

# 查看访问日志（Gunicorn）
docker compose -f docker-compose.prod.yml logs backend 2>&1 | grep "GET\|POST\|PUT\|DELETE"
```

### 健康检查

```bash
# 一键检查所有服务健康状态
docker compose -f docker-compose.prod.yml ps --format "table {{.Name}}\t{{.Status}}"

# 后端 API 健康检查
curl -s http://localhost/api/v1/health | python3 -m json.tool
```

### 资源使用监控

```bash
# 查看容器资源使用
docker stats --no-stream

# 查看磁盘使用
docker system df

# 清理未使用的资源（谨慎操作）
docker system prune -a --volumes
```

### 日志级别调整

在 `.env` 中修改 `LOG_LEVEL` 来调整日志详细程度：

```
LOG_LEVEL=debug    # 最详细，包含所有请求/响应
LOG_LEVEL=info     # 默认，记录关键操作
LOG_LEVEL=warning  # 仅警告和错误
LOG_LEVEL=error    # 仅错误
```

修改后重启后端：
```bash
docker compose -f docker-compose.prod.yml restart backend
```

## 架构概览

```
                    ┌──────────────┐
                    │   Internet   │
                    └──────┬───────┘
                           │
                    :80 (configurable)
                    ┌──────┴───────┐
                    │   Frontend   │  Nginx (non-root)
                    │   (nginx)    │  - 静态文件服务
                    │              │  - SPA 路由回退
                    │              │  - API 反向代理
                    │              │  - gzip 压缩
                    └──────┬───────┘
                           │ /api/* -> proxy_pass
                    ┌──────┴───────┐
                    │   Backend    │  Gunicorn + Uvicorn (non-root)
                    │   (fastapi)  │  4 workers
                    │   :8000      │
                    └──────┬───────┘
                           │
                    ┌──────┴───────┐
                    │   Database   │  PostgreSQL 16
                    │   (postgres) │  持久化卷
                    │   :5432      │
                    └──────────────┘
```

网络隔离：
- `internal` 网络：后端 <-> 数据库通信
- `frontend` 网络：前端 <-> 后端通信
- 数据库不暴露到外部网络
