# Asset Coverage Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix asset coverage reporting so `mid` is a valid warehouse layer, unknown assets are tracked separately, task-to-table parsing is more complete, and run coverage explains output-task gaps accurately.

**Architecture:** Keep the existing import pipeline and SQLite schema. Extend parsing helpers in `dlc_mcp/wedata.py`, then improve reporting/diagnostics in `dlc_mcp/assets.py` and Markdown formatting in `dlc_mcp/mcp.py`. Preserve output-only semantics for table production runs.

**Tech Stack:** Python 3.10, SQLite via `sqlite3`, pytest, existing MCP formatter helpers.

## Global Constraints

- Effective warehouse layers are exactly `ods`, `dim`, `dwd`, `dws`, `mid`, `ads`.
- `mid` is valid but optional; do not require every business chain to include it.
- `unknown` tables must not be deleted, hidden, or treated as healthy.
- Main coverage denominator excludes `unknown`; `unknown` remains visible as a separate governance pool.
- Coverage lineage is table-level lineage, not task-to-task dependency.
- Run coverage remains output-only: `table -> output task -> task_runs`.
- Do not count input/consumer task runs as table production runs.
- Do not use task names alone to create table assets.
- Do not fix quality-rule coverage in this plan.
- Do not expand the default incremental sync window.

---

## File Structure

- Modify `dlc_mcp/wedata.py`
  - Owns WeData API dump normalization, table layer inference, task input/output table parsing, SQL table extraction.
- Modify `dlc_mcp/diagnose_asset_gaps.py`
  - Owns CLI/report diagnostics for unknown layers and parser-fixable layer inference.
- Modify `dlc_mcp/assets.py`
  - Owns SQLite-backed coverage metrics, gap classification, governance issue inventory, and production/run linkage summaries.
- Modify `dlc_mcp/mcp.py`
  - Owns Markdown rendering for MCP tool responses.
- Modify `tests/test_wedata_import.py`
  - Parser/import behavior tests.
- Modify `tests/test_diagnose_asset_gaps.py`
  - Layer diagnostic tests.
- Modify `tests/test_assets.py`
  - Coverage and gap-classification tests.
- Modify `tests/test_mcp.py`
  - Markdown formatting tests.

---

### Task 1: Add `mid` as a Valid Warehouse Layer

**Files:**
- Modify: `dlc_mcp/wedata.py:657-663`
- Modify: `dlc_mcp/diagnose_asset_gaps.py:9`
- Test: `tests/test_wedata_import.py`
- Test: `tests/test_diagnose_asset_gaps.py`

**Interfaces:**
- Consumes: existing `_layer_from_text(value: object) -> str` and `_table_layer(item: dict, name: str, database: str) -> str`.
- Produces: `WAREHOUSE_LAYERS: tuple[str, ...]` in `dlc_mcp/wedata.py`; `_layer_from_text()` returns `"mid"` when found in text tokens.

- [ ] **Step 1: Write failing import tests for `mid` layer inference**

Append this test to `tests/test_wedata_import.py` near `test_infers_layer_from_database_path_and_layer_aliases`:

```python
def test_infers_mid_layer_from_name_database_path_and_aliases(self):
    snapshot = snapshot_from_api_dump(
        {
            "tables": {
                "Response": {
                    "Data": {
                        "Items": [
                            {"Name": "mid_customer_profile_di"},
                            {"Name": "customer_profile", "DatabaseName": "warehouse_mid"},
                            {"Name": "seat_daily", "FolderPath": "/warehouse/mid/finance"},
                            {"Name": "order_detail", "BizLayer": "mid"},
                        ]
                    }
                }
            }
        }
    )

    self.assertEqual([table["layer"] for table in snapshot["tables"]], ["mid", "mid", "mid", "mid"])
```

- [ ] **Step 2: Write failing diagnostic test for `mid` not being unknown**

Append this test to `tests/test_diagnose_asset_gaps.py`:

```python
def test_mid_layer_is_not_reported_as_unknown(self):
    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "assets.db")
        store = AssetStore(sqlite3.connect(db_path))
        store.init_schema()
        store.upsert_table({"name": "mid_customer_profile_di", "layer": "mid", "owner": "owner-a"})
        store.upsert_table({"name": "mystery_table", "layer": "unknown", "owner": "owner-b"})

        report = render_gap_diagnosis(db_path, tmp, sample_limit=10)

    self.assertIn("DB unknown 层表数：**1**", report)
    self.assertIn("mystery_table", report)
    self.assertNotIn("mid_customer_profile_di |", report)
```

If imports are missing in the file, ensure the top of `tests/test_diagnose_asset_gaps.py` contains:

```python
import os
import sqlite3
import tempfile
import unittest

from dlc_mcp.assets import AssetStore
from dlc_mcp.diagnose_asset_gaps import render_gap_diagnosis
```

- [ ] **Step 3: Run the new tests and verify they fail**

Run:

```bash
python -m pytest tests/test_wedata_import.py::WedataImportTest::test_infers_mid_layer_from_name_database_path_and_layer_aliases tests/test_diagnose_asset_gaps.py::DiagnoseAssetGapsTest::test_mid_layer_is_not_reported_as_unknown -v
```

