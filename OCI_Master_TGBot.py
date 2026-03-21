import oci
import os
import csv
from datetime import datetime, timezone
from io import StringIO
from telegram import Update, InputFile
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters, ConversationHandler
)

# === Telegram Bot 配置 ===
TELEGRAM_BOT_TOKEN = '放你的bot token'    # <-- 替换为你自己的 Telegram Bot Token
ALLOWED_CHAT_IDS = None  # 可选: 写 List[int] 只允许你本人用机器人

# ============ OCI 原始工具逻辑（只改输出方式） ==============

def oci_get_config():
    return oci.config.from_file()

def oci_get_identity_domains_client(config):
    identity_client = oci.identity.IdentityClient(config)
    domains = identity_client.list_domains(config["tenancy"]).data
    default_domain = next(d for d in domains if d.display_name == "Default")
    domain_url = default_domain.url.replace(":443", "")
    return oci.identity_domains.IdentityDomainsClient(config, service_endpoint=domain_url)

def oci_user_info():
    try:
        config = oci_get_config()
        identity_client = oci.identity.IdentityClient(config)
        response = identity_client.get_user(config["user"])
        if not hasattr(response, 'data') or not response.data:
            return "❌ 未能获取到用户信息。"
        u = response.data
        msg = (
            f"👤 OCI 当前用户信息：\n"
            f"用户名: {getattr(u, 'name', 'N/A')}\n"
            f"全名/描述: {getattr(u, 'description', 'N/A')}\n"
            f"用户 OCID: {getattr(u, 'id', 'N/A')}\n"
        )
        return msg
    except Exception as e:
        return f"❌ 获取用户信息失败: {e}"

def oci_export_usage_fee():
    try:
        config = oci_get_config()
        usage_client = oci.usage_api.UsageapiClient(config)
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

        if not response.data.items:
            return "本月无费用数据。", None

        sorted_items = sorted(response.data.items, key=lambda x: x.time_usage_started)
        output = StringIO()
        writer = csv.writer(output)
        writer.writerow(['日期', '服务名称', '金额', '币种'])
        total_cost = 0.0
        currency = "USD"
        lines = []
        for item in sorted_items:
            date_str = item.time_usage_started.strftime('%Y-%m-%d')
            service = getattr(item, 'service', "Unknown Service") or "Unknown Service"
            amount = getattr(item, 'computed_amount', 0.0) or 0.0
            currency = getattr(item, 'currency', "USD") or "USD"
            total_cost += amount
            writer.writerow([date_str, service, f"{amount:.4f}", currency])
            lines.append(f"{date_str} | {service} | {amount:.4f} {currency}")

        msg = (
            "💰 本月费用账单导出如下：\n\n" +
            "\n".join(lines) +
            f"\n\n本月预估总计: {total_cost:.4f} {currency}\n"
            "CSV 文件也随消息发送。"
        )
        output.seek(0)
        return msg, output
    except Exception as e:
        return f"❌ 账单导出失败: {e}", None

def oci_list_policies():
    try:
        config = oci_get_config()
        id_domains_client = oci_get_identity_domains_client(config)
        response = id_domains_client.list_password_policies()
        resources = getattr(response.data, 'resources', [])
        if not resources:
            return "❌ 未发现任何密码策略。"
        sorted_policies = sorted(resources, key=lambda x: getattr(x, 'priority', 999) if getattr(x, 'priority', None) is not None else 999)
        msg = "🛡️ 当前 OCI 密码策略:\n\n"
        for idx, p in enumerate(sorted_policies):
            name = getattr(p, 'name', 'N/A')
            priority = getattr(p, 'priority', 'N/A')
            expires = getattr(p, 'password_expires_after', 'N/A')
            is_top = (idx == 0)
            status = "🚀 正在生效" if is_top else "⏳ 备用/次要"
            expire_display = "永不过期" if expires == 0 else f"{expires} 天"
            msg += f"- {name} | 优先级:{priority} | 过期: {expire_display} | {status}\n"
        return msg
    except Exception as e:
        return f"❌ 查询策略失败: {e}"

def oci_create_safe_policy():
    try:
        config = oci_get_config()
        id_domains_client = oci_get_identity_domains_client(config)
        from oci.identity_domains import models
        response = id_domains_client.list_password_policies()
        resources = getattr(response.data, 'resources', [])
        std_policy = next((p for p in resources if getattr(p, 'name', '') == 'standardPasswordPolicy'), None)
        if not std_policy:
            return "❌ 未找到标准策略，无法克隆。"
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
        res = id_domains_client.create_password_policy(password_policy=new_policy_obj)
        if res.status == 201:
            return "✅ 已成功创建『NeverExpireStandard』。"
        else:
            return f"⚠️ 状态异常: {res.status}"
    except Exception as e:
        if "already exists" in str(e).lower():
            return "💡 提醒：策略已存在，系统保持当前设置。"
        return f"❌ 同步失败: {e}"

