import os
import sys
from typing import Dict, List, Optional, Tuple

from oci_master.config import load_app_config
from oci_master.services.billing import export_usage_fee
from oci_master.services.instances import get_instance_detail, instance_action, list_instances
from oci_master.services.network_security import (
    get_instance_ingress_rules_data,
    preview_cleanup_temp_rules,
    preview_open_ingress_rule,
    render_instance_ingress_rules_cli,
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


def print_cli_menu() -> None:
    print("\n" + "☁️  OCI 甲骨文云一键运维工具 ☁️ ".center(50))
    print("=" * 62)
    print("  1. 👤 查看当前用户详细信息")
    print("  2. 💰 导出本月费用账单 (CLI展示)")
    print("  3. 🛡️  查询当前密码策略看板")
    print("  4. 🔒 创建/修复永不过期安全策略")
    print("  5. 🗑️  删除冗余密码策略")
    print("  6. 🤖 启动 Telegram Bot 轮询")
    print("  7. 🖥️  列出实例")
    print("  8. 🔎 查看实例详情")
    print("  9. ▶️  启动实例")
    print(" 10. ⏹️  停止实例")
    print(" 11. 🔄 重启实例")
    print(" 12. 🌐 查看实例网络/安全概览")
    print(" 13. 🛡️ 查看实例现有入站规则")
    print(" 14. 🔓 新增临时入站规则（预览+确认）")
    print(" 15. 🧹 删除临时入站规则（预览+确认）")
    print(" 16. 🌏 查看已订阅 Region 列表")
    print(" 17. 🪣 查看 Object Storage / Bucket 信息")
    print(" 18. 📋 查看 Audit Events")
    print("  0. 🚪 退出程序")
    print("=" * 62)


def main_menu(app_config: Dict[str, object]) -> None:
    clear_cmd = "cls" if os.name == "nt" else "clear"

    while True:
        print_cli_menu()
        choice = input("👉 请选择要执行的功能 (0-18): ").strip()

        if choice not in [str(i) for i in range(19)]:
            os.system(clear_cmd)
            print("❌ 指令无效！请重新输入菜单前方的数字 (0 到 18 之间)。")
            continue

        if choice == "1":
            get_user_info(app_config)
        elif choice == "2":
            export_usage_fee(app_config)
        elif choice == "3":
            list_policies(app_config)
        elif choice == "4":
            create_safe_policy(app_config)
        elif choice == "5":
            delete_policy(app_config)
        elif choice == "6":
            TelegramBotRunner(app_config).run_polling()
        elif choice == "7":
            list_instances(app_config)
        elif choice == "8":
            get_instance_detail(app_config)
        elif choice == "9":
            instance_action(app_config, action="start")
        elif choice == "10":
            instance_action(app_config, action="stop")
        elif choice == "11":
            instance_action(app_config, action="restart")
        elif choice == "12":
            show_instance_network_overview(app_config)
        elif choice == "13":
            show_instance_ingress_rules(app_config)
        elif choice == "14":
            preview_open_ingress_rule(app_config)
        elif choice == "15":
            preview_cleanup_temp_rules(app_config)
        elif choice == "16":
            show_region_subscriptions(app_config)
        elif choice == "17":
            show_bucket_info(app_config)
        elif choice == "18":
            show_audit_events(app_config)
        elif choice == "0":
            print("\n👋 感谢使用，已安全退出程序！\n")
            break

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
    action_name, args = parse_action(action)
    action = action_name if not args else ":".join((action_name, *args))
    if action == "user_info":
        get_user_info(app_config)
    elif action == "usage_fee":
        export_usage_fee(app_config)
    elif action == "policies":
        list_policies(app_config)
    elif action == "region_subscriptions":
        print(render_region_subscriptions_cli(get_region_subscriptions_data(app_config)))
    elif action == "bucket_info":
        print(render_bucket_info_cli(get_bucket_info_data(app_config)))
    elif action == "audit_events":
        print(render_audit_events_cli(get_audit_events_data(app_config, limit=20), limit=20))
    elif action.startswith("audit_events:"):
        limit_text = action.split(":", 1)[1].strip() or "20"
        print(render_audit_events_cli(get_audit_events_data(app_config, limit=int(limit_text)), limit=int(limit_text)))
    elif action == "create_safe_policy":
        create_safe_policy(app_config, auto_approve=True)
    elif action == "list_instances":
        list_instances(app_config)
    elif action.startswith("delete_policy:"):
        delete_policy(app_config, target_name=action.split(":", 1)[1].strip(), auto_approve=True)
    elif action.startswith("instance_detail:"):
        get_instance_detail(app_config, instance_ref=action.split(":", 1)[1].strip())
    elif action.startswith("instance_start:"):
        instance_action(app_config, action="start", instance_ref=action.split(":", 1)[1].strip(), auto_approve=True)
    elif action.startswith("instance_stop:"):
        instance_action(app_config, action="stop", instance_ref=action.split(":", 1)[1].strip(), auto_approve=True)
    elif action.startswith("instance_restart:"):
        instance_action(app_config, action="restart", instance_ref=action.split(":", 1)[1].strip(), auto_approve=True)
    elif action.startswith("instance_network:"):
        show_instance_network_overview(app_config, instance_ref=action.split(":", 1)[1].strip())
    elif action.startswith("instance_rules:"):
        payload = action.split(":", 1)[1].strip()
        if not payload:
            raise ValueError("instance_rules 需要参数: instance_rules:<实例>[:page]")
        if ":" in payload:
            instance_ref, page_text = payload.rsplit(":", 1)
            page = int(page_text)
        else:
            instance_ref, page = payload, 1
        print(render_instance_ingress_rules_cli(get_instance_ingress_rules_data(instance_ref.strip(), app_config, page=page, temp_only=False)))
    elif action.startswith("instance_temp_rules:"):
        payload = action.split(":", 1)[1].strip()
        if not payload:
            raise ValueError("instance_temp_rules 需要参数: instance_temp_rules:<实例>[:page]")
        if ":" in payload:
            instance_ref, page_text = payload.rsplit(":", 1)
            page = int(page_text)
        else:
            instance_ref, page = payload, 1
        print(render_instance_ingress_rules_cli(get_instance_ingress_rules_data(instance_ref.strip(), app_config, page=page, temp_only=True)))
    elif action.startswith("open_ingress_preview:"):
        from oci_master.services.network_security import preview_open_ingress_rule_data, render_open_ingress_preview_cli
        parts = action.split(":", 3)
        if len(parts) < 4:
            raise ValueError("open_ingress_preview 需要参数: open_ingress_preview:<实例>:<端口>:<CIDR>")
        print(render_open_ingress_preview_cli(preview_open_ingress_rule_data(parts[1].strip(), parts[2].strip(), parts[3].strip(), app_config)))
    elif action.startswith("open_ingress_apply:"):
        from oci_master.services.network_security import apply_open_ingress_rule_data
        parts = action.split(":", 3)
        if len(parts) < 4:
            raise ValueError("open_ingress_apply 需要参数: open_ingress_apply:<实例>:<端口>:<CIDR>")
        result = apply_open_ingress_rule_data(parts[1].strip(), parts[2].strip(), parts[3].strip(), app_config)
        print(result.get("message", "完成"))
        print(f"status={result.get('status', 'N/A')} target={result['target']['target_name']} port=TCP/{result['port']} source={result['source_cidr']}")
    elif action.startswith("cleanup_temp_rules_preview:"):
        from oci_master.services.network_security import preview_cleanup_temp_rules_data, render_cleanup_preview_cli
        parts = action.split(":", 3)
        if len(parts) < 4:
            raise ValueError("cleanup_temp_rules_preview 需要参数: cleanup_temp_rules_preview:<实例>:<端口>:<CIDR>")
        print(render_cleanup_preview_cli(preview_cleanup_temp_rules_data(parts[1].strip(), parts[2].strip(), parts[3].strip(), app_config)))
    elif action.startswith("cleanup_temp_rules_apply:"):
        from oci_master.services.network_security import apply_cleanup_temp_rules_data
        parts = action.split(":", 3)
        if len(parts) < 4:
            raise ValueError("cleanup_temp_rules_apply 需要参数: cleanup_temp_rules_apply:<实例>:<端口>:<CIDR>")
        result = apply_cleanup_temp_rules_data(parts[1].strip(), parts[2].strip(), parts[3].strip(), app_config)
        print(result.get("message", "完成"))
        print(f"status={result.get('status', 'N/A')} removed={result.get('removed_count', 0)} target={result['target']['target_name']} port=TCP/{result['port']} source={result['source_cidr']}")
    else:
        raise ValueError(
            "不支持的 action。可选: user_info, usage_fee, policies, region_subscriptions, bucket_info, audit_events[:N], create_safe_policy, list_instances, delete_policy:<名称>, instance_detail:<实例>, instance_start:<实例>, instance_stop:<实例>, instance_restart:<实例>, instance_network:<实例>, instance_rules:<实例>[:page], instance_temp_rules:<实例>[:page], open_ingress_preview:<实例>:<端口>:<CIDR>, open_ingress_apply:<实例>:<端口>:<CIDR>, cleanup_temp_rules_preview:<实例>:<端口>:<CIDR>, cleanup_temp_rules_apply:<实例>:<端口>:<CIDR>"
        )


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
