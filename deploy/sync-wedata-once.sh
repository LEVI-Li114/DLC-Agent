#!/usr/bin/env bash
set -euo pipefail

ENV_FILE="${1:-/etc/dlc-agent/env}"
if [ ! -f "$ENV_FILE" ]; then
  echo "missing env file: $ENV_FILE" >&2
  exit 1
fi

set -a
. "$ENV_FILE"
set +a

: "${WEDATA_PROJECT_ID:?missing WEDATA_PROJECT_ID}"
: "${DLC_AGENT_DB:=/data/dlc-agent/assets.db}"

WORK_DIR="${DLC_AGENT_SYNC_DIR:-/data/dlc-agent/sync}"
mkdir -p "$WORK_DIR"

python -m dlc_agent.call_wedata_api ListTasks "{\"ProjectId\":\"$WEDATA_PROJECT_ID\"}" > "$WORK_DIR/wedata_tasks.json"

python -m dlc_agent.import_wedata_api_dump \
  --tasks "$WORK_DIR/wedata_tasks.json" \
  --db "$DLC_AGENT_DB"

echo "synced WeData task dump into $DLC_AGENT_DB"
