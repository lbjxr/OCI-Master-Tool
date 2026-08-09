import html
import os
import secrets
import time
from typing import Any, Dict, List, Optional

import requests

from oci_master.config import get_instance_runtime_config, get_network_runtime_config, get_telegram_runtime_config
from oci_master.action_dispatch import parse_action
from oci_master import registry
from oci_master.services.billing import get_usage_fee_report_data, render_usage_fee_telegram
from oci_master.services.instances import (
    _paginate_items,
    execute_instance_action_data,
    get_instance_detail_data,
    list_instances_data,
    render_instance_action_telegram,
    render_instance_detail_telegram,
    render_instances_telegram,
)
from oci_master.services.network_security import (
    apply_cleanup_selected_temp_rules_data,
    apply_cleanup_temp_rules_data,
    apply_open_ingress_rule_data,
    get_instance_ingress_rules_data,
    get_instance_network_detail_pages,
    get_instance_network_overview_data,
    preview_cleanup_selected_temp_rules_data,
    preview_cleanup_temp_rules_data,
    preview_open_ingress_rule_data,
    render_cleanup_preview_telegram,
    render_cleanup_result_telegram,
    render_cleanup_selected_preview_telegram,
    render_cleanup_selected_result_telegram,
    render_instance_ingress_rules_telegram,
    render_instance_network_details_telegram,
    render_instance_network_overview_telegram,
    render_open_ingress_preview_telegram,
    render_open_ingress_result_telegram,
)
from oci_master.services.policies import (
    build_policy_create_confirm_keyboard,
    build_policy_days_keyboard,
    build_policy_delete_confirm_keyboard,
    build_policy_list_keyboard,
    build_policy_menu_keyboard,
    build_policy_post_action_keyboard,
    create_policy_data,
    delete_policy,
    delete_policy_data,
    list_policies,
    list_policies_data,
    render_policies_telegram,
    render_policy_action_telegram,
    render_policy_create_confirm,
    render_policy_create_days_prompt,
    render_policy_create_name_prompt,
    render_policy_delete_confirm,
    render_policy_delete_picker,
    render_policy_home_text,
    validate_expires_days,
    validate_policy_name,
)
from oci_master.services.tenant_insights import (
    get_audit_events_data,
    get_bucket_info_data,
    get_region_subscriptions_data,
    render_audit_events_telegram,
    render_bucket_info_telegram,
    render_region_subscriptions_telegram,
)
from oci_master.services.user_info import get_user_info, get_user_info_data, render_user_info_telegram
from oci_master.utils import build_inline_keyboard, capture_output, safe_get


def _parse_single_tcp_port_input(port_text: str) -> int:
    value = (port_text or "").strip()
    if not value:
        raise ValueError("端口不能为空")
    if "-" in value or "," in value or " " in value:
        raise ValueError("这里只支持单个 TCP 端口，例如 22 或 25565")
    try:
        port = int(value)
    except Exception as exc:
        raise ValueError("端口必须是整数") from exc
    if port < 1 or port > 65535:
        raise ValueError(f"端口超出范围：{port}，允许范围为 1-65535")
    return port


