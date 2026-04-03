import oci
import os
import csv
from datetime import datetime, timezone

# ==========================================
# 1. 全局配置与辅助函数
# ==========================================
def get_config():
    """加载 OCI 配置"""
    return oci.config.from_file()

def get_identity_domains_client(config):
    """辅助函数：获取身份域客户端"""
    identity_client = oci.identity.IdentityClient(config)
    domains = identity_client.list_domains(config["tenancy"]).data
    default_domain = next(d for d in domains if d.display_name == "Default")
    domain_url = default_domain.url.replace(":443", "")
    return oci.identity_domains.IdentityDomainsClient(config, service_endpoint=domain_url)

def _print_policy_table(id_domains_client):
    """内部辅助函数：获取并打印策略列表 (供功能3、4、5复用)"""
    response = id_domains_client.list_password_policies()
    resources = getattr(response.data, 'resources', [])
    
    if not resources:
        print("❌ 未发现任何策略。")
        return False

    # 排序逻辑：将 None 视为最低优先级 (999)
    sorted_policies = sorted(resources, key=lambda x: getattr(x, 'priority', 999) if getattr(x, 'priority', None) is not None else 999)

    print(f"\n{'策略名称':<25} | {'优先级':<6} | {'过期天数':<12} | {'当前状态'}")
    print("-" * 80)

    for p in sorted_policies:
        raw_name = getattr(p, 'name', 'N/A')
        name = str(raw_name) if raw_name is not None else "N/A"
        
        raw_priority = getattr(p, 'priority', 'N/A')
        priority = str(raw_priority) if raw_priority is not None else "N/A"
        
        raw_expires = getattr(p, 'password_expires_after', 'N/A')
        expires = str(raw_expires) if raw_expires is not None else "N/A"
        
        is_top = (p == sorted_policies[0])
        status = "🚀 正在生效 (最高)" if is_top else "⏳ 备用/次要"
        expire_display = f"{expires} (永不过期)" if expires == "0" else f"{expires} 天"
        
        print(f"{name:<25} | {priority:<6} | {expire_display:<12} | {status}")

    print("-" * 80)
    return True

# ==========================================
# 2. 核心功能模块
# ==========================================

def get_user_info():
    """功能 1：查询当前用户信息"""
    print("\n" + "="*40)
    print("👤 正在查询用户信息...")
    try:
        config = get_config()
        identity_client = oci.identity.IdentityClient(config)
        response = identity_client.get_user(config["user"])
        
        if response and hasattr(response, 'data') and response.data:
            user_data = response.data
            print(f"✅ 连接成功！")
            print(f"   用户名 (Name): {getattr(user_data, 'name', 'N/A')}")
            print(f"   描述/全名   : {getattr(user_data, 'description', 'N/A')}")
            print(f"   用户 OCID   : {getattr(user_data, 'id', 'N/A')}")
        else:
            print("❌ 未能获取到用户信息，返回数据为空。")
    except Exception as e:
        print(f"❌ 连接失败，请检查配置：\n{e}")

def export_usage_fee():
    """功能 2：导出本月费用账单"""
    print("\n" + "="*65)
    print("💰 正在查询并导出本月费用数据...")
    try:
        config = get_config()
        usage_client = oci.usage_api.UsageapiClient(config)
        script_dir = os.path.dirname(os.path.abspath(__file__))
        
        now_utc = datetime.now(timezone.utc)
        start_time = now_utc.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end_time = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)

        request_details = oci.usage_api.models.RequestSummarizedUsagesDetails(
            tenant_id=config["tenancy"],
            time_usage_started=start_time,
            time_usage_ended=end_time,
            granularity='DAILY',
            query_type='COST',
            group_by=['service']
        )
        
        response = usage_client.request_summarized_usages(request_details)
        total_cost = 0.0
        currency = "USD"
        
        if not response.data.items:
            print("提示：此时间段内没有产生任何费用数据。")
        else:
            sorted_items = sorted(response.data.items, key=lambda x: x.time_usage_started)
            filename = f"oci_costs_{start_time.strftime('%Y_%m')}.csv"
            csv_filepath = os.path.join(script_dir, filename)
            
            with open(csv_filepath, 'w', newline='', encoding='utf-8-sig') as f:
                writer = csv.writer(f)
                writer.writerow(['日期', '服务名称', '金额', '币种'])
                
                print(f"{'日期':<12} | {'服务名称':<30} | {'金额':<10}")
                print("-" * 65)
                
                for item in sorted_items:
                    date_str = item.time_usage_started.strftime('%Y-%m-%d')
                    service = getattr(item, 'service', "Unknown Service") or "Unknown Service"
                    amount = getattr(item, 'computed_amount', 0.0) or 0.0
                    currency = getattr(item, 'currency', "USD") or "USD"
                    
                    total_cost += amount
                    print(f"{date_str:<12} | {service:<30} | {amount:.4f} {currency}")
                    writer.writerow([date_str, service, f"{amount:.4f}", currency])
            
            print("-" * 65)
            print(f"📊 本月预估总计: {total_cost:.4f} {currency}")
            print(f"✅ 数据已成功保存至: {csv_filepath}")
    except Exception as e:
        print(f"❌ 运行出错: {e}")

