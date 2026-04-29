import html
from datetime import datetime
from typing import Any, Dict, List, Optional

import oci
import requests
from oci.signer import Signer

from oci_master.config import get_active_profile_name, get_oci_config, load_app_config
from oci_master.utils import format_datetime_compact, format_size_compact, safe_get, safe_get_any, truncate_text


def _normalize_collection_items(data: Any) -> List[Any]:
    if data is None:
        return []
    if isinstance(data, list):
        return data
    resources = getattr(data, "resources", None)
    if isinstance(resources, list):
        return resources
    items = getattr(data, "items", None)
    if isinstance(items, list):
        return items
    return []


def _parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def _short_ocid(ocid: Any) -> str:
    text = str(ocid or "")
    if not text:
        return "N/A"
    if len(text) <= 18:
        return text
    return f"{text[:10]}...{text[-6:]}"


def _bucket_access_text(public_access_type: Any) -> str:
    value = str(public_access_type or "NoPublicAccess")
    mapping = {
        "NoPublicAccess": "私有",
        "ObjectRead": "公开读",
        "ObjectReadWithoutList": "公开读(禁列目录)",
        "UNKNOWN_ENUM_VALUE": "未知",
    }
    return mapping.get(value, value)


def _build_compartment_name_map(identity_client: Any, tenancy_id: str) -> Dict[str, str]:
    compartment_map: Dict[str, str] = {tenancy_id: "租户根目录"}
    response = oci.pagination.list_call_get_all_results(
        identity_client.list_compartments,
        tenancy_id,
        compartment_id_in_subtree=True,
        access_level="ACCESSIBLE",
    )
    for item in _normalize_collection_items(getattr(response, "data", None)):
        cid = str(safe_get(item, "id", "")).strip()
        if not cid:
            continue
        state = str(safe_get(item, "lifecycle_state", "") or "").upper()
        if state and state != "ACTIVE":
            continue
        compartment_map[cid] = str(safe_get(item, "name", cid))
    return compartment_map


def _list_all_buckets(object_storage_client: Any, namespace_name: str, compartment_id: str) -> List[Any]:
    buckets: List[Any] = []
    page: Optional[str] = None
    while True:
        kwargs: Dict[str, Any] = {"limit": 1000}
        if page:
            kwargs["page"] = page
        response = object_storage_client.list_buckets(namespace_name, compartment_id, **kwargs)
        buckets.extend(_normalize_collection_items(getattr(response, "data", None)))
        page = getattr(response, "headers", {}).get("opc-next-page")
        if not page:
            break
    return buckets


