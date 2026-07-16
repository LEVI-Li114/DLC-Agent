from dataclasses import dataclass, field

from .source import Source


@dataclass
class LiveAssetResult:
    source: str
    data: dict
    errors: list = field(default_factory=list)

    def as_dict(self):
        result = dict(self.data or {})
        result["source"] = self.source
        if self.errors:
            result["errors"] = self.errors
        return result


class LiveAssetService:
    def __init__(self, store, live):
        self.store = store
        self.live = live

    def get_partition_profile(self, table_name, partition_date=""):
        try:
            self.live.sync_table_partitions(table_name)
            data = self.store.get_table_partition_profile(table_name, partition_date)
            return LiveAssetResult(Source.LIVE, data, [])
        except Exception as exc:
            data = self.store.get_table_partition_profile(table_name, partition_date)
            safe = {
                "table_name": table_name,
                "partition_date": partition_date,
                "is_partitioned": data.get("is_partitioned", False),
                "partition_field": data.get("partition_field", ""),
                "partition_fact_available": False,
                "status": "unknown",
                "target_partition": None,
                "recent_partitions": [],
            }
            return LiveAssetResult(
                Source.PARTIAL_LIVE,
                safe,
                [
                    {
                        "module": "partition",
                        "status": "check_failed",
                        "api_action": "ListTablePartitions",
                        "error_message": str(exc),
                        "retryable": _retryable_error(str(exc)),
                    }
                ],
            )

    def get_task_runs(self, task_id="", task_name="", instance_date="", limit=10):
        try:
            self.live.sync_task_runs(task_name=task_name, task_id=task_id, instance_date=instance_date)
            if task_name:
                data = self.store.get_task_runs_by_name(task_name, limit, instance_date)
            else:
                data = self.store.get_task_runs(task_id, limit, instance_date)
            return LiveAssetResult(Source.LIVE, data, [])
        except Exception as exc:
            return LiveAssetResult(
                Source.PARTIAL_LIVE,
                {
                    "task_id": task_id,
                    "task_name": task_name,
                    "runs": [],
                    "status": "unknown",
                },
                [
                    {
                        "module": "task_runs",
                        "status": "check_failed",
                        "api_action": "ListTaskInstances",
                        "error_message": str(exc),
                        "retryable": _retryable_error(str(exc)),
                    }
                ],
            )


def _retryable_error(message):
    text = (message or "").lower()
    return any(token in text for token in ("timeout", "throttl", "rate", "internal", "temporary", "5"))
