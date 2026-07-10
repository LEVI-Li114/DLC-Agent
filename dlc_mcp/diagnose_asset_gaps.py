import argparse
import json
import os
import sqlite3
from collections import Counter

from .assets import AssetStore

LAYER_VALUES = {"ods", "dim", "dwd", "dws", "ads"}
RAW_FILES = {
    "tables": "wedata_tables.json",
    "metadata": "wedata_metadata.json",
    "tasks": "wedata_tasks.json",
    "task_instances": "wedata_task_instances.json",
    "table_partitions": "wedata_table_partitions.json",
}


def main():
    args = _parse_args()
    print(
        render_gap_diagnosis(
            args.db,
            args.sync_dir,
            report_source=args.report_source,
            quality_rule_count=args.quality_rule_count,
            unknown_layer_count=args.unknown_layer_count,
            sample_limit=args.sample_limit,
            project_id=args.project_id,
        )
    )


def _parse_args():
    parser = argparse.ArgumentParser(description="Diagnose DLC-MCP asset coverage gaps without mutating data.")
    parser.add_argument("--db", default=os.environ.get("DLC_MCP_DB", "data/assets.db"))
    parser.add_argument("--sync-dir", default=os.environ.get("DLC_MCP_SYNC_DIR", "/data/dlc-mcp/sync"))
    parser.add_argument("--report-source", default="")
    parser.add_argument("--quality-rule-count", type=int, default=None)
    parser.add_argument("--unknown-layer-count", type=int, default=None)
    parser.add_argument("--sample-limit", type=int, default=10)
    parser.add_argument("--project-id", default=os.environ.get("WEDATA_PROJECT_ID", ""))
    return parser.parse_args()


def render_gap_diagnosis(db_path, sync_dir, report_source="", quality_rule_count=None, unknown_layer_count=None, sample_limit=10, project_id=""):
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"asset database not found: {db_path}")
    store = AssetStore(sqlite3.connect(db_path))
    store.init_schema()
    raw = _load_raw_dumps(sync_dir)
    sections = [
        "# DLC-MCP 资产缺口诊断报告",
        _inspection_section(db_path, sync_dir, raw, report_source, quality_rule_count, unknown_layer_count),
        _quality_section(store, raw),
        _unknown_layer_section(store, raw, sample_limit),
        _partition_section(store, raw, sample_limit, project_id),
        _task_run_section(store, raw, sample_limit),
        _next_actions_section(),
    ]
    return "\n\n".join(section for section in sections if section)


def _load_raw_dumps(sync_dir):
    raw = {}
    for key, filename in RAW_FILES.items():
        path = os.path.join(sync_dir, filename)
        if not os.path.exists(path):
            raw[key] = {"exists": False, "path": path, "data": None, "error": ""}
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            raw[key] = {"exists": True, "path": path, "data": data, "error": ""}
        except (OSError, json.JSONDecodeError) as exc:
            raw[key] = {"exists": True, "path": path, "data": None, "error": str(exc)}
    return raw


def _inspection_section(db_path, sync_dir, raw, report_source, quality_rule_count, unknown_layer_count):
    lines = ["## 巡检来源", f"- 数据库：`{_cell(db_path)}`", f"- raw dump 目录：`{_cell(sync_dir)}`"]
    if report_source:
        lines.append(f"- 来源：{_cell(report_source)}")
    if quality_rule_count is not None:
        lines.append(f"- 质量规则基线：**{quality_rule_count}**（来自最新服务端资产库巡检）")
    if unknown_layer_count is not None:
        lines.append(f"- unknown 层表基线：**{unknown_layer_count}**（来自最新服务端资产库巡检）")
    missing = [item["path"] for item in raw.values() if not item["exists"]]
    bad = [f"{item['path']}: {item['error']}" for item in raw.values() if item["error"]]
    if missing:
        lines.append("- raw dump 不存在，只能进行 DB-only 诊断；无法区分接口未返回和解析/导入丢失。")
    if bad:
        lines.append("- raw dump 解析失败：" + "；".join(_cell(item) for item in bad))
    return "\n".join(lines)


