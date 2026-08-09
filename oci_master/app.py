import os
import sys
from typing import Any, Dict, List, Optional, Tuple

from oci_master.config import load_app_config
from oci_master.services.billing import export_usage_fee
from oci_master.services.instances import get_instance_detail, instance_action, list_instances
from oci_master.services.network_security import (
    apply_cleanup_temp_rules_data,
    apply_open_ingress_rule_data,
    get_instance_ingress_rules_data,
    preview_cleanup_temp_rules_data,
    preview_open_ingress_rule_data,
    render_cleanup_preview_cli,
    render_instance_ingress_rules_cli,
    render_open_ingress_preview_cli,
    show_instance_ingress_rules,
    show_instance_network_overview,
)
from oci_master.services.policies import create_safe_policy, delete_policy, list_policies
from oci_master.services.tenant_insights import (
    get_audit_events_data,
    get_bucket_info_data,
    get_region_subscriptions_data,
    render_audit_events_cli,
    render_bucket_info_cli,
    render_region_subscriptions_cli,
    show_audit_events,
    show_bucket_info,
    show_region_subscriptions,
)
from oci_master.services.user_info import get_user_info
from oci_master.action_dispatch import parse_action
from oci_master.telegram_bot import TelegramBotRunner
from oci_master import registry


def print_cli_menu() -> None:
    print("\n" + "☁️  OCI 甲骨文云一键运维工具 ☁️ ".center(50))
    print("=" * 62)
    entries = registry.get_menu_entries()
    for idx, (label, action_key, description) in enumerate(entries, start=1):
        print(f"  {idx}. {label}")
    print("  0. 🚪 退出程序")
    print("=" * 62)


def main_menu(app_config: Dict[str, object]) -> None:
    clear_cmd = "cls" if os.name == "nt" else "clear"

    while True:
        print_cli_menu()
        max_choice = len(registry.get_menu_entries())
        choice = input(f"👉 请选择要执行的功能 (0-{max_choice}): ").strip()

        if choice == "0":
            print("\n👋 感谢使用，已安全退出程序！\n")
            break

        try:
            idx = int(choice)
            if idx < 1 or idx > max_choice:
                raise ValueError
        except ValueError:
            os.system(clear_cmd)
            print(f"❌ 指令无效！请重新输入菜单前方的数字 (0 到 {max_choice} 之间)。")
            continue

        entries = registry.get_menu_entries()
        _, action_key, _ = entries[idx - 1]
        registry.dispatch_cli(action_key, app_config)

        input("\n⌨️  按 [Enter] 键返回主菜单...")
        os.system(clear_cmd)


def parse_args(argv: List[str]) -> Tuple[str, Optional[str]]:
    if len(argv) >= 2:
        if argv[1] == "telegram":
            return "telegram", None
        if argv[1] == "run" and len(argv) >= 3:
            return "run", argv[2]
    return "menu", None


def execute_action(action: str, app_config: Dict[str, object]) -> None:
    registry.dispatch_cli(action, app_config)


def main() -> None:
    app_config = load_app_config()
    mode, action = parse_args(sys.argv)

    if mode == "telegram":
        TelegramBotRunner(app_config).run_polling()
        return
    if mode == "run" and action:
        execute_action(action, app_config)
        return

    main_menu(app_config)


# ────────────────────────────────────────────
# Registry bootstrap: register all CLI actions and menu entries
# ────────────────────────────────────────────

def _cli_user_info(app_config: Dict[str, Any], args: Tuple[str, ...]) -> None:
    get_user_info(app_config)


def _cli_usage_fee(app_config: Dict[str, Any], args: Tuple[str, ...]) -> None:
    export_usage_fee(app_config)


def _cli_policies(app_config: Dict[str, Any], args: Tuple[str, ...]) -> None:
    list_policies(app_config)


def _cli_region_subscriptions(app_config: Dict[str, Any], args: Tuple[str, ...]) -> None:
    print(render_region_subscriptions_cli(get_region_subscriptions_data(app_config)))


def _cli_bucket_info(app_config: Dict[str, Any], args: Tuple[str, ...]) -> None:
    print(render_bucket_info_cli(get_bucket_info_data(app_config)))


def _cli_audit_events(app_config: Dict[str, Any], args: Tuple[str, ...]) -> None:
    limit_text = args[0] if args else "20"
    print(render_audit_events_cli(get_audit_events_data(app_config, limit=int(limit_text)), limit=int(limit_text)))


