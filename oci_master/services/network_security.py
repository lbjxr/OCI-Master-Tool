import html
import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

import oci

from oci_master.clients import get_compute_client, get_virtual_network_client
from oci_master.config import (
    get_active_profile_name,
    get_network_runtime_config,
    get_oci_config,
)
from oci_master.services.instances import _collect_instances, _lookup_instance, _resolve_instance
from oci_master.utils import build_text_table, format_datetime_compact, print_kv, print_section, truncate_text

TCP_PROTOCOL = "6"
TEMP_RULE_KIND = "oci-master-temp"


def _safe_str(value: Any, default: str = "N/A") -> str:
    text = str(value or "").strip()
    return text or default


def _protocol_name(protocol: Any) -> str:
    value = str(protocol or "").strip()
    return {
        "1": "ICMP",
        "6": "TCP",
        "17": "UDP",
        "all": "ALL",
    }.get(value.lower(), value or "N/A")


def _extract_rule_port_text(rule: Any) -> str:
    tcp_options = getattr(rule, "tcp_options", None)
    if tcp_options is None and isinstance(rule, dict):
        tcp_options = rule.get("tcp_options") or rule.get("tcpOptions")
    if tcp_options is not None:
        port_range = getattr(tcp_options, "destination_port_range", None)
        if port_range is None and isinstance(tcp_options, dict):
            port_range = tcp_options.get("destination_port_range") or tcp_options.get("destinationPortRange")
        if port_range is not None:
            min_port = getattr(port_range, "min", None)
            max_port = getattr(port_range, "max", None)
            if isinstance(port_range, dict):
                min_port = port_range.get("min", min_port)
                max_port = port_range.get("max", max_port)
            if min_port is not None and max_port is not None:
                if int(min_port) == int(max_port):
                    return str(int(min_port))
                return f"{int(min_port)}-{int(max_port)}"
    udp_options = getattr(rule, "udp_options", None)
    if udp_options is None and isinstance(rule, dict):
        udp_options = rule.get("udp_options") or rule.get("udpOptions")
    if udp_options is not None:
        port_range = getattr(udp_options, "destination_port_range", None)
        if port_range is None and isinstance(udp_options, dict):
            port_range = udp_options.get("destination_port_range") or udp_options.get("destinationPortRange")
        if port_range is not None:
            min_port = getattr(port_range, "min", None)
            max_port = getattr(port_range, "max", None)
            if isinstance(port_range, dict):
                min_port = port_range.get("min", min_port)
                max_port = port_range.get("max", max_port)
            if min_port is not None and max_port is not None:
                if int(min_port) == int(max_port):
                    return str(int(min_port))
                return f"{int(min_port)}-{int(max_port)}"
    return "ALL"


def _is_temp_rule(rule: Any) -> bool:
    description = str(getattr(rule, "description", None) or (rule.get("description") if isinstance(rule, dict) else "") or "")
    return description.startswith(TEMP_RULE_KIND)


def _build_ingress_rule_summary_item(rule: Any, target: Dict[str, Any], rule_index: int) -> Dict[str, Any]:
    direction = str(getattr(rule, "direction", None) or (rule.get("direction") if isinstance(rule, dict) else "INGRESS") or "INGRESS").upper()
    protocol = str(getattr(rule, "protocol", None) or (rule.get("protocol") if isinstance(rule, dict) else "") or "")
    source = str(getattr(rule, "source", None) or (rule.get("source") if isinstance(rule, dict) else "") or "")
    description = str(getattr(rule, "description", None) or (rule.get("description") if isinstance(rule, dict) else "") or "")
    return {
        "rule_key": f"{target['target_scope']}#{rule_index}",
        "target_scope": target["target_scope"],
        "target_type": target["target_type"],
        "target_name": target["target_name"],
        "target_id": target["target_id"],
        "via": target["via"],
        "protocol": _protocol_name(protocol),
        "protocol_raw": protocol,
        "port_text": _extract_rule_port_text(rule),
        "source": source or "N/A",
        "description": description,
        "direction": direction,
        "is_temp": _is_temp_rule(rule),
        "is_ingress": direction == "INGRESS",
        "is_stateless": bool(getattr(rule, "is_stateless", None) or (rule.get("is_stateless") if isinstance(rule, dict) else False) or False),
    }


def _collect_target_ingress_rules_summary(target_choices: Sequence[Dict[str, Any]], network_client: Any) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for target in list(target_choices or []):
        if target.get("target_type") == "nsg":
            nsg = network_client.get_network_security_group(target["target_id"]).data
            for index, rule in enumerate(list(getattr(nsg, "security_rules", []) or []), start=1):
                item = _build_ingress_rule_summary_item(rule, target, index)
                if item["is_ingress"]:
                    items.append(item)
            continue
        security_list = network_client.get_security_list(target["target_id"]).data
        for index, rule in enumerate(list(getattr(security_list, "ingress_security_rules", []) or []), start=1):
            item = _build_ingress_rule_summary_item(rule, target, index)
            item["is_ingress"] = True
            item["direction"] = "INGRESS"
            items.append(item)
    return items


def _paginate_rule_summary(items: Sequence[Dict[str, Any]], page: int = 1, page_size: int = 8, temp_only: bool = False) -> Dict[str, Any]:
    values = [dict(item) for item in list(items or []) if (item.get("is_temp") if temp_only else True)]
    safe_page_size = max(1, int(page_size or 1))
    total_items = len(values)
    total_pages = max(1, math.ceil(total_items / safe_page_size))
    current_page = min(max(1, int(page or 1)), total_pages)
    start = (current_page - 1) * safe_page_size
    end = start + safe_page_size
    return {
        "items": values[start:end],
        "page": current_page,
        "page_size": safe_page_size,
        "total_items": total_items,
        "total_pages": total_pages,
        "has_prev": current_page > 1,
        "has_next": current_page < total_pages,
        "temp_only": temp_only,
    }


def get_instance_ingress_rules_data(instance_ref: str, app_config: Optional[Dict[str, Any]] = None, page: int = 1, page_size: int = 8, temp_only: bool = False) -> Dict[str, Any]:
    overview = _collect_instance_network_objects(instance_ref, app_config)
    pagination = _paginate_rule_summary(overview.get("rule_summary", []), page=page, page_size=page_size, temp_only=temp_only)
    return {
        "profile": overview["profile"],
        "instance": overview["instance"],
        "target_choices": overview.get("target_choices", []),
        "items": pagination["items"],
        "pagination": pagination,
        "total_rules": overview.get("ingress_rule_count", 0),
        "temp_rule_count": overview.get("temp_rule_count", 0),
        "temp_only": temp_only,
    }


def render_instance_ingress_rules_cli(data: Dict[str, Any]) -> str:
    pagination = data["pagination"]
    parts = [
        "\n" + "=" * 76,
        "🛡️ 实例现有入站规则",
        f"实例: {data['instance']['display_name']} | Profile: {data['profile']}",
        f"规则总数: {data['total_rules']} | 本工具临时规则: {data['temp_rule_count']} | 当前页: {pagination['page']}/{pagination['total_pages']}",
        f"过滤: {'仅临时规则' if data.get('temp_only') else '全部入站规则'}",
    ]
    if not data["items"]:
        parts.append("(当前页无规则)")
        return "\n".join(parts)
    rows = []
    for idx, item in enumerate(data["items"], start=1 + (pagination['page'] - 1) * pagination['page_size']):
        rows.append([
            idx,
            item["protocol"],
            item["port_text"],
            truncate_text(item["source"], 18),
            "临时" if item["is_temp"] else "-",
            "NSG" if item["target_type"] == "nsg" else "SL",
            truncate_text(item["target_name"], 18),
        ])
    parts.append(build_text_table(["#", "协议", "端口", "来源", "标记", "挂载", "目标对象"], rows))
    parts.append("")
    parts.append("详情字段：端口 / 来源 CIDR / 协议 / 是否本工具临时规则 / 挂载对象（NSG/SL）")
    parts.append("CLI action: instance_rules:<实例>[:page] 或 instance_temp_rules:<实例>[:page]")
    return "\n".join(parts)


