#!/usr/bin/env python3
"""
集成 policy_menu 到 OCI_Master.py 的脚本
"""
import re

# 读取原文件
with open("OCI_Master.py", "r", encoding="utf-8") as f:
    content = f.read()

# 1. 在 imports 后添加新模块导入
imports_pattern = r"(from urllib3\.util\.retry import Retry)"
new_imports = r"\1\n\n# 导入新模块\nfrom telegram.menus.policy_menu import (\n    render_pm_home, render_pm_list, render_pm_create_step1,\n    render_pm_create_step2, render_pm_create_confirm,\n    render_pm_delete_list, render_pm_delete_confirm,\n    get_pm_state, set_pm_state, clear_pm_state,\n    validate_policy_name, validate_expires_days\n)\nfrom features.policies import create_policy, delete_policy"

if "from telegram.menus.policy_menu import" not in content:
    content = re.sub(imports_pattern, new_imports, content)
    print("✅ 添加了模块导入")
else:
    print("⏭️ 模块导入已存在")

# 2. 在命令列表中添加 policy_menu
commands_pattern = r'(\{"command": "instance_info".*?\})'
new_command = r'\1,\n            {"command": "policy_menu", "description": "密码策略菜单管理"}'

if '"policy_menu"' not in content:
    content = re.sub(commands_pattern, new_command, content)
    print("✅ 添加了命令注册")
else:
    print("⏭️ 命令注册已存在")

# 3. 在帮助文本中添加 policy_menu
help_pattern = r'("🖥️ /instance_info.*?\\n")'
new_help = r'\1\n            "🔐 /policy_menu - 密码策略菜单管理\\n"'

if '/policy_menu' not in content:
    content = re.sub(help_pattern, new_help, content)
    print("✅ 添加了帮助文本")
else:
    print("⏭️ 帮助文本已存在")

# 4. 在 handle_command 中添加 /policy_menu 处理
# 找到 /instance_info 的位置，在其后添加
policy_menu_handler = '''
        if normalized.startswith("/policy_menu"):
            try:
                text, keyboard = render_pm_home()
                return self.send_message_with_keyboard(chat_id, text, keyboard)
            except Exception as e:
                LOGGER.exception("打开策略菜单失败")
                return f"❌ 打开失败: {str(e)[:200]}"'''

if 'if normalized.startswith("/policy_menu")' not in content:
    # 在 /instance_info 后插入
    instance_info_end = content.find('return f"❌ 查询失败: {str(e)[:200]}"', content.find('if normalized.startswith("/instance_info")'))
    if instance_info_end > 0:
        insert_pos = content.find('\n        if normalized.startswith', instance_info_end)
        if insert_pos > 0:
            content = content[:insert_pos] + policy_menu_handler + content[insert_pos:]
            print("✅ 添加了 /policy_menu 命令处理")
        else:
            print("❌ 未找到插入位置")
    else:
        print("❌ 未找到 /instance_info 处理逻辑")
else:
    print("⏭️ 命令处理已存在")

# 5. 添加 callback_query 处理逻辑（在 handle_callback_query 中）
callback_handler = '''
        # Policy Menu 回调处理
        if data.startswith("pm:"):
            return self.handle_policy_menu_callback(chat_id, message_id, data, app_config)
        '''

if 'if data.startswith("pm:")' not in content:
    # 在 slm: 处理之后插入
    slm_pos = content.find('if data.startswith("slm:")')
    if slm_pos > 0:
        # 找到这个 if 块的结束位置
        next_if_pos = content.find('\n        if data.startswith', slm_pos + 100)
        if next_if_pos > 0:
            content = content[:next_if_pos] + callback_handler + content[next_if_pos:]
            print("✅ 添加了 callback 处理")
        else:
            print("❌ 未找到 callback 插入位置")
    else:
        print("❌ 未找到 slm: 处理逻辑")
else:
    print("⏭️ Callback 处理已存在")

