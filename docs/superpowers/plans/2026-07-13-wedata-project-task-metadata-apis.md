# WeData Project, Task Dependency, and Table Metadata APIs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add six read-only WeData-backed MCP tools for projects, project members, task dependencies, and table metadata, with SQLite caching and Markdown output.

**Architecture:** Follow the existing WeData-first MCP architecture: TencentCloudClient performs signed Tencent Cloud calls, LiveWeData handles action-specific sync, wedata.py normalizes API responses, AssetStore persists facts in SQLite, and mcp.py exposes user-facing Markdown tools. New project, member, task-relation, and table-detail facts are cached first and then returned through the same store/formatter flow used by existing tools.

**Tech Stack:** Python 3 standard library, sqlite3, unittest, existing MCP JSON-RPC handler, existing Tencent Cloud TC3 client, Node package smoke checks.

## Global Constraints

- User-facing MCP access remains read-only.
- Tencent Cloud AK/SK stay on the trusted server.
- MCP tool names use snake_case; Tencent Cloud Action names remain PascalCase internally.
- Tools return Markdown summaries and key-field tables, not raw Tencent Cloud JSON.
- API responses that can be reused are cached in SQLite.
- `project_id` parameters default to `WEDATA_PROJECT_ID` when omitted.
- `list_projects` does not require `project_id`.
- `get_table` requires at least one of `table_name` or `table_guid`.
- Do not commit changes unless the user explicitly authorizes committing in the execution conversation.
- Use code-review-graph MCP tools before Grep/Glob/Read when exploring code.

---

## File Structure

Modify these files:

- `dlc_mcp/assets.py`
  - Add six WeData API catalog entries.
  - Add SQLite tables `projects`, `project_members`, and `task_relations`.
  - Add compatible `tables` columns: `project_id`, `table_type`, `catalog_name`, `schema_name`, `raw_json`.
  - Add store methods for projects, project members, task relations, and table-detail lookup.
  - Extend `upsert_table`, `_table_dict`, `list_metadata`, and sync health counts.

- `dlc_mcp/wedata.py`
  - Extend `import_wedata_snapshot` and `snapshot_from_api_dump` for `projects`, `project_members`, and `task_relations`.
  - Add normalizers for project records, member records, task dependency records, and table detail.
  - Preserve unnormalized fields in `raw` dictionaries that AssetStore persists as `raw_json`.

- `dlc_mcp/live.py`
  - Add project ID resolution helper.
  - Add sync methods for projects, project details, project members, task relations, and table details.
  - Use `_list_all` for list APIs and direct `client.call` for detail APIs.

- `dlc_mcp/mcp.py`
  - Register six new MCP tools.
  - Add `_call_tool` branches for cache-first/live-refresh behavior.
  - Add Markdown formatters for project lists, project details, member lists, upstream/downstream task lists, and table metadata details.
  - Add local error helpers for missing project ID and table identity.

- `README.md`
  - Add six new tools to the Tools table.

- `tests/test_assets.py`
  - Add store tests for API catalog entries, project cache, member cache, task relation cache, and table-detail fields.

- `tests/test_wedata_import.py`
  - Add normalizer/import tests for the new response families.

- `tests/test_mcp.py`
  - Add tools/list and tools/call tests for the six MCP tools.
  - Add fake live-client assertions for Action names and default project ID behavior.

No new third-party dependencies are required.

---

### Task 1: Extend AssetStore schema, catalog, and cache methods

**Files:**
- Modify: `dlc_mcp/assets.py`
- Test: `tests/test_assets.py`

**Interfaces:**
- Consumes: Existing `AssetStore.init_schema()`, `upsert_cloud_api()`, `upsert_table()`, `_all()`, `_one()`, `_add_column_if_missing()`, `_table_dict()`.
- Produces:
  - `AssetStore.upsert_project(item: dict) -> None`
  - `AssetStore.list_projects(query: str = "") -> dict`
  - `AssetStore.get_project(project_id: str) -> dict`
  - `AssetStore.replace_project_members(project_id: str, members: list[dict]) -> None`
  - `AssetStore.list_project_members(project_id: str) -> dict`
  - `AssetStore.replace_task_relations(project_id: str, task_id: str, direction: str, relations: list[dict]) -> None`
  - `AssetStore.list_task_relations(project_id: str, task_id: str, direction: str) -> dict`
  - `AssetStore.get_table_detail(table_name: str = "", table_guid: str = "") -> dict`

- [ ] **Step 1: Add failing tests for the new API catalog entries**

Append this test method to `AssetStoreTest` in `tests/test_assets.py`:

```python
    def test_cloud_api_catalog_includes_project_task_relation_and_get_table_apis(self):
        apis = make_store().list_cloud_apis(service="wedata")["results"]
        by_action = {api["action"]: api for api in apis}

        self.assertEqual(by_action["ListProjects"]["doc_category"], "项目管理相关接口")
        self.assertEqual(by_action["GetProject"]["doc_category"], "项目管理相关接口")
        self.assertEqual(by_action["ListProjectMembers"]["doc_category"], "项目管理相关接口")
        self.assertEqual(by_action["ListDownstreamTasks"]["doc_category"], "数据开发相关接口")
        self.assertEqual(by_action["ListUpstreamTasks"]["doc_category"], "数据开发相关接口")
        self.assertEqual(by_action["GetTable"]["doc_category"], "元数据相关接口")
```

- [ ] **Step 2: Run the catalog test and verify it fails**

Run:

```bash
python3 -m unittest tests.test_assets.AssetStoreTest.test_cloud_api_catalog_includes_project_task_relation_and_get_table_apis -v
```

Expected: FAIL with a missing-key assertion such as `KeyError: 'ListProjects'`.

- [ ] **Step 3: Add the six API catalog entries**

In `dlc_mcp/assets.py`, append these dictionaries inside `TENCENT_CLOUD_API_CATALOG`, before the DLC `DescribeTablePartitions` entry:

```python
    {
        "service": "wedata",
        "action": "ListProjects",
        "provider": "Tencent Cloud",
        "product": "WeData",
        "doc_category": "项目管理相关接口",
        "source_url": "https://cloud.tencent.com/document/product/1267/123653",
        "description": "查看项目详情列表。",
        "usage": "同步项目清单，支撑项目名展示、默认项目检查和项目级治理范围。",
    },
    {
        "service": "wedata",
        "action": "GetProject",
        "provider": "Tencent Cloud",
        "product": "WeData",
        "doc_category": "项目管理相关接口",
        "source_url": "https://cloud.tencent.com/document/product/1267/123653",
        "description": "查看项目详情。",
        "usage": "补齐单个项目的负责人、状态、区域、描述和时间信息。",
    },
    {
        "service": "wedata",
        "action": "ListProjectMembers",
        "provider": "Tencent Cloud",
        "product": "WeData",
        "doc_category": "项目管理相关接口",
        "source_url": "https://cloud.tencent.com/document/product/1267/123653",
        "description": "查看项目成员列表。",
        "usage": "同步项目成员和角色，支撑项目权限查看与 Owner 责任链补充。",
    },
    {
        "service": "wedata",
        "action": "ListDownstreamTasks",
        "provider": "Tencent Cloud",
        "product": "WeData",
        "doc_category": "数据开发相关接口",
        "source_url": "https://cloud.tencent.com/document/product/1267/123653",
        "description": "查看下游任务列表。",
        "usage": "同步任务级下游依赖，补充表血缘之外的任务依赖分析。",
    },
    {
        "service": "wedata",
        "action": "ListUpstreamTasks",
        "provider": "Tencent Cloud",
        "product": "WeData",
        "doc_category": "数据开发相关接口",
        "source_url": "https://cloud.tencent.com/document/product/1267/123653",
        "description": "查看上游任务列表。",
        "usage": "同步任务级上游依赖，补充表血缘之外的任务依赖分析。",
    },
    {
        "service": "wedata",
        "action": "GetTable",
        "provider": "Tencent Cloud",
        "product": "WeData",
        "doc_category": "元数据相关接口",
        "source_url": "https://cloud.tencent.com/document/product/1267/123653",
        "description": "获取表详情。",
        "usage": "补齐单表元数据详情，并与表画像能力共享表资产缓存。",
    },
```

