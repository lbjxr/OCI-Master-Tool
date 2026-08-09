import unittest

from oci_master.action_dispatch import parse_action
from oci_master.config import get_network_runtime_config, get_telegram_runtime_config


class Task8RefactorTests(unittest.TestCase):
    def test_shared_action_parser_normalizes_name_and_arguments(self):
        self.assertEqual(parse_action(" audit_events:10 "), ("audit_events", ("10",)))
        self.assertEqual(parse_action("instance_detail: vm-1"), ("instance_detail", ("vm-1",)))

    def test_shared_action_parser_rejects_empty_action(self):
        with self.assertRaises(ValueError):
            parse_action("  ")

    def test_telegram_defaults_are_shared_with_runtime_config(self):
        runtime = get_telegram_runtime_config({})
        self.assertEqual(runtime["poll_interval_seconds"], 3)
        self.assertEqual(runtime["initial_update_offset"], 0)

    def test_network_defaults_remain_stable(self):
        runtime = get_network_runtime_config({})
        self.assertEqual(runtime["quick_open_allowed_tcp_ports"], [22, 80, 443, 3389])
        self.assertEqual(runtime["default_source_cidr"], "0.0.0.0/0")


if __name__ == "__main__":
    unittest.main()
