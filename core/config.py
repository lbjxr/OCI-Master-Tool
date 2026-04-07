"""
OCI Master - 配置加载模块
"""
import os
import json
from typing import Dict, Any, Optional
import oci


# 配置文件路径
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_APP_CONFIG_PATH = os.path.join(BASE_DIR, "oci_master_config.json")
DEFAULT_APP_CONFIG_EXAMPLE_PATH = os.path.join(BASE_DIR, "oci_master_config.example.json")


def load_app_config(config_path: Optional[str] = None) -> Dict[str, Any]:
    """加载应用配置文件，用于 OCI 读取参数、策略参数、Telegram Bot 参数。"""
    target_path = config_path or os.environ.get("OCI_MASTER_APP_CONFIG") or DEFAULT_APP_CONFIG_PATH

    if not os.path.exists(target_path):
        raise FileNotFoundError(
            f"未找到应用配置文件：{target_path}\n"
            f"请先参考示例文件创建配置：{DEFAULT_APP_CONFIG_EXAMPLE_PATH}"
        )

    with open(target_path, "r", encoding="utf-8") as file:
        cfg = json.load(file)
    
    # 基础配置校验
    if "oci" not in cfg:
        raise ValueError("配置文件缺少必填字段: oci")
    
    return cfg


def get_oci_config(app_config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """加载 OCI SDK 配置，支持通过应用配置文件传入路径和 profile。"""
    app_config = app_config or load_app_config()
    oci_settings = app_config.get("oci", {})
    config_file = oci_settings.get("config_file")
    profile = oci_settings.get("profile_name", "DEFAULT")

    if config_file:
        return oci.config.from_file(file_location=config_file, profile_name=profile)
    return oci.config.from_file(profile_name=profile)


def get_default_compartment_id(config: Dict[str, Any], app_config: Optional[Dict[str, Any]] = None) -> str:
    """获取默认 compartment_id；未配置时回退到 tenancy 根 compartment。"""
    app_config = app_config or {}
    network_firewall_cfg = app_config.get("network_firewall", {})
    return (
        network_firewall_cfg.get("default_compartment_id")
        or app_config.get("oci", {}).get("compartment_id")
        or config.get("tenancy")
    )
