# Partition Sync Live Fallback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make partition profiles reliable by keeping DLC partition sync table-based instead of yesterday-`dt`-based, and adding live partition refresh fallback for cache misses.

**Architecture:** Keep `table_partitions` as the fast cache. For DLC `DescribeTablePartitions`, daily sync stores every partition returned for each partitioned table and lets DB upsert deduplicate; `partition_date` becomes a query-focus parameter only. MCP live mode refreshes partition facts for a single table via DLC when the cache is missing or stale enough to be unusable.

**Tech Stack:** Python stdlib, SQLite via `AssetStore`, existing Tencent Cloud client wrapper, existing MCP stdio/gateway formatting, pytest/unittest tests.

## Global Constraints

- Use code-review-graph before direct file exploration when more structural context is needed.
- Do not treat `ListTablePartitions InvalidAction` as a parameter problem; keep it classified as action/version unsupported.
- Keep existing WeData partition-service behavior unless a task explicitly changes DLC-only behavior.
- Do not remove the `table_partitions` cache; cache remains primary and live refresh is fallback.
- `partition_date` means target partition for profile display/health only, not a destructive filter for DLC sync results.

---

## File Structure

- Modify `dlc_mcp/sync_wedata.py`
  - Owns batch partition sync, partition payloads, pagination, partition filtering behavior, and helpers reused by live refresh.
  - Change DLC sync so `incremental` stores all returned partitions; keep WeData service date filtering unchanged.
- Modify `dlc_mcp/live.py`
  - Add `LiveWeData.sync_table_partitions(table_name)` for single-table DLC refresh and cache import.
- Modify `dlc_mcp/mcp.py`
  - Wire `get_table_partition_profile(live=true)` to `LiveWeData.sync_table_partitions()` when requested or when cache has missing facts for a partitioned table.
  - Preserve query metadata output.
- Modify `tests/test_sync_wedata.py`
  - Update tests for DLC incremental semantics and keep non-DLC date filtering tests.
- Modify `tests/test_mcp.py`
  - Add MCP live fallback test for partition profile.
- Modify `tests/test_wedata_import.py` or `tests/test_assets.py` only if an importer/cache assertion needs to be made explicit; prefer existing coverage if already present.
- Optionally modify `docs/server-mcp-wedata-flow.md`
  - Update operator-facing semantics after code/tests pass.

---

### Task 1: Make DLC partition sync keep all returned partitions

**Files:**
- Modify: `dlc_mcp/sync_wedata.py:564-598`
- Modify: `tests/test_sync_wedata.py:553-565`
- Modify: `tests/test_sync_wedata.py:627-640`

**Interfaces:**
- Consumes: `_sync_partitions(client, project_id, table_names, page_size, progress_every=10, catalog_tables=None)` existing signature.
- Produces: DLC `_sync_partitions()` returns all `_partition_items(response)` tagged with `QueriedTableName`, regardless of `WEDATA_PARTITION_DATE` or `_partition_sync_mode()`; non-DLC behavior continues to filter by `partition_matches_date(item, partition_date)`.

- [ ] **Step 1: Update the DLC incremental failing test expectation**

In `tests/test_sync_wedata.py`, replace `test_dlc_incremental_partition_sync_defaults_to_yesterday` with this test:

```python
    def test_dlc_incremental_partition_sync_keeps_all_returned_partitions(self):
        with patch.dict(os.environ, {"WEDATA_PARTITION_SERVICE": "dlc", "DLC_CATALOG": "DataLakeCatalog", "WEDATA_PARTITION_SYNC_MODE": "incremental"}, clear=False), patch("dlc_mcp.sync_wedata._partition_client", return_value=FakeDlcPartitionClient()), patch("dlc_mcp.sync_wedata.date") as fake_date:
            fake_date.today.return_value = datetime(2026, 7, 9).date()
            response = _sync_partitions(
                FakePartitionClient(),
                "project",
                ["ads_revenue"],
                1,
                progress_every=0,
                catalog_tables={"ads_revenue": {"DatabaseName": "ads_mart"}},
            )

        self.assertEqual([item["Partition"] for item in response["Response"]["Data"]["Items"]], ["dt=20260708", "dt=20260709"])
        self.assertTrue(all(item["QueriedTableName"] == "ads_revenue" for item in response["Response"]["Data"]["Items"]))
```

