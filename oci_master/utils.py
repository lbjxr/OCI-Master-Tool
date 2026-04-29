import html
import io
from contextlib import redirect_stdout
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List


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


def safe_get(obj: Any, attr_name: str, default: Any = "N/A") -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        value = obj.get(attr_name, default)
    else:
        value = getattr(obj, attr_name, default)
    return default if value is None else value


def safe_get_any(obj: Any, *attr_names: str, default: Any = "N/A") -> Any:
    for attr_name in attr_names:
        value = safe_get(obj, attr_name, default)
        if value != default:
            return value
    return default


def unwrap_state_value(value: Any, *nested_keys: str, default: Any = "N/A") -> Any:
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


def format_datetime_compact(value: Any) -> str:
    if value in (None, "N/A", ""):
        return "N/A"
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
        try:
            if text.endswith("Z"):
                text = text[:-1] + "+00:00"
            dt = datetime.fromisoformat(text)
        except Exception:
            return str(value)
    if dt.tzinfo is None:
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def format_size_compact(num_bytes: Any) -> str:
    if num_bytes in (None, "N/A", ""):
        return "N/A"
    try:
        value = float(num_bytes)
    except (TypeError, ValueError):
        return str(num_bytes)

    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    index = 0
    while value >= 1024 and index < len(units) - 1:
        value /= 1024
        index += 1
    if index == 0:
        return f"{int(value)} {units[index]}"
    return f"{value:.2f} {units[index]}"


def capture_output(func: Callable, *args, **kwargs) -> str:
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        func(*args, **kwargs)
    return buffer.getvalue().strip()


def html_escape(value: Any) -> str:
    return html.escape(str(value))