def oci_delete_policy(policy_name):
    try:
        config = oci_get_config()
        id_domains_client = oci_get_identity_domains_client(config)
        response = id_domains_client.list_password_policies()
        resources = getattr(response.data, 'resources', [])
        target_policy = next((p for p in resources if getattr(p, 'name', '') == policy_name), None)
        if not target_policy:
            return f"❌ 未找到名为 '{policy_name}' 的策略。"
        res = id_domains_client.delete_password_policy(password_policy_id=target_policy.id)
        if res.status == 204:
            return f"✅ 成功删除策略: {policy_name}"
        return f"⚠️ 删除策略状态码: {res.status}"
    except Exception as e:
        if "checkProtectedResource" in str(e):
            return f"❌ 删除失败：'{policy_name}' 是系统预设资源，禁止删除。"
        return f"❌ 删除出错: {e}"

# ============ Telegram Handler 交互部分 ===============

# 用于多步骤的对话状态
ASK_DELETE_POLICY_NAME, ASK_DELETE_POLICY_CONFIRM = range(2)

# 内部权限控制
def is_allowed(update: Update):
    return not ALLOWED_CHAT_IDS or update.effective_chat.id in ALLOWED_CHAT_IDS

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        await update.message.reply_text("你没有权限使用此Bot。")
        return
    await update.message.reply_text(
        "欢迎使用 OCI Master Tool Bot！可用命令：\n"
        "/user - 查询当前用户\n"
        "/usage - 导出本月账单并发送（CSV）\n"
        "/policy - 查看密码策略\n"
        "/add_policy - 创建永不过期策略\n"
        "/del_policy - 删除策略"
    )

async def user_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return
    await update.message.reply_text(oci_user_info())

async def usage_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return
    msg, output = oci_export_usage_fee()
    await update.message.reply_text(msg)
    if output:
        output.seek(0)
        await update.message.reply_document(document=InputFile(output, filename="oci_costs.csv"))

async def policy_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return
    await update.message.reply_text(oci_list_policies())

async def add_policy_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return
    msg = (
        "⚠️ 即将基于官方标准规则克隆一个【永不过期】的最高优先级策略。\n"
        "确定要继续创建吗？请回复 “是” 或 “否”。"
    )
    context.user_data['add_policy_pending'] = True
    await update.message.reply_text(msg)

async def add_policy_confirm_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('add_policy_pending'):
        if update.message.text.strip().lower() in ['是','y','yes','ok']:
            await update.message.reply_text("正在操作...")
            await update.message.reply_text(oci_create_safe_policy())
        else:
            await update.message.reply_text("🍀 已取消创建。")
        context.user_data['add_policy_pending'] = False

async def del_policy_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return ConversationHandler.END
    # 展示策略让用户选
    msg = oci_list_policies()
    await update.message.reply_text(msg)
    await update.message.reply_text("请输入要删除的策略名称（完全一致，区分大小写），或发送“取消”取消。")
    return ASK_DELETE_POLICY_NAME

async def del_policy_askname(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    if name.lower() == "取消":
        await update.message.reply_text("已取消。")
        return ConversationHandler.END
    context.user_data['policy_name'] = name
    await update.message.reply_text(
        f"⚠️ 确认永久删除策略“{name}”吗？回复“是”以确认，其他任意输入取消。"
    )
    return ASK_DELETE_POLICY_CONFIRM

async def del_policy_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    confirmed = update.message.text.strip().lower() in ['是','y','yes','ok']
    policy_name = context.user_data.get('policy_name')
    if confirmed and policy_name:
        await update.message.reply_text("正在删除...")
        await update.message.reply_text(oci_delete_policy(policy_name))
    else:
        await update.message.reply_text("已取消。")
    return ConversationHandler.END

# 其它消息用于 add_policy 二次确认
async def catchall(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await add_policy_confirm_reply(update, context)

# ============== 启动您的Bot =================
def main():
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("user", user_handler))
    app.add_handler(CommandHandler("usage", usage_handler))
    app.add_handler(CommandHandler("policy", policy_handler))
    app.add_handler(CommandHandler("add_policy", add_policy_handler))

    del_conv = ConversationHandler(
        entry_points=[CommandHandler("del_policy", del_policy_handler)],
        states={
            ASK_DELETE_POLICY_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, del_policy_askname)],
            ASK_DELETE_POLICY_CONFIRM: [MessageHandler(filters.TEXT & ~filters.COMMAND, del_policy_confirm)],
        },
        fallbacks=[]
    )
    app.add_handler(del_conv)

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, catchall))

    print("Bot running...")
    app.run_polling()

if __name__ == "__main__":
    main()