- [ ] **Step 2: Update DLC mixed stats test expectation**

In `tests/test_sync_wedata.py`, update `test_dlc_partition_sync_reads_mixed_partition_stats` assertions to expect both paged items:

```python
        items = response["Response"]["Data"]["Items"]
        self.assertEqual(len(items), 2)
        self.assertEqual([item["Partition"] for item in items], ["dt=20260708", "dt=20260709"])
        self.assertEqual(items[0]["QueriedTableName"], "ads_revenue")
        self.assertEqual(items[0]["Records"], 10)
```

- [ ] **Step 3: Run the targeted tests and verify they fail before implementation**

Run:

```bash
pytest tests/test_sync_wedata.py::SyncWeDataTest::test_dlc_incremental_partition_sync_keeps_all_returned_partitions tests/test_sync_wedata.py::SyncWeDataTest::test_dlc_partition_sync_reads_mixed_partition_stats -v
```

Expected before implementation: failures showing only `dt=20260708` was returned under DLC incremental/date filtering.

- [ ] **Step 4: Implement DLC-only keep-all behavior**

In `dlc_mcp/sync_wedata.py`, replace the item append block inside `_sync_partitions()`:

```python
        for item in _partition_items(response):
            item["QueriedTableName"] = table_name
            if partition_matches_date(item, partition_date):
                items.append(item)
```

with:

```python
        keep_all_partitions = os.environ.get("WEDATA_PARTITION_SERVICE", "wedata") == "dlc"
        for item in _partition_items(response):
            item["QueriedTableName"] = table_name
            if keep_all_partitions or partition_matches_date(item, partition_date):
                items.append(item)
```

Keep the existing block that only adds `PartitionDate` to non-DLC payloads:

```python
        if partition_date and os.environ.get("WEDATA_PARTITION_SERVICE", "wedata") != "dlc":
            payload["PartitionDate"] = partition_date
```

- [ ] **Step 5: Verify targeted tests pass**

Run:

```bash
pytest tests/test_sync_wedata.py::SyncWeDataTest::test_dlc_full_partition_sync_keeps_all_partitions tests/test_sync_wedata.py::SyncWeDataTest::test_dlc_incremental_partition_sync_keeps_all_returned_partitions tests/test_sync_wedata.py::SyncWeDataTest::test_dlc_partition_sync_reads_mixed_partition_stats tests/test_sync_wedata.py::SyncWeDataTest::test_partition_sync_keeps_only_requested_dt_partition -v
```

Expected: all pass. This verifies DLC keeps all and non-DLC still filters requested `dt`.

- [ ] **Step 6: Commit**

```bash
git add dlc_mcp/sync_wedata.py tests/test_sync_wedata.py
git commit -m "fix: keep all DLC partitions during incremental sync"
```

---

### Task 2: Add single-table live partition refresh

**Files:**
- Modify: `dlc_mcp/live.py:3-6`
- Modify: `dlc_mcp/live.py:20-42`
- Modify: `tests/test_mcp.py` or `tests/test_sync_wedata.py` if the project has a better existing live test location

**Interfaces:**
- Consumes: `LiveWeData.store`, `LiveWeData.project_id`, `LiveWeData.page_size`, sync helpers `_partition_payload`, `_partition_payload_ready`, `_partition_client`, `_list_partitions`, `_partition_items` from `dlc_mcp.sync_wedata`.
- Produces: `LiveWeData.sync_table_partitions(table_name: str) -> None`, which calls DLC/partition service for exactly one table and imports `{"table_partitions": response}` into cache.