- [ ] **Step 4: Run the catalog test and verify it passes**

Run:

```bash
python3 -m unittest tests.test_assets.AssetStoreTest.test_cloud_api_catalog_includes_project_task_relation_and_get_table_apis -v
```

Expected: PASS.

- [ ] **Step 5: Add failing tests for project, member, task relation, and table-detail cache methods**

Append these test methods to `AssetStoreTest` in `tests/test_assets.py`:

```python
    def test_project_cache_round_trip_and_query(self):
        store = make_store()
        store.upsert_project(
            {
                "id": "p1",
                "name": "prod",
                "display_name": "生产项目",
                "description": "Production project",
                "owner": "data-platform",
                "status": "enabled",
                "region": "ap-guangzhou",
                "create_time": "2026-07-01 10:00:00",
                "update_time": "2026-07-02 10:00:00",
                "raw": {"ProjectId": "p1"},
            }
        )

        project = store.get_project("p1")
        self.assertEqual(project["name"], "prod")
        self.assertEqual(project["display_name"], "生产项目")
        self.assertEqual(project["raw"]["ProjectId"], "p1")
        self.assertEqual(store.list_projects("生产")["results"][0]["id"], "p1")

    def test_project_member_cache_replaces_one_project(self):
        store = make_store()
        store.replace_project_members(
            "p1",
            [
                {
                    "member_id": "u1",
                    "member_name": "zhangsan",
                    "display_name": "张三",
                    "role_name": "管理员",
                    "role_id": "r1",
                    "member_type": "user",
                    "join_time": "2026-07-01 11:00:00",
                    "raw": {"UserId": "u1"},
                }
            ],
        )
        store.replace_project_members("p2", [{"member_id": "u2", "member_name": "lisi", "role_id": "r2"}])
        store.replace_project_members("p1", [{"member_id": "u3", "member_name": "wangwu", "role_id": "r3"}])

        members = store.list_project_members("p1")
        self.assertEqual([member["member_id"] for member in members["members"]], ["u3"])
        self.assertEqual(store.list_project_members("p2")["members"][0]["member_id"], "u2")

    def test_task_relation_cache_replaces_by_project_task_and_direction(self):
        store = make_store()
        store.replace_task_relations(
            "p1",
            "task_001",
            "downstream",
            [
                {
                    "related_task_id": "task_002",
                    "task_name": "build_dim_customer",
                    "related_task_name": "build_ads_customer",
                    "dependency_type": "normal",
                    "owner": "etl-owner",
                    "status": "Y11",
                    "raw": {"TaskId": "task_002"},
                }
            ],
        )

        relations = store.list_task_relations("p1", "task_001", "downstream")
        self.assertEqual(relations["relations"][0]["related_task_id"], "task_002")
        self.assertEqual(relations["relations"][0]["related_task_name"], "build_ads_customer")
        self.assertEqual(store.get_task("task_002")["name"], "build_ads_customer")

    def test_table_detail_fields_are_cached(self):
        store = make_store()
        store.upsert_table(
            {
                "name": "ads_order_daily",
                "guid": "guid_ads_order_daily",
                "project_id": "p1",
                "database": "bi",
                "table_type": "MANAGED_TABLE",
                "catalog_name": "DataLakeCatalog",
                "schema_name": "bi",
                "owner": "data-finance",
                "description": "Order daily summary",
                "raw": {"TableName": "ads_order_daily"},
            }
        )

        detail = store.get_table_detail(table_name="ads_order_daily")
        self.assertEqual(detail["table"]["project_id"], "p1")
        self.assertEqual(detail["table"]["table_type"], "MANAGED_TABLE")
        self.assertEqual(detail["table"]["catalog_name"], "DataLakeCatalog")
        self.assertEqual(detail["table"]["schema_name"], "bi")
        self.assertEqual(detail["table"]["raw"]["TableName"], "ads_order_daily")
        self.assertEqual(store.get_table_detail(table_guid="guid_ads_order_daily")["table"]["name"], "ads_order_daily")
```

- [ ] **Step 6: Run the new cache tests and verify they fail**

Run:

```bash
python3 -m unittest \
  tests.test_assets.AssetStoreTest.test_project_cache_round_trip_and_query \
  tests.test_assets.AssetStoreTest.test_project_member_cache_replaces_one_project \
  tests.test_assets.AssetStoreTest.test_task_relation_cache_replaces_by_project_task_and_direction \
  tests.test_assets.AssetStoreTest.test_table_detail_fields_are_cached -v
```

Expected: FAIL with missing methods such as `AttributeError: 'AssetStore' object has no attribute 'upsert_project'`.

- [ ] **Step 7: Add schema tables and compatible columns**

In `AssetStore.init_schema()` in `dlc_mcp/assets.py`, add these `create table` statements inside the existing `executescript` block after `data_source_tasks` and before `table_partitions`:

```python
            create table if not exists projects (
                id text primary key,
                name text not null default '',
                display_name text not null default '',
                description text not null default '',
                owner text not null default '',
                status text not null default '',
                region text not null default '',
                create_time text not null default '',
                update_time text not null default '',
                raw_json text not null default '{}'
            );
            create table if not exists project_members (
                project_id text not null,
                member_id text not null,
                member_name text not null default '',
                display_name text not null default '',
                role_name text not null default '',
                role_id text not null default '',
                member_type text not null default '',
                join_time text not null default '',
                raw_json text not null default '{}',
                primary key (project_id, member_id, role_id)
            );
            create table if not exists task_relations (
                project_id text not null,
                task_id text not null,
                related_task_id text not null,
                direction text not null,
                task_name text not null default '',
                related_task_name text not null default '',
                dependency_type text not null default '',
                owner text not null default '',
                status text not null default '',
                raw_json text not null default '{}',
                primary key (project_id, task_id, related_task_id, direction)
            );
```

Still in `init_schema()`, after the existing `_add_column_if_missing("tables", "data_source_id", ...)` calls, add:

```python
        self._add_column_if_missing("tables", "project_id", "text not null default ''")
        self._add_column_if_missing("tables", "table_type", "text not null default ''")
        self._add_column_if_missing("tables", "catalog_name", "text not null default ''")
        self._add_column_if_missing("tables", "schema_name", "text not null default ''")
        self._add_column_if_missing("tables", "raw_json", "text not null default '{}'")
```

- [ ] **Step 8: Extend `upsert_table` and table reads**

Replace `AssetStore.upsert_table()` with this implementation:

