# 本地资产治理诊断增强设计

日期：2026-07-15

## 背景

当前 live 增量同步受环境文件和腾讯云凭证阻塞，但本地 SQLite 资产库仍可用于继续治理诊断。用户确认本轮不处理“高影响质量规则补齐”，因为数据源本身质量规则较少。本轮应优先修复和增强本地可验证的问题：unknown 中 `mid_*` 层级识别、任务映射缺口解释、运行实例缺口解释。

## 目标

1. 让 `mid_*` 表稳定识别为 `mid`，不再因为层级为空或 unknown 影响主覆盖口径。
2. 为存量库中 `layer = ''` 或 `layer = 'unknown'` 的表提供本地重算路径。
3. 增强 `missing_task_mapping` 的 `suspected_root_cause` 和 `recommended_next_check`，让治理动作更可执行。
4. 增强 `missing_task_runs` 的 `suspected_root_cause` 和 `recommended_next_check`，区分 producer 缺失、运行窗口缺口、task_id 对齐等原因。
5. 保持现有 MCP 返回结构兼容，不引入 live API 依赖。

## 非目标

- 不补质量规则。
- 不调整质量规则 P0/P1 优先级。
- 不依赖 `/etc/dlc-mcp/env` 或腾讯云 live API。
- 不执行全量资产同步。
- 不新增大型 CLI；如后续需要批量修复命令，再单独设计。

## 设计

### 1. 层级识别保障

现有数据流为：

```text
WeData API dump
  -> dlc_mcp/wedata.py:snapshot_from_api_dump()
  -> _table_from_api()
  -> _table_layer()
  -> AssetStore.upsert_table()
  -> SQLite tables.layer
  -> coverage / issue inventory / daily report
```

本轮沿用该数据流，做两层保障：

1. 导入时识别：继续通过 `_table_layer()` 从 explicit layer、database、folder、datasource、table name 推断层级，并补充测试证明 `mid_crm_customer_df`、`mid_sms_instance_bill_detail_di` 会识别为 `mid`。
2. 存量库重算：在 `AssetStore` 中提供小型本地方法，例如 `refresh_inferred_layers()`，只处理 `layer = ''` 或 `layer = 'unknown'` 的表。该方法根据表名重新推断有效数仓层级，不覆盖已有明确的 `ods/dim/dwd/dws/mid/ads`。

### 2. 任务映射缺口解释增强

保留现有 issue inventory 结构，不改变顶层返回格式。增强字段集中在：

- `suspected_root_cause`
- `recommended_next_check`
- evidence 中已有计数字段的组合解释

分类规则：

- `parser_gap`：`task_count = 0`，疑似 SQL/任务表名解析不到该表。
- `producer_mapping_gap`：`task_count > 0` 且 `producer_task_count = 0`，说明有相关任务但没有识别出产出任务。
- `layer_mapping_gap`：表层级为空或 unknown，且有下游、任务或运行实例，说明该表可能被错误排除在主覆盖口径之外。
- `normalization_gap`：当表名表现出可能的标准化差异时，在 next check 中提示检查表名标准化和 SQL 引用格式。

### 3. 运行实例缺口解释增强

同样保留现有 issue inventory 结构。分类规则：

- `instance_window_gap`：`producer_task_count > 0` 且 `run_count = 0`，优先检查 `ListTaskInstances` 时间窗口、页数上限、task_id 对齐。
- `producer_missing_gap`：`producer_task_count = 0` 且 `run_count = 0`，不能直接判定任务未执行，应先修 producer 映射。
- `task_id_alignment_gap`：当存在任务关联但运行实例不能按 task_id 串联时，在 next check 中提示 task_id / task_name 对齐。
- `unknown_layer_gap`：unknown 层表存在 producer 或 run 风险时，提示先修层级归类以稳定覆盖口径。

## 错误处理与兼容性

- 存量层级重算只更新空层级或 unknown 层级，不覆盖明确层级，降低误伤。
- 如果表名无法推断层级，保持原值，不伪造健康状态。
- issue inventory 不改变顶层 schema，避免破坏现有 MCP 客户端。
- 缺少 live env 时仍可运行本地测试和基于 SQLite 的诊断。

## 测试计划

1. `mid_*` 层级识别：
   - `mid_crm_customer_df` -> `mid`
   - `mid_sms_instance_bill_detail_di` -> `mid`
   - `ads_xxx` / `dwd_xxx` 等原有层级不回退

2. 存量 unknown 重算：
   - layer 为空或 unknown 的 `mid_crm_customer_df` 重算后变为 `mid`
   - 已有明确 layer 的表不被覆盖

3. `missing_task_mapping` 分类：
   - `task_count = 0` -> `parser_gap`
   - `task_count > 0` 且 `producer_task_count = 0` -> `producer_mapping_gap`
   - unknown 高影响表给出 layer 相关 next check

4. `missing_task_runs` 分类：
   - 有 producer、无 run -> `instance_window_gap`
   - 无 producer、无 run -> `producer_missing_gap`
   - unknown 层有 producer 或运行风险时给出 layer 提示

## 验收标准

- `mid_*` 表不会继续因为可推断层级缺失而作为高优 unknown layer 问题出现。
- `missing_task_mapping` 的 root cause 和 next check 能区分 parser、producer、layer、normalization 方向。
- `missing_task_runs` 的 root cause 和 next check 能区分 producer 缺失、运行窗口缺口、task_id 对齐方向。
- 现有 MCP 返回结构保持兼容。
- 不以质量规则覆盖率作为本轮验收指标。
- 没有 live env 时，仍能通过本地 SQLite 事实库和单元测试验证改动。

## 实施边界

本设计适合拆成一个小型实现计划：先补测试，再实现层级重算和 issue 分类增强，最后用当前本地事实库复查治理输出。若后续需要批量修复命令或 live 同步执行方案，应另开设计或实现计划。
