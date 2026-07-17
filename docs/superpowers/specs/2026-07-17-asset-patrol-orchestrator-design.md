# 资产巡检编排与缓存/live 查询策略设计

日期：2026-07-17

## 背景

当前项目已经有资产巡检基础能力：

- `dlc_mcp/patrol.py` 中的 `PatrolService`
- `dlc_mcp/asset_patrol.py` CLI 入口
- `patrol_runs`、`patrol_asset_snapshots`、`patrol_findings`、`patrol_metrics`、`patrol_errors` 巡检结果表

现有巡检主要面向 `daily_p0`，单表检查逻辑较窄，当前 `_check_table()` 主要调用分区画像能力。用户希望以 `ads_360_fin_income_cost_1d_di` 这类表为例，建立统一的资产巡检编排能力：执行每日核心表巡检或全量资产巡检时，系统能按信息类型选择缓存或 live 查询，调用对应 `dlc-mcp` 能力，产出最新、清晰、可解释的资产巡检报告。

## 目标

1. 在现有 `PatrolService` 基础上升级资产巡检编排能力，不重复造一套平行框架。
2. 支持每日核心表巡检、月度全量巡检和手动巡检。
3. 明确每类证据的查询策略：稳定资产事实走缓存，动态状态走 live。
4. 巡检结果写入巡检快照和报告，不把 live-only 证据写回长期资产事实缓存。
5. 每张表的巡检结果能清楚说明：基础资产是否完整、任务是否可解释、质量规则是否存在、运行实例是否正常、缺口原因和责任方。
6. 尽可能复用现有 store、live service、MCP tool 逻辑，减少重复代码。

## 非目标

- 不重写整个资产图谱或 MCP server。
- 不直接绕过 `dlc-mcp` 资产服务去 ad hoc 读取 SQLite。
- 不把任务运行实例、最新质量状态等动态信息长期缓存为基础资产事实。
- 不在本设计中定义最终核心表清单规则，只预留核心表筛选接口。

## 设计原则

- **复用优先**：保留 `PatrolService` 作为对外入口，内部拆小组件或私有方法，避免新增重复编排链路。
- **单表结果是中间产物**：巡检最终目标是巡检报告和问题清单，不是孤立的单表画像工具。
- **cache/live 明确标注**：所有证据都标记来源和查询策略。
- **缺口和失败分离**：live 查询成功但无数据是 `missing`；live 调用异常是 `live_failed`；策略未覆盖是 `not_checked`。
- **巡检快照不是长期事实缓存**：snapshot 记录本次巡检证据和判断，基础资产缓存仍只保存稳定事实。

## 组件设计

### 1. `PatrolService` 保持对外入口

继续使用现有 `dlc_mcp/patrol.py::PatrolService`，将其升级为资产巡检编排器。

建议内部结构：

```text
PatrolService
├─ ScopeResolver
│  ├─ daily_core candidates
│  ├─ monthly_full candidates
│  └─ manual candidates
│
├─ PatrolEvidenceCollector
│  ├─ cached evidence
│  └─ live-only evidence
│
├─ PatrolResultNormalizer
│  ├─ coverage statuses
│  ├─ issue classification
│  ├─ severity
│  └─ owner bucket
│
└─ PatrolReportPersistence
   ├─ patrol_asset_snapshots
   ├─ patrol_findings
   ├─ patrol_metrics
   └─ patrol_errors
```

实现时不要求一开始就创建多个新文件。优先在 `patrol.py` 中按方法分层；只有文件明显过大或职责复杂时，再抽出小模块。

### 2. CLI 入口扩展

当前 `asset_patrol.py` 只支持：

```text
--scope daily_p0
```

扩展为：

```text
--scope daily_core | monthly_full | manual | daily_p0
```

其中：

- `daily_p0` 保持兼容，可映射为 `daily_core` 的 P0 优先模式。
- `daily_core` 每日巡检核心表。
- `monthly_full` 月度全量资产巡检。
- `manual` 支持指定表、层级、owner、core_level 等范围。

建议参数：

```text
--instance-date
--limit
--batch-size
--offset 或 --cursor
--resume-run-id
--table
--layer
--owner
--core-level
--concurrency
--table-timeout-seconds
--retry
--retry-backoff-seconds
--api-delay-seconds
--failure-threshold
```

## 巡检模式

### `daily_core`

每日核心表巡检。

范围来源按优先级组合：

1. 专家标注为核心的表。
2. `is_core_table` 或 `get_asset_value_profile` 判定为 P0/P1/P2 的表。
3. 后续配置的核心表清单。
4. 兼容旧 `daily_p0` 时，可只选择 P0 或 P0 优先。

每天对范围内表执行完整 live-only 检查。

### `monthly_full`

月度全量巡检。