```python
    def upsert_table(self, item):
        self.conn.execute(
            """
            insert into tables
                (name, source_guid, data_source_id, database_name, layer, domain, owner, description, manual_core_level,
                 project_id, table_type, catalog_name, schema_name, raw_json)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            on conflict(name) do update set
                source_guid = coalesce(nullif(excluded.source_guid, ''), tables.source_guid),
                data_source_id = coalesce(nullif(excluded.data_source_id, ''), tables.data_source_id),
                database_name = coalesce(nullif(excluded.database_name, ''), tables.database_name),
                layer = coalesce(nullif(excluded.layer, ''), tables.layer),
                domain = coalesce(nullif(excluded.domain, ''), tables.domain),
                owner = coalesce(nullif(excluded.owner, ''), tables.owner),
                description = coalesce(nullif(excluded.description, ''), tables.description),
                manual_core_level = coalesce(excluded.manual_core_level, tables.manual_core_level),
                project_id = coalesce(nullif(excluded.project_id, ''), tables.project_id),
                table_type = coalesce(nullif(excluded.table_type, ''), tables.table_type),
                catalog_name = coalesce(nullif(excluded.catalog_name, ''), tables.catalog_name),
                schema_name = coalesce(nullif(excluded.schema_name, ''), tables.schema_name),
                raw_json = case when excluded.raw_json != '{}' then excluded.raw_json else tables.raw_json end
            """,
            (
                item["name"],
                item.get("guid", ""),
                item.get("data_source_id", ""),
                item.get("database", ""),
                item.get("layer", ""),
                item.get("domain", ""),
                item.get("owner", ""),
                item.get("description", ""),
                item.get("manual_core_level"),
                item.get("project_id", ""),
                item.get("table_type", ""),
                item.get("catalog_name", ""),
                item.get("schema_name", ""),
                json.dumps(item.get("raw", {}), ensure_ascii=False, sort_keys=True),
            ),
        )
        if item.get("data_source_id"):
            self.upsert_asset_edge(
                "data_source",
                item.get("data_source_id", ""),
                "table",
                item["name"],
                "contains_table",
                "wedata_list_table",
                "high",
                {"database": item.get("database", ""), "guid": item.get("guid", ""), "project_id": item.get("project_id", "")},
                commit=False,
            )
        self.conn.commit()
```

Find every SQL select that reads from `tables` with the old column list:

```sql
select name, source_guid, data_source_id, database_name, layer, domain, owner, description, manual_core_level from tables
```

Replace it with this column list:

```sql
select name, source_guid, data_source_id, database_name, layer, domain, owner, description, manual_core_level, project_id, table_type, catalog_name, schema_name, raw_json from tables
```

- [ ] **Step 9: Add project, member, task relation, and table-detail store methods**

In `dlc_mcp/assets.py`, insert these methods after `list_cloud_apis()` and before `upsert_table()`:

```python
    def upsert_project(self, item):
        self.conn.execute(
            """
            insert into projects (id, name, display_name, description, owner, status, region, create_time, update_time, raw_json)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            on conflict(id) do update set
                name = excluded.name,
                display_name = excluded.display_name,
                description = excluded.description,
                owner = excluded.owner,
                status = excluded.status,
                region = excluded.region,
                create_time = excluded.create_time,
                update_time = excluded.update_time,
                raw_json = excluded.raw_json
            """,
            (
                item["id"],
                item.get("name", ""),
                item.get("display_name", ""),
                item.get("description", ""),
                item.get("owner", ""),
                item.get("status", ""),
                item.get("region", ""),
                item.get("create_time", ""),
                item.get("update_time", ""),
                json.dumps(item.get("raw", {}), ensure_ascii=False, sort_keys=True),
            ),
        )
        self.conn.commit()

    def list_projects(self, query=""):
        like = f"%{query}%"
        rows = self._all(
            """
            select id, name, display_name, description, owner, status, region, create_time, update_time, raw_json
            from projects
            where ? = '' or id like ? or name like ? or display_name like ? or owner like ? or status like ?
            order by name, id
            limit 200
            """,
            (query, like, like, like, like, like),
        )
        return {"query": query, "results": [self._project_dict(row) for row in rows]}

    def get_project(self, project_id):
        row = self._one(
            """
            select id, name, display_name, description, owner, status, region, create_time, update_time, raw_json
            from projects
            where id = ?
            """,
            (project_id,),
        )
        if not row:
            return {"error": "project_not_found", "project_id": project_id}
        return self._project_dict(row)

    def replace_project_members(self, project_id, members):
        self.conn.execute("delete from project_members where project_id = ?", (project_id,))
        for item in members:
            self.conn.execute(
                """
                insert or replace into project_members
                    (project_id, member_id, member_name, display_name, role_name, role_id, member_type, join_time, raw_json)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    item["member_id"],
                    item.get("member_name", ""),
                    item.get("display_name", ""),
                    item.get("role_name", ""),
                    item.get("role_id", ""),
                    item.get("member_type", ""),
                    item.get("join_time", ""),
                    json.dumps(item.get("raw", {}), ensure_ascii=False, sort_keys=True),
                ),
            )
        self.conn.commit()

    def list_project_members(self, project_id):
        rows = self._all(
            """
            select project_id, member_id, member_name, display_name, role_name, role_id, member_type, join_time, raw_json
            from project_members
            where project_id = ?
            order by role_name, member_name, member_id
            """,
            (project_id,),
        )
        return {"project_id": project_id, "members": [self._project_member_dict(row) for row in rows]}

    def replace_task_relations(self, project_id, task_id, direction, relations):
        self.conn.execute(
            "delete from task_relations where project_id = ? and task_id = ? and direction = ?",
            (project_id, task_id, direction),
        )
        for item in relations:
            related_task_id = item["related_task_id"]
            task_name = item.get("task_name", "")
            related_task_name = item.get("related_task_name", "")
            self.conn.execute(
                """
                insert or replace into task_relations
                    (project_id, task_id, related_task_id, direction, task_name, related_task_name, dependency_type, owner, status, raw_json)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    task_id,
                    related_task_id,
                    direction,
                    task_name,
                    related_task_name,
                    item.get("dependency_type", ""),
                    item.get("owner", ""),
                    item.get("status", ""),
                    json.dumps(item.get("raw", {}), ensure_ascii=False, sort_keys=True),
                ),
            )
            self.upsert_task(
                {
                    "id": related_task_id,
                    "name": related_task_name,
                    "task_type": item.get("task_type", ""),
                    "owner": item.get("owner", ""),
                    "status": item.get("status", ""),
                }
            )
        self.conn.commit()

    def list_task_relations(self, project_id, task_id, direction):
        rows = self._all(
            """
            select project_id, task_id, related_task_id, direction, task_name, related_task_name, dependency_type, owner, status, raw_json
            from task_relations
            where project_id = ? and task_id = ? and direction = ?
            order by related_task_name, related_task_id
            """,
            (project_id, task_id, direction),
        )
        return {"project_id": project_id, "task_id": task_id, "direction": direction, "relations": [self._task_relation_dict(row) for row in rows]}

    def get_table_detail(self, table_name="", table_guid=""):
        if table_guid:
            row = self._one(
                """
                select name, source_guid, data_source_id, database_name, layer, domain, owner, description, manual_core_level,
                       project_id, table_type, catalog_name, schema_name, raw_json
                from tables
                where source_guid = ?
                """,
                (table_guid,),
            )
        else:
            row = self._one(
                """
                select name, source_guid, data_source_id, database_name, layer, domain, owner, description, manual_core_level,
                       project_id, table_type, catalog_name, schema_name, raw_json
                from tables
                where name = ?
                """,
                (table_name,),
            )
        if not row:
            return {"error": "table_not_found", "table_name": table_name, "table_guid": table_guid}
        table = self._table_dict(row)
        columns = [dict(item) for item in self._all("select name, type, description from columns where table_name = ? order by ordinal, name", (table["name"],))]
        return {"table": table, "columns": columns}
```

