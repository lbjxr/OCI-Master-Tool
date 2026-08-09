import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import oci
import requests

from oci_master.services import instances


class InstanceExceptionNarrowingTests(unittest.TestCase):
    def setUp(self):
        self.config = {"tenancy": "tenancy-1", "region": "region-1"}
        self.identity = Mock()
        self.identity.get_compartment.return_value = SimpleNamespace(
            data=SimpleNamespace(id="tenancy-1", name="root")
        )
        self.identity.list_compartments.return_value = SimpleNamespace(data=[])
        self.compute = Mock()
        self.compute.list_instances.return_value = SimpleNamespace(
            data=[SimpleNamespace(
                id="instance-1", display_name="vm-1", lifecycle_state="RUNNING",
                shape="VM.Standard", availability_domain="AD-1", time_created=None,
            )]
        )
        self.network = Mock()

    def collect_with_network_error(self, error):
        with patch.object(instances, "get_oci_config", return_value=self.config), patch.object(
            instances, "get_compute_client", return_value=self.compute
        ), patch.object(instances.oci.identity, "IdentityClient", return_value=self.identity), patch.object(
            instances, "get_virtual_network_client", return_value=self.network
        ), patch.object(
            instances.oci.pagination,
            "list_call_get_all_results",
            side_effect=[
                SimpleNamespace(data=[]),
                SimpleNamespace(data=self.compute.list_instances.return_value.data),
                error,
            ],
        ):
            return instances._collect_instances(self.config)

    def test_vnic_attribute_error_is_not_silenced(self):
        with self.assertRaises(AttributeError):
            self.collect_with_network_error(AttributeError("broken test double"))

    def test_vnic_type_error_is_not_silenced(self):
        with self.assertRaises(TypeError):
            self.collect_with_network_error(TypeError("broken test double"))

    def test_vnic_oci_service_error_falls_back_to_na(self):
        service_error = oci.exceptions.ServiceError(503, "ServiceUnavailable", {}, "temporary OCI failure")
        result = self.collect_with_network_error(service_error)
        self.assertEqual(result[0]["ip_address"], "N/A")

    def test_vnic_requests_error_falls_back_to_na(self):
        result = self.collect_with_network_error(requests.exceptions.ConnectionError("temporary network failure"))
        self.assertEqual(result[0]["ip_address"], "N/A")

    def test_recheck_attribute_error_is_not_silenced(self):
        with patch.object(instances, "_fetch_instance_state", side_effect=AttributeError("bug")), patch.object(
            instances.time, "sleep"
        ):
            with self.assertRaises(AttributeError):
                instances._recheck_instance_state("instance-1", delays=(0,))

    def test_recheck_oci_service_error_is_reported(self):
        service_error = oci.exceptions.ServiceError(503, "ServiceUnavailable", {}, "temporary OCI failure")
        with patch.object(instances, "_fetch_instance_state", side_effect=service_error), patch.object(
            instances.time, "sleep"
        ):
            result = instances._recheck_instance_state("instance-1", delays=(0,))
        self.assertIsNone(result["state"])
        self.assertIn("temporary OCI failure", result["recheck_error"])

    def test_recheck_requests_error_is_reported(self):
        with patch.object(
            instances, "_fetch_instance_state", side_effect=requests.exceptions.Timeout("temporary network failure")
        ), patch.object(instances.time, "sleep"):
            result = instances._recheck_instance_state("instance-1", delays=(0,))
        self.assertIsNone(result["state"])
        self.assertIn("temporary network failure", result["recheck_error"])


if __name__ == "__main__":
    unittest.main()
