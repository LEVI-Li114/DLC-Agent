import json
import sqlite3
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

from dlc_mcp.assets import AssetStore
from dlc_mcp import sync_table_fields


class FakeClient:
    def __init__(self):
        self.calls = []

    def call(self, action, payload):
        self.calls.append((action, payload))
        if action == "ListTable":
            return {
                "Response": {
                    "Data": {
                        "Items": [
                            {"Name": "has_columns", "Guid": "guid_has"},
                            {"Name": "new_table", "Guid": "guid_new"},
                            {"Name": "missing_guid"},
                        ]
                    }
                }
            }
        if action == "GetTableColumns":
            return {"Response": {"Data": [{"Name": "id", "Type": "bigint", "Description": "id"}]}}
        return {"Response": {"Data": {"Items": []}}}


class SyncTableFieldsTest(unittest.TestCase):
    def test_full_field_sync_skips_existing_columns_and_reports_failures(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "assets.db")
            store = AssetStore(sqlite3.connect(db_path))
            store.init_schema()
            store.upsert_table({"name": "has_columns"})
            store.upsert_column("has_columns", "old_id")

            with patch.dict("os.environ", {"WEDATA_PROJECT_ID": "project", "DLC_MCP_DB": db_path, "DLC_MCP_SYNC_DIR": tmp}), patch.object(sync_table_fields.TencentCloudClient, "wedata_from_env", return_value=FakeClient()), patch("sys.argv", ["sync_table_fields"]):
                sync_table_fields.main()

            store = AssetStore(sqlite3.connect(db_path))
            self.assertEqual([row["name"] for row in store.list_table_columns("new_table")["columns"]], ["id"])
            report = json.loads((Path(tmp) / "wedata_table_fields_full_report.json").read_text())
            self.assertEqual(report["synced_table_count"], 1)
            self.assertEqual(report["skipped_table_count"], 1)
            self.assertEqual(report["failed_table_count"], 1)

    def test_call_with_retries_retries_then_succeeds(self):
        attempts = []
        args = Namespace(max_retries=2, retry_base_sleep=0)

        def call():
            attempts.append(1)
            if len(attempts) == 1:
                return {"Response": {"Error": {"Code": "RequestLimitExceeded", "Message": "slow down"}}}
            return {"Response": {"Data": {}}}

        self.assertEqual(sync_table_fields._call_with_retries(call, "GetTableColumns", args), {"Response": {"Data": {}}})
        self.assertEqual(len(attempts), 2)


if __name__ == "__main__":
    unittest.main()