Then add these row-conversion helpers near existing `_data_source_dict` / `_table_dict` helpers:

```python
    def _project_dict(self, row):
        data = dict(row)
        data["raw"] = _json_dict(data.pop("raw_json", "{}"))
        return data

    def _project_member_dict(self, row):
        data = dict(row)
        data["raw"] = _json_dict(data.pop("raw_json", "{}"))
        return data

    def _task_relation_dict(self, row):
        data = dict(row)
        data["raw"] = _json_dict(data.pop("raw_json", "{}"))
        return data
```

Update `_table_dict(row)` so it includes the new fields and raw payload:

```python
    def _table_dict(self, row):
        data = dict(row)
        data["guid"] = data.pop("source_guid", "")
        data["database"] = data.pop("database_name", "")
        data["raw"] = _json_dict(data.pop("raw_json", "{}")) if "raw_json" in data else {}
        return data
```

- [ ] **Step 10: Update sync health counts**

In `AssetStore.get_sync_health()`, add these keys to `counts`:

```python
            "projects": self._count("projects"),
            "project_members": self._count("project_members"),
            "task_relations": self._count("task_relations"),
```

Add these gap checks after the existing data source gap check:

```python
        if counts["projects"] == 0:
            gaps.append("未同步 WeData 项目列表")
        if counts["project_members"] == 0:
            gaps.append("未同步 WeData 项目成员")
        if counts["task_relations"] == 0:
            gaps.append("未同步任务上下游依赖")
```

- [ ] **Step 11: Run the new AssetStore tests and verify they pass**

Run:

```bash
python3 -m unittest \
  tests.test_assets.AssetStoreTest.test_cloud_api_catalog_includes_project_task_relation_and_get_table_apis \
  tests.test_assets.AssetStoreTest.test_project_cache_round_trip_and_query \
  tests.test_assets.AssetStoreTest.test_project_member_cache_replaces_one_project \
  tests.test_assets.AssetStoreTest.test_task_relation_cache_replaces_by_project_task_and_direction \
  tests.test_assets.AssetStoreTest.test_table_detail_fields_are_cached -v
```

Expected: PASS.

- [ ] **Step 12: Run the full AssetStore test file for regression**

Run:

```bash
python3 -m unittest tests.test_assets -v
```

Expected: PASS. If SQL column-list regressions occur, update the affected select to include the new `tables` columns and keep `_table_dict()` as the single row conversion point.

---

### Task 2: Extend WeData snapshot normalization and import

**Files:**
- Modify: `dlc_mcp/wedata.py`
- Test: `tests/test_wedata_import.py`

**Interfaces:**
- Consumes from Task 1:
  - `AssetStore.upsert_project(item: dict)`
  - `AssetStore.replace_project_members(project_id: str, members: list[dict])`
  - `AssetStore.replace_task_relations(project_id: str, task_id: str, direction: str, relations: list[dict])`
  - Extended `AssetStore.upsert_table(item: dict)`
- Produces:
  - `snapshot_from_api_dump(dump: dict) -> dict` includes keys `projects`, `project_members`, `task_relations`.
  - `import_wedata_snapshot(store, snapshot)` imports these new keys.

- [ ] **Step 1: Add failing normalization tests**

Append these methods to `WeDataImportTest` in `tests/test_wedata_import.py`:

```python
    def test_maps_projects_members_task_relations_and_table_detail_from_api_dump(self):
        snapshot = snapshot_from_api_dump(
            {
                "projects": {
                    "Response": {
                        "Data": {
                            "Items": [
                                {
                                    "ProjectId": "p1",
                                    "ProjectName": "prod",
                                    "DisplayName": "生产项目",
                                    "Description": "Production project",
                                    "Owner": "data-platform",
                                    "Status": "enabled",
                                    "Region": "ap-guangzhou",
                                    "CreateTime": "2026-07-01 10:00:00",
                                    "UpdateTime": "2026-07-02 10:00:00",
                                }
                            ]
                        }
                    }
                },
                "project_members": {
                    "p1": {
                        "Response": {
                            "Data": {
                                "Items": [
                                    {
                                        "UserId": "u1",
                                        "UserName": "zhangsan",
                                        "DisplayName": "张三",
                                        "RoleName": "管理员",
                                        "RoleId": "r1",
                                        "MemberType": "user",
                                        "JoinTime": "2026-07-01 11:00:00",
                                    }
                                ]
                            }
                        }
                    }
                },
                "task_relations": {
                    "p1:task_001:downstream": {
                        "Response": {
                            "Data": {
                                "Items": [
                                    {
                                        "TaskId": "task_002",
                                        "TaskName": "build_ads_customer",
                                        "DependencyType": "normal",
                                        "Owner": "etl-owner",
                                        "Status": "Y11",
                                    }
                                ]
                            }
                        }
                    }
                },
                "tables": {
                    "Response": {
                        "Data": {
                            "TableName": "ads_customer_revenue_daily",
                            "Guid": "guid_ads_customer_revenue_daily",
                            "ProjectId": "p1",
                            "DatabaseName": "bi",
                            "TableType": "MANAGED_TABLE",
                            "CatalogName": "DataLakeCatalog",
                            "SchemaName": "bi",
                            "Owner": "data-finance",
                            "Description": "Revenue table",
                            "Columns": [{"Name": "customer_id", "Type": "string", "Description": "Customer ID"}],
                        }
                    }
                },
            }
        )

        self.assertEqual(snapshot["projects"][0]["id"], "p1")
        self.assertEqual(snapshot["project_members"][0]["project_id"], "p1")
        self.assertEqual(snapshot["project_members"][0]["members"][0]["member_id"], "u1")
        self.assertEqual(snapshot["task_relations"][0]["project_id"], "p1")
        self.assertEqual(snapshot["task_relations"][0]["relations"][0]["related_task_id"], "task_002")
        self.assertEqual(snapshot["tables"][0]["project_id"], "p1")
        self.assertEqual(snapshot["tables"][0]["columns"][0]["name"], "customer_id")

    def test_imports_project_member_and_task_relation_snapshot(self):
        store = AssetStore(sqlite3.connect(":memory:"))
        store.init_schema()

        import_wedata_snapshot(
            store,
            {
                "projects": [{"id": "p1", "name": "prod", "display_name": "生产项目"}],
                "project_members": [
                    {"project_id": "p1", "members": [{"member_id": "u1", "member_name": "zhangsan", "role_id": "r1"}]}
                ],
                "task_relations": [
                    {
                        "project_id": "p1",
                        "task_id": "task_001",
                        "direction": "upstream",
                        "relations": [{"related_task_id": "task_000", "related_task_name": "build_ods_customer"}],
                    }
                ],
            },
        )

        self.assertEqual(store.get_project("p1")["display_name"], "生产项目")
        self.assertEqual(store.list_project_members("p1")["members"][0]["member_id"], "u1")
        self.assertEqual(store.list_task_relations("p1", "task_001", "upstream")["relations"][0]["related_task_id"], "task_000")
```

- [ ] **Step 2: Run new normalization tests and verify they fail**

Run:

```bash
python3 -m unittest \
  tests.test_wedata_import.WeDataImportTest.test_maps_projects_members_task_relations_and_table_detail_from_api_dump \
  tests.test_wedata_import.WeDataImportTest.test_imports_project_member_and_task_relation_snapshot -v
```

Expected: FAIL because `snapshot_from_api_dump()` does not populate the new keys and `import_wedata_snapshot()` does not import them.

- [ ] **Step 3: Extend `import_wedata_snapshot`**

