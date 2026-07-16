import sqlite3

from dlc_mcp.assets import AssetStore
from dlc_mcp.live_assets import LiveAssetService
from dlc_mcp.source import Source


class SyncingLive:
    def __init__(self, store):
        self.store = store
        self.partition_calls = []
        self.run_calls = []

    def sync_table_partitions(self, table_name):
        self.partition_calls.append(table_name)
        self.store.upsert_table_partition(
            {
                "table_name": table_name,
                "partition_name": "dt=20260715",
                "partition_date": "20260715",
                "row_count": 2,
            }
        )

    def sync_task_runs(self, task_name="", task_id="", instance_date=""):
        self.run_calls.append((task_name, task_id, instance_date))


class FailingLive:
    def sync_table_partitions(self, table_name):
        raise RuntimeError("DescribeTablePartitions failed: Throttling rate exceeded")

    def sync_task_runs(self, task_name="", task_id="", instance_date=""):
        raise RuntimeError("ListTaskInstances failed: InternalError temporary unavailable")


def _store_with_partitioned_table():
    conn = sqlite3.connect(":memory:")
    store = AssetStore(conn)
    store.init_schema()
    store.upsert_table({"name": "ods_cloud_cost_baidu_day_di", "database": "byai_bigdata"})
    store.upsert_column("ods_cloud_cost_baidu_day_di", "dt", "string", "", 1)
    return store


def test_live_asset_service_partition_success_returns_live_result():
    store = _store_with_partitioned_table()
    live = SyncingLive(store)
    service = LiveAssetService(store, live)

    result = service.get_partition_profile("ods_cloud_cost_baidu_day_di", "20260715")

    assert result.source == Source.LIVE
    assert result.data["target_partition"]["partition_name"] == "dt=20260715"
    assert result.errors == []
    assert live.partition_calls == ["ods_cloud_cost_baidu_day_di"]


def test_live_asset_service_partition_failure_is_partial_live_not_missing():
    store = _store_with_partitioned_table()
    service = LiveAssetService(store, FailingLive())

    result = service.get_partition_profile("ods_cloud_cost_baidu_day_di", "20260715")

    assert result.source == Source.PARTIAL_LIVE
    assert result.data["status"] == "unknown"
    assert result.errors[0]["module"] == "partition"
    assert result.errors[0]["status"] == "check_failed"
    assert "Throttling" in result.errors[0]["error_message"]
