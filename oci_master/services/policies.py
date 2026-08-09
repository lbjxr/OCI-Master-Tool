import html
import re
from typing import Any, Dict, List, Optional, Tuple

from oci_master.clients import get_identity_domains_client
from oci_master.config import get_oci_config, get_policy_runtime_config


_POLICY_NAME_RE = re.compile(r"^[a-zA-Z0-9_]+$")


def list_policies_data(app_config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    config = get_oci_config(app_config)
    domain_name = (app_config or {}).get("oci", {}).get("identity_domain_name", "Default")
    id_domains_client = get_identity_domains_client(config, domain_name=domain_name)
    response = id_domains_client.list_password_policies()
    resources = list(getattr(response.data, "resources", []) or [])
    resources.sort(
        key=lambda x: getattr(x, "priority", 999) if getattr(x, "priority", None) is not None else 999,
    )
    return {
        "domain_name": domain_name,
        "count": len(resources),
        "items": resources,
    }



def get_policy_by_name(policy_name: str, app_config: Optional[Dict[str, Any]] = None):
    data = list_policies_data(app_config)
    return next((p for p in data["items"] if getattr(p, "name", "") == policy_name), None)



def render_policies_telegram(data: Dict[str, Any]) -> str:
    policies = data["items"]
    if not policies:
        return "<b>🛡️ 密码策略看板</b>\n\n❓ 未发现任何策略"

    parts = [
        "<b>🛡️ 密码策略看板</b>",
        f"<blockquote>策略总数：<b>{data['count']}</b></blockquote>",
        "",
    ]

    for index, policy in enumerate(policies, 1):
        name = str(getattr(policy, "name", "N/A") or "N/A")
        priority = getattr(policy, "priority", "N/A")
        expires = getattr(policy, "password_expires_after", "N/A")
        is_active = index == 1
        status_icon = "🚀" if is_active else "⏳"
        expire_text = "♾️ 永不过期" if str(expires) == "0" else f"📅 {expires} 天"

        parts.append(f"<b>{status_icon} {index}. {html.escape(name)}</b>")
        parts.append(f"   优先级: <code>{priority}</code> | 过期: {expire_text}")
        if is_active:
            parts.append("   🟢 <i>当前生效</i>")
        parts.append("")

    return "\n".join(parts).strip()



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



def list_policies(app_config: Optional[Dict[str, Any]] = None) -> None:
    print("\n" + "=" * 80)
    print("🛡️ 正在获取身份域密码策略看板...")
    try:
        config = get_oci_config(app_config)
        domain_name = (app_config or {}).get("oci", {}).get("identity_domain_name", "Default")
        id_domains_client = get_identity_domains_client(config, domain_name=domain_name)
        _print_policy_table(id_domains_client)
    except Exception as e:
        print(f"❌ 查询失败: {e}")



def create_safe_policy(app_config: Optional[Dict[str, Any]] = None, auto_approve: bool = False) -> None:
    print("\n" + "=" * 80)
    policy_cfg = get_policy_runtime_config(app_config or {})

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



def create_policy_data(
    policy_name: str,
    expires_days: int,
    app_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    if not policy_name:
        raise ValueError("策略名称不能为空")
    if not _POLICY_NAME_RE.match(policy_name):
        raise ValueError("策略名称只能包含英文字母、数字、下划线")
    if expires_days < 0 or expires_days > 36500:
        raise ValueError("过期天数必须在 0 到 36500 之间")

    config = get_oci_config(app_config)
    domain_name = (app_config or {}).get("oci", {}).get("identity_domain_name", "Default")
    id_domains_client = get_identity_domains_client(config, domain_name=domain_name)
    from oci.identity_domains import models

    response = id_domains_client.list_password_policies()
    resources = list(getattr(response.data, "resources", []) or [])
    policy_cfg = get_policy_runtime_config(app_config or {})
    source_name = policy_cfg["source_policy_name"]
    source_policy = next((p for p in resources if getattr(p, "name", "") == source_name), None)
    if not source_policy and resources:
        source_policy = resources[0]
    if not source_policy:
        raise ValueError("未找到可用于克隆的源策略")

    new_policy_details = {
        "name": policy_name,
        "description": f"基于 {getattr(source_policy, 'name', source_name)} 克隆，通过 Telegram 创建",
        "schemas": ["urn:ietf:params:scim:schemas:oracle:idcs:PasswordPolicy"],
        "priority": 999,
        "password_expires_after": expires_days,
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
    result = id_domains_client.create_password_policy(password_policy=new_policy_obj)

    return {
        "action": "create",
        "name": policy_name,
        "expires_days": expires_days,
        "priority": 999,
        "status": getattr(result, "status", "N/A"),
        "source_policy_name": getattr(source_policy, "name", source_name),
    }



def delete_policy(
    app_config: Optional[Dict[str, Any]] = None,
    target_name: Optional[str] = None,
    auto_approve: bool = False,
) -> None:
    print("\n" + "=" * 80)
    print("🗑️ 准备删除策略，正在拉取当前策略列表...")
    current_target_name = target_name or ""

    try:
        config = get_oci_config(app_config)
        domain_name = (app_config or {}).get("oci", {}).get("identity_domain_name", "Default")
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



def delete_policy_data(
    policy_name: str,
    app_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    if not policy_name:
        raise ValueError("策略名称不能为空")

    config = get_oci_config(app_config)
    domain_name = (app_config or {}).get("oci", {}).get("identity_domain_name", "Default")
    id_domains_client = get_identity_domains_client(config, domain_name=domain_name)
    response = id_domains_client.list_password_policies()
    resources = list(getattr(response.data, "resources", []) or [])
    target_policy = next((p for p in resources if getattr(p, "name", "") == policy_name), None)
    if not target_policy:
        raise ValueError(f"未找到策略：{policy_name}")

    result = id_domains_client.delete_password_policy(password_policy_id=target_policy.id)
    return {
        "action": "delete",
        "name": policy_name,
        "status": getattr(result, "status", "N/A"),
    }



def render_policy_action_telegram(result: Dict[str, Any]) -> str:
    if result.get("action") == "create":
        expires_days = int(result.get("expires_days", 0) or 0)
        expire_text = "♾️ 永不过期" if expires_days == 0 else f"📅 {expires_days} 天"
        return (
            "<b>✅ 策略创建成功</b>\n"
            f"<blockquote>策略名称：<b>{html.escape(str(result['name']))}</b>\n"
            f"过期策略：{expire_text}\n"
            f"优先级：<code>{html.escape(str(result['priority']))}</code>\n"
            f"克隆来源：<code>{html.escape(str(result['source_policy_name']))}</code>\n"
            f"返回状态码：<code>{html.escape(str(result['status']))}</code></blockquote>\n"
            "💡 可继续点下面按钮刷新策略列表。"
        )
    return (
        "<b>✅ 策略删除成功</b>\n"
        f"<blockquote>策略名称：<b>{html.escape(str(result['name']))}</b>\n"
        f"返回状态码：<code>{html.escape(str(result['status']))}</code></blockquote>\n"
        "💡 建议立即刷新一次策略列表，确认当前生效顺序。"
    )



def validate_policy_name(name: str) -> Tuple[bool, str]:
    if not name:
        return False, "策略名称不能为空"
    if len(name) > 50:
        return False, "策略名称过长（最多 50 字符）"
    if not _POLICY_NAME_RE.match(name):
        return False, "策略名称只能包含英文字母、数字、下划线"
    return True, ""



def validate_expires_days(days_str: str) -> Tuple[bool, int, str]:
    try:
        days = int(days_str)
        if days < 0:
            return False, 0, "天数不能为负数"
        if days > 36500:
            return False, 0, "天数过大（最多 36500 天）"
        return True, days, ""
    except ValueError:
        return False, 0, "请输入有效的数字"



def build_policy_menu_keyboard() -> Dict[str, Any]:
    return {
        "inline_keyboard": [
            [{"text": "📋 查看策略列表", "callback_data": "pm:view"}],
            [{"text": "➕ 创建新策略", "callback_data": "pm:create"}],
            [{"text": "🗑️ 删除策略", "callback_data": "pm:delete"}],
        ]
    }



def build_policy_list_keyboard(data: Dict[str, Any]) -> Dict[str, Any]:
    rows: List[List[Dict[str, str]]] = []
    for policy in data["items"][:12]:
        name = str(getattr(policy, "name", "N/A") or "N/A")
        rows.append([{"text": f"🗑️ 删除 {name}", "callback_data": f"pm:delete:pick:{name}"}])
    rows.append([{"text": "🔄 刷新列表", "callback_data": "pm:view"}, {"text": "🏠 返回主菜单", "callback_data": "menu:home"}])
    return {"inline_keyboard": rows}



def build_policy_days_keyboard() -> Dict[str, Any]:
    return {
        "inline_keyboard": [
            [{"text": "0 (永不过期)", "callback_data": "pm:create:days:0"}],
            [{"text": "30 天", "callback_data": "pm:create:days:30"}, {"text": "60 天", "callback_data": "pm:create:days:60"}],
            [{"text": "90 天", "callback_data": "pm:create:days:90"}, {"text": "180 天", "callback_data": "pm:create:days:180"}],
            [{"text": "✍️ 自定义天数", "callback_data": "pm:create:days:custom"}],
            [{"text": "⬅️ 返回上一步", "callback_data": "pm:home"}, {"text": "🏠 主菜单", "callback_data": "menu:home"}],
        ]
    }



def build_policy_delete_confirm_keyboard(policy_name: str) -> Dict[str, Any]:
    return {
        "inline_keyboard": [
            [{"text": "✅ 确认删除", "callback_data": f"pm:delete:confirm:{policy_name}"}],
            [{"text": "⬅️ 返回列表", "callback_data": "pm:delete"}, {"text": "🏠 主菜单", "callback_data": "menu:home"}],
        ]
    }



def render_policy_home_text() -> str:
    return "<b>🔐 密码策略管理</b>\n请选择操作："



def render_policy_create_name_prompt() -> str:
    return (
        "<b>➕ 创建密码策略 · 步骤 1/2</b>\n\n"
        "请输入策略名称（英文字母、数字、下划线）：\n\n"
        "💡 示例：\n"
        "• <code>NeverExpirePolicy</code>\n"
        "• <code>CustomPolicy_30Days</code>\n"
        "• <code>MyTeamPolicy</code>"
    )



def render_policy_create_days_prompt(policy_name: str) -> str:
    return (
        "<b>➕ 创建密码策略 · 步骤 2/2</b>\n\n"
        f"策略名称：<code>{html.escape(policy_name)}</code>\n\n"
        "请设置密码过期天数："
    )



def render_policy_create_confirm(policy_name: str, expires_days: int) -> str:
    expire_text = "♾️ 永不过期" if expires_days == 0 else f"📅 {expires_days} 天"
    return (
        "<b>✅ 确认创建策略</b>\n\n"
        f"策略名称：<code>{html.escape(policy_name)}</code>\n"
        f"密码过期：{expire_text}\n"
        "优先级：<code>999</code>\n"
        "描述：基于系统策略克隆\n\n"
        "⚠️ 此操作将创建新策略，是否继续？"
    )



def build_policy_create_confirm_keyboard(expires_days: int) -> Dict[str, Any]:
    return {
        "inline_keyboard": [
            [{"text": "✅ 确认创建", "callback_data": f"pm:create:confirm:{expires_days}"}],
            [{"text": "⬅️ 返回上一步", "callback_data": "pm:create:back_to_days"}, {"text": "🏠 主菜单", "callback_data": "menu:home"}],
        ]
    }



def render_policy_delete_confirm(policy_name: str, app_config: Optional[Dict[str, Any]] = None) -> str:
    policy = get_policy_by_name(policy_name, app_config)
    if not policy:
        return f"❌ 未找到策略：{html.escape(policy_name)}"
    priority = getattr(policy, "priority", "N/A")
    expires = getattr(policy, "password_expires_after", "N/A")
    expire_text = "♾️ 永不过期" if str(expires) == "0" else f"📅 {expires} 天"
    return (
        "<b>⚠️ 删除确认</b>\n\n"
        f"策略名称：<code>{html.escape(policy_name)}</code>\n"
        f"🎯 优先级：<code>{priority}</code>\n"
        f"⏰ 过期：{expire_text}\n\n"
        "🚨 此操作不可撤销！确认删除？"
    )



def render_policy_delete_picker(data: Dict[str, Any]) -> str:
    if not data["items"]:
        return "<b>🗑️ 删除策略</b>\n\n❓ 未发现任何策略"
    parts = ["<b>🗑️ 选择要删除的策略</b>"]
    for index, policy in enumerate(data["items"], 1):
        name = str(getattr(policy, "name", "N/A") or "N/A")
        priority = getattr(policy, "priority", "N/A")
        expires = getattr(policy, "password_expires_after", "N/A")
        expire_text = "♾️ 永不过期" if str(expires) == "0" else f"📅 {expires} 天"
        icon = "🔒" if str(expires) == "0" else "🔑"
        parts.append(f"<b>{index}. {icon} {html.escape(name)}</b>")
        parts.append(f"   🎯 优先级: <code>{priority}</code> | ⏰ {expire_text}")
    parts.append("")
    parts.append("⚠️ 系统保护策略无法删除")
    return "\n".join(parts)



def build_policy_post_action_keyboard() -> Dict[str, Any]:
    return {
        "inline_keyboard": [
            [{"text": "📋 查看策略列表", "callback_data": "pm:view"}],
            [{"text": "🏠 返回主菜单", "callback_data": "menu:home"}],
        ]
    }
