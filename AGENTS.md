# DLC-Agent Project Rules

## Tool Boundary

- Query asset data only through the native `dlc-mcp` MCP tools loaded by Codex.
- Never downgrade a data query to `ssh`, an SSH tunnel, `curl`, direct Gateway HTTP, or direct SQLite access.
- If native `dlc-mcp` tools are unavailable, stop the query and report that Codex must reload or the MCP configuration must be repaired.
- Use `ssh` only for deployment, backfill, service restart, and log inspection.

## Task Lineage

- Treat "downstream" as the first-level downstream task dependency unless the user explicitly asks for downstream table lineage.
- For data-source task, downstream task, output-table, or DDL requests, follow `.agents/skills/dlc-task-lineage/SKILL.md`.
- Never infer an input or output table from a task name.
