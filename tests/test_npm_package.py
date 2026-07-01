import json
import os
import unittest


class NpmPackageTest(unittest.TestCase):
    def test_package_exposes_mcp_bin(self):
        with open("package.json", "r", encoding="utf-8") as f:
            package = json.load(f)

        self.assertEqual(package["bin"]["dlc-agent-mcp"], "bin/dlc-agent-mcp.js")
        self.assertTrue(os.path.exists("bin/dlc-agent-mcp.js"))

    def test_launcher_has_shared_defaults(self):
        with open("bin/dlc-agent-mcp.js", "r", encoding="utf-8") as f:
            script = f.read()

        self.assertIn('"data-agent-host"', script)
        self.assertIn('"/opt/dlc-agent"', script)
        self.assertIn('"/data/dlc-agent/assets.db"', script)
        self.assertIn('"python3"', script)


if __name__ == "__main__":
    unittest.main()
