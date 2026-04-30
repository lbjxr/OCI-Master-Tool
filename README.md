# OCI Master

<p align="center">
  <b>OCI Master</b><br>
  <sub>A polished operations console for Oracle Cloud Infrastructure</sub><br>
  <sub>CLI + Telegram Bot · 安全优先 · 高频运维场景一站收束</sub>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.14+-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python 3.14+" />
  <img src="https://img.shields.io/badge/OCI-Operations-C74634?style=for-the-badge&logo=oracle&logoColor=white" alt="OCI Operations" />
  <img src="https://img.shields.io/badge/Telegram-Bot-26A5E4?style=for-the-badge&logo=telegram&logoColor=white" alt="Telegram Bot" />
  <img src="https://img.shields.io/badge/Mode-CLI%20%2B%20Remote-111827?style=for-the-badge" alt="CLI + Remote" />
</p>

> 面向 **Oracle Cloud Infrastructure (OCI)** 的一站式运维控制台。  
> 支持 **CLI + Telegram Bot** 双入口，覆盖账户信息、费用、实例、网络安全、Object Storage、Audit Events 等核心场景。

<p align="center">
  <i>为日常 OCI 运维打造：更轻、更快、更适合远程控制。</i>
</p>

---

## 📚 目录导航

- [🖼️ 一眼看懂](#️-一眼看懂)
- [✨ 项目亮点](#-项目亮点)
- [💎 Why OCI Master](#-why-oci-master)
- [🚀 当前支持能力](#-当前支持能力)
- [🧭 适用场景](#-适用场景)
- [🏗️ 运行约定](#️-运行约定)
- [📁 目录结构](#-目录结构)
- [🧱 典型工作流](#-典型工作流)
- [⚡ 快速开始](#-快速开始)
- [🧩 兼容入口用法](#-兼容入口用法)
- [🤖 Telegram 支持命令](#-telegram-支持命令)
- [⚙️ 配置说明](#️-配置说明)
- [✅ 已验证功能](#-已验证功能)
- [🖥️ 实例管理与网络安全补充](#️-实例管理与网络安全补充)
- [⚠️ 已知注意事项](#️-已知注意事项)
- [🎯 项目定位](#-项目定位)

---

## 🖼️ 一眼看懂

```text
                         ┌───────────────────────┐
                         │      OCI Master       │
                         │  统一运维控制入口层   │
                         └───────────┬───────────┘
                                     │
                 ┌───────────────────┼───────────────────┐
                 │                   │                   │
                 ▼                   ▼                   ▼
        ┌────────────────┐  ┌────────────────┐  ┌────────────────┐
        │   CLI 入口     │  │ Telegram Bot   │  │ Action Runner  │
        │ 本地交互/命令式 │  │ 远程交互/按钮流 │  │ 自动化执行入口 │
        └────────┬───────┘  └────────┬───────┘  └────────┬───────┘
                 │                   │                   │
                 └───────────────────┴───────────────────┘
                                     │
                                     ▼
      ┌────────────────────────────────────────────────────────────┐
      │                      核心服务能力层                        │
      ├────────────────────────────────────────────────────────────┤
      │ 用户 / 账单 / Region / Password Policy / 实例 / 网络安全  │
      │ Bucket / Object Storage / Audit Events / 状态复查 / 分页  │
      └────────────────────────────────────────────────────────────┘
                                     │
                                     ▼
                     ┌─────────────────────────────┐
                     │ Oracle Cloud Infrastructure │
                     └─────────────────────────────┘
```

## ✨ 项目亮点

OCI Master 不是一堆零散脚本的拼装，而是一个更适合日常运维的轻量控制台：

- **双入口体验**：既能本地 CLI 交互，也能直接通过 Telegram Bot 远程操作
- **实例运维闭环**：列表、详情、启停重启、动作后状态复查，一条链跑通
- **网络安全可控**：支持低风险临时放行单个 TCP 端口，带预览 / 确认 / 回执
- **对象存储可视化查看**：Bucket 基础信息、对象数量、容量估算、版本控制等一屏直达
- **审计可追溯**：支持 Identity Domain Audit Events 只读查询
- **多账号配置友好**：支持 profile 化配置，便于多租户 / 多环境管理
- **部署务实**：不依赖系统 Python 环境“完美无缺”，项目自带本地依赖目录方案

---

## 💎 Why OCI Master

很多 OCI 工具的问题，不是“不能用”，而是：

- 太依赖图形控制台，路径深、点得多
- 远程处理高频动作不顺手
- 网络改动缺少轻量但可靠的确认流程
- 信息查询、实例动作、审计查看分散在不同入口

OCI Master 想解决的不是“所有事情”，而是**最常见、最高频、最容易打断工作流的那些事**。

它的价值不在于替代官方控制台，而在于：

- 把高频运维动作收束成统一入口
- 让 Telegram 也能承担一部分真正可用的远程运维能力
- 在“方便”和“安全边界”之间做更克制的平衡
- 让脚本工具更像一个完整产品，而不是一堆临时命令

---

## 🖼️ 界面预览

<img width="263" height="260" alt="PixPin_2026-04-30_16-01-29" src="https://github.com/user-attachments/assets/1d6d7cca-d4b5-4101-aad7-5ad4340ed7b7" />

<img width="256" height="385" alt="PixPin_2026-04-30_16-02-11" src="https://github.com/user-attachments/assets/1296f739-3179-4c0b-8547-8563d9e68b65" />

<img width="320" height="497" alt="PixPin_2026-04-30_16-02-53" src="https://github.com/user-attachments/assets/da847f0b-2a68-4a75-b283-27f263acd87f" />

<img width="274" height="353" alt="PixPin_2026-04-30_16-03-37" src="https://github.com/user-attachments/assets/bead9f40-7ba0-491f-9f19-c5ae97ccec9a" />



---

## 🚀 当前支持能力

### 账户与租户信息

- 当前用户信息查询
- 本月费用账单查询
- Region subscriptions 查询
- Identity Domain 密码策略管理

### 实例运维

- 实例列表
- 实例详情
- 实例启动 / 停止 / 重启
- 实例动作后状态复查回执
- 实例列表分页
- 默认 compartment 过滤

### 网络与安全

- 实例网络 / 安全概览
  - VNIC
  - Subnet
  - NSG
  - Security List
- 低风险快捷网络操作
  - 常见 TCP 端口新增入站规则
  - 删除临时规则
  - 全链路预览 / 确认式执行

### 存储与审计

- Object Storage / Bucket 基础信息查询
- Audit Events 查询（只读）

### 接入方式

- CLI 菜单入口
- 命令式 action 入口
- Telegram Bot 命令入口

---

## 🧭 适用场景

OCI Master 适合这些场景：

- 想快速查看 OCI 实例、账单、Bucket、审计事件
- 想通过 Telegram 在手机上完成基础运维操作
- 想给实例做 **低风险、可回滚、可确认** 的临时网络放行
- 想用更统一的方式管理多 profile / 多 compartment 的 OCI 环境

---

## 🏗️ 运行约定

这个项目当前**不依赖系统 Python 环境完整性**。

由于宿主机 `/usr/bin/python3` 缺少完整 `venv/pip` 能力，项目采用以下运行方式：

- 运行解释器：`/usr/local/python3/bin/python3.14`
- 项目本地依赖目录：`./.deps`
- 兼容入口：`OCI_Master.py` 会自动把 `./.deps` 注入 `sys.path`

也就是说，正常情况下直接运行本文档里的命令即可，**不需要手工拼 `PYTHONPATH`**。

---

## 📁 目录结构

```text
OCI-Master-Tool/
├── OCI_Master.py                  # 兼容入口
├── oci_master/                    # 主代码包
│   └── services/                  # 业务模块
├── oci_master_config.json         # 实际配置
├── oci_master_config.example.json # 配置示例
├── .deps/                         # 项目本地 Python 依赖目录
└── run_oci_master.sh              # 推荐启动脚本
```

---

## 🧱 典型工作流

### Telegram 运维流

```text
实例详情
  → 网络/安全概览
    → 选择开放临时端口 / 清理临时规则
      → 选择快捷端口或输入自定义端口
        → 选择默认 CIDR 或输入自定义 CIDR
          → 预览
            → 确认
              → 执行回执
```

### 实例动作流

```text
实例列表
  → 选择实例
    → 启动 / 停止 / 重启
      → 提交动作
        → 自动补一次短暂状态复查
          → 返回最终回执
```

---

## ⚡ 快速开始

### 1）CLI 菜单模式

```bash
./run_oci_master.sh
```

### 2）Telegram Bot 轮询模式

```bash
./run_oci_master.sh telegram
```

### 3）直接执行 action

```bash
./run_oci_master.sh run user_info
./run_oci_master.sh run usage_fee
./run_oci_master.sh run region_subscriptions
./run_oci_master.sh run bucket_info
./run_oci_master.sh run audit_events:10
./run_oci_master.sh run policies
./run_oci_master.sh run list_instances
./run_oci_master.sh run instance_detail:oracle-arm
./run_oci_master.sh run instance_network:oracle-arm
./run_oci_master.sh run open_ingress_preview:oracle-arm:22:1.2.3.4/32
./run_oci_master.sh run cleanup_temp_rules_preview:oracle-arm:22:1.2.3.4/32
```

---

## 🧩 兼容入口用法

如果你希望直接调用 Python 入口，也可以这样运行：

```bash
/usr/local/python3/bin/python3.14 OCI_Master.py
/usr/local/python3/bin/python3.14 OCI_Master.py telegram
/usr/local/python3/bin/python3.14 OCI_Master.py run list_instances
```

`OCI_Master.py` 会自动注入 `.deps`，因此无需额外设置 `PYTHONPATH`。

---

## 🤖 Telegram 支持命令

```text
/user_info
/usage_fee
/regions
/bucket_info
/audit_events 10
/policies
/create_safe_policy
/delete_policy 名称
/instances
/instance_detail <名称|OCID>
/instance_start <名称|OCID>
/instance_stop <名称|OCID>
/instance_restart <名称|OCID>
/instance_network <名称|OCID>
/netsec_open <名称|OCID> <端口> <CIDR>
/netsec_close_temp <名称|OCID> <端口> <CIDR>
/run <action>
```

---

## ⚙️ 配置说明

当前配置同时支持两种写法。

### 旧写法（兼容保留）

```json
{
  "oci": {
    "config_file": "/root/.oci/config",
    "profile_name": "DEFAULT",
    "identity_domain_name": "Default"
  }
}
```

### 新写法（推荐，适合多账号 / 多环境）

```json
{
  "active_profile": "DEFAULT",
  "profiles": {
    "DEFAULT": {
      "config_file": "/root/.oci/config",
      "profile_name": "DEFAULT",
      "identity_domain_name": "Default",
      "instance_defaults": {
        "default_compartment_ids": ["ocid1.compartment.oc1..example"],
        "default_compartment_names": ["Prod"]
      }
    }
  },
  "instances": {
    "telegram_page_size": 8,
    "default_compartment_ids": [],
    "default_compartment_names": []
  },
  "network_security": {
    "quick_open_allowed_tcp_ports": [22, 80, 443, 3389],
    "default_source_cidr": "0.0.0.0/0"
  }
}
```

### 配置项说明

- `instances.default_compartment_ids` / `instances.default_compartment_names`：全局默认过滤
- `profiles.<name>.instance_defaults.*`：会覆盖全局默认过滤，适合多账号分环境隔离
- 若两者都不配置：保持旧行为，遍历全部可访问 compartment
- `telegram_page_size`：控制 Telegram 实例列表每页数量
- `network_security.quick_open_allowed_tcp_ports`：仅控制 Telegram 快捷端口按钮展示项，默认 `22 / 80 / 443 / 3389`
- 当前命令式入口与 Telegram 输入态都支持**自定义单个 TCP 端口**
- 端口范围限制为 `1-65535`，**不支持端口段、多端口、UDP**
- `network_security.default_source_cidr`：仅作为 CLI 交互默认值；Telegram / action 模式仍建议显式传 CIDR

---

## ✅ 已验证功能

本地已验证通过：

- 用户信息查询
- 费用账单查询
- Region subscriptions 渲染
- Bucket / Object Storage 渲染
- Audit events 渲染
- 密码策略看板
- 实例列表
- 实例详情
- 实例列表分页渲染
- 实例动作后的状态复查回执

### 当前运维边界

- 实例动作链路已接好，但真实启停 / 重启仍应按现场需要谨慎操作
- 网络快捷操作当前只覆盖**低风险范围**：
  - 仅主 VNIC 关联对象
  - 仅 ingress
  - 仅单个 TCP 端口
  - 执行前先预览

---

## 🖥️ 实例管理与网络安全补充

### 实例管理

- Telegram `/instances` 支持分页浏览，不再只截固定前几个实例
- 新增 `/regions`、`/bucket_info`、`/audit_events [N]`
- 对应 action：
  - `run region_subscriptions`
  - `run bucket_info`
  - `run audit_events[:N]`

### Object Storage

当前只做只读查看，支持展示：

- namespace
- bucket 列表
- compartment
- 创建时间
- public access
- storage tier
- versioning
- auto tiering
- approximate object count / size

### Audit Events

当前只做只读查看：

- 走 Identity Domain `/admin/v1/AuditEvents`
- 按旧版展示 `message / actor / clientIp / timestamp`

### Telegram 按钮流优化

- 实例列表按钮与动作按钮全部改用**短 token 映射**
- 避免把超长 OCID 直接塞进 `callback_data`
- `/instance_start`、`/instance_stop`、`/instance_restart` 以及 Telegram 按钮动作，提交后会补一次短暂状态复查

### 网络 / 安全按钮流

当前已支持：

1. 实例详情
2. 网络 / 安全概览
3. 选择“开放临时端口 / 清理临时规则”
4. 快捷端口按钮或输入自定义端口
5. 默认或自定义 CIDR
6. 预览
7. 确认
8. 执行回执

### 临时规则策略

- `/netsec_open`
- `/netsec_close_temp`
- `run open_ingress_preview/apply`
- `run cleanup_temp_rules_preview/apply`

以上入口都支持直接接受**任意合法单个 TCP 端口**，统一走预览 / 确认 / 回执链路。

删除临时规则时，只匹配本工具写入的描述前缀：

```text
oci-master-temp
```

以避免误删已有长期规则。

如果实例仍处于以下过渡态：

- `STARTING`
- `STOPPING`
- `RESETTING`

回执会明确提示稍后复查。

---

## ⚠️ 已知注意事项

- `OCI_Master.py` 启动时会尝试清屏；在无 `TERM` 环境下可能看到 `TERM environment variable not set`，**不影响功能**
- 如果要做长期部署，建议补一个 systemd service，把 `run_oci_master.sh telegram` 收成正式服务
- Audit Events 依赖当前 profile 对 Identity Domain 审计接口有权限；若租户 / 域权限不足，会直接报 OCI / HTTP 错误
- Object Storage 的统计字段使用 `approximateCount / approximateSize`，属于 OCI 近似值，不保证秒级精确
- 当前快捷网络修改优先选主 VNIC 关联的第一个 NSG；若主 VNIC 没有 NSG，则回落到主 VNIC 所在 Subnet 的第一个 Security List
- 这是一个有意保守的上线策略：**先覆盖高频低风险场景，不碰附属 VNIC / IPv6 / 更复杂拓扑**

---

## 🎯 项目定位

OCI Master 的目标不是替代 OCI 官方控制台，而是把高频、分散、重复的日常操作收束成一个更轻、更快、更适合远程运维的入口。

如果你希望：

- 少开几个页面
- 少翻几层 OCI 控制台菜单
- 在 Telegram 上也能做基础运维
- 在执行网络变更时保留确认感和安全边界

那么这个项目就是为这种工作流而生的。
