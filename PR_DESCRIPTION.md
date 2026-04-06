# Security List 菜单式管理功能

## 📋 Pull Request 概述

本 PR 为 OCI Master 新增了 **Security List 菜单式管理功能** (`/sl_menu`)，提供基于实例优先（instance-first）的交互式向导流程，大幅提升 Security List 规则管理的用户体验。

## ✨ 核心功能

### 1. `/sl_menu` 菜单式管理
- **实例优先流程**：选择动作 → 选择实例 → 选择 Security List → 执行操作
- **支持操作**：
  - 📝 查看安全列表规则
  - ⬇️ 新增入站规则 / ⬆️ 新增出站规则
  - 🚫 删除入站规则 / ❌ 删除出站规则
  - 🔁 替换入站规则 / ♻️ 替换出站规则

### 2. 智能向导流程
- **协议选择**：TCP (传输控制)、UDP (用户数据报)、ICMP (网络控制)、ALL (所有协议)
- **CIDR 输入**：
  - 快捷按钮：`0.0.0.0/0`、`::/0`、`10.0.0.0/8`、`192.168.0.0/16`
  - 自定义输入：支持 IPv4/IPv6 CIDR 严格校验
- **端口配置**：
  - 快捷按钮：`22`、`80`、`443`、`25000-25100`
  - 自定义输入：支持单端口或范围（1-65535）
  - 智能跳过：ALL/ICMP 等无需端口协议自动跳过端口步骤
- **描述填写**：可选描述信息
- **确认提交**：预览所有参数后确认执行

### 3. 用户体验优化
- ⬅️ **返回上一步**：支持多步向导中返回修改
- 🔒 **输入校验**：CIDR 和端口非法输入时保持状态并提示错误
- 🇨🇳 **中文化**：Security List 按钮名称翻译（`Default Security List for` → `默认安全列表`）
- 🎨 **图标区分度**：入站/出站、新增/删除/替换使用不同图标

## 🔒 安全增强

### 输入校验
- **CIDR 校验**：使用 Python `ipaddress` 模块验证 IPv4/IPv6 CIDR 合法性
- **端口校验**：验证端口范围（1-65535）和逻辑正确性（起始 ≤ 结束）
- **非法输入处理**：错误时保持当前状态，不破坏已填写内容

### 数据安全
- 从 Git 追踪中移除 `.env` 和会话文件
- 更新 `.gitignore` 防止未来误提交
- 所有文档示例使用虚构占位符（`ocid1.*.oc1..xxxxxx`）

### 状态机修复
- 修复 token 映射持久化问题（状态保存时机错误导致按钮失效）
- 修复 callback_data 长度超限问题（>64字节导致 Telegram API 拒绝）
- 修复 delete/replace 操作的规则序号错位问题

## 🧹 代码清理

### 删除未使用代码（约 580 行）
- 删除所有 NSG 相关函数（`_fetch_nsg_rules`、`render_nsg_rules_telegram`、`show_nsg_rules` 等）
- 删除所有 `/sl_*` 直接命令处理逻辑（保留 `/sl_menu` 菜单入口）
- 删除已弃用函数（`export_security_list_rules`、`_print_nsg_rules` 等）
- 清理 CLI 参数解析器中的冗余 subparser

### 保留核心函数
以下函数被 `/sl_menu` 使用，已保留：
- `_fetch_security_list` - 获取 Security List 详情
- `render_security_list_rules_telegram` - Telegram 格式化展示
- `add_security_list_ingress_rule` / `add_security_list_egress_rule` - 新增规则
- `remove_security_list_ingress_rule` / `remove_security_list_egress_rule` - 删除规则
- `replace_security_list_ingress_rule` / `replace_security_list_egress_rule` - 替换规则
- `_update_security_list_rules` - 更新 Security List

## 📊 改动统计

```
 .env                         |  2 --
 .gitignore                   |  1 +
 .telegram_menu_sessions.json |  1 -
 CHANGELOG.md                 | 79 ++++++++++++++++++
 OCI_Master.py                | (净减少约 550 行)
 README.md                    | 11 +++---
```

## 🧪 测试覆盖

### 功能测试
- ✅ 新增 TCP 入站规则（快捷按钮路径）
- ✅ 新增 ICMP 出站规则（自定义 CIDR + 无端口协议）
- ✅ 自定义端口范围（8000-9000）
- ✅ 删除规则（确认规则序号正确）
- ✅ 替换规则（确认替换目标正确）
- ✅ 返回上一步（状态保持正确）

### 异常处理测试
- ✅ 非法 CIDR 输入（`abc`、`999.999.999.999/33`）
- ✅ 非法端口输入（`0`、`65536`、`100-99`）
- ✅ 所有异常情况下状态机不崩溃

### 安全测试
- ✅ callback_data 长度检查（所有按钮 < 64 字节）
- ✅ token 映射持久化验证
- ✅ 敏感文件 Git 追踪检查

## 📦 版本信息

- **版本号**：v1.4.0
- **发布日期**：2026-04-06
- **向后兼容性**：完全兼容，仅新增功能和删除未使用代码

## 🔗 相关文档

- [CHANGELOG.md](./CHANGELOG.md) - 完整变更日志
- [README.md](./README.md) - 更新的功能说明
- [SL_GUIDE_REQUIREMENTS_AND_ACCEPTANCE.md](./SL_GUIDE_REQUIREMENTS_AND_ACCEPTANCE.md) - 需求与验收文档

## 🎯 验收标准

- [x] 所有功能按需求文档实现
- [x] 编译通过（`python3 -m py_compile OCI_Master.py`）
- [x] Telegram Bot 正常启动
- [x] 端到端测试通过
- [x] 代码无敏感信息泄露
- [x] 文档更新完整

## 💡 后续优化建议

1. **协议页返回逻辑**：当前返回主菜单，建议返回到 SL 动作页
2. **delete 确认页**：建议补充"返回规则列表"按钮
3. **单 IP 地址处理**：`ipaddress` 会自动补 `/32`，如需严格拒绝可增加额外检查
4. **批量操作**：未来可考虑支持批量添加/删除规则

---

**Reviewer Checklist:**
- [ ] 代码审查：逻辑正确性
- [ ] 安全审查：无敏感信息泄露
- [ ] 功能测试：核心流程可用
- [ ] 文档完整：README/CHANGELOG 更新