class TelegramBotRunner:
    def __init__(self, app_config: Dict[str, Any]):
        self.app_config = app_config
        self.telegram_config = app_config.get("telegram", {})
        self.instance_runtime = get_instance_runtime_config(app_config)
        self.network_runtime = get_network_runtime_config(app_config)
        self.telegram_runtime = get_telegram_runtime_config(app_config)
        self.instance_page_size = self.instance_runtime["telegram_page_size"]
        self.enabled = self.telegram_config.get("enabled", False)
        self.bot_token = os.environ.get("OCI_MASTER_BOT_TOKEN") or self.telegram_config.get("bot_token", "")
        self.allowed_chat_ids = {str(item) for item in self.telegram_config.get("allowed_chat_ids", [])}
        self.allowed_user_ids = {str(item) for item in self.telegram_config.get("allowed_user_ids", [])}
        self.poll_interval = self.telegram_runtime["poll_interval_seconds"]
        self.api_base = f"https://api.telegram.org/bot{self.bot_token}" if self.bot_token else ""
        self.last_update_id = self.telegram_runtime["initial_update_offset"]
        self.menu_sessions: Dict[str, Dict[str, Any]] = {}
        self.callback_refs: Dict[str, Dict[str, Any]] = {}
        self.instance_display_cache: Dict[str, str] = {}
        self.netsec_flow_refs: Dict[str, Dict[str, Any]] = {}
        self.nav_flow_refs: Dict[str, Dict[str, Any]] = {}
        self.rule_select_refs: Dict[str, Dict[str, Any]] = {}
        self.dangerous_action_refs: Dict[str, Dict[str, Any]] = {}
        self.rule_selection_sessions: Dict[str, Dict[str, Any]] = {}
        self.callback_ttl_seconds = 60.0
        self.callback_capacity = 1024
        self._active_callback_owner: tuple[str, str] = ("", "")
        self._startup_notice_sent = False
        self._update_query_cache: Dict[str, Any] = {}

    def validate(self) -> None:
        if not self.enabled:
            raise ValueError("Telegram Bot 未启用，请在配置文件中将 telegram.enabled 设为 true")
        if not self.bot_token:
            raise ValueError("Telegram Bot 缺少 bot_token 配置")
        if not self.allowed_chat_ids:
            raise ValueError("Telegram Bot 缺少 allowed_chat_ids 白名单配置，拒绝启动")
        if not self.allowed_user_ids:
            raise ValueError("Telegram Bot 缺少 allowed_user_ids 白名单配置，拒绝启动")

    def _request(self, method: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        response = requests.post(f"{self.api_base}/{method}", json=payload or {}, timeout=60)
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            raise requests.HTTPError(f"Telegram 请求失败: method={method} status={response.status_code}") from exc
        data = response.json()
        if not data.get("ok"):
            raise ValueError(f"Telegram API 调用失败: method={method} error_code={data.get('error_code', 'unknown')}")
        return data

    def _menu_key(self, chat_id: str, user_id: str) -> str:
        return f"{chat_id}:{user_id}"

    def _get_menu_state(self, chat_id: str, user_id: str) -> Dict[str, Any]:
        return dict(self.menu_sessions.get(self._menu_key(chat_id, user_id), {}))

    def _set_menu_state(self, chat_id: str, user_id: str, state: Dict[str, Any]) -> None:
        self.menu_sessions[self._menu_key(chat_id, user_id)] = dict(state)

    def _clear_menu_state(self, chat_id: str, user_id: str) -> None:
        self.menu_sessions.pop(self._menu_key(chat_id, user_id), None)

    def _callback_owner(self) -> tuple[str, str]:
        return self._active_callback_owner

    def _prune_callback_states(self) -> None:
        now = time.monotonic()
        stores = (self.callback_refs, self.nav_flow_refs, self.netsec_flow_refs, self.rule_select_refs, self.dangerous_action_refs)
        for store in stores:
            expired = [token for token, state in store.items() if now - float(state.get("created_at", 0)) > self.callback_ttl_seconds]
            for token in expired:
                store.pop(token, None)
            while len(store) > self.callback_capacity:
                store.pop(next(iter(store)))

    def _new_callback_state(self, store: Dict[str, Dict[str, Any]], prefix: str, payload: Dict[str, Any]) -> str:
        self._prune_callback_states()
        chat_id, user_id = self._callback_owner()
        token = f"{prefix}{secrets.token_urlsafe(9)}"
        store[token] = {**payload, "chat_id": chat_id, "user_id": user_id, "created_at": time.monotonic()}
        while len(store) > self.callback_capacity:
            store.pop(next(iter(store)))
        return token

    def _resolve_callback_state(self, store: Dict[str, Dict[str, Any]], token: str, error: str) -> Dict[str, Any]:
        self._prune_callback_states()
        state = store.get(token)
        if not state:
            raise ValueError(error)
        chat_id, user_id = self._callback_owner()
        if not chat_id or not user_id or state.get("chat_id") != chat_id or state.get("user_id") != user_id:
            raise ValueError("按钮不属于当前用户或聊天")
        return dict(state)

    def _consume_callback_state(self, store: Dict[str, Dict[str, Any]], token: str, error: str) -> Dict[str, Any]:
        state = self._resolve_callback_state(store, token, error)
        store.pop(token, None)
        return state

    def _register_dangerous_action(self, action: str, target: str) -> str:
        return self._new_callback_state(
            self.dangerous_action_refs,
            "da",
            {"action": action, "target": str(target)},
        )

    def _build_dangerous_confirmation_keyboard(self, token: str) -> Dict[str, Any]:
        return build_inline_keyboard([
            [{"text": "✅ 确认执行", "callback_data": f"danger:confirm:{token}"}],
            [{"text": "❌ 取消", "callback_data": "menu:home"}],
        ])

    def _dangerous_confirmation_text(self, action: str, target: str) -> str:
        labels = {
            "instance_stop": "停止实例",
            "instance_restart": "重启实例",
            "delete_policy": "删除密码策略",
        }
        return (
            "<b>⚠️ 高风险操作确认</b>\n"
            f"动作：<b>{html.escape(labels.get(action, action))}</b>\n"
            f"目标：<code>{html.escape(str(target))}</code>\n"
            "请确认后才会调用 OCI 写接口。确认按钮 60 秒内有效，且只能使用一次。"
        )

    def _register_callback_ref(self, value: str, prefix: str = "r") -> str:
        return self._new_callback_state(self.callback_refs, prefix, {"value": str(value)})

    def _resolve_callback_ref(self, token: str) -> str:
        state = self._resolve_callback_state(self.callback_refs, token, "按钮会话已失效，请重新进入该流程")
        return str(state["value"])

    def _build_instance_page_token(self, page: int) -> str:
        return self._register_callback_ref(str(int(page)), "p")

    def _resolve_instance_page(self, token: str) -> int:
        raw = self._resolve_callback_ref(token)
        try:
            return max(1, int(raw))
        except Exception:
            return 1

    def _cache_instance_display_name(self, instance_id: str, display_name: Optional[str]) -> None:
        instance_key = str(instance_id or "").strip()
        display = str(display_name or "").strip()
        if instance_key and display:
            self.instance_display_cache[instance_key] = display

    def _remember_instance_like(self, instance_ref: Any, display_name: Optional[str] = None) -> None:
        if isinstance(instance_ref, dict):
            instance_id = str(instance_ref.get("id", "")).strip()
            instance_name = str(instance_ref.get("display_name", "")).strip()
            if instance_id and instance_name:
                self._cache_instance_display_name(instance_id, instance_name)
            return
        instance_id = str(instance_ref or "").strip()
        if instance_id:
            self._cache_instance_display_name(instance_id, display_name)

    def _get_instance_display_name(self, instance_ref: Any, fallback: Optional[str] = None) -> str:
        if isinstance(instance_ref, dict):
            display_name = str(instance_ref.get("display_name", "")).strip()
            instance_id = str(instance_ref.get("id", "")).strip()
            if display_name:
                if instance_id:
                    self._cache_instance_display_name(instance_id, display_name)
                return display_name
            if instance_id and instance_id in self.instance_display_cache:
                return self.instance_display_cache[instance_id]
            if instance_id:
                return instance_id
        instance_id = str(instance_ref or "").strip()
        if instance_id and instance_id in self.instance_display_cache:
            return self.instance_display_cache[instance_id]
        fallback_text = str(fallback or "").strip()
        if fallback_text:
            return fallback_text
        return instance_id or "未知实例"

    def _format_instance_badge(self, instance_ref: Any, fallback: Optional[str] = None) -> str:
        display_name = self._get_instance_display_name(instance_ref, fallback=fallback)
        instance_id = ""
        if isinstance(instance_ref, dict):
            instance_id = str(instance_ref.get("id", "")).strip()
        else:
            instance_id = str(instance_ref or "").strip()
        if instance_id and display_name != instance_id:
            short_id = instance_id if len(instance_id) <= 18 else f"{instance_id[:8]}...{instance_id[-6:]}"
            return f"<b>{html.escape(display_name)}</b>\n引用：<code>{html.escape(short_id)}</code>"
        return f"<b>{html.escape(display_name)}</b>"

    def _register_nav_flow(self, kind: str, **payload: Any) -> str:
        return self._new_callback_state(self.nav_flow_refs, "nv", {"kind": kind, **payload})

    def _resolve_nav_flow(self, token: str) -> Dict[str, Any]:
        return self._resolve_callback_state(self.nav_flow_refs, token, "导航会话已失效，请重新进入该流程")

    def _build_netsec_waiting_keyboard(self, action: str, instance_ref: str, port: str, back_page: int = 1, mode: str = "cidr") -> Dict[str, Any]:
        instance_token = self._register_callback_ref(instance_ref, "i")
        port_token = self._register_callback_ref(str(port), "pt")
        page_token = self._build_instance_page_token(back_page)
        default_cidr = str(self.network_runtime.get('default_source_cidr', '0.0.0.0/0'))
        flow_token = self._register_netsec_flow(action, instance_ref, str(port), default_cidr, back_page)
        if mode == "port":
            return build_inline_keyboard([
                [
                    {"text": "⬅️ 返回端口选择", "callback_data": f"netsec:ports:{action}:{instance_token}:{page_token}"},
                    {"text": "⬅️ 返回网络/安全概览", "callback_data": f"instance:network:{instance_token}:{page_token}"},
                ],
                [{"text": "🏠 返回主菜单", "callback_data": "menu:home"}],
            ])
        return build_inline_keyboard([
            [{"text": "✅ 直接用默认 CIDR", "callback_data": f"netsec:flowuse:{flow_token}"}],
            [
                {"text": "⬅️ 返回 CIDR 选择", "callback_data": f"netsec:cidr:{action}:{instance_token}:{port_token}:{page_token}"},
                {"text": "⬅️ 返回端口选择", "callback_data": f"netsec:ports:{action}:{instance_token}:{page_token}"},
            ],
            [{"text": "🏠 返回主菜单", "callback_data": "menu:home"}],
        ])

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
            last_response = self._request("sendMessage", payload)
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

    def _send_generic_error(self, chat_id: str, message_id: Optional[int] = None) -> None:
        text = "<b>❌ 操作失败</b>\n请求未完成，请查看服务日志中的错误编号。"
        keyboard = build_inline_keyboard([[{"text": "🏠 返回主菜单", "callback_data": "menu:home"}]])
        if message_id:
            self.edit_message_text(chat_id=chat_id, message_id=message_id, text=text, parse_mode="HTML", reply_markup=keyboard)
        else:
            self.send_message(chat_id=chat_id, text=text, parse_mode="HTML", reply_markup=keyboard)

    def build_bot_commands(self) -> List[Dict[str, str]]:
        return [
            {"command": "start", "description": "查看欢迎信息"},
            {"command": "help", "description": "查看帮助菜单"},
            {"command": "menu", "description": "查看帮助菜单"},
            {"command": "user_info", "description": "查看当前用户详细信息"},
            {"command": "usage_fee", "description": "查询本月费用账单"},
            {"command": "regions", "description": "查看已订阅 Region 列表"},
            {"command": "bucket_info", "description": "查看 Object Storage / Bucket 信息"},
            {"command": "audit_events", "description": "查看 Audit Events"},
            {"command": "policies", "description": "密码策略菜单管理"},
            {"command": "create_safe_policy", "description": "创建永不过期安全策略"},
            {"command": "delete_policy", "description": "删除指定密码策略"},
            {"command": "instances", "description": "列出可访问实例"},
            {"command": "instance_detail", "description": "查看实例详情"},
            {"command": "instance_start", "description": "启动实例"},
            {"command": "instance_stop", "description": "停止实例"},
            {"command": "instance_restart", "description": "重启实例"},
            {"command": "instance_network", "description": "查看实例网络/安全概览"},
            {"command": "instance_rules", "description": "查看实例当前入站规则"},
            {"command": "instance_temp_rules", "description": "查看本工具临时规则"},
            {"command": "netsec_open", "description": "预览+确认开放临时 TCP 入站"},
            {"command": "netsec_close_temp", "description": "预览+确认删除临时入站规则"},
        ]

    def refresh_bot_commands(self) -> None:
        self._request("setMyCommands", {"commands": self.build_bot_commands()})

    def is_authorized(self, message: Dict[str, Any]) -> bool:
        chat_id = str(safe_get(safe_get(message, "chat", {}), "id", ""))
        user_id = str(safe_get(safe_get(message, "from", {}), "id", ""))
        chat_ok = chat_id in self.allowed_chat_ids
        user_ok = user_id in self.allowed_user_ids
        return chat_ok and user_ok

    def build_help_text(self) -> str:
        return (
            "<b>🤖 OCI Master 命令菜单</b>\n"
            "👋 /start - 欢迎信息\n"
            "💬 /menu - 显示此菜单\n\n"
            "<b>📊 查询</b>\n"
            "👤 /user_info - 用户账号信息\n"
            "💰 /usage_fee - 本月费用账单\n"
            "🌏 /regions - 已订阅 Region 列表\n"
            "🪣 /bucket_info - Object Storage / Bucket 信息\n"
            "📋 /audit_events [数量] - Audit Events\n"
            "🔐 /policies - 密码策略菜单\n"
            "🖥️ /instances - 实例信息总览\n"
            "🔎 /instance_detail 名称或OCID - 查看实例详情\n"
            "🌐 /instance_network 名称或OCID - 查看实例网络/安全概览\n"
            "🛡️ /instance_rules 名称或OCID - 查看当前现有入站规则\n"
            "🧪 /instance_temp_rules 名称或OCID - 查看本工具临时规则\n\n"
            "<b>🛡️ 网络 / 安全</b>\n"
            "🔓 /netsec_open 实例 端口 CIDR - 预览+确认新增临时入站规则\n"
            "🧹 /netsec_close_temp 实例 端口 CIDR - 预览+确认删除临时规则\n\n"
            "<b>🛠️ 管理</b>\n"
            "▶️ /instance_start 名称或OCID - 启动实例\n"
            "⏹️ /instance_stop 名称或OCID - 停止实例\n"
            "🔄 /instance_restart 名称或OCID - 重启实例\n\n"
            "<b>⚙️ 兼容入口</b>\n"
            "<code>/run policies</code>\n"
            "<code>/run region_subscriptions</code>\n"
            "<code>/run bucket_info</code>\n"
            "<code>/run audit_events[:10]</code>\n"
            "<code>/run list_instances</code>\n"
            "<code>/run instance_detail:&lt;名称或OCID&gt;</code>\n"
            "<code>/run instance_network:&lt;名称或OCID&gt;</code>\n"
            "<code>/run instance_rules:&lt;名称或OCID&gt;</code>\n"
            "<code>/run instance_temp_rules:&lt;名称或OCID&gt;</code>"
        )

    def build_main_menu_keyboard(self) -> Dict[str, Any]:
        return build_inline_keyboard([
            [{"text": "👤 用户信息", "callback_data": "menu:user_info"}, {"text": "💰 本月账单", "callback_data": "menu:usage_fee"}],
            [{"text": "🌏 Region", "callback_data": "menu:regions"}, {"text": "🪣 Bucket", "callback_data": "menu:buckets"}],
            [{"text": "📋 Audit", "callback_data": "menu:audit"}, {"text": "🔐 密码策略", "callback_data": "menu:policies"}],
            [{"text": "🖥️ 实例列表", "callback_data": f"menu:instances:{self._build_instance_page_token(1)}"}],
            [{"text": "💬 帮助菜单", "callback_data": "menu:help"}],
        ])

    def build_usage_fee_keyboard(self, show_all: bool, unique_dates_count: int, display_days: int) -> Dict[str, Any]:
        rows: List[List[Dict[str, str]]] = []
        if unique_dates_count > display_days:
            if show_all:
                rows.append([{"text": "收起历史数据", "callback_data": "usage_fee:collapse"}])
            else:
                rows.append([{"text": "展开全部历史数据", "callback_data": "usage_fee:expand"}])
        rows.append([{"text": "🏠 返回主菜单", "callback_data": "menu:home"}])
        return build_inline_keyboard(rows)

    def build_instances_keyboard(self, data: Dict[str, Any], page: int = 1) -> Optional[Dict[str, Any]]:
        pagination = _paginate_items(data.get("items", []), page=page, page_size=self.instance_page_size)
        items = pagination["items"]
        if not items:
            return build_inline_keyboard([[{"text": "🏠 返回主菜单", "callback_data": "menu:home"}]])

        rows: List[List[Dict[str, str]]] = []
        current_page_token = self._build_instance_page_token(pagination["page"])
        for item in items:
            name = str(item["display_name"])
            state = str(item["lifecycle_state"] or "UNKNOWN")
            icon = "🟢" if state.upper() == "RUNNING" else ("🔴" if state.upper() == "STOPPED" else "🟡")
            button_text = f"{icon} {name[:22]}"
            rows.append([
                {"text": button_text, "callback_data": f"instance:detail:{self._register_callback_ref(item['id'], 'i')}:{current_page_token}"}
            ])

        nav_row: List[Dict[str, str]] = []
        if pagination["has_prev"]:
            nav_row.append({"text": "⬅️ 上一页", "callback_data": f"menu:instances:{self._build_instance_page_token(pagination['page'] - 1)}"})
        nav_row.append({"text": f"📄 {pagination['page']}/{pagination['total_pages']}", "callback_data": f"menu:instances:{self._build_instance_page_token(pagination['page'])}"})
        if pagination["has_next"]:
            nav_row.append({"text": "下一页 ➡️", "callback_data": f"menu:instances:{self._build_instance_page_token(pagination['page'] + 1)}"})
        rows.append(nav_row)
        rows.append([
            {"text": "🔄 刷新本页", "callback_data": f"menu:instances:{self._build_instance_page_token(pagination['page'])}"},
            {"text": "🏠 返回主菜单", "callback_data": "menu:home"},
        ])
        return build_inline_keyboard(rows)

    def build_instance_detail_keyboard(self, detail: Dict[str, Any], back_page: int = 1) -> Dict[str, Any]:
        instance_id = str(detail["id"])
        self._remember_instance_like(detail)
        instance_token = self._register_callback_ref(instance_id, "i")
        page_token = self._build_instance_page_token(back_page)
        rows: List[List[Dict[str, str]]] = [
            [
                {"text": "▶️ 启动", "callback_data": f"instance:start:{instance_token}:{page_token}"},
                {"text": "⏹️ 停止", "callback_data": f"instance:stop:{instance_token}:{page_token}"},
                {"text": "🔄 重启", "callback_data": f"instance:restart:{instance_token}:{page_token}"},
            ],
            [
                {"text": "🌐 网络/安全", "callback_data": f"instance:network:{instance_token}:{page_token}"},
            ],
            [
                {"text": "⬅️ 返回实例列表", "callback_data": f"menu:instances:{page_token}"},
                {"text": "🏠 返回主菜单", "callback_data": "menu:home"},
            ],
        ]
        return build_inline_keyboard(rows)

    def build_instance_action_keyboard(self, instance_id: str, back_page: int = 1) -> Dict[str, Any]:
        instance_token = self._register_callback_ref(instance_id, "i")
        page_token = self._build_instance_page_token(back_page)
        return build_inline_keyboard([
            [
                {"text": "🔎 查看实例详情", "callback_data": f"instance:detail:{instance_token}:{page_token}"},
                {"text": "🌐 网络/安全", "callback_data": f"instance:network:{instance_token}:{page_token}"},
            ],
            [
                {"text": "🖥️ 返回实例列表", "callback_data": f"menu:instances:{page_token}"},
                {"text": "🏠 返回主菜单", "callback_data": "menu:home"},
            ],
        ])

    def build_instance_network_keyboard(self, instance_id: str, back_page: int = 1) -> Dict[str, Any]:
        self._remember_instance_like(instance_id)
        instance_token = self._register_callback_ref(instance_id, "i")
        page_token = self._build_instance_page_token(back_page)
        detail_nav = self._register_nav_flow("network_more", instance_ref=instance_id, back_page=back_page, detail_page=1)
        return build_inline_keyboard([
            [
                {"text": "🔎 查看更多明细", "callback_data": f"nav:{detail_nav}"},
            ],
            [
                {"text": "🛡️ 查看现有规则", "callback_data": f"netsec:rules:{instance_token}:{page_token}:all:1"},
                {"text": "🧪 临时规则管理", "callback_data": f"netsec:rules:{instance_token}:{page_token}:temp:1"},
            ],
            [
                {"text": "🔓 放行临时端口", "callback_data": f"netsec:ports:open:{instance_token}:{page_token}"},
                {"text": "🧹 清理临时规则", "callback_data": f"netsec:ports:cleanup:{instance_token}:{page_token}"},
            ],
            [
                {"text": "⬅️ 返回实例详情", "callback_data": f"instance:detail:{instance_token}:{page_token}"},
                {"text": "⬅️ 返回实例列表", "callback_data": f"menu:instances:{page_token}"},
            ],
            [
                {"text": "🏠 返回主菜单", "callback_data": "menu:home"},
            ],
        ])

    def build_netsec_port_keyboard(self, action: str, instance_id: str, back_page: int = 1) -> Dict[str, Any]:
        self._remember_instance_like(instance_id)
        instance_token = self._register_callback_ref(instance_id, "i")
        page_token = self._build_instance_page_token(back_page)
        allowed_ports = list(self.network_runtime.get("quick_open_allowed_tcp_ports", []))
        rows: List[List[Dict[str, str]]] = []
        row: List[Dict[str, str]] = []
        for index, port in enumerate(allowed_ports, start=1):
            cidr_nav = self._register_nav_flow("netsec_cidr", action=action, instance_ref=instance_id, port=int(port), back_page=back_page)
            row.append({
                "text": f"TCP/{int(port)}",
                "callback_data": f"nav:{cidr_nav}",
            })
            if index % 2 == 0:
                rows.append(row)
                row = []
        if row:
            rows.append(row)
        rows.append([
            {"text": "✍️ 输入自定义端口", "callback_data": f"nav:{self._register_nav_flow('netsec_portask', action=action, instance_ref=instance_id, back_page=back_page)}"},
        ])
        rows.extend([
            [
                {"text": "⬅️ 返回网络/安全概览", "callback_data": f"instance:network:{instance_token}:{page_token}"},
            ],
            [
                {"text": "⬅️ 返回实例详情", "callback_data": f"instance:detail:{instance_token}:{page_token}"},
                {"text": "🏠 返回主菜单", "callback_data": "menu:home"},
            ],
        ])
        return build_inline_keyboard(rows)

    def build_netsec_cidr_keyboard(self, action: str, instance_id: str, port: str, back_page: int = 1) -> Dict[str, Any]:
        self._remember_instance_like(instance_id)
        instance_token = self._register_callback_ref(instance_id, "i")
        port_token = self._register_callback_ref(port, "pt")
        page_token = self._build_instance_page_token(back_page)
        return build_inline_keyboard([
            [
                {"text": f"⚡ 使用默认 CIDR {self.network_runtime.get('default_source_cidr', '0.0.0.0/0')}", "callback_data": f"netsec:flowuse:{self._register_netsec_flow(action, instance_id, str(port), str(self.network_runtime.get('default_source_cidr', '0.0.0.0/0')), back_page)}"},
            ],
            [
                {"text": "✍️ 输入自定义 CIDR", "callback_data": f"nav:{self._register_nav_flow('netsec_cidrask', action=action, instance_ref=instance_id, port=str(port), back_page=back_page)}"},
            ],
            [
                {"text": "⬅️ 返回端口选择", "callback_data": f"netsec:ports:{action}:{instance_token}:{page_token}"},
                {"text": "⬅️ 返回实例详情", "callback_data": f"instance:detail:{instance_token}:{page_token}"},
            ],
            [
                {"text": "🏠 返回主菜单", "callback_data": "menu:home"},
            ],
        ])

    def _register_netsec_flow(self, action: str, instance_ref: str, port: str, source_cidr: str, back_page: int = 1) -> str:
        return self._new_callback_state(self.netsec_flow_refs, "nf", {
            "action": action,
            "instance_ref": str(instance_ref),
            "port": str(port),
            "source_cidr": str(source_cidr),
            "back_page": int(back_page),
        })

    def _selection_session_key(self, instance_ref: str, back_page: int, page: int) -> str:
        return f"{str(instance_ref)}|{int(back_page)}|{int(page)}"

    def _get_rule_selection_session(self, instance_ref: str, back_page: int = 1, page: int = 1) -> Dict[str, Any]:
        key = self._selection_session_key(instance_ref, back_page, page)
        state = self.rule_selection_sessions.get(key)
        if not state:
            state = {
                "instance_ref": str(instance_ref),
                "back_page": int(back_page),
                "page": int(page),
                "rule_keys": [],
            }
            self.rule_selection_sessions[key] = state
        return state

    def _clear_rule_selection_session(self, instance_ref: str, back_page: int = 1, page: int = 1) -> None:
        self.rule_selection_sessions.pop(self._selection_session_key(instance_ref, back_page, page), None)

    def _register_rule_selection(self, instance_ref: str, rule_keys: List[str], back_page: int = 1, page: int = 1) -> str:
        normalized_keys = sorted({str(item).strip() for item in list(rule_keys or []) if str(item).strip()})
        return self._new_callback_state(self.rule_select_refs, "rs", {
            "instance_ref": str(instance_ref),
            "rule_keys": normalized_keys,
            "back_page": int(back_page),
            "page": int(page),
        })

    def _resolve_rule_selection(self, token: str) -> Dict[str, Any]:
        return self._resolve_callback_state(self.rule_select_refs, token, "规则选择会话已失效，请重新进入临时规则管理")

    def _toggle_rule_selection(self, instance_ref: str, rule_key: str, back_page: int = 1, page: int = 1) -> Dict[str, Any]:
        session = self._get_rule_selection_session(instance_ref, back_page=back_page, page=page)
        current = {str(item).strip() for item in list(session.get("rule_keys", []) or []) if str(item).strip()}
        rule_key = str(rule_key).strip()
        if rule_key in current:
            current.remove(rule_key)
        else:
            current.add(rule_key)
        session["rule_keys"] = sorted(current)
        self.rule_selection_sessions[self._selection_session_key(instance_ref, back_page, page)] = session
        return dict(session)

    def build_ingress_rules_keyboard(self, instance_id: str, back_page: int = 1, page: int = 1, temp_only: bool = False) -> Dict[str, Any]:
        self._remember_instance_like(instance_id)
        instance_token = self._register_callback_ref(instance_id, "i")
        page_token = self._build_instance_page_token(back_page)
        mode = "temp" if temp_only else "all"
        selection_session = self._get_rule_selection_session(instance_id, back_page=back_page, page=page)
        selected_rule_keys = {str(item).strip() for item in list(selection_session.get("rule_keys", []) or []) if str(item).strip()}
        data = get_instance_ingress_rules_data(instance_id, self.app_config, page=page, temp_only=temp_only)
        data["selected_rule_keys"] = sorted(selected_rule_keys)
        pagination = data["pagination"]
        rows: List[List[Dict[str, str]]] = []
        nav_row: List[Dict[str, str]] = []
        if pagination["has_prev"]:
            nav_row.append({"text": "⬅️ 上一页", "callback_data": f"netsec:rules:{instance_token}:{page_token}:{mode}:{pagination['page'] - 1}"})
        nav_row.append({"text": f"📄 {pagination['page']}/{pagination['total_pages']}", "callback_data": f"netsec:rules:{instance_token}:{page_token}:{mode}:{pagination['page']}"})
        if pagination["has_next"]:
            nav_row.append({"text": "下一页 ➡️", "callback_data": f"netsec:rules:{instance_token}:{page_token}:{mode}:{pagination['page'] + 1}"})
        if nav_row:
            rows.append(nav_row)
        rows.append([
            {"text": "🛡️ 全部规则" if temp_only else "🧪 仅临时规则", "callback_data": f"netsec:rules:{instance_token}:{page_token}:{'all' if temp_only else 'temp'}:1"},
        ])
        if temp_only and data.get("items"):
            for item in data["items"][:6]:
                rule_key = str(item["rule_key"])
                checked = "✅" if rule_key in selected_rule_keys else "☑️"
                proto_port = f"{item['protocol']}/{item['port_text']}"
                source_short = str(item['source'])[:10]
                toggle_token = self._register_rule_selection(instance_id, [rule_key], back_page=back_page, page=page)
                rows.append([
                    {"text": f"{checked} {proto_port}"[:28], "callback_data": f"netsec:selecttoggle:{toggle_token}"},
                    {"text": f"{source_short}"[:18], "callback_data": f"netsec:selecttoggle:{toggle_token}"},
                ])
            action_row: List[Dict[str, str]] = []
            if selected_rule_keys:
                preview_token = self._register_rule_selection(instance_id, sorted(selected_rule_keys), back_page=back_page, page=page)
                action_row.append({"text": f"🧾 预览已选({len(selected_rule_keys)})", "callback_data": f"netsec:selectpreview:{preview_token}"})
                action_row.append({"text": "♻️ 清空本页", "callback_data": f"netsec:selectclear:{instance_token}:{page_token}:{page}"})
            if action_row:
                rows.append(action_row)
        rows.extend([
            [
                {"text": "⬅️ 返回网络/安全概览", "callback_data": f"instance:network:{instance_token}:{page_token}"},
            ],
            [
                {"text": "⬅️ 返回实例详情", "callback_data": f"instance:detail:{instance_token}:{page_token}"},
                {"text": "🏠 返回主菜单", "callback_data": "menu:home"},
            ],
        ])
        return build_inline_keyboard(rows)

    def _resolve_netsec_flow(self, token: str) -> Dict[str, Any]:
        return self._resolve_callback_state(self.netsec_flow_refs, token, "网络/安全会话已失效，请重新进入该流程")

    def build_netsec_preview_keyboard(self, action: str, instance_ref: str, port: str, source_cidr: str, back_page: int = 1) -> Dict[str, Any]:
        self._remember_instance_like(instance_ref)
        allowed_ports = {int(item) for item in self.network_runtime.get("quick_open_allowed_tcp_ports", [])}
        is_custom_port = int(port) not in allowed_ports
        action_label = ("⚠️ 二次确认放行" if is_custom_port and action == "open" else "✅ 确认放行") if action == "open" else ("⚠️ 二次确认清理" if is_custom_port else "✅ 确认清理")
        action_icon = "✅" if action == "open" else "🧹"
        flow_token = self._register_netsec_flow(action, instance_ref, str(port), source_cidr, back_page)
        return build_inline_keyboard([
            [
                {"text": f"{action_icon} {action_label}", "callback_data": f"netsec:apply:{flow_token}"},
            ],
            [
                {"text": "✍️ 重填 CIDR", "callback_data": f"nav:{self._register_nav_flow('netsec_cidrask', action=action, instance_ref=instance_ref, port=str(port), back_page=back_page)}"},
                {"text": "✍️ 改端口", "callback_data": f"netsec:ports:{action}:{self._register_callback_ref(instance_ref, 'i')}:{self._build_instance_page_token(back_page)}"},
            ],
            [
                {"text": "⬅️ 返回网络/安全概览", "callback_data": f"instance:network:{self._register_callback_ref(instance_ref, 'i')}:{self._build_instance_page_token(back_page)}"},
            ],
            [
                {"text": "⬅️ 返回实例详情", "callback_data": f"instance:detail:{self._register_callback_ref(instance_ref, 'i')}:{self._build_instance_page_token(back_page)}"},
                {"text": "🏠 返回主菜单", "callback_data": "menu:home"},
            ],
        ])

    def build_netsec_result_keyboard(self, instance_id: str, back_page: int = 1, refresh_temp_page: Optional[int] = None) -> Dict[str, Any]:
        self._remember_instance_like(instance_id)
        instance_token = self._register_callback_ref(instance_id, "i")
        page_token = self._build_instance_page_token(back_page)
        rows = []
        if refresh_temp_page is not None:
            rows.append([
                {"text": "🧪 返回临时规则管理并刷新", "callback_data": f"netsec:rules:{instance_token}:{page_token}:temp:{int(refresh_temp_page)}"},
            ])
        rows.extend([
            [
                {"text": "⬅️ 返回网络/安全概览", "callback_data": f"instance:network:{instance_token}:{page_token}"},
                {"text": "⬅️ 返回实例详情", "callback_data": f"instance:detail:{instance_token}:{page_token}"},
            ],
            [
                {"text": "⬅️ 返回实例列表", "callback_data": f"menu:instances:{page_token}"},
                {"text": "🏠 返回主菜单", "callback_data": "menu:home"},
            ],
        ])
        return build_inline_keyboard(rows)

    def handle_command(self, text: str) -> str:
        normalized = (text or "").strip()
        if not normalized:
            return "未收到命令内容。"

        if normalized.startswith("/start"):
            return (
                "<b>👋 欢迎使用 OCI Master Telegram Bot！</b>\n"
                "使用 /menu 查看可用命令。"
            )
        if normalized.startswith("/help") or normalized.startswith("/menu"):
            return self.build_help_text()
        if normalized.startswith("/user_info"):
            return render_user_info_telegram(get_user_info_data(self.app_config))
        if normalized.startswith("/usage_fee"):
            report_data = get_usage_fee_report_data(self.app_config)
            return render_usage_fee_telegram(report_data, show_all=False)
        if normalized.startswith("/regions") or normalized.startswith("/region_subscriptions"):
            return render_region_subscriptions_telegram(get_region_subscriptions_data(self.app_config))
        if normalized.startswith("/bucket_info"):
            return render_bucket_info_telegram(get_bucket_info_data(self.app_config))
        if normalized.startswith("/audit_events"):
            parts = normalized.split(maxsplit=1)
            limit = 10
            if len(parts) > 1:
                try:
                    limit = min(max(1, int(parts[1].strip())), 50)
                except Exception:
                    pass
            return render_audit_events_telegram(get_audit_events_data(self.app_config, limit=limit), limit=limit)
        if normalized.startswith("/policies"):
            return render_policy_home_text()
        if normalized.startswith("/create_safe_policy"):
            return capture_output(create_safe_policy, self.app_config, True)
        if normalized.startswith("/delete_policy"):
            parts = normalized.split(maxsplit=1)
            if len(parts) < 2:
                return "请提供要删除的策略名称，例如：<code>/delete_policy NeverExpireStandard</code>"
            target = parts[1].strip()
            token = self._register_dangerous_action("delete_policy", target)
            return self._dangerous_confirmation_text("delete_policy", target)
        if normalized.startswith("/instances"):
            return render_instances_telegram(list_instances_data(self.app_config), page=1, page_size=self.instance_page_size)
        if normalized.startswith("/instance_detail"):
            instance_ref = self._extract_tail_argument(normalized)
            if not instance_ref:
                return "请提供实例名称或 OCID，例如：<code>/instance_detail my-vm</code>"
            return render_instance_detail_telegram(get_instance_detail_data(instance_ref, self.app_config))
        if normalized.startswith("/instance_start"):
            instance_ref = self._extract_tail_argument(normalized)
            if not instance_ref:
                return "请提供实例名称或 OCID，例如：<code>/instance_start my-vm</code>"
            return render_instance_action_telegram(execute_instance_action_data("start", instance_ref, self.app_config))
        if normalized.startswith("/instance_stop"):
            instance_ref = self._extract_tail_argument(normalized)
            if not instance_ref:
                return "请提供实例名称或 OCID，例如：<code>/instance_stop my-vm</code>"
            self._register_dangerous_action("instance_stop", instance_ref)
            return self._dangerous_confirmation_text("instance_stop", instance_ref)
        if normalized.startswith("/instance_restart"):
            instance_ref = self._extract_tail_argument(normalized)
            if not instance_ref:
                return "请提供实例名称或 OCID，例如：<code>/instance_restart my-vm</code>"
            self._register_dangerous_action("instance_restart", instance_ref)
            return self._dangerous_confirmation_text("instance_restart", instance_ref)
        if normalized.startswith("/instance_network"):
            instance_ref = self._extract_tail_argument(normalized)
            if not instance_ref:
                return "请提供实例名称或 OCID，例如：<code>/instance_network my-vm</code>"
            return render_instance_network_overview_telegram(get_instance_network_overview_data(instance_ref, self.app_config))
        if normalized.startswith("/instance_rules"):
            instance_ref = self._extract_tail_argument(normalized)
            if not instance_ref:
                return "请提供实例名称或 OCID，例如：<code>/instance_rules my-vm</code>"
            return render_instance_ingress_rules_telegram(get_instance_ingress_rules_data(instance_ref, self.app_config, page=1, temp_only=False))
        if normalized.startswith("/instance_temp_rules"):
            instance_ref = self._extract_tail_argument(normalized)
            if not instance_ref:
                return "请提供实例名称或 OCID，例如：<code>/instance_temp_rules my-vm</code>"
            return render_instance_ingress_rules_telegram(get_instance_ingress_rules_data(instance_ref, self.app_config, page=1, temp_only=True))
        if normalized.startswith("/netsec_open"):
            parts = normalized.split(maxsplit=3)
            if len(parts) < 4:
                return "用法：<code>/netsec_open 实例名 22 1.2.3.4/32</code>"
            return render_open_ingress_preview_telegram(preview_open_ingress_rule_data(parts[1], parts[2], parts[3], self.app_config))
        if normalized.startswith("/netsec_close_temp"):
            parts = normalized.split(maxsplit=3)
            if len(parts) < 4:
                return "用法：<code>/netsec_close_temp 实例名 22 1.2.3.4/32</code>"
            return render_cleanup_preview_telegram(preview_cleanup_temp_rules_data(parts[1], parts[2], parts[3], self.app_config))
        if normalized.startswith("/run"):
            parts = normalized.split(maxsplit=1)
            if len(parts) < 2:
                return "请提供 action，例如：<code>/run user_info</code>"
            return self.handle_run_action(parts[1].strip())
        return "<b>❌ 不支持的命令</b>\n请先看下面的可用菜单：\n\n" + self.build_help_text()

    def _extract_tail_argument(self, normalized: str) -> str:
        parts = normalized.split(maxsplit=1)
        return parts[1].strip() if len(parts) > 1 else ""

    def handle_run_action(self, action: str) -> str:
        action_name, args = parse_action(action)
        action = action_name if not args else ":".join((action_name, *args))
        if action == "user_info":
            return render_user_info_telegram(get_user_info_data(self.app_config))
        if action == "usage_fee":
            report_data = get_usage_fee_report_data(self.app_config)
            return render_usage_fee_telegram(report_data, show_all=False)
        if action == "region_subscriptions":
            return render_region_subscriptions_telegram(get_region_subscriptions_data(self.app_config))
        if action == "bucket_info":
            return render_bucket_info_telegram(get_bucket_info_data(self.app_config))
        if action == "audit_events":
            return render_audit_events_telegram(get_audit_events_data(self.app_config, limit=10), limit=10)
        if action.startswith("audit_events:"):
            limit_text = action.split(":", 1)[1].strip() or "10"
            try:
                limit = min(max(1, int(limit_text)), 50)
            except Exception:
                return "audit_events 动作的数量参数必须是整数，例如 <code>audit_events:10</code>"
            return render_audit_events_telegram(get_audit_events_data(self.app_config, limit=limit), limit=limit)
        if action == "policies":
            return render_policies_telegram(list_policies_data(self.app_config))
        if action == "create_safe_policy":
            return capture_output(create_safe_policy, self.app_config, True)
        if action == "list_instances":
            return render_instances_telegram(list_instances_data(self.app_config), page=1, page_size=self.instance_page_size)
        if action.startswith("delete_policy:"):
            policy_name = action.split(":", 1)[1].strip()
            if not policy_name:
                return "delete_policy 动作必须附带策略名，例如 <code>delete_policy:NeverExpireStandard</code>"
            return capture_output(delete_policy, self.app_config, policy_name, True)
        if action.startswith("instance_detail:"):
            instance_ref = action.split(":", 1)[1].strip()
            if not instance_ref:
                return "instance_detail 动作必须附带实例名或 OCID"
            return render_instance_detail_telegram(get_instance_detail_data(instance_ref, self.app_config))
        for name in ("instance_start", "instance_stop", "instance_restart"):
            prefix = f"{name}:"
            if action.startswith(prefix):
                instance_ref = action.split(":", 1)[1].strip()
                if not instance_ref:
                    return f"{name} 动作必须附带实例名或 OCID"
                verb = name.split("_", 1)[1]
                return render_instance_action_telegram(execute_instance_action_data(verb, instance_ref, self.app_config))
        if action.startswith("instance_network:"):
            instance_ref = action.split(":", 1)[1].strip()
            if not instance_ref:
                return "instance_network 动作必须附带实例名或 OCID"
            return render_instance_network_overview_telegram(get_instance_network_overview_data(instance_ref, self.app_config))
        if action.startswith("instance_rules:"):
            instance_ref = action.split(":", 1)[1].strip()
            if not instance_ref:
                return "instance_rules 动作必须附带实例名或 OCID"
            return render_instance_ingress_rules_telegram(get_instance_ingress_rules_data(instance_ref, self.app_config, page=1, temp_only=False))
        if action.startswith("instance_temp_rules:"):
            instance_ref = action.split(":", 1)[1].strip()
            if not instance_ref:
                return "instance_temp_rules 动作必须附带实例名或 OCID"
            return render_instance_ingress_rules_telegram(get_instance_ingress_rules_data(instance_ref, self.app_config, page=1, temp_only=True))
        if action.startswith("open_ingress_preview:"):
            parts = action.split(":", 3)
            if len(parts) < 4:
                return "open_ingress_preview 动作必须附带 实例/端口/CIDR"
            return render_open_ingress_preview_telegram(preview_open_ingress_rule_data(parts[1], parts[2], parts[3], self.app_config))
        if action.startswith("open_ingress_apply:"):
            parts = action.split(":", 3)
            if len(parts) < 4:
                return "open_ingress_apply 动作必须附带 实例/端口/CIDR"
            return render_open_ingress_result_telegram(apply_open_ingress_rule_data(parts[1], parts[2], parts[3], self.app_config))
        if action.startswith("cleanup_temp_rules_preview:"):
            parts = action.split(":", 3)
            if len(parts) < 4:
                return "cleanup_temp_rules_preview 动作必须附带 实例/端口/CIDR"
            return render_cleanup_preview_telegram(preview_cleanup_temp_rules_data(parts[1], parts[2], parts[3], self.app_config))
        if action.startswith("cleanup_temp_rules_apply:"):
            parts = action.split(":", 3)
            if len(parts) < 4:
                return "cleanup_temp_rules_apply 动作必须附带 实例/端口/CIDR"
            return render_cleanup_result_telegram(apply_cleanup_temp_rules_data(parts[1], parts[2], parts[3], self.app_config))
        return (
            "<b>❌ 未知 action</b>\n"
            "可选：<code>user_info</code>、<code>usage_fee</code>、<code>region_subscriptions</code>、<code>bucket_info</code>、<code>audit_events[:10]</code>、<code>policies</code>、"
            "<code>create_safe_policy</code>、<code>delete_policy:&lt;名称&gt;</code>、"
            "<code>list_instances</code>、<code>instance_detail:&lt;实例&gt;</code>、"
            "<code>instance_start:&lt;实例&gt;</code>、<code>instance_stop:&lt;实例&gt;</code>、"
            "<code>instance_restart:&lt;实例&gt;</code>、<code>instance_network:&lt;实例&gt;</code>、"
            "<code>open_ingress_preview:&lt;实例&gt;:&lt;端口&gt;:&lt;CIDR&gt;</code>、"
            "<code>open_ingress_apply:&lt;实例&gt;:&lt;端口&gt;:&lt;CIDR&gt;</code>、"
            "<code>cleanup_temp_rules_preview:&lt;实例&gt;:&lt;端口&gt;:&lt;CIDR&gt;</code>、"
            "<code>cleanup_temp_rules_apply:&lt;实例&gt;:&lt;端口&gt;:&lt;CIDR&gt;</code>"
        )

    def _route_menu_callback(self, data: str) -> tuple[str, Optional[Dict[str, Any]]]:
        if data == "menu:home":
            return self.build_start_card_text(), self.build_main_menu_keyboard()
        if data == "menu:help":
            return self.build_help_text(), self.build_main_menu_keyboard()
        if data == "menu:user_info":
            return render_user_info_telegram(get_user_info_data(self.app_config)), self.build_main_menu_keyboard()
        if data == "menu:usage_fee":
            report_data = get_usage_fee_report_data(self.app_config)
            return render_usage_fee_telegram(report_data, show_all=False), self.build_usage_fee_keyboard(False, len(report_data["unique_dates"]), report_data["display_days"])
        if data == "menu:policies":
            return render_policy_home_text(), build_policy_menu_keyboard()
        if data == "menu:regions":
            return render_region_subscriptions_telegram(get_region_subscriptions_data(self.app_config)), self.build_main_menu_keyboard()
        if data == "menu:buckets":
            return render_bucket_info_telegram(get_bucket_info_data(self.app_config)), self.build_main_menu_keyboard()
        if data == "menu:audit":
            return render_audit_events_telegram(get_audit_events_data(self.app_config, limit=10), limit=10), self.build_main_menu_keyboard()
        if data == "menu:netsec_help":
            return (
                "<b>🌐 网络 / 安全入口</b>\n"
                "<blockquote>这条线已经接进来了，只是需要先选实例。</blockquote>\n"
                "<b>推荐入口</b>\n"
                "• 先点 <b>🖥️ 实例列表</b>，再进某台实例的 <b>🌐 网络/安全</b>\n"
                "• 或直接用命令：<code>/instance_network 实例名</code>\n\n"
                "<b>快捷命令</b>\n"
                "<code>/netsec_open 实例 端口 CIDR</code>\n"
                "<code>/netsec_close_temp 实例 端口 CIDR</code>",
                build_inline_keyboard([
                    [{"text": "🖥️ 去实例列表", "callback_data": f"menu:instances:{self._build_instance_page_token(1)}"}],
                    [{"text": "🏠 返回主菜单", "callback_data": "menu:home"}],
                ]),
            )
        if data.startswith("menu:instances"):
            page = 1
            parts = data.split(":", 2)
            if len(parts) >= 3:
                page = self._resolve_instance_page(parts[2])
            instance_data = list_instances_data(self.app_config)
            return render_instances_telegram(instance_data, page=page, page_size=self.instance_page_size), self.build_instances_keyboard(instance_data, page=page)
        raise ValueError("未知菜单操作")

    def build_start_card_text(self) -> str:
        return (
            "<b>👋 欢迎使用 OCI Master Telegram Bot！</b>\n"
            "<b>🚀 快速入口</b>\n"
            "• <code>/menu</code> 查看完整菜单\n"
            "• <code>/policies</code> 进入密码策略菜单\n"
            "• <code>/instances</code> 查看实例列表\n"
            "• <code>/usage_fee</code> 查看本月账单"
        )

    def _handle_policy_callback(self, chat_id: str, user_id: str, data: str) -> tuple[str, Optional[Dict[str, Any]], Optional[str]]:
        state = self._get_menu_state(chat_id, user_id)

        if data == "pm:home":
            self._clear_menu_state(chat_id, user_id)
            return render_policy_home_text(), build_policy_menu_keyboard(), "已返回策略菜单"
        if data == "pm:view":
            policy_data = list_policies_data(self.app_config)
            return render_policies_telegram(policy_data), build_policy_list_keyboard(policy_data), "已刷新策略列表"
        if data == "pm:create":
            self._set_menu_state(chat_id, user_id, {"step": "create_wait_name"})
            return render_policy_create_name_prompt(), build_inline_keyboard([[{"text": "🏠 返回主菜单", "callback_data": "menu:home"}]]), "请发送策略名称"
        if data == "pm:create:back_to_days":
            policy_name = str(state.get("policy_name", ""))
            return render_policy_create_days_prompt(policy_name), build_policy_days_keyboard(), "已返回上一步"
        if data.startswith("pm:create:days:"):
            value = data.split(":")[-1]
            if value == "custom":
                state["step"] = "create_wait_days_custom"
                self._set_menu_state(chat_id, user_id, state)
                return (
                    "<b>✍️ 自定义过期天数</b>\n\n请直接发送数字，例如：<code>45</code>",
                    build_inline_keyboard([[{"text": "⬅️ 返回上一步", "callback_data": "pm:create:back_to_days"}, {"text": "🏠 主菜单", "callback_data": "menu:home"}]]),
                    "请发送过期天数",
                )
            ok, days, error = validate_expires_days(value)
            if not ok:
                raise ValueError(error)
            policy_name = str(state.get("policy_name", ""))
            state["expires_days"] = days
            state["step"] = "create_confirm"
            self._set_menu_state(chat_id, user_id, state)
            return render_policy_create_confirm(policy_name, days), build_policy_create_confirm_keyboard(days), "请确认创建"
        if data.startswith("pm:create:confirm:"):
            expires_days = int(data.split(":")[-1])
            policy_name = str(state.get("policy_name", ""))
            result = create_policy_data(policy_name, expires_days, self.app_config)
            self._clear_menu_state(chat_id, user_id)
            return render_policy_action_telegram(result), build_policy_post_action_keyboard(), "策略已创建"
        if data == "pm:delete":
            policy_data = list_policies_data(self.app_config)
            return render_policy_delete_picker(policy_data), build_policy_list_keyboard(policy_data), "请选择要删除的策略"
        if data.startswith("pm:delete:pick:"):
            policy_name = data.split(":", 3)[3]
            return render_policy_delete_confirm(policy_name, self.app_config), build_policy_delete_confirm_keyboard(policy_name), "请确认删除"
        if data.startswith("pm:delete:confirm:"):
            policy_name = data.split(":", 3)[3]
            result = delete_policy_data(policy_name, self.app_config)
            self._clear_menu_state(chat_id, user_id)
            return render_policy_action_telegram(result), build_policy_post_action_keyboard(), "策略已删除"

        raise ValueError("未知策略菜单操作")

    def _handle_usage_fee_callback(self, callback_query_id: str, chat_id: str, message_id: int, data: str) -> bool:
        """Render the usage-fee expansion/collapse callbacks."""
        if data not in {"usage_fee:expand", "usage_fee:collapse"}:
            return False
        report_data = get_usage_fee_report_data(self.app_config)
        show_all = data == "usage_fee:expand"
        text = render_usage_fee_telegram(report_data, show_all=show_all)
        keyboard = self.build_usage_fee_keyboard(show_all, len(report_data["unique_dates"]), report_data["display_days"])
        self.edit_message_text(chat_id=chat_id, message_id=message_id, text=text, parse_mode="HTML", reply_markup=keyboard)
        self.answer_callback_query(callback_query_id, "已更新显示内容")
        return True

    def _handle_menu_callback(self, callback_query_id: str, chat_id: str, message_id: int, data: str) -> bool:
        """Render menu callbacks while keeping callback acknowledgement at the route boundary."""
        if not data.startswith("menu:"):
            return False
        text, keyboard = self._route_menu_callback(data)
        self.edit_message_text(chat_id=chat_id, message_id=message_id, text=text, parse_mode="HTML", reply_markup=keyboard)
        self.answer_callback_query(callback_query_id, "已切换菜单")
        return True

    def handle_callback_query(self, callback_query: Dict[str, Any]) -> None:
        callback_query_id = str(callback_query.get("id", ""))
        data = str(callback_query.get("data", ""))
        message = callback_query.get("message") or {}
        chat = message.get("chat") or {}
        chat_id = str(chat.get("id", ""))
        message_id = int(message.get("message_id", 0) or 0)
        from_user = callback_query.get("from") or {}
        user_id = str(from_user.get("id", ""))

        pseudo_message = {"chat": chat, "from": from_user}
        if not self.is_authorized(pseudo_message):
            self.answer_callback_query(callback_query_id, "未授权操作")
            return

        try:
            if registry.dispatch_telegram_callback(
                self, data, chat_id, user_id, str(message_id), callback_query_id
            ):
                return

            if self._handle_usage_fee_callback(callback_query_id, chat_id, message_id, data):
                return

            if self._handle_menu_callback(callback_query_id, chat_id, message_id, data):
                return

            if data.startswith("pm:"):
                text, keyboard, notice = self._handle_policy_callback(chat_id, user_id, data)
                self.edit_message_text(chat_id=chat_id, message_id=message_id, text=text, parse_mode="HTML", reply_markup=keyboard)
                self.answer_callback_query(callback_query_id, notice or "已更新")
                return

            if data.startswith("danger:confirm:"):
                action = self._consume_callback_state(
                    self.dangerous_action_refs,
                    data.split(":", 2)[2],
                    "确认会话已失效，请重新发送命令",
                )
                target = str(action["target"])
                if action["action"] == "delete_policy":
                    result = delete_policy_data(target, self.app_config)
                    text = render_policy_action_telegram(result)
                    notice = "策略已删除"
                else:
                    verb = str(action["action"]).split("_", 1)[1]
                    result = execute_instance_action_data(verb, target, self.app_config)
                    self._remember_instance_like(result["id"], str(result.get("display_name", "")))
                    text = render_instance_action_telegram(result)
                    notice = f"已提交{verb}操作"
                self.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=text,
                    parse_mode="HTML",
                    reply_markup=self.build_main_menu_keyboard(),
                )
                self.answer_callback_query(callback_query_id, notice)
                return

            if data.startswith("instance:detail:"):
                parts = data.split(":")
                instance_ref = self._resolve_callback_ref(parts[2])
                back_page = self._resolve_instance_page(parts[3]) if len(parts) > 3 else 1
                detail = get_instance_detail_data(instance_ref, self.app_config)
                self._remember_instance_like(detail)
                self.edit_message_text(chat_id=chat_id, message_id=message_id, text=render_instance_detail_telegram(detail), parse_mode="HTML", reply_markup=self.build_instance_detail_keyboard(detail, back_page=back_page))
                self.answer_callback_query(callback_query_id, "已打开实例详情")
                return

            if data.startswith("nav:"):
                flow = self._resolve_nav_flow(data.split(":", 1)[1])
                kind = str(flow.get("kind", ""))
                if kind == "network_more":
                    instance_ref = str(flow["instance_ref"])
                    back_page = int(flow.get("back_page", 1) or 1)
                    detail_page = int(flow.get("detail_page", 1) or 1)
                    overview = get_instance_network_overview_data(instance_ref, self.app_config)
                    detail_meta = get_instance_network_detail_pages(overview)
                    total_pages = int(detail_meta.get("total_pages", 1) or 1)
                    detail_page = min(max(1, detail_page), total_pages)
                    self._remember_instance_like(overview["instance"])
                    prev_token = self._register_nav_flow("network_more", instance_ref=str(overview["instance"]["id"]), back_page=back_page, detail_page=detail_page - 1)
                    cur_token = self._register_nav_flow("network_more", instance_ref=str(overview["instance"]["id"]), back_page=back_page, detail_page=detail_page)
                    next_token = self._register_nav_flow("network_more", instance_ref=str(overview["instance"]["id"]), back_page=back_page, detail_page=detail_page + 1)
                    instance_token = self._register_callback_ref(str(overview["instance"]["id"]), "i")
                    page_token = self._build_instance_page_token(back_page)
                    nav_row = []
                    if detail_page > 1:
                        nav_row.append({"text": "⬅️ 上一段", "callback_data": f"nav:{prev_token}"})
                    nav_row.append({"text": f"📄 {detail_page}/{total_pages}", "callback_data": f"nav:{cur_token}"})
                    if detail_page < total_pages:
                        nav_row.append({"text": "下一段 ➡️", "callback_data": f"nav:{next_token}"})
                    keyboard_rows = []
                    if nav_row:
                        keyboard_rows.append(nav_row)
                    keyboard_rows.extend([
                        [{"text": "⬅️ 收起回概览", "callback_data": f"instance:network:{instance_token}:{page_token}"}],
                        [{"text": "🔓 放行临时端口", "callback_data": f"netsec:ports:open:{instance_token}:{page_token}"}, {"text": "🧹 清理临时规则", "callback_data": f"netsec:ports:cleanup:{instance_token}:{page_token}"}],
                        [{"text": "⬅️ 返回实例详情", "callback_data": f"instance:detail:{instance_token}:{page_token}"}, {"text": "⬅️ 返回实例列表", "callback_data": f"menu:instances:{page_token}"}],
                        [{"text": "🏠 返回主菜单", "callback_data": "menu:home"}],
                    ])
                    self.edit_message_text(
                        chat_id=chat_id,
                        message_id=message_id,
                        text=render_instance_network_details_telegram(overview, page=detail_page),
                        parse_mode="HTML",
                        reply_markup=build_inline_keyboard(keyboard_rows),
                    )
                    self.answer_callback_query(callback_query_id, f"已切到明细 {detail_page}/{total_pages}")
                    return
                if kind == "netsec_cidr":
                    action = str(flow["action"])
                    instance_ref = str(flow["instance_ref"])
                    port = str(flow["port"])
                    back_page = int(flow.get("back_page", 1) or 1)
                    self.edit_message_text(
                        chat_id=chat_id,
                        message_id=message_id,
                        text=(
                            f"<b>{'🌍' if action == 'open' else '🧭'} 网络 / 安全向导</b>\n"
                            f"<b>{'放行临时端口' if action == 'open' else '清理临时规则'} · 选择来源 CIDR</b>\n"
                            f"<blockquote>实例：{self._format_instance_badge(instance_ref)}\n端口：<code>TCP/{html.escape(str(port))}</code></blockquote>\n"
                            "🧭 当前步骤：选择默认值，或切到输入态自行发送 CIDR。\n"
                            f"⚡ 默认 CIDR：<code>{html.escape(str(self.network_runtime.get('default_source_cidr', '0.0.0.0/0')))}</code>"
                        ),
                        parse_mode="HTML",
                        reply_markup=self.build_netsec_cidr_keyboard(action, instance_ref, str(port), back_page=back_page),
                    )
                    self.answer_callback_query(callback_query_id, "请选择 CIDR")
                    return
                if kind == "netsec_portask":
                    action = str(flow["action"])
                    instance_ref = str(flow["instance_ref"])
                    back_page = int(flow.get("back_page", 1) or 1)
                    self._set_menu_state(chat_id, user_id, {
                        "step": "netsec_wait_port",
                        "netsec_action": action,
                        "instance_ref": instance_ref,
                        "instance_display_name": self._get_instance_display_name(instance_ref),
                        "back_page": back_page,
                        "prompt_message_id": message_id,
                    })
                    self.edit_message_text(
                        chat_id=chat_id,
                        message_id=message_id,
                        text=(
                            f"<b>✍️ 网络 / 安全向导</b>\n"
                            f"<b>输入自定义端口</b>\n"
                            f"<blockquote>动作：<code>{html.escape('放行临时端口' if action == 'open' else '清理临时规则')}</code>\n"
                            f"实例：{self._format_instance_badge(instance_ref)}</blockquote>\n"
                            "🧭 当前步骤：直接发送一个 TCP 端口，例如 <code>25565</code>\n"
                            f"📦 快捷端口：<code>{', '.join(str(int(p)) for p in self.network_runtime.get('quick_open_allowed_tcp_ports', []))}</code>\n"
                            "⚠️ 仅支持单个 TCP 端口，范围 1-65535；不会扩到端口段、UDP、路由或子网改动。"
                        ),
                        parse_mode="HTML",
                        reply_markup=self._build_netsec_waiting_keyboard(action, instance_ref, "0", back_page=back_page, mode="port"),
                    )
                    self.answer_callback_query(callback_query_id, "请发送端口")
                    return
                if kind == "netsec_cidrask":
                    action = str(flow["action"])
                    instance_ref = str(flow["instance_ref"])
                    port = str(flow["port"])
                    back_page = int(flow.get("back_page", 1) or 1)
                    self._set_menu_state(chat_id, user_id, {
                        "step": "netsec_wait_cidr",
                        "netsec_action": action,
                        "instance_ref": instance_ref,
                        "instance_display_name": self._get_instance_display_name(instance_ref),
                        "port": str(port),
                        "back_page": back_page,
                        "prompt_message_id": message_id,
                    })
                    self.edit_message_text(
                        chat_id=chat_id,
                        message_id=message_id,
                        text=(
                            f"<b>✍️ 网络 / 安全向导</b>\n"
                            f"<b>输入自定义 CIDR</b>\n"
                            f"<blockquote>动作：<code>{html.escape('放行临时端口' if action == 'open' else '清理临时规则')}</code>\n"
                            f"实例：{self._format_instance_badge(instance_ref)}\n端口：<code>TCP/{html.escape(str(port))}</code></blockquote>\n"
                            f"🧭 当前步骤：直接发送一条 CIDR 消息，例如 <code>1.2.3.4/32</code>\n"
                            f"⚡ 默认值：<code>{html.escape(str(self.network_runtime.get('default_source_cidr', '0.0.0.0/0')))}</code>\n"
                            "💡 你发来后，我会尽量接着这张卡片往下走。\n"
                            "⚠️ 这一页只记录输入，不会自动提交规则。"
                        ),
                        parse_mode="HTML",
                        reply_markup=self._build_netsec_waiting_keyboard(action, instance_ref, str(port), back_page=back_page),
                    )
                    self.answer_callback_query(callback_query_id, "请发送 CIDR")
                    return
                raise ValueError("未知导航操作")

            if data.startswith("instance:network:more:"):
                parts = data.split(":")
                instance_ref = self._resolve_callback_ref(parts[3])
                back_page = self._resolve_instance_page(parts[4]) if len(parts) > 4 else 1
                detail_page = int(self._resolve_callback_ref(parts[5])) if len(parts) > 5 else 1
                overview = get_instance_network_overview_data(instance_ref, self.app_config)
                detail_meta = get_instance_network_detail_pages(overview)
                total_pages = int(detail_meta.get("total_pages", 1) or 1)
                detail_page = min(max(1, detail_page), total_pages)
                self._remember_instance_like(overview["instance"])
                instance_token = self._register_callback_ref(str(overview["instance"]["id"]), "i")
                page_token = self._build_instance_page_token(back_page)
                nav_row = []
                if detail_page > 1:
                    nav_row.append({"text": "⬅️ 上一段", "callback_data": f"instance:network:more:{instance_token}:{page_token}:{self._register_callback_ref(str(detail_page - 1), 'ndp')}"})
                nav_row.append({"text": f"📄 {detail_page}/{total_pages}", "callback_data": f"instance:network:more:{instance_token}:{page_token}:{self._register_callback_ref(str(detail_page), 'ndp')}"})
                if detail_page < total_pages:
                    nav_row.append({"text": "下一段 ➡️", "callback_data": f"instance:network:more:{instance_token}:{page_token}:{self._register_callback_ref(str(detail_page + 1), 'ndp')}"})
                keyboard_rows = []
                if nav_row:
                    keyboard_rows.append(nav_row)
                keyboard_rows.extend([
                    [{"text": "⬅️ 收起回概览", "callback_data": f"instance:network:{instance_token}:{page_token}"}],
                    [{"text": "🔓 放行临时端口", "callback_data": f"netsec:ports:open:{instance_token}:{page_token}"}, {"text": "🧹 清理临时规则", "callback_data": f"netsec:ports:cleanup:{instance_token}:{page_token}"}],
                    [{"text": "⬅️ 返回实例详情", "callback_data": f"instance:detail:{instance_token}:{page_token}"}, {"text": "⬅️ 返回实例列表", "callback_data": f"menu:instances:{page_token}"}],
                    [{"text": "🏠 返回主菜单", "callback_data": "menu:home"}],
                ])
                self.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=render_instance_network_details_telegram(overview, page=detail_page),
                    parse_mode="HTML",
                    reply_markup=build_inline_keyboard(keyboard_rows),
                )
                self.answer_callback_query(callback_query_id, f"已切到明细 {detail_page}/{total_pages}")
                return

            if data.startswith("instance:network:"):
                parts = data.split(":")
                instance_ref = self._resolve_callback_ref(parts[2])
                back_page = self._resolve_instance_page(parts[3]) if len(parts) > 3 else 1
                overview = get_instance_network_overview_data(instance_ref, self.app_config)
                self._remember_instance_like(overview["instance"])
                self.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=render_instance_network_overview_telegram(overview),
                    parse_mode="HTML",
                    reply_markup=self.build_instance_network_keyboard(str(overview["instance"]["id"]), back_page=back_page),
                )
                self.answer_callback_query(callback_query_id, "已打开网络/安全概览")
                return

            if data.startswith("netsec:rules:"):
                parts = data.split(":")
                instance_ref = self._resolve_callback_ref(parts[2])
                back_page = self._resolve_instance_page(parts[3]) if len(parts) > 3 else 1
                mode = parts[4] if len(parts) > 4 else "all"
                page = int(parts[5]) if len(parts) > 5 else 1
                temp_only = mode == "temp"
                rule_data = get_instance_ingress_rules_data(instance_ref, self.app_config, page=page, temp_only=temp_only)
                if temp_only:
                    selection_session = self._get_rule_selection_session(instance_ref, back_page=back_page, page=page)
                    rule_data["selected_rule_keys"] = list(selection_session.get("rule_keys", []) or [])
                self._remember_instance_like(rule_data["instance"])
                self.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=render_instance_ingress_rules_telegram(rule_data),
                    parse_mode="HTML",
                    reply_markup=self.build_ingress_rules_keyboard(str(rule_data["instance"]["id"]), back_page=back_page, page=rule_data["pagination"]["page"], temp_only=temp_only),
                )
                self.answer_callback_query(callback_query_id, "已打开规则列表")
                return

            if data.startswith("netsec:selecttoggle:"):
                selection = self._resolve_rule_selection(data.split(":", 2)[2])
                session = self._toggle_rule_selection(selection["instance_ref"], selection["rule_keys"][0], back_page=int(selection.get("back_page", 1) or 1), page=int(selection.get("page", 1) or 1))
                rule_data = get_instance_ingress_rules_data(selection["instance_ref"], self.app_config, page=int(session.get("page", 1) or 1), temp_only=True)
                rule_data["selected_rule_keys"] = list(session.get("rule_keys", []) or [])
                self._remember_instance_like(rule_data["instance"])
                self.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=render_instance_ingress_rules_telegram(rule_data),
                    parse_mode="HTML",
                    reply_markup=self.build_ingress_rules_keyboard(str(rule_data["instance"]["id"]), back_page=int(session.get("back_page", 1) or 1), page=rule_data["pagination"]["page"], temp_only=True),
                )
                self.answer_callback_query(callback_query_id, f"已选 {len(session.get('rule_keys', []) or [])} 条")
                return

            if data.startswith("netsec:selectclear:"):
                parts = data.split(":")
                instance_ref = self._resolve_callback_ref(parts[2])
                back_page = self._resolve_instance_page(parts[3]) if len(parts) > 3 else 1
                page = int(parts[4]) if len(parts) > 4 else 1
                self._clear_rule_selection_session(instance_ref, back_page=back_page, page=page)
                rule_data = get_instance_ingress_rules_data(instance_ref, self.app_config, page=page, temp_only=True)
                rule_data["selected_rule_keys"] = []
                self._remember_instance_like(rule_data["instance"])
                self.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=render_instance_ingress_rules_telegram(rule_data),
                    parse_mode="HTML",
                    reply_markup=self.build_ingress_rules_keyboard(str(rule_data["instance"]["id"]), back_page=back_page, page=rule_data["pagination"]["page"], temp_only=True),
                )
                self.answer_callback_query(callback_query_id, "已清空本页选择")
                return

            if data.startswith("netsec:selectpreview:"):
                selection = self._resolve_rule_selection(data.split(":", 2)[2])
                preview = preview_cleanup_selected_temp_rules_data(selection["instance_ref"], selection["rule_keys"], self.app_config)
                self._remember_instance_like(preview["instance"])
                instance_token = self._register_callback_ref(str(preview["instance"]["id"]), "i")
                page_token = self._build_instance_page_token(int(selection.get("back_page", 1) or 1))
                apply_token = self._register_rule_selection(selection["instance_ref"], selection["rule_keys"], back_page=int(selection.get("back_page", 1) or 1), page=int(selection.get("page", 1) or 1))
                self.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=render_cleanup_selected_preview_telegram(preview),
                    parse_mode="HTML",
                    reply_markup=build_inline_keyboard([
                        [{"text": "✅ 统一确认删除", "callback_data": f"netsec:selectapply:{apply_token}"}],
                        [{"text": "⬅️ 返回临时规则列表", "callback_data": f"netsec:rules:{instance_token}:{page_token}:temp:{int(selection.get('page', 1) or 1)}"}, {"text": "取消", "callback_data": f"netsec:rules:{instance_token}:{page_token}:temp:{int(selection.get('page', 1) or 1)}"}],
                        [{"text": "⬅️ 返回网络/安全概览", "callback_data": f"instance:network:{instance_token}:{page_token}"}, {"text": "🏠 返回主菜单", "callback_data": "menu:home"}],
                    ]),
                )
                self.answer_callback_query(callback_query_id, "已生成选择式清理预览")
                return

            if data.startswith("netsec:selectapply:"):
                selection = self._consume_callback_state(self.rule_select_refs, data.split(":", 2)[2], "规则选择会话已失效，请重新进入临时规则管理")
                result = apply_cleanup_selected_temp_rules_data(selection["instance_ref"], selection["rule_keys"], self.app_config)
                self._remember_instance_like(result["instance"])
                self._clear_rule_selection_session(selection["instance_ref"], back_page=int(selection.get("back_page", 1) or 1), page=int(selection.get("page", 1) or 1))
                self.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=render_cleanup_selected_result_telegram(result),
                    parse_mode="HTML",
                    reply_markup=self.build_netsec_result_keyboard(
                        str(result["instance"]["id"]),
                        back_page=int(selection.get("back_page", 1) or 1),
                        refresh_temp_page=int(selection.get("page", 1) or 1),
                    ),
                )
                self.answer_callback_query(callback_query_id, "已删除选中临时规则")
                return

            if data.startswith("netsec:ports:"):
                parts = data.split(":")
                action = parts[2]
                instance_ref = self._resolve_callback_ref(parts[3])
                back_page = self._resolve_instance_page(parts[4]) if len(parts) > 4 else 1
                action_title = "放行临时端口" if action == "open" else "清理临时规则"
                self.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=(
                        f"<b>{'🔓' if action == 'open' else '🧹'} 网络 / 安全向导</b>\n"
                        f"<b>{action_title} · 选择端口</b>\n"
                        f"<blockquote>实例：{self._format_instance_badge(instance_ref)}</blockquote>\n"
                        f"📦 快捷端口：<code>{', '.join(str(int(p)) for p in self.network_runtime.get('quick_open_allowed_tcp_ports', []))}</code>\n"
                        "🧭 当前步骤：先选端口，再选来源 CIDR，最后预览确认。\n"
                        "✍️ 也可以点“输入自定义端口”直接发单个 TCP 端口。\n"
                        "⚠️ 仍只支持低风险边界：单个 TCP 入站临时规则。"
                    ),
                    parse_mode="HTML",
                    reply_markup=self.build_netsec_port_keyboard(action, instance_ref, back_page=back_page),
                )
                self.answer_callback_query(callback_query_id, "请选择端口")
                return

            if data.startswith("netsec:cidr:"):
                parts = data.split(":")
                action = parts[2]
                instance_ref = self._resolve_callback_ref(parts[3])
                port = self._resolve_callback_ref(parts[4])
                back_page = self._resolve_instance_page(parts[5]) if len(parts) > 5 else 1
                action_title = "放行临时端口" if action == "open" else "清理临时规则"
                self.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=(
                        f"<b>{'🌍' if action == 'open' else '🧭'} 网络 / 安全向导</b>\n"
                        f"<b>{action_title} · 选择来源 CIDR</b>\n"
                        f"<blockquote>实例：{self._format_instance_badge(instance_ref)}\n端口：<code>TCP/{html.escape(str(port))}</code></blockquote>\n"
                        "🧭 当前步骤：选择默认值，或切到输入态自行发送 CIDR。\n"
                        f"⚡ 默认 CIDR：<code>{html.escape(str(self.network_runtime.get('default_source_cidr', '0.0.0.0/0')))}</code>"
                    ),
                    parse_mode="HTML",
                    reply_markup=self.build_netsec_cidr_keyboard(action, instance_ref, str(port), back_page=back_page),
                )
                self.answer_callback_query(callback_query_id, "请选择 CIDR")
                return

            if data.startswith("netsec:cidrask:"):
                parts = data.split(":")
                action = parts[2]
                instance_ref = self._resolve_callback_ref(parts[3])
                port = self._resolve_callback_ref(parts[4])
                back_page = self._resolve_instance_page(parts[5]) if len(parts) > 5 else 1
                self._set_menu_state(chat_id, user_id, {
                    "step": "netsec_wait_cidr",
                    "netsec_action": action,
                    "instance_ref": instance_ref,
                    "instance_display_name": self._get_instance_display_name(instance_ref),
                    "port": str(port),
                    "back_page": back_page,
                    "prompt_message_id": message_id,
                })
                self.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=(
                        f"<b>✍️ 网络 / 安全向导</b>\n"
                        f"<b>输入自定义 CIDR</b>\n"
                        f"<blockquote>动作：<code>{html.escape('放行临时端口' if action == 'open' else '清理临时规则')}</code>\n"
                        f"实例：{self._format_instance_badge(instance_ref)}\n端口：<code>TCP/{html.escape(str(port))}</code></blockquote>\n"
                        f"🧭 当前步骤：直接发送一条 CIDR 消息，例如 <code>1.2.3.4/32</code>\n"
                        f"⚡ 默认值：<code>{html.escape(str(self.network_runtime.get('default_source_cidr', '0.0.0.0/0')))}</code>\n"
                        "💡 你发来后，我会尽量接着这张卡片往下走。\n"
                        "⚠️ 这一页只记录输入，不会自动提交规则。"
                    ),
                    parse_mode="HTML",
                    reply_markup=self._build_netsec_waiting_keyboard(action, instance_ref, str(port), back_page=back_page),
                )
                self.answer_callback_query(callback_query_id, "请发送 CIDR")
                return

            if data.startswith("netsec:flowuse:"):
                flow = self._consume_callback_state(self.netsec_flow_refs, data.split(":", 2)[2], "网络/安全会话已失效，请重新进入该流程")
                action = str(flow["action"])
                instance_ref = str(flow["instance_ref"])
                port = str(flow["port"])
                source_cidr = str(flow["source_cidr"])
                back_page = int(flow.get("back_page", 1) or 1)
                self._clear_menu_state(chat_id, user_id)
                preview = preview_open_ingress_rule_data(instance_ref, port, source_cidr, self.app_config) if action == "open" else preview_cleanup_temp_rules_data(instance_ref, port, source_cidr, self.app_config)
                self._remember_instance_like(preview["instance"])
                preview_text = render_open_ingress_preview_telegram(preview) if action == "open" else render_cleanup_preview_telegram(preview)
                self.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=preview_text,
                    parse_mode="HTML",
                    reply_markup=self.build_netsec_preview_keyboard(action, str(preview["instance"]["id"]), str(port), source_cidr, back_page=back_page),
                )
                self.answer_callback_query(callback_query_id, "已生成预览")
                return

            if data.startswith("netsec:apply:"):
                flow = self._consume_callback_state(self.netsec_flow_refs, data.split(":", 2)[2], "网络/安全会话已失效，请重新进入该流程")
                action = str(flow["action"])
                instance_ref = str(flow["instance_ref"])
                port = str(flow["port"])
                source_cidr = str(flow["source_cidr"])
                back_page = int(flow.get("back_page", 1) or 1)
                self._clear_menu_state(chat_id, user_id)
                if action == "open":
                    result = apply_open_ingress_rule_data(instance_ref, port, source_cidr, self.app_config)
                    result_text = render_open_ingress_result_telegram(result)
                    notice = "已提交放行"
                else:
                    result = apply_cleanup_temp_rules_data(instance_ref, port, source_cidr, self.app_config)
                    result_text = render_cleanup_result_telegram(result)
                    notice = "已提交清理"
                self._remember_instance_like(result["instance"])
                self.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=result_text,
                    parse_mode="HTML",
                    reply_markup=self.build_netsec_result_keyboard(
                        str(result["instance"]["id"]),
                        back_page=back_page,
                        refresh_temp_page=1 if action == "cleanup" else None,
                    ),
                )
                self.answer_callback_query(callback_query_id, notice)
                return

            for verb in ("start", "stop", "restart"):
                prefix = f"instance:{verb}:"
                if data.startswith(prefix):
                    parts = data.split(":")
                    instance_ref = self._resolve_callback_ref(parts[2])
                    back_page = self._resolve_instance_page(parts[3]) if len(parts) > 3 else 1
                    result = execute_instance_action_data(verb, instance_ref, self.app_config)
                    self._remember_instance_like(result["id"], str(result.get("display_name", "")))
                    text = render_instance_action_telegram(result)
                    keyboard = self.build_instance_action_keyboard(str(result["id"]), back_page=back_page)
                    self.send_message(chat_id=chat_id, text=text, parse_mode="HTML", reply_markup=keyboard)
                    self.answer_callback_query(callback_query_id, f"已提交{verb}操作")
                    return

            self.answer_callback_query(callback_query_id, "未知操作")
        except Exception as exc:
            self.answer_callback_query(callback_query_id, "操作失败")
            self._send_generic_error(chat_id)

    def _handle_message_update(self, message: Dict[str, Any], chat_id: str, user_id: str, text: str) -> bool:
        """Handle message-level routing prerequisites; state/command handlers follow."""
        if not chat_id or not text:
            return True
        if not self.is_authorized(message):
            self.send_message(chat_id, "❌ 当前 chat/user 未授权执行该 Bot 命令。")
            return True
        return False

    def process_update(self, update: Dict[str, Any]) -> None:
        self._update_query_cache.clear()
        self._process_update(update)
        self.last_update_id = max(self.last_update_id, int(update.get("update_id", 0)))
        self._update_query_cache.clear()

    def _process_update(self, update: Dict[str, Any]) -> None:
        callback_query = update.get("callback_query")
        if callback_query:
            callback_message = callback_query.get("message") or {}
            callback_chat = callback_message.get("chat") or {}
            callback_user = callback_query.get("from") or {}
            self._active_callback_owner = (str(callback_chat.get("id", "")), str(callback_user.get("id", "")))
            self.handle_callback_query(callback_query)
            return

        message = update.get("message") or {}
        chat = message.get("chat") or {}
        chat_id = str(chat.get("id", ""))
        text = message.get("text", "")
        user_id = str((message.get("from") or {}).get("id", ""))
        self._active_callback_owner = (chat_id, user_id)

        if self._handle_message_update(message, chat_id, user_id, text):
            return

        state = self._get_menu_state(chat_id, user_id)
        if state and not text.strip().startswith("/"):
            try:
                step = state.get("step")
                if step == "create_wait_name":
                    policy_name = text.strip()
                    ok, error = validate_policy_name(policy_name)
                    if not ok:
                        self.send_message(chat_id, f"❌ {error}", parse_mode="HTML")
                        return
                    state["policy_name"] = policy_name
                    state["step"] = "create_wait_days"
                    self._set_menu_state(chat_id, user_id, state)
                    self.send_message(chat_id, render_policy_create_days_prompt(policy_name), parse_mode="HTML", reply_markup=build_policy_days_keyboard())
                    return
                if step == "create_wait_days_custom":
                    ok, days, error = validate_expires_days(text.strip())
                    if not ok:
                        self.send_message(chat_id, f"❌ {error}", parse_mode="HTML")
                        return
                    policy_name = str(state.get("policy_name", ""))
                    state["expires_days"] = days
                    state["step"] = "create_confirm"
                    self._set_menu_state(chat_id, user_id, state)
                    self.send_message(chat_id, render_policy_create_confirm(policy_name, days), parse_mode="HTML", reply_markup=build_policy_create_confirm_keyboard(days))
                    return
                if step == "netsec_wait_port":
                    action = str(state.get("netsec_action", "open"))
                    instance_ref = str(state.get("instance_ref", ""))
                    back_page = int(state.get("back_page", 1) or 1)
                    prompt_message_id = int(state.get("prompt_message_id", 0) or 0)
                    port = str(_parse_single_tcp_port_input(text.strip()))
                    self._set_menu_state(chat_id, user_id, {
                        "step": "netsec_wait_cidr",
                        "netsec_action": action,
                        "instance_ref": instance_ref,
                        "instance_display_name": self._get_instance_display_name(instance_ref),
                        "port": port,
                        "back_page": back_page,
                        "prompt_message_id": prompt_message_id,
                    })
                    cidr_text = (
                        f"<b>{'🌍' if action == 'open' else '🧭'} 网络 / 安全向导</b>\n"
                        f"<b>{'放行临时端口' if action == 'open' else '清理临时规则'} · 选择来源 CIDR</b>\n"
                        f"<blockquote>实例：{self._format_instance_badge(instance_ref, fallback=str(state.get('instance_display_name', '')))}\n端口：<code>TCP/{html.escape(str(port))}</code></blockquote>\n"
                        "🧭 当前步骤：选择默认值，或切到输入态自行发送 CIDR。\n"
                        f"⚡ 默认 CIDR：<code>{html.escape(str(self.network_runtime.get('default_source_cidr', '0.0.0.0/0')))}</code>"
                    )
                    if prompt_message_id:
                        self.edit_message_text(
                            chat_id=chat_id,
                            message_id=prompt_message_id,
                            text=cidr_text,
                            parse_mode="HTML",
                            reply_markup=self.build_netsec_cidr_keyboard(action, instance_ref, str(port), back_page=back_page),
                        )
                    else:
                        self.send_message(
                            chat_id,
                            cidr_text,
                            parse_mode="HTML",
                            reply_markup=self.build_netsec_cidr_keyboard(action, instance_ref, str(port), back_page=back_page),
                        )
                    return
                if step == "netsec_wait_cidr":
                    action = str(state.get("netsec_action", "open"))
                    instance_ref = str(state.get("instance_ref", ""))
                    port = str(state.get("port", ""))
                    back_page = int(state.get("back_page", 1) or 1)
                    prompt_message_id = int(state.get("prompt_message_id", 0) or 0)
                    source_cidr = text.strip()
                    preview = preview_open_ingress_rule_data(instance_ref, port, source_cidr, self.app_config) if action == "open" else preview_cleanup_temp_rules_data(instance_ref, port, source_cidr, self.app_config)
                    self._remember_instance_like(preview["instance"])
                    preview_text = render_open_ingress_preview_telegram(preview) if action == "open" else render_cleanup_preview_telegram(preview)
                    self._clear_menu_state(chat_id, user_id)
                    if prompt_message_id:
                        self.edit_message_text(
                            chat_id=chat_id,
                            message_id=prompt_message_id,
                            text=preview_text,
                            parse_mode="HTML",
                            reply_markup=self.build_netsec_preview_keyboard(action, str(preview["instance"]["id"]), port, source_cidr, back_page=back_page),
                        )
                    else:
                        self.send_message(
                            chat_id,
                            preview_text,
                            parse_mode="HTML",
                            reply_markup=self.build_netsec_preview_keyboard(action, str(preview["instance"]["id"]), port, source_cidr, back_page=back_page),
                        )
                    return
            except Exception as exc:
                step = state.get("step")
                if step == "netsec_wait_port":
                    action = str(state.get("netsec_action", "open"))
                    instance_ref = str(state.get("instance_ref", ""))
                    back_page = int(state.get("back_page", 1) or 1)
                    prompt_message_id = int(state.get("prompt_message_id", 0) or 0)
                    error_text = (
                        f"<b>❌ 网络 / 安全向导</b>\n"
                        f"<b>端口格式不正确</b>\n"
                        f"<blockquote>实例：{self._format_instance_badge(instance_ref, fallback=str(state.get('instance_display_name', '')))}</blockquote>\n"
                        "🧭 当前步骤：请重新发送单个 TCP 端口，例如 <code>22</code> 或 <code>25565</code>\n"
                        f"错误：<code>{html.escape(str(exc))}</code>\n"
                        "⚠️ 仅支持 1-65535 的单端口；目前还没动任何规则。"
                    )
                    if prompt_message_id:
                        self.edit_message_text(
                            chat_id=chat_id,
                            message_id=prompt_message_id,
                            text=error_text,
                            parse_mode="HTML",
                            reply_markup=self._build_netsec_waiting_keyboard(action, instance_ref, "0", back_page=back_page, mode="port"),
                        )
                    else:
                        self.send_message(
                            chat_id,
                            error_text,
                            parse_mode="HTML",
                            reply_markup=self._build_netsec_waiting_keyboard(action, instance_ref, "0", back_page=back_page, mode="port"),
                        )
                    return
                if step == "netsec_wait_cidr":
                    action = str(state.get("netsec_action", "open"))
                    instance_ref = str(state.get("instance_ref", ""))
                    port = str(state.get("port", ""))
                    back_page = int(state.get("back_page", 1) or 1)
                    prompt_message_id = int(state.get("prompt_message_id", 0) or 0)
                    error_text = (
                        f"<b>❌ 网络 / 安全向导</b>\n"
                        f"<b>CIDR 格式不正确</b>\n"
                        f"<blockquote>实例：{self._format_instance_badge(instance_ref, fallback=str(state.get('instance_display_name', '')))}\n"
                        f"端口：<code>TCP/{html.escape(port)}</code></blockquote>\n"
                        f"🧭 当前步骤：请重新发送合法 CIDR，例如 <code>1.2.3.4/32</code>\n"
                        f"错误：<code>{html.escape(str(exc))}</code>\n"
                        "💡 修正后直接再发一条就行。\n"
                        "⚠️ 目前还没动任何规则。"
                    )
                    if prompt_message_id:
                        self.edit_message_text(
                            chat_id=chat_id,
                            message_id=prompt_message_id,
                            text=error_text,
                            parse_mode="HTML",
                            reply_markup=self._build_netsec_waiting_keyboard(action, instance_ref, port, back_page=back_page),
                        )
                    else:
                        self.send_message(
                            chat_id,
                            error_text,
                            parse_mode="HTML",
                            reply_markup=self._build_netsec_waiting_keyboard(action, instance_ref, port, back_page=back_page),
                        )
                    return
                self.send_message(chat_id, f"<b>❌ 输入处理失败</b>\n<code>{html.escape(str(exc))}</code>", parse_mode="HTML")
                return

        try:
            if text.strip().startswith("/start"):
                self.send_message(chat_id, self.build_start_card_text(), parse_mode="HTML", reply_markup=self.build_main_menu_keyboard())
                return
            if text.strip().startswith("/menu"):
                self.send_message(chat_id, self.build_help_text(), parse_mode="HTML", reply_markup=self.build_main_menu_keyboard())
                return
            if text.strip().startswith("/policies"):
                self._clear_menu_state(chat_id, user_id)
                self.send_message(chat_id, render_policy_home_text(), parse_mode="HTML", reply_markup=build_policy_menu_keyboard())
                return
            if text.strip().startswith("/usage_fee"):
                report_data = get_usage_fee_report_data(self.app_config)
                rendered = render_usage_fee_telegram(report_data, show_all=False)
                keyboard = self.build_usage_fee_keyboard(False, len(report_data["unique_dates"]), report_data["display_days"])
                self.send_message(chat_id, rendered, parse_mode="HTML", reply_markup=keyboard)
                return
            if text.strip().startswith(("/regions", "/region_subscriptions")):
                self.send_message(chat_id, render_region_subscriptions_telegram(get_region_subscriptions_data(self.app_config)), parse_mode="HTML", reply_markup=self.build_main_menu_keyboard())
                return
            if text.strip().startswith("/bucket_info"):
                self.send_message(chat_id, render_bucket_info_telegram(get_bucket_info_data(self.app_config)), parse_mode="HTML", reply_markup=self.build_main_menu_keyboard())
                return
            if text.strip().startswith("/audit_events"):
                normalized = text.strip()
                parts = normalized.split(maxsplit=1)
                limit = 10
                if len(parts) > 1:
                    try:
                        limit = min(max(1, int(parts[1].strip())), 50)
                    except Exception:
                        limit = 10
                self.send_message(chat_id, render_audit_events_telegram(get_audit_events_data(self.app_config, limit=limit), limit=limit), parse_mode="HTML", reply_markup=self.build_main_menu_keyboard())
                return
            if text.strip().startswith("/instances"):
                instance_data = list_instances_data(self.app_config)
                self.send_message(chat_id, render_instances_telegram(instance_data, page=1, page_size=self.instance_page_size), parse_mode="HTML", reply_markup=self.build_instances_keyboard(instance_data, page=1))
                return
            if text.strip().startswith("/instance_detail"):
                instance_ref = self._extract_tail_argument(text.strip())
                detail = get_instance_detail_data(instance_ref, self.app_config) if instance_ref else None
                result = render_instance_detail_telegram(detail) if detail else self.handle_command(text)
                if detail:
                    self._remember_instance_like(detail)
                self.send_message(chat_id, result, parse_mode="HTML", reply_markup=self.build_instance_detail_keyboard(detail, back_page=1) if detail else None)
                return
            if text.strip().startswith("/instance_network"):
                normalized = text.strip()
                instance_ref = self._extract_tail_argument(normalized)
                if not instance_ref:
                    self.send_message(chat_id, "<b>🌐 网络 / 安全向导</b>\n请提供实例名称或 OCID，例如：<code>/instance_network my-vm</code>", parse_mode="HTML")
                    return
                overview = get_instance_network_overview_data(instance_ref, self.app_config)
                self._remember_instance_like(overview["instance"])
                self.send_message(
                    chat_id,
                    render_instance_network_overview_telegram(overview),
                    parse_mode="HTML",
                    reply_markup=self.build_instance_network_keyboard(str(overview["instance"]["id"]), back_page=1),
                )
                return
            if text.strip().startswith("/instance_rules"):
                normalized = text.strip()
                instance_ref = self._extract_tail_argument(normalized)
                if not instance_ref:
                    self.send_message(chat_id, "<b>🛡️ 网络 / 安全向导</b>\n请提供实例名称或 OCID，例如：<code>/instance_rules my-vm</code>", parse_mode="HTML")
                    return
                rule_data = get_instance_ingress_rules_data(instance_ref, self.app_config, page=1, temp_only=False)
                self._remember_instance_like(rule_data["instance"])
                self.send_message(chat_id, render_instance_ingress_rules_telegram(rule_data), parse_mode="HTML", reply_markup=self.build_ingress_rules_keyboard(str(rule_data["instance"]["id"]), back_page=1, page=1, temp_only=False))
                return
            if text.strip().startswith("/instance_temp_rules"):
                normalized = text.strip()
                instance_ref = self._extract_tail_argument(normalized)
                if not instance_ref:
                    self.send_message(chat_id, "<b>🧪 网络 / 安全向导</b>\n请提供实例名称或 OCID，例如：<code>/instance_temp_rules my-vm</code>", parse_mode="HTML")
                    return
                rule_data = get_instance_ingress_rules_data(instance_ref, self.app_config, page=1, temp_only=True)
                self._remember_instance_like(rule_data["instance"])
                self.send_message(chat_id, render_instance_ingress_rules_telegram(rule_data), parse_mode="HTML", reply_markup=self.build_ingress_rules_keyboard(str(rule_data["instance"]["id"]), back_page=1, page=1, temp_only=True))
                return
            if text.strip().startswith("/netsec_open"):
                normalized = text.strip()
                parts = normalized.split(maxsplit=3)
                if len(parts) < 4:
                    self.send_message(chat_id, "<b>🔓 网络 / 安全向导</b>\n用法：<code>/netsec_open 实例名 22 1.2.3.4/32</code>", parse_mode="HTML")
                    return
                preview = preview_open_ingress_rule_data(parts[1], parts[2], parts[3], self.app_config)
                self._remember_instance_like(preview["instance"])
                preview_text = render_open_ingress_preview_telegram(preview)
                self.send_message(chat_id, preview_text, parse_mode="HTML", reply_markup=self.build_netsec_preview_keyboard("open", str(preview["instance"]["id"]), parts[2], parts[3], back_page=1))
                return
            if text.strip().startswith("/netsec_close_temp"):
                normalized = text.strip()
                parts = normalized.split(maxsplit=3)
                if len(parts) < 4:
                    self.send_message(chat_id, "<b>🧹 网络 / 安全向导</b>\n用法：<code>/netsec_close_temp 实例名 22 1.2.3.4/32</code>", parse_mode="HTML")
                    return
                preview = preview_cleanup_temp_rules_data(parts[1], parts[2], parts[3], self.app_config)
                self._remember_instance_like(preview["instance"])
                preview_text = render_cleanup_preview_telegram(preview)
                self.send_message(chat_id, preview_text, parse_mode="HTML", reply_markup=self.build_netsec_preview_keyboard("cleanup", str(preview["instance"]["id"]), parts[2], parts[3], back_page=1))
                return
            if text.strip().startswith(("/instance_start", "/instance_stop", "/instance_restart")):
                normalized = text.strip()
                instance_ref = self._extract_tail_argument(normalized)
                if not instance_ref:
                    result = self.handle_command(normalized)
                    self.send_message(chat_id, result, parse_mode="HTML")
                    return
                action = normalized.split()[0].replace("/instance_", "")
                if action in {"stop", "restart"}:
                    action_name = f"instance_{action}"
                    token = self._register_dangerous_action(action_name, instance_ref)
                    self.send_message(
                        chat_id,
                        self._dangerous_confirmation_text(action_name, instance_ref),
                        parse_mode="HTML",
                        reply_markup=self._build_dangerous_confirmation_keyboard(token),
                    )
                    return
                action_result = execute_instance_action_data(action, instance_ref, self.app_config)
                self._remember_instance_like(action_result["id"], str(action_result.get("display_name", "")))
                self.send_message(
                    chat_id,
                    render_instance_action_telegram(action_result),
                    parse_mode="HTML",
                    reply_markup=self.build_instance_action_keyboard(str(action_result["id"]), back_page=1),
                )
                return
            if text.strip().startswith("/delete_policy"):
                normalized = text.strip()
                parts = normalized.split(maxsplit=1)
                if len(parts) < 2:
                    self.send_message(chat_id, self.handle_command(normalized), parse_mode="HTML")
                    return
                target = parts[1].strip()
                token = self._register_dangerous_action("delete_policy", target)
                self.send_message(
                    chat_id,
                    self._dangerous_confirmation_text("delete_policy", target),
                    parse_mode="HTML",
                    reply_markup=self._build_dangerous_confirmation_keyboard(token),
                )
                return
            if text.strip().startswith(("/help", "/run")):
                result = self.handle_command(text)
                self.send_message(chat_id, result or "✅ 命令执行完成，但无返回内容。", parse_mode="HTML")
                return
            result = self.handle_command(text)
        except Exception as exc:
            result = "<b>❌ 命令执行失败</b>\n请求未完成，请稍后重试。"

        parse_mode = "HTML" if any(tag in result for tag in ("<b>", "<code>", "<blockquote>", "<i>", "&lt;")) else None
        self.send_message(chat_id, result or "✅ 命令执行完成，但无返回内容。", parse_mode=parse_mode)

    def run_polling(self) -> None:
        self.validate()
        self.refresh_bot_commands()
        if not self._startup_notice_sent:
            for chat_id in self.allowed_chat_ids:
                self.send_message(chat_id, "⚠️ Bot 服务已重启，旧的按钮流程已失效。请重新打开菜单；未重新确认的危险操作不会执行。")
            self._startup_notice_sent = True
        print("🤖 Telegram Bot 命令菜单已同步到 Telegram 客户端。")
        print("🤖 Telegram Bot 已启动，正在轮询消息...")
        print("按 Ctrl+C 可停止 Bot。")
        while True:
            try:
                updates = self.get_updates()
                for update in updates:
                    self.process_update(update)
            except requests.RequestException as exc:
                print("⚠️ Telegram 网络请求失败，请稍后重试。")
                time.sleep(self.poll_interval)
            except Exception as exc:
                print("⚠️ Telegram 处理异常，请稍后重试。")
                time.sleep(self.poll_interval)
