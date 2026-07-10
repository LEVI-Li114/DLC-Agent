import os
import sqlite3
import unittest
from tempfile import TemporaryDirectory

from dlc_mcp.assets import AssetStore
from dlc_mcp.diagnose_asset_gaps import render_gap_diagnosis


class DiagnoseAssetGapsTest(unittest.TestCase):
    def _store(self, db_path):
        store = AssetStore(sqlite3.connect(db_path))
        store.init_schema()
        return store

    def test_report_labels_service_baselines_and_db_only_mode(self):
        with TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "assets.db")
            store = self._store(db_path)
            store.upsert_table({"name": "mystery_table", "layer": "unknown", "owner": "owner-a"})
            store.upsert_table({"name": "ads_revenue", "layer": "ads", "owner": "owner-b"})
            store.upsert_column("ads_revenue", "amount", "decimal", "", 1)

            report = render_gap_diagnosis(
                db_path,
                os.path.join(tmpdir, "sync"),
                report_source="latest service asset inspection",
                quality_rule_count=62,
                unknown_layer_count=2141,
                sample_limit=5,
            )

        self.assertIn("# DLC-MCP 资产缺口诊断报告", report)
        self.assertIn("latest service asset inspection", report)
        self.assertIn("质量规则基线：**62**", report)
        self.assertIn("unknown 层表基线：**2141**", report)
        self.assertIn("raw dump 不存在，只能进行 DB-only 诊断", report)
        self.assertIn("质量规则可能是源头治理不足或同步范围不足", report)
        self.assertIn("真实表缺任务/运行实例诊断", report)
        self.assertIn("不是任务名误造表清理问题", report)

    def test_raw_quality_rules_greater_than_db_reports_parser_loss(self):
        with TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "assets.db")
            sync_dir = os.path.join(tmpdir, "sync")
            os.makedirs(sync_dir)
            store = self._store(db_path)
            store.upsert_table({"name": "ads_revenue", "layer": "ads"})
            with open(os.path.join(sync_dir, "wedata_metadata.json"), "w", encoding="utf-8") as f:
                f.write('{"payload":{"quality_rules":{"Response":{"Data":{"Items":[{"TableName":"ads_revenue","RuleName":"r1"},{"TableName":"ads_revenue","RuleName":"r2"}]}}}}}')

            report = render_gap_diagnosis(db_path, sync_dir)

        self.assertIn("raw 质量规则数：**2**", report)
        self.assertIn("raw 质量规则多于 DB", report)

    def test_unknown_layer_reports_parser_fixable_from_raw_database(self):
        with TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "assets.db")
            sync_dir = os.path.join(tmpdir, "sync")
            os.makedirs(sync_dir)
            store = self._store(db_path)
            store.upsert_table({"name": "revenue_daily", "layer": "unknown", "database": "ads_mart"})
            with open(os.path.join(sync_dir, "wedata_tables.json"), "w", encoding="utf-8") as f:
                f.write('{"Response":{"Data":{"Items":[{"Name":"revenue_daily","DatabaseName":"ads_mart"}]}}}')

            report = render_gap_diagnosis(db_path, sync_dir)

        self.assertIn("revenue_daily", report)
        self.assertIn("ads", report)
        self.assertIn("抽样中可由名称/库/路径推断：1", report)

    def test_partition_raw_invalid_action_reports_action_version_unsupported(self):
        with TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "assets.db")
            sync_dir = os.path.join(tmpdir, "sync")
            os.makedirs(sync_dir)
            self._store(db_path)
            with open(os.path.join(sync_dir, "wedata_table_partitions.json"), "w", encoding="utf-8") as f:
                f.write('{"Response":{"Error":{"Code":"InvalidAction","Message":"Action ListTablePartitions is not supported in version 2025-08-06"},"Data":{"Items":[]},"UnsupportedAction":"ListTablePartitions"}}')

            report = render_gap_diagnosis(db_path, sync_dir)

        self.assertIn("InvalidAction", report)
        self.assertIn("action 名/版本不支持", report)
        self.assertIn("ListTablePartitions", report)


if __name__ == "__main__":
    unittest.main()
