import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from oci_master.config import get_network_runtime_config
from oci_master.services import network_security
from oci_master.telegram_bot import TelegramBotRunner


class ThreeRemediationTests(unittest.TestCase):
    def test_public_cidr_is_disabled_by_default(self):
        runtime = get_network_runtime_config({})
        self.assertFalse(runtime["allow_public_cidr"])
        with self.assertRaisesRegex(ValueError, "0.0.0.0/0"):
            network_security._normalize_source_cidr("0.0.0.0/0", "0.0.0.0/0", False)

    def test_custom_port_requires_high_risk_confirmation_label(self):
        bot = TelegramBotRunner({"telegram": {"enabled": True, "bot_token": "test-token"}})
        keyboard = bot.build_netsec_preview_keyboard("open", "vm-1", "25565", "192.0.2.10/32")
        button_text = keyboard["inline_keyboard"][0][0]["text"]
        self.assertIn("二次确认", button_text)

    def test_security_list_update_passes_etag(self):
        preview = {
            "target": {"target_type": "security_list", "target_id": "sl-1"},
            "port": 22,
            "source_cidr": "192.0.2.10/32",
            "description": "temporary",
            "rule_model": {
                "description": "temporary",
                "is_stateless": False,
                "protocol": "6",
                "source": "192.0.2.10/32",
                "source_type": "CIDR_BLOCK",
                "tcp_options": {"destination_port_range": {"min": 22, "max": 22}},
            },
        }
        security_list = SimpleNamespace(
            display_name="sl",
            defined_tags={},
            freeform_tags={},
            egress_security_rules=[],
            ingress_security_rules=[],
        )
        client = Mock()
        client.get_security_list.return_value = SimpleNamespace(data=security_list, headers={"etag": "etag-1"})
        client.update_security_list.return_value = SimpleNamespace(status=200)
        with patch.object(network_security, "preview_open_ingress_rule_data", return_value=preview), patch.object(
            network_security, "get_oci_config", return_value={}
        ), patch.object(network_security, "get_virtual_network_client", return_value=client):
            result = network_security.apply_open_ingress_rule_data("vm-1", 22, "192.0.2.10/32")
        self.assertTrue(result["applied"])
        self.assertEqual(client.update_security_list.call_args.kwargs["if_match"], "etag-1")

    def test_telegram_error_does_not_include_token_or_body(self):
        bot = TelegramBotRunner({"telegram": {"enabled": True, "bot_token": "secret-token"}})
        response = Mock()
        response.raise_for_status.side_effect = __import__("requests").HTTPError("raw")
        response.status_code = 502
        response.text = "secret-token and sensitive body"
        with patch("oci_master.telegram_bot.requests.post", return_value=response):
            with self.assertRaises(Exception) as raised:
                bot._request("getUpdates")
        self.assertNotIn("secret-token", str(raised.exception))
        self.assertNotIn("sensitive body", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
