# 资产覆盖率修复设计

日期：2026-07-14

## 1. 背景与目标

当前资产覆盖率中，字段覆盖较高，但血缘、任务映射、运行实例关联覆盖偏低。质量规则覆盖暂不在本次修复范围。

本次修复目标是让覆盖率更准确反映真实数仓资产健康度，同时保留 unknown 资产池作为治理对象：

1. 修复层级识别和覆盖率口径，加入 `mid` 作为合法数仓层。
2. 增强任务到表的 input/output 解析，提高 `task_tables` 准确率。
3. 修复运行实例关联的诊断链路，保持 output-only 生产实例口径。

## 2. 术语与口径

### 2.1 有效数仓层

有效数仓层包含：

- `ods`
- `dim`
- `dwd`
- `dws`
- `mid`
- `ads`

`mid` 是合法但可选的数仓分层；不是所有链路都必须出现 `mid`。

### 2.2 unknown 资产池

`unknown` 表不删除、不视为健康，也不纳入主覆盖率分母。它们单独作为待治理资产池展示，包括数量、已有事实覆盖情况和样例。

### 2.3 血缘

覆盖率中的血缘指表级血缘：

```text
upstream table -> downstream table
```

不是任务之间的依赖关系。任务依赖关系继续作为独立事实存在。

### 2.4 运行实例关联

运行实例关联只统计表的产出任务实例：

```text
table -> output task -> task_runs
```

input/consumer 任务实例不能算作表生产实例。

## 3. 层级识别与覆盖率口径

### 3.1 层级识别

在 `dlc_mcp/wedata.py` 中扩展层级识别逻辑，将 `mid` 加入合法层级集合。

识别来源包括：

- 表名：如 `mid_xxx`、`xxx_mid_xxx`
- 数据库名：如 `mid_mart`、`warehouse_mid`
- 路径：如 `/warehouse/mid/finance`
- WeData 显式字段：`Layer`、`TableLayer`、`BizLayer`、`DataLayer`、`layer`

`dlc_mcp/diagnose_asset_gaps.py` 中的诊断层级集合也同步加入 `mid`。

### 3.2 覆盖率输出

`get_asset_coverage()` 继续返回逐层明细，但额外增加两个聚合区块：

```json
{
  "warehouse_coverage": {
    "table_count": 0,
    "fields": 0.0,
    "lineage": 0.0,
    "quality": 0.0,
    "tasks": 0.0,
    "runs": 0.0,
    "data_source": 0.0
  },
  "unknown_pool": {
    "table_count": 0,
    "tables_with_columns": 0,
    "tables_with_lineage": 0,
    "tables_with_tasks": 0,
    "tables_with_runs": 0,
    "tables_with_data_source": 0
  }
}
```

主展示优先显示有效数仓覆盖率，再显示 unknown 资产池。

### 3.3 不做的事情

- 不删除 unknown 表。
- 不把 unknown 当健康。
- 不把所有 unknown 从治理视图中隐藏。
- 不强制所有业务链路都有 `mid`。

## 4. 任务到表映射增强

### 4.1 统一表名规范化

所有任务来源解析出的表名都经过统一规范化：

- 去掉库名前缀：`byai_bigdata.ads_xxx` -> `ads_xxx`
- 去掉反引号等 SQL 标识符包装
- 支持 `mid` 层表名
- 过滤明显不是表名的字符串
- 保留现有防误判逻辑：不能只因为任务名像表名就创建表资产

### 4.2 扩展 input/output 字段解析

增强 `dlc_mcp/wedata.py` 中任务表解析逻辑。

输入方向候选字段包括：

- `InputTables`
- `InputTableList`
- `SourceTables`
- `SourceTableList`
- `Sources`
- `Reads`
- `ReadTables`
- `DependencyTables`

输出方向候选字段包括：

- `OutputTables`
- `OutputTableList`
- `TargetTables`
- `TargetTableList`
- `SinkTables`
- `WriteTables`
- `Writes`
- `Resource`
- `Resources`

字段值可能是 JSON 字符串、列表、字典或逗号/空白分隔字符串，统一递归解析。

### 4.3 加强 SQL 解析

继续从任务 SQL 中解析表名。

输出表模式包括：

- `insert overwrite table xxx`
- `insert into xxx`
- `create table xxx as`

输入表模式包括：

- `from xxx`
- `join xxx`

解析时需要过滤：

