# get_task_code MCP Tool Design

Date: 2026-07-13

## Goal

Add a `get_task_code(task_id, task_name, live)` MCP tool that returns the SQL/code content for a Tencent Cloud WeData task using the documented `GetTaskCode` API.

The tool will use the existing project pattern: read from local SQLite cache by default, and refresh from WeData when `live=true` or when the cache is missing.

## External API

Tencent Cloud WeData `GetTaskCode`:

- Action: `GetTaskCode`
- Version: `2025-08-06`
- Required business parameters:
  - `ProjectId`
  - `TaskId`
- Response content:
  - `Response.Data.CodeInfo`
  - `Response.Data.CodeFileSize`

`CodeInfo` may be Base64 encoded. The implementation will try to decode it as UTF-8 Base64. If decoding fails, it will return the raw `CodeInfo` string as code content rather than failing the request.

## MCP Tool Contract

Tool name: `get_task_code`

Input schema:

- `task_id`: optional string. Preferred lookup key.
- `task_name`: optional string. Used only when `task_id` is absent.
- `live`: optional boolean. When true, refreshes code from Tencent Cloud before returning.

Validation:

- If both `task_id` and `task_name` are missing, return `missing_task_identity`.
- `TaskId` is required for the actual Tencent Cloud `GetTaskCode` call.
- If only `task_name` is provided, resolve it to a task id from cached tasks. When live refresh is available, sync tasks by task name first if needed, then retry resolution.

Output:

- Markdown response with:
  - Project ID
  - Task ID
  - Task name when known
  - Code file size when provided
  - Encoding status (`base64` or `raw`)
  - Cache update time
  - SQL/code content in a fenced code block

## Storage Design

Add a new `task_codes` table to `AssetStore.init_schema()`:

- `project_id text not null`
- `task_id text not null`
- `task_name text not null default ''`
- `code_info text not null default ''`
- `code_text text not null default ''`
- `code_file_size integer not null default 0`
- `encoding text not null default ''`
- `raw_json text not null default '{}'`
- `updated_at text not null default ''`
- primary key: `(project_id, task_id)`

This keeps task metadata (`tasks`) separate from task code content, because task definitions and code bodies have different refresh lifecycles and may later need version-specific handling.

## Component Changes

### `dlc_mcp/assets.py`

Add methods:

- `resolve_task(task_id='', task_name='')`
  - If `task_id` is provided, return that task from `tasks` when present, or a minimal task identity when absent.
  - If `task_name` is provided, exact-match cached `tasks.name` and return the matching task.
  - If no match, return `None`.
- `upsert_task_code(project_id, task_id, task_name, code_info, code_text, code_file_size, encoding, raw)`
  - Writes decoded and raw code payload to `task_codes`.
- `get_task_code(project_id='', task_id='', task_name='')`
  - Resolves `task_id` from `task_name` when needed.
  - Returns cached task code or an error (`task_not_found` / `task_code_not_found`).

### `dlc_mcp/live.py`

Add `sync_task_code(task_id='', task_name='', project_id='')`:

1. Resolve project id via existing `project_id_or_default()`.
2. Resolve task id:
   - If `task_id` is provided, use it.
   - If only `task_name` is provided, sync tasks with `ListTasks(TaskName=task_name)` and resolve exact cached match.
3. Call `GetTaskCode` with `ProjectId` and `TaskId`.
4. Extract `Response.Data.CodeInfo` and `CodeFileSize`.
5. Decode `CodeInfo` if possible.
6. Store result through `AssetStore.upsert_task_code()`.

### `dlc_mcp/mcp.py`

Add `TOOLS['get_task_code']` with schema for `task_id`, `task_name`, and `live`.

Add `_call_tool` branch:

1. Validate identity.
2. Try cached `store.get_task_code(...)`.
3. If live is available and either `live=true` or cache miss:
   - call `live.sync_task_code(...)`
   - read cache again
4. Return formatted Markdown.

Add `_format_markdown('get_task_code', data)`:

- For errors, reuse generic error formatting.
- For success, render metadata and code block.
- Use a conservative code fence language such as `sql` when code contains SQL-looking tokens; otherwise use plain fenced code.

## Error Handling

- `missing_task_identity`: no `task_id` or `task_name` supplied.
- `missing_project_id`: no project id available from arguments or `WEDATA_PROJECT_ID`.
- `task_not_found`: task name could not be resolved to a task id.
- `task_code_not_found`: task identity exists but no cached code is available and live refresh was not requested or not available.
- Tencent Cloud API errors: keep current live-sync behavior and raise `RuntimeError` with action/code/message.
- Base64 decode failure: return raw `CodeInfo`, set `encoding='raw'`, and do not fail the tool call.

## Tests

Add or update tests in `tests/test_mcp.py` and nearby unit tests:

1. `tools/list` includes `get_task_code`.
2. Cached `get_task_code` returns decoded SQL/code content.
3. Missing identity returns `missing_task_identity`.
4. `live=true` calls fake WeData client action `GetTaskCode` with `ProjectId` and `TaskId`, then returns decoded SQL.
5. Task-name-only lookup resolves a cached task name to task id.
6. Base64 `CodeInfo` decodes correctly; invalid Base64 falls back to raw content.

## Out of Scope

- Version-specific task code history.
- Editing or publishing task code.
- Fetching code by non-exact fuzzy task-name matches.
- Changes to production sync cron jobs.