def render_instance_ingress_rules_telegram(data: Dict[str, Any]) -> str:
    pagination = data["pagination"]
    instance = data["instance"]
    selected_rule_keys = {str(item).strip() for item in list(data.get("selected_rule_keys", []) or []) if str(item).strip()}
    lines = [
        "<b>🛡️ 网络 / 安全向导</b>",
        "<b>现有入站规则</b>",
        f"<blockquote>实例：<b>{html.escape(str(instance['display_name']))}</b>\n状态：<code>{html.escape(str(instance['lifecycle_state']))}</code> · Profile：<code>{html.escape(str(data['profile']))}</code>\n引用：<code>{html.escape(_short_ref(instance.get('id')))}</code></blockquote>",
        f"📊 规则：全部 <code>{int(data.get('total_rules', 0))}</code> · 本工具临时 <code>{int(data.get('temp_rule_count', 0))}</code>",
        f"📄 当前页：<code>{pagination['page']}/{pagination['total_pages']}</code> · {'仅临时规则' if data.get('temp_only') else '全部入站规则'}",
        "🧭 重点看：协议、端口、来源 CIDR、是否本工具临时规则。",
    ]
    if data.get("temp_only"):
        lines.append(f"☑️ 页内已选：<b>{len(selected_rule_keys)}</b> 条")
        lines.append("💡 这一页支持多选本工具临时规则，再统一预览 / 确认 / 删除。")
    if not data["items"]:
        lines.append("")
        lines.append("ℹ️ 当前页没有可显示的入站规则。")
        return "\n".join(lines).strip()
    lines.append("")
    base_index = (pagination["page"] - 1) * pagination["page_size"]
    for offset, item in enumerate(data["items"], start=1):
        index = base_index + offset
        temp_tag = "🧪临时 · " if item.get("is_temp") else ""
        selected_tag = " ✅已选" if item.get("rule_key") in selected_rule_keys else ""
        line = f"<b>{index}. {temp_tag}{html.escape(str(item['protocol']))}/{html.escape(str(item['port_text']))}{selected_tag}</b> · 来源 <code>{html.escape(str(item['source']))}</code>"
        description = str(item.get("description") or "").strip()
        if description:
            line += f"\n└ 描述 <code>{html.escape(description[:120])}</code>"
        lines.append(line)
    return "\n".join(lines).strip()