Expected: first test fails because `mid` is not inferred. The diagnostic test may also fail until the diagnostic layer set includes `mid`.

- [ ] **Step 4: Add shared layer constants and include `mid`**

In `dlc_mcp/wedata.py`, add this constant above `INPUT_TABLE_FIELDS`:

```python
WAREHOUSE_LAYERS = ("ods", "dim", "dwd", "dws", "mid", "ads")
WAREHOUSE_LAYER_SET = set(WAREHOUSE_LAYERS)
```

Replace `_layer_from_text()` with:

```python
def _layer_from_text(value):
    text = str(value or "").lower().replace("-", "_").replace("/", "_").replace(".", "_")
    parts = [part for part in text.split("_") if part]
    for part in parts:
        if part in WAREHOUSE_LAYER_SET:
            return part
    return ""
```

In `dlc_mcp/diagnose_asset_gaps.py`, replace:

```python
LAYER_VALUES = {"ods", "dim", "dwd", "dws", "ads"}
```

with:

```python
LAYER_VALUES = {"ods", "dim", "dwd", "dws", "mid", "ads"}
```

- [ ] **Step 5: Run layer tests and verify they pass**

Run:

```bash
python -m pytest tests/test_wedata_import.py::WedataImportTest::test_infers_mid_layer_from_name_database_path_and_layer_aliases tests/test_diagnose_asset_gaps.py::DiagnoseAssetGapsTest::test_mid_layer_is_not_reported_as_unknown -v
```

Expected: both tests pass.

- [ ] **Step 6: Commit Task 1**

```bash
git add dlc_mcp/wedata.py dlc_mcp/diagnose_asset_gaps.py tests/test_wedata_import.py tests/test_diagnose_asset_gaps.py
git commit -m "Add mid as warehouse layer"
```

---

### Task 2: Add Warehouse Coverage and Unknown Pool Metrics

**Files:**
- Modify: `dlc_mcp/assets.py:1070-1100`
- Modify: `dlc_mcp/mcp.py:740-764`
- Test: `tests/test_assets.py`
- Test: `tests/test_mcp.py`

**Interfaces:**
- Consumes: `AssetStore.get_asset_coverage() -> dict` existing return fields `totals`, `layers`, `coverage_notes`.
- Produces: additional keys `warehouse_coverage`, `unknown_pool`, and `warehouse_layers` in `get_asset_coverage()` result.

- [ ] **Step 1: Write failing coverage metric test**

Append this test to `tests/test_assets.py` in the main test class that already uses `make_store()`:

```python
def test_asset_coverage_reports_warehouse_and_unknown_pool_separately(self):
    store = make_store()
    store.upsert_table({"name": "ads_revenue", "layer": "ads", "data_source_id": "DLC"})
    store.upsert_table({"name": "mid_revenue", "layer": "mid", "data_source_id": "DLC"})
    store.upsert_table({"name": "mystery_table", "layer": "unknown", "data_source_id": "DLC"})
    store.upsert_column("ads_revenue", "id", "string", "", 1)
    store.upsert_column("mid_revenue", "id", "string", "", 1)
    store.upsert_lineage("mid_revenue", "ads_revenue", "build_ads_revenue")
    store.upsert_task({"id": "task_ads", "name": "build_ads_revenue", "outputs": ["ads_revenue"], "inputs": ["mid_revenue"]})
    store.upsert_task_run({"task_id": "task_ads", "instance_id": "run_1", "instance_date": "2026-07-13", "status": "COMPLETED"})

    coverage = store.get_asset_coverage()

    self.assertEqual(coverage["warehouse_layers"], ["ods", "dim", "dwd", "dws", "mid", "ads"])
    self.assertEqual(coverage["warehouse_coverage"]["table_count"], 2)
    self.assertEqual(coverage["warehouse_coverage"]["tables_with_columns"], 2)
    self.assertEqual(coverage["warehouse_coverage"]["tables_with_lineage"], 2)
    self.assertEqual(coverage["warehouse_coverage"]["tables_with_tasks"], 2)
    self.assertEqual(coverage["warehouse_coverage"]["tables_with_runs"], 1)
    self.assertEqual(coverage["warehouse_coverage"]["ratios"]["fields"], 1.0)
    self.assertEqual(coverage["warehouse_coverage"]["ratios"]["lineage"], 1.0)
    self.assertEqual(coverage["warehouse_coverage"]["ratios"]["tasks"], 1.0)
    self.assertEqual(coverage["warehouse_coverage"]["ratios"]["runs"], 0.5)
    self.assertEqual(coverage["unknown_pool"]["table_count"], 1)
    self.assertEqual(coverage["unknown_pool"]["tables_with_data_source"], 1)
```

- [ ] **Step 2: Write failing MCP formatting test**

Append this test to `tests/test_mcp.py` in the existing MCP test class:

```python
def test_get_asset_coverage_formats_warehouse_and_unknown_sections(self):
    store = AssetStore(sqlite3.connect(":memory:"))
    store.init_schema()
    store.upsert_table({"name": "ads_revenue", "layer": "ads", "data_source_id": "DLC"})
    store.upsert_table({"name": "mystery_table", "layer": "unknown"})
    data = store.get_asset_coverage()

    text = format_tool_result("get_asset_coverage", data)

    self.assertIn("有效数仓覆盖", text)
    self.assertIn("unknown 资产池", text)
    self.assertIn("unknown 不计入主覆盖率", text)
```

