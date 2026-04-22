import unittest
from unittest.mock import patch

import OCI_Master


class BucketInfoTests(unittest.TestCase):
    def test_render_bucket_info_telegram_contains_core_fields(self):
        data = {
            "namespace": "myns",
            "profile": "DEFAULT",
            "bucket_count": 1,
            "stats_note": "approx note",
            "buckets": [
                {
                    "name": "logs-bucket",
                    "namespace": "myns",
                    "compartment_name": "Prod",
                    "time_created": "2026-04-01T01:02:03+00:00",
                    "public_access_type": "NoPublicAccess",
                    "storage_tier": "Standard",
                    "versioning": "Enabled",
                    "auto_tiering": "InfrequentAccess",
                    "approximate_count": 12,
                    "approximate_size": 2048,
                }
            ],
        }

        text = OCI_Master.render_bucket_info_telegram(data)
        self.assertIn("OCI 存储桶总览", text)
        self.assertIn("logs-bucket", text)
        self.assertIn("Namespace", text)
        self.assertIn("myns", text)
        self.assertIn("Compartment", text)
        self.assertIn("Prod", text)
        self.assertIn("创建时间", text)
        self.assertIn("私有", text)
        self.assertIn("Standard", text)
        self.assertIn("Enabled", text)
        self.assertIn("InfrequentAccess", text)
        self.assertIn("12", text)
        self.assertIn("2.00 KB", text)

    def test_render_bucket_info_telegram_multiple_buckets_keeps_clear_hierarchy(self):
        data = {
            "namespace": "myns",
            "profile": "DEFAULT",
            "bucket_count": 2,
            "buckets": [
                {
                    "name": "a-bucket",
                    "namespace": "myns",
                    "compartment_name": "Alpha",
                    "time_created": "2026-04-01T01:02:03+00:00",
                    "public_access_type": "NoPublicAccess",
                    "storage_tier": "Standard",
                    "versioning": "Enabled",
                    "auto_tiering": "Disabled",
                    "approximate_count": 1,
                    "approximate_size": 1024,
                },
                {
                    "name": "b-bucket",
                    "namespace": "myns",
                    "compartment_name": "Beta",
                    "time_created": "2026-04-02T01:02:03+00:00",
                    "public_access_type": "ObjectRead",
                    "storage_tier": "Archive",
                    "versioning": "Disabled",
                    "auto_tiering": "InfrequentAccess",
                    "approximate_count": 2,
                    "approximate_size": 2048,
                },
            ],
        }

        text = OCI_Master.render_bucket_info_telegram(data)
        self.assertIn("1. 🪣 a-bucket", text)
        self.assertIn("2. 🪣 b-bucket", text)
        self.assertEqual(text.count("🏷️ Namespace:"), 2)
        self.assertEqual(text.count("📁 Compartment:"), 2)
        self.assertEqual(text.count("🕒 创建时间:"), 2)

    def test_handle_command_bucket_info_dispatch(self):
        with patch("OCI_Master.get_bucket_info_data", return_value={"namespace": "myns", "profile": "DEFAULT", "bucket_count": 0, "buckets": []}), patch(
            "OCI_Master.render_bucket_info_telegram", return_value="bucket-ok"
        ):
            bot = OCI_Master.TelegramBotRunner({"telegram": {"enabled": False}})
            self.assertEqual(bot.handle_command("/bucket_info"), "bucket-ok")

    def test_get_bucket_info_data_collects_bucket_details(self):
        class FakeListResp:
            def __init__(self, data, headers=None):
                self.data = data
                self.headers = headers or {}

        class FakeIdentityClient:
            def __init__(self, _config):
                pass

            def list_compartments(self, _tenancy, **kwargs):
                return FakeListResp([
                    {"id": "ocid1.compartment.oc1..child", "name": "ChildComp"},
                ])

        class FakeObjectStorageClient:
            def __init__(self, _config):
                pass

            def get_namespace(self):
                return type("Resp", (), {"data": "testns"})()

            def list_buckets(self, namespace_name, compartment_id, **kwargs):
                if compartment_id == "ocid1.tenancy.oc1..root":
                    return FakeListResp([
                        {"name": "root-bucket", "time_created": "2026-04-01T00:00:00+00:00"},
                    ])
                if compartment_id == "ocid1.compartment.oc1..child":
                    return FakeListResp([
                        {"name": "child-bucket", "time_created": "2026-04-02T00:00:00+00:00"},
                    ])
                return FakeListResp([])

            def get_bucket(self, namespace_name, bucket_name, **kwargs):
                payload = {
                    "root-bucket": type(
                        "Bucket",
                        (),
                        {
                            "namespace": "testns",
                            "name": "root-bucket",
                            "compartment_id": "ocid1.tenancy.oc1..root",
                            "time_created": "2026-04-01T00:00:00+00:00",
                            "public_access_type": "NoPublicAccess",
                            "storage_tier": "Standard",
                            "versioning": "Disabled",
                            "auto_tiering": "Disabled",
                            "approximate_count": 10,
                            "approximate_size": 1024,
                        },
                    )(),
                    "child-bucket": type(
                        "Bucket",
                        (),
                        {
                            "namespace": "testns",
                            "name": "child-bucket",
                            "compartment_id": "ocid1.compartment.oc1..child",
                            "time_created": "2026-04-02T00:00:00+00:00",
                            "public_access_type": "ObjectRead",
                            "storage_tier": "Archive",
                            "versioning": "Enabled",
                            "auto_tiering": "InfrequentAccess",
                            "approximate_count": 99,
                            "approximate_size": 4096,
                        },
                    )(),
                }
                return type("Resp", (), {"data": payload[bucket_name]})()

        with patch("OCI_Master.get_oci_config", return_value={"tenancy": "ocid1.tenancy.oc1..root", "region": "ap-tokyo-1"}), patch(
            "OCI_Master.oci.identity.IdentityClient", FakeIdentityClient
        ), patch("OCI_Master.oci.object_storage.ObjectStorageClient", FakeObjectStorageClient):
            data = OCI_Master.get_bucket_info_data({"oci": {"profile_name": "DEFAULT"}})

        self.assertEqual(data["namespace"], "testns")
        self.assertEqual(data["bucket_count"], 2)
        self.assertEqual(data["buckets"][0]["name"], "child-bucket")
        self.assertEqual(data["buckets"][0]["compartment_name"], "ChildComp")
        self.assertEqual(data["buckets"][1]["name"], "root-bucket")


if __name__ == "__main__":
    unittest.main()
