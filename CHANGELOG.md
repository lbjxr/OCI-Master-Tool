# Changelog

All notable changes to this project will be documented in this file.

## [v1.4.0] - 2026-04-06

### ✨ 新增功能
- **Security List 菜单式管理** (`/sl_menu`)
  - 实例优先（instance-first）交互流程
  - 支持查看、新增、删除、替换入站/出站规则
  - 智能向导：协议选择 → CIDR 输入 → 端口配置 → 描述 → 确认提交
  - CIDR 快捷按钮：`0.0.0.0/0`、`::/0`、`10.0.0.0/8`、`192.168.0.0/16`、自定义
  - 端口快捷按钮：`22`、`80`、`443`、`25000-25100`、自定义
  - 协议中文化：TCP (传输控制)、UDP (用户数据报)、ICMP (网络控制)、ALL (所有协议)

### 🔒 安全增强
- CIDR 输入严格校验（IPv4/IPv6）
- 端口范围校验（1-65535，起始 ≤ 结束）
- Token 映射持久化修复（callback_data 长度优化）
- 从 Git 追踪中移除敏感文件（`.env`、会话文件）

### 🎨 用户体验优化
- Security List 按钮中文化（`Default Security List for` → `默认安全列表`）
- 图标区分度优化：
  - ⬇️ 入站 / ⬆️ 出站（方向明确）
  - 🚫 删除入站 / ❌ 删除出站
  - 🔁 替换入站 / ♻️ 替换出站
- 返回链路完善（支持多步向导返回上一步）
- 无需端口协议自动跳过端口步骤（ALL/ICMP/ICMPv6）

### 🧹 代码清理
- 删除未使用的 NSG 命令和函数（约 580 行）
- 删除所有 `/sl_*` 直接命令处理逻辑（保留 `/sl_menu` 菜单式入口）
- 移除 `export_security_list_rules`、`show_nsg_rules` 等已弃用函数
- 清理 CLI 参数解析器中的冗余 subparser

### 🐛 Bug 修复
- 修复 token 映射丢失导致按钮点击无响应问题
- 修复 callback_data 超长（>64字节）导致 `BUTTON_DATA_INVALID` 错误
- 修复状态机在自定义输入时状态不一致问题
- 修复 delete/replace 操作的规则序号错位问题

---

## [v1.3.0] - 2026-04-06

### ✨ 新增功能
- 实例网络安全查询：支持从计算实例视角查看 VNIC、私网/公网 IP、Subnet、NSG、Security Lists
- Security List 管理：支持导出备份、预览添加 Ingress、预览删除 Ingress，并显式 `--apply` 提交
- 安全改动策略：默认只预览不落库；变更前自动生成 JSON 备份

---

## [v1.2.0] - 2026-04-05

### ✨ 新增功能
- Identity Domains 审计事件查询：支持 CLI 和 Telegram Bot
- SCIM 2.0 过滤：支持过滤语法
- 移动端 UI：费用/用户/策略/审计输出改为卡片式布局
- 服务识别：自动添加中文名称与表情图标

### 🔐 安全增强
- 授权白名单严格校验
- Bot Token 环境变量优先
- HTML 转义、配置必填校验

### 🐛 Bug 修复
- Telegram Bot HTML 转义错误
- Python unbuffered 输出
- REST API 字段映射

---

## [v1.1.0] - 初始版本

### ✨ 功能
- 密码策略治理
- 费用导出
- Telegram 机器人基础功能
