# ☁️ OCI Master - 甲骨文云一键运维助手

OCI Master 是一个基于 Python 与 Oracle Cloud Infrastructure (OCI) SDK 的轻量级工具，帮助甲骨文云用户完成日常运维：账单查询导出、密码策略治理、网络防火墙配置以及 Telegram 机器人查询等。

## 📦 最新版本 v1.7.0（2026-04-07）
- 🧹 命令优化：删除冗余命令（`/help`、`/policies`、`/create_safe_policy`、`/delete_policy`），简化菜单结构
- 🔥 网络防火墙配置：`/sl_menu` 改名并换用 🔥 图标，更贴合防火墙概念
- 🐛 BUG 修复：修复 `/start` 命令语法错误，欢迎信息改为引导式提示
- 📋 文档增强：新增项目审视报告（`PROJECT_AUDIT_2026-04-07.md`）与 `CHANGELOG.md`
- 🗑️ 备份清理：保留最近 5 份 Security List 备份，删除 20 份旧备份
- 📉 代码减脂：总行数从 3478 减至 3434（-52，-1.3%）

> 历史版本记录请查阅 [CHANGELOG.md](CHANGELOG.md)。

## ✨ 主要功能（Features）
- 🔐 密码策略菜单管理：查看/创建/删除策略，自定义策略名称与过期天数（`/policy_menu`）
- 🔥 网络防火墙配置：实例优先流程、智能向导、查看/新增/删除/替换 Security List 规则（`/sl_menu`）
- 💰 费用导出：按日历月统计各服务扣费明细，UTF-8-SIG CSV（兼容 Excel）
- 🖥️ 实例信息总览：查询所有实例的 CPU、内存、存储、状态等详细信息（`/instance_info`）
- 🔍 审计事件查询：查询登录/登出/密码修改/权限变更等操作记录
- 🤖 本地运行：基于 OCI 官方 SDK 直连，无需第三方托管密钥
- 🧭 多平台支持：Windows / Linux / macOS
- 💬 Telegram 机器人：随时查询费用、用户信息、密码策略、审计事件、实例信息（移动端友好展示）
---

## 🚀 快速开始(Quick Start)

### 1) 获取 OCI API 凭证
- 控制台路径:身份和安全 (Identity & Security) → 域 (Domain) → 用户 (User) → API 密钥
- 添加 API 密钥并下载 .pem 私钥;复制生成的配置信息(user、tenancy、fingerprint、region 等)
- 权限要求:建议将 API 用户加入 Identity Domain Administrator 或 Security Administrator 组

### 2) 配置凭证文件
- 私钥建议路径:
  - Windows: `C:\Users\<Username>\.oci\oci_api_key.pem`
  - Linux/macOS: `~/.oci/oci_api_key.pem`
- 创建 `config` 文件(与私钥同目录),示例:

```ini
[DEFAULT]
user=ocid1.user.oc1..xxxxxx
fingerprint=xx:xx:xx:xx:xx:xx:xx:xx:xx:xx:xx:xx:xx:xx:xx:xx
tenancy=ocid1.tenancy.oc1..xxxxxx
region=ap-tokyo-1
key_file=/absolute/path/to/.oci/oci_api_key.pem
```

- Linux/macOS 需收紧私钥权限:
```bash
chmod 600 ~/.oci/oci_api_key.pem
```

### 3) 安装依赖
```bash
pip install -r requirements.txt  # 若无此文件,可执行: pip install oci requests
```

---

## 🧪 使用方式(Usage)

### A. CLI 模式(交互式菜单)
- 启动:
```bash
python3 OCI_Master.py
```
- 直接命令(非交互):
```bash
python3 OCI_Master.py region-subscriptions
python3 OCI_Master.py run region_subscriptions
```
- 菜单示例:
```plaintext
  1. 👤 查看当前用户信息
  2. 💰 导出本月费用账单 (CSV)
  3. 🛡️ 查询当前密码策略看板
  4. 📊 查询 Identity Domains 审计事件
  5. 🔒 创建/修复永不过期安全策略
  6. 🗑️ 删除冗余密码策略
  7. 🚪 退出程序
```

### B. Telegram Bot 模式(移动端友好)

#### 基础配置
- 在 `oci_master_config.json` 中启用 Telegram(token 推荐走环境变量,见下节):
```json
{
  "telegram": {
    "enabled": true,
    "bot_token": "留空或删除,推荐用环境变量",
    "allowed_chat_ids": ["123456789", "-1001234567890"],
    "allowed_user_ids": ["987654321"]
  }
}
```
- 启动:
```bash
python3 OCI_Master.py telegram
```

#### 安全配置(强烈推荐)
- 环境变量优先级(从高到低):
  1. `OCI_MASTER_BOT_TOKEN`(最高优先,推荐)
  2. 配置文件 `telegram.bot_token`
- 白名单授权逻辑:
  - 配置了 `allowed_chat_ids` 则消息必须来自白名单聊天
  - 配置了 `allowed_user_ids` 则消息必须来自白名单用户
  - 两者可同时配置(严格模式);未授权请求会被拒绝并记录警告日志
