import html
import time
from typing import Any, Dict, List, Optional, Sequence

import oci
import requests

from oci_master.clients import get_compute_client, get_virtual_network_client
from oci_master.config import (
    get_active_profile_name,
    get_instance_runtime_config,
    get_oci_config,
)
from oci_master.utils import (
    build_text_table,
    format_datetime_compact,
    print_kv,
    print_section,
    safe_get,
    truncate_text,
)

INSTANCE_ACTION_MAP = {
    "start": "START",
    "stop": "SOFTSTOP",
    "restart": "SOFTRESET",
}

TRANSITION_STATES = {
    "PROVISIONING",
    "STARTING",
    "STOPPING",
    "STOPPED",
    "TERMINATING",
    "TERMINATED",
    "RESETTING",
}

_RECOVERABLE_QUERY_ERRORS = (
    oci.exceptions.ServiceError,
    oci.exceptions.RequestException,
    requests.exceptions.RequestException,
    TimeoutError,
    ConnectionError,
)


def _list_accessible_compartments(identity_client, tenancy_id: str) -> List[Any]:
    compartments = [identity_client.get_compartment(tenancy_id).data]
    listed = oci.pagination.list_call_get_all_results(
        identity_client.list_compartments,
        tenancy_id,
        compartment_id_in_subtree=True,
        access_level="ACCESSIBLE",
    ).data
    for compartment in listed:
        state = str(getattr(compartment, "lifecycle_state", "") or "")
        if state.upper() == "ACTIVE":
            compartments.append(compartment)
    return compartments


def _normalize_filter_values(values: Sequence[Any]) -> List[str]:
    normalized: List[str] = []
    for value in values or []:
        text = str(value or "").strip()
        if text:
            normalized.append(text)
    return normalized


def _filter_compartments(compartments: List[Any], app_config: Optional[Dict[str, Any]] = None) -> List[Any]:
    runtime_cfg = get_instance_runtime_config(app_config or {})
    allowed_ids = {item for item in _normalize_filter_values(runtime_cfg.get("default_compartment_ids", []))}
    allowed_names = {item.lower() for item in _normalize_filter_values(runtime_cfg.get("default_compartment_names", []))}

    if not allowed_ids and not allowed_names:
        return compartments

    filtered: List[Any] = []
    for compartment in compartments:
        compartment_id = str(getattr(compartment, "id", "") or "")
        compartment_name = str(getattr(compartment, "name", compartment_id) or compartment_id)
        if compartment_id in allowed_ids or compartment_name.lower() in allowed_names:
            filtered.append(compartment)
    return filtered


def _build_scope_label(app_config: Optional[Dict[str, Any]] = None) -> str:
    runtime_cfg = get_instance_runtime_config(app_config or {})
    names = _normalize_filter_values(runtime_cfg.get("default_compartment_names", []))
    ids = _normalize_filter_values(runtime_cfg.get("default_compartment_ids", []))
    labels = names + [truncate_text(item, 28) for item in ids]
    return "、".join(labels) if labels else "全部可访问 Compartment"