def list_policies():
    """功能 3：查询当前密码策略状态"""
    print("\n" + "="*80)
    print("🛡️ 正在获取身份域密码策略看板...")
    try:
        config = get_config()
        id_domains_client = get_identity_domains_client(config)
        _print_policy_table(id_domains_client)
    except Exception as e:
        print(f"❌ 查询失败: {e}")

def create_safe_policy():
    """功能 4：创建永不过期安全策略 (带二次确认和结果打印)"""
    print("\n" + "="*80)
    # 优化点 3：增加二次确认
    confirm = input("⚠️ 即将基于官方标准规则克隆一个【永不过期】的最高优先级策略。\n👉 确定要继续创建吗？(y/n): ").strip().lower()
    if confirm != 'y':
        print("🛑 已取消创建操作。")
        return

    print("🔒 正在分析现有策略并同步 Standard 规则...")
    try:
        config = get_config()
        id_domains_client = get_identity_domains_client(config)
        from oci.identity_domains import models
        
        response = id_domains_client.list_password_policies()
        resources = getattr(response.data, 'resources', [])
        std_policy = next((p for p in resources if getattr(p, 'name', '') == 'standardPasswordPolicy'), None)
        
        if not std_policy:
            print("❌ 未能定位到 standardPasswordPolicy，无法进行安全同步。")
            return
            
        new_policy_name = "NeverExpireStandard"
        new_policy_details = {
            "name": new_policy_name,
            "description": "基于 Standard 规则克隆，由 API 强制设为永不过期 (Priority 1)",
            "schemas": ["urn:ietf:params:scim:schemas:oracle:idcs:PasswordPolicy"],
            "priority": 1,
            "password_expires_after": 0,
            "min_length": getattr(std_policy, 'min_length', 8),
            "max_length": getattr(std_policy, 'max_length', 40),
            "min_lower_case": getattr(std_policy, 'min_lower_case', 1),
            "min_upper_case": getattr(std_policy, 'min_upper_case', 1),
            "min_numerals": getattr(std_policy, 'min_numerals', 1),
            "min_special_chars": getattr(std_policy, 'min_special_chars', 0),
            "max_incorrect_attempts": getattr(std_policy, 'max_incorrect_attempts', 5),
            "lockout_duration": getattr(std_policy, 'lockout_duration', 30),
            "num_passwords_in_history": getattr(std_policy, 'num_passwords_in_history', 1),
            "user_name_disallowed": getattr(std_policy, 'user_name_disallowed', True),
            "first_name_disallowed": getattr(std_policy, 'first_name_disallowed', True),
            "last_name_disallowed": getattr(std_policy, 'last_name_disallowed', True)
        }
        
        new_policy_obj = models.PasswordPolicy(**new_policy_details)
        print(f"--- 正在推送新策略: {new_policy_name} ---")
        res = id_domains_client.create_password_policy(password_policy=new_policy_obj)
        
        if res.status == 201:
            print(f"✅ 成功！已创建『{new_policy_name}』。")
            # 优化点 2：执行成功后打印所有策略，方便确认
            print("\n🔍 最新的策略列表如下，请确认新策略是否已生效：")
            _print_policy_table(id_domains_client)
        else:
            print(f"⚠️ 状态异常: {res.status}")
    except Exception as e:
        if "already exists" in str(e).lower():
            print(f"💡 提醒：策略已存在，系统保持当前设置。")
        else:
            print(f"❌ 同步失败: {e}")