- 获取 ID:可使用 @userinfobot(user_id)与 @getidsbot(chat_id)

#### systemd 服务部署(推荐)
- 下面示例中的 `/opt/oci-master-tool` 只是**示例安装路径**。请先把仓库 clone 到你自己的部署目录，再把 `WorkingDirectory` 和 `ExecStart` 改成对应实际路径。
- 通用准备步骤(脚本化/手动两种方式都适用):
```bash
# 1) 选择部署目录(示例)
sudo mkdir -p /opt/oci-master-tool
sudo chown "$USER":"$USER" /opt/oci-master-tool
git clone https://github.com/lbjxr/OCI-Master-Tool.git /opt/oci-master-tool
cd /opt/oci-master-tool
python3 -m pip install -r requirements.txt

# 2) 环境文件(更安全)
echo 'OCI_MASTER_BOT_TOKEN=你的_token' | sudo tee /etc/oci-master.env
sudo chmod 600 /etc/oci-master.env
```

##### 脚本化初始化(推荐)
- 项目已提供 `scripts/setup_systemd.sh`，会按与手动方式一致的内容生成 service 文件。
- 脚本特性:
  - 生成前会检查 `OCI_Master.py` 是否存在
  - 如果目标 service 已存在，会先自动备份
  - Telegram token 不写入 service 文件，只通过 `EnvironmentFile` 注入
- 推荐用法:
```bash
chmod +x scripts/setup_systemd.sh
sudo ./scripts/setup_systemd.sh \
  --install-dir /opt/oci-master-tool \
  --config-path /root/oci_master_config.json \
  --service-name oci-master-telegram \
  --user root \
  --env-file /etc/oci-master.env \
  --enable-now

sudo systemctl --no-pager -l status oci-master-telegram.service
```
- 如只想先预览/生成而不触发 `systemctl`，可追加 `--dry-run`。

##### 手动初始化
- 最简服务示例(推荐使用 EnvironmentFile):
```bash
sudo tee /etc/systemd/system/oci-master-telegram.service >/dev/null <<'EOF'
[Unit]
Description=OCI Master Telegram runner
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/opt/oci-master-tool
Environment=OCI_MASTER_APP_CONFIG=/root/oci_master_config.json
EnvironmentFile=/etc/oci-master.env
ExecStart=/usr/bin/python3 /opt/oci-master-tool/OCI_Master.py telegram
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

sudo systemctl daemon-reload
sudo systemctl enable --now oci-master-telegram.service
sudo systemctl --no-pager -l status oci-master-telegram.service
```
- 如果你的仓库不在 `/opt/oci-master-tool`，请同步修改这两项:
  - `WorkingDirectory=/你的实际项目目录`
  - `ExecStart=/usr/bin/python3 /你的实际项目目录/OCI_Master.py telegram`

#### 命令列表
- 👤 `/user_info` - 用户账号信息(基础/联系方式/权限/安全状态)
- 🌏 `/regions` - 查询当前租户订阅区域(含 Home Region 标记)
- 💰 `/usage_fee` - 本月费用账单(按日汇总 + 服务明细)
- 🛡️ `/policies` - 密码策略看板(按优先级、当前生效高亮)
- 🧱 `/instance_network <instance_ocid>` - 实例网络安全总览(VNIC / NSG / Security Lists)
- 🛡️ `/nsg_rules <nsg_ocid>` - NSG 规则查询
- 📋 `/sl_rules <security_list_ocid>` - Security List 规则查询
- 🔒 `/create_safe_policy` - 创建永不过期策略
- 🗑️ `/delete_policy <名称>` - 删除指定策略
- 💬 `/help` - 分类帮助菜单

> 说明:机器人自动使用 HTML 渲染(parse_mode=HTML),无需额外配置。

示例(/usage_fee):
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

### C. 审计事件查询(Identity Domains Audit)

OCI Master 支持查询 Identity Domains 审计事件,追踪身份相关操作(登录/登出/密码修改/权限变更等)。

#### CLI 命令
```bash
python3 OCI_Master.py audit-events --limit 20
python3 OCI_Master.py audit-events --filter 'message co "login"' --limit 50
```

参数说明:
- `--limit N`:返回条数(默认 10)
- `--filter "SCIM"`:SCIM 2.0 过滤语法,例如 `message co "password"` / `actorName eq "user@example.com"`
- `--sort-by field`:排序字段(默认 timestamp)
- `--sort-order ORDER`:排序方式(ascending / descending)

#### Telegram 命令
```
/audit_events        # 查询最近 10 条
/audit_events 20     # 查询最近 20 条(最多 50)
```

示例输出:
```
📋 审计事件 (最近 10 条)
━━━━━━━━━━━━━━━━━━━━━━

🔑 User b.com signed in
   👤 用户: <code>b@com</code>
   🌐 IP: <code>123.45.67.89</code>
   🕒 时间: 04-01 08:36:16

🔒 Password policy updated
   👤 用户: <code>11用户名</code>
   🌐 IP: <code>98.76.54.32</code>
   🕒 时间: 04-01 08:30:22
```