- 范围：所有表资产。
- 支持分批、限流、断点继续。
- 默认按层级和表名稳定排序。
- 每张表使用与 `daily_core` 相同的检查逻辑。
- 允许更长运行窗口。

### `manual`

手动巡检。

范围可以来自：

- 指定表名
- 指定层级
- 指定 owner
- 指定 core_level
- 指定 limit

用于临时诊断或验证巡检规则。

## 查询策略

### 缓存查询

这些属于稳定基础事实，巡检时从缓存/registry 读取：

| 信息 | 建议复用能力 | 策略 |
| --- | --- | --- |
| 表元数据 | `get_table_profile` / `get_table_detail` 内部等价逻辑 | cache |
| 字段 | `list_table_columns` / store columns | cache |
| 表血缘 | `get_table_lineage` / store lineage | cache |
| 数据源 | `get_data_source` / 表 profile 数据源 | cache |
| 核心表判断 | `is_core_table` / `get_asset_value_profile` / expert label | cache |

### live-only 查询

这些属于动态或需要最新判断的信息，巡检时 live 查询，不写入长期基础缓存：

| 信息 | 建议复用能力 | 策略 |
| --- | --- | --- |
| 表相关任务 | `get_table_tasks` 的 live-first/等价服务 | live-only |
| 任务详情 | `search_tasks`、`get_task_code`、任务详情 service | live-only |
| 任务上下游依赖 | `list_upstream_tasks` / `list_downstream_tasks` | live-only |
| 质量规则状态 | `get_quality_status` | live-only |
| 表产出状态 | `get_table_production_status` | live-only |
| 生产风险详情 | `get_table_production_risk_detail` | live-only |
| 任务运行实例 | `get_task_runs` | live-only |

live-only 查询结果可以写入 `patrol_asset_snapshots.snapshot_json` 和 `patrol_findings.evidence_json`，但不更新长期资产事实缓存表。

## 单表巡检中间结果

每张表 `_check_table()` 产出统一结构，供 snapshot、finding、report 聚合使用。

示例：

```json
{
  "asset_name": "ads_360_fin_income_cost_1d_di",
  "scope": "daily_core",
  "instance_date": "2026-07-17",
  "source_policy": {
    "metadata": "cache",
    "columns": "cache",
    "lineage": "cache",
    "tasks": "live_only",
    "quality": "live_only",
    "runs": "live_only"
  },
  "cached": {
    "metadata": {"status": "complete"},
    "columns": {"status": "complete", "count": 36},
    "lineage": {"status": "complete", "upstream_count": 26, "downstream_count": 13}
  },
  "live": {
    "tasks": {"status": "missing", "producer_count": 0, "consumer_count": 0},
    "quality": {"status": "missing", "rule_count": 0},
    "runs": {"status": "missing", "reason": "missing_producer_task"}
  },
  "issues": [
    {
      "type": "missing_producer_task",
      "severity": "p1",
      "source": "live",
      "evidence": "live query succeeded but no producer task was found"
    }
  ]
}
```

## 报告结构

每日核心表巡检和月度全量巡检使用同一报告结构，区别在 `mode/scope` 和范围。

```text
资产巡检报告
├─ 1. 巡检摘要
├─ 2. 数据来源与查询策略
├─ 3. 覆盖总览
├─ 4. P0 当日必须处理
├─ 5. P1 需要跟进
├─ 6. 表明细
├─ 7. live 查询失败清单
├─ 8. 缓存缺口清单
├─ 9. 按责任方拆解
└─ 10. 验收标准
```

摘要字段：

| 字段 | 含义 |
| --- | --- |
| `run_id` | 本次巡检 ID |
| `mode` | `daily_core` / `monthly_full` / `manual` |
| `instance_date` | 查询日期 |
| `table_count` | 应巡检表数 |
| `checked_count` | 实际完成表数 |
| `live_success_count` | live 完整成功表数 |
| `live_partial_count` | live 部分缺失表数 |
| `live_failed_count` | live 失败表数 |
| `p0_count` | P0 问题数 |
| `p1_count` | P1 问题数 |
| `started_at` / `finished_at` | 巡检时间 |
| `elapsed_seconds` | 耗时 |

覆盖总览按表展示：

| 表名 | 核心等级 | Owner | 元数据 | 字段 | 血缘 | 任务 | 质量 | 运行 | 状态 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `ads_360_fin_income_cost_1d_di` | P2 | tencent | 完整 | 完整 | 完整 | 缺失 | 缺失 | 缺失 | P1 |

## 问题分类

缓存侧问题：

- `missing_table_metadata`
- `missing_columns`
- `missing_lineage`
- `missing_data_source`
- `unknown_layer`
- `missing_owner`

live 侧问题：