In `dlc_mcp/wedata.py`, add these loops after the existing data-source import loops:

```python
    for project in snapshot.get("projects", []):
        store.upsert_project(project)

    for item in snapshot.get("project_members", []):
        store.replace_project_members(item["project_id"], item.get("members", []))

    for item in snapshot.get("task_relations", []):
        store.replace_task_relations(item["project_id"], item["task_id"], item["direction"], item.get("relations", []))
```

- [ ] **Step 4: Extend `snapshot_from_api_dump`**

Replace the return value in `snapshot_from_api_dump(dump)` with this structure, preserving existing keys:

```python
    return {
        "tables": tables,
        "tasks": tasks,
        "task_instances": [_task_instance_from_api(item) for item in _items(dump.get("task_instances", {}))],
        "table_partitions": [_partition_from_api(item) for item in _items(dump.get("table_partitions", {}))],
        "data_sources": data_sources + _builtin_data_sources(tables, data_sources),
        "data_source_tasks": _data_source_tasks_from_dump(dump.get("data_source_tasks", {})),
        "projects": [_project_from_api(item) for item in _items(dump.get("projects", {}))],
        "project_members": _project_members_from_dump(dump.get("project_members", {})),
        "task_relations": _task_relations_from_dump(dump.get("task_relations", {})),
        "lineage": [edge for edge in (_lineage_from_api(item) for item in _items(dump.get("lineage", {}))) if edge["upstream"] and edge["downstream"] and edge["upstream"] != edge["downstream"]],
        "quality_rules": [_quality_rule_from_api(item) for item in _items(dump.get("quality_rules", {}))],
    }
```

- [ ] **Step 5: Add project and member normalizers**

Add these functions after `_data_source_from_api` or another nearby normalizer section:

```python
def _project_from_api(item):
    project_id = str(_get(item, "ProjectId", "Id", "id"))
    return {
        "id": project_id,
        "name": _get(item, "ProjectName", "Name", "name"),
        "display_name": _get(item, "DisplayName", "Display", "Name", "ProjectName", "name"),
        "description": _get(item, "Description", "Desc", "description"),
        "owner": str(_get(item, "Owner", "OwnerName", "CreateUser", "Creator", "AdminUser", "owner")),
        "status": str(_get(item, "Status", "State", "ProjectStatus", "status")),
        "region": _get(item, "Region", "RegionId", "Area", "region"),
        "create_time": _get(item, "CreateTime", "CreatedAt", "CreateDate", "createTime"),
        "update_time": _get(item, "UpdateTime", "UpdatedAt", "ModifyTime", "updateTime"),
        "raw": item,
    }


def _project_members_from_dump(value):
    if not isinstance(value, dict):
        return []
    results = []
    for project_id, response in value.items():
        members = [_project_member_from_api(item) for item in _items(response)]
        results.append({"project_id": str(project_id), "members": members})
    return results


def _project_member_from_api(item):
    member_id = str(_get(item, "MemberId", "UserId", "UserUin", "Uin", "Id", "id"))
    role_id = str(_get(item, "RoleId", "ProjectRoleId", "roleId", default=""))
    if not role_id:
        role_id = _get(item, "RoleName", "ProjectRoleName", "roleName", default="")
    return {
        "member_id": member_id,
        "member_name": _get(item, "MemberName", "UserName", "Name", "UserAlias", "name"),
        "display_name": _get(item, "DisplayName", "NickName", "UserDisplayName", "UserName", "Name"),
        "role_name": _get(item, "RoleName", "ProjectRoleName", "roleName"),
        "role_id": str(role_id),
        "member_type": _get(item, "MemberType", "UserType", "Type", "type"),
        "join_time": _get(item, "JoinTime", "CreateTime", "CreatedAt", "createTime"),
        "raw": item,
    }
```

- [ ] **Step 6: Add task relation normalizers**

Add these functions after the project member normalizers:

```python
def _task_relations_from_dump(value):
    if not isinstance(value, dict):
        return []
    results = []
    for key, response in value.items():
        parts = str(key).split(":", 2)
        if len(parts) != 3:
            continue
        project_id, task_id, direction = parts
        results.append(
            {
                "project_id": project_id,
                "task_id": task_id,
                "direction": direction,
                "relations": [_task_relation_from_api(item, task_id) for item in _items(response)],
            }
        )
    return results


def _task_relation_from_api(item, source_task_id):
    related_task_id = str(_get(item, "TaskId", "RelatedTaskId", "Id", "id"))
    return {
        "related_task_id": related_task_id,
        "task_name": _get(item, "SourceTaskName", "CurrentTaskName", default=""),
        "related_task_name": _get(item, "TaskName", "RelatedTaskName", "Name", "name"),
        "dependency_type": _get(item, "DependencyType", "Dependency", "Type", "type"),
        "task_type": str(_get(item, "TaskType", "TaskTypeId", "type", default="")),
        "owner": str(_get(item, "Owner", "OwnerName", "ResponsibleUser", "owner")),
        "status": str(_get(item, "Status", "State", "TaskLatestVersionStatus", "status")),
        "raw": item,
    }
```

- [ ] **Step 7: Extend table normalizer for GetTable fields**

In `_table_from_api(item)`, keep the existing fields and add these keys to the returned dictionary:

```python
        "project_id": str(_get(item, "ProjectId", "ProjectID", "projectId", default="")),
        "table_type": _get(item, "TableType", "Type", "TableKind", "tableType"),
        "catalog_name": _get(item, "CatalogName", "Catalog", "catalogName"),
        "schema_name": _get(item, "SchemaName", "Schema", "schemaName", default=database),
        "raw": item,
```

Also update `_items(response)` to treat a detail object as a single item. Replace the end of `_items()` with:

```python
    if isinstance(data, dict):
        for key in ("Items", "Rows", "List", "Records"):
            if isinstance(data.get(key), list):
                return data[key]
        for key in ("Project", "Table", "Detail"):
            if isinstance(data.get(key), dict):
                return [data[key]]
        if any(name in data for name in ("ProjectId", "TableName", "Guid", "Name")):
            return [data]
    return data if isinstance(data, list) else []
```

- [ ] **Step 8: Run new normalization/import tests and verify they pass**

Run:

```bash
python3 -m unittest \
  tests.test_wedata_import.WeDataImportTest.test_maps_projects_members_task_relations_and_table_detail_from_api_dump \
  tests.test_wedata_import.WeDataImportTest.test_imports_project_member_and_task_relation_snapshot -v
```

Expected: PASS.

- [ ] **Step 9: Run full WeData import tests for regression**

Run:

```bash
python3 -m unittest tests.test_wedata_import -v
```

Expected: PASS.

---

### Task 3: Add LiveWeData sync methods

**Files:**
- Modify: `dlc_mcp/live.py`
- Test: `tests/test_mcp.py`

**Interfaces:**
- Consumes from Task 2:
  - `snapshot_from_api_dump()` accepts `projects`, `project_members`, `task_relations`, and detail `tables` payloads.
  - `import_wedata_snapshot()` persists those facts.
- Produces:
  - `LiveWeData.project_id_or_default(project_id: str = "") -> str`
  - `LiveWeData.sync_projects(query: str = "") -> None`
  - `LiveWeData.sync_project(project_id: str = "") -> None`
  - `LiveWeData.sync_project_members(project_id: str = "") -> None`
  - `LiveWeData.sync_task_relations(task_id: str, direction: str, project_id: str = "") -> None`
  - `LiveWeData.sync_table_detail(table_name: str = "", table_guid: str = "", project_id: str = "") -> None`

