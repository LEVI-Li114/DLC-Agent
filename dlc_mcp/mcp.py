import json


TOOLS = {
    "search_assets": {
        "description": "Search tables by name, domain, or description.",
        "schema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
    },
    "search_tasks": {
        "description": "Search WeData ETL tasks by id, name, owner, or status.",
        "schema": {"type": "object", "properties": {"query": {"type": "string"}, "live": {"type": "boolean"}}, "required": ["query"]},
    },
    "get_table_profile": {
        "description": "Return table metadata, columns, lineage, quality status, and core-table decision.",
        "schema": {"type": "object", "properties": {"table_name": {"type": "string"}, "live": {"type": "boolean"}}, "required": ["table_name"]},
    },
    "list_table_columns": {
        "description": "List fields for a table.",
        "schema": {"type": "object", "properties": {"table_name": {"type": "string"}, "live": {"type": "boolean"}}, "required": ["table_name"]},
    },
    "get_quality_status": {
        "description": "Return quality monitoring rules and latest status for a table.",
        "schema": {"type": "object", "properties": {"table_name": {"type": "string"}, "live": {"type": "boolean"}}, "required": ["table_name"]},
    },
    "get_table_lineage": {
        "description": "Return upstream and downstream assets for a table.",
        "schema": {"type": "object", "properties": {"table_name": {"type": "string"}, "live": {"type": "boolean"}}, "required": ["table_name"]},
    },
    "get_table_tasks": {
        "description": "Return ETL tasks that read from or produce a table.",
        "schema": {"type": "object", "properties": {"table_name": {"type": "string"}}, "required": ["table_name"]},
    },
    "get_task_runs": {
        "description": "Return task instances by task id or exact task name, with optional instance date filter.",
        "schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string"},
                "task_name": {"type": "string"},
                "instance_date": {"type": "string"},
                "limit": {"type": "integer"},
                "live": {"type": "boolean"},
            },
        },
    },
    "list_data_sources": {
        "description": "List data sources and their stored configuration summary.",
        "schema": {"type": "object", "properties": {"query": {"type": "string"}, "live": {"type": "boolean"}}},
    },
    "get_data_source": {
        "description": "Return one data source by id, including configuration details stored in the fact database.",
        "schema": {"type": "object", "properties": {"data_source_id": {"type": "string"}, "live": {"type": "boolean"}}, "required": ["data_source_id"]},
    },
    "list_metadata": {
        "description": "List imported databases and table metadata.",
        "schema": {"type": "object", "properties": {}},
    },
    "is_core_table": {
        "description": "Decide whether a table is core and return explainable scoring reasons.",
        "schema": {"type": "object", "properties": {"table_name": {"type": "string"}}, "required": ["table_name"]},
    },
}


def handle_request(store, request, live=None):
    method = request.get("method")
    if method == "initialize":
        return _result(request, {"protocolVersion": "2024-11-05", "serverInfo": {"name": "dlc-mcp", "version": "0.1.0"}, "capabilities": {"tools": {}}})
    if method == "tools/list":
        tools = [
            {
                "name": name,
                "description": spec["description"],
                "inputSchema": spec["schema"],
            }
            for name, spec in TOOLS.items()
        ]
        return _result(request, {"tools": tools})
    if method == "tools/call":
        return _call_tool(store, request, live)
    if method == "notifications/initialized":
        return None
    return _error(request, -32601, "method_not_found")