- [ ] **Step 1: Add imports needed for live partition sync**

In `dlc_mcp/live.py`, replace the sync import line:

```python
from .sync_wedata import _merge_task_responses, _sync_related_task_definitions
```

with:

```python
from .sync_wedata import _list_partitions, _merge_task_responses, _partition_client, _partition_items, _partition_payload, _partition_payload_ready, _sync_related_task_definitions
```

- [ ] **Step 2: Write a failing unit test for live single-table partition refresh**

Add this test class to `tests/test_mcp.py` if it already contains live tool tests; otherwise add it near other MCP/live tests in that file. If `tests/test_mcp.py` does not import these names, add the imports shown here.

```python
import os
import sqlite3
from unittest.mock import patch

from dlc_mcp.assets import AssetStore
from dlc_mcp.live import LiveWeData


class FakeLivePartitionClient:
    def call(self, action, payload):
        if action == "DescribeTablePartitions":
            return {
                "Response": {
                    "MixedPartitions": {
                        "TotalSize": 1,
                        "IcebergPartitions": [
                            {
                                "Partition": "dt=20260706",
                                "Records": 2,
                                "DataFileStorage": 123,
                                "DataFileSize": 1,
                                "UpdateTime": "2026-07-16T07:02:22+08:00",
                            }
                        ],
                    }
                }
            }
        return {"Response": {"Data": {"Items": []}}}


def test_live_sync_table_partitions_imports_dlc_partition_facts():
    conn = sqlite3.connect(":memory:")
    store = AssetStore(conn)
    store.init_schema()
    store.upsert_table({"name": "ods_cloud_cost_baidu_day_di", "database": "byai_bigdata"})
    store.upsert_column("ods_cloud_cost_baidu_day_di", "dt", "string", "", 1)

    with patch.dict(
        os.environ,
        {
            "WEDATA_PROJECT_ID": "project",
            "WEDATA_PARTITION_SERVICE": "dlc",
            "WEDATA_PARTITION_ACTION": "DescribeTablePartitions",
            "DLC_CATALOG": "DataLakeCatalog",
        },
        clear=False,
    ), patch("dlc_mcp.live._partition_client", return_value=FakeLivePartitionClient()):
        live = LiveWeData(store, client=FakeLivePartitionClient())
        live.sync_table_partitions("ods_cloud_cost_baidu_day_di")

    profile = store.get_table_partition_profile("ods_cloud_cost_baidu_day_di", "")
    assert profile["partition_fact_available"] is True
    assert profile["partition_count"] == 1
    assert profile["latest_partition"]["partition_name"] == "dt=20260706"
```

- [ ] **Step 3: Run test to verify it fails**

Run:

```bash
pytest tests/test_mcp.py::test_live_sync_table_partitions_imports_dlc_partition_facts -v
```

Expected before implementation: FAIL with `AttributeError: 'LiveWeData' object has no attribute 'sync_table_partitions'`.

- [ ] **Step 4: Implement `LiveWeData.sync_table_partitions()`**

In `dlc_mcp/live.py`, add this method after `sync_table()`:

```python
    def sync_table_partitions(self, table_name):
        table = self.store._one("select * from tables where name = ?", (table_name,))
        if not table:
            self.sync_table(table_name)
            table = self.store._one("select * from tables where name = ?", (table_name,))
        if not table:
            raise RuntimeError("table_not_found")
        table_data = self.store._table_dict(table)
        catalog_item = table_data.get("raw") or {}
        payload = _partition_payload(self.project_id, table_name, catalog_item)
        if not _partition_payload_ready(payload):
            raise RuntimeError("missing required partition payload fields")
        action = os.environ.get("WEDATA_PARTITION_ACTION", "ListTablePartitions")
        response = _list_partitions(_partition_client(self.client), action, payload, self.page_size)
        items = _partition_items(response)
        for item in items:
            item["QueriedTableName"] = table_name
        normalized = {"Response": {"Data": {"Items": items}, "PartitionFailures": []}}
        self._import({"table_partitions": normalized})
```