def _cli_create_safe_policy(app_config: Dict[str, Any], args: Tuple[str, ...]) -> None:
    create_safe_policy(app_config, auto_approve=True)


def _cli_list_instances(app_config: Dict[str, Any], args: Tuple[str, ...]) -> None:
    list_instances(app_config)


def _cli_delete_policy(app_config: Dict[str, Any], args: Tuple[str, ...]) -> None:
    target_name = args[0] if args else ""
    delete_policy(app_config, target_name=target_name, auto_approve=True)


def _cli_instance_detail(app_config: Dict[str, Any], args: Tuple[str, ...]) -> None:
    instance_ref = args[0] if args else ""
    get_instance_detail(app_config, instance_ref=instance_ref)


def _cli_instance_start(app_config: Dict[str, Any], args: Tuple[str, ...]) -> None:
    instance_ref = args[0] if args else ""
    instance_action(app_config, action="start", instance_ref=instance_ref, auto_approve=True)


def _cli_instance_stop(app_config: Dict[str, Any], args: Tuple[str, ...]) -> None:
    instance_ref = args[0] if args else ""
    instance_action(app_config, action="stop", instance_ref=instance_ref, auto_approve=True)


def _cli_instance_restart(app_config: Dict[str, Any], args: Tuple[str, ...]) -> None:
    instance_ref = args[0] if args else ""
    instance_action(app_config, action="restart", instance_ref=instance_ref, auto_approve=True)


def _cli_instance_network(app_config: Dict[str, Any], args: Tuple[str, ...]) -> None:
    instance_ref = args[0] if args else ""
    show_instance_network_overview(app_config, instance_ref=instance_ref)


def _cli_instance_rules(app_config: Dict[str, Any], args: Tuple[str, ...]) -> None:
    if not args:
        raise ValueError("instance_rules 需要参数: instance_rules:<实例>[:page]")
    payload = args[0]
    if ":" in payload:
        instance_ref, page_text = payload.rsplit(":", 1)
        page = int(page_text)
    else:
        instance_ref, page = payload, 1
    print(render_instance_ingress_rules_cli(get_instance_ingress_rules_data(instance_ref.strip(), app_config, page=page, temp_only=False)))


def _cli_instance_temp_rules(app_config: Dict[str, Any], args: Tuple[str, ...]) -> None:
    if not args:
        raise ValueError("instance_temp_rules 需要参数: instance_temp_rules:<实例>[:page]")
    payload = args[0]
    if ":" in payload:
        instance_ref, page_text = payload.rsplit(":", 1)
        page = int(page_text)
    else:
        instance_ref, page = payload, 1
    print(render_instance_ingress_rules_cli(get_instance_ingress_rules_data(instance_ref.strip(), app_config, page=page, temp_only=True)))


def _cli_open_ingress_preview(app_config: Dict[str, Any], args: Tuple[str, ...]) -> None:
    if len(args) < 3:
        raise ValueError("open_ingress_preview 需要参数: open_ingress_preview:<实例>:<端口>:<CIDR>")
    print(render_open_ingress_preview_cli(preview_open_ingress_rule_data(args[0].strip(), args[1].strip(), args[2].strip(), app_config)))


def _cli_open_ingress_apply(app_config: Dict[str, Any], args: Tuple[str, ...]) -> None:
    if len(args) < 3:
        raise ValueError("open_ingress_apply 需要参数: open_ingress_apply:<实例>:<端口>:<CIDR>")
    result = apply_open_ingress_rule_data(args[0].strip(), args[1].strip(), args[2].strip(), app_config)
    print(result.get("message", "完成"))
    print(f"status={result.get('status', 'N/A')} target={result['target']['target_name']} port=TCP/{result['port']} source={result['source_cidr']}")


def _cli_cleanup_temp_rules_preview(app_config: Dict[str, Any], args: Tuple[str, ...]) -> None:
    if len(args) < 3:
        raise ValueError("cleanup_temp_rules_preview 需要参数: cleanup_temp_rules_preview:<实例>:<端口>:<CIDR>")
    print(render_cleanup_preview_cli(preview_cleanup_temp_rules_data(args[0].strip(), args[1].strip(), args[2].strip(), app_config)))


