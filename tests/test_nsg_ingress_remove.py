import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from oci_master.services import network_security


class NsgIngressRemoveTests(unittest.TestCase):
    def make_client(self, rule):
        client = Mock()
        client.get_network_security_group.side_effect = [
            SimpleNamespace(data=SimpleNamespace(security_rules=[rule])),
            SimpleNamespace(data=SimpleNamespace(security_rules=[])),
        ]
        client.remove_network_security_group_security_rules.return_value = SimpleNamespace(status=204)
        return client

    def test_apply_cleanup_temp_rules_uses_remove_api_and_rechecks(self):
        rule = SimpleNamespace(id="rule-1")
        preview = {
            "target": {"target_type": "nsg", "target_id": "nsg-1"},
            "port": 22,
            "source_cidr": "192.0.2.10/32",
            "description": "temporary",
            "matched_rules": [{"id": "rule-1"}],
        }
        client = self.make_client(rule)

        with patch.object(network_security, "preview_cleanup_temp_rules_data", return_value=preview), patch.object(
            network_security, "get_oci_config", return_value={}
        ), patch.object(network_security, "get_virtual_network_client", return_value=client):
            result = network_security.apply_cleanup_temp_rules_data("instance-1", 22)

        self.assertEqual(result["removed_count"], 1)
        client.remove_network_security_group_security_rules.assert_called_once()
        client.update_network_security_group_security_rules.assert_not_called()
        details = client.remove_network_security_group_security_rules.call_args.args[1]
        self.assertIsInstance(
            details,
            network_security.oci.core.models.RemoveNetworkSecurityGroupSecurityRulesDetails,
        )
        self.assertEqual(details.security_rule_ids, ["rule-1"])
        self.assertEqual(client.get_network_security_group.call_count, 2)

    def test_apply_selected_cleanup_uses_remove_api(self):
        rule = SimpleNamespace(id="rule-1", direction="INGRESS", description="OCI Master temporary")
        preview = {
            "selected_rules": [
                {
                    "target_scope": "nsg:nsg-1",
                    "target_type": "nsg",
                    "target_id": "nsg-1",
                    "rule_key": "nsg:nsg-1#1",
                }
            ],
            "instance": {"display_name": "demo"},
            "profile": "DEFAULT",
        }
        client = self.make_client(rule)
        overview = {"rule_summary": [], "profile": "DEFAULT", "instance": {"display_name": "demo"}}

        with patch.object(network_security, "preview_cleanup_selected_temp_rules_data", return_value=preview), patch.object(
            network_security, "get_oci_config", return_value={}
        ), patch.object(network_security, "get_virtual_network_client", return_value=client), patch.object(
            network_security, "_is_temp_rule", return_value=True
        ), patch.object(network_security, "_collect_instance_network_objects", return_value=overview):
            result = network_security.apply_cleanup_selected_temp_rules_data("instance-1", ["nsg:nsg-1#1"])

        self.assertEqual(result["removed_count"], 1)
        client.remove_network_security_group_security_rules.assert_called_once()
        client.update_network_security_group_security_rules.assert_not_called()


if __name__ == "__main__":
    unittest.main()