#### 技术细节
- **API 调用**:Identity Domains REST API(`/admin/v1/AuditEvents`)
- **SDK 限制**:Python OCI SDK 未封装此 API,使用 `oci.signer.Signer` 直接签名 HTTP 请求
- **字段映射**:
  - 用户名:`actorDisplayName` / `actorName`
  - 源 IP:`clientIp`
  - 事件描述:`message`
  - 时间戳:`timestamp`

---

### D. 实例网络安全查询(VNIC / NSG / Security Lists)

OCI Master 支持从 **计算实例** 出发,查询实际生效的网络安全配置。

查询链路:
- 实例 → VNIC Attachments → VNIC
- VNIC → NSG
- VNIC 所在 Subnet → Security Lists

#### CLI 命令
```bash
python3 OCI_Master.py instance-network ocid1.instance.oc1..xxxxxx
python3 OCI_Master.py nsg-rules ocid1.networksecuritygroup.oc1..xxxxxx
python3 OCI_Master.py security-list-rules ocid1.securitylist.oc1..xxxxxx
```

#### Telegram 命令
```
/instance_network ocid1.instance.oc1..xxxxxx
/nsg_rules ocid1.networksecuritygroup.oc1..xxxxxx
/sl_rules ocid1.securitylist.oc1..xxxxxx
```

#### 输出内容
- 实例名称 / 状态 / 实例 OCID
- 每个 VNIC 的私网 / 公网 IP
- VNIC 所在子网
- VNIC 绑定的 NSG
- 子网绑定的 Security Lists
- NSG / Security List 规则摘要

#### 技术细节
- **ComputeClient**:`get_instance()`、`list_vnic_attachments()`
- **VirtualNetworkClient**:`get_vnic()`、`get_subnet()`、`get_network_security_group()`、`get_security_list()`、`list_network_security_group_security_rules()`

---

### E. Security List 管理(备份 / 预览 / 显式提交)

OCI Master 当前已支持 **Security List Ingress 规则管理**,并采用安全优先策略:
- 默认仅预览,不修改线上
- 每次变更前自动导出 JSON 备份
- 只有显式加 `--apply` 才会真正提交到 OCI

#### CLI 命令
```bash
python3 OCI_Master.py security-list-export ocid1.securitylist.oc1..xxxxxx
python3 OCI_Master.py security-list-add-ingress ocid1.securitylist.oc1..xxxxxx --source 0.0.0.0/0 --protocol 6 --port-min 22 --port-max 22
python3 OCI_Master.py security-list-remove-ingress ocid1.securitylist.oc1..xxxxxx --rule-index 1
```

#### 真正提交变更
```bash
python3 OCI_Master.py security-list-add-ingress ocid1.securitylist.oc1..xxxxxx --source 0.0.0.0/0 --protocol 6 --port-min 22 --port-max 22 --apply
python3 OCI_Master.py security-list-remove-ingress ocid1.securitylist.oc1..xxxxxx --rule-index 1 --apply
```

#### 行为说明
- `security-list-export`:导出当前完整 Security List JSON 备份
- `security-list-add-ingress`:新增一条 Ingress 规则(默认预览)
- `security-list-remove-ingress`:按序号删除一条 Ingress 规则(默认预览)
- 备份目录:`backups/`

---

## 📚 更新记录(Changelog)

- 2026-04-06 · v1.3.0
  - 新功能:实例网络安全查询(CLI + Telegram)
  - 支持从实例出发查看 VNIC / NSG / Security Lists / 规则摘要
  - 新功能:Security List 管理(导出备份 / 添加 Ingress / 删除 Ingress)
  - 管理策略:默认预览,显式 `--apply` 才会落库
  - 新增命令:`instance-network`、`nsg-rules`、`security-list-rules`
  - 新增命令:`security-list-export`、`security-list-add-ingress`、`security-list-remove-ingress`
  - 新增 Telegram 命令:`/instance_network`、`/nsg_rules`、`/sl_rules`

- 2026-04-05 · v1.2.0
  - 新功能:Identity Domains 审计事件查询(CLI + Telegram)
  - 支持 SCIM 2.0 过滤语法(`message co "login"`)
  - 移动端友好 UI:卡片式布局(费用/用户/策略/审计)
  - 服务类型中文化与图标映射
  - 安全增强:授权白名单、环境变量 Token、HTML 转义、配置校验
  - 健壮性:空数据提示、常量化、超时优化
  - Bug 修复:Telegram Bot HTML 转义、unbuffered 输出、REST API 字段映射

- 2026-04-05 · v1.1.0
  - 移动端友好 UI 优化
  - 服务类型中文化

- 2026-04-03 · v1.0.x
  - 增强用户/域信息展示
  - 策略看板与优先级表
  - 本月费用导出(CSV)
  - 预留 Telegram 机器人钩子

> 注:自 2026-04-04 起统一仅保留单一入口脚本 `OCI_Master.py`。