def _collect_instances(app_config: Optional[Dict[str, Any]] = None, include_network: bool = True) -> List[Dict[str, Any]]:
    config = get_oci_config(app_config)
    compute_client = get_compute_client(config)
    identity_client = oci.identity.IdentityClient(config)
    network_client = get_virtual_network_client(config) if include_network else None

    tenancy_id = config["tenancy"]
    compartments = _filter_compartments(_list_accessible_compartments(identity_client, tenancy_id), app_config)
    seen_instance_ids = set()
    instances: List[Dict[str, Any]] = []

    for compartment in compartments:
        compartment_id = compartment.id
        compartment_name = getattr(compartment, "name", compartment_id)
        response = oci.pagination.list_call_get_all_results(
            compute_client.list_instances,
            compartment_id=compartment_id,
        )
        for item in response.data:
            instance_id = item.id
            if instance_id in seen_instance_ids:
                continue
            seen_instance_ids.add(instance_id)

            vnic_ip = "N/A"
            if include_network:
                try:
                    assert network_client is not None
                    attachments = oci.pagination.list_call_get_all_results(
                        compute_client.list_vnic_attachments,
                        compartment_id=compartment_id,
                        instance_id=instance_id,
                    ).data
                    if attachments:
                        vnic = network_client.get_vnic(attachments[0].vnic_id).data
                        vnic_ip = getattr(vnic, "public_ip", None) or getattr(vnic, "private_ip", "N/A")
                except _RECOVERABLE_QUERY_ERRORS:
                    vnic_ip = "N/A"

            instances.append(
                {
                    "id": item.id,
                    "display_name": getattr(item, "display_name", item.id),
                    "lifecycle_state": getattr(item, "lifecycle_state", "UNKNOWN"),
                    "shape": getattr(item, "shape", "N/A"),
                    "compartment_id": compartment_id,
                    "compartment_name": compartment_name,
                    "availability_domain": getattr(item, "availability_domain", "N/A"),
                    "region": config.get("region", "N/A"),
                    "time_created": getattr(item, "time_created", None),
                    "ip_address": vnic_ip,
                }
            )

    instances.sort(key=lambda x: (x["compartment_name"], x["display_name"]))
    return instances


def _instance_from_detail(detail: Any, config: Dict[str, Any]) -> Dict[str, Any]:
    compartment_id = getattr(detail, "compartment_id", "N/A")
    return {
        "id": detail.id,
        "display_name": getattr(detail, "display_name", detail.id),
        "lifecycle_state": getattr(detail, "lifecycle_state", "UNKNOWN"),
        "shape": getattr(detail, "shape", "N/A"),
        "compartment_id": compartment_id,
        "compartment_name": getattr(detail, "compartment_name", compartment_id),
        "availability_domain": getattr(detail, "availability_domain", "N/A"),
        "region": config.get("region", "N/A"),
        "time_created": getattr(detail, "time_created", None),
        "ip_address": "N/A",
    }


