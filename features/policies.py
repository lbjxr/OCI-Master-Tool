"""
OCI Master - 密码策略管理功能
"""
import logging
from typing import Dict, Any, List, Optional, Tuple
import oci
from oci.identity_domains import models

from core import load_app_config, get_oci_config, safe_get

LOGGER = logging.getLogger(__name__)


def get_identity_domains_client(config: Dict[str, Any], domain_name: str = "Default"):
    """创建 Identity Domains 客户端"""
    identity_client = oci.identity.IdentityClient(config)
    domains_response = identity_client.list_domains(compartment_id=config["tenancy"])
    domains = domains_response.data
    
    target_domain = next((d for d in domains if d.display_name == domain_name), None)
    if not target_domain:
        raise ValueError(f"未找到 Identity Domain: {domain_name}")
    
    domain_url = target_domain.url
    return oci.identity_domains.IdentityDomainsClient(config, service_endpoint=domain_url)


def list_policies(app_config: Optional[Dict[str, Any]] = None) -> List[Any]:
    """获取所有密码策略列表"""
    app_config = app_config or load_app_config()
    config = get_oci_config(app_config)
    domain_name = app_config.get("oci", {}).get("identity_domain_name", "Default")
    
    client = get_identity_domains_client(config, domain_name=domain_name)
    response = client.list_password_policies()
    return getattr(response.data, "resources", [])


def get_policy_by_name(policy_name: str, app_config: Optional[Dict[str, Any]] = None) -> Optional[Any]:
    """根据名称获取策略"""
    policies = list_policies(app_config)
    return next((p for p in policies if getattr(p, "name", "") == policy_name), None)


def get_policy_runtime_config(app_config: Dict[str, Any]) -> Dict[str, Any]:
    """获取策略运行时配置"""
    policy_cfg = app_config.get("password_policy", {})
    return {
        "domain_name": app_config.get("oci", {}).get("identity_domain_name", "Default"),
        "source_policy_name": policy_cfg.get("source_policy_name", "Standard Password Policy"),
        "new_policy_name": policy_cfg.get("new_policy_name", "NeverExpireStandard"),
        "description": policy_cfg.get("description", "永不过期密码策略（基于 Standard Policy 克隆）"),
        "priority": policy_cfg.get("priority", 999),
        "password_expires_after": policy_cfg.get("password_expires_after", 0),
    }


def create_policy(
    policy_name: str,
    expires_after_days: int = 0,
    app_config: Optional[Dict[str, Any]] = None
) -> Tuple[bool, str]:
    """
    创建密码策略
    
    Args:
        policy_name: 策略名称
        expires_after_days: 密码过期天数（0 表示永不过期）
        app_config: 应用配置
    
    Returns:
        (成功标志, 消息)
    """
    try:
        app_config = app_config or load_app_config()
        config = get_oci_config(app_config)
        policy_cfg = get_policy_runtime_config(app_config)
        
        client = get_identity_domains_client(config, domain_name=policy_cfg["domain_name"])
        
        # 获取源策略（用于克隆配置）
        policies = list_policies(app_config)
        source_policy = next(
            (p for p in policies if getattr(p, "name", "") == policy_cfg["source_policy_name"]),
            None,
        )
        
        if not source_policy:
            return False, f"❌ 未找到源策略: {policy_cfg['source_policy_name']}"
        
        # 构建新策略
        new_policy_details = {
            "name": policy_name,
            "description": f"密码{expires_after_days}天过期策略（基于 {policy_cfg['source_policy_name']} 克隆）",
            "schemas": ["urn:ietf:params:scim:schemas:oracle:idcs:PasswordPolicy"],
            "priority": policy_cfg["priority"],
            "password_expires_after": expires_after_days,
            "min_length": getattr(source_policy, "min_length", 8),
            "max_length": getattr(source_policy, "max_length", 40),
            "min_lower_case": getattr(source_policy, "min_lower_case", 1),
            "min_upper_case": getattr(source_policy, "min_upper_case", 1),
            "min_numerals": getattr(source_policy, "min_numerals", 1),
            "min_special_chars": getattr(source_policy, "min_special_chars", 0),
            "max_incorrect_attempts": getattr(source_policy, "max_incorrect_attempts", 5),
            "lockout_duration": getattr(source_policy, "lockout_duration", 30),
            "num_passwords_in_history": getattr(source_policy, "num_passwords_in_history", 1),
            "user_name_disallowed": getattr(source_policy, "user_name_disallowed", True),
            "first_name_disallowed": getattr(source_policy, "first_name_disallowed", True),
            "last_name_disallowed": getattr(source_policy, "last_name_disallowed", True),
        }
        
        new_policy_obj = models.PasswordPolicy(**new_policy_details)
        response = client.create_password_policy(password_policy=new_policy_obj)
        
        if response.status == 201:
            return True, f"✅ 成功创建策略: {policy_name}"
        else:
            return False, f"⚠️ 创建返回异常状态: {response.status}"
    
    except Exception as e:
        LOGGER.exception("创建策略失败")
        if "already exists" in str(e).lower():
            return False, f"❌ 策略已存在: {policy_name}"
        return False, f"❌ 创建失败: {str(e)[:200]}"


def delete_policy(
    policy_name: str,
    app_config: Optional[Dict[str, Any]] = None
) -> Tuple[bool, str]:
    """
    删除密码策略
    
    Args:
        policy_name: 策略名称
        app_config: 应用配置
    
    Returns:
        (成功标志, 消息)
    """
    try:
        app_config = app_config or load_app_config()
        config = get_oci_config(app_config)
        domain_name = app_config.get("oci", {}).get("identity_domain_name", "Default")
        
        client = get_identity_domains_client(config, domain_name=domain_name)
        
        # 查找目标策略
        policy = get_policy_by_name(policy_name, app_config)
        if not policy:
            return False, f"❌ 未找到策略: {policy_name}"
        
        # 执行删除
        response = client.delete_password_policy(password_policy_id=policy.id)
        
        if response.status == 204:
            return True, f"✅ 成功删除策略: {policy_name}"
        else:
            return False, f"⚠️ 删除返回异常状态: {response.status}"
    
    except Exception as e:
        LOGGER.exception("删除策略失败")
        if "checkProtectedResource" in str(e):
            return False, f"❌ 无法删除系统保护策略: {policy_name}"
        return False, f"❌ 删除失败: {str(e)[:200]}"