- [ ] **Step 1: Add fake-client test for live sync methods**

In `tests/test_mcp.py`, add these action responses to `FakeWeDataClient.call()` before the final return:

```python
        if action == "ListProjects":
            return {"Response": {"Data": {"Items": [{"ProjectId": "project", "ProjectName": "prod", "Owner": "data-platform"}], "TotalPageNumber": 1}}}
        if action == "GetProject":
            return {"Response": {"Data": {"ProjectId": payload.get("ProjectId"), "ProjectName": "prod", "Owner": "data-platform", "Status": "enabled"}}}
        if action == "ListProjectMembers":
            return {"Response": {"Data": {"Items": [{"UserId": "u1", "UserName": "zhangsan", "RoleName": "管理员"}], "TotalPageNumber": 1}}}
        if action == "ListDownstreamTasks":
            return {"Response": {"Data": {"Items": [{"TaskId": "task_down", "TaskName": "downstream_task"}], "TotalPageNumber": 1}}}
        if action == "ListUpstreamTasks":
            return {"Response": {"Data": {"Items": [{"TaskId": "task_up", "TaskName": "upstream_task"}], "TotalPageNumber": 1}}}
        if action == "GetTable":
            return {"Response": {"Data": {"Guid": payload.get("TableGuid", "guid_dim_customer"), "TableName": "dim_customer", "ProjectId": payload.get("ProjectId", "project"), "DatabaseName": "dw", "Owner": "data-customer"}}}
```

Then append this test method to `McpTest`:

```python
    def test_live_wedata_syncs_new_api_families_with_default_project_id(self):
        client = FakeWeDataClient()
        with patch.dict(os.environ, {"WEDATA_PROJECT_ID": "project"}, clear=False):
            live = LiveWeData(self.store, client=client)
            live.sync_projects()
            live.sync_project()
            live.sync_project_members()
            live.sync_task_relations("task_001", "downstream")
            live.sync_task_relations("task_001", "upstream")
            live.sync_table_detail(table_guid="guid_dim_customer")

        actions = [action for action, payload in client.calls]
        self.assertIn("ListProjects", actions)
        self.assertIn("GetProject", actions)
        self.assertIn("ListProjectMembers", actions)
        self.assertIn("ListDownstreamTasks", actions)
        self.assertIn("ListUpstreamTasks", actions)
        self.assertIn("GetTable", actions)
        self.assertEqual(self.store.get_project("project")["name"], "prod")
        self.assertEqual(self.store.list_project_members("project")["members"][0]["member_id"], "u1")
        self.assertEqual(self.store.list_task_relations("project", "task_001", "downstream")["relations"][0]["related_task_id"], "task_down")
```

- [ ] **Step 2: Run the live sync test and verify it fails**

Run:

```bash
python3 -m unittest tests.test_mcp.McpTest.test_live_wedata_syncs_new_api_families_with_default_project_id -v
```

Expected: FAIL with missing `LiveWeData.sync_projects`.

- [ ] **Step 3: Add project ID helper and sync methods**

In `dlc_mcp/live.py`, add these methods inside `class LiveWeData` after `sync_data_sources()`:

```python
    def project_id_or_default(self, project_id=""):
        value = project_id or self.project_id
        if not value:
            raise RuntimeError("missing_project_id")
        return value

    def sync_projects(self, query=""):
        payload = {}
        if query:
            payload["Keyword"] = query
        data = self._list_all("ListProjects", payload)
        self._import({"projects": data})

    def sync_project(self, project_id=""):
        resolved_project_id = self.project_id_or_default(project_id)
        data = self.client.call("GetProject", {"ProjectId": resolved_project_id})
        self._import({"projects": data})

    def sync_project_members(self, project_id=""):
        resolved_project_id = self.project_id_or_default(project_id)
        data = self._list_all("ListProjectMembers", {"ProjectId": resolved_project_id})
        self._import({"project_members": {resolved_project_id: data}})

    def sync_task_relations(self, task_id, direction, project_id=""):
        resolved_project_id = self.project_id_or_default(project_id)
        action = "ListDownstreamTasks" if direction == "downstream" else "ListUpstreamTasks"
        data = self._list_all(action, {"ProjectId": resolved_project_id, "TaskId": task_id})
        self._import({"task_relations": {f"{resolved_project_id}:{task_id}:{direction}": data}})

    def sync_table_detail(self, table_name="", table_guid="", project_id=""):
        resolved_project_id = self.project_id_or_default(project_id)
        payload = {"ProjectId": resolved_project_id}
        if table_guid:
            payload["TableGuid"] = table_guid
        if table_name:
            payload["TableName"] = table_name
        data = self.client.call("GetTable", payload)
        self._import({"tables": data})
```

- [ ] **Step 4: Run the live sync test and verify it passes**

Run:

```bash
python3 -m unittest tests.test_mcp.McpTest.test_live_wedata_syncs_new_api_families_with_default_project_id -v
```

Expected: PASS.

- [ ] **Step 5: Run MCP tests for regression after LiveWeData changes**

Run:

```bash
python3 -m unittest tests.test_mcp -v
```

Expected: PASS.

---

### Task 4: Register MCP tools and add cache-first call behavior

**Files:**
- Modify: `dlc_mcp/mcp.py`
- Test: `tests/test_mcp.py`

**Interfaces:**
- Consumes from Task 1:
  - `store.list_projects(query)`
  - `store.get_project(project_id)`
  - `store.list_project_members(project_id)`
  - `store.list_task_relations(project_id, task_id, direction)`
  - `store.get_table_detail(table_name, table_guid)`
- Consumes from Task 3:
  - `live.sync_projects(query)`
  - `live.sync_project(project_id)`
  - `live.sync_project_members(project_id)`
  - `live.sync_task_relations(task_id, direction, project_id)`
  - `live.sync_table_detail(table_name, table_guid, project_id)`
- Produces six user-facing MCP tools listed in `TOOLS`.

- [ ] **Step 1: Add failing tools/list test assertions**

In `tests/test_mcp.py`, in `test_lists_tools`, add these assertions after existing tool assertions:

```python
        self.assertIn("list_projects", [tool["name"] for tool in response["result"]["tools"]])
        self.assertIn("get_project", [tool["name"] for tool in response["result"]["tools"]])
        self.assertIn("list_project_members", [tool["name"] for tool in response["result"]["tools"]])
        self.assertIn("list_downstream_tasks", [tool["name"] for tool in response["result"]["tools"]])
        self.assertIn("list_upstream_tasks", [tool["name"] for tool in response["result"]["tools"]])
        self.assertIn("get_table", [tool["name"] for tool in response["result"]["tools"]])
```

- [ ] **Step 2: Add failing tools/call tests for cached data and validation**

Append these tests to `McpTest`:

```python
    def test_calls_project_tools_from_cache(self):
        self.store.upsert_project({"id": "project", "name": "prod", "display_name": "生产项目", "owner": "data-platform", "status": "enabled"})
        self.store.replace_project_members("project", [{"member_id": "u1", "member_name": "zhangsan", "role_name": "管理员", "role_id": "r1"}])

        list_response = handle_request(self.store, {"jsonrpc": "2.0", "id": 31, "method": "tools/call", "params": {"name": "list_projects", "arguments": {"query": "生产"}}})
        get_response = handle_request(self.store, {"jsonrpc": "2.0", "id": 32, "method": "tools/call", "params": {"name": "get_project", "arguments": {"project_id": "project"}}})
        members_response = handle_request(self.store, {"jsonrpc": "2.0", "id": 33, "method": "tools/call", "params": {"name": "list_project_members", "arguments": {"project_id": "project"}}})

        self.assertIn("项目列表", list_response["result"]["content"][0]["text"])
        self.assertIn("生产项目", list_response["result"]["content"][0]["text"])
        self.assertIn("项目详情", get_response["result"]["content"][0]["text"])
        self.assertIn("data-platform", get_response["result"]["content"][0]["text"])
        self.assertIn("项目成员", members_response["result"]["content"][0]["text"])
        self.assertIn("zhangsan", members_response["result"]["content"][0]["text"])

    def test_calls_task_relation_and_get_table_tools_from_cache(self):
        self.store.replace_task_relations("project", "task_001", "downstream", [{"related_task_id": "task_002", "related_task_name": "build_ads_customer"}])
        self.store.replace_task_relations("project", "task_001", "upstream", [{"related_task_id": "task_000", "related_task_name": "build_ods_customer"}])
        self.store.upsert_table({"name": "dim_customer", "guid": "guid_dim_customer", "project_id": "project", "database": "dw", "owner": "data-customer", "table_type": "MANAGED_TABLE"})

        downstream = handle_request(self.store, {"jsonrpc": "2.0", "id": 34, "method": "tools/call", "params": {"name": "list_downstream_tasks", "arguments": {"project_id": "project", "task_id": "task_001"}}})
        upstream = handle_request(self.store, {"jsonrpc": "2.0", "id": 35, "method": "tools/call", "params": {"name": "list_upstream_tasks", "arguments": {"project_id": "project", "task_id": "task_001"}}})
        table = handle_request(self.store, {"jsonrpc": "2.0", "id": 36, "method": "tools/call", "params": {"name": "get_table", "arguments": {"table_name": "dim_customer"}}})

        self.assertIn("下游任务", downstream["result"]["content"][0]["text"])
        self.assertIn("task_002", downstream["result"]["content"][0]["text"])
        self.assertIn("上游任务", upstream["result"]["content"][0]["text"])
        self.assertIn("task_000", upstream["result"]["content"][0]["text"])
        self.assertIn("表元数据详情", table["result"]["content"][0]["text"])
        self.assertIn("dim_customer", table["result"]["content"][0]["text"])

    def test_new_tools_return_readable_validation_errors(self):
        with patch.dict(os.environ, {}, clear=True):
            project = handle_request(self.store, {"jsonrpc": "2.0", "id": 37, "method": "tools/call", "params": {"name": "get_project", "arguments": {}}})
        table = handle_request(self.store, {"jsonrpc": "2.0", "id": 38, "method": "tools/call", "params": {"name": "get_table", "arguments": {}}})

        self.assertIn("missing_project_id", project["result"]["content"][0]["text"])
        self.assertIn("missing_table_identity", table["result"]["content"][0]["text"])
```

- [ ] **Step 3: Run new MCP tests and verify they fail**

Run:

```bash
python3 -m unittest \
  tests.test_mcp.McpTest.test_lists_tools \
  tests.test_mcp.McpTest.test_calls_project_tools_from_cache \
  tests.test_mcp.McpTest.test_calls_task_relation_and_get_table_tools_from_cache \
  tests.test_mcp.McpTest.test_new_tools_return_readable_validation_errors -v
```

Expected: FAIL because the tools are not registered.

- [ ] **Step 4: Add tool schemas to `TOOLS`**

In `dlc_mcp/mcp.py`, add these entries to the `TOOLS` dictionary before `list_metadata`:

```python
    "list_projects": {
        "description": "List WeData projects cached from Tencent Cloud ListProjects.",
        "schema": {"type": "object", "properties": {"query": {"type": "string"}, "live": {"type": "boolean"}}},
    },
    "get_project": {
        "description": "Return one WeData project by project_id, defaulting to WEDATA_PROJECT_ID.",
        "schema": {"type": "object", "properties": {"project_id": {"type": "string"}, "live": {"type": "boolean"}}},
    },
    "list_project_members": {
        "description": "List members and roles for a WeData project, defaulting to WEDATA_PROJECT_ID.",
        "schema": {"type": "object", "properties": {"project_id": {"type": "string"}, "live": {"type": "boolean"}}},
    },
    "list_downstream_tasks": {
        "description": "List downstream WeData tasks for a task id.",
        "schema": {"type": "object", "properties": {"task_id": {"type": "string"}, "project_id": {"type": "string"}, "live": {"type": "boolean"}}, "required": ["task_id"]},
    },
    "list_upstream_tasks": {
        "description": "List upstream WeData tasks for a task id.",
        "schema": {"type": "object", "properties": {"task_id": {"type": "string"}, "project_id": {"type": "string"}, "live": {"type": "boolean"}}, "required": ["task_id"]},
    },
    "get_table": {
        "description": "Return Tencent Cloud WeData table metadata detail by table_name or table_guid.",
        "schema": {"type": "object", "properties": {"table_name": {"type": "string"}, "table_guid": {"type": "string"}, "project_id": {"type": "string"}, "live": {"type": "boolean"}}},
    },
```

- [ ] **Step 5: Add project ID and error helpers**

In `dlc_mcp/mcp.py`, add these helper functions near `_error()`:

```python
def _project_id_arg(args):
    return args.get("project_id") or os.environ.get("WEDATA_PROJECT_ID", "")


def _error_data(error, **fields):
    return {"error": error, **fields}
```

`mcp.py` already imports `os`; keep that import.

- [ ] **Step 6: Add `_call_tool` branches for the six tools**

In `_call_tool`, add these branches before `elif name == "list_metadata":`:

```python
    elif name == "list_projects":
        data = store.list_projects(args.get("query", ""))
        if live and (args.get("live") or not data.get("results")):
            live.sync_projects(args.get("query", ""))
            data = store.list_projects(args.get("query", ""))
    elif name == "get_project":
        project_id = _project_id_arg(args)
        if not project_id:
            data = _error_data("missing_project_id")
        else:
            data = store.get_project(project_id)
            if live and (args.get("live") or data.get("error")):
                live.sync_project(project_id)
                data = store.get_project(project_id)
    elif name == "list_project_members":
        project_id = _project_id_arg(args)
        if not project_id:
            data = _error_data("missing_project_id")
        else:
            data = store.list_project_members(project_id)
            if live and (args.get("live") or not data.get("members")):
                live.sync_project_members(project_id)
                data = store.list_project_members(project_id)
    elif name == "list_downstream_tasks":
        project_id = _project_id_arg(args)
        if not project_id:
            data = _error_data("missing_project_id")
        else:
            data = store.list_task_relations(project_id, args["task_id"], "downstream")
            if live and (args.get("live") or not data.get("relations")):
                live.sync_task_relations(args["task_id"], "downstream", project_id)
                data = store.list_task_relations(project_id, args["task_id"], "downstream")
    elif name == "list_upstream_tasks":
        project_id = _project_id_arg(args)
        if not project_id:
            data = _error_data("missing_project_id")
        else:
            data = store.list_task_relations(project_id, args["task_id"], "upstream")
            if live and (args.get("live") or not data.get("relations")):
                live.sync_task_relations(args["task_id"], "upstream", project_id)
                data = store.list_task_relations(project_id, args["task_id"], "upstream")
    elif name == "get_table":
        table_name = args.get("table_name", "")
        table_guid = args.get("table_guid", "")
        project_id = _project_id_arg(args)
        if not table_name and not table_guid:
            data = _error_data("missing_table_identity")
        elif not project_id:
            data = _error_data("missing_project_id")
        else:
            data = store.get_table_detail(table_name, table_guid)
            cached_guid = table_guid or (data.get("table") or {}).get("guid", "")
            if live and args.get("live"):
                if cached_guid or table_name:
                    live.sync_table_detail(table_name=table_name, table_guid=cached_guid, project_id=project_id)
                    data = store.get_table_detail(table_name, cached_guid)
                else:
                    data = _error_data("table_guid_required", "table_name", table_name)
```

