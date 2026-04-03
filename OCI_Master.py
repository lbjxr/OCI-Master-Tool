import io
import json
import os
import sys
import time
import html
from contextlib import redirect_stdout
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

import oci
import requests


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_APP_CONFIG_PATH = os.path.join(BASE_DIR, "oci_master_config.json")
DEFAULT_APP_CONFIG_EXAMPLE_PATH = os.path.join(BASE_DIR, "oci_master_config.example.json")


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
        return json.load(file)


def get_oci_config(app_config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """加载 OCI SDK 配置，支持通过应用配置文件传入路径和 profile。"""
    app_config = app_config or load_app_config()
    oci_settings = app_config.get("oci", {})
    config_file = oci_settings.get("config_file")
    profile = oci_settings.get("profile_name", "DEFAULT")

    if config_file:
        return oci.config.from_file(file_location=config_file, profile_name=profile)
    return oci.config.from_file(profile_name=profile)


def get_identity_domains_client(config: Dict[str, Any], domain_name: str = "Default"):
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


def export_usage_fee(app_config: Optional[Dict[str, Any]] = None) -> None:
    """功能 2：查询本月费用账单，并默认仅展示最新 1 天结果。"""
    print("\n" + "=" * 65)
    print("💰 正在查询本月费用数据...")
    try:
        app_config = app_config or load_app_config()
        config = get_oci_config(app_config)
        usage_client = oci.usage_api.UsageapiClient(config)
        output_cfg = app_config.get("output", {})
        display_days = int(output_cfg.get("usage_fee_display_days", 1) or 1)

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
        total_cost = 0.0
        currency = "USD"

        if not response.data.items:
            print("提示：此时间段内没有产生任何费用数据。")
            return

        sorted_items = sorted(response.data.items, key=lambda x: x.time_usage_started)
        rows: List[List[str]] = []
        unique_dates = []
        seen_dates = set()

        for item in sorted_items:
            date_str = item.time_usage_started.strftime("%Y-%m-%d")
            service = getattr(item, "service", "Unknown Service") or "Unknown Service"
            amount = getattr(item, "computed_amount", 0.0) or 0.0
            currency = getattr(item, "currency", "USD") or "USD"
            total_cost += amount

            rows.append([date_str, truncate_text(service, 28), f"{amount:.4f}", currency])
            if date_str not in seen_dates:
                seen_dates.add(date_str)
                unique_dates.append(date_str)

        latest_dates = set(unique_dates[-display_days:]) if unique_dates else set()
        display_rows = [row for row in rows if row[0] in latest_dates]

        print_section("本月费用汇总", "💰")
        print_kv("查询区间", f"{start_time.strftime('%Y-%m-%d')} ~ {end_time.strftime('%Y-%m-%d')}")
        print_kv("账单总记录数", len(rows))
        print_kv("涉及日期数", len(unique_dates))
        print_kv("默认展示天数", display_days)
        print(f"📊 本月预估总计: {total_cost:.4f} {currency}")

        print_section(f"费用明细（默认仅展示最近 {display_days} 天）", "📄")
        print(build_text_table(["日期", "服务名称", "金额", "币种"], display_rows))

        if len(unique_dates) > display_days:
            hidden_days = len(unique_dates) - display_days
            print()
            print(f"ℹ️ 已折叠更早的 {hidden_days} 天数据；当前默认仅展示最近 {display_days} 天。")
    except Exception as e:
        print(f"❌ 运行出错: {e}")


def get_usage_fee_report_data(app_config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    app_config = app_config or load_app_config()
    config = get_oci_config(app_config)
    usage_client = oci.usage_api.UsageapiClient(config)
    output_cfg = app_config.get("output", {})
    display_days = int(output_cfg.get("usage_fee_display_days", 1) or 1)

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

    latest_dates = set(unique_dates if show_all else unique_dates[-display_days:]) if unique_dates else set()
    display_rows = [
        [row[0], truncate_text(row[1], 22), row[2], row[3] or "-"]
        for row in rows
        if row[0] in latest_dates
    ]

    table = build_text_table(["日期", "服务", "金额", "币种"], display_rows)
    hidden_days = max(0, len(unique_dates) - display_days)

    message_parts = [
        "<b>💰 本月费用汇总</b>",
        f"查询区间: <code>{report_data['start_time'].strftime('%Y-%m-%d')} ~ {report_data['end_time'].strftime('%Y-%m-%d')}</code>",
        f"账单总记录数: <b>{len(rows)}</b>",
        f"涉及日期数: <b>{len(unique_dates)}</b>",
        f"本月预估总计: <b>{report_data['total_cost']:.4f} {html.escape(report_data['currency'])}</b>",
        "",
        f"<b>📄 费用明细（{'全部数据' if show_all else f'最近 {display_days} 天'}）</b>",
        f"<pre>{html.escape(table)}</pre>",
    ]

    if not show_all and hidden_days > 0:
        message_parts.append(f"ℹ️ 已折叠更早的 <b>{hidden_days}</b> 天数据，点击下方按钮可展开全部。")
    elif show_all and len(unique_dates) > display_days:
        message_parts.append("ℹ️ 当前显示全部数据，点击下方按钮可切回默认折叠视图。")

    return "\n".join(message_parts)


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
        self.bot_token = self.telegram_config.get("bot_token", "")
        self.allowed_chat_ids = {str(item) for item in self.telegram_config.get("allowed_chat_ids", [])}
        self.allowed_user_ids = {str(item) for item in self.telegram_config.get("allowed_user_ids", [])}
        self.poll_interval = int(self.telegram_config.get("poll_interval_seconds", 3))
        self.api_base = f"https://api.telegram.org/bot{self.bot_token}" if self.bot_token else ""
        self.last_update_id = int(self.telegram_config.get("initial_update_offset", 0))

    def validate(self) -> None:
        if not self.enabled:
            raise ValueError("Telegram Bot 未启用，请在配置文件中将 telegram.enabled 设为 true")
        if not self.bot_token:
            raise ValueError("Telegram Bot 缺少 bot_token 配置")

    def _request(self, method: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        response = requests.post(f"{self.api_base}/{method}", json=payload or {}, timeout=60)
        response.raise_for_status()
        data = response.json()
        if not data.get("ok"):
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
        max_len = 3900
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

        chat_ok = not self.allowed_chat_ids or chat_id in self.allowed_chat_ids
        user_ok = not self.allowed_user_ids or user_id in self.allowed_user_ids
        return chat_ok and user_ok

    def build_help_text(self) -> str:
        return (
            "🤖 OCI Master Telegram Bot 命令菜单\n"
            "────────────────────────\n"
            "/start                查看欢迎信息\n"
            "/help                 查看帮助\n"
            "/menu                 查看帮助\n"
            "/user_info            查看当前用户详细信息\n"
            "/usage_fee            导出本月费用账单\n"
            "/policies             查询密码策略看板\n"
            "/create_safe_policy   创建永不过期安全策略\n"
            "/delete_policy 名称   删除指定策略\n"
            "/run <action>         执行动作\n\n"
            "可用 action:\n"
            "- user_info\n"
            "- usage_fee\n"
            "- policies\n"
            "- create_safe_policy\n"
            "- delete_policy:<名称>"
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
            return capture_output(get_user_info, self.app_config)
        if normalized.startswith("/usage_fee"):
            report_data = get_usage_fee_report_data(self.app_config)
            return render_usage_fee_telegram(report_data, show_all=False)
        if normalized.startswith("/policies"):
            return capture_output(list_policies, self.app_config)
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
        if action == "create_safe_policy":
            return capture_output(create_safe_policy, self.app_config, True)
        if action.startswith("delete_policy:"):
            policy_name = action.split(":", 1)[1].strip()
            if not policy_name:
                return "delete_policy 动作必须附带策略名，例如 delete_policy:NeverExpireStandard"
            return capture_output(delete_policy, self.app_config, policy_name, True)
        return "未知 action，可选: user_info, usage_fee, policies, create_safe_policy, delete_policy:<名称>"

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
            self.handle_callback_query(callback_query)
            return

        message = update.get("message") or {}
        chat = message.get("chat") or {}
        chat_id = str(chat.get("id", ""))
        text = message.get("text", "")

        if not chat_id or not text:
            return

        if not self.is_authorized(message):
            self.send_message(chat_id, "❌ 当前 chat/user 未授权执行该 Bot 命令。")
            return

        try:
            if text.strip().startswith("/usage_fee"):
                report_data = get_usage_fee_report_data(self.app_config)
                rendered = render_usage_fee_telegram(report_data, show_all=False)
                keyboard = self.build_usage_fee_keyboard(False, len(report_data["unique_dates"]), report_data["display_days"])
                self.send_message(chat_id, rendered, parse_mode="HTML", reply_markup=keyboard)
                return

            result = self.handle_command(text)
        except Exception as exc:
            result = f"❌ 命令执行失败：{exc}"

        self.send_message(chat_id, result or "✅ 命令执行完成，但无返回内容。")

    def run_polling(self) -> None:
        self.validate()
        self.refresh_bot_commands()
        print("🤖 Telegram Bot 命令菜单已同步到 Telegram 客户端。")
        print("🤖 Telegram Bot 已启动，正在轮询消息...")
        print("按 Ctrl+C 可停止 Bot。")
        while True:
            try:
                updates = self.get_updates()
                for update in updates:
                    self.process_update(update)
            except requests.RequestException as exc:
                print(f"⚠️ Telegram 网络请求失败: {exc}")
                time.sleep(self.poll_interval)
            except Exception as exc:
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
    print("  4. 🔒 创建/修复永不过期安全策略")
    print("  5. 🗑️  删除冗余密码策略")
    print("  6. 🤖 启动 Telegram Bot 轮询")
    print("  0. 🚪 退出程序")
    print("=" * 62)


def main_menu(app_config: Dict[str, Any]) -> None:
    clear_cmd = "cls" if os.name == "nt" else "clear"

    while True:
        print_cli_menu()
        choice = input("👉 请选择要执行的功能 (0-6): ").strip()

        if choice not in ["0", "1", "2", "3", "4", "5", "6"]:
            os.system(clear_cmd)
            print("❌ 指令无效！请重新输入菜单前方的数字 (0 到 6 之间)。")
            continue

        if choice == "1":
            get_user_info(app_config)
        elif choice == "2":
            export_usage_fee(app_config)
        elif choice == "3":
            list_policies(app_config)
        elif choice == "4":
            create_safe_policy(app_config)
        elif choice == "5":
            delete_policy(app_config)
        elif choice == "6":
            TelegramBotRunner(app_config).run_polling()
        elif choice == "0":
            print("\n👋 感谢使用，已安全退出程序！\n")
            break

        input("\n⌨️  按 [Enter] 键返回主菜单...")
        os.system(clear_cmd)


def parse_args(argv: List[str]) -> Tuple[str, Optional[str]]:
    if len(argv) >= 2:
        if argv[1] == "telegram":
            return "telegram", None
        if argv[1] == "run" and len(argv) >= 3:
            return "run", argv[2]
    return "menu", None


def execute_action(action: str, app_config: Dict[str, Any]) -> None:
    if action == "user_info":
        get_user_info(app_config)
    elif action == "usage_fee":
        export_usage_fee(app_config)
    elif action == "policies":
        list_policies(app_config)
    elif action == "create_safe_policy":
        create_safe_policy(app_config, auto_approve=True)
    elif action.startswith("delete_policy:"):
        delete_policy(app_config, target_name=action.split(":", 1)[1].strip(), auto_approve=True)
    else:
        raise ValueError("不支持的 action。可选: user_info, usage_fee, policies, create_safe_policy, delete_policy:<名称>")


def main() -> None:
    app_config = load_app_config()
    mode, action = parse_args(sys.argv)

    if mode == "telegram":
        TelegramBotRunner(app_config).run_polling()
        return
    if mode == "run" and action:
        execute_action(action, app_config)
        return

    main_menu(app_config)


if __name__ == "__main__":
    try:
        os.system("cls" if os.name == "nt" else "clear")
        main()
    except KeyboardInterrupt:
        print("\n\n👋 程序已被手动中止，再见！\n")
