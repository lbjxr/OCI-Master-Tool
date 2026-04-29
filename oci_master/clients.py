from typing import Any, Dict

import oci


def get_identity_domains_client(config: Dict[str, Any], domain_name: str = "Default"):
    identity_client = oci.identity.IdentityClient(config)
    response = identity_client.list_domains(config["tenancy"])
    if response is None or response.data is None:
        raise ValueError("Failed to retrieve domains from OCI")

    domains = response.data
    target_domain = next((d for d in domains if d.display_name == domain_name), None)
    if target_domain is None:
        raise ValueError(f"未找到名为 {domain_name} 的 Identity Domain")

    domain_url = target_domain.url.replace(":443", "")
    return oci.identity_domains.IdentityDomainsClient(config, service_endpoint=domain_url)


def get_compute_client(config: Dict[str, Any]):
    return oci.core.ComputeClient(config)


def get_virtual_network_client(config: Dict[str, Any]):
    return oci.core.VirtualNetworkClient(config)
