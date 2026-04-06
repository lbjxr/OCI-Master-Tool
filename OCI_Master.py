import io
import json
import os
import sys
import time
import html
import csv
import logging
import argparse
from pathlib import Path
from contextlib import redirect_stdout
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

import oci
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_APP_CONFIG_PATH = os.path.join(BASE_DIR, "oci_master_config.json")
DEFAULT_APP_CONFIG_EXAMPLE_PATH = os.path.join(BASE_DIR, "oci_master_config.example.json")

# Constants
TELEGRAM_MAX_MESSAGE_LENGTH = 3900
DEFAULT_DISPLAY_DAYS = 1

# Simple logger setup (overridable via --verbose or OCI_MASTER_LOG_LEVEL)
LOGGER = logging.getLogger("oci_master")

def setup_logger(level: Optional[str] = None, verbose: bool = False) -> None:
    lvl = (level or os.environ.get("OCI_MASTER_LOG_LEVEL") or ("DEBUG" if verbose else "INFO")).upper()
    logging.basicConfig(
        level=getattr(logging, lvl, logging.INFO),
        format="%(asctime)s %(levelname)s %(message)s",
    )


def create_requests_session(
    total_retries: int = 3,
    backoff_factor: float = 0.5,
    status_forcelist: Tuple[int, ...] = (429, 500, 502, 503, 504),
) -> requests.Session:
    """Create a requests Session with sane HTTP retry behavior."""
    session = requests.Session()
    adapter = HTTPAdapter(
        max_retries=Retry(
            total=total_retries,
            backoff_factor=backoff_factor,
            status_forcelist=status_forcelist,
            allowed_methods=frozenset(["GET", "POST", "PUT", "DELETE", "PATCH"]),
        )
    )
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


def print_divider(char: str = "=", width: int = 64) -> None:
    print(char * width)


def print_section(title: str, icon: str = "📌", width: int = 64) -> None:
    print()
    print_divider("=", width)
    print(f"{icon} {title}")
    print_divider("=", width)


def print_kv(label: str, value: Any, width: int = 28) -> None:
    print(f"{label:<{width}} : {value}")


def truncate_text(value: Any, width: int) -> str:
    text = str(value)
    if len(text) <= width:
        return text
    return text[: max(0, width - 3)] + "..."


def build_text_table(headers: List[str], rows: List[List[Any]]) -> str:
    if not rows:
        return "(无数据)"

    normalized_rows = [["" if cell is None else str(cell) for cell in row] for row in rows]
    widths = []
    for index, header in enumerate(headers):
        max_row_width = max((len(row[index]) for row in normalized_rows), default=0)
        widths.append(max(len(header), max_row_width))

    def format_row(row: List[str]) -> str:
        return "| " + " | ".join(f"{row[i]:<{widths[i]}}" for i in range(len(headers))) + " |"

    border = "+-" + "-+-".join("-" * width for width in widths) + "-+"
    lines = [border, format_row(headers), border]
    for row in normalized_rows:
        lines.append(format_row(row))
    lines.append(border)
    return "\n".join(lines)


def build_inline_keyboard(button_rows: List[List[Dict[str, str]]]) -> Dict[str, Any]:
    return {"inline_keyboard": button_rows}


# ==========================================
# 1. 配置与通用辅助函数
# ==========================================
def safe_get(obj: Any, attr_name: str, default: Any = "N/A") -> Any:
    """安全读取对象属性，兼容 dict / SDK model / 普通对象。"""
    if obj is None:
        return default

    if isinstance(obj, dict):
        value = obj.get(attr_name, default)
    else:
        value = getattr(obj, attr_name, default)

    return default if value is None else value


def safe_get_any(obj: Any, *attr_names: str, default: Any = "N/A") -> Any:
    """按顺序尝试多个属性名，适配 snake_case / camelCase / 原始 SCIM key。"""
    for attr_name in attr_names:
        value = safe_get(obj, attr_name, default)
        if value != default:
            return value
    return default


def unwrap_state_value(value: Any, *nested_keys: str, default: Any = "N/A") -> Any:
    """兼容扩展状态字段既可能是布尔/字符串，也可能是嵌套对象的情况。"""
    if value is None:
        return default

    if isinstance(value, dict):
        for key in nested_keys:
            nested = value.get(key)
            if nested is not None:
                return nested
        return value if value else default

    for key in nested_keys:
        nested = safe_get(value, key, None)
        if nested is not None:
            return nested

    return value


def format_bool(value: Any) -> str:
    if isinstance(value, bool):
        return "Yes" if value else "No"
    return str(value)


