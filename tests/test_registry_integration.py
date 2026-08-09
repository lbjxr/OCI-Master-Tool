import unittest
from unittest.mock import patch

from oci_master import registry
from oci_master import app as app_module


class RegistryIntegrationTests(unittest.TestCase):
    def setUp(self):
        registry.clear_registries()
        app_module._register_all_actions()

    def test_execute_action_delegates_to_registry(self):
        with patch.object(registry, "dispatch_cli") as mock_dispatch:
            app_module.execute_action("user_info", {"x": 1})
            mock_dispatch.assert_called_once_with("user_info", {"x": 1})

    def test_app_registry_contains_known_actions(self):
        names = {name for name, _ in registry.list_cli_actions()}
        expected = {
            "user_info", "usage_fee", "policies", "region_subscriptions",
            "bucket_info", "audit_events", "create_safe_policy",
            "list_instances", "delete_policy", "instance_detail",
            "instance_start", "instance_stop", "instance_restart",
            "instance_network", "instance_rules", "instance_temp_rules",
            "open_ingress_preview", "open_ingress_apply",
            "cleanup_temp_rules_preview", "cleanup_temp_rules_apply",
        }
        self.assertTrue(expected.issubset(names), f"Missing actions: {expected - names}")

    def test_app_menu_contains_entries(self):
        entries = registry.get_menu_entries()
        self.assertGreaterEqual(len(entries), 15)
        labels = [label for label, _, _ in entries]
        self.assertIn("👤 查看当前用户详细信息", labels)
        self.assertIn("💰 导出本月费用账单 (CLI展示)", labels)
        self.assertIn("🖥️  列出实例", labels)


if __name__ == '__main__':
    unittest.main()