def _call_tool(store, request, live=None):
    params = request.get("params") or {}
    name = params.get("name")
    args = params.get("arguments") or {}
    if name not in TOOLS:
        return _error(request, -32602, "unknown_tool")

    if name == "search_assets":
        data = store.search_assets(args["query"])
    elif name == "search_tasks":
        data = store.search_tasks(args["query"])
        if live and (args.get("live") or not data["results"]):
            live.sync_tasks(args["query"])
            data = store.search_tasks(args["query"])
    elif name == "get_table_profile":
        data = store.get_table_profile(args["table_name"])
        if live and (args.get("live") or data.get("error") or not data.get("columns")):
            live.sync_table(args["table_name"])
            data = store.get_table_profile(args["table_name"])
    elif name == "list_table_columns":
        data = store.list_table_columns(args["table_name"])
        if live and (args.get("live") or data.get("error") or not data.get("columns")):
            live.sync_table(args["table_name"])
            data = store.list_table_columns(args["table_name"])
    elif name == "get_quality_status":
        data = store.get_quality_status(args["table_name"])
        if live and args.get("live"):
            live.sync_table(args["table_name"])
            data = store.get_quality_status(args["table_name"])
    elif name == "get_table_lineage":
        data = store.get_table_lineage(args["table_name"])
        if live and (args.get("live") or not data["downstream"]):
            live.sync_table(args["table_name"])
            data = store.get_table_lineage(args["table_name"])
    elif name == "get_table_tasks":
        data = store.get_table_tasks(args["table_name"])
    elif name == "get_task_runs":
        if args.get("task_name"):
            data = store.get_task_runs_by_name(args["task_name"], args.get("limit", 10), args.get("instance_date", ""))
            if live and (args.get("live") or not data.get("runs")):
                live.sync_task_runs(task_name=args["task_name"], instance_date=args.get("instance_date", ""))
                data = store.get_task_runs_by_name(args["task_name"], args.get("limit", 10), args.get("instance_date", ""))
        else:
            data = store.get_task_runs(args["task_id"], args.get("limit", 10), args.get("instance_date", ""))
            if live and (args.get("live") or not data.get("runs")):
                live.sync_task_runs(task_id=args["task_id"], instance_date=args.get("instance_date", ""))
                data = store.get_task_runs(args["task_id"], args.get("limit", 10), args.get("instance_date", ""))
    elif name == "list_data_sources":
        data = store.list_data_sources(args.get("query", ""))
        if live and (args.get("live") or not data["results"]):
            live.sync_data_sources(args.get("query", ""))
            data = store.list_data_sources(args.get("query", ""))
    elif name == "get_data_source":
        data = store.get_data_source(args["data_source_id"])
        if live and (args.get("live") or data.get("error")):
            live.sync_data_sources(args["data_source_id"])
            data = store.get_data_source(args["data_source_id"])
    elif name == "list_metadata":
        data = store.list_metadata()
    else:
        data = store.is_core_table(args["table_name"])

    return _result(request, {"content": [{"type": "text", "text": _format_markdown(name, data)}]})


def _result(request, result):
    return {"jsonrpc": "2.0", "id": request.get("id"), "result": result}


def _error(request, code, message):
    return {"jsonrpc": "2.0", "id": request.get("id"), "error": {"code": code, "message": message}}