This method intentionally does not filter by `partition_date`. The caller uses `partition_date` only when rendering/health-checking the target partition after cache refresh.

- [ ] **Step 5: Verify test passes**

Run:

```bash
pytest tests/test_mcp.py::test_live_sync_table_partitions_imports_dlc_partition_facts -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add dlc_mcp/live.py tests/test_mcp.py
git commit -m "feat: add live table partition refresh"
```

---

### Task 3: Wire MCP partition profile to live fallback

**Files:**
- Modify: `dlc_mcp/mcp.py:365-367`
- Modify: `tests/test_mcp.py`

**Interfaces:**
- Consumes: `LiveWeData.sync_table_partitions(table_name: str) -> None` from Task 2.
- Produces: `get_table_partition_profile` MCP call supports existing `live` argument behavior: live refresh happens when `live=true`, or when global live object is available and cache profile says table is partitioned but `partition_fact_available` is false. Returned markdown includes query metadata from `_format_with_meta()`.

- [ ] **Step 1: Add failing MCP tool-call test**

Add this test to `tests/test_mcp.py`, adapting only the request helper if that file already has one. The key assertions are that `sync_table_partitions()` is called and the formatted result reports live refresh metadata.

```python
class FakePartitionLive:
    def __init__(self):
        self.synced = []

    def sync_table_partitions(self, table_name):
        self.synced.append(table_name)


def test_partition_profile_live_true_triggers_partition_refresh():
    conn = sqlite3.connect(":memory:")
    store = AssetStore(conn)
    store.init_schema()
    store.upsert_table({"name": "ods_cloud_cost_baidu_day_di", "database": "byai_bigdata"})
    store.upsert_column("ods_cloud_cost_baidu_day_di", "dt", "string", "", 1)
    live = FakePartitionLive()
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "get_table_partition_profile",
            "arguments": {"table_name": "ods_cloud_cost_baidu_day_di", "partition_date": "", "live": True},
        },
    }

    response = _call_tool(store, request, live)
    text = response["result"]["content"][0]["text"]

    assert live.synced == ["ods_cloud_cost_baidu_day_di"]
    assert "实时刷新：是" in text
    assert "触发原因：user_requested" in text
```

If `_call_tool` is not imported in `tests/test_mcp.py`, add:

```python
from dlc_mcp.mcp import _call_tool
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pytest tests/test_mcp.py::test_partition_profile_live_true_triggers_partition_refresh -v
```

Expected before implementation: FAIL because `live.synced` remains empty.

- [ ] **Step 3: Implement live fallback in MCP dispatcher**

In `dlc_mcp/mcp.py`, replace the `get_table_partition_profile` branch:

```python
    elif name == "get_table_partition_profile":
        data = store.get_table_partition_profile(args["table_name"], args.get("partition_date", ""))
```

with:

```python
    elif name == "get_table_partition_profile":
        data = store.get_table_partition_profile(args["table_name"], args.get("partition_date", ""))
        if live:
            refreshed = _maybe_live_refresh(
                meta,
                args,
                data,
                lambda item: _has_error(item) or (item.get("is_partitioned") and not item.get("partition_fact_available")),
                lambda: live.sync_table_partitions(args["table_name"]),
                reason="missing_partition_facts" if data.get("is_partitioned") and not data.get("partition_fact_available") else "",
            )
            if refreshed:
                data = store.get_table_partition_profile(args["table_name"], args.get("partition_date", ""))
```

- [ ] **Step 4: Verify targeted MCP tests pass**

Run:

```bash
pytest tests/test_mcp.py::test_partition_profile_live_true_triggers_partition_refresh -v
```

Expected: PASS.

- [ ] **Step 5: Run partition-related test subset**

Run:

```bash
pytest tests/test_mcp.py tests/test_sync_wedata.py tests/test_partitioning.py tests/test_wedata_import.py -v
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add dlc_mcp/mcp.py tests/test_mcp.py
git commit -m "feat: refresh partition facts on live profile queries"
```

---

### Task 4: Update docs and run end-to-end validation

**Files:**
- Modify: `docs/server-mcp-wedata-flow.md:284-349`
- No source code changes unless validation exposes a defect.

**Interfaces:**
- Consumes: Task 1 DLC sync behavior and Task 3 live profile behavior.
- Produces: operator docs that state DLC daily partition sync stores all returned partitions, and `partition_date` is a query target, not a DLC sync filter.

- [ ] **Step 1: Update operator docs**

In `docs/server-mcp-wedata-flow.md`, update the partition sync section to include this language:

```markdown
For `WEDATA_PARTITION_SERVICE=dlc`, `DescribeTablePartitions` returns the table's partition list. DLC daily sync stores all returned partitions for each candidate partitioned table and relies on `table_partitions` upsert keys to deduplicate repeated daily refreshes. Do not interpret `WEDATA_PARTITION_DATE` as a DLC-side result filter.

`partition_date` in `get_table_partition_profile(table_name, partition_date)` is the target partition to highlight in the profile. It does not mean the cache only contains that date. This is required for delayed tables such as cloud cost tables, where a run on 2026-07-16 may update `dt=20260706` rather than `dt=20260715`.

When a table is identified as partitioned but the cache has no partition facts, call `get_table_partition_profile(..., live=true)` to refresh the single table from DLC and write the returned partition facts back to cache.
```

- [ ] **Step 2: Run full test suite**

Run:

```bash
pytest -q
```

Expected: all tests pass.

- [ ] **Step 3: Run local smoke command for profile formatting**

Run this one-off command:

```bash
python3 - <<'PY'
import sqlite3
from dlc_mcp.assets import AssetStore
conn = sqlite3.connect(':memory:')
store = AssetStore(conn)
store.init_schema()
store.upsert_table({'name': 'ods_cloud_cost_baidu_day_di', 'database': 'byai_bigdata'})
store.upsert_column('ods_cloud_cost_baidu_day_di', 'dt', 'string', '', 1)
print(store.get_table_partition_profile('ods_cloud_cost_baidu_day_di', ''))
PY
```

Expected: output contains `is_partitioned': True`, `partition_keys': ['dt']`, and `partition_fact_status': 'missing'`.

- [ ] **Step 4: Commit docs and validation state**

```bash
git add docs/server-mcp-wedata-flow.md
git commit -m "docs: clarify DLC partition sync semantics"
```

---

### Task 5: Deploy and verify on the server

**Files:**
- No repository file changes unless deployment scripts need a discovered correction.

**Interfaces:**
- Consumes: merged code from Tasks 1-4.
- Produces: server `root@64.186.234.87` running new gateway and cache with `ods_cloud_cost_baidu_day_di` partition facts populated after live/sync validation.

- [ ] **Step 1: Copy or pull updated code on the server**

Use the repository's established deployment process. If deploying by git pull on server:

```bash
ssh root@64.186.234.87 'cd /opt/dlc-mcp/DLC-MCP && git pull --ff-only'
```

Expected: server working tree updates to the commit containing Tasks 1-4.

- [ ] **Step 2: Run server-side focused tests**

```bash
ssh root@64.186.234.87 'cd /opt/dlc-mcp/DLC-MCP && pytest tests/test_sync_wedata.py::SyncWeDataTest::test_dlc_incremental_partition_sync_keeps_all_returned_partitions tests/test_mcp.py::test_live_sync_table_partitions_imports_dlc_partition_facts -v'
```

Expected: both tests pass.

- [ ] **Step 3: Restart MCP gateway**

