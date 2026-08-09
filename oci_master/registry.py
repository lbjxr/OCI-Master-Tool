"""Plugin-style action registry for CLI, menu, and Telegram dispatch.

Goals:
- Add a feature without touching app.py or telegram_bot.py
- Each feature registers: CLI handler, Telegram message handler, Telegram callback handlers, menu entry
- Auto-discovery via import-time registration (no fragile magic import loops)

Design:
- Handlers are plain callables registered by string key.
- CLI entry = (callable, help_text, argument_parser)
- Telegram entry = (message_handler, callback_prefix, callback_handler)
- Menu entry = (label, action_key, emoji)
"""
from typing import Any, Callable, Dict, List, Optional, Tuple

# ────────────────────────────────────────────
# CLI Registry
# ────────────────────────────────────────────
CLIAction = Callable[[Dict[str, Any], Tuple[str, ...]], Any]

_cli_registry: Dict[str, Tuple[CLIAction, str]] = {}


def register_cli(action: str, handler: CLIAction, help_text: str = "") -> None:
    """Register a CLI action handler.

    handler signature: handler(app_config, args) -> Any
    args is the tuple after the action name split by colon.
    """
    _cli_registry[action] = (handler, help_text)


def list_cli_actions() -> List[Tuple[str, str]]:
    """Return list of (action_name, help_text) for menu generation."""
    return sorted((name, help) for name, (_, help) in _cli_registry.items())


def dispatch_cli(action: str, app_config: Dict[str, Any]) -> Any:
    """Dispatch a CLI action string like 'user_info' or 'instance_detail:my-vm'."""
    parts = tuple(item.strip() for item in action.split(":"))
    name = parts[0]
    if name not in _cli_registry:
        known = ", ".join(sorted(_cli_registry.keys()))
        raise ValueError(f"不支持的 action: {action}。可选: {known}")
    handler, _ = _cli_registry[name]
    return handler(app_config, parts[1:])


# ────────────────────────────────────────────
# Telegram Message Handler Registry
# ────────────────────────────────────────────
TGMessageHandler = Callable[[Any, str, str, str, str], Any]
# runner, text, chat_id, user_id, message_id -> None (sends response internally)

_tg_message_registry: Dict[str, TGMessageHandler] = {}


def register_telegram_message(command: str, handler: TGMessageHandler) -> None:
    """Register a Telegram message handler for a /command or keyword.

    command should be the text prefix, e.g. '/start', '/instances', '/load_balancers'
    handler receives (runner, text, chat_id, user_id, message_id)
    """
    _tg_message_registry[command] = handler


def dispatch_telegram_message(runner: Any, text: str, chat_id: str, user_id: str, message_id: str) -> bool:
    """Dispatch a Telegram message. Returns True if handled."""
    normalized = (text or "").strip()
    for prefix, handler in _tg_message_registry.items():
        if normalized.startswith(prefix):
            handler(runner, normalized, chat_id, user_id, message_id)
            return True
    return False


# ────────────────────────────────────────────
# Telegram Callback Handler Registry
# ────────────────────────────────────────────
TGCallbackHandler = Callable[[Any, str, str, str, str, Optional[str]], Any]
# runner, callback_data, chat_id, user_id, message_id -> None

_tg_callback_registry: Dict[str, TGCallbackHandler] = {}


def register_telegram_callback(prefix: str, handler: TGCallbackHandler) -> None:
    """Register a callback handler for a data prefix.

    prefix should be the part before ':', e.g. 'menu', 'netsec', 'lb'
    """
    _tg_callback_registry[prefix] = handler


def dispatch_telegram_callback(runner: Any, callback_data: str, chat_id: str, user_id: str, message_id: str, callback_query_id: Optional[str] = None) -> bool:
    """Dispatch a Telegram callback. Returns True if handled."""
    prefix = (callback_data or "").split(":", 1)[0]
    handler = _tg_callback_registry.get(prefix)
    if handler:
        handler(runner, callback_data, chat_id, user_id, message_id, callback_query_id)
        return True
    return False


# ────────────────────────────────────────────
# Menu Entry Registry
# ────────────────────────────────────────────
MenuEntry = Tuple[str, str, str]  # (emoji_label, action_key, description)

_menu_registry: List[MenuEntry] = []


def register_menu(emoji_label: str, action_key: str, description: str = "") -> None:
    """Register an interactive menu entry.

    emoji_label: e.g. "1. 👤 查看当前用户详细信息"
    action_key: the action dispatched when selected
    description: short help text
    """
    _menu_registry.append((emoji_label, action_key, description))


def get_menu_entries() -> List[MenuEntry]:
    return list(_menu_registry)


def clear_registries() -> None:
    """Reset all registries. Primarily for testing."""
    _cli_registry.clear()
    _tg_message_registry.clear()
    _tg_callback_registry.clear()
    _menu_registry.clear()