def get_region_subscriptions_data(app_config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    config = get_oci_config(app_config or load_app_config())
    identity_client = oci.identity.IdentityClient(config)
    response = identity_client.list_region_subscriptions(config["tenancy"])
    subscriptions = _normalize_collection_items(getattr(response, "data", None))

    regions: List[Dict[str, Any]] = []
    for item in subscriptions:
        regions.append(
            {
                "region_name": str(safe_get(item, "region_name", "N/A")),
                "region_key": str(safe_get(item, "region_key", "N/A")),
                "status": str(safe_get(item, "status", "UNKNOWN")).upper(),
                "is_home_region": _parse_bool(safe_get(item, "is_home_region", False)),
            }
        )

    regions.sort(key=lambda x: (not x["is_home_region"], x["region_name"]))
    home_region = next((r["region_name"] for r in regions if r["is_home_region"]), config.get("region", "N/A"))
    return {
        "profile": get_active_profile_name(app_config or {}),
        "home_region": str(home_region),
        "total_regions": len(regions),
        "regions": regions,
    }


def render_region_subscriptions_telegram(data: Dict[str, Any]) -> str:
    regions = data.get("regions") or []
    if not regions:
        return "📭 <b>未查询到订阅区域</b>"

    lines = [
        "<b>🌏 OCI 订阅区域</b>",
        f"🪪 Profile：<code>{html.escape(str(data.get('profile', 'DEFAULT')))}</code>",
        f"📌 Home Region：<code>{html.escape(str(data.get('home_region', 'N/A')))}</code>",
        f"📈 已订阅：<code>{int(data.get('total_regions', len(regions)))}</code> 个",
    ]
    for idx, region in enumerate(regions, 1):
        name = html.escape(str(region.get("region_name", "N/A")))
        key = html.escape(str(region.get("region_key", "N/A")))
        status = html.escape(str(region.get("status", "UNKNOWN")))
        is_home = bool(region.get("is_home_region"))
        status_icon = "✅" if status == "READY" else ("⏳" if status in {"IN_PROGRESS", "CREATING"} else "⚠️")
        home_tag = "  🏠 <b>HOME</b>" if is_home else ""
        lines.append(f"{idx}. <b>{name}</b>{home_tag}")
        lines.append(f"   <code>{key}</code>  {status_icon} <code>{status}</code>")
    return "\n".join(lines)


def render_region_subscriptions_cli(data: Dict[str, Any]) -> str:
    regions = data.get("regions") or []
    if not regions:
        return "📭 未查询到订阅区域"
    lines = [
        "🌏 OCI 订阅区域",
        f"Profile: {data.get('profile', 'DEFAULT')}",
        f"Home Region: {data.get('home_region', 'N/A')}",
        f"已订阅: {int(data.get('total_regions', len(regions)))} 个",
        "-" * 48,
    ]
    for idx, region in enumerate(regions, 1):
        home_tag = " [HOME]" if region.get("is_home_region") else ""
        lines.append(f"{idx}. {region.get('region_name', 'N/A')}{home_tag} | {region.get('region_key', 'N/A')} | {region.get('status', 'UNKNOWN')}")
    return "\n".join(lines)


def show_region_subscriptions(app_config: Optional[Dict[str, Any]] = None) -> None:
    print("\n" + "=" * 65)
    print("🌏 正在查询 OCI 订阅区域...")
    print(render_region_subscriptions_cli(get_region_subscriptions_data(app_config or load_app_config())))


def get_bucket_info_data(app_config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    app_config = app_config or load_app_config()
    config = get_oci_config(app_config)

    identity_client = oci.identity.IdentityClient(config)
    object_storage_client = oci.object_storage.ObjectStorageClient(config)

    namespace_name = object_storage_client.get_namespace().data
    tenancy_id = config["tenancy"]
    compartment_map = _build_compartment_name_map(identity_client, tenancy_id)
    accessible_compartment_ids = list(compartment_map.keys())

    bucket_rows: List[Dict[str, Any]] = []
    for compartment_id in accessible_compartment_ids:
        try:
            bucket_summaries = _list_all_buckets(object_storage_client, namespace_name, compartment_id)
        except Exception:
            continue

        for bucket_summary in bucket_summaries:
            bucket_name = str(safe_get(bucket_summary, "name", "N/A"))
            try:
                detail = object_storage_client.get_bucket(
                    namespace_name,
                    bucket_name,
                    fields=["approximateCount", "approximateSize", "autoTiering"],
                ).data
            except Exception:
                detail = bucket_summary

            detail_compartment_id = str(safe_get(detail, "compartment_id", compartment_id))
            bucket_rows.append(
                {
                    "name": bucket_name,
                    "namespace": str(safe_get(detail, "namespace", namespace_name)),
                    "compartment_id": detail_compartment_id,
                    "compartment_name": compartment_map.get(detail_compartment_id, _short_ocid(detail_compartment_id)),
                    "time_created": safe_get(detail, "time_created", safe_get(bucket_summary, "time_created", "N/A")),
                    "public_access_type": str(safe_get(detail, "public_access_type", "NoPublicAccess")),
                    "storage_tier": str(safe_get(detail, "storage_tier", "N/A")),
                    "versioning": str(safe_get(detail, "versioning", "N/A")),
                    "auto_tiering": str(safe_get(detail, "auto_tiering", "N/A")),
                    "approximate_count": safe_get(detail, "approximate_count", "N/A"),
                    "approximate_size": safe_get(detail, "approximate_size", "N/A"),
                }
            )

    bucket_rows.sort(key=lambda item: (str(item.get("compartment_name", "")), str(item.get("name", ""))))
    return {
        "namespace": str(namespace_name),
        "profile": get_active_profile_name(app_config),
        "tenancy_id": tenancy_id,
        "bucket_count": len(bucket_rows),
        "buckets": bucket_rows,
        "stats_note": "对象数量与大小来自 OCI approximateCount / approximateSize，为近似值；权限不足时会显示 N/A。",
    }


def render_bucket_info_telegram(data: Dict[str, Any]) -> str:
    buckets = data.get("buckets") or []
    namespace = html.escape(str(data.get("namespace", "N/A")))
    profile = html.escape(str(data.get("profile", "DEFAULT")))

    if not buckets:
        return (
            "<b>🪣 存储桶总览</b>\n"
            "📭 未查询到存储桶\n"
            f"📦 Namespace：<code>{namespace}</code>\n"
            f"🪪 Profile：<code>{profile}</code>"
        )

    lines = [
        "<b>🪣 存储桶总览</b>",
        f"📊 Bucket 总数：<code>{int(data.get('bucket_count', len(buckets)))}</code>",
        f"📦 Namespace：<code>{namespace}</code>",
        f"🪪 Profile：<code>{profile}</code>",
    ]

    for idx, bucket in enumerate(buckets, 1):
        bucket_name = html.escape(str(bucket.get("name", "N/A")))
        compartment_name = html.escape(str(bucket.get("compartment_name", "N/A")))
        created_at = html.escape(format_datetime_compact(bucket.get("time_created")))
        access = html.escape(_bucket_access_text(bucket.get("public_access_type")))
        tier = html.escape(str(bucket.get("storage_tier", "N/A")))
        versioning = html.escape(str(bucket.get("versioning", "N/A")))
        auto_tiering = html.escape(str(bucket.get("auto_tiering", "N/A")))
        approx_size = html.escape(format_size_compact(bucket.get("approximate_size")))
        approx_count = html.escape(str(bucket.get("approximate_count", "N/A")))

        lines.extend([
            "",
            f"<b>{idx}. 🪣 {bucket_name}</b>",
            f"📁 Compartment：<code>{compartment_name}</code>",
            f"🕒 创建时间：<code>{created_at}</code>",
            f"🌐 访问：<code>{access}</code> · 🧊 存储层：<code>{tier}</code>",
            f"🧬 版本控制：<code>{versioning}</code> · 🔄 自动分层：<code>{auto_tiering}</code>",
            f"📦 对象/容量：<code>{approx_count}</code> 个 · <code>{approx_size}</code>",
        ])

    stats_note = str(data.get("stats_note", "")).strip()
    if stats_note:
        lines.extend(["", f"<i>ℹ️ {html.escape(stats_note)}</i>"])
    return "\n".join(lines)


def render_bucket_info_cli(data: Dict[str, Any]) -> str:
    buckets = data.get("buckets") or []
    if not buckets:
        return f"📭 未查询到存储桶\nNamespace: {data.get('namespace', 'N/A')}\nProfile: {data.get('profile', 'DEFAULT')}"

    lines = [
        "🪣 OCI 存储桶总览",
        f"Namespace: {data.get('namespace', 'N/A')}",
        f"Profile: {data.get('profile', 'DEFAULT')}",
        f"Bucket 数量: {int(data.get('bucket_count', len(buckets)))}",
        "-" * 64,
    ]
    for idx, bucket in enumerate(buckets, 1):
        lines.append(f"{idx}. {bucket.get('name', 'N/A')}")
        lines.append(f"   compartment : {bucket.get('compartment_name', 'N/A')}")
        lines.append(f"   created     : {format_datetime_compact(bucket.get('time_created'))}")
        lines.append(f"   access/tier : {_bucket_access_text(bucket.get('public_access_type'))} / {bucket.get('storage_tier', 'N/A')}")
        lines.append(f"   version/at  : {bucket.get('versioning', 'N/A')} / {bucket.get('auto_tiering', 'N/A')}")
        lines.append(f"   approx stat : {format_size_compact(bucket.get('approximate_size'))} / {bucket.get('approximate_count', 'N/A')} objects")
    lines.append("-" * 64)
    lines.append(str(data.get("stats_note", "")))
    return "\n".join(lines)


def show_bucket_info(app_config: Optional[Dict[str, Any]] = None) -> None:
    print("\n" + "=" * 65)
    print("🪣 正在查询 OCI Object Storage 存储桶...")
    print(render_bucket_info_cli(get_bucket_info_data(app_config or load_app_config())))


def _get_identity_domain_url(config: Dict[str, Any], domain_name: str) -> str:
    identity_client = oci.identity.IdentityClient(config)
    response = identity_client.list_domains(config["tenancy"])
    domains = getattr(response, "data", []) or []
    target_domain = next((d for d in domains if getattr(d, "display_name", None) == domain_name), None)
    if not target_domain:
        raise ValueError(f"未找到名为 {domain_name} 的 Identity Domain")
    return str(target_domain.url).replace(":443", "")


def _fetch_audit_events_rest(
    config: Dict[str, Any],
    domain_url: str,
    limit: int = 20,
    filter_expr: Optional[str] = None,
    sort_by: str = "timestamp",
    sort_order: str = "DESCENDING",
) -> List[Dict[str, Any]]:
    signer = Signer(
        tenancy=config["tenancy"],
        user=config["user"],
        fingerprint=config["fingerprint"],
        private_key_file_location=config.get("key_file"),
        pass_phrase=config.get("pass_phrase"),
        private_key_content=config.get("key_content"),
    )
    params: Dict[str, Any] = {
        "count": max(1, min(int(limit), 100)),
        "sortBy": sort_by,
        "sortOrder": sort_order,
    }
    if filter_expr:
        params["filter"] = filter_expr
    response = requests.get(
        f"{domain_url}/admin/v1/AuditEvents",
        auth=signer,
        headers={"Content-Type": "application/json"},
        params=params,
        timeout=(5, 60),
    )
    response.raise_for_status()
    return list((response.json() or {}).get("Resources", []) or [])


def _audit_event_icon(message: str) -> str:
    lowered = str(message or "").lower()
    if "login" in lowered or "sign in" in lowered:
        return "🔑"
    if "logout" in lowered or "sign out" in lowered:
        return "🚪"
    if "create" in lowered:
        return "➕"
    if "update" in lowered or "modify" in lowered:
        return "✏️"
    if "delete" in lowered or "remove" in lowered:
        return "🗑️"
    if "password" in lowered:
        return "🔒"
    return "🔐"


def get_audit_events_data(
    app_config: Optional[Dict[str, Any]] = None,
    limit: int = 20,
    filter_expr: Optional[str] = None,
    sort_by: str = "timestamp",
    sort_order: str = "DESCENDING",
) -> Dict[str, Any]:
    app_config = app_config or load_app_config()
    config = get_oci_config(app_config)
    domain_name = (app_config.get("oci", {}) or {}).get("identity_domain_name", "Default")
    domain_url = _get_identity_domain_url(config, domain_name)
    events = _fetch_audit_events_rest(config, domain_url, limit=limit, filter_expr=filter_expr, sort_by=sort_by, sort_order=sort_order)
    return {
        "profile": get_active_profile_name(app_config),
        "domain_name": domain_name,
        "limit": max(1, min(int(limit), 100)),
        "count": len(events),
        "events": events,
        "filter": filter_expr or "",
        "sort_by": sort_by,
        "sort_order": sort_order,
    }


def render_audit_events_telegram(data: Dict[str, Any], limit: Optional[int] = None) -> str:
    events = data.get("events") or []
    display_limit = max(1, min(int(limit or data.get("limit", 10) or 10), 50))
    if not events:
        return "📭 <b>未找到审计事件</b>"

    parts = [
        "<b>📋 审计事件</b>",
        f"🪪 Profile：<code>{html.escape(str(data.get('profile', 'DEFAULT')))}</code>",
        f"🏢 Domain：<code>{html.escape(str(data.get('domain_name', 'Default')))}</code>",
        f"📈 返回：<code>{len(events)}</code> 条",
    ]
    for event in events[:display_limit]:
        timestamp = safe_get_any(event, "timestamp", default="")
        if timestamp:
            try:
                dt = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
                timestamp = dt.strftime("%m-%d %H:%M:%S")
            except Exception:
                pass
        else:
            timestamp = "N/A"
        event_message = str(safe_get_any(event, "message", default="N/A"))
        user_name = str(safe_get_any(event, "actorDisplayName", "actorName", default="系统"))
        source_ip = str(safe_get_any(event, "clientIp", default="N/A"))
        parts.append(f"\n{_audit_event_icon(event_message)} <b>{html.escape(truncate_text(event_message, 80))}</b>")
        parts.append(f"   👤 用户：<code>{html.escape(user_name)}</code>")
        parts.append(f"   🌐 IP：<code>{html.escape(source_ip)}</code>")
        parts.append(f"   🕒 时间：{html.escape(str(timestamp))}")
    if len(events) > display_limit:
        parts.append(f"\n<i>... 还有 {len(events) - display_limit} 条事件未显示</i>")
    return "\n".join(parts)


def render_audit_events_cli(data: Dict[str, Any], limit: Optional[int] = None) -> str:
    events = data.get("events") or []
    display_limit = max(1, min(int(limit or data.get("limit", 20) or 20), 100))
    if not events:
        return "📭 未找到审计事件"

    lines = [
        "📋 OCI 审计事件",
        f"Profile: {data.get('profile', 'DEFAULT')}",
        f"Domain : {data.get('domain_name', 'Default')}",
        f"返回条数: {len(events)}",
        "-" * 80,
    ]
    for idx, event in enumerate(events[:display_limit], 1):
        timestamp = safe_get_any(event, "timestamp", default="")
        timestamp_fmt = format_datetime_compact(timestamp) if timestamp else "N/A"
        event_message = str(safe_get_any(event, "message", default="N/A"))
        user_name = str(safe_get_any(event, "actorDisplayName", "actorName", default="系统"))
        source_ip = str(safe_get_any(event, "clientIp", default="N/A"))
        service_name = str(safe_get_any(event, "serviceName", default=""))
        event_id = str(safe_get_any(event, "eventId", default=""))
        target_name = service_name or event_id or "N/A"
        lines.append(f"{idx}. {truncate_text(event_message, 64)}")
        lines.append(f"   time   : {timestamp_fmt}")
        lines.append(f"   user   : {truncate_text(user_name, 48)}")
        lines.append(f"   ip     : {source_ip}")
        lines.append(f"   target : {truncate_text(target_name, 48)}")
    return "\n".join(lines)


def show_audit_events(
    app_config: Optional[Dict[str, Any]] = None,
    limit: int = 20,
    filter_expr: Optional[str] = None,
    sort_by: str = "timestamp",
    sort_order: str = "DESCENDING",
) -> None:
    print("\n" + "=" * 80)
    print("📋 正在获取审计事件...")
    print(render_audit_events_cli(get_audit_events_data(app_config or load_app_config(), limit=limit, filter_expr=filter_expr, sort_by=sort_by, sort_order=sort_order), limit=limit))
