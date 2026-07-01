import json
import os
import sqlite3

from .assets import AssetStore
from .tencentcloud import TencentCloudClient
from .wedata import import_wedata_snapshot, snapshot_from_api_dump


def main():
    project_id = os.environ["WEDATA_PROJECT_ID"]
    db_path = os.environ.get("DLC_AGENT_DB", "/data/dlc-agent/assets.db")
    work_dir = os.environ.get("DLC_AGENT_SYNC_DIR", "/data/dlc-agent/sync")
    page_size = int(os.environ.get("WEDATA_PAGE_SIZE", "100"))

    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    os.makedirs(work_dir, exist_ok=True)

    client = TencentCloudClient.wedata_from_env()
    tasks_response = _list_all(client, "ListTasks", {"ProjectId": project_id}, page_size)
    tasks_path = os.path.join(work_dir, "wedata_tasks.json")
    with open(tasks_path, "w", encoding="utf-8") as f:
        json.dump(tasks_response, f, ensure_ascii=False, indent=2)

    dump = {"tasks": tasks_response}
    if os.environ.get("WEDATA_SYNC_INSTANCES") == "1":
        instance_payload = {"ProjectId": project_id}
        for env_name, field_name in (("WEDATA_INSTANCE_START", "StartTime"), ("WEDATA_INSTANCE_END", "EndTime")):
            if os.environ.get(env_name):
                instance_payload[field_name] = os.environ[env_name]
        instances_response = _list_all(client, "ListTaskInstances", instance_payload, page_size)
        instances_path = os.path.join(work_dir, "wedata_task_instances.json")
        with open(instances_path, "w", encoding="utf-8") as f:
            json.dump(instances_response, f, ensure_ascii=False, indent=2)
        dump["task_instances"] = instances_response

    store = AssetStore(sqlite3.connect(db_path))
    store.init_schema()
    import_wedata_snapshot(store, snapshot_from_api_dump(dump))

    total = len(tasks_response["Response"]["Data"]["Items"])
    print(f"synced {total} WeData tasks into {db_path}")
    print(f"saved raw task dump to {tasks_path}")
    if "task_instances" in dump:
        run_total = len(dump["task_instances"]["Response"]["Data"]["Items"])
        print(f"synced {run_total} WeData task instances")


def _list_all(client, action, payload, page_size):
    first = client.call(action, {**payload, "PageNumber": 1, "PageSize": page_size})
    data = first.get("Response", {}).get("Data", {})
    total_pages = int(data.get("TotalPageNumber") or 1)
    items = list(data.get("Items") or [])

    for page in range(2, total_pages + 1):
        response = client.call(action, {**payload, "PageNumber": page, "PageSize": page_size})
        items.extend(response.get("Response", {}).get("Data", {}).get("Items") or [])

    first["Response"]["Data"]["Items"] = items
    first["Response"]["Data"]["PageNumber"] = 1
    first["Response"]["Data"]["PageSize"] = page_size
    first["Response"]["Data"]["TotalPageNumber"] = total_pages
    return first


if __name__ == "__main__":
    main()