def _cli_cleanup_temp_rules_apply(app_config: Dict[str, Any], args: Tuple[str, ...]) -> None:
    if len(args) < 3:
        raise ValueError("cleanup_temp_rules_apply 需要参数: cleanup_temp_rules_apply:<实例>:<端口>:<CIDR>")
    result = apply_cleanup_temp_rules_data(args[0].strip(), args[1].strip(), args[2].strip(), app_config)
    print(result.get("message", "完成"))
    print(f"status={result.get('status', 'N/A')} removed={result.get('removed_count', 0)} target={result['target']['target_name']} port=TCP/{result['port']} source={result['source_cidr']}")


# Register CLI actions
def _register_all_actions() -> None:
    registry.register_cli("user_info", _cli_user_info, "查看当前用户详细信息")
    registry.register_cli("usage_fee", _cli_usage_fee, "导出本月费用账单 (CLI展示)")
    registry.register_cli("policies", _cli_policies, "查询当前密码策略看板")
    registry.register_cli("region_subscriptions", _cli_region_subscriptions, "查看已订阅 Region 列表")
    registry.register_cli("bucket_info", _cli_bucket_info, "查看 Object Storage / Bucket 信息")
    registry.register_cli("audit_events", _cli_audit_events, "查看 Audit Events")
    registry.register_cli("create_safe_policy", _cli_create_safe_policy, "创建/修复永不过期安全策略")
    registry.register_cli("list_instances", _cli_list_instances, "列出实例")
    registry.register_cli("delete_policy", _cli_delete_policy, "删除冗余密码策略")
    registry.register_cli("instance_detail", _cli_instance_detail, "查看实例详情")
    registry.register_cli("instance_start", _cli_instance_start, "启动实例")
    registry.register_cli("instance_stop", _cli_instance_stop, "停止实例")
    registry.register_cli("instance_restart", _cli_instance_restart, "重启实例")
    registry.register_cli("instance_network", _cli_instance_network, "查看实例网络/安全概览")
    registry.register_cli("instance_rules", _cli_instance_rules, "查看实例现有入站规则")
    registry.register_cli("instance_temp_rules", _cli_instance_temp_rules, "查看实例临时入站规则")
    registry.register_cli("open_ingress_preview", _cli_open_ingress_preview, "新增临时入站规则预览")
    registry.register_cli("open_ingress_apply", _cli_open_ingress_apply, "新增临时入站规则确认")
    registry.register_cli("cleanup_temp_rules_preview", _cli_cleanup_temp_rules_preview, "删除临时入站规则预览")
    registry.register_cli("cleanup_temp_rules_apply", _cli_cleanup_temp_rules_apply, "删除临时入站规则确认")

    registry.register_menu("👤 查看当前用户详细信息", "user_info", "查看当前用户详细信息")
    registry.register_menu("💰 导出本月费用账单 (CLI展示)", "usage_fee", "导出本月费用账单")
    registry.register_menu("🛡️  查询当前密码策略看板", "policies", "查询当前密码策略看板")
    registry.register_menu("🔒 创建/修复永不过期安全策略", "create_safe_policy", "创建/修复永不过期安全策略")
    registry.register_menu("🗑️  删除冗余密码策略", "delete_policy", "删除冗余密码策略")
    registry.register_menu("🖥️  列出实例", "list_instances", "列出实例")
    registry.register_menu("🔎 查看实例详情", "instance_detail", "查看实例详情")
    registry.register_menu("▶️  启动实例", "instance_start", "启动实例")
    registry.register_menu("⏹️  停止实例", "instance_stop", "停止实例")
    registry.register_menu("🔄 重启实例", "instance_restart", "重启实例")
    registry.register_menu("🌐 查看实例网络/安全概览", "instance_network", "查看实例网络/安全概览")
    registry.register_menu("🛡️ 查看实例现有入站规则", "instance_rules", "查看实例现有入站规则")
    registry.register_menu("🔓 新增临时入站规则（预览+确认）", "open_ingress_preview", "新增临时入站规则")
    registry.register_menu("🧹 删除临时入站规则（预览+确认）", "cleanup_temp_rules_preview", "删除临时入站规则")
    registry.register_menu("🌏 查看已订阅 Region 列表", "region_subscriptions", "查看已订阅 Region 列表")
    registry.register_menu("🪣 查看 Object Storage / Bucket 信息", "bucket_info", "查看 Object Storage / Bucket 信息")
    registry.register_menu("📋 查看 Audit Events", "audit_events", "查看 Audit Events")


_register_all_actions()
