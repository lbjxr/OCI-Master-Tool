"""
OCI Master - Telegram 策略菜单
"""
import html
import logging
import re
from typing import Dict, Any, Tuple, List

from core import safe_get
from features.policies import list_policies, create_policy, delete_policy, get_policy_by_name

LOGGER = logging.getLogger(__name__)


# 策略菜单会话状态存储
_policy_menu_sessions = {}


def _pm_key(chat_id: int) -> str:
    """生成策略菜单会话键"""
    return f"pm_{chat_id}"


def get_pm_state(chat_id: int) -> Dict[str, Any]:
    """获取策略菜单会话状态"""
    key = _pm_key(chat_id)
    return _policy_menu_sessions.get(key, {})


def set_pm_state(chat_id: int, state: Dict[str, Any]) -> None:
    """保存策略菜单会话状态"""
    key = _pm_key(chat_id)
    _policy_menu_sessions[key] = state


def clear_pm_state(chat_id: int) -> None:
    """清除策略菜单会话状态"""
    key = _pm_key(chat_id)
    _policy_menu_sessions.pop(key, None)


def build_inline_keyboard(rows: List[List[Dict[str, str]]]) -> Dict[str, Any]:
    """构建 Telegram inline keyboard"""
    return {"inline_keyboard": rows}


def render_pm_home() -> Tuple[str, Dict[str, Any]]:
    """渲染策略菜单主页"""
    text = (
        "<b>🔐 密码策略管理</b>\n"
        "请选择操作："
    )
    keyboard = build_inline_keyboard([
        [{"text": "📋 查看策略列表", "callback_data": "pm:view"}],
        [{"text": "➕ 创建新策略", "callback_data": "pm:create"}],
        [{"text": "🗑️ 删除策略", "callback_data": "pm:delete"}],
    ])
    return text, keyboard


