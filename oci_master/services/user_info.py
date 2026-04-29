import html
from typing import Any, Dict, Optional

import oci

from oci_master.clients import get_identity_domains_client
from oci_master.config import get_oci_config
from oci_master.utils import (
    format_bool,
    format_datetime_compact,
    print_divider,
    print_kv,
    print_section,
    safe_get,
    safe_get_any,
    unwrap_state_value,
)


def find_current_user_in_domain(id_domains_client, user_ocid: str) -> Dict[str, Any]:
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
    print_kv("用户名 (user_name)", safe_get_any(user_data, "user_name", "userName"))
    print_kv("显示名称 (display_name)", safe_get_any(user_data, "display_name", "displayName"))
    print_kv("描述/全名", safe_get(user_data, "description"))
    print_kv("用户 ID", safe_get(user_data, "id"))
    print_kv("用户 OCID", safe_get(user_data, "ocid", safe_get(user_data, "id")))
    print_kv("Active", format_bool(safe_get(user_data, "active")))
    print_kv("用户类型", safe_get_any(user_data, "user_type", "userType"))
    print_kv(
        "创建时间",
        format_datetime_compact(
            safe_get_any(safe_get(user_data, "meta", {}), "created", "creation_date", "creationDate")
        ),
    )
    print_kv("Locale", safe_get(user_data, "locale"))
    print_kv("Timezone", safe_get(user_data, "timezone"))
    print_kv("Preferred Language", safe_get_any(user_data, "preferred_language", "preferredLanguage"))


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


def get_user_info_data(app_config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    config = get_oci_config(app_config)
    identity_client = oci.identity.IdentityClient(config)
    basic_response = identity_client.get_user(config["user"])

    if not basic_response or not getattr(basic_response, "data", None):
        raise ValueError("未能从 IAM 获取当前用户基础信息")

    current_user_ocid = safe_get(basic_response.data, "id")
    domain_name = (app_config or {}).get("oci", {}).get("identity_domain_name", "Default")
    id_domains_client = get_identity_domains_client(config, domain_name=domain_name)
    return find_current_user_in_domain(id_domains_client, current_user_ocid)


def render_user_info_telegram(user_data: Dict[str, Any]) -> str:
    username = html.escape(str(safe_get_any(user_data, "user_name", "userName")))
    display_name = html.escape(str(safe_get_any(user_data, "display_name", "displayName")))
    description = html.escape(str(safe_get(user_data, "description")))
    user_id = html.escape(str(safe_get(user_data, "id")))
    user_ocid = html.escape(str(safe_get(user_data, "ocid", safe_get(user_data, "id"))))
    active = html.escape(str(format_bool(safe_get(user_data, "active"))))
    user_type = html.escape(str(safe_get_any(user_data, "user_type", "userType")))
    created_at = html.escape(format_datetime_compact(safe_get_any(safe_get(user_data, "meta", {}), "created", "creation_date", "creationDate")))
    locale = html.escape(str(safe_get(user_data, "locale")))
    timezone = html.escape(str(safe_get(user_data, "timezone")))
    preferred_language = html.escape(str(safe_get_any(user_data, "preferred_language", "preferredLanguage")))

    emails = safe_get(user_data, "emails", [])
    email_lines = []
    if emails and emails != "N/A":
        for email in emails[:5]:
            value = html.escape(str(safe_get(email, "value")))
            email_type = html.escape(str(safe_get(email, "type")))
            primary = "⭐️" if safe_get(email, "primary", False) else "•"
            email_lines.append(f"{primary} <code>{value}</code> <i>({email_type})</i>")
    else:
        email_lines.append("• <i>N/A</i>")

    groups = safe_get(user_data, "groups", [])
    group_lines = []
    if groups and groups != "N/A":
        for group in groups[:8]:
            group_lines.append(f"• {html.escape(str(safe_get(group, 'display', safe_get(group, 'value'))))}")
    else:
        group_lines.append("• <i>N/A</i>")

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
    locked_value = html.escape(str(unwrap_state_value(safe_get(user_state, "locked", None), "on", default="N/A"))) if user_state else "N/A"
    expired_value = html.escape(str(unwrap_state_value(safe_get(password_state, "expired", None), "on", default="N/A"))) if password_state else "N/A"

    lines = [
        "<b>👤 当前用户信息</b>",
        f"<blockquote><b>{display_name}</b>\n用户名：<code>{username}</code>\nActive：<code>{active}</code></blockquote>",
        "<b>📌 基础信息</b>",
        f"🆔 用户 ID：<code>{user_id}</code>",
        f"🧾 用户类型：<code>{user_type}</code>",
        f"🕒 创建时间：<code>{created_at}</code>",
        f"🌐 Locale / Language：<code>{locale} / {preferred_language}</code>",
        f"🕰️ Timezone：<code>{timezone}</code>",
        f"📄 描述：<code>{description}</code>",
        "",
        "<b>📧 联系方式</b>",
        *email_lines,
        "",
        "<b>🛡️ 权限归属</b>",
        *group_lines,
        "",
        "<b>🔐 账号状态</b>",
        f"🔒 锁定状态：<code>{locked_value}</code>",
        f"🔑 密码过期：<code>{expired_value}</code>",
        "",
        f"<b>🆔 用户 OCID</b>\n<code>{user_ocid}</code>",
    ]
    return "\n".join(lines)


def get_user_info(app_config: Optional[Dict[str, Any]] = None) -> None:
    print()
    print_divider("=", 40)
    print("👤 正在查询用户详细信息...")
    print_divider("=", 40)

    try:
        domain_user = get_user_info_data(app_config)
        print("✅ 连接成功！已获取更详细的账号信息。")
        print_basic_identity_info(domain_user)
        print_contact_info(domain_user)
        print_membership_info(domain_user)
        print_extension_info(domain_user)
        print()
    except Exception as e:
        print(f"❌ 查询失败，请检查 OCI 配置、租户域设置或接口权限：\n{e}")
