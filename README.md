# ☁️ OCI Master - 甲骨文云一键运维助手
OCI Master 是一个基于 Python 和 Oracle Cloud Infrastructure (OCI) SDK 开发的轻量级交互式命令行工具。旨在帮助甲骨文云（Oracle Cloud）玩家一键解决日常账号维护痛点，包括账单导出与破解 120 天密码强制过期限制。

## ✨ 亮点内容 (Features)
- 🛡️ 突破密码限制：一键克隆官方安全标准，创建并启用"永不过期 (Priority 1)"的密码策略，彻底告别每 120 天强制改密码的烦恼。

- 💰 费用精准导出：按日历月精确统计各服务的扣费明细，一键导出为 UTF-8-SIG 编码的 CSV 文件（完美兼容 Excel 不乱码）。

- 🤖 交互式防呆设计：内置全中文终端菜单，支持越界指令拦截、清屏刷新。对于"创建"和"删除"等敏感操作，均配有二次确认提示与操作前后状态对比，杜绝误操作。

- 🔒 绝对安全隐私：完全基于 OCI 官方 Python SDK 本地运行，所有 API 请求直连 Oracle 服务器，无需将密钥托管给任何第三方面板，从根源保障账号安全。

- 🌐 跨平台兼容：完美支持 Windows、Linux 和 macOS，一套代码，随处运行。

## 部署方式
### 🔑 第一步：获取 OCI API 凭证

登录并进入主页：首先，登录甲骨文云 (Oracle Cloud) 的官方网站，进入到控制台的首页

打开左侧菜单：点击页面左上角的“三条杠”（导航菜单按钮）

导航至用户详情：在左侧菜单中依次选择 “身份和安全” (Identity and Security) ➡️ “概览” (Overview) ➡️ 选择并进入 “域” (Domain) ➡️ 选择并进入你的 “用户” (User) 。

找到 API 密钥选项：在用户详情页面中，一直向下滚动，找到 “API 密钥” 选项。

添加并下载密钥：点击“添加 API 密钥”。在弹出的窗口中，系统会要求你首先下载 API 密钥文件。将该密钥文件下载并妥善保存后，点击“添加”按钮。

复制 API 配置信息：点击添加后，页面上会直接生成一串包含你账号 API 详情的数据文本（即配置结构信息），请将这串信息全部复制。

**⚠️ 重要权限提示：**  脚本中的"密码策略修改"功能需要较高的身份域权限。请确保当前 API 用户隶属于 Identity Domain Administrator 或 Security Administrator 用户组。

### ⚙️ 第二步：参数初始化与配置
根据你的操作系统，配置 OCI 凭证文件。

1. 存放私钥文件

将刚刚下载的 .pem 私钥文件放到一个安全的目录中。

Windows 推荐路径: 

```
C:\Users\你的用户名\.oci\oci_api_key.pem
```

Linux / macOS 推荐路径:

```
~/.oci/oci_api_key.pem
```

3. 创建 config 文件

在私钥同级目录下，创建一个名为 config 的无后缀文本文件，并将第一步复制的配置信息粘贴进去。修改 key_file 的路径，使其指向你的私钥文件。

标准 config 文件示例：

```ini
[DEFAULT]
user=ocid1.user.oc1..xxxxxx
fingerprint=xx:xx:xx:xx:xx:xx:xx:xx:xx:xx:xx:xx:xx:xx:xx:xx
tenancy=ocid1.tenancy.oc1..xxxxxx
region=ap-tokyo-1
# 下面的路径请根据你的实际操作系统修改
key_file=C:\Users\Username\.oci\oci_api_key.pem
```

5. (关键) Linux / macOS 权限设置

为了安全，Linux 和 macOS 要求私钥文件必须是隐藏且仅拥有者可读的。请在终端执行：

```bash
chmod 600 ~/.oci/oci_api_key.pem
```

### 🚀 第三步：部署与使用
确保你的电脑已安装 Python 3.6+。

1. 安装依赖

无论使用哪种操作系统，首先在终端/命令行中安装 OCI 官方 SDK：

```bash
pip install oci
```

2. 运行环境要求

- 🪟 Windows  
  将 OCI_Master.py 下载到本地目录。

打开 PowerShell 或 CMD，进入脚本所在目录：

```cmd
python OCI_Master.py
```

你也可以编写一个 run.bat 文件放在桌面，内容为 `python C:\你的路径\OCI_Master.py`，双击即可直接唤醒工具。

- 🐧 Linux (Ubuntu/Debian/CentOS) 和 🍎 macOS

将脚本上传至服务器。macOS打开终端 (Terminal)。

在终端中运行：

```bash
python3 OCI_Master.py
```

## 📖 菜单功能说明
运行成功后，你将看到如下交互式菜单：

