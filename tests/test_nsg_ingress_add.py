import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from oci_master.services import network_security


class NsgIngressAddTests(unittest.TestCase):
    def test_apply_open_ingress_uses_add_api_and_add_model(self):
        preview = {
            "target": {"target_type": "nsg", "target_id": "nsg-1"},
            "port": 22,
            "source_cidr": "192.0.2.10/32",
            "description": "OCI Master temporary TCP/22",
            "rule_model": {
                "description": "OCI Master temporary TCP/22",
                "is_stateless": False,
                "protocol": "6",
                "source": "192.0.2.10/32",
                "source_type": "CIDR_BLOCK",
                "tcp_options": {"destination_port_range": {"min": 22, "max": 22}},
            },
        }
        nsg = SimpleNamespace(security_rules=[])
        client = Mock()
        client.get_network_security_group.return_value = SimpleNamespace(data=nsg)
        client.add_network_security_group_security_rules.return_value = SimpleNamespace(status=200)

        with patch.object(network_security, "preview_open_ingress_rule_data", return_value=preview), patch.object(
            network_security, "get_oci_config", return_value={}
        ), patch.object(network_security, "get_virtual_network_client", return_value=client):
            result = network_security.apply_open_ingress_rule_data("instance-1", 22)

        self.assertTrue(result["applied"])
        client.add_network_security_group_security_rules.assert_called_once()
        client.update_network_security_group_security_rules.assert_not_called()
        details = client.add_network_security_group_security_rules.call_args.args[1]
        self.assertIsInstance(
            details,
            network_security.oci.core.models.AddNetworkSecurityGroupSecurityRulesDetails,
        )
        self.assertEqual(len(details.security_rules), 1)
        self.assertIsInstance(details.security_rules[0], network_security.oci.core.models.AddSecurityRuleDetails)


if __name__ == "__main__":
    unittest.main()