def load_app_config(config_path: Optional[str] = None) -> Dict[str, Any]:
    """加载应用配置文件，用于 OCI 读取参数、策略参数、Telegram Bot 参数。"""
    target_path = config_path or os.environ.get("OCI_MASTER_APP_CONFIG") or DEFAULT_APP_CONFIG_PATH

    if not os.path.exists(target_path):
        raise FileNotFoundError(
            "未找到应用配置文件：{0}\n请先参考示例文件创建配置：{1}".format(
                target_path, DEFAULT_APP_CONFIG_EXAMPLE_PATH
            )
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


def _normalize_collection_items(data: Any) -> List[Any]:
    """兼容 OCI SDK 返回 list 或 *Collection(items=[])."""
    if data is None:
        return []
    if isinstance(data, list):
        return data
    return getattr(data, "items", []) or []


def _protocol_name(value: Any) -> str:
    mapping = {
        "1": "ICMP",
        "6": "TCP",
        "17": "UDP",
        "58": "ICMPv6",
        "all": "ALL",
    }
    key = str(value).lower()
    return mapping.get(key, str(value))


def _format_port_range(port_range: Any) -> str:
    if not port_range:
        return "all"
    min_port = safe_get(port_range, "min", default=None)
    max_port = safe_get(port_range, "max", default=None)
    if min_port in (None, "N/A") and max_port in (None, "N/A"):
        return "all"
    if min_port == max_port:
        return str(min_port)
    return f"{min_port}-{max_port}"


def _extract_rule_port_text(rule: Any) -> str:
    tcp_options = safe_get(rule, "tcp_options", default=None)
    udp_options = safe_get(rule, "udp_options", default=None)
    icmp_options = safe_get(rule, "icmp_options", default=None)
    icmp6_options = safe_get(rule, "icmp_options", default=None)

    if tcp_options is not None and not isinstance(tcp_options, str):
        return f"tcp/{_format_port_range(safe_get(tcp_options, 'destination_port_range', default=None))}"
    if udp_options is not None and not isinstance(udp_options, str):
        return f"udp/{_format_port_range(safe_get(udp_options, 'destination_port_range', default=None))}"
    if icmp_options is not None and not isinstance(icmp_options, str):
        icmp_type = safe_get(icmp_options, "type", default="*")
        icmp_code = safe_get(icmp_options, "code", default="*")
        return f"icmp(type={icmp_type},code={icmp_code})"
    if icmp6_options is not None and not isinstance(icmp6_options, str):
        icmp_type = safe_get(icmp6_options, "type", default="*")
        icmp_code = safe_get(icmp6_options, "code", default="*")
        return f"icmp6(type={icmp_type},code={icmp_code})"
    return "all"


    """获取 Identity Domain 客户端。"""
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


def capture_output(func: Callable, *args, **kwargs) -> str:
    """捕获函数标准输出，供 Telegram 回复使用。"""
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        func(*args, **kwargs)
    return buffer.getvalue().strip()


def get_policy_runtime_config(app_config: Dict[str, Any]) -> Dict[str, Any]:
    policy_cfg = app_config.get("policy", {})
    create_cfg = policy_cfg.get("create_safe_policy", {})
    return {
        "domain_name": app_config.get("oci", {}).get("identity_domain_name", "Default"),
        "new_policy_name": create_cfg.get("name", "NeverExpireStandard"),
        "description": create_cfg.get(
            "description",
            "基于 Standard 规则克隆，由 API 强制设为永不过期 (Priority 1)",
        ),
        "priority": create_cfg.get("priority", 1),
        "password_expires_after": create_cfg.get("password_expires_after", 0),
        "source_policy_name": create_cfg.get("source_policy_name", "standardPasswordPolicy"),
    }


# ==========================================
# 2. 用户信息查询（已整合 OCI_User_Info.py）
# ==========================================
def find_current_user_in_domain(id_domains_client, user_ocid: str) -> Dict[str, Any]:
    """从 Identity Domain 中查询当前用户，拿到更完整的 SCIM 用户信息。"""
    search_response = id_domains_client.list_users(
        filter=f'ocid eq "{user_ocid}"',
        attributes=(
            "id,ocid,userName,displayName,description,active,emails,phoneNumbers,"
            "groups,roles,meta,name,locale,timezone,userType,preferredLanguage,"
            "urn:ietf:params:scim:schemas:oracle:idcs:extension:userState:User,"
            "urn:ietf:params:scim:schemas:oracle:idcs:extension:passwordState:User"
        ),
        attribute_sets=["all"],
    )

    resources = getattr(getattr(search_response, "data", None), "resources", [])
    if not resources:
        raise ValueError("在 Identity Domain 中未找到当前用户")

    return oci.util.to_dict(resources[0])


def print_basic_identity_info(user_data: Dict[str, Any]) -> None:
    print_section("基础信息", "👤")
    print_kv("用户名 (user_name)", safe_get_any(user_data, 'user_name', 'userName'))
    print_kv("显示名称 (display_name)", safe_get_any(user_data, 'display_name', 'displayName'))
    print_kv("描述/全名", safe_get(user_data, 'description'))
    print_kv("用户 ID", safe_get(user_data, 'id'))
    print_kv("用户 OCID", safe_get(user_data, 'ocid', safe_get(user_data, 'id')))
    print_kv("Active", format_bool(safe_get(user_data, 'active')))
    print_kv("用户类型", safe_get_any(user_data, 'user_type', 'userType'))
    print_kv("Locale", safe_get(user_data, 'locale'))
    print_kv("Timezone", safe_get(user_data, 'timezone'))
    print_kv("Preferred Language", safe_get_any(user_data, 'preferred_language', 'preferredLanguage'))


def print_contact_info(user_data: Dict[str, Any]) -> None:
    print_section("联系方式", "📇")

    emails = safe_get(user_data, "emails", [])
    if emails and emails != "N/A":
        for index, email in enumerate(emails, start=1):
            print(
                f"📧 邮箱 {index}: value={safe_get(email, 'value')}, "
                f"type={safe_get(email, 'type')}, primary={safe_get(email, 'primary', False)}"
            )
    else:
        print("📧 邮箱: N/A")

    phones = safe_get_any(user_data, "phone_numbers", "phoneNumbers", default=[])
    if phones and phones != "N/A":
        for index, phone in enumerate(phones, start=1):
            print(
                f"📱 电话 {index}: value={safe_get(phone, 'value')}, "
                f"type={safe_get(phone, 'type')}, primary={safe_get(phone, 'primary', False)}"
            )
    else:
        print("📱 电话: N/A")


def print_membership_info(user_data: Dict[str, Any]) -> None:
    print_section("权限归属", "🛡️")

    groups = safe_get(user_data, "groups", [])
    if groups and groups != "N/A":
        print(f"👪 所属组数量: {len(groups)}")
        for index, group in enumerate(groups[:10], start=1):
            print(f"   - 组 {index}: {safe_get(group, 'display', safe_get(group, 'value'))}")
        if len(groups) > 10:
            print(f"   ... 其余 {len(groups) - 10} 个组未展开")
    else:
        print("👪 所属组: N/A")

    roles = safe_get(user_data, "roles", [])
    if roles and roles != "N/A":
        print(f"🛡️ 角色数量: {len(roles)}")
        for index, role in enumerate(roles[:10], start=1):
            print(f"   - 角色 {index}: {safe_get(role, 'display', safe_get(role, 'value'))}")
        if len(roles) > 10:
            print(f"   ... 其余 {len(roles) - 10} 个角色未展开")
    else:
        print("🛡️ 角色: N/A")


def print_extension_info(user_data: Dict[str, Any]) -> None:
    print_section("扩展账号状态信息", "🔍")

    user_state = safe_get_any(
        user_data,
        "urn_ietf_params_scim_schemas_oracle_idcs_extension_user_state_user",
        "urn:ietf:params:scim:schemas:oracle:idcs:extension:userState:User",
        default=None,
    )
    password_state = safe_get_any(
        user_data,
        "urn_ietf_params_scim_schemas_oracle_idcs_extension_password_state_user",
        "urn:ietf:params:scim:schemas:oracle:idcs:extension:passwordState:User",
        default=None,
    )

    if user_state and user_state != "N/A":
        locked_value = unwrap_state_value(safe_get(user_state, "locked", None), "on", default="N/A")
        print(f"🔐 账号锁定状态 (locked)       : {locked_value}")
        print(f"⏰ 锁定到期时间 (lock_date)     : {safe_get_any(user_state, 'lock_date', 'lockDate')}")
        print(f"❌ 登录失败次数                : {safe_get_any(user_state, 'failed_login_attempts', 'failedLoginAttempts')}")
        print(f"🕘 最近成功登录时间            : {safe_get_any(user_state, 'last_successful_login_date', 'lastSuccessfulLoginDate')}")
        print(f"🚫 最近失败登录时间            : {safe_get_any(user_state, 'last_failed_login_date', 'lastFailedLoginDate')}")
    else:
        print("🔐 userState 扩展信息: N/A")

    if password_state and password_state != "N/A":
        expired_value = unwrap_state_value(safe_get(password_state, "expired", None), "on", default="N/A")
        print(f"🔑 密码已过期 (expired)        : {expired_value}")
        print(f"📅 密码过期时间                : {safe_get_any(password_state, 'expiry_date', 'expiryDate')}")
        print(f"🔄 是否需修改密码              : {safe_get_any(password_state, 'must_change', 'mustChange')}")
        print(f"🧾 上次修改密码时间            : {safe_get_any(password_state, 'last_successful_set_date', 'lastSuccessfulSetDate')}")
    else:
        print("🔑 passwordState 扩展信息: N/A")


def get_user_info(app_config: Optional[Dict[str, Any]] = None) -> None:
    """功能 1：查询当前用户详细信息。"""
    print()
    print_divider("=", 40)
    print("👤 正在查询用户详细信息...")
    print_divider("=", 40)

    try:
        app_config = app_config or load_app_config()
        config = get_oci_config(app_config)
        identity_client = oci.identity.IdentityClient(config)
        basic_response = identity_client.get_user(config["user"])

        if not basic_response or not getattr(basic_response, "data", None):
            print("❌ 未能从 IAM 获取当前用户基础信息。")
            return

        current_user_ocid = safe_get(basic_response.data, "id")
        domain_name = app_config.get("oci", {}).get("identity_domain_name", "Default")
        id_domains_client = get_identity_domains_client(config, domain_name=domain_name)
        domain_user = find_current_user_in_domain(id_domains_client, current_user_ocid)

        print("✅ 连接成功！已获取更详细的账号信息。")
        print_basic_identity_info(domain_user)
        print_contact_info(domain_user)
        print_membership_info(domain_user)
        print_extension_info(domain_user)
        print()
    except Exception as e:
        print(f"❌ 查询失败，请检查 OCI 配置、租户域设置或接口权限：\n{e}")


# ==========================================
# 3. 费用与密码策略功能
# ==========================================
def _print_policy_table(id_domains_client) -> bool:
    response = id_domains_client.list_password_policies()
    resources = getattr(response.data, "resources", [])

    if not resources:
        print("❌ 未发现任何策略。")
        return False

    sorted_policies = sorted(
        resources,
        key=lambda x: getattr(x, "priority", 999) if getattr(x, "priority", None) is not None else 999,
    )

    print(f"\n{'策略名称':<25} | {'优先级':<6} | {'过期天数':<12} | {'当前状态'}")
    print("-" * 80)

    for p in sorted_policies:
        name = str(getattr(p, "name", "N/A") or "N/A")
        priority = str(getattr(p, "priority", "N/A") or "N/A")
        expires = str(getattr(p, "password_expires_after", "N/A") or "N/A")
        is_top = p == sorted_policies[0]
        status = "🚀 正在生效 (最高)" if is_top else "⏳ 备用/次要"
        expire_display = f"{expires} (永不过期)" if expires == "0" else f"{expires} 天"
        print(f"{name:<25} | {priority:<6} | {expire_display:<12} | {status}")

    print("-" * 80)
    return True


def export_usage_fee(
    app_config: Optional[Dict[str, Any]] = None,
    show_all: bool = False,
    csv_out: Optional[str] = None,
) -> None:
    """功能 2：查询本月费用账单，支持可选 CSV 导出与展开所有日期。"""
    print("\n" + "=" * 65)
    print("💰 正在查询本月费用数据...")
    try:
        app_config = app_config or load_app_config()
        report_data = get_usage_fee_report_data(app_config)
        # 渲染 CLI 视图
        print(render_usage_fee_cli(report_data, show_all=show_all))

        # 处理 CSV 导出
        output_cfg = app_config.get("output", {})
        csv_path = csv_out or output_cfg.get("usage_fee_csv_path")
        if not csv_path:
            csv_dir = output_cfg.get("usage_fee_csv_dir")
            if csv_dir:
                month_tag = report_data["end_time"].strftime("%Y%m")
                csv_path = os.path.join(csv_dir, f"usage_fee_{month_tag}.csv")
        if csv_path:
            os.makedirs(os.path.dirname(csv_path), exist_ok=True)
            unique_dates = report_data["unique_dates"]
            display_days = report_data["display_days"]
            latest_dates = set(unique_dates if show_all else unique_dates[-display_days:]) if unique_dates else set()
            rows_to_write = [row for row in report_data["rows"] if (row[0] in latest_dates) or show_all]
            with open(csv_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["date", "service", "amount", "currency"])
                writer.writerows(rows_to_write)
            print_kv("CSV 已导出", csv_path)
    except Exception as e:
        print(f"❌ 运行出错: {e}")


def get_usage_fee_report_data(app_config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    app_config = app_config or load_app_config()
    config = get_oci_config(app_config)
    usage_client = oci.usage_api.UsageapiClient(config)
    output_cfg = app_config.get("output", {})
    display_days = int(output_cfg.get("usage_fee_display_days", DEFAULT_DISPLAY_DAYS) or DEFAULT_DISPLAY_DAYS)

    now_utc = datetime.now(timezone.utc)
    start_time = now_utc.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    end_time = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)

    request_details = oci.usage_api.models.RequestSummarizedUsagesDetails(
        tenant_id=config["tenancy"],
        time_usage_started=start_time,
        time_usage_ended=end_time,
        granularity="DAILY",
        query_type="COST",
        group_by=["service"],
    )

    response = usage_client.request_summarized_usages(request_details)
    items = getattr(response.data, "items", []) or []

    total_cost = 0.0
    currency = "USD"
    rows: List[List[str]] = []
    unique_dates: List[str] = []
    seen_dates = set()

    for item in sorted(items, key=lambda x: x.time_usage_started):
        date_str = item.time_usage_started.strftime("%Y-%m-%d")
        service = getattr(item, "service", "Unknown Service") or "Unknown Service"
        amount = getattr(item, "computed_amount", 0.0) or 0.0
        currency = getattr(item, "currency", "USD") or currency or "USD"
        total_cost += amount

        rows.append([date_str, service, f"{amount:.4f}", currency])
        if date_str not in seen_dates:
            seen_dates.add(date_str)
            unique_dates.append(date_str)

    return {
        "start_time": start_time,
        "end_time": end_time,
        "rows": rows,
        "unique_dates": unique_dates,
        "display_days": display_days,
        "total_cost": total_cost,
        "currency": currency,
    }


def render_usage_fee_cli(report_data: Dict[str, Any], show_all: bool = False) -> str:
    rows = report_data["rows"]
    unique_dates = report_data["unique_dates"]
    display_days = report_data["display_days"]

    if not unique_dates:
        return "\n".join([
            "\n" + "=" * 65,
            "💰 正在查询本月费用数据...",
            "",
            "=" * 64,
            "💰 本月费用汇总",
            "=" * 64,
            f"查询区间                         : {report_data['start_time'].strftime('%Y-%m-%d')} ~ {report_data['end_time'].strftime('%Y-%m-%d')}",
            "📊 本月暂无费用数据",
        ])

    latest_dates = set(unique_dates if show_all else unique_dates[-display_days:]) if unique_dates else set()
    display_rows = [
        [row[0], truncate_text(row[1], 28), row[2], row[3]]
        for row in rows
        if row[0] in latest_dates
    ]

    parts = [
        "\n" + "=" * 65,
        "💰 正在查询本月费用数据...",
        "",
        "=" * 64,
        "💰 本月费用汇总",
        "=" * 64,
        f"查询区间                         : {report_data['start_time'].strftime('%Y-%m-%d')} ~ {report_data['end_time'].strftime('%Y-%m-%d')}",
        f"账单总记录数                       : {len(rows)}",
        f"涉及日期数                        : {len(unique_dates)}",
        f"默认展示天数                       : {display_days}",
        f"📊 本月预估总计: {report_data['total_cost']:.4f} {report_data['currency']}",
        "",
        "=" * 64,
        f"📄 费用明细（{'展示全部数据' if show_all else f'默认仅展示最近 {display_days} 天'}）",
        "=" * 64,
        build_text_table(["日期", "服务名称", "金额", "币种"], display_rows),
    ]

    if not show_all and len(unique_dates) > display_days:
        hidden_days = len(unique_dates) - display_days
        parts.extend(["", f"ℹ️ 已折叠更早的 {hidden_days} 天数据；当前默认仅展示最近 {display_days} 天。"])

    return "\n".join(parts)


def render_usage_fee_telegram(report_data: Dict[str, Any], show_all: bool = False) -> str:
    rows = report_data["rows"]
    unique_dates = report_data["unique_dates"]
    display_days = report_data["display_days"]

    if not unique_dates:
        return "\n".join([
            "<b>💰 本月费用汇总</b>",
            f"查询区间: <code>{report_data['start_time'].strftime('%Y-%m-%d')} ~ {report_data['end_time'].strftime('%Y-%m-%d')}</code>",
            "📊 本月暂无费用数据"
        ])

    latest_dates = set(unique_dates if show_all else unique_dates[-display_days:]) if unique_dates else set()
    
    # 按日期分组汇总
    from collections import defaultdict
    daily_totals = defaultdict(float)
    daily_services = defaultdict(list)
    
    for row in rows:
        date_str, service, amount_str, currency = row
        if date_str in latest_dates:
            amount = float(amount_str)
            daily_totals[date_str] += amount
            daily_services[date_str].append((service, amount))
    
    hidden_days = max(0, len(unique_dates) - display_days)
    currency = report_data['currency']
    
    # 构建移动端友好的卡片式布局
    message_parts = [
        "<b>💰 本月费用汇总</b>",
        f"查询区间: <code>{report_data['start_time'].strftime('%Y-%m-%d')} ~ {report_data['end_time'].strftime('%Y-%m-%d')}</code>",
        f"本月预估总计: <b>{report_data['total_cost']:.4f} {html.escape(currency)}</b>",
        "",
        f"<b>📅 {'全部数据' if show_all else f'最近 {display_days} 天'} ({len(daily_totals)} 天)</b>",
    ]
    
    # 按日期倒序显示（最新的在前）
    for date_str in sorted(daily_totals.keys(), reverse=True):
        total = daily_totals[date_str]
        services = daily_services[date_str]
        
        # 日期标题行
        message_parts.append(f"\n<b>📆 {date_str}</b>")
        message_parts.append(f"💵 小计: <code>{total:.4f} {html.escape(currency)}</code>")
        
        # 服务类型对应的 emoji 图标和中文名称
        def get_service_display(service_name: str) -> tuple:
            service_lower = service_name.lower()
            if 'compute' in service_lower or 'instance' in service_lower:
                return ('🖥️', '计算实例')
            elif 'storage' in service_lower or 'block' in service_lower:
                return ('💾', '块存储')
            elif 'object' in service_lower:
                return ('💾', '对象存储')
            elif 'network' in service_lower or 'bandwidth' in service_lower:
                return ('🌐', '网络带宽')
            elif 'load balancer' in service_lower:
                return ('🌐', '负载均衡')
            elif 'database' in service_lower or 'mysql' in service_lower or 'oracle' in service_lower:
                return ('🗄️', '数据库')
            elif 'function' in service_lower or 'serverless' in service_lower:
                return ('⚡', '无服务器')
            elif 'monitoring' in service_lower or 'observability' in service_lower:
                return ('📊', '监控服务')
            elif 'security' in service_lower or 'firewall' in service_lower or 'waf' in service_lower:
                return ('🔒', '安全服务')
            elif 'ai' in service_lower or 'ml' in service_lower or 'machine learning' in service_lower:
                return ('🤖', 'AI/机器学习')
            elif 'container' in service_lower or 'kubernetes' in service_lower:
                return ('📦', '容器服务')
            elif 'api' in service_lower or 'gateway' in service_lower:
                return ('🔌', 'API 网关')
            else:
                # 其他服务使用缩略后的原始名称
                return ('🔹', truncate_text(service_name, 12))
        
        # 服务明细（仅显示前3个主要服务，其余合并）
        services_sorted = sorted(services, key=lambda x: x[1], reverse=True)
        for i, (service, amount) in enumerate(services_sorted[:3]):
            icon, display_name = get_service_display(service)
            message_parts.append(f"  {icon} {html.escape(display_name)}: <code>{amount:.4f}</code>")
        
        if len(services_sorted) > 3:
            other_count = len(services_sorted) - 3
            other_total = sum(s[1] for s in services_sorted[3:])
            message_parts.append(f"  📦 其他 {other_count} 项: <code>{other_total:.4f}</code>")
    
    if not show_all and hidden_days > 0:
        message_parts.append(f"\nℹ️ 已折叠更早的 <b>{hidden_days}</b> 天数据")
    
    return "\n".join(message_parts)


def render_user_info_telegram(user_data: Dict[str, Any]) -> str:
    """为 Telegram 渲染用户信息（移动端友好）。"""
    parts = [
        "<b>👤 用户账号信息</b>",
        "",
    ]
    
    # 基础信息
    username = safe_get_any(user_data, 'user_name', 'userName')
    display_name = safe_get_any(user_data, 'display_name', 'displayName')
    description = safe_get(user_data, 'description')
    user_id = safe_get(user_data, 'id')
    user_ocid = safe_get(user_data, 'ocid', safe_get(user_data, 'id'))
    active = safe_get(user_data, 'active')
    user_type = safe_get_any(user_data, 'user_type', 'userType')
    locale = safe_get(user_data, 'locale')
    timezone = safe_get(user_data, 'timezone')
    
    parts.extend([
        f"🔑 <b>用户名</b>: <code>{html.escape(str(username))}</code>",
        f"📛 <b>显示名</b>: {html.escape(str(display_name))}",
    ])
    
    if str(description) != "N/A":
        parts.append(f"📝 <b>描述/全名</b>: {html.escape(str(description))}")
    
    parts.extend([
        f"🆔 <b>用户 ID</b>: <code>{html.escape(str(user_id)[:20])}...</code>",
        f"✅ <b>状态</b>: {'激活' if active else '停用'}",
    ])
    
    if str(user_type) != "N/A":
        parts.append(f"📄 <b>用户类型</b>: {html.escape(str(user_type))}")
    if str(locale) != "N/A":
        parts.append(f"🌐 <b>Locale</b>: {html.escape(str(locale))}")
    if str(timezone) != "N/A":
        parts.append(f"⏰ <b>时区</b>: {html.escape(str(timezone))}")
    
    parts.append("")
    
    # 联系方式
    emails = safe_get(user_data, "emails", [])
    if emails and emails != "N/A":
        parts.append("<b>📧 邮箱</b>")
        for email in emails[:3]:
            email_val = safe_get(email, 'value')
            is_primary = safe_get(email, 'primary', False)
            primary_tag = " ⭐" if is_primary else ""
            parts.append(f"  • <code>{html.escape(str(email_val))}</code>{primary_tag}")
        parts.append("")
    
    # 权限信息
    groups = safe_get(user_data, "groups", [])
    roles = safe_get(user_data, "roles", [])
    
    if (groups and groups != "N/A") or (roles and roles != "N/A"):
        parts.append("<b>🛡️ 权限信息</b>")
        
        if groups and groups != "N/A":
            parts.append(f"👪 所属组: <b>{len(groups)}</b> 个")
            for i, group in enumerate(groups[:3], 1):
                group_name = safe_get(group, 'display', safe_get(group, 'value'))
                parts.append(f"  {i}. {html.escape(str(group_name))}")
            if len(groups) > 3:
                parts.append(f"  … 还有 {len(groups) - 3} 个组")
        
        if roles and roles != "N/A":
            parts.append(f"🛡️ 角色: <b>{len(roles)}</b> 个")
            for i, role in enumerate(roles[:3], 1):
                role_name = safe_get(role, 'display', safe_get(role, 'value'))
                parts.append(f"  {i}. {html.escape(str(role_name))}")
            if len(roles) > 3:
                parts.append(f"  … 还有 {len(roles) - 3} 个角色")
        
        parts.append("")
    
    # 电话信息
    phones = safe_get_any(user_data, "phone_numbers", "phoneNumbers", default=[])
    if phones and phones != "N/A" and len(phones) > 0:
        parts.append("<b>📱 电话</b>")
        for phone in phones[:3]:
            phone_val = safe_get(phone, 'value')
            phone_type = safe_get(phone, 'type', '')
            is_primary = safe_get(phone, 'primary', False)
            primary_tag = " ⭐" if is_primary else ""
            type_tag = f" ({phone_type})" if str(phone_type) != "N/A" else ""
            parts.append(f"  • <code>{html.escape(str(phone_val))}</code>{type_tag}{primary_tag}")
        parts.append("")
    
    # 安全状态
    user_state = safe_get_any(
        user_data,
        "urn_ietf_params_scim_schemas_oracle_idcs_extension_user_state_user",
        "urn:ietf:params:scim:schemas:oracle:idcs:extension:userState:User",
        default=None,
    )
    password_state = safe_get_any(
        user_data,
        "urn_ietf_params_scim_schemas_oracle_idcs_extension_password_state_user",
        "urn:ietf:params:scim:schemas:oracle:idcs:extension:passwordState:User",
        default=None,
    )
    
    if (user_state and user_state != "N/A") or (password_state and password_state != "N/A"):
        parts.append("<b>🔒 账号安全</b>")
    
    if user_state and user_state != "N/A":
        locked = unwrap_state_value(safe_get(user_state, "locked", None), "on", default="N/A")
        if str(locked) != "N/A":
            lock_status = "🔒 已锁定" if locked else "✅ 未锁定"
            parts.append(f"账号状态: {lock_status}")
        
        # 登录失败次数
        failed_attempts = safe_get_any(user_state, 'failed_login_attempts', 'failedLoginAttempts')
        if str(failed_attempts) != "N/A":
            parts.append(f"登录失败: {failed_attempts} 次")
        
        # 最近成功登录
        last_success = safe_get_any(user_state, 'last_successful_login_date', 'lastSuccessfulLoginDate')
        if str(last_success) != "N/A":
            parts.append(f"最近成功登录: {str(last_success)[:10]}")
    
    if password_state and password_state != "N/A":
        expired = unwrap_state_value(safe_get(password_state, "expired", None), "on", default="N/A")
        if str(expired) != "N/A":
            pwd_status = "⚠️ 已过期" if expired else "✅ 有效"
            parts.append(f"密码状态: {pwd_status}")
        
        # 密码过期时间
        expiry_date = safe_get_any(password_state, 'expiry_date', 'expiryDate')
        if str(expiry_date) != "N/A":
            parts.append(f"密码过期: {str(expiry_date)[:10]}")
        
        # 上次修改密码
        last_set = safe_get_any(password_state, 'last_successful_set_date', 'lastSuccessfulSetDate')
        if str(last_set) != "N/A":
            parts.append(f"上次修改: {str(last_set)[:10]}")
    
    return "\n".join(parts)


def render_policies_telegram(policies_data: list) -> str:
    """为 Telegram 渲染密码策略看板（移动端友好）。"""
    if not policies_data:
        return "<b>🛡️ 密码策略看板</b>\n\n❓ 未发现任何策略"
    
    sorted_policies = sorted(
        policies_data,
        key=lambda x: getattr(x, "priority", 999) if getattr(x, "priority", None) is not None else 999,
    )
    
    parts = [
        "<b>🛡️ 密码策略看板</b>",
        f"策略总数: <b>{len(policies_data)}</b>",
        "",
    ]
    
    for i, policy in enumerate(sorted_policies, 1):
        name = str(getattr(policy, "name", "N/A") or "N/A")
        priority = getattr(policy, "priority", "N/A")
        expires = getattr(policy, "password_expires_after", "N/A")
        
        is_active = (i == 1)  # 优先级最高的正在生效
        status_icon = "🚀" if is_active else "⏳"
        
        if str(expires) == "0":
            expire_text = "♾️ 永不过期"
        else:
            expire_text = f"📅 {expires} 天"
        
        parts.append(f"<b>{status_icon} {i}. {html.escape(name)}</b>")
        parts.append(f"   优先级: <code>{priority}</code> | 过期: {expire_text}")
        if is_active:
            parts.append("   🟢 <i>当前生效</i>")
        parts.append("")
    
    return "\n".join(parts)


def list_policies(app_config: Optional[Dict[str, Any]] = None) -> None:
    """功能 3：查询当前密码策略状态。"""
    print("\n" + "=" * 80)
    print("🛡️ 正在获取身份域密码策略看板...")
    try:
        app_config = app_config or load_app_config()
        config = get_oci_config(app_config)
        domain_name = app_config.get("oci", {}).get("identity_domain_name", "Default")
        id_domains_client = get_identity_domains_client(config, domain_name=domain_name)
        _print_policy_table(id_domains_client)
    except Exception as e:
        print(f"❌ 查询失败: {e}")




# ==========================================
# 审计事件查询功能
# ==========================================
def _fetch_audit_events_rest(
    config: Dict[str, Any],
    domain_url: str,
    limit: int = 20,
    filter_expr: Optional[str] = None,
    sort_by: str = "timestamp",
    sort_order: str = "DESCENDING"
) -> List[Dict[str, Any]]:
    """通过 REST API 获取审计事件。
    
    Returns:
        审计事件列表
    """
    from oci.signer import Signer
    import requests
    
    signer = Signer(
        tenancy=config["tenancy"],
        user=config["user"],
        fingerprint=config["fingerprint"],
        private_key_file_location=config.get("key_file")
    )
    
    params = {
        "count": limit,
        "sortBy": sort_by,
        "sortOrder": sort_order
    }
    if filter_expr:
        params["filter"] = filter_expr
        
    url = f"{domain_url}/admin/v1/AuditEvents"
    headers = {"Content-Type": "application/json"}
    
    response = requests.get(url, auth=signer, headers=headers, params=params, timeout=(5, 60))
    response.raise_for_status()
    data = response.json()
    
    return data.get("Resources", [])


def list_audit_events(
    app_config: Optional[Dict[str, Any]] = None,
    limit: int = 20,
    filter_expr: Optional[str] = None,
    sort_by: str = "timestamp",
    sort_order: str = "DESCENDING"
) -> None:
    """查询 OCI Identity Domain 审计事件。
    
    Args:
        app_config: 应用配置
        limit: 返回结果数量限制（默认 20）
        filter_expr: SCIM 过滤表达式，例如: 'eventType eq "user.login"'
        sort_by: 排序字段（默认 timestamp）
        sort_order: 排序方向 ASCENDING 或 DESCENDING（默认 DESCENDING）
    """
    print("\n" + "=" * 80)
    print("📋 正在获取审计事件...")
    try:
        app_config = app_config or load_app_config()
        config = get_oci_config(app_config)
        domain_name = app_config.get("oci", {}).get("identity_domain_name", "Default")
        
        # 获取 Identity Domain URL
        identity_client = oci.identity.IdentityClient(config)
        response = identity_client.list_domains(config["tenancy"])
        domains = response.data
        target_domain = next((d for d in domains if d.display_name == domain_name), None)
        if not target_domain:
            raise ValueError(f"未找到名为 {domain_name} 的 Identity Domain")
        domain_url = target_domain.url.replace(":443", "")
        
        # 调用 REST API
        resources = _fetch_audit_events_rest(config, domain_url, limit, filter_expr, sort_by, sort_order)
        
        if not resources:
            print("📭 未找到审计事件")
            return
            
        _print_audit_events_table(resources)
        
    except Exception as e:
        LOGGER.exception("查询审计事件失败")
        print(f"❌ 查询失败: {e}")


def _print_audit_events_table(events: List[Any]) -> None:
    """打印审计事件表格（CLI 格式）。"""
    if not events:
        print("📭 (无审计事件)")
        return
        
    print(f"\n📋 共找到 {len(events)} 条审计事件\n")
    print_divider("-", 120)
    
    # 表头
    header_format = "{:<20} {:<25} {:<20} {:<15} {:<40}"
    print(header_format.format("时间", "事件类型", "用户", "来源IP", "目标资源"))
    print_divider("-", 120)
    
    for event in events:
        timestamp = safe_get_any(event, "timestamp", default="")
        # 转换 ISO 8601 时间为可读格式
        if timestamp:
            try:
                dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                timestamp = dt.strftime("%Y-%m-%d %H:%M:%S")
            except:
                pass
                
        # Identity Domains 使用 message 字段
        event_message = safe_get_any(event, "message", default="N/A")
        
        # 获取用户信息（actorDisplayName 或 actorName）
        user_name = (safe_get_any(event, "actorDisplayName") or 
                    safe_get_any(event, "actorName") or "N/A")
            
        # 获取来源 IP（clientIp）
        source_ip = safe_get_any(event, "clientIp", default="N/A")
        
        # 获取目标资源（如果有）
        service_name = safe_get_any(event, "serviceName", default="")
        event_id = safe_get_any(event, "eventId", default="")
        target_name = service_name or event_id or "N/A"
            
        # 截断过长字段
        user_name = truncate_text(user_name, 20)
        event_message = truncate_text(event_message, 25)
        target_name = truncate_text(target_name, 40)
        
        print(header_format.format(timestamp, event_message, user_name, source_ip, target_name))
    
    print_divider("-", 120)


def render_audit_events_telegram(events: List[Any], limit: int = 10) -> str:
    """渲染审计事件为 Telegram 格式。
    
    Args:
        events: 审计事件列表
        limit: 显示数量限制
    """
    if not events:
        return "📭 <b>未找到审计事件</b>"
    
    # 审计事件渲染（字段映射已验证）
    
    parts = [
        f"<b>📋 审计事件 (最近 {min(len(events), limit)} 条)</b>\n",
        "━━━━━━━━━━━━━━━━━━━━━━"
    ]
    
    for i, event in enumerate(events[:limit], 1):
        # 使用实际 API 返回的字段名
        timestamp = safe_get_any(event, "timestamp", default="")
        if timestamp:
            try:
                dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                timestamp = dt.strftime("%m-%d %H:%M:%S")
            except:
                pass
        else:
            timestamp = "N/A"
        
        # Identity Domains 使用 message 字段存储事件描述
        event_message = safe_get_any(event, "message", default="N/A")
        
        # 事件类型图标（基于 message 字段内容）
        icon = "🔐"
        if "login" in str(event_message).lower() or "sign in" in str(event_message).lower():
            icon = "🔑"
        elif "logout" in str(event_message).lower() or "sign out" in str(event_message).lower():
            icon = "🚪"
        elif "create" in str(event_message).lower():
            icon = "➕"
        elif "update" in str(event_message).lower() or "modify" in str(event_message).lower():
            icon = "✏️"
        elif "delete" in str(event_message).lower() or "remove" in str(event_message).lower():
            icon = "🗑️"
        elif "password" in str(event_message).lower():
            icon = "🔒"
        
        # 获取用户信息（actorName 或 actorDisplayName）
        user_name = (safe_get_any(event, "actorDisplayName") or 
                    safe_get_any(event, "actorName") or "系统")
            
        # 获取源 IP（clientIp 字段）
        source_ip = safe_get_any(event, "clientIp", default="N/A")
        
        parts.append(f"\n{icon} <b>{html.escape(str(event_message)[:80])}</b>")
        parts.append(f"   👤 用户: <code>{html.escape(user_name)}</code>")
        parts.append(f"   🌐 IP: <code>{source_ip}</code>")
        parts.append(f"   🕒 时间: {timestamp}")
    
    parts.append("\n━━━━━━━━━━━━━━━━━━━━━━")
    
    if len(events) > limit:
        parts.append(f"\n<i>... 还有 {len(events) - limit} 条事件未显示</i>")
    
    return "\n".join(parts)


# ==========================================
# 计算实例网络安全查询功能
# ==========================================
def _get_compute_client(config: Dict[str, Any]):
    return oci.core.ComputeClient(config)


def _get_virtual_network_client(config: Dict[str, Any]):
    return oci.core.VirtualNetworkClient(config)


def _fetch_instance_network_topology(config: Dict[str, Any], instance_id: str) -> Dict[str, Any]:
    compute_client = _get_compute_client(config)
    vcn_client = _get_virtual_network_client(config)

    instance = compute_client.get_instance(instance_id).data
    attachments = oci.pagination.list_call_get_all_results(
        compute_client.list_vnic_attachments,
        compartment_id=instance.compartment_id,
        instance_id=instance_id,
    ).data

    vnic_entries: List[Dict[str, Any]] = []
    subnet_cache: Dict[str, Any] = {}
    sl_cache: Dict[str, Any] = {}
    nsg_cache: Dict[str, Any] = {}

    for attachment in attachments:
        vnic = vcn_client.get_vnic(attachment.vnic_id).data
        subnet = subnet_cache.get(vnic.subnet_id)
        if subnet is None:
            subnet = vcn_client.get_subnet(vnic.subnet_id).data
            subnet_cache[vnic.subnet_id] = subnet

        nsgs: List[Any] = []
        for nsg_id in getattr(vnic, "nsg_ids", []) or []:
            nsg = nsg_cache.get(nsg_id)
            if nsg is None:
                nsg = vcn_client.get_network_security_group(nsg_id).data
                nsg_cache[nsg_id] = nsg
            nsgs.append(nsg)

        security_lists: List[Any] = []
        for sl_id in getattr(subnet, "security_list_ids", []) or []:
            sl = sl_cache.get(sl_id)
            if sl is None:
                sl = vcn_client.get_security_list(sl_id).data
                sl_cache[sl_id] = sl
            security_lists.append(sl)

        vnic_entries.append({
            "attachment": attachment,
            "vnic": vnic,
            "subnet": subnet,
            "nsgs": nsgs,
            "security_lists": security_lists,
        })

    return {
        "instance": instance,
        "vnics": vnic_entries,
    }


def _fetch_nsg_rules(config: Dict[str, Any], nsg_id: str) -> Tuple[Any, List[Any]]:
    vcn_client = _get_virtual_network_client(config)
    nsg = vcn_client.get_network_security_group(nsg_id).data
    rules_resp = oci.pagination.list_call_get_all_results(
        vcn_client.list_network_security_group_security_rules,
        network_security_group_id=nsg_id,
    )
    rules = _normalize_collection_items(getattr(rules_resp, "data", None))
    return nsg, rules


def _fetch_security_list(config: Dict[str, Any], security_list_id: str) -> Any:
    vcn_client = _get_virtual_network_client(config)
    return vcn_client.get_security_list(security_list_id).data


def _rule_signature(rule: Any, direction: str = "ingress") -> Dict[str, Any]:
    base: Dict[str, Any] = {
        "direction": direction,
        "protocol": safe_get(rule, "protocol", default=None),
        "is_stateless": safe_get(rule, "is_stateless", default=False),
        "description": safe_get(rule, "description", default=None),
    }
    if direction == "ingress":
        base["peer"] = safe_get(rule, "source", default=None)
        base["peer_type"] = safe_get(rule, "source_type", default="CIDR_BLOCK")
    else:
        base["peer"] = safe_get(rule, "destination", default=None)
        base["peer_type"] = safe_get(rule, "destination_type", default="CIDR_BLOCK")

    tcp_options = safe_get(rule, "tcp_options", default=None)
    udp_options = safe_get(rule, "udp_options", default=None)
    icmp_options = safe_get(rule, "icmp_options", default=None)

    if tcp_options is not None and not isinstance(tcp_options, str):
        dest = safe_get(tcp_options, "destination_port_range", default=None)
        src = safe_get(tcp_options, "source_port_range", default=None)
        base["tcp_destination_port_range"] = {
            "min": safe_get(dest, "min", default=None),
            "max": safe_get(dest, "max", default=None),
        } if dest not in (None, "N/A") else None
        base["tcp_source_port_range"] = {
            "min": safe_get(src, "min", default=None),
            "max": safe_get(src, "max", default=None),
        } if src not in (None, "N/A") else None
    if udp_options is not None and not isinstance(udp_options, str):
        dest = safe_get(udp_options, "destination_port_range", default=None)
        src = safe_get(udp_options, "source_port_range", default=None)
        base["udp_destination_port_range"] = {
            "min": safe_get(dest, "min", default=None),
            "max": safe_get(dest, "max", default=None),
        } if dest not in (None, "N/A") else None
        base["udp_source_port_range"] = {
            "min": safe_get(src, "min", default=None),
            "max": safe_get(src, "max", default=None),
        } if src not in (None, "N/A") else None
    if icmp_options is not None and not isinstance(icmp_options, str):
        base["icmp_options"] = {
            "type": safe_get(icmp_options, "type", default=None),
            "code": safe_get(icmp_options, "code", default=None),
        }
    return base


def _make_port_range(min_port: Optional[int], max_port: Optional[int]):
    if min_port is None and max_port is None:
        return None
    if max_port is None:
        max_port = min_port
    return oci.core.models.PortRange(min=min_port, max=max_port)


def _build_ingress_rule_model(
    protocol: str,
    source: str,
    source_type: str = "CIDR_BLOCK",
    port_min: Optional[int] = None,
    port_max: Optional[int] = None,
    stateless: bool = False,
    description: Optional[str] = None,
) -> Any:
    kwargs: Dict[str, Any] = {
        "protocol": str(protocol),
        "source": source,
        "source_type": source_type,
        "is_stateless": stateless,
        "description": description,
    }
    if str(protocol) == "6":
        kwargs["tcp_options"] = oci.core.models.TcpOptions(
            destination_port_range=_make_port_range(port_min, port_max)
        )
    elif str(protocol) == "17":
        kwargs["udp_options"] = oci.core.models.UdpOptions(
            destination_port_range=_make_port_range(port_min, port_max)
        )
    return oci.core.models.IngressSecurityRule(**kwargs)


def export_security_list_rules(
    app_config: Optional[Dict[str, Any]] = None,
    security_list_id: Optional[str] = None,
    output_path: Optional[str] = None,
) -> str:
    if not security_list_id:
        raise ValueError("缺少 security_list_id")
    app_config = app_config or load_app_config()
    config = get_oci_config(app_config)
    security_list = _fetch_security_list(config, security_list_id)
    payload = {
        "security_list": oci.util.to_dict(security_list),
        "exported_at": datetime.now(timezone.utc).isoformat(),
    }
    target = output_path or os.path.join(
        BASE_DIR,
        "backups",
        f"security_list_{security_list_id.split('.')[-1]}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
    )
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return target


def _update_security_list_rules(config: Dict[str, Any], security_list: Any, ingress_rules: List[Any], egress_rules: List[Any]) -> Any:
    vcn_client = _get_virtual_network_client(config)
    details = oci.core.models.UpdateSecurityListDetails(
        display_name=safe_get(security_list, "display_name"),
        ingress_security_rules=ingress_rules,
        egress_security_rules=egress_rules,
        freeform_tags=safe_get(security_list, "freeform_tags", default={}),
        defined_tags=safe_get(security_list, "defined_tags", default={}),
    )
    return vcn_client.update_security_list(security_list.id, details, if_match=getattr(security_list, 'etag', None))


def add_security_list_ingress_rule(
    app_config: Optional[Dict[str, Any]] = None,
    security_list_id: Optional[str] = None,
    source: Optional[str] = None,
    protocol: str = "6",
    port_min: Optional[int] = None,
    port_max: Optional[int] = None,
    description: Optional[str] = None,
    stateless: bool = False,
    apply: bool = False,
) -> None:
    print("\n" + "=" * 80)
    print("➕ 准备添加 Security List Ingress 规则...")
    if not security_list_id or not source:
        print("❌ 缺少 security_list_id 或 source")
        return
    try:
        app_config = app_config or load_app_config()
        config = get_oci_config(app_config)
        backup_path = export_security_list_rules(app_config, security_list_id)
        security_list = _fetch_security_list(config, security_list_id)
        ingress_rules = list(getattr(security_list, "ingress_security_rules", []) or [])
        egress_rules = list(getattr(security_list, "egress_security_rules", []) or [])
        new_rule = _build_ingress_rule_model(protocol, source, port_min=port_min, port_max=port_max, description=description, stateless=stateless)
        ingress_rules.append(new_rule)
        print(f"✅ 已生成备份: {backup_path}")
        print(f"预览新增规则: {_format_rule_target(new_rule)}")
        print(f"变更后 Ingress 条数: {len(ingress_rules)}")
        if not apply:
            print("ℹ️ 当前为预览模式，未实际提交。追加 --apply 才会落库。")
            return
        res = _update_security_list_rules(config, security_list, ingress_rules, egress_rules)
        print(f"✅ 已提交更新，HTTP {getattr(res, 'status', 'N/A')}")
    except Exception as e:
        LOGGER.exception("添加 Security List Ingress 规则失败")
        print(f"❌ 操作失败: {e}")


def remove_security_list_ingress_rule(
    app_config: Optional[Dict[str, Any]] = None,
    security_list_id: Optional[str] = None,
    rule_index: Optional[int] = None,
    apply: bool = False,
) -> None:
    print("\n" + "=" * 80)
    print("➖ 准备删除 Security List Ingress 规则...")
    if not security_list_id or rule_index is None:
        print("❌ 缺少 security_list_id 或 rule_index")
        return
    try:
        app_config = app_config or load_app_config()
        config = get_oci_config(app_config)
        backup_path = export_security_list_rules(app_config, security_list_id)
        security_list = _fetch_security_list(config, security_list_id)
        ingress_rules = list(getattr(security_list, "ingress_security_rules", []) or [])
        egress_rules = list(getattr(security_list, "egress_security_rules", []) or [])
        if rule_index < 1 or rule_index > len(ingress_rules):
            print(f"❌ rule_index 超出范围。当前 Ingress 条数: {len(ingress_rules)}")
            return
        removed = ingress_rules.pop(rule_index - 1)
        print(f"✅ 已生成备份: {backup_path}")
        print(f"预览删除规则: {_format_rule_target(removed)}")
        print(f"变更后 Ingress 条数: {len(ingress_rules)}")
        if not apply:
            print("ℹ️ 当前为预览模式，未实际提交。追加 --apply 才会落库。")
            return
        res = _update_security_list_rules(config, security_list, ingress_rules, egress_rules)
        print(f"✅ 已提交更新，HTTP {getattr(res, 'status', 'N/A')}")
    except Exception as e:
        LOGGER.exception("删除 Security List Ingress 规则失败")
        print(f"❌ 操作失败: {e}")


def _format_rule_target(rule: Any) -> str:
    protocol_name = _protocol_name(safe_get(rule, "protocol"))
    source = safe_get_any(rule, "source", "destination", default="N/A")
    port_text = _extract_rule_port_text(rule)
    desc = safe_get(rule, "description", default="")
    stateless = safe_get(rule, "is_stateless", default=False)
    return f"{protocol_name} {port_text}, peer={source}, stateless={stateless}, desc={desc or '-'}"


def _print_instance_network_topology(topology: Dict[str, Any]) -> None:
    instance = topology["instance"]
    entries = topology["vnics"]

    print_section("实例网络安全总览", "🧱")
    print_kv("实例名称", safe_get(instance, "display_name"))
    print_kv("实例 OCID", safe_get(instance, "id"))
    print_kv("状态", safe_get(instance, "lifecycle_state"))
    print_kv("Compartment OCID", safe_get(instance, "compartment_id"))
    print_kv("VNIC 数量", len(entries))

    for index, entry in enumerate(entries, 1):
        vnic = entry["vnic"]
        subnet = entry["subnet"]
        nsgs = entry["nsgs"]
        security_lists = entry["security_lists"]
        print_section(f"VNIC #{index}", "🌐")
        print_kv("VNIC 名称", safe_get(vnic, "display_name"))
        print_kv("VNIC OCID", safe_get(vnic, "id"))
        print_kv("Private IP", safe_get(vnic, "private_ip"))
        print_kv("Public IP", safe_get(vnic, "public_ip", default="(无)"))
        print_kv("Subnet OCID", safe_get(subnet, "id"))
        print_kv("Subnet 名称", safe_get(subnet, "display_name"))
        print_kv("VCN OCID", safe_get(subnet, "vcn_id"))
        print_kv("NSG 数量", len(nsgs))
        for nsg in nsgs:
            print(f"  - NSG: {safe_get(nsg, 'display_name')} | {safe_get(nsg, 'id')}")
        print_kv("Security List 数量", len(security_lists))
        for sl in security_lists:
            print(f"  - Security List: {safe_get(sl, 'display_name')} | {safe_get(sl, 'id')}")


def _print_nsg_rules(nsg: Any, rules: List[Any]) -> None:
    print_section("NSG 规则", "🛡️")
    print_kv("NSG 名称", safe_get(nsg, "display_name"))
    print_kv("NSG OCID", safe_get(nsg, "id"))
    print_kv("规则数", len(rules))
    if not rules:
        print("📭 (无 NSG 规则)")
        return
    for idx, rule in enumerate(rules, 1):
        print(f"{idx:>2}. {safe_get(rule, 'direction')} | {_format_rule_target(rule)}")


def _print_security_list_rules(security_list: Any) -> None:
    ingress = getattr(security_list, "ingress_security_rules", []) or []
    egress = getattr(security_list, "egress_security_rules", []) or []
    print_section("Security List 规则", "📋")
    print_kv("名称", safe_get(security_list, "display_name"))
    print_kv("OCID", safe_get(security_list, "id"))
    print_kv("Ingress 条数", len(ingress))
    for idx, rule in enumerate(ingress, 1):
        print(f"  Ingress {idx:>2}: {_format_rule_target(rule)}")
    print_kv("Egress 条数", len(egress))
    for idx, rule in enumerate(egress, 1):
        print(f"  Egress  {idx:>2}: {_format_rule_target(rule)}")


def render_instance_network_telegram(topology: Dict[str, Any]) -> str:
    instance = topology["instance"]
    entries = topology["vnics"]
    parts = [
        "<b>🧱 实例网络安全总览</b>",
        f"实例: <b>{html.escape(str(safe_get(instance, 'display_name')))}</b>",
        f"状态: <code>{html.escape(str(safe_get(instance, 'lifecycle_state')))}</code>",
        f"实例 OCID: <code>{html.escape(str(safe_get(instance, 'id')))}</code>",
        f"VNIC 数量: <code>{len(entries)}</code>",
        "━━━━━━━━━━━━━━━━━━━━━━",
    ]
    for idx, entry in enumerate(entries, 1):
        vnic = entry["vnic"]
        subnet = entry["subnet"]
        nsgs = entry["nsgs"]
        security_lists = entry["security_lists"]
        parts.append(f"\n🌐 <b>VNIC #{idx}: {html.escape(str(safe_get(vnic, 'display_name')))}</b>")
        parts.append(f"   🔒 Private IP: <code>{html.escape(str(safe_get(vnic, 'private_ip')))}</code>")
        parts.append(f"   🌍 Public IP: <code>{html.escape(str(safe_get(vnic, 'public_ip', default='(无)')))}</code>")
        parts.append(f"   📦 Subnet: <code>{html.escape(str(safe_get(subnet, 'display_name')))}</code>")
        if nsgs:
            for nsg in nsgs:
                parts.append(f"   🛡️ NSG: <code>{html.escape(str(safe_get(nsg, 'display_name')))}</code>")
        else:
            parts.append("   🛡️ NSG: <i>(无)</i>")
        if security_lists:
            for sl in security_lists:
                parts.append(f"   📋 SL: <code>{html.escape(str(safe_get(sl, 'display_name')))}</code>")
        else:
            parts.append("   📋 SL: <i>(无)</i>")
    return "\n".join(parts)


def render_nsg_rules_telegram(nsg: Any, rules: List[Any]) -> str:
    parts = [
        "<b>🛡️ NSG 规则</b>",
        f"名称: <b>{html.escape(str(safe_get(nsg, 'display_name')))}</b>",
        f"OCID: <code>{html.escape(str(safe_get(nsg, 'id')))}</code>",
        f"规则数: <code>{len(rules)}</code>",
        "━━━━━━━━━━━━━━━━━━━━━━",
    ]
    if not rules:
        parts.append("📭 <i>无 NSG 规则</i>")
        return "\n".join(parts)
    for idx, rule in enumerate(rules, 1):
        parts.append(f"\n{idx}. <b>{html.escape(str(safe_get(rule, 'direction')))}</b>")
        parts.append(f"   <code>{html.escape(_format_rule_target(rule))}</code>")
    return "\n".join(parts)


def render_security_list_rules_telegram(security_list: Any) -> str:
    ingress = getattr(security_list, "ingress_security_rules", []) or []
    egress = getattr(security_list, "egress_security_rules", []) or []
    parts = [
        "<b>📋 Security List 规则</b>",
        f"名称: <b>{html.escape(str(safe_get(security_list, 'display_name')))}</b>",
        f"OCID: <code>{html.escape(str(safe_get(security_list, 'id')))}</code>",
        f"Ingress: <code>{len(ingress)}</code> | Egress: <code>{len(egress)}</code>",
        "━━━━━━━━━━━━━━━━━━━━━━",
    ]
    if ingress:
        parts.append("\n<b>Ingress</b>")
        for idx, rule in enumerate(ingress, 1):
            parts.append(f"{idx}. <code>{html.escape(_format_rule_target(rule))}</code>")
    if egress:
        parts.append("\n<b>Egress</b>")
        for idx, rule in enumerate(egress, 1):
            parts.append(f"{idx}. <code>{html.escape(_format_rule_target(rule))}</code>")
    if not ingress and not egress:
        parts.append("📭 <i>无 Security List 规则</i>")
    return "\n".join(parts)


def show_instance_network(app_config: Optional[Dict[str, Any]] = None, instance_id: Optional[str] = None) -> None:
    print("\n" + "=" * 80)
    print("🧱 正在获取实例网络安全总览...")
    if not instance_id:
        print("❌ 缺少 instance_id")
        return
    try:
        app_config = app_config or load_app_config()
        config = get_oci_config(app_config)
        topology = _fetch_instance_network_topology(config, instance_id)
        _print_instance_network_topology(topology)
    except Exception as e:
        LOGGER.exception("查询实例网络安全总览失败")
        print(f"❌ 查询失败: {e}")


def show_nsg_rules(app_config: Optional[Dict[str, Any]] = None, nsg_id: Optional[str] = None) -> None:
    print("\n" + "=" * 80)
    print("🛡️ 正在获取 NSG 规则...")
    if not nsg_id:
        print("❌ 缺少 nsg_id")
        return
    try:
        app_config = app_config or load_app_config()
        config = get_oci_config(app_config)
        nsg, rules = _fetch_nsg_rules(config, nsg_id)
        _print_nsg_rules(nsg, rules)
    except Exception as e:
        LOGGER.exception("查询 NSG 规则失败")
        print(f"❌ 查询失败: {e}")


def show_security_list_rules(app_config: Optional[Dict[str, Any]] = None, security_list_id: Optional[str] = None) -> None:
    print("\n" + "=" * 80)
    print("📋 正在获取 Security List 规则...")
    if not security_list_id:
        print("❌ 缺少 security_list_id")
        return
    try:
        app_config = app_config or load_app_config()
        config = get_oci_config(app_config)
        security_list = _fetch_security_list(config, security_list_id)
        _print_security_list_rules(security_list)
    except Exception as e:
        LOGGER.exception("查询 Security List 规则失败")
        print(f"❌ 查询失败: {e}")


def create_safe_policy(app_config: Optional[Dict[str, Any]] = None, auto_approve: bool = False) -> None:
    """功能 4：创建永不过期安全策略。"""
    print("\n" + "=" * 80)
    app_config = app_config or load_app_config()
    policy_cfg = get_policy_runtime_config(app_config)

    if not auto_approve:
        confirm = input(
            "⚠️ 即将基于官方标准规则克隆一个【永不过期】的最高优先级策略。\n"
            f"👉 确定要继续创建策略 '{policy_cfg['new_policy_name']}' 吗？(y/n): "
        ).strip().lower()
        if confirm != "y":
            print("🛑 已取消创建操作。")
            return

    print("🔒 正在分析现有策略并同步 Standard 规则...")
    try:
        config = get_oci_config(app_config)
        id_domains_client = get_identity_domains_client(config, domain_name=policy_cfg["domain_name"])
        from oci.identity_domains import models

        response = id_domains_client.list_password_policies()
        resources = getattr(response.data, "resources", [])
        std_policy = next(
            (p for p in resources if getattr(p, "name", "") == policy_cfg["source_policy_name"]),
            None,
        )

        if not std_policy:
            print(f"❌ 未能定位到 {policy_cfg['source_policy_name']}，无法进行安全同步。")
            return

        new_policy_details = {
            "name": policy_cfg["new_policy_name"],
            "description": policy_cfg["description"],
            "schemas": ["urn:ietf:params:scim:schemas:oracle:idcs:PasswordPolicy"],
            "priority": policy_cfg["priority"],
            "password_expires_after": policy_cfg["password_expires_after"],
            "min_length": getattr(std_policy, "min_length", 8),
            "max_length": getattr(std_policy, "max_length", 40),
            "min_lower_case": getattr(std_policy, "min_lower_case", 1),
            "min_upper_case": getattr(std_policy, "min_upper_case", 1),
            "min_numerals": getattr(std_policy, "min_numerals", 1),
            "min_special_chars": getattr(std_policy, "min_special_chars", 0),
            "max_incorrect_attempts": getattr(std_policy, "max_incorrect_attempts", 5),
            "lockout_duration": getattr(std_policy, "lockout_duration", 30),
            "num_passwords_in_history": getattr(std_policy, "num_passwords_in_history", 1),
            "user_name_disallowed": getattr(std_policy, "user_name_disallowed", True),
            "first_name_disallowed": getattr(std_policy, "first_name_disallowed", True),
            "last_name_disallowed": getattr(std_policy, "last_name_disallowed", True),
        }

        new_policy_obj = models.PasswordPolicy(**new_policy_details)
        print(f"--- 正在推送新策略: {policy_cfg['new_policy_name']} ---")
        res = id_domains_client.create_password_policy(password_policy=new_policy_obj)

        if res.status == 201:
            print(f"✅ 成功！已创建『{policy_cfg['new_policy_name']}』。")
            print("\n🔍 最新的策略列表如下，请确认新策略是否已生效：")
            _print_policy_table(id_domains_client)
        else:
            print(f"⚠️ 状态异常: {res.status}")
    except Exception as e:
        if "already exists" in str(e).lower():
            print("💡 提醒：策略已存在，系统保持当前设置。")
        else:
            print(f"❌ 同步失败: {e}")


def delete_policy(
    app_config: Optional[Dict[str, Any]] = None,
    target_name: Optional[str] = None,
    auto_approve: bool = False,
) -> None:
    """功能 5：删除指定密码策略。"""
    print("\n" + "=" * 80)
    print("🗑️ 准备删除策略，正在拉取当前策略列表...")
    current_target_name = target_name or ""

    try:
        app_config = app_config or load_app_config()
        config = get_oci_config(app_config)
        domain_name = app_config.get("oci", {}).get("identity_domain_name", "Default")
        id_domains_client = get_identity_domains_client(config, domain_name=domain_name)

        has_policies = _print_policy_table(id_domains_client)
        if not has_policies:
            return

        if not current_target_name:
            current_target_name = input("\n👉 请输入表格中要删除的【策略名称】(直接回车可取消操作): ").strip()

        if not current_target_name:
            print("🛑 已取消操作。")
            return

        if not auto_approve:
            confirm = input(f"⚠️ 警告: 确定要永久删除策略 '{current_target_name}' 吗？(y/n): ").strip().lower()
            if confirm != "y":
                print("🛑 已取消删除操作。")
                return

        print(f"--- 正在执行删除: {current_target_name} ---")
        response = id_domains_client.list_password_policies()
        resources = getattr(response.data, "resources", [])
        target_policy = next(
            (p for p in resources if getattr(p, "name", "") == current_target_name),
            None,
        )

        if not target_policy:
            print(f"⚠️ 未找到名为 '{current_target_name}' 的策略，请检查拼写大小写是否正确。")
            return

        res = id_domains_client.delete_password_policy(password_policy_id=target_policy.id)
        if res.status == 204:
            print(f"✅ 成功删除策略: {current_target_name}")
            print("\n🔍 删除后的最新策略列表如下：")
            _print_policy_table(id_domains_client)
        else:
            print(f"⚠️ 删除返回状态码: {res.status}")
    except Exception as e:
        if "checkProtectedResource" in str(e):
            print(f"❌ 删除失败：'{current_target_name}' 是系统预设的保护资源，官方禁止删除。")
        else:
            print(f"❌ 操作出错: {e}")


# ==========================================
# 4. Telegram Bot 集成
# ==========================================
class TelegramBotRunner:
    def __init__(self, app_config: Dict[str, Any]):
        self.app_config = app_config
        self.telegram_config = app_config.get("telegram", {})
        self.enabled = self.telegram_config.get("enabled", False)
        self.bot_token = os.environ.get("OCI_MASTER_BOT_TOKEN") or self.telegram_config.get("bot_token", "")
        self.allowed_chat_ids = {str(item) for item in self.telegram_config.get("allowed_chat_ids", [])}
        self.allowed_user_ids = {str(item) for item in self.telegram_config.get("allowed_user_ids", [])}
        self.poll_interval = int(self.telegram_config.get("poll_interval_seconds", 3))
        self.api_base = f"https://api.telegram.org/bot{self.bot_token}" if self.bot_token else ""
        self.last_update_id = int(self.telegram_config.get("initial_update_offset", 0))
        self.session = create_requests_session()

    def validate(self) -> None:
        if not self.enabled:
            raise ValueError("Telegram Bot 未启用，请在配置文件中将 telegram.enabled 设为 true")
        if not self.bot_token:
            raise ValueError("Telegram Bot 缺少 bot_token 配置")

    def _request(self, method: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        response = self.session.post(f"{self.api_base}/{method}", json=payload or {}, timeout=(5, 60))
        try:
            response.raise_for_status()
        except requests.HTTPError as e:
            LOGGER.error(f"Telegram API HTTP 错误: {e}")
            LOGGER.error(f"Response: {response.text[:500]}")
            raise
        data = response.json()
        if not data.get("ok"):
            LOGGER.error(f"Telegram API 返回错误: {data}")
            raise ValueError(f"Telegram API 调用失败: {data}")
        return data

    def get_updates(self) -> List[Dict[str, Any]]:
        payload = {
            "offset": self.last_update_id + 1,
            "timeout": 30,
            "allowed_updates": ["message", "callback_query"],
        }
        data = self._request("getUpdates", payload)
        return data.get("result", [])

    def send_message(
        self,
        chat_id: str,
        text: str,
        parse_mode: Optional[str] = None,
        reply_markup: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        max_len = TELEGRAM_MAX_MESSAGE_LENGTH
        chunks = [text[i:i + max_len] for i in range(0, len(text), max_len)] or ["(空响应)"]
        last_response: Dict[str, Any] = {}
        for chunk in chunks:
            payload: Dict[str, Any] = {
                "chat_id": chat_id,
                "text": chunk,
            }
            if parse_mode:
                payload["parse_mode"] = parse_mode
            if reply_markup and len(chunks) == 1:
                payload["reply_markup"] = reply_markup
            last_response = self._request(
                "sendMessage",
                payload,
            )
        return last_response

    def edit_message_text(
        self,
        chat_id: str,
        message_id: int,
        text: str,
        parse_mode: Optional[str] = None,
        reply_markup: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
        }
        if parse_mode:
            payload["parse_mode"] = parse_mode
        if reply_markup:
            payload["reply_markup"] = reply_markup
        return self._request("editMessageText", payload)

    def answer_callback_query(self, callback_query_id: str, text: Optional[str] = None) -> None:
        payload: Dict[str, Any] = {"callback_query_id": callback_query_id}
        if text:
            payload["text"] = text
        self._request("answerCallbackQuery", payload)

    def build_bot_commands(self) -> List[Dict[str, str]]:
        return [
            {"command": "start", "description": "查看欢迎信息"},
            {"command": "help", "description": "查看帮助菜单"},
            {"command": "menu", "description": "查看帮助菜单"},
            {"command": "user_info", "description": "查看当前用户详细信息"},
            {"command": "usage_fee", "description": "查询本月费用账单"},
            {"command": "policies", "description": "查询密码策略看板"},
            {"command": "audit_events", "description": "查询审计事件日志"},
            {"command": "instance_network", "description": "查询实例网络安全总览"},
            {"command": "nsg_rules", "description": "查询 NSG 规则"},
            {"command": "sl_rules", "description": "查询 Security List 规则"},
            {"command": "create_safe_policy", "description": "创建永不过期安全策略"},
            {"command": "delete_policy", "description": "删除指定密码策略"},
        ]

    def refresh_bot_commands(self) -> None:
        self._request(
            "setMyCommands",
            {
                "commands": self.build_bot_commands(),
            },
        )

    def is_authorized(self, message: Dict[str, Any]) -> bool:
        chat_id = str(safe_get(safe_get(message, "chat", {}), "id", ""))
        user_id = str(safe_get(safe_get(message, "from", {}), "id", ""))

        # 只要配置了白名单，就必须匹配
        if self.allowed_chat_ids and chat_id not in self.allowed_chat_ids:
            LOGGER.warning(f"Unauthorized chat_id: {chat_id}")
            return False
        if self.allowed_user_ids and user_id not in self.allowed_user_ids:
            LOGGER.warning(f"Unauthorized user_id: {user_id}")
            return False
        return True

    def build_help_text(self) -> str:
        return (
            "<b>🤖 OCI Master Bot 命令菜单</b>\n\n"
            "<b>📊 查询命令</b>\n"
            "👤 /user_info - 查看用户账号信息\n"
            "💰 /usage_fee - 本月费用账单\n"
            "🛡️ /policies - 密码策略看板\n"
            "📋 /audit_events - 审计事件日志\n"
            "🧱 /instance_network &lt;instance_ocid&gt; - 实例网络安全总览\n"
            "🛡️ /nsg_rules &lt;nsg_ocid&gt; - NSG 规则\n"
            "📋 /sl_rules &lt;security_list_ocid&gt; - Security List 规则\n\n"
            "<b>⚙️ 管理命令</b>\n"
            "🔒 /create_safe_policy - 创建永不过期策略\n"
            "🗑️ /delete_policy &lt;名称&gt; - 删除指定策略\n\n"
            "<b>❓ 帮助</b>\n"
            "👋 /start - 欢迎信息\n"
            "💬 /help - 显示此帮助"
        )

    def build_usage_fee_keyboard(self, show_all: bool, unique_dates_count: int, display_days: int) -> Optional[Dict[str, Any]]:
        if unique_dates_count <= display_days:
            return None
        if show_all:
            return build_inline_keyboard([[{"text": "收起历史数据", "callback_data": "usage_fee:collapse"}]])
        return build_inline_keyboard([[{"text": "展开全部历史数据", "callback_data": "usage_fee:expand"}]])

    def handle_command(self, text: str) -> str:
        normalized = (text or "").strip()
        if not normalized:
            return "未收到命令内容。"

        if normalized.startswith("/start"):
            return "欢迎使用 OCI Master Telegram Bot。\n" + self.build_help_text()
        if normalized.startswith("/help") or normalized.startswith("/menu"):
            return self.build_help_text()
        if normalized.startswith("/user_info"):
            try:
                app_config = self.app_config or load_app_config()
                config = get_oci_config(app_config)
                identity_client = oci.identity.IdentityClient(config)
                basic_response = identity_client.get_user(config["user"])
                if not basic_response or not getattr(basic_response, "data", None):
                    return "❌ 未能获取用户信息"
                current_user_ocid = safe_get(basic_response.data, "id")
                domain_name = app_config.get("oci", {}).get("identity_domain_name", "Default")
                id_domains_client = get_identity_domains_client(config, domain_name=domain_name)
                domain_user = find_current_user_in_domain(id_domains_client, current_user_ocid)
                return render_user_info_telegram(domain_user)
            except Exception as e:
                return f"❌ 查询失败: {str(e)[:200]}"
        if normalized.startswith("/usage_fee"):
            report_data = get_usage_fee_report_data(self.app_config)
            return render_usage_fee_telegram(report_data, show_all=False)
        if normalized.startswith("/policies"):
            try:
                app_config = self.app_config or load_app_config()
                config = get_oci_config(app_config)
                domain_name = app_config.get("oci", {}).get("identity_domain_name", "Default")
                id_domains_client = get_identity_domains_client(config, domain_name=domain_name)
                response = id_domains_client.list_password_policies()
                resources = getattr(response.data, "resources", [])
                return render_policies_telegram(resources)
            except Exception as e:
                return f"❌ 查询失败: {str(e)[:200]}"
        if normalized.startswith("/audit_events"):
            try:
                app_config = self.app_config or load_app_config()
                config = get_oci_config(app_config)
                domain_name = app_config.get("oci", {}).get("identity_domain_name", "Default")
                
                # 获取 Identity Domain URL
                identity_client = oci.identity.IdentityClient(config)
                response = identity_client.list_domains(config["tenancy"])
                domains = response.data
                target_domain = next((d for d in domains if d.display_name == domain_name), None)
                if not target_domain:
                    return f"❌ 未找到名为 {domain_name} 的 Identity Domain"
                domain_url = target_domain.url.replace(":443", "")
                
                # 解析参数：/audit_events [limit]
                parts = normalized.split()
                limit = 10  # 默认显示 10 条
                if len(parts) > 1 and parts[1].isdigit():
                    limit = min(int(parts[1]), 50)  # 最多 50 条
                
                # 调用 REST API
                resources = _fetch_audit_events_rest(config, domain_url, limit)
                return render_audit_events_telegram(resources, limit=limit)
            except Exception as e:
                LOGGER.exception("查询审计事件失败")
                return f"❌ 查询失败: {str(e)[:200]}"
        if normalized.startswith("/instance_network"):
            try:
                parts = normalized.split(maxsplit=1)
                if len(parts) < 2:
                    return "请提供实例 OCID，例如：/instance_network ocid1.instance.oc1..."
                app_config = self.app_config or load_app_config()
                config = get_oci_config(app_config)
                topology = _fetch_instance_network_topology(config, parts[1].strip())
                return render_instance_network_telegram(topology)
            except Exception as e:
                LOGGER.exception("查询实例网络安全总览失败")
                return f"❌ 查询失败: {str(e)[:200]}"
        if normalized.startswith("/nsg_rules"):
            try:
                parts = normalized.split(maxsplit=1)
                if len(parts) < 2:
                    return "请提供 NSG OCID，例如：/nsg_rules ocid1.networksecuritygroup.oc1..."
                app_config = self.app_config or load_app_config()
                config = get_oci_config(app_config)
                nsg, rules = _fetch_nsg_rules(config, parts[1].strip())
                return render_nsg_rules_telegram(nsg, rules)
            except Exception as e:
                LOGGER.exception("查询 NSG 规则失败")
                return f"❌ 查询失败: {str(e)[:200]}"
        if normalized.startswith("/sl_rules"):
            try:
                parts = normalized.split(maxsplit=1)
                if len(parts) < 2:
                    return "请提供 Security List OCID，例如：/sl_rules ocid1.securitylist.oc1..."
                app_config = self.app_config or load_app_config()
                config = get_oci_config(app_config)
                security_list = _fetch_security_list(config, parts[1].strip())
                return render_security_list_rules_telegram(security_list)
            except Exception as e:
                LOGGER.exception("查询 Security List 规则失败")
                return f"❌ 查询失败: {str(e)[:200]}"
        if normalized.startswith("/create_safe_policy"):
            return capture_output(create_safe_policy, self.app_config, True)
        if normalized.startswith("/delete_policy"):
            parts = normalized.split(maxsplit=1)
            if len(parts) < 2:
                return "请提供要删除的策略名称，例如：/delete_policy NeverExpireStandard"
            return capture_output(delete_policy, self.app_config, parts[1].strip(), True)
        if normalized.startswith("/run"):
            parts = normalized.split(maxsplit=1)
            if len(parts) < 2:
                return "请提供 action，例如：/run user_info"
            return self.handle_run_action(parts[1].strip())
        return "不支持的命令。\n" + self.build_help_text()

    def handle_run_action(self, action: str) -> str:
        if action == "user_info":
            return capture_output(get_user_info, self.app_config)
        if action == "usage_fee":
            report_data = get_usage_fee_report_data(self.app_config)
            return render_usage_fee_telegram(report_data, show_all=False)
        if action == "policies":
            return capture_output(list_policies, self.app_config)
        if action == "audit_events" or action.startswith("audit_events:"):
            limit = 10
            if ":" in action:
                try:
                    limit = int(action.split(":")[1])
                    limit = min(limit, 50)
                except:
                    pass
            return capture_output(list_audit_events, self.app_config, limit)
        if action.startswith("instance_network:"):
            return capture_output(show_instance_network, self.app_config, action.split(":", 1)[1].strip())
        if action.startswith("nsg_rules:"):
            return capture_output(show_nsg_rules, self.app_config, action.split(":", 1)[1].strip())
        if action.startswith("sl_rules:"):
            return capture_output(show_security_list_rules, self.app_config, action.split(":", 1)[1].strip())
        if action == "create_safe_policy":
            return capture_output(create_safe_policy, self.app_config, True)
        if action.startswith("delete_policy:"):
            policy_name = action.split(":", 1)[1].strip()
            if not policy_name:
                return "delete_policy 动作必须附带策略名，例如 delete_policy:NeverExpireStandard"
            return capture_output(delete_policy, self.app_config, policy_name, True)
        return "未知 action，可选: user_info, usage_fee, policies, audit_events[:N], instance_network:<OCID>, nsg_rules:<OCID>, sl_rules:<OCID>, create_safe_policy, delete_policy:<名称>"

    def handle_callback_query(self, callback_query: Dict[str, Any]) -> None:
        callback_query_id = str(callback_query.get("id", ""))
        data = str(callback_query.get("data", ""))
        message = callback_query.get("message") or {}
        chat = message.get("chat") or {}
        chat_id = str(chat.get("id", ""))
        message_id = int(message.get("message_id", 0) or 0)
        from_user = callback_query.get("from") or {}

        pseudo_message = {
            "chat": chat,
            "from": from_user,
        }

        if not self.is_authorized(pseudo_message):
            self.answer_callback_query(callback_query_id, "未授权操作")
            return

        if data not in {"usage_fee:expand", "usage_fee:collapse"}:
            self.answer_callback_query(callback_query_id, "未知操作")
            return

        report_data = get_usage_fee_report_data(self.app_config)
        show_all = data == "usage_fee:expand"
        text = render_usage_fee_telegram(report_data, show_all=show_all)
        keyboard = self.build_usage_fee_keyboard(show_all, len(report_data["unique_dates"]), report_data["display_days"])

        self.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            parse_mode="HTML",
            reply_markup=keyboard,
        )
        self.answer_callback_query(callback_query_id, "已更新显示内容")

    def process_update(self, update: Dict[str, Any]) -> None:
        self.last_update_id = max(self.last_update_id, int(update.get("update_id", 0)))
        callback_query = update.get("callback_query")
        if callback_query:
            LOGGER.info(f"🔘 处理 callback_query: {callback_query.get('data')}")
            self.handle_callback_query(callback_query)
            return

        message = update.get("message") or {}
        chat = message.get("chat") or {}
        chat_id = str(chat.get("id", ""))
        text = message.get("text", "")

        if not chat_id or not text:
            LOGGER.debug(f"⏩ 跳过空消息: chat_id={chat_id}, text={text}")
            return

        LOGGER.info(f"💬 收到消息: chat_id={chat_id}, text={text[:50]}")

        if not self.is_authorized(message):
            LOGGER.warning(f"❌ 未授权访问: chat_id={chat_id}")
            self.send_message(chat_id, "❌ 当前 chat/user 未授权执行该 Bot 命令。")
            return

        try:
            LOGGER.info(f"🚀 开始处理命令: {text[:100]}")
            if text.strip().startswith("/usage_fee"):
                LOGGER.info("📊 处理 /usage_fee 命令")
                report_data = get_usage_fee_report_data(self.app_config)
                rendered = render_usage_fee_telegram(report_data, show_all=False)
                keyboard = self.build_usage_fee_keyboard(False, len(report_data["unique_dates"]), report_data["display_days"])
                self.send_message(chat_id, rendered, parse_mode="HTML", reply_markup=keyboard)
                LOGGER.info("✅ /usage_fee 命令处理完成")
                return

            result = self.handle_command(text)
            LOGGER.info(f"✅ 命令处理完成，结果长度: {len(result)} 字符")
        except Exception as exc:
            LOGGER.exception(f"❌ 命令执行失败: {text[:50]}")
            result = f"❌ 命令执行失败：{exc}"

        # 检测是否包含 HTML 标签
        parse_mode = "HTML" if "<b>" in result or "<code>" in result or "<i>" in result else None
        LOGGER.info(f"📤 发送回复: chat_id={chat_id}, parse_mode={parse_mode}, length={len(result)}")
        self.send_message(chat_id, result or "✅ 命令执行完成，但无返回内容。", parse_mode=parse_mode)
        LOGGER.info("✅ 回复已发送")

    def run_polling(self) -> None:
        LOGGER.info("🔍 开始启动 Telegram Bot...")
        try:
            LOGGER.info("🔍 步骤 1/3: 验证配置...")
            self.validate()
            LOGGER.info("✅ 配置验证通过")
            
            LOGGER.info("🔍 步骤 2/3: 同步 Bot 命令菜单...")
            self.refresh_bot_commands()
            LOGGER.info("✅ Telegram Bot 命令菜单已同步")
            
            LOGGER.info("🔍 步骤 3/3: 启动消息轮询...")
            LOGGER.info("🤖 Telegram Bot 已启动，正在轮询消息...")
            print("🤖 Telegram Bot 已启动，正在轮询消息...")  # 保留 print 以防 LOGGER 被禁用
            print("按 Ctrl+C 可停止 Bot。")
        except Exception as e:
            LOGGER.exception("❌ Bot 启动失败")
            raise
        
        while True:
            try:
                updates = self.get_updates()
                if updates:
                    LOGGER.info(f"📨 收到 {len(updates)} 条更新")
                for update in updates:
                    self.process_update(update)
            except requests.RequestException as exc:
                LOGGER.warning(f"⚠️ Telegram 网络请求失败: {exc}")
                print(f"⚠️ Telegram 网络请求失败: {exc}")
                time.sleep(self.poll_interval)
            except Exception as exc:
                LOGGER.exception("⚠️ Telegram 处理异常")
                print(f"⚠️ Telegram 处理异常: {exc}")
                time.sleep(self.poll_interval)


# ==========================================
# 5. 主程序菜单与入口
# ==========================================
def print_cli_menu() -> None:
    print("\n" + "☁️  OCI 甲骨文云一键运维工具 ☁️ ".center(50))
    print("=" * 62)
    print("  1. 👤 查看当前用户详细信息")
    print("  2. 💰 导出本月费用账单 (CSV)")
    print("  3. 🛡️  查询当前密码策略看板")
    print("  4. 📋 查询审计事件日志")
    print("  5. 🔥 查询网络防火墙策略列表")
    print("  6. 🧱 查询网络防火墙实例列表")
    print("  7. 🔒 创建/修复永不过期安全策略")
    print("  8. 🗑️  删除冗余密码策略")
    print("  9. 🤖 启动 Telegram Bot 轮询")
    print("  0. 🚪 退出程序")
    print("=" * 62)


def main_menu(app_config: Dict[str, Any]) -> None:
    clear_cmd = "cls" if os.name == "nt" else "clear"

    while True:
        print_cli_menu()
        choice = input("👉 请选择要执行的功能 (0-9): ").strip()

        if choice not in ["0", "1", "2", "3", "4", "5", "6", "7", "8", "9"]:
            os.system(clear_cmd)
            print("❌ 指令无效！请重新输入菜单前方的数字 (0 到 9 之间)。")
            continue

        if choice == "1":
            get_user_info(app_config)
        elif choice == "2":
            export_usage_fee(app_config)
        elif choice == "3":
            list_policies(app_config)
        elif choice == "4":
            list_audit_events(app_config)
        elif choice == "5":
            list_network_firewall_policies(app_config)
        elif choice == "6":
            list_network_firewalls(app_config)
        elif choice == "7":
            create_safe_policy(app_config)
        elif choice == "8":
            delete_policy(app_config)
        elif choice == "9":
            TelegramBotRunner(app_config).run_polling()
        elif choice == "0":
            print("\n👋 感谢使用，已安全退出程序！\n")
            break

        input("\n⌨️  按 [Enter] 键返回主菜单...")
        os.system(clear_cmd)


def main() -> None:
    parser = argparse.ArgumentParser(prog="OCI_Master", description="OCI 甲骨文云一键运维工具")
    parser.add_argument("--app-config", help="指定应用配置文件路径 (默认读取环境变量 OCI_MASTER_APP_CONFIG 或同目录 oci_master_config.json)")
    parser.add_argument("-v", "--verbose", action="store_true", help="启用 DEBUG 日志")

    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("menu", help="交互式菜单")
    sub.add_parser("telegram", help="启动 Telegram Bot 轮询")

    sub.add_parser("user-info", help="查看当前用户详细信息")

    uf = sub.add_parser("usage-fee", help="查询本月费用账单")
    uf.add_argument("--show-all", action="store_true", help="展示全部日期，不折叠")
    uf.add_argument("--csv-out", help="将结果另存为 CSV 路径（默认读取 output.usage_fee_csv_* 配置）")

    sub.add_parser("policies", help="查询当前密码策略看板")

    ae = sub.add_parser("audit-events", help="查询审计事件日志")
    ae.add_argument("--limit", type=int, default=20, help="返回结果数量（默认 20）")
    ae.add_argument("--filter", help="SCIM 过滤表达式，例如: 'eventType eq \"user.login\"'")
    ae.add_argument("--sort-by", default="timestamp", help="排序字段（默认 timestamp）")
    ae.add_argument("--sort-order", choices=["ASCENDING", "DESCENDING"], default="DESCENDING", help="排序方向")

    inet = sub.add_parser("instance-network", help="查询实例网络安全总览")
    inet.add_argument("instance_id", help="实例 OCID")

    nsg = sub.add_parser("nsg-rules", help="查询 NSG 规则")
    nsg.add_argument("nsg_id", help="NSG 的 OCID")

    sl = sub.add_parser("security-list-rules", help="查询 Security List 规则")
    sl.add_argument("security_list_id", help="Security List 的 OCID")

    sle = sub.add_parser("security-list-export", help="导出 Security List 规则备份")
    sle.add_argument("security_list_id", help="Security List 的 OCID")
    sle.add_argument("--output", help="导出 JSON 路径")

    sla = sub.add_parser("security-list-add-ingress", help="添加 Security List Ingress 规则（默认预览）")
    sla.add_argument("security_list_id", help="Security List 的 OCID")
    sla.add_argument("--source", required=True, help="来源 CIDR，例如 0.0.0.0/0")
    sla.add_argument("--protocol", default="6", help="协议号，默认 6(TCP)")
    sla.add_argument("--port-min", type=int, help="目标最小端口")
    sla.add_argument("--port-max", type=int, help="目标最大端口")
    sla.add_argument("--description", help="规则描述")
    sla.add_argument("--stateless", action="store_true", help="是否为无状态规则")
    sla.add_argument("--apply", action="store_true", help="真正提交变更；默认仅预览")

    slr = sub.add_parser("security-list-remove-ingress", help="删除 Security List Ingress 规则（默认预览）")
    slr.add_argument("security_list_id", help="Security List 的 OCID")
    slr.add_argument("--rule-index", type=int, required=True, help="要删除的 Ingress 规则序号（从 1 开始）")
    slr.add_argument("--apply", action="store_true", help="真正提交变更；默认仅预览")

    csp = sub.add_parser("create-safe-policy", help="创建/修复永不过期安全策略")
    csp.add_argument("--auto-approve", action="store_true", help="无需交互确认")

    dp = sub.add_parser("delete-policy", help="删除冗余密码策略")
    dp.add_argument("name", help="策略名称")
    dp.add_argument("--auto-approve", action="store_true", help="无需交互确认")

    # 兼容旧版 run action
    runp = sub.add_parser("run", help="兼容旧版：运行预设动作")
    runp.add_argument("action", help="user_info|usage_fee|policies|audit_events[:N]|instance_network:<OCID>|nsg_rules:<OCID>|sl_rules:<OCID>|create_safe_policy|delete_policy:<名称>")

    args = parser.parse_args()

    setup_logger(verbose=args.verbose)

    app_config = load_app_config(args.app_config)

    if args.cmd in (None, "menu"):
        return main_menu(app_config)
    if args.cmd == "telegram":
        return TelegramBotRunner(app_config).run_polling()
    if args.cmd == "user-info":
        return get_user_info(app_config)
    if args.cmd == "usage-fee":
        try:
            export_usage_fee(app_config, show_all=args.show_all, csv_out=args.csv_out)
        except Exception as e:
            print(f"❌ 运行出错: {e}")
            sys.exit(1)
        return
    if args.cmd == "policies":
        return list_policies(app_config)
    if args.cmd == "audit-events":
        return list_audit_events(
            app_config,
            limit=args.limit,
            filter_expr=args.filter,
            sort_by=args.sort_by,
            sort_order=args.sort_order
        )
    if args.cmd == "instance-network":
        return show_instance_network(app_config, instance_id=args.instance_id)
    if args.cmd == "nsg-rules":
        return show_nsg_rules(app_config, nsg_id=args.nsg_id)
    if args.cmd == "security-list-rules":
        return show_security_list_rules(app_config, security_list_id=args.security_list_id)
    if args.cmd == "security-list-export":
        print(export_security_list_rules(app_config, security_list_id=args.security_list_id, output_path=args.output))
        return
    if args.cmd == "security-list-add-ingress":
        return add_security_list_ingress_rule(
            app_config,
            security_list_id=args.security_list_id,
            source=args.source,
            protocol=args.protocol,
            port_min=args.port_min,
            port_max=args.port_max,
            description=args.description,
            stateless=args.stateless,
            apply=args.apply,
        )
    if args.cmd == "security-list-remove-ingress":
        return remove_security_list_ingress_rule(
            app_config,
            security_list_id=args.security_list_id,
            rule_index=args.rule_index,
            apply=args.apply,
        )
    if args.cmd == "create-safe-policy":
        return create_safe_policy(app_config, auto_approve=args.auto_approve)
    if args.cmd == "delete-policy":
        return delete_policy(app_config, target_name=args.name, auto_approve=args.auto_approve)
    if args.cmd == "run":
        action = args.action
        if action == "user_info":
            return get_user_info(app_config)
        if action == "usage_fee":
            return export_usage_fee(app_config)
        if action == "policies":
            return list_policies(app_config)
        if action.startswith("instance_network:"):
            return show_instance_network(app_config, instance_id=action.split(":", 1)[1].strip())
        if action.startswith("nsg_rules:"):
            return show_nsg_rules(app_config, nsg_id=action.split(":", 1)[1].strip())
        if action.startswith("sl_rules:"):
            return show_security_list_rules(app_config, security_list_id=action.split(":", 1)[1].strip())
        if action == "create_safe_policy":
            return create_safe_policy(app_config, auto_approve=True)
        if action.startswith("delete_policy:"):
            return delete_policy(app_config, target_name=action.split(":", 1)[1].strip(), auto_approve=True)
        raise ValueError("不支持的 action。可选: user_info, usage_fee, policies, audit_events[:N], instance_network:<OCID>, nsg_rules:<OCID>, sl_rules:<OCID>, create_safe_policy, delete_policy:<名称>")


if __name__ == "__main__":
    try:
        os.system("cls" if os.name == "nt" else "clear")
        main()
    except KeyboardInterrupt:
        print("\n\n👋 程序已被手动中止，再见！\n")