def render_pm_list(app_config: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    """渲染策略列表"""
    try:
        policies = list_policies(app_config)
        
        if not policies:
            text = "<b>📋 密码策略列表</b>\n\n❓ 未发现任何策略"
        else:
            sorted_policies = sorted(
                policies,
                key=lambda x: getattr(x, "priority", 999) if getattr(x, "priority", None) is not None else 999,
            )
            
            parts = [
                "<b>📋 密码策略列表</b>",
                f"📊 策略总数: <code>{len(policies)}</code>",
            ]
            
            for i, policy in enumerate(sorted_policies, 1):
                name = str(getattr(policy, "name", "N/A") or "N/A")
                priority = getattr(policy, "priority", "N/A")
                expires = getattr(policy, "password_expires_after", "N/A")
                
                is_active = (i == 1)  # 优先级最高的正在生效
                
                if str(expires) == "0":
                    expire_text = "♾️ 永不过期"
                    status_icon = "🔒"
                else:
                    expire_text = f"📅 {expires} 天"
                    status_icon = "🔑"
                
                parts.append(f"\n<b>{i}. {status_icon} {html.escape(name)}</b>")
                parts.append(f"🎯 优先级: <code>{priority}</code>")
                parts.append(f"⏰ 过期: {expire_text}")
                if is_active:
                    parts.append("✅ <i>当前生效</i>")
                
            text = "\n".join(parts)
        
        keyboard = build_inline_keyboard([
            [{"text": "🏠 返回主菜单", "callback_data": "pm:home"}]
        ])
        
        return text, keyboard
    
    except Exception as e:
        LOGGER.exception("查询策略列表失败")
        text = f"❌ 查询失败: {str(e)[:200]}"
        keyboard = build_inline_keyboard([
            [{"text": "🏠 返回主菜单", "callback_data": "pm:home"}]
        ])
        return text, keyboard


def render_pm_create_step1(chat_id: int) -> Tuple[str, Dict[str, Any]]:
    """渲染创建策略 - 步骤1：输入策略名称"""
    text = (
        "<b>➕ 创建密码策略 · 步骤 1/2</b>\n\n"
        "请输入策略名称（英文字母、数字、下划线）：\n\n"
        "💡 示例：\n"
        "  • <code>NeverExpirePolicy</code>\n"
        "  • <code>CustomPolicy_30Days</code>\n"
        "  • <code>MyTeamPolicy</code>"
    )
    
    keyboard = build_inline_keyboard([
        [{"text": "❌ 取消", "callback_data": "pm:home"}]
    ])
    
    # 设置状态：等待用户输入策略名称
    set_pm_state(chat_id, {"step": "create_wait_name"})
    
    return text, keyboard


def render_pm_create_step2(chat_id: int, policy_name: str) -> Tuple[str, Dict[str, Any]]:
    """渲染创建策略 - 步骤2：选择过期天数"""
    text = (
        f"<b>➕ 创建密码策略 · 步骤 2/2</b>\n\n"
        f"策略名称: <code>{html.escape(policy_name)}</code>\n\n"
        f"请设置密码过期天数："
    )
    
    keyboard = build_inline_keyboard([
        [{"text": "0 (永不过期)", "callback_data": "pm:create:days:0"}],
        [{"text": "30 天", "callback_data": "pm:create:days:30"}, {"text": "60 天", "callback_data": "pm:create:days:60"}],
        [{"text": "90 天", "callback_data": "pm:create:days:90"}, {"text": "180 天", "callback_data": "pm:create:days:180"}],
        [{"text": "✍️ 自定义天数", "callback_data": "pm:create:days:custom"}],
        [{"text": "⬅️ 返回上一步", "callback_data": "pm:create"}, {"text": "❌ 取消", "callback_data": "pm:home"}],
    ])
    
    # 更新状态
    state = get_pm_state(chat_id)
    state.update({"step": "create_wait_days", "policy_name": policy_name})
    set_pm_state(chat_id, state)
    
    return text, keyboard


def render_pm_create_confirm(chat_id: int, policy_name: str, expires_days: int) -> Tuple[str, Dict[str, Any]]:
    """渲染创建策略 - 确认页面"""
    expire_text = "♾️ 永不过期" if expires_days == 0 else f"📅 {expires_days} 天"
    
    text = (
        f"<b>✅ 确认创建策略</b>\n\n"
        f"策略名称: <code>{html.escape(policy_name)}</code>\n"
        f"密码过期: {expire_text}\n"
        f"优先级: <code>999</code>\n"
        f"描述: 基于系统策略克隆\n\n"
        f"⚠️ 此操作将创建新策略，是否继续？"
    )
    
    keyboard = build_inline_keyboard([
        [{"text": "✅ 确认创建", "callback_data": f"pm:create:confirm:{expires_days}"}],
        [{"text": "⬅️ 返回上一步", "callback_data": "pm:create:back_to_days"}, {"text": "❌ 取消", "callback_data": "pm:home"}],
    ])
    
    # 更新状态
    state = get_pm_state(chat_id)
    state.update({"step": "create_confirm", "policy_name": policy_name, "expires_days": expires_days})
    set_pm_state(chat_id, state)
    
    return text, keyboard


def render_pm_delete_list(app_config: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    """渲染删除策略 - 策略列表"""
    try:
        policies = list_policies(app_config)
        
        if not policies:
            text = "<b>🗑️ 删除策略</b>\n\n❓ 未发现任何策略"
            keyboard = build_inline_keyboard([
                [{"text": "🏠 返回主菜单", "callback_data": "pm:home"}]
            ])
            return text, keyboard
        
        sorted_policies = sorted(
            policies,
            key=lambda x: getattr(x, "priority", 999) if getattr(x, "priority", None) is not None else 999,
        )
        
        parts = [
            "<b>🗑️ 选择要删除的策略</b>",
        ]
        
        rows = []
        for i, policy in enumerate(sorted_policies, 1):
            name = str(getattr(policy, "name", "N/A") or "N/A")
            priority = getattr(policy, "priority", "N/A")
            expires = getattr(policy, "password_expires_after", "N/A")
            policy_id = getattr(policy, "id", "")
            
            if str(expires) == "0":
                expire_text = "♾️ 永不过期"
                status_icon = "🔒"
            else:
                expire_text = f"📅 {expires} 天"
                status_icon = "🔑"
            
            parts.append(f"<b>{i}. {status_icon} {html.escape(name)}</b>")
            parts.append(f"   🎯 优先级: <code>{priority}</code> | ⏰ {expire_text}")
            
            # 添加删除按钮（使用策略名称而非 OCID，避免泄露）
            rows.append([{"text": f"🗑️ 删除 {name}", "callback_data": f"pm:delete:policy:{html.escape(name)}"}])
            parts.append("")
        parts.append("⚠️ 系统保护策略无法删除")
        
        rows.append([{"text": "🏠 返回主菜单", "callback_data": "pm:home"}])
        
        text = "\n".join(parts)
        keyboard = build_inline_keyboard(rows)
        
        return text, keyboard
    
    except Exception as e:
        LOGGER.exception("查询策略列表失败")
        text = f"❌ 查询失败: {str(e)[:200]}"
        keyboard = build_inline_keyboard([
            [{"text": "🏠 返回主菜单", "callback_data": "pm:home"}]
        ])
        return text, keyboard


def render_pm_delete_confirm(policy_name: str, app_config: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    """渲染删除策略 - 确认页面"""
    try:
        policy = get_policy_by_name(policy_name, app_config)
        
        if not policy:
            text = f"❌ 未找到策略: {html.escape(policy_name)}"
            keyboard = build_inline_keyboard([
                [{"text": "🏠 返回主菜单", "callback_data": "pm:home"}]
            ])
            return text, keyboard
        
        priority = getattr(policy, "priority", "N/A")
        expires = getattr(policy, "password_expires_after", "N/A")
        expire_text = "♾️ 永不过期" if str(expires) == "0" else f"📅 {expires} 天"
        
        text = (
            f"<b>⚠️ 删除确认</b>\n\n"
            f"策略名称: <code>{html.escape(policy_name)}</code>\n"
            f"🎯 优先级: <code>{priority}</code>\n"
            f"⏰ 过期: {expire_text}\n\n"
            f"🚨 此操作不可撤销！确认删除？"
        )
        
        keyboard = build_inline_keyboard([
            [{"text": "✅ 确认删除", "callback_data": f"pm:delete:confirm:{html.escape(policy_name)}"}],
            [{"text": "⬅️ 返回列表", "callback_data": "pm:delete"}, {"text": "❌ 取消", "callback_data": "pm:home"}],
        ])
        
        return text, keyboard
    
    except Exception as e:
        LOGGER.exception("查询策略详情失败")
        text = f"❌ 查询失败: {str(e)[:200]}"
        keyboard = build_inline_keyboard([
            [{"text": "🏠 返回主菜单", "callback_data": "pm:home"}]
        ])
        return text, keyboard


def validate_policy_name(name: str) -> Tuple[bool, str]:
    """
    验证策略名称
    
    Returns:
        (是否有效, 错误消息)
    """
    if not name:
        return False, "策略名称不能为空"
    
    if len(name) > 50:
        return False, "策略名称过长（最多 50 字符）"
    
    # 只允许字母、数字、下划线
    if not re.match(r'^[a-zA-Z0-9_]+$', name):
        return False, "策略名称只能包含英文字母、数字、下划线"
    
    return True, ""


def validate_expires_days(days_str: str) -> Tuple[bool, int, str]:
    """
    验证过期天数
    
    Returns:
        (是否有效, 天数值, 错误消息)
    """
    try:
        days = int(days_str)
        if days < 0:
            return False, 0, "天数不能为负数"
        if days > 36500:  # 100年
            return False, 0, "天数过大（最多 36500 天）"
        return True, days, ""
    except ValueError:
        return False, 0, "请输入有效的数字"
