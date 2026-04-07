"""
OCI Master - 核心工具函数
"""
from typing import Any


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
    """格式化布尔值为 Yes/No"""
    if isinstance(value, bool):
        return "Yes" if value else "No"
    return str(value)