def _quality_section(store, raw):
    counts = store.get_sync_health().get("counts", {})
    coverage = store.get_asset_coverage().get("layers", [])
    db_rules = int(counts.get("quality_rules") or 0)
    raw_rules = _raw_quality_rule_count(raw)
    rows = []
    for row in coverage:
        table_count = int(row.get("table_count") or 0)
        with_rules = int(row.get("tables_with_quality_rules") or 0)
        rows.append([row.get("layer"), table_count, f"{with_rules}/{table_count}"])
    causes = []
    if raw_rules is None:
        causes.append("质量规则可能是源头治理不足或同步范围不足；缺少 raw metadata，暂不能区分。")
    elif raw_rules > db_rules:
        causes.append("raw 质量规则多于 DB，优先排查 `_quality_rule_from_api` 字段映射或入库冲突。")
    else:
        causes.append("raw 质量规则与 DB 接近，优先判断为 WeData 源头治理不足或同步范围太小。")
    return "\n\n".join(
        [
            "## 质量规则覆盖诊断",
            f"- DB 质量规则数：**{db_rules}**",
            f"- raw 质量规则数：**{raw_rules if raw_rules is not None else '未知'}**",
            _table(["层级", "表数", "有质量规则"], rows),
            _bullets(causes),
        ]
    )


def _unknown_layer_section(store, raw, sample_limit):
    rows = _query(store, "select name, database_name, owner, source_guid, data_source_id from tables where coalesce(layer, '') in ('', 'unknown') order by name limit ?", (sample_limit,))
    total = _scalar(store, "select count(*) from tables where coalesce(layer, '') in ('', 'unknown')")
    raw_tables = _raw_items(raw.get("tables", {}).get("data"))
    raw_by_name = {_normalize_name(_raw_table_name(item)): item for item in raw_tables if _raw_table_name(item)}
    detail_rows = []
    causes = Counter()
    for row in rows:
        raw_item = raw_by_name.get(_normalize_name(row["name"]), {})
        inferred = _infer_layer(row["name"], row["database_name"], raw_item)
        if inferred:
            causes["parser_fixable"] += 1
        elif raw_item:
            causes["raw_insufficient"] += 1
        else:
            causes["raw_missing"] += 1
        detail_rows.append([row["name"], row["database_name"], inferred or "", "Y" if raw_item else "N"])
    cause_lines = [
        f"抽样中可由名称/库/路径推断：{causes['parser_fixable']}",
        f"抽样中 raw 存在但信息不足：{causes['raw_insufficient']}",
        f"抽样中找不到 raw 记录：{causes['raw_missing']}",
    ]
    return "\n\n".join(
        [
            "## unknown 层诊断",
            f"- DB unknown 层表数：**{total}**",
            _table(["表名", "库名", "可推断层级", "raw 记录"], detail_rows),
            _bullets(cause_lines),
        ]
    )


def _partition_section(store, raw, sample_limit, project_id):
    rows = _query(store, "select name, source_guid, database_name, data_source_id from tables order by name limit ?", (sample_limit,))
    payload_rows = []
    for row in rows:
        for payload in _partition_payloads(row, project_id):
            payload_rows.append([row["name"], json.dumps(payload, ensure_ascii=False, sort_keys=True)])
    partition_raw = raw.get("table_partitions", {})
    partition_data = partition_raw.get("data") or {}
    error = partition_data.get("Response", {}).get("Error", {}) if isinstance(partition_data, dict) else {}
    unsupported_action = partition_data.get("Response", {}).get("UnsupportedAction", "") if isinstance(partition_data, dict) else ""
    raw_count = len(_raw_items(partition_data)) if partition_raw.get("exists") and partition_raw.get("data") is not None else "未知"
    lines = [
        "## 分区接口参数诊断",
        "- 默认不调用外部 API，不做全量分区同步，只生成小样本候选 payload。",
        f"- raw 分区 item 数：**{raw_count}**",
    ]
    if error.get("Code") == "InvalidAction":
        action = unsupported_action or "ListTablePartitions"
        lines.append(f"- InvalidAction：`{_cell(action)}` 在当前 WeData 版本不支持，属于 action 名/版本不支持，不是参数错误。")
        lines.append(f"- 接口返回：{_cell(error.get('Message'))}")
    lines.append(_table(["表名", "候选 payload"], payload_rows))
    return "\n\n".join(lines)


def _task_run_section(store, raw, sample_limit):
    rows = _query(
        store,
        """
        select t.name,
               count(distinct tt.task_id) as task_count,
               count(distinct tr.instance_id) as run_count
        from tables t
        left join task_tables tt on tt.table_name = t.name
        left join task_runs tr on tr.task_id = tt.task_id
        group by t.name
        having task_count = 0 or run_count = 0
        order by t.name
        limit ?
        """,
        (sample_limit,),
    )
    detail_rows = []
    for row in rows:
        if int(row["task_count"] or 0) == 0:
            cause = "缺任务映射：排查任务输入输出/SQL 表名解析"
        else:
            cause = "有任务但缺运行实例：排查时间窗口、keyword、max pages 或 task_id 对齐"
        detail_rows.append([row["name"], row["task_count"], row["run_count"], cause])
    raw_instances = _raw_items(raw.get("task_instances", {}).get("data"))
    return "\n\n".join(
        [
            "## 真实表缺任务/运行实例诊断",
            "- 这些是已同步真实表的映射/运行缺口，不是任务名误造表清理问题。",
            f"- raw task instance item 数：**{len(raw_instances) if raw_instances else '未知'}**",
            _table(["表名", "任务数", "运行实例数", "分类"], detail_rows),
        ]
    )


