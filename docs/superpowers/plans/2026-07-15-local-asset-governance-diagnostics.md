# Local Asset Governance Diagnostics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enhance local data asset governance diagnostics so inferable `mid_*` assets stop being stranded in `unknown`, and task/run gaps explain the likely remediation path without requiring live Tencent Cloud credentials.

**Architecture:** Keep the existing SQLite-backed `AssetStore` and MCP response schema. Add a small local layer inference/repair method in `dlc_mcp/assets.py`, then reuse the same helper to make governance issue root causes and next checks more precise. Tests stay in `tests/test_assets.py` and exercise behavior through public `AssetStore` methods.

**Tech Stack:** Python 3, SQLite, unittest/pytest, existing `dlc_mcp.assets.AssetStore`.

## Global Constraints

- Do not implement or prioritize high-impact quality rule remediation in this work.
- Do not require `/etc/dlc-mcp/env`, Tencent Cloud credentials, or live WeData API calls.
- Preserve the top-level schema returned by `get_asset_governance_issue_inventory`.
- Only repair table layers when current `tables.layer` is empty or `unknown`; never overwrite existing `ods/dim/dwd/dws/mid/ads` values.
- Treat missing local facts as governance gaps, not as healthy states.

---

## File Structure

- Modify: `dlc_mcp/assets.py`
  - Add `AssetStore.refresh_inferred_layers()` near `upsert_table()` because it mutates rows in the `tables` table and belongs with table persistence methods.
  - Add helper functions near the existing governance helper section: `_infer_warehouse_layer()`, `_is_unknown_layer()`, `_has_inferable_layer()`, `_unknown_layer_issue_detail()`, `_missing_task_mapping_issue_detail()`, and `_missing_task_runs_issue_detail()`.
  - Update `_governance_issues_for_table()` to use those helpers while preserving existing issue object shape.
- Modify: `tests/test_assets.py`
  - Add tests under `AssetStoreTest` for layer repair.
  - Add tests under `AssetGovernanceIssueInventoryTest` for more specific root causes and next checks.
- No new production files.
- No live env files.

---

### Task 1: Add local layer inference repair

**Files:**
- Modify: `dlc_mcp/assets.py:521-573`
- Modify: `dlc_mcp/assets.py:2824-2920`
- Test: `tests/test_assets.py`

**Interfaces:**
- Consumes: existing `AssetStore.upsert_table(item: dict) -> None`, existing module constants `WAREHOUSE_LAYER_SET`.
- Produces: `AssetStore.refresh_inferred_layers() -> dict` returning `{"updated_count": int, "updated": list[dict]}`.
- Produces: `_infer_warehouse_layer(value: str) -> str` for later governance issue classification.

- [ ] **Step 1: Write failing tests for layer inference repair**

Add these methods inside `class AssetStoreTest(unittest.TestCase):` in `tests/test_assets.py`, after `test_table_detail_fields_are_cached`:

```python
    def test_refresh_inferred_layers_repairs_unknown_mid_tables(self):
        store = make_store()
        store.upsert_table({"name": "mid_crm_customer_df", "layer": "unknown", "owner": "tencent"})
        store.upsert_table({"name": "mid_sms_instance_bill_detail_di", "layer": "", "owner": "tencent"})

        result = store.refresh_inferred_layers()

        self.assertEqual(result["updated_count"], 2)
        self.assertEqual(
            {item["name"]: item["new_layer"] for item in result["updated"]},
            {
                "mid_crm_customer_df": "mid",
                "mid_sms_instance_bill_detail_di": "mid",
            },
        )
        self.assertEqual(store.get_table_detail(table_name="mid_crm_customer_df")["table"]["layer"], "mid")
        self.assertEqual(store.get_table_detail(table_name="mid_sms_instance_bill_detail_di")["table"]["layer"], "mid")

    def test_refresh_inferred_layers_does_not_overwrite_explicit_layers(self):
        store = make_store()
        store.upsert_table({"name": "mid_named_but_ads_owned", "layer": "ads", "owner": "tencent"})

        result = store.refresh_inferred_layers()

        self.assertEqual(result["updated_count"], 0)
        self.assertEqual(store.get_table_detail(table_name="mid_named_but_ads_owned")["table"]["layer"], "ads")
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
python3 -m pytest tests/test_assets.py::AssetStoreTest::test_refresh_inferred_layers_repairs_unknown_mid_tables tests/test_assets.py::AssetStoreTest::test_refresh_inferred_layers_does_not_overwrite_explicit_layers -q
```

