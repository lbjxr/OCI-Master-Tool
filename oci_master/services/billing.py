import hashlib
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import oci

from oci_master.config import get_oci_config
from oci_master.utils import build_text_table, html_escape, print_kv, print_section, truncate_text


def export_usage_fee(app_config: Optional[Dict[str, Any]] = None) -> None:
    print("\n" + "=" * 65)
    print("💰 正在查询本月费用数据...")
    try:
        config = get_oci_config(app_config)
        usage_client = oci.usage_api.UsageapiClient(config)
        output_cfg = (app_config or {}).get("output", {})
        display_days = int(output_cfg.get("usage_fee_display_days", 1) or 1)

        now_utc = datetime.now(timezone.utc)
        start_time = now_utc.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end_time = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)

        if end_time <= start_time:
            print("提示：本月暂无可查询的日粒度费用数据，请稍后再试。")
            return

        request_details = oci.usage_api.models.RequestSummarizedUsagesDetails(
            tenant_id=config["tenancy"],
            time_usage_started=start_time,
            time_usage_ended=end_time,
            granularity="DAILY",
            query_type="COST",
            group_by=["service"],
        )

        response = usage_client.request_summarized_usages(request_details)
        total_cost = 0.0
        currency = "USD"

        if not response.data.items:
            print("提示：此时间段内没有产生任何费用数据。")
            return

        sorted_items = sorted(response.data.items, key=lambda x: x.time_usage_started)
        rows: List[List[str]] = []
        unique_dates = []
        seen_dates = set()

        for item in sorted_items:
            date_str = item.time_usage_started.strftime("%Y-%m-%d")
            service = getattr(item, "service", "Unknown Service") or "Unknown Service"
            amount = getattr(item, "computed_amount", 0.0) or 0.0
            currency = getattr(item, "currency", "USD") or "USD"
            total_cost += amount

            rows.append([date_str, truncate_text(service, 28), f"{amount:.4f}", currency])
            if date_str not in seen_dates:
                seen_dates.add(date_str)
                unique_dates.append(date_str)

        latest_dates = set(unique_dates[-display_days:]) if unique_dates else set()
        display_rows = [row for row in rows if row[0] in latest_dates]

        print_section("本月费用汇总", "💰")
        print_kv("查询区间", f"{start_time.strftime('%Y-%m-%d')} ~ {end_time.strftime('%Y-%m-%d')}")
        print_kv("账单总记录数", len(rows))
        print_kv("涉及日期数", len(unique_dates))
        print_kv("默认展示天数", display_days)
        print(f"📊 本月预估总计: {total_cost:.4f} {currency}")

        print_section(f"费用明细（默认仅展示最近 {display_days} 天）", "📄")
        print(build_text_table(["日期", "服务名称", "金额", "币种"], display_rows))

        if len(unique_dates) > display_days:
            hidden_days = len(unique_dates) - display_days
            print()
            print(f"ℹ️ 已折叠更早的 {hidden_days} 天数据；当前默认仅展示最近 {display_days} 天。")
    except Exception as exc:
        error_code = hashlib.sha256(type(exc).__name__.encode("utf-8")).hexdigest()[:8].upper()
        print(f"❌ 运行出错，请稍后重试（错误编号：{error_code}）")


def get_usage_fee_report_data(app_config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    config = get_oci_config(app_config)
    usage_client = oci.usage_api.UsageapiClient(config)
    output_cfg = (app_config or {}).get("output", {})
    display_days = int(output_cfg.get("usage_fee_display_days", 1) or 1)

    now_utc = datetime.now(timezone.utc)
    start_time = now_utc.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    end_time = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)

    if end_time <= start_time:
        return {
            "start_time": start_time,
            "end_time": end_time,
            "rows": [],
            "unique_dates": [],
            "display_days": display_days,
            "total_cost": 0.0,
            "currency": "USD",
            "pending_month_start": True,
        }

    request_details = oci.usage_api.models.RequestSummarizedUsagesDetails(
        tenant_id=config["tenancy"],
        time_usage_started=start_time,
        time_usage_ended=end_time,
        granularity="DAILY",
        query_type="COST",
        group_by=["service"],
    )

    response = usage_client.request_summarized_usages(request_details)
    items = getattr(response.data, "items", []) or []

    total_cost = 0.0
    currency = "USD"
    rows: List[List[str]] = []
    unique_dates: List[str] = []
    seen_dates = set()

    for item in sorted(items, key=lambda x: x.time_usage_started):
        date_str = item.time_usage_started.strftime("%Y-%m-%d")
        service = getattr(item, "service", "Unknown Service") or "Unknown Service"
        amount = getattr(item, "computed_amount", 0.0) or 0.0
        currency = getattr(item, "currency", "USD") or currency or "USD"
        total_cost += amount

        rows.append([date_str, service, f"{amount:.4f}", currency])
        if date_str not in seen_dates:
            seen_dates.add(date_str)
            unique_dates.append(date_str)

    return {
        "start_time": start_time,
        "end_time": end_time,
        "rows": rows,
        "unique_dates": unique_dates,
        "display_days": display_days,
        "total_cost": total_cost,
        "currency": currency,
        "pending_month_start": False,
    }


