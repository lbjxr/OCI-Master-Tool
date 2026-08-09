# 📝 Changelog

## [1.8.0] - 2026-08-10

### ✨ 新增
- 🔌 插件注册表机制（`oci_master/registry.py`）
  - 支持 `register_cli` / `register_telegram_message` / `register_telegram_callback` / `register_menu`
  - 新增功能只需注册 handler，无需修改 `app.py` 或 `telegram_bot.py`
- 🧪 测试基线修复与扩展
  - 修复全部 59 个测试（原 18 个失败），覆盖注册表、集成测试、菜单键盘、错误处理
- 🛡️ 密码策略 Telegram 交互菜单
  - 查看、创建、删除密码策略，支持自定义名称与过期天数
- 🏠 菜单返回按钮统一
  - 所有实例/网络/安全相关命令和错误场景均包含返回主菜单按钮
- 🔄 `_send_generic_error` 增强
  - 支持可选重试按钮（`retry_callback_data`）

### 🔧 优化
- 🏗️ 架构解耦
  - `app.py` 重构：CLI action 与菜单完全解耦到注册表系统
  - `telegram_bot.py` 重构：callback 路由完全解耦到注册表系统
- 📐 渲染格式统一
  - 所有 Telegram 渲染函数元数据统一使用 `<blockquote>` 包裹
  - `build_help_text` 重写为分区结构，更简洁直观
- ⚡ 性能优化
  - 实例列表默认跳过 VNIC/IP 查询（`include_network=False`）
  - 单实例查询直接调用 `get_instance()`，消除全租户扫描和 N+1 VNIC 请求
- 🧹 异常捕获收窄
  - 仅捕获 `oci.exceptions.ServiceError`、网络异常、超时异常
  - 编程错误（`AttributeError`/`TypeError`）向上抛出暴露 traceback
- 📦 依赖锁定
  - 建立 `/opt/oci-tool/.venv`，固定 `oci==2.152.1`、`requests==2.33.1`

### 🛡️ 安全加固
- 🔒 Telegram 鉴权改为 fail-closed
  - 空白名单不再表示“不限制”，空配置直接拒绝启动
  - 群聊同时匹配 `chat_id` 和 `user_id`
- 👤 systemd 专用用户与沙箱
  - 新增 `oci-master` 系统用户
  - 配置/私钥迁移到 `/etc/oci-master/`
  - 启用 `NoNewPrivileges`、`PrivateTmp`、`ProtectSystem=strict`、`ProtectHome`
- 🔐 凭证脱敏
  - 日志中 Token、OCID、私钥路径统一脱敏为 `[REDACTED]`
- 🧹 环境隔离
  - `scripts/setup_systemd.sh` 默认生成完整沙箱配置和 `.venv` 解释器

### 🐛 修复
- ✅ 修复 NSG / Security List API 语义错误
- ✅ 修复 `--dry-run` 演练模式（不再实际创建目录/备份/写 service 文件）
- ✅ 修复本月账单月初空数据边界提示
- ✅ 修复 `menu:netsec_help` 占位文案
- ✅ 修复 `/instance_network`、`/instance_rules`、`/instance_temp_rules` 无参数时缺少返回按钮

### 📝 文档
- 📖 新增 `PROJECT_AUDIT_2026-08-09.md`（架构审计与安全优化报告）
- 📖 新增 `MENU_AUDIT_2026-08-09.md`（菜单 UX 审计报告）
- 📖 更新 README.md：架构图、功能列表、配置说明、部署说明

---

## [1.7.0] - 2026-04-07

### ✨ 新增
- 📋 添加项目审视报告（PROJECT_AUDIT_2026-04-07.md）

### 🔧 优化
- 🧹 删除冗余命令（`/help`、`/policies`、`/create_safe_policy`、`/delete_policy`）
- 🎯 简化 `/start` 命令，精简欢迎信息并引导用户使用 `/menu`
- 🔥 `/sl_menu` 更名为"网络防火墙配置"，更直观易懂
- 📊 优化 Telegram Bot 命令菜单结构，从 12 个命令精简到 8 个

### 🐛 修复
- ✅ 修复 `/start` 命令语法错误（缺少 `if` 条件判断）

### 🗑️ 清理
- 🧹 删除 20 个旧备份文件，保留最新 5 个
- 📉 代码减少 52 行（从 3478 行优化到 3434 行，-1.3%）

### 📝 文档
- 📖 更新 README.md，补充 v1.7.0 版本说明
- 🎨 调整功能列表顺序，突出核心功能

---

## [1.6.0] - 2026-04-07

### ✨ 新增
- 🔐 密码策略菜单式管理：查看/创建/删除策略，自定义策略名称与过期天数
- 📋 审计事件只读查询（Identity Domain Audit Events）
- 🪣 Object Storage / Bucket 基础信息查询
- 🌐 实例网络/安全概览（VNIC、Subnet、NSG、Security List）
- 🛡️ 入站规则查看与临时规则管理
- ⚡ 实例动作后状态复查（启停重启后自动刷新状态）
- 📊 实例列表分页支持

### 🔧 优化
- 🏗️ 重构 CLI 入口为统一 action dispatch
- 📐 优化 Telegram 渲染格式（HTML 标签、emoji 图标）

### 🐛 修复
- ✅ 修复实例状态图标映射
- ✅ 修复 OCID 解析与名称查找歧义

---

## [1.5.0] - 2026-03-28

### ✨ 新增
- 🤖 Telegram Bot 远程运维入口
- 💰 本月费用账单查询
- 🖥️ 实例信息总览与详情
- 🌏 Region subscriptions 查询
- 👤 当前用户账号信息查询

### 🔧 优化
- 📦 统一配置管理（`oci_master/config.py`）
- 🧹 统一工具函数（`oci_master/utils.py`）

---

## [1.0.0] - 2026-03-20

### ✨ 新增
- 🚀 OCI Master 初始版本
- 🖥️ CLI 运维控制台
- 🔧 基础 OCI 查询能力（用户、实例、账单）