# 6. 添加 handle_policy_menu_callback 方法
policy_menu_callback_method = '''
    def handle_policy_menu_callback(self, chat_id: int, message_id: int, data: str, app_config: Dict[str, Any]) -> None:
        """处理策略菜单回调"""
        try:
            parts = data.split(":")
            action = parts[1] if len(parts) > 1 else ""
            
            # 主菜单
            if action == "home":
                clear_pm_state(chat_id)
                text, keyboard = render_pm_home()
                return self.edit_message(chat_id, message_id, text, keyboard)
            
            # 查看策略列表
            elif action == "view":
                text, keyboard = render_pm_list(app_config)
                return self.edit_message(chat_id, message_id, text, keyboard)
            
            # 创建策略流程
            elif action == "create":
                if len(parts) == 2:
                    # 步骤1：输入策略名称
                    text, keyboard = render_pm_create_step1(chat_id)
                    return self.edit_message(chat_id, message_id, text, keyboard)
                elif parts[2] == "days":
                    # 步骤2：选择过期天数
                    state = get_pm_state(chat_id)
                    policy_name = state.get("policy_name", "")
                    if not policy_name:
                        return self.send_message(chat_id, "❌ 会话已过期，请重新开始")
                    
                    if len(parts) > 3 and parts[3] == "custom":
                        # 等待用户输入自定义天数
                        state["step"] = "create_wait_custom_days"
                        set_pm_state(chat_id, state)
                        return self.send_message(chat_id, "请输入自定义过期天数（0-36500）：")
                    else:
                        # 选择了预设天数
                        days = int(parts[3])
                        text, keyboard = render_pm_create_confirm(chat_id, policy_name, days)
                        return self.edit_message(chat_id, message_id, text, keyboard)
                elif parts[2] == "confirm":
                    # 确认创建
                    state = get_pm_state(chat_id)
                    policy_name = state.get("policy_name", "")
                    expires_days = int(parts[3])
                    
                    success, message = create_policy(policy_name, expires_days, app_config)
                    
                    clear_pm_state(chat_id)
                    
                    result_text = f"{message}\\n\\n"
                    if success:
                        result_text += "策略已创建成功！"
                    
                    keyboard = build_inline_keyboard([
                        [{"text": "📋 查看策略列表", "callback_data": "pm:view"}],
                        [{"text": "🏠 返回主菜单", "callback_data": "pm:home"}]
                    ])
                    
                    return self.edit_message(chat_id, message_id, result_text, keyboard)
                elif parts[2] == "back_to_days":
                    # 返回选择天数
                    state = get_pm_state(chat_id)
                    policy_name = state.get("policy_name", "")
                    text, keyboard = render_pm_create_step2(chat_id, policy_name)
                    return self.edit_message(chat_id, message_id, text, keyboard)
            
            # 删除策略流程
            elif action == "delete":
                if len(parts) == 2:
                    # 显示策略列表
                    text, keyboard = render_pm_delete_list(app_config)
                    return self.edit_message(chat_id, message_id, text, keyboard)
                elif parts[2] == "policy":
                    # 显示删除确认
                    policy_name = ":".join(parts[3:])  # 策略名可能包含冒号
                    text, keyboard = render_pm_delete_confirm(policy_name, app_config)
                    return self.edit_message(chat_id, message_id, text, keyboard)
                elif parts[2] == "confirm":
                    # 确认删除
                    policy_name = ":".join(parts[3:])
                    
                    success, message = delete_policy(policy_name, app_config)
                    
                    result_text = f"{message}\\n\\n"
                    
                    keyboard = build_inline_keyboard([
                        [{"text": "📋 查看策略列表", "callback_data": "pm:view"}],
                        [{"text": "🏠 返回主菜单", "callback_data": "pm:home"}]
                    ])
                    
                    return self.edit_message(chat_id, message_id, result_text, keyboard)
            
            else:
                return self.send_message(chat_id, f"❌ 未知操作: {data}")
        
        except Exception as e:
            LOGGER.exception("处理策略菜单回调失败")
            return self.send_message(chat_id, f"❌ 处理失败: {str(e)[:200]}")
'''

if 'def handle_policy_menu_callback' not in content:
    # 在 handle_sl_menu_callback 方法之后插入
    slm_callback_pos = content.rfind('def handle_sl_menu_callback')
    if slm_callback_pos > 0:
        # 找到这个方法的结束位置（下一个 def）
        next_method_pos = content.find('\n    def ', slm_callback_pos + 100)
        if next_method_pos > 0:
            content = content[:next_method_pos] + policy_menu_callback_method + content[next_method_pos:]
            print("✅ 添加了 handle_policy_menu_callback 方法")
        else:
            print("❌ 未找到方法插入位置")
    else:
        print("❌ 未找到 handle_sl_menu_callback 方法")
else:
    print("⏭️ Callback 方法已存在")

# 写回文件
with open("OCI_Master.py", "w", encoding="utf-8") as f:
    f.write(content)

print("\\n✅ 集成完成！")