- [ ] **Step 7: Add Markdown formatters**

In `_format_markdown(tool_name, data)`, add these branches after the existing error branch and before `list_data_sources`:

```python
    if tool_name == "list_projects":
        rows = data.get("results", [])
        return _section("项目列表", [f"查询：`{_cell(data.get('query', ''))}`", f"数量：{len(rows)}"]) + "\n\n" + _table(
            ["项目ID", "名称", "展示名", "负责人", "状态", "区域", "创建时间", "更新时间"],
            [[r.get("id"), r.get("name"), r.get("display_name"), r.get("owner"), r.get("status"), r.get("region"), r.get("create_time"), r.get("update_time")] for r in rows],
        )
    if tool_name == "get_project":
        return _section(
            "项目详情",
            [
                f"项目ID：`{_cell(data.get('id'))}`",
                f"名称：**{_cell(data.get('name'))}**",
                f"展示名：{_cell(data.get('display_name'))}",
                f"负责人：`{_cell(data.get('owner'))}`",
                f"状态：`{_cell(data.get('status'))}`",
                f"区域：`{_cell(data.get('region'))}`",
                f"创建时间：{_cell(data.get('create_time'))}",
                f"更新时间：{_cell(data.get('update_time'))}",
                f"描述：{_cell(data.get('description'))}",
            ],
        )
    if tool_name == "list_project_members":
        rows = data.get("members", [])
        return _section("项目成员", [f"项目ID：`{_cell(data.get('project_id'))}`", f"成员数：{len(rows)}"]) + "\n\n" + _table(
            ["成员ID", "账号", "展示名", "角色", "角色ID", "类型", "加入时间"],
            [[r.get("member_id"), r.get("member_name"), r.get("display_name"), r.get("role_name"), r.get("role_id"), r.get("member_type"), r.get("join_time")] for r in rows],
        )
    if tool_name in {"list_downstream_tasks", "list_upstream_tasks"}:
        rows = data.get("relations", [])
        title = "下游任务" if tool_name == "list_downstream_tasks" else "上游任务"
        return _section(title, [f"项目ID：`{_cell(data.get('project_id'))}`", f"TaskId：`{_cell(data.get('task_id'))}`", f"任务数：{len(rows)}"]) + "\n\n" + _table(
            ["相关TaskId", "任务名", "依赖类型", "负责人", "状态"],
            [[r.get("related_task_id"), r.get("related_task_name"), r.get("dependency_type"), r.get("owner"), r.get("status")] for r in rows],
        )
    if tool_name == "get_table":
        table = data.get("table", {})
        columns = data.get("columns", [])
        return _section(
            "表元数据详情",
            [
                f"表名：**{_cell(table.get('name'))}**",
                f"GUID：`{_cell(table.get('guid'))}`",
                f"项目ID：`{_cell(table.get('project_id'))}`",
                f"库：`{_cell(table.get('database'))}`",
                f"Catalog：`{_cell(table.get('catalog_name'))}`",
                f"Schema：`{_cell(table.get('schema_name'))}`",
                f"类型：`{_cell(table.get('table_type'))}`",
                f"数据源：`{_cell(table.get('data_source_id'))}`",
                f"负责人：`{_cell(table.get('owner'))}`",
                f"描述：{_cell(table.get('description'))}",
                f"字段数：{len(columns)}",
            ],
        ) + "\n\n" + _table(["字段名", "类型", "说明"], [[c.get("name"), c.get("type"), c.get("description")] for c in columns[:20]])
```

- [ ] **Step 8: Run new MCP tests and verify they pass**

Run:

```bash
python3 -m unittest \
  tests.test_mcp.McpTest.test_lists_tools \
  tests.test_mcp.McpTest.test_calls_project_tools_from_cache \
  tests.test_mcp.McpTest.test_calls_task_relation_and_get_table_tools_from_cache \
  tests.test_mcp.McpTest.test_new_tools_return_readable_validation_errors -v
```

Expected: PASS.

- [ ] **Step 9: Run full MCP tests for regression**

Run:

```bash
python3 -m unittest tests.test_mcp -v
```

Expected: PASS.

---

### Task 5: Document tools and run final verification

**Files:**
- Modify: `README.md`
- Test: `tests/test_docs.py`

**Interfaces:**
- Consumes from Task 4: six tool names exist in `dlc_mcp.mcp.TOOLS`.
- Produces: README tool table lists all six new tools so `DocsTest.test_readme_lists_all_mcp_tools` passes.

- [ ] **Step 1: Add README tool rows**

In `README.md`, in the Tools table after `list_data_source_tasks(data_source_id, live)`, add:

```markdown
| `list_projects(query, live)` | List WeData projects cached from Tencent Cloud ListProjects. |
| `get_project(project_id, live)` | Return one WeData project, defaulting to `WEDATA_PROJECT_ID` when omitted. |
| `list_project_members(project_id, live)` | List members and roles for a WeData project. |
| `list_downstream_tasks(task_id, project_id, live)` | List downstream WeData task dependencies for a task. |
| `list_upstream_tasks(task_id, project_id, live)` | List upstream WeData task dependencies for a task. |
| `get_table(table_name/table_guid, project_id, live)` | Return Tencent Cloud WeData table metadata detail. |
```

- [ ] **Step 2: Run docs tests and verify they pass**

Run:

```bash
python3 -m unittest tests.test_docs -v
```

Expected: PASS.

- [ ] **Step 3: Run full Python test suite**

Run:

```bash
python3 -m unittest discover -s tests -v
```

Expected: PASS. If a test fails due to the new `tables` column list, update only the affected SQL select to include `project_id`, `table_type`, `catalog_name`, `schema_name`, and `raw_json`, then rerun the failing test first.

- [ ] **Step 4: Run Node syntax check**

Run:

```bash
node --check bin/dlc-mcp.js
```

Expected: no output and exit code 0.

- [ ] **Step 5: Run package dry-run**

Run:

```bash
npm pack --dry-run
```

Expected: command exits 0 and lists package contents.

- [ ] **Step 6: Inspect working tree**

Run:

```bash
git status --short
```

Expected: modified files include the planned Python tests/source files, README, this plan file, and the design spec. Do not commit unless the user explicitly asks.

---

## Self-Review

Spec coverage:

- API catalog registration is covered by Task 1.
- SQLite caching for projects, members, task relations, and table detail is covered by Task 1.
- WeData response normalization and `raw_json` preservation are covered by Task 2.
- Live Connector methods and Tencent Cloud Action mapping are covered by Task 3.
- User-facing MCP tools, project ID defaults, validation errors, and Markdown output are covered by Task 4.
- README updates and final verification are covered by Task 5.

Placeholder scan:

- The plan contains no TBD markers, no unfinished sections, and no unspecified test/code steps.
- The plan intentionally avoids commit commands because the session-level developer instruction says to commit only when the user asks.

Type consistency:

- Store method names used by `live.py` and `mcp.py` match Task 1 outputs.
- Snapshot keys used by `live.py` match Task 2 outputs: `projects`, `project_members`, `task_relations`, and `tables`.
- MCP tool names match the approved snake_case names and README rows.