def _format_markdown(tool_name, data):
    if isinstance(data, dict) and data.get("error"):
        return f"**未找到**\n\n- 错误：`{_cell(data['error'])}`\n" + "\n".join(f"- {k}: `{_cell(v)}`" for k, v in data.items() if k != "error")
    if tool_name == "list_data_sources":
        rows = data.get("results", [])
        return _section("数据源列表", [f"查询：`{_cell(data.get('query', ''))}`", f"数量：{len(rows)}"]) + "\n\n" + _table(
            ["ID", "名称", "类型", "负责人", "花名", "任务数", "库", "Host", "URL"],
            [[r.get("id"), r.get("name"), r.get("type"), r.get("owner"), r.get("owner_name"), r.get("task_count"), r.get("config", {}).get("database"), r.get("config", {}).get("host"), r.get("config", {}).get("url")] for r in rows],
        )
    if tool_name == "get_data_source":
        config = data.get("config", {})
        return _section("数据源详情", [f"ID：`{_cell(data.get('id'))}`", f"名称：**{_cell(data.get('name'))}**", f"类型：`{_cell(data.get('type'))}`", f"负责人：`{_cell(data.get('owner'))}` / `{_cell(data.get('owner_name'))}`", f"已关联任务数：**{data.get('task_count', 0)}**", f"描述：{_cell(data.get('description'))}"]) + "\n\n" + _table(
            ["配置项", "值"],
            [[k, v] for k, v in config.items()],
        )
    if tool_name == "search_tasks":
        rows = data.get("results", [])
        return _section("任务搜索结果", [f"查询：`{_cell(data.get('query'))}`", f"数量：{len(rows)}"]) + "\n\n" + _table(
            ["TaskId", "任务名", "类型", "负责人", "状态", "产出表"],
            [[r.get("id"), r.get("name"), r.get("task_type"), r.get("owner"), r.get("status"), ", ".join(r.get("outputs") or [])] for r in rows],
        )
    if tool_name == "get_task_runs":
        rows = data.get("runs", [])
        title = f"任务运行实例：{data.get('task_name') or data.get('task_id')}"
        return _section(title, [f"TaskId：`{_cell(data.get('task_id'))}`", f"数量：{len(rows)}"]) + "\n\n" + _table(
            ["实例日期", "开始时间", "结束时间", "耗时秒", "状态", "实例ID"],
            [[r.get("instance_date"), r.get("start_time"), r.get("end_time"), r.get("duration_seconds"), r.get("status"), r.get("instance_id")] for r in rows],
        )
    if tool_name == "list_table_columns":
        return _section(f"字段列表：{data.get('table_name')}", [f"字段数：{len(data.get('columns', []))}"]) + "\n\n" + _table(
            ["字段名", "类型", "说明"],
            [[c.get("name"), c.get("type"), c.get("description")] for c in data.get("columns", [])],
        )
    if tool_name == "get_quality_status":
        return _section(f"质量状态：{data.get('table_name')}", [f"是否有监控：{data.get('has_quality_monitoring')}", f"规则数：{data.get('rule_count')}", f"最新状态：`{_cell(data.get('latest_status'))}`"]) + "\n\n" + _table(
            ["规则名", "类型", "目标", "启用", "状态", "检查时间"],
            [[r.get("rule_name"), r.get("rule_type"), r.get("target"), r.get("enabled"), r.get("last_status"), r.get("last_checked_at")] for r in data.get("rules", [])],
        )
    if tool_name == "get_table_lineage":
        upstream = _table(["上游", "经由"], [[r.get("upstream"), r.get("via")] for r in data.get("upstream", [])])
        downstream = _table(["下游", "经由"], [[r.get("downstream"), r.get("via")] for r in data.get("downstream", [])])
        return f"**血缘关系**\n\n上游：\n\n{upstream}\n\n下游：\n\n{downstream}"
    if tool_name == "get_table_profile":
        table = data.get("table", {})
        core = data.get("core", {})
        return "\n\n".join(
            [
                _section(
                    f"表画像：{table.get('name')}",
                    [
                        f"库：`{_cell(table.get('database'))}`",
                        f"层级：`{_cell(table.get('layer'))}`",
                        f"领域：`{_cell(table.get('domain'))}`",
                        f"负责人：`{_cell(table.get('owner'))}`",
                        f"描述：{_cell(table.get('description'))}",
                        f"核心表：**{core.get('is_core')}**，分数：**{core.get('score')}**，原因：{', '.join(core.get('reasons') or [])}",
                    ],
                ),
                _format_markdown("list_table_columns", {"table_name": table.get("name"), "columns": data.get("columns", [])}),
                _format_markdown("get_table_lineage", data.get("lineage", {})),
                _format_markdown("get_quality_status", {"table_name": table.get("name"), "has_quality_monitoring": bool(data.get("quality", {}).get("rule_count")), **data.get("quality", {})}),
                _section("相关任务", []) + "\n\n" + _table(["TaskId", "任务名", "方向", "状态"], [[t.get("id"), t.get("name"), t.get("direction"), t.get("status")] for t in data.get("tasks", [])]),
            ]
        )
    if tool_name == "is_core_table":
        return _section(f"核心表判断：{data.get('table_name')}", [f"是否核心：**{data.get('is_core')}**", f"分数：**{data.get('score')}**", f"原因：{', '.join(data.get('reasons') or [])}"])
    return "```json\n" + json.dumps(data, ensure_ascii=False, indent=2) + "\n```"


def _section(title, lines):
    body = "\n".join(f"- {line}" for line in lines if line)
    return f"**{title}**" + (f"\n\n{body}" if body else "")


def _table(headers, rows):
    if not rows:
        return "_无数据_"
    header = "| " + " | ".join(headers) + " |"
    sep = "| " + " | ".join(["---"] * len(headers)) + " |"
    body = ["| " + " | ".join(_cell(v) for v in row) + " |" for row in rows]
    return "\n".join([header, sep, *body])


def _cell(value):
    text = "" if value is None else str(value)
    return text.replace("|", "\\|").replace("\n", " ")