```plaintext
               ☁️  OCI 甲骨文云一键运维工具 ☁️               
=======================================================
  1. 👤 查看当前用户信息
  2. 💰 导出本月费用账单 (CSV)
  3. 🛡️  查询当前密码策略看板
  4. 🔒 创建/修复永不过期安全策略
  5. 🗑️  删除冗余密码策略
  6. 🚪 退出程序
=======================================================
👉 请选择要执行的功能 (0-5): 
```

- 功能 1：连通性测试。验证 API 密钥是否配置正确，打印账号基础信息。

- 功能 2：在脚本同级目录下生成形如 oci_costs_2026_03.csv 的账单报表。

- 功能 3：直观展示身份域中所有密码策略的优先级与状态。

- 功能 4：核心功能。智能克隆官方 standardPasswordPolicy 的安全要求（如大小写、长度限制），并生成优先级最高的永不过期策略。

- 功能 5：带防呆确认的策略清理工具，用于删除测试产生的多余策略，系统级保护策略会自动拦截删除以防系统崩溃。

---
更新（2026-04-03）

- 替换增强版 OCI_Master.py
  - 更完善的用户/域信息展示（中英文标签、空值更友好）
  - 密码策略看板与优先级表
  - 本月费用导出（CSV）
  - 预留 Telegram 机器人钩子（后续可独立到 OCI_Master_TGBot.py）
- 新增 oci_master_config.example.json（已脱敏）
  - 复制为 oci_master_config.json 后按需填写：oci 配置文件路径/PROFILE、Identity Domain 名称、输出目录等
- 新增 requirements.txt（oci、requests）
  - 安装：pip install -r requirements.txt
- 更新 .gitignore
  - 忽略 oci_master_config.json、.env、__pycache__/，避免提交敏感信息或缓存文件


> 说明：自 2026-04-04 起统一仅保留一个入口 `OCI_Master.py`，所有示例以该文件为准。

## 部署与运行（单一入口 OCI_Master.py）

仅保留一个入口脚本 OCI_Master.py。以下为推荐运行方式：

### 🔐 安全配置（推荐）

#### 环境变量优先级

为保护敏感信息，脚本支持通过**环境变量**配置 Telegram Bot Token，优先级高于配置文件：

```bash
# 方式 1：临时设置（当前会话有效）
export OCI_MASTER_BOT_TOKEN="your_bot_token_here"
python3 OCI_Master.py telegram

# 方式 2：systemd 服务环境变量（推荐，见下文）
```

**优先级规则**：
1. 环境变量 `OCI_MASTER_BOT_TOKEN`（最高）
2. 配置文件 `oci_master_config.json` 中的 `telegram.bot_token`

#### Telegram 白名单授权说明

脚本支持双重白名单校验，保护 Bot 免受未授权访问：

- **`allowed_chat_ids`**：允许的聊天/群组 ID 列表
- **`allowed_user_ids`**：允许的用户 ID 列表

**授权逻辑**：
- 如果配置了 `allowed_chat_ids`，消息必须来自白名单内的聊天
- 如果配置了 `allowed_user_ids`，消息必须来自白名单内的用户
- 两者可同时配置（严格模式）或都不配置（开放模式，不推荐）
- 未授权请求会被拒绝并记录日志（`LOGGER.warning`）

**获取 Chat ID 和 User ID**：
```bash
# 发送 /start 给 @userinfobot，会返回你的 user_id
# 或使用 @getidsbot 查询 chat_id
```

示例配置（`oci_master_config.json`）：
```json
{
  "telegram": {
    "enabled": true,
    "bot_token": "留空，改用环境变量",
    "allowed_chat_ids": ["123456789", "-1001234567890"],
    "allowed_user_ids": ["987654321"]
  }
}
```

### 方式 A：systemd 服务（推荐）

```bash
cat >/etc/systemd/system/oci-master-telegram.service <<'EOF'
[Unit]
Description=OCI Master Telegram runner
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/root/.openclaw/workspace/tmp/OCI-Master-Tool
Environment=OCI_MASTER_APP_CONFIG=/root/oci_master_config.json
Environment=OCI_MASTER_BOT_TOKEN=你的_bot_token_这里
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
```

**安全提示**：
- 将 `你的_bot_token_这里` 替换为实际 Token
- 或使用 systemd 环境文件（更安全）：
  ```bash
  # 创建环境文件
  echo 'OCI_MASTER_BOT_TOKEN=你的_token' > /etc/oci-master.env
  chmod 600 /etc/oci-master.env
  
  # 修改 service 文件，替换 Environment= 行为：
  # EnvironmentFile=/etc/oci-master.env
  ```

```bash
systemctl daemon-reload
systemctl enable --now oci-master-telegram.service
systemctl --no-pager -l status oci-master-telegram.service
```
