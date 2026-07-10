import argparse
import json
import os
import sqlite3

from .server import _load_env_file


def main():
    args = _parse_args()
    if args.env_file and os.path.exists(args.env_file):
        _load_env_file(args.env_file)
    db_path = args.db or os.environ.get("DLC_MCP_DB", "data/assets.db")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    print(json.dumps(cleanup_derived_tables(conn, apply=args.apply), ensure_ascii=False, sort_keys=True))


def cleanup_derived_tables(conn, apply=False):
    names = [
        row["name"]
        for row in conn.execute(
            """
            select name
            from tables
            where source_guid = ''
              and database_name = ''
              and description like 'Derived from WeData task%'
            order by name
            """
        )
    ]
    counts = {"candidate_tables": len(names), "apply": bool(apply)}
    if not names or not apply:
        return counts

    placeholders = ",".join(["?"] * len(names))
    targets = [
        ("columns", f"table_name in ({placeholders})", names),
        ("task_tables", f"table_name in ({placeholders})", names),
        ("lineage", f"upstream in ({placeholders}) or downstream in ({placeholders})", names + names),
        ("quality_rules", f"table_name in ({placeholders})", names),
        ("table_partitions", f"table_name in ({placeholders})", names),
        ("expert_labels", f"asset_type = 'table' and asset_name in ({placeholders})", names),
        ("tables", f"name in ({placeholders})", names),
    ]
    with conn:
        for table, where, params in targets:
            cur = conn.execute(f"delete from {table} where {where}", params)
            counts[f"deleted_{table}"] = cur.rowcount
    return counts


def _parse_args():
    parser = argparse.ArgumentParser(description="Remove old table assets derived only from WeData task names.")
    parser.add_argument("--env-file", default=os.environ.get("DLC_MCP_ENV_FILE", "/etc/dlc-mcp/env"))
    parser.add_argument("--db", default="")
    parser.add_argument("--apply", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    main()
