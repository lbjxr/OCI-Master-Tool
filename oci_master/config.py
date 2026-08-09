import json
import os
from typing import Any, Dict, Optional

import oci


BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_APP_CONFIG_PATH = os.path.join(BASE_DIR, "oci_master_config.json")
DEFAULT_APP_CONFIG_EXAMPLE_PATH = os.path.join(BASE_DIR, "oci_master_config.example.json")
DEFAULT_TELEGRAM_RUNTIME = {
    "poll_interval_seconds": 3,
    "initial_update_offset": 0,
}


def load_app_config(config_path: Optional[str] = None) -> Dict[str, Any]:
    target_path = config_path or os.environ.get("OCI_MASTER_APP_CONFIG") or DEFAULT_APP_CONFIG_PATH
    if not os.path.exists(target_path):
        raise FileNotFoundError(
            "未找到应用配置文件：{0}\n请先参考示例文件创建配置：{1}".format(
                target_path, DEFAULT_APP_CONFIG_EXAMPLE_PATH
            )
        )
    with open(target_path, "r", encoding="utf-8") as file:
        app_config = json.load(file)
    return normalize_app_config(app_config)


def normalize_app_config(app_config: Dict[str, Any]) -> Dict[str, Any]:
    normalized = dict(app_config or {})
    oci_cfg = dict(normalized.get("oci", {}))
    profiles = normalized.get("profiles")
    active_profile = normalized.get("active_profile") or oci_cfg.get("profile_name") or "DEFAULT"

    if not profiles:
        profiles = {
            active_profile: {
                "config_file": oci_cfg.get("config_file"),
                "profile_name": oci_cfg.get("profile_name", active_profile),
                "identity_domain_name": oci_cfg.get("identity_domain_name", "Default"),
                "region": oci_cfg.get("region"),
                "instance_defaults": dict(oci_cfg.get("instance_defaults", {})),
            }
        }

    selected = dict(profiles.get(active_profile) or {})
    merged_oci = {
        "config_file": selected.get("config_file", oci_cfg.get("config_file")),
        "profile_name": selected.get("profile_name", active_profile),
        "identity_domain_name": selected.get("identity_domain_name", oci_cfg.get("identity_domain_name", "Default")),
        "region": selected.get("region", oci_cfg.get("region")),
        "instance_defaults": dict(selected.get("instance_defaults") or oci_cfg.get("instance_defaults", {})),
    }

    normalized["active_profile"] = active_profile
    normalized["profiles"] = profiles
    normalized["oci"] = merged_oci
    return normalized


def get_active_profile_name(app_config: Dict[str, Any]) -> str:
    return str(app_config.get("active_profile") or app_config.get("oci", {}).get("profile_name") or "DEFAULT")


def get_oci_profile_settings(app_config: Dict[str, Any]) -> Dict[str, Any]:
    app_config = normalize_app_config(app_config)
    active_profile = get_active_profile_name(app_config)
    return dict(app_config.get("profiles", {}).get(active_profile) or app_config.get("oci", {}))


def get_oci_config(app_config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    app_config = normalize_app_config(app_config or load_app_config())
    oci_settings = get_oci_profile_settings(app_config)
    config_file = oci_settings.get("config_file")
    profile = oci_settings.get("profile_name", get_active_profile_name(app_config))

    if config_file:
        return oci.config.from_file(file_location=config_file, profile_name=profile)
    return oci.config.from_file(profile_name=profile)


def get_policy_runtime_config(app_config: Dict[str, Any]) -> Dict[str, Any]:
    policy_cfg = app_config.get("policy", {})
    create_cfg = policy_cfg.get("create_safe_policy", {})
    return {
        "domain_name": get_oci_profile_settings(app_config).get("identity_domain_name", "Default"),
        "new_policy_name": create_cfg.get("name", "NeverExpireStandard"),
        "description": create_cfg.get(
            "description",
            "基于 Standard 规则克隆，由 API 强制设为永不过期 (Priority 1)",
        ),
        "priority": create_cfg.get("priority", 1),
        "password_expires_after": create_cfg.get("password_expires_after", 0),
        "source_policy_name": create_cfg.get("source_policy_name", "standardPasswordPolicy"),
    }


def get_instance_runtime_config(app_config: Dict[str, Any]) -> Dict[str, Any]:
    app_config = normalize_app_config(app_config)
    root_cfg = dict(app_config.get("instances", {}))
    profile_cfg = dict(get_oci_profile_settings(app_config).get("instance_defaults", {}))

    page_size = profile_cfg.get("telegram_page_size", root_cfg.get("telegram_page_size", 8))
    try:
        page_size = max(1, int(page_size))
    except Exception:
        page_size = 8

    return {
        "telegram_page_size": page_size,
        "default_compartment_ids": profile_cfg.get(
            "default_compartment_ids",
            root_cfg.get("default_compartment_ids", []),
        ) or [],
        "default_compartment_names": profile_cfg.get(
            "default_compartment_names",
            root_cfg.get("default_compartment_names", []),
        ) or [],
    }


def get_network_runtime_config(app_config: Dict[str, Any]) -> Dict[str, Any]:
    app_config = normalize_app_config(app_config)
    network_cfg = dict(app_config.get("network_security", {}))

    allowed_ports = network_cfg.get("quick_open_allowed_tcp_ports", [22, 80, 443, 3389])
    normalized_ports = []
    for item in allowed_ports:
        try:
            value = int(item)
        except Exception:
            continue
        if 1 <= value <= 65535:
            normalized_ports.append(value)
    if not normalized_ports:
        normalized_ports = [22, 80, 443, 3389]

    return {
        "quick_open_allowed_tcp_ports": normalized_ports,
        "default_source_cidr": str(network_cfg.get("default_source_cidr", "0.0.0.0/0") or "0.0.0.0/0"),
        "allow_public_cidr": bool(network_cfg.get("allow_public_cidr", False)),
    }


def get_telegram_runtime_config(app_config: Dict[str, Any]) -> Dict[str, Any]:
    telegram_cfg = dict((app_config or {}).get("telegram", {}))
    runtime = dict(DEFAULT_TELEGRAM_RUNTIME)
    for key in runtime:
        if key in telegram_cfg:
            runtime[key] = telegram_cfg[key]
    try:
        runtime["poll_interval_seconds"] = max(1, int(runtime["poll_interval_seconds"]))
    except (TypeError, ValueError):
        runtime["poll_interval_seconds"] = DEFAULT_TELEGRAM_RUNTIME["poll_interval_seconds"]
    try:
        runtime["initial_update_offset"] = int(runtime["initial_update_offset"])
    except (TypeError, ValueError):
        runtime["initial_update_offset"] = DEFAULT_TELEGRAM_RUNTIME["initial_update_offset"]
    return runtime