def _lookup_instance(instance_ref: str, app_config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Resolve an OCID directly; use a metadata-only list for human names."""
    needle = (instance_ref or "").strip()
    if not needle:
        raise ValueError("实例标识不能为空，可传实例名称或 OCID")
    config = get_oci_config(app_config)
    compute_client = get_compute_client(config)
    if needle.lower().startswith("ocid1.instance."):
        return _instance_from_detail(compute_client.get_instance(needle).data, config)
    return _resolve_instance(_collect_instances(app_config, include_network=False), needle)


def _resolve_instance(instances: List[Dict[str, Any]], instance_ref: str) -> Dict[str, Any]:
    needle = (instance_ref or "").strip().lower()
    if not needle:
        raise ValueError("实例标识不能为空，可传实例名称或 OCID")

    exact_matches = [
        item for item in instances if item["id"].lower() == needle or item["display_name"].lower() == needle
    ]
    if len(exact_matches) == 1:
        return exact_matches[0]
    if len(exact_matches) > 1:
        raise ValueError("匹配到多个同名实例，请改用实例 OCID")

    fuzzy_matches = [
        item for item in instances if needle in item["id"].lower() or needle in item["display_name"].lower()
    ]
    if len(fuzzy_matches) == 1:
        return fuzzy_matches[0]
    if len(fuzzy_matches) > 1:
        raise ValueError("匹配到多个实例，请提供更精确的名称或直接使用实例 OCID")

    raise ValueError(f"未找到实例：{instance_ref}")


def _paginate_items(items: List[Dict[str, Any]], page: int = 1, page_size: int = 8) -> Dict[str, Any]:
    safe_page_size = max(1, int(page_size or 1))
    total = len(items)
    total_pages = max(1, (total + safe_page_size - 1) // safe_page_size)
    current_page = min(max(1, int(page or 1)), total_pages)
    start = (current_page - 1) * safe_page_size
    end = start + safe_page_size
    return {
        "items": items[start:end],
        "page": current_page,
        "page_size": safe_page_size,
        "total_pages": total_pages,
        "total": total,
        "start_index": start,
        "end_index": min(end, total),
        "has_prev": current_page > 1,
        "has_next": current_page < total_pages,
    }


def _fetch_instance_state(instance_id: str, app_config: Optional[Dict[str, Any]] = None) -> str:
    config = get_oci_config(app_config)
    compute_client = get_compute_client(config)
    detail = compute_client.get_instance(instance_id).data
    return str(getattr(detail, "lifecycle_state", "UNKNOWN") or "UNKNOWN")


def _recheck_instance_state(instance_id: str, app_config: Optional[Dict[str, Any]] = None, delays: Optional[Sequence[float]] = None) -> Dict[str, Any]:
    if delays is None:
        delays = (2, 5)

    last_error: Optional[str] = None
    for delay in delays:
        if delay > 0:
            time.sleep(delay)
        try:
            state = _fetch_instance_state(instance_id, app_config)
            return {"state": state, "recheck_delay_seconds": delay, "recheck_error": None}
        except _RECOVERABLE_QUERY_ERRORS as exc:
            last_error = str(exc)
    return {"state": None, "recheck_delay_seconds": sum(delays), "recheck_error": last_error}


def _is_transition_state(state: Any) -> bool:
    text = str(state or "").upper()
    return text in TRANSITION_STATES


def list_instances_data(app_config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    instances = _collect_instances(app_config, include_network=False)
    return {
        "profile": get_active_profile_name(app_config or {}),
        "count": len(instances),
        "scope": _build_scope_label(app_config),
        "items": instances,
    }


def render_instances_cli(data: Dict[str, Any]) -> str:
    rows = [
        [
            item["display_name"],
            item["lifecycle_state"],
            truncate_text(item["shape"], 18),
            truncate_text(item["compartment_name"], 18),
            truncate_text(item["ip_address"], 18),
            truncate_text(item["id"], 28),
        ]
        for item in data["items"]
    ]
    parts = [
        "\n" + "=" * 72,
        f"🖥️ 实例列表（Profile: {data['profile']}）",
        f"实例总数: {data['count']}",
        f"范围: {data.get('scope', '全部可访问 Compartment')}",
    ]
    if rows:
        parts.append(build_text_table(["名称", "状态", "规格", "Compartment", "IP", "实例 OCID"], rows))
    else:
        parts.append("(无实例数据)")
    return "\n".join(parts)


def render_instances_telegram(data: Dict[str, Any], page: int = 1, page_size: int = 8) -> str:
    pagination = _paginate_items(data["items"], page=page, page_size=page_size)
    items = pagination["items"]
    profile = html.escape(str(data["profile"]))
    scope = html.escape(str(data.get("scope", "全部可访问 Compartment")))
    if not items:
        return (
            "<b>🖥️ OCI 实例总览</b>\n"
            f"<blockquote>Profile：<code>{profile}</code>\n范围：<code>{scope}</code></blockquote>\n"
            "当前未发现可访问实例。"
        )

    state_icon_map = {
        "RUNNING": "🟢",
        "STOPPED": "🔴",
        "STARTING": "🟡",
        "STOPPING": "🟡",
        "TERMINATED": "⚫️",
        "PROVISIONING": "🟡",
        "RESETTING": "🟡",
    }

    lines = [
        "<b>🖥️ OCI 实例总览</b>",
        f"<blockquote>Profile：<code>{profile}</code>\n实例总数：<b>{data['count']}</b>\n范围：<code>{scope}</code></blockquote>",
        f"<b>📋 实例列表</b>（第 {pagination['page']}/{pagination['total_pages']} 页，{pagination['start_index'] + 1}-{pagination['end_index']}）",
        "",
    ]
    for index, item in enumerate(items, start=pagination["start_index"] + 1):
        state = str(item["lifecycle_state"] or "UNKNOWN")
        state_icon = state_icon_map.get(state.upper(), "⚪️")
        display_name = html.escape(str(item["display_name"]))
        shape = html.escape(str(item["shape"]))
        compartment = html.escape(str(item["compartment_name"]))
        ip_address = html.escape(str(item["ip_address"]))
        lines.extend(
            [
                f"<b>{index}. {display_name}</b>",
                f"{state_icon} 状态：<code>{html.escape(state)}</code>",
                f"⚙️ 规格：<code>{shape}</code>",
                f"📁 Compartment：<code>{compartment}</code>",
                f"🌐 IP：<code>{ip_address}</code>",
                "",
            ]
        )
    lines.append("💡 点下面按钮可翻页、进详情、再做启停重启。")
    return "\n".join(lines).strip()


def list_instances(app_config: Optional[Dict[str, Any]] = None) -> None:
    try:
        data = list_instances_data(app_config)
        print(render_instances_cli(data))
    except Exception as e:
        print(f"❌ 获取实例列表失败: {e}")


def get_instance_detail_data(instance_ref: str, app_config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    config = get_oci_config(app_config)
    compute_client = get_compute_client(config)
    if (instance_ref or "").strip().lower().startswith("ocid1.instance."):
        detail = compute_client.get_instance(instance_ref.strip()).data
        instance = _instance_from_detail(detail, config)
    else:
        instance = _lookup_instance(instance_ref, app_config)
        detail = compute_client.get_instance(instance["id"]).data

    return {
        **instance,
        "fault_domain": getattr(detail, "fault_domain", "N/A"),
        "image_id": getattr(detail, "image_id", "N/A"),
        "memory_gbs": safe_get(getattr(detail, "shape_config", None), "memory_in_gbs", "N/A"),
        "ocpus": safe_get(getattr(detail, "shape_config", None), "ocpus", "N/A"),
        "source_details": getattr(getattr(detail, "source_details", None), "source_type", "N/A"),
        "time_created": getattr(detail, "time_created", instance.get("time_created")),
    }


def get_instance_detail(app_config: Optional[Dict[str, Any]] = None, instance_ref: Optional[str] = None) -> None:
    if not instance_ref:
        instance_ref = input("👉 请输入实例名称或 OCID: ").strip()
    try:
        detail = get_instance_detail_data(instance_ref, app_config)
        print_section("实例详情", "🖥️")
        print_kv("名称", detail["display_name"])
        print_kv("OCID", detail["id"])
        print_kv("状态", detail["lifecycle_state"])
        print_kv("Compartment", detail["compartment_name"])
        print_kv("可用区", detail["availability_domain"])
        print_kv("故障域", detail["fault_domain"])
        print_kv("规格", detail["shape"])
        print_kv("OCPU", detail["ocpus"])
        print_kv("内存(GB)", detail["memory_gbs"])
        print_kv("IP", detail["ip_address"])
        print_kv("镜像 ID", detail["image_id"])
        print_kv("启动源类型", detail["source_details"])
        print_kv("创建时间", format_datetime_compact(detail["time_created"]))
    except Exception as e:
        print(f"❌ 获取实例详情失败: {e}")


def render_instance_detail_telegram(detail: Dict[str, Any]) -> str:
    name = html.escape(str(detail["display_name"]))
    state = html.escape(str(detail["lifecycle_state"]))
    compartment = html.escape(str(detail["compartment_name"]))
    shape = html.escape(str(detail["shape"]))
    ip_address = html.escape(str(detail["ip_address"]))
    ad = html.escape(str(detail["availability_domain"]))
    fd = html.escape(str(detail["fault_domain"]))
    image_id = html.escape(str(detail["image_id"]))
    source_type = html.escape(str(detail["source_details"]))
    created_at = html.escape(format_datetime_compact(detail["time_created"]))
    ocid = html.escape(str(detail["id"]))

    lines = [
        "<b>🖥️ 实例详情</b>",
        f"<blockquote><b>{name}</b>\n状态：<code>{state}</code></blockquote>",
        "<b>📦 基础信息</b>",
        f"⚙️ 规格：<code>{shape}</code>",
        f"🧠 OCPU / 内存：<code>{detail['ocpus']} / {detail['memory_gbs']} GB</code>",
        f"🌐 IP：<code>{ip_address}</code>",
        f"📁 Compartment：<code>{compartment}</code>",
        "",
        "<b>🛰️ 部署信息</b>",
        f"🏢 可用区 / 故障域：<code>{ad} / {fd}</code>",
        f"🕒 创建时间：<code>{created_at}</code>",
        f"💿 镜像 ID：<code>{image_id}</code>",
        f"🚀 启动源类型：<code>{source_type}</code>",
        "",
        f"<b>🆔 实例 OCID</b>\n<code>{ocid}</code>",
    ]
    return "\n".join(lines)


def instance_action(app_config: Optional[Dict[str, Any]] = None, action: str = "start", instance_ref: Optional[str] = None, auto_approve: bool = False) -> None:
    if not instance_ref:
        instance_ref = input("👉 请输入实例名称或 OCID: ").strip()
    action_key = action.lower()
    oci_action = INSTANCE_ACTION_MAP.get(action_key)
    if not oci_action:
        print(f"❌ 不支持的实例动作: {action}")
        return

    try:
        data = list_instances_data(app_config)
        instance = _resolve_instance(data["items"], instance_ref)
        if not auto_approve:
            confirm = input(f"⚠️ 确认对实例 '{instance['display_name']}' 执行 {action_key} 吗？(y/n): ").strip().lower()
            if confirm != "y":
                print("🛑 已取消实例操作。")
                return

        result = execute_instance_action_data(action_key, instance["id"], app_config)
        print("✅ 实例动作已提交。")
        print_kv("实例名称", result["display_name"])
        print_kv("实例 OCID", result["id"])
        print_kv("动作", result["action"])
        print_kv("返回状态码", result["status"])
        print_kv("当前状态", result.get("current_state") or "未知")
        if result.get("recheck_error"):
            print_kv("状态复查", f"失败：{result['recheck_error']}")
        elif result.get("transitioning"):
            print_kv("状态提示", "实例仍在过渡态，可稍后再查详情")
    except Exception as e:
        print(f"❌ 实例操作失败: {e}")


def execute_instance_action_data(action: str, instance_ref: str, app_config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    action_key = action.lower()
    oci_action = INSTANCE_ACTION_MAP.get(action_key)
    if not oci_action:
        raise ValueError(f"不支持的实例动作: {action}")

    instance = _lookup_instance(instance_ref, app_config)
    config = get_oci_config(app_config)
    compute_client = get_compute_client(config)
    response = compute_client.instance_action(instance["id"], oci_action)
    recheck = _recheck_instance_state(instance["id"], app_config)
    current_state = recheck.get("state") or instance.get("lifecycle_state") or "UNKNOWN"
    return {
        "display_name": instance["display_name"],
        "id": instance["id"],
        "action": action_key,
        "status": getattr(response, "status", "N/A"),
        "current_state": current_state,
        "recheck_delay_seconds": recheck.get("recheck_delay_seconds"),
        "recheck_error": recheck.get("recheck_error"),
        "transitioning": _is_transition_state(current_state),
    }


def render_instance_action_telegram(result: Dict[str, Any]) -> str:
    action_label_map = {
        "start": "启动",
        "stop": "停止",
        "restart": "重启",
    }
    action = str(result["action"])
    action_label = action_label_map.get(action, action)
    current_state = html.escape(str(result.get("current_state") or "未知"))
    lines = [
        "<b>✅ 实例操作已提交</b>",
        f"<blockquote>实例：<b>{html.escape(str(result['display_name']))}</b>\n动作：<code>{html.escape(action_label)}</code>\n返回状态码：<code>{html.escape(str(result['status']))}</code></blockquote>",
        f"🧭 当前状态：<code>{current_state}</code>",
    ]
    if result.get("recheck_error"):
        lines.append(f"⚠️ 状态复查失败：<code>{html.escape(str(result['recheck_error']))}</code>")
        lines.append("ℹ️ 动作大概率已提交，但这次没拿到最新状态。可稍后点详情再看。")
    elif result.get("transitioning"):
        lines.append("⏳ 实例仍处于过渡态，OCI 侧还在处理。可稍后复查。")
    else:
        lines.append("✅ 已拿到一次最新状态回执。")
    lines.append(f"🆔 OCID：<code>{html.escape(str(result['id']))}</code>")
    return "\n".join(lines)