def render_usage_fee_cli(report_data: Dict[str, Any], show_all: bool = False) -> str:
    rows = report_data["rows"]
    unique_dates = report_data["unique_dates"]
    display_days = report_data["display_days"]

    latest_dates = set(unique_dates if show_all else unique_dates[-display_days:]) if unique_dates else set()
    display_rows = [
        [row[0], truncate_text(row[1], 28), row[2], row[3]]
        for row in rows
        if row[0] in latest_dates
    ]

    parts = [
        "\n" + "=" * 65,
        "💰 正在查询本月费用数据...",
        "",
        "=" * 64,
        "💰 本月费用汇总",
        "=" * 64,
        f"查询区间                         : {report_data['start_time'].strftime('%Y-%m-%d')} ~ {report_data['end_time'].strftime('%Y-%m-%d')}",
        f"账单总记录数                       : {len(rows)}",
        f"涉及日期数                        : {len(unique_dates)}",
        f"默认展示天数                       : {display_days}",
        f"📊 本月预估总计: {report_data['total_cost']:.4f} {report_data['currency']}",
        "",
        "=" * 64,
        f"📄 费用明细（{'展示全部数据' if show_all else f'默认仅展示最近 {display_days} 天'}）",
        "=" * 64,
        build_text_table(["日期", "服务名称", "金额", "币种"], display_rows),
    ]

    if not show_all and len(unique_dates) > display_days:
        hidden_days = len(unique_dates) - display_days
        parts.extend(["", f"ℹ️ 已折叠更早的 {hidden_days} 天数据；当前默认仅展示最近 {display_days} 天。"])

    return "\n".join(parts)


def render_usage_fee_telegram(report_data: Dict[str, Any], show_all: bool = False) -> str:
    rows = report_data["rows"]
    unique_dates = report_data["unique_dates"]
    display_days = report_data["display_days"]

    if not unique_dates:
        empty_text = "本月暂无可展示费用数据。"
        if report_data.get("pending_month_start"):
            empty_text = "本月刚开始，OCI 日粒度账单数据尚未产出，请稍后再试。"
        return "\n".join([
            "<b>💰 本月费用汇总</b>",
            f"<blockquote>查询区间：<code>{report_data['start_time'].strftime('%Y-%m-%d')} ~ {report_data['end_time'].strftime('%Y-%m-%d')}</code></blockquote>",
            empty_text,
        ])

    latest_dates = set(unique_dates if show_all else unique_dates[-display_days:]) if unique_dates else set()

    daily_totals: Dict[str, float] = {}
    daily_services: Dict[str, List[Any]] = {}
    for row in rows:
        date_str, service, amount_str, currency = row
        if date_str not in latest_dates:
            continue
        amount = float(amount_str)
        daily_totals[date_str] = daily_totals.get(date_str, 0.0) + amount
        daily_services.setdefault(date_str, []).append((service, amount, currency))

    hidden_days = max(0, len(unique_dates) - display_days)
    currency = html_escape(report_data["currency"])

    def service_label(service_name: str) -> str:
        service_lower = str(service_name).lower()
        if "compute" in service_lower or "instance" in service_lower:
            return "🖥️ 计算实例"
        if "block" in service_lower or "storage" in service_lower:
            return "💾 存储"
        if "object" in service_lower:
            return "🪣 对象存储"
        if "network" in service_lower or "bandwidth" in service_lower or "load balancer" in service_lower:
            return "🌐 网络"
        if "database" in service_lower or "mysql" in service_lower or "oracle" in service_lower:
            return "🗄️ 数据库"
        if "security" in service_lower or "waf" in service_lower or "firewall" in service_lower:
            return "🔐 安全"
        return f"🔹 {html_escape(truncate_text(service_name, 16))}"

    message_parts = [
        "<b>💰 本月费用汇总</b>",
        (
            f"<blockquote>查询区间：<code>{report_data['start_time'].strftime('%Y-%m-%d')} ~ {report_data['end_time'].strftime('%Y-%m-%d')}</code>\n"
            f"账单记录：<b>{len(rows)}</b> 条\n"
            f"涉及日期：<b>{len(unique_dates)}</b> 天\n"
            f"本月预估：<b>{report_data['total_cost']:.4f} {currency}</b></blockquote>"
        ),
        f"<b>📄 {'全部账单明细' if show_all else f'最近 {display_days} 天账单明细'}</b>",
    ]

    for date_str in sorted(daily_totals.keys(), reverse=True):
        message_parts.append("")
        message_parts.append(f"<b>📆 {html_escape(date_str)}</b>")
        message_parts.append(f"💵 当日小计：<code>{daily_totals[date_str]:.4f} {currency}</code>")

        services = sorted(daily_services[date_str], key=lambda item: item[1], reverse=True)
        for service, amount, _ in services[:4]:
            message_parts.append(f"{service_label(service)}：<code>{amount:.4f}</code>")
        if len(services) > 4:
            other_total = sum(item[1] for item in services[4:])
            message_parts.append(f"📦 其他 {len(services) - 4} 项：<code>{other_total:.4f}</code>")

    if not show_all and hidden_days > 0:
        message_parts.append("")
        message_parts.append(f"ℹ️ 已折叠更早的 <b>{hidden_days}</b> 天数据，可点击下方按钮展开。")
    elif show_all and len(unique_dates) > display_days:
        message_parts.append("")
        message_parts.append("ℹ️ 当前显示全部数据，可点击下方按钮收起历史部分。")

    return "\n".join(message_parts)