Ensure `tests/test_mcp.py` imports `format_tool_result` from `dlc_mcp.mcp` and `AssetStore` from `dlc_mcp.assets`; if aliases already exist, use the existing names.

- [ ] **Step 3: Run tests and verify they fail**

Run:

```bash
python -m pytest tests/test_assets.py::AssetsTest::test_asset_coverage_reports_warehouse_and_unknown_pool_separately tests/test_mcp.py::McpTest::test_get_asset_coverage_formats_warehouse_and_unknown_sections -v
```

Expected: tests fail because new fields and sections are absent.

- [ ] **Step 4: Add warehouse coverage aggregation helpers**

In `dlc_mcp/assets.py`, add these module-level constants near `GOVERNANCE_ISSUE_TYPES`:

```python
WAREHOUSE_LAYERS = ("ods", "dim", "dwd", "dws", "mid", "ads")
WAREHOUSE_LAYER_SET = set(WAREHOUSE_LAYERS)
```

Add these helper functions near `_coverage_gaps()`:

```python
def _coverage_ratio(numerator, denominator):
    return round(int(numerator or 0) / int(denominator or 0), 4) if int(denominator or 0) else 0


def _coverage_summary(rows):
    summary = {
        "table_count": 0,
        "tables_with_columns": 0,
        "tables_with_quality_rules": 0,
        "tables_with_lineage": 0,
        "tables_with_tasks": 0,
        "tables_with_runs": 0,
        "tables_with_data_source": 0,
    }
    for row in rows:
        table_count = int(row.get("table_count") or 0)
        upstream = int(row.get("tables_with_upstream") or 0)
        downstream = int(row.get("tables_with_downstream") or 0)
        summary["table_count"] += table_count
        summary["tables_with_columns"] += int(row.get("tables_with_columns") or 0)
        summary["tables_with_quality_rules"] += int(row.get("tables_with_quality_rules") or 0)
        summary["tables_with_lineage"] += min(table_count, upstream + downstream)
        summary["tables_with_tasks"] += int(row.get("tables_with_tasks") or 0)
        summary["tables_with_runs"] += int(row.get("tables_with_runs") or 0)
        summary["tables_with_data_source"] += int(row.get("tables_with_data_source") or 0)
    table_count = summary["table_count"]
    summary["ratios"] = {
        "fields": _coverage_ratio(summary["tables_with_columns"], table_count),
        "quality": _coverage_ratio(summary["tables_with_quality_rules"], table_count),
        "lineage": _coverage_ratio(summary["tables_with_lineage"], table_count),
        "tasks": _coverage_ratio(summary["tables_with_tasks"], table_count),
        "runs": _coverage_ratio(summary["tables_with_runs"], table_count),
        "data_source": _coverage_ratio(summary["tables_with_data_source"], table_count),
    }
    return summary
```

- [ ] **Step 5: Extend `get_asset_coverage()` SQL with run counts**

Replace the SQL inside `get_asset_coverage()` with this version, preserving the function name:

```python
layer_rows = self._all(
    """
    select
        coalesce(nullif(layer, ''), 'unknown') as layer,
        count(*) as table_count,
        sum(case when c.column_count > 0 then 1 else 0 end) as tables_with_columns,
        sum(case when q.rule_count > 0 then 1 else 0 end) as tables_with_quality_rules,
        sum(case when d.downstream_count > 0 then 1 else 0 end) as tables_with_downstream,
        sum(case when u.upstream_count > 0 then 1 else 0 end) as tables_with_upstream,
        sum(case when tt.task_count > 0 then 1 else 0 end) as tables_with_tasks,
        sum(case when r.run_count > 0 then 1 else 0 end) as tables_with_runs,
        sum(case when data_source_id != '' then 1 else 0 end) as tables_with_data_source
    from tables t
    left join (select table_name, count(*) as column_count from columns group by table_name) c on c.table_name = t.name
    left join (select table_name, count(*) as rule_count from quality_rules group by table_name) q on q.table_name = t.name
    left join (select upstream, count(*) as downstream_count from lineage group by upstream) d on d.upstream = t.name
    left join (select downstream, count(*) as upstream_count from lineage group by downstream) u on u.downstream = t.name
    left join (select table_name, count(distinct task_id) as task_count from task_tables group by table_name) tt on tt.table_name = t.name
    left join (
        select tt.table_name, count(distinct tr.instance_id) as run_count
        from task_tables tt
        join task_runs tr on tr.task_id = tt.task_id
        where tt.direction = 'output'
        group by tt.table_name
    ) r on r.table_name = t.name
    group by coalesce(nullif(layer, ''), 'unknown')
    order by case coalesce(nullif(layer, ''), 'unknown') when 'ods' then 1 when 'dim' then 2 when 'dwd' then 3 when 'dws' then 4 when 'mid' then 5 when 'ads' then 6 else 9 end, layer
    """
)
```

