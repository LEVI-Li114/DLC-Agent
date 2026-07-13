# Project Operating Rules

- 查数据：走 `dlc-mcp` MCP server。
- 部署、补数、重启、查日志：走 `ssh`。

## Architecture Boundary

- MCP Tools 层：用户只调用工具，输出治理结论、DDL、任务、血缘、缺口。
- Live Connector 层：封装 WeData/DLC API，负责分页、重试、限流、字段解析。
- Asset Store 层：SQLite 缓存/资产图谱，存事实、证据、刷新状态，支持跨资产分析。
- Sync Jobs / Admin Ops 层：全量补数、增量同步、重启服务、查日志。

普通数据查询不要绕过 MCP tools 去读 SQLite、跑 `curl` 或走 `ssh`。只有运维动作才使用 `ssh`。