def delete_policy():
    """功能 5：删除指定密码策略 (先打印查询，再二次确认)"""
    print("\n" + "="*80)
    print("🗑️ 准备删除策略，正在拉取当前策略列表...")
    try:
        config = get_config()
        id_domains_client = get_identity_domains_client(config)
        
        # 优化点 1：先查询现有策略并打印
        has_policies = _print_policy_table(id_domains_client)
        if not has_policies:
            return

        target_name = input("\n👉 请输入表格中要删除的【策略名称】(直接回车可取消操作): ").strip()
        if not target_name:
            print("🛑 已取消操作。")
            return
            
        # 优化点 3：增加二次确认按钮操作
        confirm = input(f"⚠️ 警告: 确定要永久删除策略 '{target_name}' 吗？(y/n): ").strip().lower()
        if confirm != 'y':
            print("🛑 已取消删除操作。")
            return

        print(f"--- 正在执行删除: {target_name} ---")
        response = id_domains_client.list_password_policies()
        resources = getattr(response.data, 'resources', [])
        target_policy = next((p for p in resources if getattr(p, 'name', '') == target_name), None)
        
        if not target_policy:
            print(f"⚠️ 未找到名为 '{target_name}' 的策略，请检查拼写大小写是否正确。")
            return

        res = id_domains_client.delete_password_policy(password_policy_id=target_policy.id)
        if res.status == 204:
            print(f"✅ 成功删除策略: {target_name}")
            # 删除后再次刷新列表供确认
            print("\n🔍 删除后的最新策略列表如下：")
            _print_policy_table(id_domains_client)
        else:
            print(f"⚠️ 删除返回状态码: {res.status}")
    except Exception as e:
        if "checkProtectedResource" in str(e):
            print(f"❌ 删除失败：'{target_name}' 是系统预设的保护资源，官方禁止删除。")
        else:
            print(f"❌ 操作出错: {e}")

# ==========================================
# 3. 主程序交互菜单
# ==========================================
def main_menu():
    # 优化点 4：清屏变量，用于美化终端显示
    clear_cmd = 'cls' if os.name == 'nt' else 'clear'
    
    while True:
        print("\n" + "☁️  OCI 甲骨文云一键运维工具 ☁️ ".center(50))
        print("=" * 55)
        print("  1. 👤 查看当前用户信息")
        print("  2. 💰 导出本月费用账单 (CSV)")
        print("  3. 🛡️  查询当前密码策略看板")
        print("  4. 🔒 创建/修复永不过期安全策略")
        print("  5. 🗑️  删除冗余密码策略")
        print("  0. 🚪 退出程序")
        print("=" * 55)
        
        choice = input("👉 请选择要执行的功能 (0-5): ").strip()
        
        # 优化点 4：无效输入校验
        if choice not in ['0', '1', '2', '3', '4', '5']:
            os.system(clear_cmd)
            print("❌ 指令无效！请重新输入菜单前方的数字 (0 到 5 之间)。")
            continue
            
        if choice == '1':
            get_user_info()
        elif choice == '2':
            export_usage_fee()
        elif choice == '3':
            list_policies()
        elif choice == '4':
            create_safe_policy()
        elif choice == '5':
            delete_policy()
        elif choice == '0':
            print("\n👋 感谢使用，已安全退出程序！\n")
            break
            
        # 操作完成后暂停，等待用户阅读结果后再刷新菜单
        input("\n⌨️  按 [Enter] 键返回主菜单...")
        os.system(clear_cmd)

if __name__ == "__main__":
    # 捕获 Ctrl+C，实现优雅退出
    try:
        # 启动时先清一下屏
        os.system('cls' if os.name == 'nt' else 'clear')
        main_menu()
    except KeyboardInterrupt:
        print("\n\n👋 程序已被手动中止，再见！\n")