def _next_actions_section():
    return "\n".join(
        [
            "## 建议下一步",
            "- 如果 raw 质量规则数也低，推动 WeData 源头质量规则治理或扩大同步范围。",
            "- 如果 unknown 抽样可推断层级，增强 `dlc_mcp/wedata.py` 的层级解析。",
            "- 用分区候选 payload 在服务端小样本验证参数后，再配置同步。",
            "- 对缺任务/运行实例表，优先排查表名规范化、任务 SQL 解析、实例时间窗口和分页限制。",
        ]
    )


def _partition_payloads(row, project_id):
    base = {"ProjectId": project_id} if project_id else {}
    payloads = []
    if row["name"]:
        payloads.append({**base, "TableName": row["name"]})
    if row["source_guid"]:
        payloads.append({**base, "TableGuid": row["source_guid"]})
    if row["database_name"] and row["name"]:
        payloads.append({**base, "DatabaseName": row["database_name"], "TableName": row["name"]})
    if row["data_source_id"] and row["database_name"] and row["name"]:
        payloads.append({**base, "DataSourceId": row["data_source_id"], "DatabaseName": row["database_name"], "TableName": row["name"]})
    return payloads


def _raw_quality_rule_count(raw):
    metadata = raw.get("metadata", {}).get("data")
    if not metadata:
        return None
    payload = metadata.get("payload", metadata)
    quality = payload.get("quality_rules", {}) if isinstance(payload, dict) else {}
    return len(_raw_items(quality))


def _raw_items(response):
    if not response:
        return []
    data = response.get("Response", response) if isinstance(response, dict) else response
    for key in ("Data", "Result"):
        if isinstance(data, dict) and key in data:
            data = data[key]
    if isinstance(data, dict):
        for key in ("Items", "Rows", "List", "Records"):
            if isinstance(data.get(key), list):
                return data[key]
    return data if isinstance(data, list) else []


def _raw_table_name(item):
    return str(item.get("TableName") or item.get("Name") or item.get("tableName") or item.get("name") or "")


def _infer_layer(name, database_name, raw_item):
    values = [
        raw_item.get("Layer"),
        raw_item.get("TableLayer"),
        raw_item.get("BizLayer"),
        raw_item.get("DataLayer"),
        raw_item.get("layer"),
        database_name,
        raw_item.get("DatabaseName"),
        raw_item.get("Database"),
        raw_item.get("DbName"),
        raw_item.get("SchemaName"),
        raw_item.get("FolderName"),
        raw_item.get("FolderPath"),
        raw_item.get("CategoryName"),
        raw_item.get("ProjectName"),
        raw_item.get("DatasourceName"),
        raw_item.get("DataSourceName"),
        name,
    ]
    for value in values:
        layer = _layer_from_text(value)
        if layer:
            return layer
    return ""


def _layer_from_text(value):
    text = str(value or "").lower().replace("-", "_").replace("/", "_").replace(".", "_")
    parts = [part for part in text.split("_") if part]
    for part in parts:
        if part in LAYER_VALUES:
            return part
    for layer in LAYER_VALUES:
        if text.startswith(layer + "_") or ("_" + layer + "_") in ("_" + text + "_"):
            return layer
    return ""


def _normalize_name(value):
    return str(value or "").strip().strip("`'\"").replace("`", "").split(".")[-1]


def _query(store, sql, params=()):
    return [dict(row) for row in store.conn.execute(sql, params).fetchall()]


def _scalar(store, sql, params=()):
    return store.conn.execute(sql, params).fetchone()[0]


def _table(headers, rows):
    if not rows:
        return "_无数据_"
    return "\n".join(
        [
            "| " + " | ".join(headers) + " |",
            "| " + " | ".join(["---"] * len(headers)) + " |",
            *["| " + " | ".join(_cell(value) for value in row) + " |" for row in rows],
        ]
    )


def _bullets(lines):
    return "\n".join(f"- {line}" for line in lines)


def _cell(value):
    return ("" if value is None else str(value)).replace("|", "\\|").replace("\n", " ")


if __name__ == "__main__":
    main()