- `missing_related_tasks`
- `missing_producer_task`
- `missing_task_detail`
- `missing_quality_rules`
- `missing_task_runs`
- `task_run_failed`
- `task_run_timeout`
- `live_api_error`
- `live_tool_unsupported`

策略侧状态：

- `not_checked_by_scope`
- `skipped_by_rate_limit`
- `deferred_to_monthly_full`

## P0/P1/P2 判定

### P0

满足任一条件：

- P0/P1 核心表当日产出任务运行失败。
- P0/P1 核心表 live 查询到产出任务，但当日无运行实例。
- P0/P1 核心表元数据或字段缺失，导致基础画像不可用。
- live API 大面积失败，导致本次核心巡检不可信。
- 核心表 owner 缺失且同时存在生产异常。

### P1

满足任一条件：

- 核心表缺相关任务或缺产出任务。
- 核心表缺质量规则。
- 核心表血缘不完整。
- 核心表 live 查询部分失败，但基础缓存完整。
- ADS/DWS 高下游表缺运行实例证据。

### P2

- 非核心表问题。
- 月度全量巡检中的低影响缺口。
- unknown 资产归类问题。
- 低影响字段描述缺失。

## 持久化策略

继续复用现有巡检表：

- `patrol_runs`：记录 run 元信息、状态、配置和 summary。
- `patrol_asset_snapshots`：记录每张表本次巡检中间结果。
- `patrol_findings`：记录结构化问题。
- `patrol_metrics`：记录聚合指标。
- `patrol_errors`：记录 live/API/超时/异常。

需要补强：

1. `summary_json` 中增加 live 成功/部分/失败计数、P0/P1/P2 计数。
2. `snapshot_json` 中保留 `source_policy`、cached/live evidence、coverage statuses。
3. `patrol_findings.evidence_json` 中明确 `source`、`tool`、`query_mode`、`evidence`。
4. 不新增长期缓存表来保存 live-only 结果。

## 错误处理

- 单表超时：记录 `patrol_errors`，该表状态为 `live_failed` 或 `check_failed`，不阻断整批。
- live API 错误：记录具体 action、错误码、是否 retryable。
- live 查询成功但无数据：记录为 `missing_*` finding，不记为 API 错误。
- 工具不支持：记录 `live_tool_unsupported`。
- 超过失败阈值：run 状态置为 `failed`，否则为 `partial` 或 `completed`。

## 测试策略

### 单元测试

- `asset_patrol.py` 参数解析支持 `daily_core`、`monthly_full`、`manual`，并兼容 `daily_p0`。
- `PatrolService` 能根据 scope 选择候选表。
- `_check_table()` 能组合缓存证据和 live-only 证据。
- live 查询成功但无数据时产生 `missing_*` finding。
- live 查询异常时产生 `patrol_errors`，不误判为 missing。
- `monthly_full` 支持分批和 limit/offset 或 cursor。
- 巡检 summary 包含 live 成功/部分/失败计数和 P0/P1/P2 计数。

### 集成测试

- 构造 `ads_360_fin_income_cost_1d_di` 类似表：有元数据、字段、血缘，但 live 无任务/质量/运行实例。
- 执行 `daily_core` 后应写入 snapshot，并产生缺任务、缺质量、缺运行实例 findings。
- 构造 live 失败表，确认进入 errors 而不是 findings。
- 构造全量巡检，确认所有表进入候选或按 limit 分批进入。

### 验证命令

```bash
python3 -m unittest discover -s tests -v
node --check bin/dlc-mcp.js
npm pack --dry-run
```

## 实施顺序

1. 扩展 CLI scope 和参数，保持 `daily_p0` 兼容。
2. 在 `PatrolService` 中新增统一 `run(scope, ...)` 或 `run_daily_core` / `run_monthly_full` / `run_manual` 方法。
3. 抽出候选表选择逻辑，支持 daily_core、monthly_full、manual。
4. 扩展 `_check_table()`：从单一分区检查升级为缓存证据 + live-only 证据收集。
5. 增加结果归一化和 finding 分类。
6. 扩展持久化 summary/snapshot/finding/error。
7. 更新 MCP 报告读取/格式化，使 patrol snapshot 能展示新的报告结构。
8. 补充测试并运行验证命令。

## 通过标准

- `daily_core` 能巡检核心表，并输出缓存/live 来源明确的报告。
- `monthly_full` 能按全量表范围执行，并支持分批或 limit 调试。
- `manual` 能指定表或范围执行同一套检查。
- live-only 证据不写入长期资产事实缓存，只进入巡检 snapshot/finding/error。
- 报告能清楚区分 missing、live_failed、not_checked。
- 现有 `daily_p0` 调用不破坏。
- 单元测试、Node 检查、npm pack dry-run 通过。