Then replace the return block with:

```python
rows = [dict(row) for row in layer_rows]
warehouse_rows = [row for row in rows if row.get("layer") in WAREHOUSE_LAYER_SET]
unknown_rows = [row for row in rows if row.get("layer") not in WAREHOUSE_LAYER_SET]
return {
    "totals": totals,
    "layers": rows,
    "warehouse_layers": list(WAREHOUSE_LAYERS),
    "warehouse_coverage": _coverage_summary(warehouse_rows),
    "unknown_pool": _coverage_summary(unknown_rows),
    "coverage_notes": [
        "主覆盖率按有效数仓层 ods/dim/dwd/dws/mid/ads 统计。",
        "unknown 不计入主覆盖率，但仍作为治理缺口单独展示。",
        "运行实例关联只统计 output 产出任务的 task_runs。",
    ],
}
```

- [ ] **Step 6: Update MCP coverage formatting**

In `dlc_mcp/mcp.py`, replace the `if tool_name == "get_asset_coverage":` block with:

```python
if tool_name == "get_asset_coverage":
    totals = data.get("totals", {})
    warehouse = data.get("warehouse_coverage", {})
    unknown = data.get("unknown_pool", {})
    ratios = warehouse.get("ratios", {})
    return "\n\n".join(
        [
            _section("资产覆盖率", ["按已同步表资产统计。"]),
            _table("资产类型 数量".split(), [[_count_label(k), v] for k, v in totals.items()]),
            _section(
                "有效数仓覆盖",
                [
                    f"数仓层：{', '.join(data.get('warehouse_layers') or [])}",
                    f"表数：{warehouse.get('table_count', 0)}",
                    f"字段：{ratios.get('fields', 0):.1%}",
                    f"血缘：{ratios.get('lineage', 0):.1%}",
                    f"任务映射：{ratios.get('tasks', 0):.1%}",
                    f"运行实例关联：{ratios.get('runs', 0):.1%}",
                    f"数据源：{ratios.get('data_source', 0):.1%}",
                ],
            ),
            _section(
                "unknown 资产池",
                [
                    f"表数：{unknown.get('table_count', 0)}",
                    f"有字段：{unknown.get('tables_with_columns', 0)}",
                    f"有血缘：{unknown.get('tables_with_lineage', 0)}",
                    f"有关联任务：{unknown.get('tables_with_tasks', 0)}",
                    f"有运行实例：{unknown.get('tables_with_runs', 0)}",
                    "unknown 不计入主覆盖率，但仍作为治理缺口追踪。",
                ],
            ),
            _table(
                ["层级", "表数", "有字段", "有质量规则", "有下游", "有上游", "有关联任务", "有运行实例", "有数据源"],
                [
                    [
                        r.get("layer"),
                        r.get("table_count"),
                        _ratio(r.get("tables_with_columns"), r.get("table_count")),
                        _ratio(r.get("tables_with_quality_rules"), r.get("table_count")),
                        _ratio(r.get("tables_with_downstream"), r.get("table_count")),
                        _ratio(r.get("tables_with_upstream"), r.get("table_count")),
                        _ratio(r.get("tables_with_tasks"), r.get("table_count")),
                        _ratio(r.get("tables_with_runs"), r.get("table_count")),
                        _ratio(r.get("tables_with_data_source"), r.get("table_count")),
                    ]
                    for r in data.get("layers", [])
                ],
            ),
            _section("说明", data.get("coverage_notes") or []),
        ]
    )
```

- [ ] **Step 7: Run coverage tests**

Run:

```bash
python -m pytest tests/test_assets.py::AssetsTest::test_asset_coverage_reports_warehouse_and_unknown_pool_separately tests/test_mcp.py::McpTest::test_get_asset_coverage_formats_warehouse_and_unknown_sections -v
```

Expected: both tests pass. If class names differ, run `python -m pytest tests/test_assets.py tests/test_mcp.py -k "asset_coverage or get_asset_coverage_formats" -v` and use the actual class names reported by pytest.

- [ ] **Step 8: Commit Task 2**

```bash
git add dlc_mcp/assets.py dlc_mcp/mcp.py tests/test_assets.py tests/test_mcp.py
git commit -m "Report warehouse coverage separately from unknown assets"
```

---

### Task 3: Strengthen Task Input/Output Table Parsing

**Files:**
- Modify: `dlc_mcp/wedata.py:181-246`
- Test: `tests/test_wedata_import.py`

**Interfaces:**
- Consumes: `_task_table_names(item: dict, direction: str) -> list[str]`, `_table_names_from_value(value: object) -> list[str]`, `_sql_table_names(sql: str, direction: str) -> list[str]`.
- Produces: broader input/output field parsing while preserving no-fake-table behavior.

- [ ] **Step 1: Write failing tests for new aliases and nested resources**

Append these tests to `tests/test_wedata_import.py`:

