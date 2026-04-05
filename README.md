# ☁️ OCI Master - 甲骨文云一键运维助手

OCI Master 是一个基于 Python 与 Oracle Cloud Infrastructure (OCI) SDK 的轻量级工具，帮助甲骨文云用户完成日常运维：账单查询导出、密码策略治理（支持“永不过期”策略）以及 Telegram 机器人查询等。

## 📦 版本 v1.1.0（2026-04-05）
- 🎨 移动端 UI：费用/用户/策略输出改为卡片式布局，更适合 Telegram/手机阅读
- 🧭 费用视图：日期倒序、每日小计、服务明细（Top3 + 其他汇总）
- 🧩 服务识别：自动添加中文名称与表情图标（计算/存储/网络/数据库等）
- 🔐 安全增强：授权白名单严格校验、Bot Token 环境变量优先、HTML 转义、配置必填校验
- ⚙️ 健壮性：空数据友好提示、常量化魔法数字、超时优化（timeout=(5,60)）

## ✨ 主要功能（Features）
- 🛡️ 密码策略治理：一键克隆官方标准，创建优先级最高的“永不过期”策略（可回滚/对比）
- 💰 费用导出：按日历月统计各服务扣费明细，UTF-8-SIG CSV（兼容 Excel）
- 🤖 本地运行：基于 OCI 官方 SDK 直连，无需第三方托管密钥
- 🧭 多平台支持：Windows / Linux / macOS
- 💬 Telegram 机器人：随时查询费用、用户信息、密码策略（移动端友好展示）

---

## 🚀 快速开始（Quick Start）

### 1) 获取 OCI API 凭证
- 控制台路径：身份和安全 (Identity & Security) → 域 (Domain) → 用户 (User) → API 密钥
- 添加 API 密钥并下载 .pem 私钥；复制生成的配置信息（user、tenancy、fingerprint、region 等）
- 权限要求：建议将 API 用户加入 Identity Domain Administrator 或 Security Administrator 组

### 2) 配置凭证文件
- 私钥建议路径：
  - Windows: `C:\Users\<Username>\.oci\oci_api_key.pem`
  - Linux/macOS: `~/.oci/oci_api_key.pem`
- 创建 `config` 文件（与私钥同目录），示例：

```ini
[DEFAULT]
user=ocid1.user.oc1..xxxxxx
fingerprint=xx:xx:xx:xx:xx:xx:xx:xx:xx:xx:xx:xx:xx:xx:xx:xx
tenancy=ocid1.tenancy.oc1..xxxxxx
region=ap-tokyo-1
key_file=/absolute/path/to/.oci/oci_api_key.pem
```

- Linux/macOS 需收紧私钥权限：
```bash
chmod 600 ~/.oci/oci_api_key.pem
```

### 3) 安装依赖
```bash
pip install -r requirements.txt  # 若无此文件，可执行： pip install oci requests
```

---

## 🧪 使用方式（Usage）

### A. CLI 模式（交互式菜单）
- 启动：
```bash
python3 OCI_Master.py
```
- 菜单示例：
```plaintext
  1. 👤 查看当前用户信息
  2. 💰 导出本月费用账单 (CSV)
  3. 🛡️ 查询当前密码策略看板
  4. 🔒 创建/修复永不过期安全策略
  5. 🗑️ 删除冗余密码策略
  6. 🚪 退出程序
```

### B. Telegram Bot 模式（移动端友好）

#### 基础配置
- 在 `oci_master_config.json` 中启用 Telegram（token 推荐走环境变量，见下节）：
```json
{
  "telegram": {
    "enabled": true,
    "bot_token": "留空或删除，推荐用环境变量",
    "allowed_chat_ids": ["123456789", "-1001234567890"],
    "allowed_user_ids": ["987654321"]
  }
}
```
- 启动：
```bash
python3 OCI_Master.py telegram
```

#### 安全配置（强烈推荐）
- 环境变量优先级（从高到低）：
  1. `OCI_MASTER_BOT_TOKEN`（最高优先，推荐）
  2. 配置文件 `telegram.bot_token`
- 白名单授权逻辑：
  - 配置了 `allowed_chat_ids` 则消息必须来自白名单聊天
  - 配置了 `allowed_user_ids` 则消息必须来自白名单用户
  - 两者可同时配置（严格模式）；未授权请求会被拒绝并记录警告日志
- 获取 ID：可使用 @userinfobot（user_id）与 @getidsbot（chat_id）

#### systemd 服务部署（推荐）
- 最简服务示例（推荐使用 EnvironmentFile）：
```bash
# 环境文件（更安全）
echo 'OCI_MASTER_BOT_TOKEN=你的_token' | sudo tee /etc/oci-master.env
sudo chmod 600 /etc/oci-master.env

# 服务单元
sudo tee /etc/systemd/system/oci-master-telegram.service >/dev/null <<'EOF'
[Unit]
Description=OCI Master Telegram runner
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/root/.openclaw/workspace/tmp/OCI-Master-Tool
Environment=OCI_MASTER_APP_CONFIG=/root/oci_master_config.json
EnvironmentFile=/etc/oci-master.env
ExecStart=/usr/bin/python3 /root/.openclaw/workspace/tmp/OCI-Master-Tool/OCI_Master.py telegram
Restart=always
RestartSec=5s
KillSignal=SIGTERM
TimeoutStopSec=15
StandardOutput=journal
StandardError=journal
User=root

[Install]
WantedBy=multi-user.target
EOF

# 生效并启动
sudo systemctl daemon-reload
sudo systemctl enable --now oci-master-telegram.service
sudo systemctl --no-pager -l status oci-master-telegram.service
```

#### 命令列表
- 👤 `/user_info` — 用户账号信息（基础/联系方式/权限/安全状态）
- 💰 `/usage_fee` — 本月费用账单（按日汇总 + 服务明细）
- 🛡️ `/policies` — 密码策略看板（按优先级、当前生效高亮）
- 🔒 `/create_safe_policy` — 创建永不过期策略
- 🗑️ `/delete_policy <名称>` — 删除指定策略
- 💬 `/help` — 分类帮助菜单

> 说明：机器人自动使用 HTML 渲染（parse_mode=HTML），无需额外配置。

示例（/usage_fee）：
```
💰 本月费用汇总
查询区间: 2026-04-01 ~ 2026-04-05
本月预估总计: 0.1234 USD

📆 2026-04-05
💵 小计: 0.0567 USD
  🖥️ 计算实例: 0.0300
  💾 块存储: 0.0200
  🌐 网络带宽: 0.0067
```

---

## 📚 更新记录（Changelog）

- 2026-04-05 · v1.1.0
  - 移动端友好 UI：卡片式布局（费用/用户/策略）
  - 服务类型中文化与图标映射
  - 安全增强：授权白名单、环境变量 Token、HTML 转义、配置校验
  - 健壮性：空数据提示、常量化、超时优化

- 2026-04-03 · v1.0.x
  - 增强用户/域信息展示
  - 策略看板与优先级表
  - 本月费用导出（CSV）
  - 预留 Telegram 机器人钩子

> 注：自 2026-04-04 起统一仅保留单一入口脚本 `OCI_Master.py`。