```bash
ssh root@64.186.234.87 'cd /opt/dlc-mcp/DLC-MCP; OLD=$(pgrep -f "python3 -m dlc_mcp.gateway" | head -1 || true); if [ -n "$OLD" ]; then kill -TERM "$OLD"; sleep 2; fi; set -a; . /etc/dlc-mcp/env; set +a; nohup python3 -m dlc_mcp.gateway --host 0.0.0.0 --port 8787 >> /data/dlc-mcp/logs/gateway.log 2>&1 & echo $! > /data/dlc-mcp/gateway.pid; sleep 2; curl -fsS http://127.0.0.1:8787/health'
```

Expected: `{"ok": true}`.

- [ ] **Step 4: Verify live refresh for Baidu table on server**

Run direct server code so the verification does not depend on local MCP connection routing:

```bash
ssh root@64.186.234.87 "cd /opt/dlc-mcp/DLC-MCP && set -a && . /etc/dlc-mcp/env && set +a && python3 - <<'PY'
import json, sqlite3, os
from dlc_mcp.assets import AssetStore
from dlc_mcp.live import LiveWeData
conn = sqlite3.connect(os.environ['DLC_MCP_DB'])
store = AssetStore(conn)
live = LiveWeData(store)
live.sync_table_partitions('ods_cloud_cost_baidu_day_di')
profile = store.get_table_partition_profile('ods_cloud_cost_baidu_day_di', '')
print(json.dumps({
    'is_partitioned': profile['is_partitioned'],
    'partition_fact_available': profile['partition_fact_available'],
    'partition_count': profile['partition_count'],
    'latest_partition': profile['latest_partition'],
}, ensure_ascii=False, default=str, indent=2))
PY"
```

Expected: `partition_fact_available` is `true`, `partition_count` is greater than `0`, and one recent partition is visible.

- [ ] **Step 5: Verify MCP tool response**

From the local Claude/MCP session, call:

```text
get_table_partition_profile(table_name="ods_cloud_cost_baidu_day_di", partition_date="", live=true)
```

Expected markdown includes:

```text
是否分区表：True
分区事实可用：True
分区数量：>0
数据来源：cache_after_live_refresh
```

- [ ] **Step 6: Run a daily sync dry validation on one known table if needed**

If server load is acceptable, run a one-table direct `_sync_partitions()` validation instead of full daily sync:

```bash
ssh root@64.186.234.87 "cd /opt/dlc-mcp/DLC-MCP && set -a && . /etc/dlc-mcp/env && set +a && python3 - <<'PY'
import json, os
from dlc_mcp.tencentcloud import TencentCloudClient
from dlc_mcp.sync_wedata import _sync_partitions
client = TencentCloudClient.wedata_from_env()
response = _sync_partitions(client, os.environ['WEDATA_PROJECT_ID'], ['ods_cloud_cost_baidu_day_di'], 100, progress_every=0, catalog_tables={'ods_cloud_cost_baidu_day_di': {'DatabaseName': 'byai_bigdata'}})
print(len(response['Response']['Data']['Items']))
PY"
```

Expected: prints a positive count, approximately the DLC API partition count observed before deployment.

- [ ] **Step 7: Do not commit deployment-only changes**

Run locally:

```bash
git status --short
```

Expected: clean or only intentionally uncommitted local deployment notes. Do not commit server-generated artifacts.

---

## Self-Review

**Spec coverage:**
- DLC sync no longer filters to `dt=昨天`: Task 1.
- Cache remains primary: Tasks 1 and 3.
- Live fallback for cache miss: Tasks 2 and 3.
- `partition_date` query target only: Tasks 1, 3, and docs in Task 4.
- Server validation for `ods_cloud_cost_baidu_day_di`: Task 5.

**Placeholder scan:** No TBD/TODO placeholders remain. Each code step includes exact code or exact command.

**Type consistency:** `LiveWeData.sync_table_partitions(table_name)` is defined in Task 2 and consumed by Task 3. `_sync_partitions()` signature remains unchanged. `partition_fact_available`, `is_partitioned`, and `partition_count` names match `AssetStore.get_table_partition_profile()`.