- 注释里的表名
- 临时表
- CTE 名称
- 函数名
- 非数仓层表名

新增 `mid` 后，`mid_xxx` 表可以作为合法 input/output。

### 4.4 使用血缘/任务详情补强 output

如果 `ListProcessLineage`、任务配置、`GetTask` 或 `GetTaskCode` 明确返回任务产出资源表，则写入 output 映射。

如果方向不明确，不写 output，避免把消费任务误判为生产任务。

### 4.5 记录解析来源

尽量在 `asset_edges.evidence_json` 或相关报告中保留来源和置信度：

- `task_payload`
- `task_sql`
- `get_task_code`
- `process_lineage`

来源用于后续排查任务映射质量。

## 5. 运行实例关联修复

### 5.1 保持 output-only 口径

运行实例关联继续只统计 output 任务：

```sql
from task_tables tt
join task_runs r on r.task_id = tt.task_id
where tt.direction = 'output'
```

input 任务实例不计入表生产实例。

### 5.2 细分运行实例缺口原因

在覆盖缺口和治理 issue 中区分：

1. 缺相关任务。
2. 有相关任务但缺产出任务。
3. 有产出任务但缺运行实例。

示例：

```text
task_count = 3, producer_task_count = 0, run_count = 0 -> 缺产出任务映射
producer_task_count = 1, run_count = 0 -> 有产出任务但缺运行实例
```

### 5.3 同步窗口显式化

在覆盖报告或同步健康报告中展示运行实例同步窗口相关信息：

- `WEDATA_INSTANCE_START`
- `WEDATA_INSTANCE_END`
- `WEDATA_INSTANCE_TIMEZONE`
- `WEDATA_INSTANCE_KEYWORDS`
- task run retention days

这样运行实例低时，可以判断是否为同步窗口或保留期问题。

### 5.4 不扩大默认同步窗口

增量同步继续默认同步昨天的实例窗口。不在本次改动中扩大默认窗口，避免同步成本突然上升。

## 6. 代码影响范围

预计修改：

- `dlc_mcp/wedata.py`
- `dlc_mcp/diagnose_asset_gaps.py`
- `dlc_mcp/assets.py`
- `dlc_mcp/mcp.py`
- `tests/test_wedata_import.py`
- `tests/test_diagnose_asset_gaps.py`
- `tests/test_assets.py`
- `tests/test_mcp.py`

必要时修改：

- `dlc_mcp/sync_wedata.py`

## 7. 测试计划

### 7.1 `tests/test_wedata_import.py`

覆盖：

- `mid_xxx` 表名识别为 `mid`
- `warehouse_mid` 或 `/warehouse/mid/...` 识别为 `mid`
- input/output 字段别名解析
- JSON 字符串、列表、字典解析
- SQL 中 `mid` 表解析
- 任务名像表名但无明确表配置时，不创建假资产

### 7.2 `tests/test_diagnose_asset_gaps.py`

覆盖：

- `mid` 是合法层，不计入 unknown
- unknown 仍单独诊断
- 可推断层级的 unknown 样例能提示 parser 可修复

### 7.3 `tests/test_assets.py`

覆盖：

- `get_asset_coverage()` 返回有效数仓覆盖率
- unknown 不计入主覆盖率分母
- unknown 资产池仍展示
- 运行实例缺口能区分缺产出任务和有产出任务但无运行实例

### 7.4 `tests/test_mcp.py`

覆盖：

- MCP 展示主覆盖率和 unknown 资产池
- 运行实例缺口说明可读

## 8. 验收标准

实现完成后，应满足：

1. `get_asset_coverage()` 明确显示有效数仓覆盖率和 unknown 资产池。
2. `mid` 被识别为合法层。
3. 主覆盖率分母不包含 unknown。
4. unknown 数量仍可见、可治理。
5. 任务映射覆盖率因更完整的 input/output 解析提升。
6. 运行实例覆盖率只通过 output 任务提升，不通过 input 任务虚增。
7. 有血缘但无任务的高价值表能被定位为任务解析缺口。
8. 相关自动化测试通过。

## 9. 明确非目标

本次不做：

- 质量规则覆盖修复。
- 默认扩大增量同步窗口。
- 删除或隐藏 unknown 表。
- 用任务名直接创建表资产。
- 将 input 任务实例算作表生产实例。
- 调整真实 WeData 任务调度配置。