Expected: FAIL with `AttributeError: 'AssetStore' object has no attribute 'refresh_inferred_layers'`.

- [ ] **Step 3: Implement layer inference helper and repair method**

In `dlc_mcp/assets.py`, add this method immediately after `upsert_table()` and before `upsert_column()`:

```python
    def refresh_inferred_layers(self):
        rows = self._all(
            """
            select name, layer
            from tables
            where coalesce(layer, '') = '' or layer = 'unknown'
            order by name
            """
        )
        updated = []
        for row in rows:
            inferred = _infer_warehouse_layer(row["name"])
            if not inferred:
                continue
            self.conn.execute(
                """
                update tables
                set layer = ?
                where name = ? and (coalesce(layer, '') = '' or layer = 'unknown')
                """,
                (inferred, row["name"]),
            )
            updated.append(
                {
                    "name": row["name"],
                    "old_layer": row["layer"] or "",
                    "new_layer": inferred,
                }
            )
        self.conn.commit()
        return {"updated_count": len(updated), "updated": updated}
```

In `dlc_mcp/assets.py`, add this module helper immediately before `_governance_issues_for_table(table)`:

```python
def _infer_warehouse_layer(value):
    text = str(value or "").lower().replace("-", "_").replace("/", "_").replace(".", "_")
    for part in [part for part in text.split("_") if part]:
        if part in WAREHOUSE_LAYER_SET:
            return part
    return ""
```

- [ ] **Step 4: Run tests and verify they pass**

Run:

```bash
python3 -m pytest tests/test_assets.py::AssetStoreTest::test_refresh_inferred_layers_repairs_unknown_mid_tables tests/test_assets.py::AssetStoreTest::test_refresh_inferred_layers_does_not_overwrite_explicit_layers -q
```

Expected: `2 passed`.

- [ ] **Step 5: Commit Task 1**

```bash
git add dlc_mcp/assets.py tests/test_assets.py
git commit -m "feat: repair inferred asset layers"
```

---

### Task 2: Enhance governance issue root-cause classification

**Files:**
- Modify: `dlc_mcp/assets.py:2824-2902`
- Test: `tests/test_assets.py`

**Interfaces:**
- Consumes: `_infer_warehouse_layer(value: str) -> str` from Task 1.
- Produces: unchanged `AssetStore.get_asset_governance_issue_inventory(layer='', core_level='', issue_type='', limit=100) -> dict` top-level schema.
- Produces root cause values: `layer_mapping_gap`, `parser_gap`, `producer_mapping_gap`, `producer_missing_gap`, `instance_window_gap`.

- [ ] **Step 1: Write failing tests for enhanced issue classification**

Add these methods inside `class AssetGovernanceIssueInventoryTest(unittest.TestCase):`, after `test_separates_missing_task_mapping_and_missing_task_runs`:

```python
    def test_unknown_layer_issue_identifies_inferable_mid_layer(self):
        store = self._store()
        store.upsert_table({"name": "mid_crm_customer_df", "layer": "unknown", "owner": "tencent"})

        data = store.get_asset_governance_issue_inventory(issue_type="unknown_layer")

        issue = data["results"][0]
        self.assertEqual(issue["asset_name"], "mid_crm_customer_df")
        self.assertEqual(issue["suspected_root_cause"], "layer_mapping_gap")
        self.assertIn("refresh_inferred_layers", issue["recommended_next_check"])

    def test_missing_task_mapping_prioritizes_inferable_layer_gap(self):
        store = self._store()
        store.upsert_table({"name": "mid_sms_instance_bill_detail_di", "layer": "unknown", "owner": "tencent"})
        store.upsert_task({"id": "task_input", "name": "consume_mid_sms", "inputs": ["mid_sms_instance_bill_detail_di"]})

        data = store.get_asset_governance_issue_inventory(issue_type="missing_task_mapping")

        issue = data["results"][0]
        self.assertEqual(issue["asset_name"], "mid_sms_instance_bill_detail_di")
        self.assertEqual(issue["suspected_root_cause"], "layer_mapping_gap")
        self.assertIn("unknown", issue["recommended_next_check"])

    def test_missing_task_runs_reports_producer_missing_before_instance_window(self):
        store = self._store()
        store.upsert_table({"name": "ads_has_consumer_no_producer", "layer": "ads", "owner": "tencent"})
        store.upsert_task({"id": "task_consumer", "name": "consume_ads", "inputs": ["ads_has_consumer_no_producer"]})

        data = store.get_asset_governance_issue_inventory(issue_type="missing_task_runs")

        issue = data["results"][0]
        self.assertEqual(issue["asset_name"], "ads_has_consumer_no_producer")
        self.assertEqual(issue["suspected_root_cause"], "producer_missing_gap")
        self.assertIn("producer", issue["recommended_next_check"])
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
python3 -m pytest tests/test_assets.py::AssetGovernanceIssueInventoryTest::test_unknown_layer_issue_identifies_inferable_mid_layer tests/test_assets.py::AssetGovernanceIssueInventoryTest::test_missing_task_mapping_prioritizes_inferable_layer_gap tests/test_assets.py::AssetGovernanceIssueInventoryTest::test_missing_task_runs_reports_producer_missing_before_instance_window -q
```

