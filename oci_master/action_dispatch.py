from typing import Tuple


def parse_action(action: str) -> Tuple[str, Tuple[str, ...]]:
    """Normalize an action name and colon-delimited arguments."""
    normalized = str(action or "").strip()
    if not normalized:
        raise ValueError("action 不能为空")
    parts = tuple(item.strip() for item in normalized.split(":"))
    name = parts[0]
    if not name:
        raise ValueError("action 不能为空")
    return name, parts[1:]