```python
def test_task_table_parser_reads_additional_aliases_and_nested_resources(self):
    snapshot = snapshot_from_api_dump(
        {
            "tasks": {
                "Response": {
                    "Data": {
                        "Items": [
                            {
                                "TaskId": "task_mid",
                                "TaskName": "build_ads_from_mid",
                                "Reads": '[{"TableName":"mid_customer_profile_di"}]',
                                "Writes": {"Tables": [{"DbTableName": "mart.ads_customer_profile_di"}]},
                            },
                            {
                                "TaskId": "task_resource",
                                "TaskName": "build_mid_from_dwd",
                                "SourceTableList": [{"Name": "dwd_customer_profile_di"}],
                                "Resources": [{"ResourceName": "warehouse.mid_customer_profile_di"}],
                            },
                        ]
                    }
                }
            }
        }
    )

    self.assertEqual(snapshot["tasks"][0]["inputs"], ["mid_customer_profile_di"])
    self.assertEqual(snapshot["tasks"][0]["outputs"], ["ads_customer_profile_di"])
    self.assertEqual(snapshot["tasks"][1]["inputs"], ["dwd_customer_profile_di"])
    self.assertEqual(snapshot["tasks"][1]["outputs"], ["mid_customer_profile_di"])


def test_sql_parser_handles_mid_outputs_and_filters_ctes(self):
    snapshot = snapshot_from_api_dump(
        {
            "tasks": {
                "Response": {
                    "Data": {
                        "Items": [
                            {
                                "TaskId": "task_sql_mid",
                                "TaskName": "build_mid_revenue",
                                "Sql": """
                                with recent_orders as (
                                    select * from ods_order_di
                                )
                                insert overwrite table mid_revenue_di
                                select * from recent_orders join dwd_customer_di on recent_orders.customer_id = dwd_customer_di.id
                                """,
                            }
                        ]
                    }
                }
            }
        }
    )

    self.assertEqual(snapshot["tasks"][0]["outputs"], ["mid_revenue_di"])
    self.assertEqual(snapshot["tasks"][0]["inputs"], ["ods_order_di", "dwd_customer_di"])
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
python -m pytest tests/test_wedata_import.py::WedataImportTest::test_task_table_parser_reads_additional_aliases_and_nested_resources tests/test_wedata_import.py::WedataImportTest::test_sql_parser_handles_mid_outputs_and_filters_ctes -v
```

Expected: alias or `mid` parsing fails before implementation.

- [ ] **Step 3: Extend field aliases**

In `dlc_mcp/wedata.py`, update `INPUT_TABLE_FIELDS` to include:

```python
"Reads",
"ReadTables",
"ReadTableList",
"DependencyTables",
"DependencyTableList",
```

Update `OUTPUT_TABLE_FIELDS` to include:

```python
"Writes",
"WriteTables",
"WriteTableList",
"SinkTables",
"SinkTableList",
"Resource",
"Resources",
```

If a name already exists, keep one copy only.

- [ ] **Step 4: Make named config direction-aware and recursive**

Replace `_table_names_from_named_config()` with:

```python
def _table_names_from_named_config(config, direction):
    if not isinstance(config, list):
        return []
    wanted = {
        "input": {"InputTables", "InputTableList", "SourceTables", "ReadTables", "DependencyTables", "TableNames", "TableName"},
        "output": {"OutputTables", "OutputTableList", "TargetTables", "WriteTables", "SinkTables", "Resource", "Resources", "TableNames", "TableName"},
    }[direction]
    names = []
    for item in config:
        if not isinstance(item, dict):
            continue
        key = str(item.get("Name") or item.get("Key") or "")
        if key in wanted:
            names.extend(_table_names_from_value(item.get("Value")))
    return names
```

- [ ] **Step 5: Make dictionary table-name parsing collect all matching fields**

Replace the dict branch inside `_table_names_from_value()` with:

```python
if isinstance(value, dict):
    names = []
    for field in TABLE_NAME_FIELDS:
        if value.get(field):
            names.extend(_table_names_from_value(value[field]))
    for field in INPUT_TABLE_FIELDS + OUTPUT_TABLE_FIELDS + ("Items", "List", "Tables", "tables", "Resources", "Resource", "Config"):
        if field in value:
            names.extend(_table_names_from_value(value[field]))
    return names
```

This collects nested table fields instead of returning after the first match.

- [ ] **Step 6: Filter CTE names from SQL input parsing**

Add this helper near `_sql_table_names()`:

```python
def _cte_names(sql):
    names = set()
    for match in re.finditer(r"\bwith\s+([`\w.]+)\s+as\s*\(", sql, flags=re.IGNORECASE):
        name = _normalize_table_name(match.group(1))
        if name:
            names.add(name)
    for match in re.finditer(r",\s*([`\w.]+)\s+as\s*\(", sql, flags=re.IGNORECASE):
        name = _normalize_table_name(match.group(1))
        if name:
            names.add(name)
    return names
```

In `_sql_table_names()`, after `text = _strip_sql_comments(sql)`, add:

```python
cte_names = _cte_names(text)
```

Change the append condition to:

```python
if name and name not in cte_names and not _is_sql_keyword_name(name):
    names.append(name)
```

- [ ] **Step 7: Run parser tests**

Run:

```bash
python -m pytest tests/test_wedata_import.py::WedataImportTest::test_task_table_parser_reads_additional_aliases_and_nested_resources tests/test_wedata_import.py::WedataImportTest::test_sql_parser_handles_mid_outputs_and_filters_ctes tests/test_wedata_import.py::WedataImportTest::test_layer_named_task_does_not_create_table_asset -v
```

Expected: all pass, including the existing no-fake-table regression.

- [ ] **Step 8: Commit Task 3**

```bash
git add dlc_mcp/wedata.py tests/test_wedata_import.py
git commit -m "Improve task table parsing for coverage"
```

---

### Task 4: Classify Run Coverage Gaps by Output Task Availability

**Files:**
- Modify: `dlc_mcp/assets.py:1102-1162`, `dlc_mcp/assets.py:1203-1249`, `dlc_mcp/assets.py:2800-2809`, `dlc_mcp/assets.py:3341-3375`
- Modify: `dlc_mcp/mcp.py:765-798`
- Test: `tests/test_assets.py`
- Test: `tests/test_mcp.py`

**Interfaces:**
- Consumes: existing `task_tables.direction` values `input` and `output`.
- Produces: row fields `producer_task_count`, `run_gap_reason`, and gap keys `producer_tasks` / `runs`.

- [ ] **Step 1: Write failing assets test for run gap reasons**

Append this test to `tests/test_assets.py`:

```python
def test_coverage_gaps_distinguish_missing_producer_from_missing_runs(self):
    store = make_store()
    store.upsert_table({"name": "ads_has_only_input", "layer": "ads", "data_source_id": "DLC"})
    store.upsert_table({"name": "ads_has_output_no_run", "layer": "ads", "data_source_id": "DLC"})
    store.upsert_table({"name": "ads_has_output_run", "layer": "ads", "data_source_id": "DLC"})
    store.upsert_task({"id": "consumer", "name": "consumer", "inputs": ["ads_has_only_input"]})
    store.upsert_task({"id": "producer_no_run", "name": "producer_no_run", "outputs": ["ads_has_output_no_run"]})
    store.upsert_task({"id": "producer_run", "name": "producer_run", "outputs": ["ads_has_output_run"]})
    store.upsert_task_run({"task_id": "producer_run", "instance_id": "run_1", "instance_date": "2026-07-13", "status": "COMPLETED"})

    gaps = store.list_asset_coverage_gaps("runs", "ads", 20)["results"]
    by_name = {row["name"]: row for row in gaps}

    self.assertEqual(by_name["ads_has_only_input"]["producer_task_count"], 0)
    self.assertEqual(by_name["ads_has_only_input"]["run_gap_reason"], "missing_producer_task")
    self.assertIn("缺产出任务", by_name["ads_has_only_input"]["gaps"])
    self.assertEqual(by_name["ads_has_output_no_run"]["producer_task_count"], 1)
    self.assertEqual(by_name["ads_has_output_no_run"]["run_gap_reason"], "missing_task_runs")
    self.assertIn("有产出任务但缺运行实例", by_name["ads_has_output_no_run"]["gaps"])
    self.assertNotIn("ads_has_output_run", by_name)
```

- [ ] **Step 2: Write failing MCP table test for producer task count and reason**

Append this test to `tests/test_mcp.py`:

```python
def test_coverage_gap_markdown_includes_producer_task_and_run_reason(self):
    store = AssetStore(sqlite3.connect(":memory:"))
    store.init_schema()
    store.upsert_table({"name": "ads_has_output_no_run", "layer": "ads", "data_source_id": "DLC"})
    store.upsert_task({"id": "producer_no_run", "name": "producer_no_run", "outputs": ["ads_has_output_no_run"]})

    text = format_tool_result("list_asset_coverage_gaps", store.list_asset_coverage_gaps("runs", "ads", 10))

    self.assertIn("产出任务", text)
    self.assertIn("运行实例缺口原因", text)
    self.assertIn("有产出任务但缺运行实例", text)
```

- [ ] **Step 3: Run tests and verify they fail**

Run:

```bash
python -m pytest tests/test_assets.py::AssetsTest::test_coverage_gaps_distinguish_missing_producer_from_missing_runs tests/test_mcp.py::McpTest::test_coverage_gap_markdown_includes_producer_task_and_run_reason -v
```

Expected: tests fail because producer count/reason is absent.

- [ ] **Step 4: Add producer task counts to coverage gap query**

In `list_asset_coverage_gaps()`, add this selected column after `task_count`:

```sql
coalesce(pt.producer_task_count, 0) as producer_task_count,
```

Add this join after the `tt` join:

```sql
left join (select table_name, count(distinct task_id) as producer_task_count from task_tables where direction = 'output' group by table_name) pt on pt.table_name = t.name
```

When building each `item`, after `item = dict(row)`, add:

```python
item["run_gap_reason"] = _run_gap_reason(item)
```

- [ ] **Step 5: Add producer task counts to governance candidate query**

In `_governance_issue_candidates()`, add selected column:

```sql
coalesce(pt.producer_task_count, 0) as producer_task_count,
```

Add join:

```sql
left join (select table_name, count(distinct task_id) as producer_task_count from task_tables where direction = 'output' group by table_name) pt on pt.table_name = t.name
```

- [ ] **Step 6: Add run gap helpers and labels**

Near `_coverage_gaps()`, add:

```python
def _run_gap_reason(row):
    if int(row.get("run_count") or 0) > 0:
        return ""
    if int(row.get("producer_task_count") or 0) == 0:
        return "missing_producer_task"
    return "missing_task_runs"
```

Modify `_coverage_gaps()` so the run section becomes:

```python
if int(row.get("task_count") or 0) == 0:
    gaps.append("tasks")
if int(row.get("producer_task_count") or 0) == 0:
    gaps.append("producer_tasks")
if int(row.get("run_count") or 0) == 0:
    gaps.append("runs")
```

Update `_gap_label()` labels with:

```python
"producer_tasks": "缺产出任务",
"runs": "有产出任务但缺运行实例",
```

Update `supported_gap_types` in `list_asset_coverage_gaps()` to include `producer_tasks` before `runs`.

Update `_normalize_gap_type()` alias map with:

```python
"producer": "producer_tasks",
"producer_task": "producer_tasks",
"producer_tasks": "producer_tasks",
"output_task": "producer_tasks",
"output_tasks": "producer_tasks",
```

- [ ] **Step 7: Update governance missing run issue root cause**

Replace the `elif int(table.get("run_count") or 0) == 0:` block in `_governance_issues_for_table()` with:

```python
    elif int(table.get("producer_task_count") or 0) == 0:
        issues.append(_governance_issue(table, "missing_task_mapping", "producer_mapping_gap", "Check task outputs and SQL table-name normalization for this table."))
    elif int(table.get("run_count") or 0) == 0:
        issues.append(_governance_issue(table, "missing_task_runs", "instance_window_gap", "Check ListTaskInstances time window, max pages, and task_id alignment."))
```

In `_governance_issue()`, add evidence field:

```python
"producer_task_count": int(table.get("producer_task_count") or 0),
```

- [ ] **Step 8: Update MCP gap table columns**

In `dlc_mcp/mcp.py`, replace the table header for `list_asset_coverage_gaps` with:

```python
["表名", "层级", "负责人", "字段", "质量规则", "上游", "下游", "任务", "产出任务", "运行实例", "运行实例缺口原因", "数据源", "缺口"]
```

Replace each row with:

```python
[
    r.get("name"),
    r.get("layer"),
    r.get("owner"),
    r.get("column_count"),
    r.get("quality_rule_count"),
    r.get("upstream_count"),
    r.get("downstream_count"),
    r.get("task_count"),
    r.get("producer_task_count"),
    r.get("run_count"),
    _run_gap_reason_label(r.get("run_gap_reason")),
    r.get("data_source_id"),
    "、".join(r.get("gaps") or []),
]
```

Add this formatter helper near `_cell()` or `_gap` helpers:

```python
def _run_gap_reason_label(reason):
    labels = {
        "missing_producer_task": "缺产出任务",
        "missing_task_runs": "有产出任务但缺运行实例",
    }
    return labels.get(reason or "", "")
```

- [ ] **Step 9: Run run-gap tests**

Run:

```bash
python -m pytest tests/test_assets.py::AssetsTest::test_coverage_gaps_distinguish_missing_producer_from_missing_runs tests/test_mcp.py::McpTest::test_coverage_gap_markdown_includes_producer_task_and_run_reason -v
```

Expected: both tests pass.

- [ ] **Step 10: Commit Task 4**

```bash
git add dlc_mcp/assets.py dlc_mcp/mcp.py tests/test_assets.py tests/test_mcp.py
git commit -m "Classify output task run coverage gaps"
```

---

### Task 5: Add Sync Window Transparency to Sync Health

**Files:**
- Modify: `dlc_mcp/assets.py` around `get_sync_health()`
- Modify: `dlc_mcp/mcp.py` sync-health formatter if one exists
- Test: `tests/test_assets.py`
- Test: `tests/test_mcp.py` if sync health has Markdown assertions

**Interfaces:**
- Consumes: environment variables `WEDATA_INSTANCE_START`, `WEDATA_INSTANCE_END`, `WEDATA_INSTANCE_TIMEZONE`, `WEDATA_INSTANCE_KEYWORDS`, `DLC_MCP_TASK_RUN_RETENTION_DAYS`.
- Produces: `get_sync_health()["task_run_window"]` dictionary.

- [ ] **Step 1: Locate `get_sync_health()`**

Run:

```bash
rg -n "def get_sync_health|sync_health|task_run_retention" dlc_mcp/assets.py dlc_mcp/mcp.py tests
```

Expected: find `AssetStore.get_sync_health()` and any MCP formatting for `get_sync_health`.

- [ ] **Step 2: Write failing sync-health test**

Append this test to `tests/test_assets.py`:

```python
def test_sync_health_exposes_task_run_window(self):
    store = make_store()
    with patch.dict(
        os.environ,
        {
            "WEDATA_INSTANCE_START": "2026-07-13 00:00:00",
            "WEDATA_INSTANCE_END": "2026-07-13 23:59:59",
            "WEDATA_INSTANCE_TIMEZONE": "UTC+8",
            "WEDATA_INSTANCE_KEYWORDS": "daily",
            "DLC_MCP_TASK_RUN_RETENTION_DAYS": "7",
        },
    ):
        health = store.get_sync_health()

    self.assertEqual(
        health["task_run_window"],
        {
            "start": "2026-07-13 00:00:00",
            "end": "2026-07-13 23:59:59",
            "timezone": "UTC+8",
            "keywords": "daily",
            "retention_days": 7,
        },
    )
```

If `tests/test_assets.py` does not import `os` and `patch`, add:

```python
import os
from unittest.mock import patch
```

- [ ] **Step 3: Run test and verify it fails**

Run:

```bash
python -m pytest tests/test_assets.py::AssetsTest::test_sync_health_exposes_task_run_window -v
```

Expected: fails because `task_run_window` is absent.

- [ ] **Step 4: Add task run window helper**

In `dlc_mcp/assets.py`, add near other private helpers:

```python
def _task_run_window_from_env():
    return {
        "start": os.environ.get("WEDATA_INSTANCE_START", ""),
        "end": os.environ.get("WEDATA_INSTANCE_END", ""),
        "timezone": os.environ.get("WEDATA_INSTANCE_TIMEZONE", "UTC+8"),
        "keywords": os.environ.get("WEDATA_INSTANCE_KEYWORDS", ""),
        "retention_days": int(os.environ.get("DLC_MCP_TASK_RUN_RETENTION_DAYS", "7") or 7),
    }
```

If `dlc_mcp/assets.py` does not already import `os`, add:

```python
import os
```

- [ ] **Step 5: Return task run window from `get_sync_health()`**

Inside `get_sync_health()` return dictionary, add:

```python
"task_run_window": _task_run_window_from_env(),
```

Keep existing keys unchanged.

- [ ] **Step 6: Update MCP formatting if needed**

If `dlc_mcp/mcp.py` has a dedicated `get_sync_health` formatter, add these lines to its details section:

```python
window = data.get("task_run_window", {})
f"运行实例窗口：{_cell(window.get('start'))} ~ {_cell(window.get('end'))} ({_cell(window.get('timezone'))})",
f"实例关键词：{_cell(window.get('keywords'))}，保留天数：{window.get('retention_days', 0)}",
```

If there is no dedicated formatter and sync health falls back to JSON, leave MCP unchanged.

- [ ] **Step 7: Run sync-health test**

Run:

```bash
python -m pytest tests/test_assets.py::AssetsTest::test_sync_health_exposes_task_run_window -v
```

Expected: pass.

- [ ] **Step 8: Commit Task 5**

```bash
git add dlc_mcp/assets.py dlc_mcp/mcp.py tests/test_assets.py tests/test_mcp.py
git commit -m "Expose task run sync window"
```

If `dlc_mcp/mcp.py` or `tests/test_mcp.py` were not modified, omit them from `git add`.

---

### Task 6: Run Full Relevant Verification and Update Graph

**Files:**
- No source changes expected unless tests expose a regression.

**Interfaces:**
- Consumes: all tasks above.
- Produces: verified working tree and updated graph.

- [ ] **Step 1: Run focused test suite**

Run:

```bash
python -m pytest tests/test_wedata_import.py tests/test_diagnose_asset_gaps.py tests/test_assets.py tests/test_mcp.py -v
```

Expected: all selected tests pass.

- [ ] **Step 2: Run deploy script tests because working tree also has deploy-script changes**

Run:

```bash
python -m pytest tests/test_deploy_scripts.py -v
```

Expected: all deploy script tests pass.

- [ ] **Step 3: Run whole test suite if focused tests pass**

Run:

```bash
python -m pytest
```

Expected: all tests pass.

- [ ] **Step 4: Update code-review graph**

Run the MCP graph update tool with:

```json
{"repo_root":"/Users/leve/Documents/DLC-Agent","full_rebuild":false,"postprocess":"minimal","base":"HEAD","recurse_submodules":null}
```

Expected: graph update completes successfully.

- [ ] **Step 5: Inspect final git status**

Run:

```bash
git status --short
```

Expected: only intended source/test changes remain uncommitted, plus any pre-existing deploy sync script changes if they were not already committed before this plan execution.

- [ ] **Step 6: Commit verification changes if any task left source changes uncommitted**

If `git status --short` shows changes from this plan, commit them:

```bash
git add dlc_mcp/wedata.py dlc_mcp/diagnose_asset_gaps.py dlc_mcp/assets.py dlc_mcp/mcp.py tests/test_wedata_import.py tests/test_diagnose_asset_gaps.py tests/test_assets.py tests/test_mcp.py
git commit -m "Complete asset coverage remediation"
```

If there are no changes from this plan, skip this step.

---

## Self-Review Notes

- Spec coverage: Tasks 1-2 cover `mid`, valid warehouse coverage, and unknown pool. Task 3 covers task input/output parsing. Task 4 covers output-only run gap diagnostics. Task 5 covers sync-window transparency. Task 6 covers verification.
- Placeholder scan: no `TBD`, `TODO`, or unspecified implementation steps are intentionally left in this plan.
- Type consistency: new return keys are `warehouse_layers`, `warehouse_coverage`, `unknown_pool`, `producer_task_count`, `run_gap_reason`, and `task_run_window`; these names are used consistently across tasks.