Expected: FAIL because current root causes are `manual_mapping_needed` / `producer_mapping_gap`, and no `missing_task_runs` issue is emitted when producer mapping is missing.

- [ ] **Step 3: Add governance issue classification helpers**

In `dlc_mcp/assets.py`, replace the current `_governance_issues_for_table(table)` function and add helper functions immediately before it:

```python
def _is_unknown_layer(table):
    return table.get("layer") in ("", "unknown")


def _has_inferable_layer(table):
    return bool(_infer_warehouse_layer(table.get("name", "")))


def _unknown_layer_issue_detail(table):
    if _has_inferable_layer(table):
        return (
            "layer_mapping_gap",
            "Run AssetStore.refresh_inferred_layers or re-import metadata so inferable table names are not left as unknown.",
        )
    return (
        "manual_mapping_needed",
        "Inspect raw ListTable fields and table naming rules for layer inference.",
    )


def _missing_task_mapping_issue_detail(table):
    if _is_unknown_layer(table) and _has_inferable_layer(table):
        return (
            "layer_mapping_gap",
            "Repair the unknown layer first with refresh_inferred_layers, then re-check producer task mapping.",
        )
    if int(table.get("task_count") or 0) == 0:
        return (
            "parser_gap",
            "Check raw task inputs/outputs, SQL table-name normalization, and whether the table appears under a database-qualified name.",
        )
    return (
        "producer_mapping_gap",
        "Check task outputs, SQL INSERT/CREATE statements, and table-name normalization for this table.",
    )


def _missing_task_runs_issue_detail(table):
    if int(table.get("producer_task_count") or 0) == 0:
        return (
            "producer_missing_gap",
            "Fix producer task mapping before judging task runs; no output task is currently linked to this table.",
        )
    if _is_unknown_layer(table):
        return (
            "unknown_layer_gap",
            "Repair unknown layer classification, then check ListTaskInstances time window, max pages, and task_id alignment.",
        )
    return (
        "instance_window_gap",
        "Check ListTaskInstances time window, max pages, WEDATA_INSTANCE_KEYWORDS, and task_id alignment.",
    )


def _governance_issues_for_table(table):
    issues = []
    if _is_unknown_layer(table):
        root_cause, next_check = _unknown_layer_issue_detail(table)
        issues.append(_governance_issue(table, "unknown_layer", root_cause, next_check))
    if int(table.get("quality_rule_count") or 0) == 0:
        issues.append(_governance_issue(table, "missing_quality_rules", "source_governance_gap", "Compare raw quality rules with DB rules for this table."))
    if int(table.get("task_count") or 0) == 0:
        root_cause, next_check = _missing_task_mapping_issue_detail(table)
        issues.append(_governance_issue(table, "missing_task_mapping", root_cause, next_check))
    elif int(table.get("producer_task_count") or 0) == 0:
        root_cause, next_check = _missing_task_mapping_issue_detail(table)
        issues.append(_governance_issue(table, "missing_task_mapping", root_cause, next_check))
        run_root_cause, run_next_check = _missing_task_runs_issue_detail(table)
        issues.append(_governance_issue(table, "missing_task_runs", run_root_cause, run_next_check))
    elif int(table.get("run_count") or 0) == 0:
        root_cause, next_check = _missing_task_runs_issue_detail(table)
        issues.append(_governance_issue(table, "missing_task_runs", root_cause, next_check))
    if not table.get("data_source_id"):
        issues.append(_governance_issue(table, "missing_data_source", "source_metadata_gap", "Check ListTable data source fields and data source sync coverage."))
    if not table.get("owner"):
        issues.append(_governance_issue(table, "missing_owner", "owner_governance_gap", "Ask table owner or warehouse owner to confirm responsibility."))
    if _profile_incomplete(table):
        issues.append(_governance_issue(table, "profile_incomplete", "profile_coverage_gap", "Prioritize missing profile facts by issue inventory entries."))
    return issues
```

