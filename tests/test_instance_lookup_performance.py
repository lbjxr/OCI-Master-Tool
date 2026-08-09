import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from oci_master.services import instances


class InstanceLookupPerformanceTests(unittest.TestCase):
    def setUp(self):
        self.config = {"tenancy": "tenancy-1", "region": "region-1"}
        self.compute = Mock()
        self.compute.get_instance.return_value = SimpleNamespace(
            data=SimpleNamespace(
                id="ocid1.instance.oc1..abc",
                display_name="vm-1",
                compartment_id="compartment-1",
                lifecycle_state="RUNNING",
                shape="VM.Standard",
                availability_domain="AD-1",
                time_created=None,
                fault_domain="FD-1",
                image_id="image-1",
                shape_config=SimpleNamespace(memory_in_gbs=4, ocpus=1),
                source_details=SimpleNamespace(source_type="image"),
            )
        )

    def test_detail_by_ocid_gets_instance_without_tenant_scan(self):
        with patch.object(instances, "get_oci_config", return_value=self.config), patch.object(
            instances, "get_compute_client", return_value=self.compute
        ), patch.object(instances.oci.identity, "IdentityClient") as identity, patch.object(
            instances, "get_virtual_network_client", return_value=Mock()
        ):
            result = instances.get_instance_detail_data("ocid1.instance.oc1..abc", self.config)

        self.assertEqual(result["id"], "ocid1.instance.oc1..abc")
        self.compute.get_instance.assert_called_once_with("ocid1.instance.oc1..abc")
        identity.assert_not_called()

    def test_name_lookup_lists_instances_but_does_not_fetch_vnics(self):
        identity = Mock()
        identity.get_compartment.return_value = SimpleNamespace(data=SimpleNamespace(id="tenancy-1", name="root"))
        identity.list_compartments.return_value = SimpleNamespace(data=[])
        listed = SimpleNamespace(
            id="ocid1.instance.oc1..abc", display_name="vm-1", compartment_id="compartment-1",
            lifecycle_state="RUNNING", shape="VM.Standard", availability_domain="AD-1", time_created=None,
        )
        self.compute.list_instances.return_value = SimpleNamespace(data=[listed])
        with patch.object(instances, "get_oci_config", return_value=self.config), patch.object(
            instances, "get_compute_client", return_value=self.compute
        ), patch.object(instances.oci.identity, "IdentityClient", return_value=identity), patch.object(
            instances, "get_virtual_network_client", return_value=Mock()
        ), patch.object(instances.oci.pagination, "list_call_get_all_results", side_effect=[
            SimpleNamespace(data=[]), SimpleNamespace(data=[listed])
        ]):
            result = instances.get_instance_detail_data("vm-1", self.config)

        self.assertEqual(result["id"], "ocid1.instance.oc1..abc")
        self.compute.list_vnic_attachments.assert_not_called()
        self.compute.get_instance.assert_called_once_with("ocid1.instance.oc1..abc")

    def test_instance_list_does_not_fetch_vnics_or_network_client(self):
        identity = Mock()
        identity.get_compartment.return_value = SimpleNamespace(data=SimpleNamespace(id="tenancy-1", name="root"))
        identity.list_compartments.return_value = SimpleNamespace(data=[])
        listed = SimpleNamespace(
            id="ocid1.instance.oc1..abc", display_name="vm-1", compartment_id="compartment-1",
            lifecycle_state="RUNNING", shape="VM.Standard", availability_domain="AD-1", time_created=None,
        )
        self.compute.list_instances.return_value = SimpleNamespace(data=[listed])
        with patch.object(instances, "get_oci_config", return_value=self.config), patch.object(
            instances, "get_compute_client", return_value=self.compute
        ), patch.object(instances.oci.identity, "IdentityClient", return_value=identity), patch.object(
            instances, "get_virtual_network_client", return_value=Mock()
        ) as network_client, patch.object(
            instances.oci.pagination, "list_call_get_all_results", side_effect=[
                SimpleNamespace(data=[]), SimpleNamespace(data=[listed])
            ]
        ):
            result = instances.list_instances_data(self.config)

        self.assertEqual(result["items"][0]["ip_address"], "N/A")
        self.compute.list_vnic_attachments.assert_not_called()
        network_client.assert_not_called()


if __name__ == "__main__":
    unittest.main()
