# ☁️ OCI Master - 甲骨文云一键运维助手
OCI Master 是一个基于 Python 和 Oracle Cloud Infrastructure (OCI) SDK 开发的轻量级交互式命令行工具。旨在帮助甲骨文云（Oracle Cloud）玩家一键解决日常账号维护痛点，包括账单导出与破解 120 天密码强制过期限制。

## ✨ 亮点内容 (Features)
- 🛡️ 突破密码限制：一键克隆官方安全标准，创建并启用“永不过期 (Priority 1)”的密码策略，彻底告别每 120 天强制改密码的烦恼。

- 💰 费用精准导出：按日历月精确统计各服务的扣费明细，一键导出为 UTF-8-SIG 编码的 CSV 文件（完美兼容 Excel 不乱码）。

- 🤖 交互式防呆设计：内置全中文终端菜单，支持越界指令拦截、清屏刷新。对于“创建”和“删除”等敏感操作，均配有二次确认提示与操作前后状态对比，杜绝误操作。

- 🔒 绝对安全隐私：完全基于 OCI 官方 Python SDK 本地运行，所有 API 请求直连 Oracle 服务器，无需将密钥托管给任何第三方面板，从根源保障账号安全。

- 🌐 跨平台兼容：完美支持 Windows、Linux 和 macOS，一套代码，随处运行。

## 部署方式
### 🔑 第一步：获取 OCI API 凭证
要让脚本与你的甲骨文账号通信，你需要生成 API 密钥。

登录 OCI 控制台：使用你的账号密码登录 Oracle Cloud 网页控制台。

进入用户设置：点击右上角的 个人头像 -> 选择 User Settings (用户设置) / 我的概要信息。

添加 API 密钥：

在左下角的资源菜单中点击 API Keys (API 密钥)。

点击 Add API Key (添加 API 密钥)。

选择 Generate API Key Pair (生成 API 密钥对)，点击 Download Private Key (下载私钥)，妥善保存这个 .pem 文件（例如 oci_api_key.pem）。

点击 Add (添加)。

复制配置信息：添加成功后，系统会弹出一个包含配置文本的文本框（Configuration File Preview），请将里面的全部内容复制下来，稍后会用到。

**⚠️ 重要权限提示：**  脚本中的“密码策略修改”功能需要较高的身份域权限。请确保当前 API 用户隶属于 Identity Domain Administrator 或 Security Administrator 用户组。

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
    
    Ini, TOML
    [DEFAULT]
    user=ocid1.user.oc1..xxxxxx
    fingerprint=xx:xx:xx:xx:xx:xx:xx:xx:xx:xx:xx:xx:xx:xx:xx:xx
    tenancy=ocid1.tenancy.oc1..xxxxxx
    region=ap-tokyo-1
    # 下面的路径请根据你的实际操作系统修改
    key_file=C:\Users\Username\.oci\oci_api_key.pem 
    
5. (关键) Linux / macOS 权限设置
   
为了安全，Linux 和 macOS 要求私钥文件必须是隐藏且仅拥有者可读的。请在终端执行：
  
    chmod 600 ~/.oci/oci_api_key.pem
    
### 🚀 第三步：部署与使用
确保你的电脑已安装 Python 3.6+。

1. 安装依赖
无论使用哪种操作系统，首先在终端/命令行中安装 OCI 官方 SDK：
    pip install oci
    
2. 运行环境要求
- 🪟 Windows
  
    将 OCI_Master.py 下载到本地目录。

    打开 PowerShell 或 CMD，进入脚本所在目录：

    python OCI_Master.py
    
    你也可以编写一个 run.bat 文件放在桌面，内容为 python C:\你的路径\OCI_Master.py，双击即可直接唤醒工具。

- 🐧 Linux (Ubuntu/Debian/CentOS) 和 🍎 macOS

将脚本上传至服务器。macOS打开终端 (Terminal)。

在终端中运行：
    
    python3 OCI_Master.py
    
## 📖 菜单功能说明
运行成功后，你将看到如下交互式菜单：

```Plaintext
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
