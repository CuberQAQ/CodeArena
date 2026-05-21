# Human Action Required

## 1. 运行 CF 全球排名采样管道
**关联 Task**: 38.2 (FR-18.5)
**操作**: 管理员调用 `POST /api/v1/admin/cf-ranking/pipeline` 触发 CF 用户数据采样
**说明**: 代码逻辑已验证正确，但 cf_sample_users 表为空，需要运行采样管道（约 1-2 小时）才能在全球排名中显示 CF 用户
**监控**: `GET /api/v1/admin/cf-ranking/status`
