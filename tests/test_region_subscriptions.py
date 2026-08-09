import unittest
from unittest.mock import patch

from oci_master.services import tenant_insights
from oci_master.telegram_bot import TelegramBotRunner


class RegionSubscriptionsTests(unittest.TestCase):
    def test_get_region_subscriptions_data_sorts_home_region_first(self):
        class FakeIdentityClient:
            def __init__(self, _config):
                pass

            def list_region_subscriptions(self, _tenancy):
                class Resp:
                    data = object()

                return Resp()

        fake_regions = [
            {
                "region_name": "us-ashburn-1",
                "region_key": "IAD",
                "status": "READY",
                "is_home_region": False,
            },
            {
                "region_name": "ap-tokyo-1",
                "region_key": "NRT",
                "status": "READY",
                "is_home_region": True,
            },
        ]

        with patch("oci_master.services.tenant_insights.get_oci_config", return_value={"tenancy": "ocid1.tenancy", "region": "ap-tokyo-1"}), patch(
            "oci_master.services.tenant_insights.oci.identity.IdentityClient", FakeIdentityClient
        ), patch("oci_master.services.tenant_insights._normalize_collection_items", return_value=fake_regions):
            data = tenant_insights.get_region_subscriptions_data({"oci": {"profile_name": "DEFAULT"}})

        self.assertEqual(data["total_regions"], 2)
        self.assertEqual(data["home_region"], "ap-tokyo-1")
        self.assertEqual(data["regions"][0]["region_name"], "ap-tokyo-1")
        self.assertTrue(data["regions"][0]["is_home_region"])

    def test_render_region_subscriptions_telegram_contains_home_tag(self):
        data = {
            "home_region": "ap-tokyo-1",
            "total_regions": 2,
            "regions": [
                {
                    "region_name": "ap-tokyo-1",
                    "region_key": "NRT",
                    "status": "READY",
                    "is_home_region": True,
                },
                {
                    "region_name": "us-ashburn-1",
                    "region_key": "IAD",
                    "status": "READY",
                    "is_home_region": False,
                },
            ],
        }
        text = tenant_insights.render_region_subscriptions_telegram(data)
        self.assertIn("OCI 订阅区域", text)
        self.assertIn("HOME", text)
        self.assertIn("ap-tokyo-1", text)
        self.assertIn("us-ashburn-1", text)

    def test_handle_command_regions_dispatch(self):
        with patch("oci_master.telegram_bot.get_region_subscriptions_data", return_value={"home_region": "ap-tokyo-1", "total_regions": 1, "regions": []}), patch(
            "oci_master.telegram_bot.render_region_subscriptions_telegram", return_value="ok"
        ):
            bot = TelegramBotRunner({"telegram": {"enabled": False}})
            self.assertEqual(bot.handle_command("/regions"), "ok")


if __name__ == "__main__":
    unittest.main()