- [ ] **Step 4: Run focused tests and verify they pass**

Run:

```bash
python3 -m pytest tests/test_assets.py::AssetGovernanceIssueInventoryTest -q
```

Expected: all `AssetGovernanceIssueInventoryTest` tests pass.

- [ ] **Step 5: Run broader asset tests**

Run:

```bash
python3 -m pytest tests/test_assets.py -q
```

Expected: all tests in `tests/test_assets.py` pass.

- [ ] **Step 6: Commit Task 2**

```bash
git add dlc_mcp/assets.py tests/test_assets.py
git commit -m "feat: explain asset governance gaps"
```

---

### Task 3: Verify current local governance output and document the result

**Files:**
- Modify: none required unless verification reveals a defect.
- Test: local MCP/data calls and pytest.

**Interfaces:**
- Consumes: `AssetStore.refresh_inferred_layers() -> dict` from Task 1.
- Consumes: enhanced `get_asset_governance_issue_inventory()` from Task 2.
- Produces: verification summary in the implementation response; no production API change.

- [ ] **Step 1: Run full relevant tests**

Run:

```bash
python3 -m pytest tests/test_assets.py tests/test_wedata_import.py tests/test_sync_wedata.py -q
```

Expected: all selected tests pass.

- [ ] **Step 2: Run a local smoke check against the existing SQLite DB**

Run:

```bash
python3 - <<'PY'
import sqlite3
from dlc_mcp.assets import AssetStore

store = AssetStore(sqlite3.connect('data/assets.db'))
store.init_schema()
print('before', store.get_asset_governance_issue_inventory(issue_type='unknown_layer', limit=5)['results'][:2])
result = store.refresh_inferred_layers()
print('repair', result['updated_count'], result['updated'][:10])
print('after', store.get_asset_governance_issue_inventory(issue_type='unknown_layer', limit=5)['results'][:2])
print('task_mapping', store.get_asset_governance_issue_inventory(issue_type='missing_task_mapping', limit=3)['results'])
print('task_runs', store.get_asset_governance_issue_inventory(issue_type='missing_task_runs', limit=3)['results'])
PY
```

Expected:
- The script runs without Tencent Cloud credentials.
- `repair` prints an integer count and a sample list.
- Any remaining `unknown_layer` issues have root causes that distinguish inferable layer gaps from manual mapping gaps.
- `missing_task_mapping` and `missing_task_runs` samples include the enhanced `suspected_root_cause` and `recommended_next_check` values.

- [ ] **Step 3: If the smoke check mutates `data/assets.db`, inspect git status**

Run:

```bash
git status --short
```

Expected:
- Source/test files are clean after commits.
- If `data/assets.db` is tracked and changed, do not commit it unless the project already expects DB fixture updates for this change.

- [ ] **Step 4: If `data/assets.db` should not be committed, revert only the DB file**

Run only if `git status --short` shows `data/assets.db` modified and the project does not expect DB fixture updates:

```bash
git checkout -- data/assets.db
```

Expected: the DB mutation from the smoke check is removed from the working tree.

- [ ] **Step 5: Commit any remaining verification-only doc/test adjustment**

If Task 3 required no source or test changes, skip this step. If it required a small fix, commit that exact fix:

```bash
git add dlc_mcp/assets.py tests/test_assets.py
git commit -m "test: verify local governance diagnostics"
```

Expected: either no commit is needed, or the commit contains only the verification fix.

---

## Self-Review

- Spec coverage: Task 1 covers `mid_*` layer repair and non-overwrite behavior. Task 2 covers enhanced `missing_task_mapping` and `missing_task_runs` root causes while preserving response schema. Task 3 covers local verification without live credentials and excludes quality-rule remediation.
- Placeholder scan: No TBD/TODO/fill-in placeholders remain. Conditional steps specify exact commands and skip conditions.
- Type consistency: `refresh_inferred_layers()` return type is consistent across tasks. Root cause strings used in tests match implementation snippets.