def preview_cleanup_selected_temp_rules_data(instance_ref: str, rule_keys: Sequence[str], app_config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    overview = _collect_instance_network_objects(instance_ref, app_config)
    selected_keys = {str(item).strip() for item in list(rule_keys or []) if str(item).strip()}
    selected = [dict(item) for item in overview.get("rule_summary", []) if item.get("rule_key") in selected_keys and item.get("is_temp")]
    selected.sort(key=lambda item: (item["target_scope"], item["rule_key"]))
    return {
        "action": "cleanup_selected_temp_rules",
        "profile": overview["profile"],
        "instance": overview["instance"],
        "selected_rules": selected,
        "selected_count": len(selected),
    }


def render_cleanup_selected_preview_telegram(preview: Dict[str, Any]) -> str:
    lines = [
        "<b>🧹 网络 / 安全向导</b>",
        "<b>选择式清理临时规则 · 预览确认</b>",
        f"<blockquote>实例：<b>{html.escape(str(preview['instance']['display_name']))}</b>\nProfile：<code>{html.escape(str(preview['profile']))}</code></blockquote>",
        f"🔎 已选临时规则：<b>{int(preview.get('selected_count', 0))}</b>",
    ]
    if not preview["selected_rules"]:
        lines.append("ℹ️ 当前没有选中任何可清理的本工具临时规则。")
        return "\n".join(lines)
    for item in preview["selected_rules"][:8]:
        target_tag = "NSG" if item.get("target_type") == "nsg" else "SL"
        lines.append(f"• <code>{html.escape(str(item['protocol']))}/{html.escape(str(item['port_text']))}</code> · <code>{html.escape(str(item['source']))}</code> · <code>{html.escape(target_tag)}:{html.escape(str(item['target_name']))}</code>")
    if len(preview["selected_rules"]) > 8:
        lines.append(f"• …其余 <b>{len(preview['selected_rules']) - 8}</b> 条已折叠")
    lines.append("⚠️ 只会删除已选中的本工具临时规则，不碰其他常规规则。")
    return "\n".join(lines)


def apply_cleanup_selected_temp_rules_data(instance_ref: str, rule_keys: Sequence[str], app_config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    preview = preview_cleanup_selected_temp_rules_data(instance_ref, rule_keys, app_config)
    if not preview["selected_rules"]:
        return {
            **preview,
            "removed_count": 0,
            "status": "no-match",
            "message": "未选中任何可清理的本工具临时规则。",
            "remaining_temp_rule_count": len([item for item in _collect_instance_network_objects(instance_ref, app_config).get("rule_summary", []) if item.get("is_temp")]),
            "remaining_total_rules": len(_collect_instance_network_objects(instance_ref, app_config).get("rule_summary", [])),
        }
    config = get_oci_config(app_config)
    network_client = get_virtual_network_client(config)
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for item in preview["selected_rules"]:
        grouped.setdefault(str(item["target_scope"]), []).append(item)
    removed_count = 0
    for items in grouped.values():
        target = items[0]
        selected_indexes = {str(item["rule_key"]).split("#", 1)[1] for item in items}
        if target["target_type"] == "nsg":
            nsg = network_client.get_network_security_group(target["target_id"]).data
            remove_ids: List[str] = []
            for index, rule in enumerate(list(getattr(nsg, "security_rules", []) or []), start=1):
                if str(index) in selected_indexes and str(getattr(rule, "direction", "") or "INGRESS").upper() == "INGRESS" and _is_temp_rule(rule):
                    rule_id = str(getattr(rule, "id", "") or "").strip()
                    if rule_id:
                        remove_ids.append(rule_id)
                    continue
            if remove_ids:
                network_client.remove_network_security_group_security_rules(
                    target["target_id"],
                    oci.core.models.RemoveNetworkSecurityGroupSecurityRulesDetails(security_rule_ids=remove_ids),
                )
                refreshed_nsg = network_client.get_network_security_group(target["target_id"]).data
                remaining_ids = {str(getattr(rule, "id", "")) for rule in getattr(refreshed_nsg, "security_rules", []) or []}
                if remaining_ids.intersection(remove_ids):
                    raise RuntimeError("NSG 规则删除后复核失败，目标规则仍存在")
                removed_count += len(remove_ids)
            continue
        security_list_response = network_client.get_security_list(target["target_id"])
        security_list = security_list_response.data
        security_list_etag = (getattr(security_list_response, "headers", {}) or {}).get("etag")
        if not security_list_etag:
            raise RuntimeError("Security List 缺少 ETag，已停止更新以避免覆盖并发修改")
        keep_ingress_rules: List[Any] = []
        for index, rule in enumerate(list(getattr(security_list, "ingress_security_rules", []) or []), start=1):
            if str(index) in selected_indexes and _is_temp_rule(rule):
                removed_count += 1
                continue
            keep_ingress_rules.append(rule)
        try:
            network_client.update_security_list(
                target["target_id"],
                oci.core.models.UpdateSecurityListDetails(
                    display_name=getattr(security_list, "display_name", None),
                    defined_tags=getattr(security_list, "defined_tags", None),
                    freeform_tags=getattr(security_list, "freeform_tags", None),
                    egress_security_rules=list(getattr(security_list, "egress_security_rules", []) or []),
                    ingress_security_rules=keep_ingress_rules,
                ),
                if_match=security_list_etag,
            )
        except oci.exceptions.ServiceError as exc:
            if getattr(exc, "status", None) == 412:
                raise RuntimeError("Security List 在确认后已被其他进程修改，未覆盖外部变更，请重新读取并确认") from exc
            raise
    overview = _collect_instance_network_objects(instance_ref, app_config)
    return {
        **preview,
        "removed_count": removed_count,
        "status": "updated",
        "message": "已删除选中的本工具临时规则。",
        "remaining_temp_rule_count": len([item for item in overview.get("rule_summary", []) if item.get("is_temp")]),
        "remaining_total_rules": len(overview.get("rule_summary", [])),
    }


def render_cleanup_selected_result_telegram(result: Dict[str, Any]) -> str:
    return "\n".join([
        "<b>🧹 网络 / 安全向导</b>",
        "<b>选择式清理临时规则 · 已处理</b>",
        f"<blockquote>实例：<b>{html.escape(str(result['instance']['display_name']))}</b>\nProfile：<code>{html.escape(str(result['profile']))}</code></blockquote>",
        f"🧾 处理结果：{html.escape(str(result.get('message', '完成')))}",
        f"🗑️ 删除数量：<b>{int(result.get('removed_count', 0) or 0)}</b>",
        f"📉 剩余本工具临时规则：<b>{int(result.get('remaining_temp_rule_count', 0) or 0)}</b>",
        f"📊 当前入站规则总数：<code>{int(result.get('remaining_total_rules', 0) or 0)}</code>",
        f"📡 返回状态：<code>{html.escape(str(result.get('status', 'N/A')))}</code>",
    ])


def _collect_instance_network_objects(instance_ref: str, app_config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    instance = _lookup_instance(instance_ref, app_config)
    config = get_oci_config(app_config)
    compute_client = get_compute_client(config)
    network_client = get_virtual_network_client(config)

    attachments = oci.pagination.list_call_get_all_results(
        compute_client.list_vnic_attachments,
        compartment_id=instance["compartment_id"],
        instance_id=instance["id"],
    ).data

    vnics: List[Dict[str, Any]] = []
    unique_subnet_ids: List[str] = []
    unique_nsg_ids: List[str] = []
    unique_security_list_ids: List[str] = []
    subnet_name_map: Dict[str, str] = {}
    security_list_name_map: Dict[str, str] = {}

    for attachment in sorted(attachments, key=lambda item: (not bool(getattr(item, "is_primary", False)), getattr(item, "time_created", None) or "")):
        vnic = network_client.get_vnic(attachment.vnic_id).data
        subnet = network_client.get_subnet(vnic.subnet_id).data
        security_lists: List[Dict[str, Any]] = []
        for security_list_id in list(getattr(subnet, "security_list_ids", []) or []):
            if security_list_id not in unique_security_list_ids:
                unique_security_list_ids.append(security_list_id)
            security_list = network_client.get_security_list(security_list_id).data
            display_name = _safe_str(getattr(security_list, "display_name", None), security_list_id)
            security_list_name_map[security_list_id] = display_name
            security_lists.append(
                {
                    "id": security_list_id,
                    "display_name": display_name,
                    "ingress_count": len(list(getattr(security_list, "ingress_security_rules", []) or [])),
                    "egress_count": len(list(getattr(security_list, "egress_security_rules", []) or [])),
                }
            )

        nsgs: List[Dict[str, Any]] = []
        for nsg_id in list(getattr(vnic, "nsg_ids", []) or []):
            if nsg_id not in unique_nsg_ids:
                unique_nsg_ids.append(nsg_id)
            nsg = network_client.get_network_security_group(nsg_id).data
            nsgs.append(
                {
                    "id": nsg_id,
                    "display_name": _safe_str(getattr(nsg, "display_name", None), nsg_id),
                    "rule_count": len(list(getattr(nsg, "security_rules", []) or [])),
                }
            )

        subnet_id = str(vnic.subnet_id)
        if subnet_id not in unique_subnet_ids:
            unique_subnet_ids.append(subnet_id)
        subnet_name_map[subnet_id] = _safe_str(getattr(subnet, "display_name", None), subnet_id)

        vnics.append(
            {
                "attachment_id": getattr(attachment, "id", "N/A"),
                "is_primary": bool(getattr(attachment, "is_primary", False)),
                "display_name": _safe_str(getattr(vnic, "display_name", None), str(vnic.id)),
                "id": str(vnic.id),
                "private_ip": _safe_str(getattr(vnic, "private_ip", None)),
                "public_ip": _safe_str(getattr(vnic, "public_ip", None)),
                "subnet_id": subnet_id,
                "subnet_name": subnet_name_map[subnet_id],
                "vlan_id": _safe_str(getattr(vnic, "vlan_id", None)),
                "nsgs": nsgs,
                "security_lists": security_lists,
            }
        )

    target_choices: List[Dict[str, Any]] = []
    primary_vnic = next((item for item in vnics if item["is_primary"]), vnics[0] if vnics else None)
    if primary_vnic:
        for nsg in primary_vnic["nsgs"]:
            target_choices.append(
                {
                    "target_type": "nsg",
                    "target_id": nsg["id"],
                    "target_name": nsg["display_name"],
                    "target_scope": f"nsg:{nsg['id']}",
                    "via": f"主 VNIC / NSG {nsg['display_name']}",
                    "modifiable": True,
                }
            )
        for security_list in primary_vnic["security_lists"]:
            target_choices.append(
                {
                    "target_type": "security_list",
                    "target_id": security_list["id"],
                    "target_name": security_list["display_name"],
                    "target_scope": f"sl:{security_list['id']}",
                    "via": f"主 VNIC 所在 Subnet / Security List {security_list['display_name']}",
                    "modifiable": True,
                }
            )

    rule_summary = _collect_target_ingress_rules_summary(target_choices, network_client)

    return {
        "profile": get_active_profile_name(app_config or {}),
        "instance": instance,
        "vnics": vnics,
        "subnet_count": len(unique_subnet_ids),
        "nsg_count": len(unique_nsg_ids),
        "security_list_count": len(unique_security_list_ids),
        "target_choices": target_choices,
        "subnet_name_map": subnet_name_map,
        "security_list_name_map": security_list_name_map,
        "rule_summary": rule_summary,
        "ingress_rule_count": len(rule_summary),
        "temp_rule_count": len([item for item in rule_summary if item.get("is_temp")]),
    }


def get_instance_network_overview_data(instance_ref: str, app_config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return _collect_instance_network_objects(instance_ref, app_config)


def render_instance_network_overview_cli(data: Dict[str, Any]) -> str:
    instance = data["instance"]
    parts = [
        "\n" + "=" * 76,
        f"🌐 实例网络 / 安全概览（Profile: {data['profile']}）",
        f"实例: {instance['display_name']} | 状态: {instance['lifecycle_state']} | Compartment: {instance['compartment_name']}",
        f"VNIC: {len(data['vnics'])} | Subnet: {data['subnet_count']} | NSG: {data['nsg_count']} | Security List: {data['security_list_count']}",
        "",
    ]

    vnic_rows: List[List[Any]] = []
    for vnic in data["vnics"]:
        vnic_rows.append(
            [
                ("主" if vnic["is_primary"] else "附"),
                truncate_text(vnic["display_name"], 18),
                truncate_text(vnic["private_ip"], 16),
                truncate_text(vnic["public_ip"], 16),
                truncate_text(vnic["subnet_name"], 18),
                len(vnic["nsgs"]),
                len(vnic["security_lists"]),
            ]
        )
    if vnic_rows:
        parts.append(build_text_table(["类型", "VNIC", "私网IP", "公网IP", "Subnet", "NSG数", "SL数"], vnic_rows))
        parts.append("")

    for index, vnic in enumerate(data["vnics"], start=1):
        parts.append(f"[{index}] {'主' if vnic['is_primary'] else '附'} VNIC: {vnic['display_name']}")
        parts.append(f"    VNIC OCID: {vnic['id']}")
        parts.append(f"    Subnet: {vnic['subnet_name']} ({vnic['subnet_id']})")
        parts.append(f"    IP: private={vnic['private_ip']} | public={vnic['public_ip']}")
        if vnic["nsgs"]:
            parts.append("    NSG:")
            for nsg in vnic["nsgs"]:
                parts.append(f"      - {nsg['display_name']} | rules={nsg['rule_count']} | {nsg['id']}")
        else:
            parts.append("    NSG: (无)")
        if vnic["security_lists"]:
            parts.append("    Security Lists:")
            for security_list in vnic["security_lists"]:
                parts.append(
                    f"      - {security_list['display_name']} | ingress={security_list['ingress_count']} egress={security_list['egress_count']} | {security_list['id']}"
                )
        else:
            parts.append("    Security Lists: (无)")
        parts.append("")

    if data["target_choices"]:
        parts.append("可修改目标（仅主 VNIC 关联对象，低风险范围）：")
        for target in data["target_choices"]:
            parts.append(f"- {target['target_scope']} | {target['via']}")
        parts.append("")
        parts.append("建议动作示例：")
        parts.append("- run open_ingress_preview:<实例>:22:1.2.3.4/32")
        parts.append("- run open_ingress_apply:<实例>:22:1.2.3.4/32")
        parts.append("- run cleanup_temp_rules_preview:<实例>:22:1.2.3.4/32")
        parts.append("- run cleanup_temp_rules_apply:<实例>:22:1.2.3.4/32")
    else:
        parts.append("当前主 VNIC 未发现可直接修改的 NSG / Security List，对此实例只开放查看。")

    return "\n".join(parts).strip()


def _short_ref(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return "N/A"
    return text if len(text) <= 18 else f"{text[:8]}...{text[-6:]}"


def render_instance_network_overview_telegram(data: Dict[str, Any]) -> str:
    instance = data["instance"]
    primary_vnic = next((item for item in data["vnics"] if item.get("is_primary")), data["vnics"][0] if data["vnics"] else None)
    lines = [
        "<b>🌐 网络 / 安全向导</b>",
        "<b>实例网络 / 安全概览</b>",
        f"<blockquote>实例：<b>{html.escape(str(instance['display_name']))}</b>\n状态：<code>{html.escape(str(instance['lifecycle_state']))}</code> · Profile：<code>{html.escape(str(data['profile']))}</code>\n引用：<code>{html.escape(_short_ref(instance.get('id')))}</code></blockquote>",
        f"📦 对象数：<code>VNIC {len(data['vnics'])}</code> · <code>Subnet {data['subnet_count']}</code> · <code>NSG {data['nsg_count']}</code> · <code>SL {data['security_list_count']}</code>",
        f"🛡️ 入站规则：全部 <code>{int(data.get('ingress_rule_count', 0))}</code> · 本工具临时 <code>{int(data.get('temp_rule_count', 0))}</code>",
        "🧭 当前步骤：先看主 VNIC 关联对象，再继续查看现有规则、放行临时端口或清理临时规则。",
        "⚠️ 边界：仅主 VNIC 关联对象、仅 ingress、仅常见 TCP 端口，不改附属 VNIC / IPv6 / 路由 / 子网结构。",
    ]

    if primary_vnic:
        lines.extend(
            [
                "",
                "<b>🧩 主 VNIC 摘要</b>",
                f"• 名称：<code>{html.escape(primary_vnic['display_name'])}</code>",
                f"• IP：<code>{html.escape(primary_vnic['private_ip'])}</code>"
                + (f" / <code>{html.escape(primary_vnic['public_ip'])}</code>" if str(primary_vnic.get('public_ip') or '').strip() else " / <code>(无公网)</code>"),
                f"• Subnet：<code>{html.escape(primary_vnic['subnet_name'])}</code>",
            ]
        )
        if primary_vnic["nsgs"]:
            nsg_summary = "；".join(
                f"{html.escape(nsg['display_name'])}({int(nsg['rule_count'])})" for nsg in primary_vnic["nsgs"][:3]
            )
            if len(primary_vnic["nsgs"]) > 3:
                nsg_summary += f"；…共 {len(primary_vnic['nsgs'])} 个"
            lines.append(f"• NSG：<code>{nsg_summary}</code>")
        else:
            lines.append("• NSG：<code>(无)</code>")
        if primary_vnic["security_lists"]:
            sl_summary = "；".join(
                f"{html.escape(item['display_name'])}(in {int(item['ingress_count'])}/out {int(item['egress_count'])})"
                for item in primary_vnic["security_lists"][:2]
            )
            if len(primary_vnic["security_lists"]) > 2:
                sl_summary += f"；…共 {len(primary_vnic['security_lists'])} 个"
            lines.append(f"• Security List：<code>{sl_summary}</code>")
        else:
            lines.append("• Security List：<code>(无)</code>")

    extra_vnic_count = max(len(data["vnics"]) - (1 if primary_vnic else 0), 0)
    if extra_vnic_count > 0:
        lines.append(f"• 其余 VNIC：<code>{extra_vnic_count}</code> 个，已省略详细展开")

    lines.append("")
    if data["target_choices"]:
        lines.append("<b>🎯 当前可操作目标</b>")
        for target in data["target_choices"][:4]:
            lines.append(f"• <code>{html.escape(target['target_scope'])}</code> · {html.escape(target['via'])}")
        if len(data["target_choices"]) > 4:
            lines.append(f"• …其余 <code>{len(data['target_choices']) - 4}</code> 个目标已折叠")
        lines.extend(
            [
                "",
                "💡 想看更细一点，可点“展开更多明细”。",
                "💡 下方按钮会沿用当前实例，继续同一条向导流。",
            ]
        )
    else:
        lines.append("ℹ️ 当前主 VNIC 没有关联可安全修改的 NSG / Security List，这一页先只提供查看。")

    return "\n".join(lines).strip()


def _chunk_items(items: Sequence[Any], chunk_size: int) -> List[List[Any]]:
    safe_chunk_size = max(1, int(chunk_size or 1))
    values = list(items or [])
    return [values[index:index + safe_chunk_size] for index in range(0, len(values), safe_chunk_size)]


def _build_network_detail_pages(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    pages: List[Dict[str, Any]] = []
    for index, vnic in enumerate(data["vnics"], start=1):
        role = "主 VNIC" if vnic.get("is_primary") else f"附属 VNIC {index}"
        pages.append(
            {
                "kind": "vnic",
                "title": role,
                "vnic_index": index,
                "vnic": vnic,
            }
        )

        nsg_chunks = _chunk_items(vnic.get("nsgs", []), 3)
        if nsg_chunks:
            total = len(nsg_chunks)
            for chunk_index, chunk in enumerate(nsg_chunks, start=1):
                pages.append(
                    {
                        "kind": "nsg",
                        "title": f"{role} · NSG {chunk_index}/{total}",
                        "vnic_index": index,
                        "vnic": vnic,
                        "items": chunk,
                        "chunk_index": chunk_index,
                        "chunk_total": total,
                    }
                )

        sl_chunks = _chunk_items(vnic.get("security_lists", []), 2)
        if sl_chunks:
            total = len(sl_chunks)
            for chunk_index, chunk in enumerate(sl_chunks, start=1):
                pages.append(
                    {
                        "kind": "security_list",
                        "title": f"{role} · Security List {chunk_index}/{total}",
                        "vnic_index": index,
                        "vnic": vnic,
                        "items": chunk,
                        "chunk_index": chunk_index,
                        "chunk_total": total,
                    }
                )

    if not pages:
        pages.append({
            "kind": "empty",
            "title": "无可展开对象",
        })
    return pages


def get_instance_network_detail_pages(data: Dict[str, Any]) -> Dict[str, Any]:
    pages = _build_network_detail_pages(data)
    return {
        "pages": pages,
        "total_pages": len(pages),
    }


def render_instance_network_details_telegram(data: Dict[str, Any], page: int = 1) -> str:
    instance = data["instance"]
    detail_pages = get_instance_network_detail_pages(data)
    pages = detail_pages["pages"]
    total_pages = detail_pages["total_pages"]
    current_page = min(max(1, int(page or 1)), total_pages)
    current = pages[current_page - 1]

    lines = [
        "<b>🌐 网络 / 安全向导</b>",
        "<b>更多网络明细</b>",
        f"<blockquote>实例：<b>{html.escape(str(instance['display_name']))}</b>\n状态：<code>{html.escape(str(instance['lifecycle_state']))}</code> · Profile：<code>{html.escape(str(data['profile']))}</code>\n引用：<code>{html.escape(_short_ref(instance.get('id')))}</code></blockquote>",
        f"📄 明细页：<code>{current_page}/{total_pages}</code> · <b>{html.escape(str(current['title']))}</b>",
        "🧭 一次只展开一小段，适合 Telegram 小屏来回翻。",
        "⚠️ 仍然只做查看；可修改边界不变，仍限主 VNIC 关联对象。",
        "",
    ]

    if current["kind"] == "empty":
        lines.append("ℹ️ 当前没有可展开的 VNIC / NSG / Security List 明细。")
        return "\n".join(lines).strip()

    if current["kind"] in {"vnic", "nsg", "security_list"}:
        vnic = current["vnic"]
        lines.extend(
            [
                f"<b>🧩 {html.escape(str(current['title']))}</b>",
                f"• 名称：<code>{html.escape(str(vnic['display_name']))}</code>",
                f"• 引用：<code>{html.escape(_short_ref(vnic.get('id')))}</code>",
                f"• IP：<code>{html.escape(str(vnic['private_ip']))}</code>"
                + (f" / <code>{html.escape(str(vnic['public_ip']))}</code>" if str(vnic.get('public_ip') or '').strip() and str(vnic.get('public_ip')) != 'N/A' else " / <code>(无公网)</code>"),
                f"• Subnet：<code>{html.escape(str(vnic['subnet_name']))}</code>",
                f"• NSG 数：<code>{len(vnic.get('nsgs', []))}</code> · Security List 数：<code>{len(vnic.get('security_lists', []))}</code>",
            ]
        )

    if current["kind"] == "vnic":
        lines.extend(
            [
                "",
                "💡 这一页先看 VNIC 基本信息。",
                "💡 继续翻页可看这个 VNIC 下的 NSG / Security List 分段明细。",
            ]
        )
    elif current["kind"] == "nsg":
        lines.extend(["", "<b>🛡️ NSG 明细</b>"])
        for nsg in current.get("items", []):
            lines.append(
                f"• <code>{html.escape(str(nsg['display_name']))}</code> · rules <code>{int(nsg['rule_count'])}</code> · <code>{html.escape(_short_ref(nsg.get('id')))}</code>"
            )
    elif current["kind"] == "security_list":
        lines.extend(["", "<b>📚 Security List 明细</b>"])
        for security_list in current.get("items", []):
            lines.append(
                f"• <code>{html.escape(str(security_list['display_name']))}</code> · in <code>{int(security_list['ingress_count'])}</code> / out <code>{int(security_list['egress_count'])}</code> · <code>{html.escape(_short_ref(security_list.get('id')))}</code>"
            )

    return "\n".join(lines).strip()


def show_instance_network_overview(app_config: Optional[Dict[str, Any]] = None, instance_ref: Optional[str] = None) -> None:
    if not instance_ref:
        instance_ref = input("👉 请输入实例名称或 OCID: ").strip()
    try:
        print(render_instance_network_overview_cli(get_instance_network_overview_data(instance_ref, app_config)))
    except Exception as exc:
        print(f"❌ 获取实例网络/安全概览失败: {exc}")


def _normalize_port(port: Any, allowed_ports: Sequence[int]) -> int:
    try:
        value = int(str(port).strip())
    except Exception as exc:
        raise ValueError("端口必须是整数") from exc
    if value < 1 or value > 65535:
        raise ValueError(f"端口超出范围：{value}，允许范围为 1-65535")
    return value


def _normalize_source_cidr(source: Optional[str], default_source_cidr: str, allow_public_cidr: bool = False) -> str:
    value = str(source or default_source_cidr or "").strip()
    if not value:
        raise ValueError("必须提供来源 CIDR，例如 1.2.3.4/32")
    if "/" not in value:
        raise ValueError("来源必须是 CIDR 格式，例如 1.2.3.4/32")

    try:
        import ipaddress

        network = ipaddress.ip_network(value, strict=False)
    except Exception as exc:
        raise ValueError(f"CIDR 不合法：{value}。示例：1.2.3.4/32") from exc

    if network.version != 4:
        raise ValueError(f"当前仅支持 IPv4 CIDR，暂不支持：{value}")
    if str(network) == "0.0.0.0/0" and not allow_public_cidr:
        raise ValueError("公网 0.0.0.0/0 默认禁止，必须显式启用 allow_public_cidr")

    normalized = str(network)
    if "/" not in normalized:
        raise ValueError("CIDR 解析失败，请使用类似 1.2.3.4/32 的格式")
    return normalized


def _build_temp_rule_description(port: int, source_cidr: str, profile: str) -> str:
    return f"{TEMP_RULE_KIND} profile={profile} tcp/{port} from {source_cidr}"


def _select_target(data: Dict[str, Any], target_scope: Optional[str]) -> Dict[str, Any]:
    choices = data.get("target_choices", []) or []
    if not choices:
        raise ValueError("当前实例主 VNIC 没有关联可安全修改的 NSG / Security List")

    if not target_scope or str(target_scope).strip().lower() == "auto":
        nsg_choice = next((item for item in choices if item["target_type"] == "nsg"), None)
        return nsg_choice or choices[0]

    normalized = str(target_scope).strip()
    for item in choices:
        if normalized in {item["target_scope"], item["target_id"]}:
            return item
    raise ValueError(f"未找到目标对象：{target_scope}")


def _build_tcp_ingress_rule_model(port: int, source_cidr: str, description: str) -> Dict[str, Any]:
    return {
        "description": description,
        "is_stateless": False,
        "protocol": TCP_PROTOCOL,
        "source": source_cidr,
        "source_type": "CIDR_BLOCK",
        "tcp_options": {
            "destination_port_range": {"min": port, "max": port},
        },
    }


def _extract_rule_port(rule: Any) -> Optional[int]:
    tcp_options = getattr(rule, "tcp_options", None)
    if tcp_options is None and isinstance(rule, dict):
        tcp_options = rule.get("tcp_options") or rule.get("tcpOptions")
    if tcp_options is not None:
        port_range = getattr(tcp_options, "destination_port_range", None)
        if port_range is None and isinstance(tcp_options, dict):
            port_range = tcp_options.get("destination_port_range") or tcp_options.get("destinationPortRange")
        if port_range is not None:
            min_port = getattr(port_range, "min", None)
            max_port = getattr(port_range, "max", None)
            if isinstance(port_range, dict):
                min_port = port_range.get("min", min_port)
                max_port = port_range.get("max", max_port)
            if min_port is not None and max_port is not None and int(min_port) == int(max_port):
                return int(min_port)

    # 兼容某些 Security List 规则：OCI SDK 返回 tcp_options.destination_port_range 为 null，
    # 但 description 仍保留了 `tcp/<port>` 打标。这里做保守 fallback，只解析单端口临时规则描述。
    import re
    description = str(getattr(rule, "description", None) or (rule.get("description") if isinstance(rule, dict) else "") or "")
    match = re.search(r"\btcp/(\d{1,5})\b", description)
    if match:
        try:
            value = int(match.group(1))
            if 1 <= value <= 65535:
                return value
        except Exception:
            return None
    return None


def _rule_matches(rule: Any, port: int, source_cidr: str, description_prefix: str) -> bool:
    protocol = str(getattr(rule, "protocol", None) or (rule.get("protocol") if isinstance(rule, dict) else "") or "")
    if protocol != TCP_PROTOCOL:
        return False
    source = str(getattr(rule, "source", None) or (rule.get("source") if isinstance(rule, dict) else "") or "")
    if source != source_cidr:
        return False
    description = str(getattr(rule, "description", None) or (rule.get("description") if isinstance(rule, dict) else "") or "")
    if not description.startswith(TEMP_RULE_KIND):
        return False

    exact_description = str(description_prefix or "").strip()
    if exact_description and description.startswith(exact_description):
        return _extract_rule_port(rule) == port

    # 兼容旧描述或轻微格式差异：只要是本工具临时规则、端口一致、CIDR 一致，就允许匹配清理
    return _extract_rule_port(rule) == port


def preview_open_ingress_rule_data(
    instance_ref: str,
    port: Any,
    source_cidr: Optional[str] = None,
    app_config: Optional[Dict[str, Any]] = None,
    target_scope: Optional[str] = None,
) -> Dict[str, Any]:
    runtime = get_network_runtime_config(app_config or {})
    normalized_port = _normalize_port(port, runtime["quick_open_allowed_tcp_ports"])
    normalized_source = _normalize_source_cidr(source_cidr, runtime["default_source_cidr"], runtime["allow_public_cidr"])
    overview = _collect_instance_network_objects(instance_ref, app_config)
    target = _select_target(overview, target_scope)
    description = _build_temp_rule_description(normalized_port, normalized_source, overview["profile"])
    allowed_ports = [int(item) for item in runtime["quick_open_allowed_tcp_ports"]]
    return {
        "action": "open_ingress",
        "profile": overview["profile"],
        "instance": overview["instance"],
        "target": target,
        "port": normalized_port,
        "source_cidr": normalized_source,
        "description": description,
        "rule_model": _build_tcp_ingress_rule_model(normalized_port, normalized_source, description),
        "allowed_ports": allowed_ports,
        "is_custom_port": normalized_port not in set(allowed_ports),
    }


def render_open_ingress_preview_cli(preview: Dict[str, Any]) -> str:
    instance = preview["instance"]
    target = preview["target"]
    return "\n".join(
        [
            "\n" + "=" * 76,
            "🔓 新增入站规则预览（未执行）",
            f"实例: {instance['display_name']} | 状态: {instance['lifecycle_state']} | Profile: {preview['profile']}",
            f"目标: {target['target_type']} | {target['target_name']}",
            f"路径: {target['via']}",
            f"来源: {preview['source_cidr']}",
            f"端口: TCP/{preview['port']}",
            "规则性质: stateful / ingress / 仅主 VNIC 关联对象",
            f"描述: {preview['description']}",
            "下一步: 确认无误后执行同参数的 open_ingress_apply",
        ]
    )


def render_open_ingress_preview_telegram(preview: Dict[str, Any]) -> str:
    instance = preview["instance"]
    target = preview["target"]
    return "\n".join(
        [
            "<b>🔓 网络 / 安全向导</b>",
            "<b>放行临时端口 · 预览确认</b>",
            f"<blockquote>实例：<b>{html.escape(str(instance['display_name']))}</b>\n端口：<code>TCP/{preview['port']}</code> · 来源：<code>{html.escape(preview['source_cidr'])}</code>\n状态：<code>{html.escape(str(instance['lifecycle_state']))}</code> · Profile：<code>{html.escape(str(preview['profile']))}</code></blockquote>",
            f"🎯 目标对象：<code>{html.escape(target['target_name'])}</code>",
            f"🧭 变更路径：{html.escape(target['via'])}",
            "🧱 规则类型：<code>ingress + stateful</code>",
            f"📝 临时描述：<code>{html.escape(preview['description'])}</code>",
            "⚠️ 当前只是预览，点确认后才会真正提交。",
        ]
    )


def _rule_exists_in_nsg(nsg: Any, port: int, source_cidr: str, description_prefix: str) -> bool:
    for rule in list(getattr(nsg, "security_rules", []) or []):
        if _rule_matches(rule, port, source_cidr, description_prefix):
            return True
    return False


def _rule_exists_in_security_list(security_list: Any, port: int, source_cidr: str, description_prefix: str) -> bool:
    for rule in list(getattr(security_list, "ingress_security_rules", []) or []):
        if _rule_matches(rule, port, source_cidr, description_prefix):
            return True
    return False


def apply_open_ingress_rule_data(
    instance_ref: str,
    port: Any,
    source_cidr: Optional[str] = None,
    app_config: Optional[Dict[str, Any]] = None,
    target_scope: Optional[str] = None,
) -> Dict[str, Any]:
    preview = preview_open_ingress_rule_data(instance_ref, port, source_cidr, app_config, target_scope)
    config = get_oci_config(app_config)
    network_client = get_virtual_network_client(config)
    target = preview["target"]
    rule_model = preview["rule_model"]

    if target["target_type"] == "nsg":
        nsg = network_client.get_network_security_group(target["target_id"]).data
        if _rule_exists_in_nsg(nsg, preview["port"], preview["source_cidr"], preview["description"]):
            return {
                **preview,
                "applied": False,
                "status": "exists",
                "message": "已存在同一条临时规则，未重复写入。",
            }
        add_details = oci.core.models.AddNetworkSecurityGroupSecurityRulesDetails(
            security_rules=[oci.core.models.AddSecurityRuleDetails(**rule_model)]
        )
        response = network_client.add_network_security_group_security_rules(target["target_id"], add_details)
        return {
            **preview,
            "applied": True,
            "status": getattr(response, "status", "N/A"),
            "message": "已向 NSG 提交新增入站规则。",
        }

    security_list_response = network_client.get_security_list(target["target_id"])
    security_list = security_list_response.data
    security_list_etag = (getattr(security_list_response, "headers", {}) or {}).get("etag")
    if not security_list_etag:
        raise RuntimeError("Security List 缺少 ETag，已停止更新以避免覆盖并发修改")
    if _rule_exists_in_security_list(security_list, preview["port"], preview["source_cidr"], preview["description"]):
        return {
            **preview,
            "applied": False,
            "status": "exists",
            "message": "已存在同一条临时规则，未重复写入。",
        }

    ingress_rules = list(getattr(security_list, "ingress_security_rules", []) or [])
    ingress_rules.append(oci.core.models.IngressSecurityRule(**rule_model))
    update_details = oci.core.models.UpdateSecurityListDetails(
        display_name=getattr(security_list, "display_name", None),
        defined_tags=getattr(security_list, "defined_tags", None),
        freeform_tags=getattr(security_list, "freeform_tags", None),
        egress_security_rules=list(getattr(security_list, "egress_security_rules", []) or []),
        ingress_security_rules=ingress_rules,
    )
    try:
        response = network_client.update_security_list(target["target_id"], update_details, if_match=security_list_etag)
    except oci.exceptions.ServiceError as exc:
        if getattr(exc, "status", None) == 412:
            raise RuntimeError("Security List 在确认后已被其他进程修改，未覆盖外部变更，请重新读取并确认") from exc
        raise
    return {
        **preview,
        "applied": True,
        "status": getattr(response, "status", "N/A"),
        "message": "已向 Security List 提交新增入站规则。",
    }


def render_open_ingress_result_telegram(result: Dict[str, Any]) -> str:
    status = html.escape(str(result.get("status", "N/A")))
    applied = bool(result.get("applied"))
    icon = "✅" if applied else "ℹ️"
    title = "放行临时端口 · 已处理"
    return "\n".join(
        [
            f"<b>{icon} 网络 / 安全向导</b>",
            f"<b>{title}</b>",
            f"<blockquote>实例：<b>{html.escape(str(result['instance']['display_name']))}</b>\n目标：<code>{html.escape(str(result['target']['target_name']))}</code>\n端口：<code>TCP/{result['port']}</code> · 来源：<code>{html.escape(str(result['source_cidr']))}</code></blockquote>",
            f"🧾 处理结果：{html.escape(str(result.get('message', '完成')))}",
            f"📡 返回状态：<code>{status}</code>",
            f"🧭 变更路径：{html.escape(str(result['target']['via']))}",
            f"📝 临时描述：<code>{html.escape(str(result['description']))}</code>",
        ]
    )


def preview_cleanup_temp_rules_data(
    instance_ref: str,
    port: Any,
    source_cidr: Optional[str] = None,
    app_config: Optional[Dict[str, Any]] = None,
    target_scope: Optional[str] = None,
) -> Dict[str, Any]:
    runtime = get_network_runtime_config(app_config or {})
    normalized_port = _normalize_port(port, runtime["quick_open_allowed_tcp_ports"])
    normalized_source = _normalize_source_cidr(source_cidr, runtime["default_source_cidr"], runtime["allow_public_cidr"])
    overview = _collect_instance_network_objects(instance_ref, app_config)
    target = _select_target(overview, target_scope)
    description = _build_temp_rule_description(normalized_port, normalized_source, overview["profile"])
    config = get_oci_config(app_config)
    network_client = get_virtual_network_client(config)

    matched_rules: List[Dict[str, Any]] = []
    if target["target_type"] == "nsg":
        nsg = network_client.get_network_security_group(target["target_id"]).data
        for rule in list(getattr(nsg, "security_rules", []) or []):
            if _rule_matches(rule, normalized_port, normalized_source, description):
                matched_rules.append(
                    {
                        "id": str(getattr(rule, "id", "")),
                        "description": str(getattr(rule, "description", "")),
                        "source": str(getattr(rule, "source", "")),
                        "port": _extract_rule_port(rule),
                    }
                )
    else:
        security_list = network_client.get_security_list(target["target_id"]).data
        for index, rule in enumerate(list(getattr(security_list, "ingress_security_rules", []) or []), start=1):
            if _rule_matches(rule, normalized_port, normalized_source, description):
                matched_rules.append(
                    {
                        "id": f"sl-rule-{index}",
                        "description": str(getattr(rule, "description", "")),
                        "source": str(getattr(rule, "source", "")),
                        "port": _extract_rule_port(rule),
                    }
                )

    allowed_ports = [int(item) for item in runtime["quick_open_allowed_tcp_ports"]]
    return {
        "action": "cleanup_temp_rules",
        "profile": overview["profile"],
        "instance": overview["instance"],
        "target": target,
        "port": normalized_port,
        "source_cidr": normalized_source,
        "description": description,
        "matched_rules": matched_rules,
        "allowed_ports": allowed_ports,
        "is_custom_port": normalized_port not in set(allowed_ports),
    }


def render_cleanup_preview_cli(preview: Dict[str, Any]) -> str:
    lines = [
        "\n" + "=" * 76,
        "🧹 删除临时规则预览（未执行）",
        f"实例: {preview['instance']['display_name']} | 目标: {preview['target']['target_name']} | TCP/{preview['port']} | {preview['source_cidr']}",
        f"匹配描述: {preview['description']}",
        f"匹配规则数: {len(preview['matched_rules'])}",
    ]
    if preview["matched_rules"]:
        for item in preview["matched_rules"]:
            lines.append(f"- {item['id']} | {item['description']}")
        lines.append("下一步: 确认无误后执行同参数的 cleanup_temp_rules_apply")
    else:
        lines.append("未发现可删除的临时规则。")
    return "\n".join(lines)


def render_cleanup_preview_telegram(preview: Dict[str, Any]) -> str:
    lines = [
        "<b>🧹 网络 / 安全向导</b>",
        "<b>清理临时规则 · 预览确认</b>",
        f"<blockquote>实例：<b>{html.escape(str(preview['instance']['display_name']))}</b>\n目标：<code>{html.escape(str(preview['target']['target_name']))}</code>\n端口：<code>TCP/{preview['port']}</code> · 来源：<code>{html.escape(str(preview['source_cidr']))}</code></blockquote>",
        f"🧭 变更路径：{html.escape(str(preview['target']['via']))}",
        f"📝 匹配描述：<code>{html.escape(str(preview['description']))}</code>",
        f"🔎 匹配规则数：<b>{len(preview['matched_rules'])}</b>",
    ]
    if preview["matched_rules"]:
        for item in preview["matched_rules"][:5]:
            lines.append(f"• <code>{html.escape(str(item['id']))}</code> · {html.escape(str(item['description']))}")
        if len(preview["matched_rules"]) > 5:
            lines.append(f"• …其余 <b>{len(preview['matched_rules']) - 5}</b> 条已折叠")
        lines.append("⚠️ 当前只是预览，点确认后才会真正删除。")
    else:
        lines.append("ℹ️ 当前没有找到可清理的临时规则，继续确认也不会删到别的规则。")
    return "\n".join(lines)


def apply_cleanup_temp_rules_data(
    instance_ref: str,
    port: Any,
    source_cidr: Optional[str] = None,
    app_config: Optional[Dict[str, Any]] = None,
    target_scope: Optional[str] = None,
) -> Dict[str, Any]:
    preview = preview_cleanup_temp_rules_data(instance_ref, port, source_cidr, app_config, target_scope)
    if not preview["matched_rules"]:
        return {
            **preview,
            "removed_count": 0,
            "status": "no-match",
            "message": "未发现匹配的临时规则，无需删除。",
        }

    config = get_oci_config(app_config)
    network_client = get_virtual_network_client(config)
    target = preview["target"]

    if target["target_type"] == "nsg":
        nsg = network_client.get_network_security_group(target["target_id"]).data
        remove_ids = [str(item["id"]).strip() for item in preview["matched_rules"] if str(item.get("id", "")).strip()]
        remove_ids = list(dict.fromkeys(remove_ids))
        if not remove_ids:
            return {
                **preview,
                "removed_count": 0,
                "status": "no-match",
                "message": "匹配规则缺少 OCI 规则 ID，未执行删除。",
            }
        response = network_client.remove_network_security_group_security_rules(
            target["target_id"],
            oci.core.models.RemoveNetworkSecurityGroupSecurityRulesDetails(security_rule_ids=remove_ids),
        )
        refreshed_nsg = network_client.get_network_security_group(target["target_id"]).data
        remaining_ids = {str(getattr(rule, "id", "")) for rule in getattr(refreshed_nsg, "security_rules", []) or []}
        if remaining_ids.intersection(remove_ids):
            raise RuntimeError("NSG 规则删除后复核失败，目标规则仍存在")
        return {
            **preview,
            "removed_count": len(remove_ids),
            "status": getattr(response, "status", "N/A"),
            "message": "已从 NSG 删除匹配的临时规则。",
        }

    security_list_response = network_client.get_security_list(target["target_id"])
    security_list = security_list_response.data
    security_list_etag = (getattr(security_list_response, "headers", {}) or {}).get("etag")
    if not security_list_etag:
        raise RuntimeError("Security List 缺少 ETag，已停止更新以避免覆盖并发修改")
    keep_ingress_rules: List[Any] = []
    removed_count = 0
    for rule in list(getattr(security_list, "ingress_security_rules", []) or []):
        if _rule_matches(rule, preview["port"], preview["source_cidr"], preview["description"]):
            removed_count += 1
            continue
        keep_ingress_rules.append(rule)
    try:
        response = network_client.update_security_list(
            target["target_id"],
            oci.core.models.UpdateSecurityListDetails(
                display_name=getattr(security_list, "display_name", None),
                defined_tags=getattr(security_list, "defined_tags", None),
                freeform_tags=getattr(security_list, "freeform_tags", None),
                egress_security_rules=list(getattr(security_list, "egress_security_rules", []) or []),
                ingress_security_rules=keep_ingress_rules,
            ),
            if_match=security_list_etag,
        )
    except oci.exceptions.ServiceError as exc:
        if getattr(exc, "status", None) == 412:
            raise RuntimeError("Security List 在确认后已被其他进程修改，未覆盖外部变更，请重新读取并确认") from exc
        raise
    return {
        **preview,
        "removed_count": removed_count,
        "status": getattr(response, "status", "N/A"),
        "message": "已从 Security List 删除匹配的临时规则。",
    }


def render_cleanup_result_telegram(result: Dict[str, Any]) -> str:
    return "\n".join(
        [
            "<b>🧹 网络 / 安全向导</b>",
            "<b>清理临时规则 · 已处理</b>",
            f"<blockquote>实例：<b>{html.escape(str(result['instance']['display_name']))}</b>\n目标：<code>{html.escape(str(result['target']['target_name']))}</code>\n端口：<code>TCP/{result['port']}</code> · 来源：<code>{html.escape(str(result['source_cidr']))}</code></blockquote>",
            f"🧾 处理结果：{html.escape(str(result.get('message', '完成')))}",
            f"🗑️ 删除数量：<b>{int(result.get('removed_count', 0) or 0)}</b>",
            f"📡 返回状态：<code>{html.escape(str(result.get('status', 'N/A')))}</code>",
            f"🧭 变更路径：{html.escape(str(result['target']['via']))}",
        ]
    )


def preview_open_ingress_rule(app_config: Optional[Dict[str, Any]] = None) -> None:
    instance_ref = input("👉 请输入实例名称或 OCID: ").strip()
    port = input("👉 请输入要开放的 TCP 端口: ").strip()
    source_cidr = input("👉 请输入来源 CIDR（例如 1.2.3.4/32，留空用默认值）: ").strip()
    target_scope = input("👉 目标对象（回车自动选主 VNIC 第一个 NSG，否则 sl:<ocid>/nsg:<ocid>）: ").strip()
    preview = preview_open_ingress_rule_data(instance_ref, port, source_cidr or None, app_config, target_scope or None)
    print(render_open_ingress_preview_cli(preview))
    confirm = input("⚠️ 确认提交这条入站规则吗？(y/n): ").strip().lower()
    if confirm != "y":
        print("🛑 已取消。")
        return
    result = apply_open_ingress_rule_data(instance_ref, port, source_cidr or None, app_config, target_scope or None)
    print_section("入站规则处理结果", "✅")
    print_kv("实例", result["instance"]["display_name"])
    print_kv("目标", result["target"]["target_name"])
    print_kv("端口", f"TCP/{result['port']}")
    print_kv("来源", result["source_cidr"])
    print_kv("结果", result.get("message", "完成"))
    print_kv("状态", result.get("status", "N/A"))


def preview_cleanup_temp_rules(app_config: Optional[Dict[str, Any]] = None) -> None:
    instance_ref = input("👉 请输入实例名称或 OCID: ").strip()
    port = input("👉 请输入要回收的 TCP 端口: ").strip()
    source_cidr = input("👉 请输入来源 CIDR（例如 1.2.3.4/32，留空用默认值）: ").strip()
    target_scope = input("👉 目标对象（回车自动选主 VNIC 第一个 NSG，否则 sl:<ocid>/nsg:<ocid>）: ").strip()
    preview = preview_cleanup_temp_rules_data(instance_ref, port, source_cidr or None, app_config, target_scope or None)
    print(render_cleanup_preview_cli(preview))
    if not preview["matched_rules"]:
        return
    confirm = input("⚠️ 确认删除这些临时规则吗？(y/n): ").strip().lower()
    if confirm != "y":
        print("🛑 已取消。")
        return
    result = apply_cleanup_temp_rules_data(instance_ref, port, source_cidr or None, app_config, target_scope or None)
    print_section("临时规则清理结果", "🧹")
    print_kv("实例", result["instance"]["display_name"])
    print_kv("目标", result["target"]["target_name"])
    print_kv("端口", f"TCP/{result['port']}")
    print_kv("来源", result["source_cidr"])
    print_kv("删除数量", result.get("removed_count", 0))
    print_kv("状态", result.get("status", "N/A"))


def show_instance_ingress_rules(app_config: Optional[Dict[str, Any]] = None, instance_ref: Optional[str] = None, page: int = 1, temp_only: bool = False) -> None:
    if not instance_ref:
        instance_ref = input("👉 请输入实例名称或 OCID: ").strip()
    print(render_instance_ingress_rules_cli(get_instance_ingress_rules_data(instance_ref, app_config, page=page, temp_only=temp_only)))


__all__ = [
    "apply_cleanup_temp_rules_data",
    "apply_open_ingress_rule_data",
    "get_instance_network_overview_data",
    "get_instance_ingress_rules_data",
    "preview_cleanup_temp_rules",
    "preview_cleanup_temp_rules_data",
    "preview_open_ingress_rule",
    "preview_open_ingress_rule_data",
    "render_cleanup_preview_telegram",
    "render_cleanup_result_telegram",
    "render_cleanup_selected_preview_telegram",
    "render_cleanup_selected_result_telegram",
    "render_instance_network_overview_cli",
    "render_instance_network_overview_telegram",
    "render_instance_ingress_rules_cli",
    "render_instance_ingress_rules_telegram",
    "get_instance_network_detail_pages",
    "render_instance_network_details_telegram",
    "render_open_ingress_preview_telegram",
    "render_open_ingress_result_telegram",
    "show_instance_ingress_rules",
    "show_instance_network_overview",
    "preview_cleanup_selected_temp_rules_data",
    "apply_cleanup_selected_temp_rules_data",
]
