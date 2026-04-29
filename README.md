# OCI Master

一个基于 Python 的 OCI 运维工具，当前支持：
- 当前用户信息查询
- 本月费用账单查询
- Identity Domain 密码策略管理
- 实例列表 / 实例详情
- 实例启动 / 停止 / 重启
- 实例网络 / 安全概览（VNIC / Subnet / NSG / Security List）
- 低风险快捷网络操作：常见 TCP 端口新增入站规则、删除临时规则（预览/确认式）
- Region subscriptions 查询
- Object Storage / Bucket 基础信息查询
- Audit Events 查询（只读）
- 实例列表分页、动作后状态复查、默认 compartment 过滤
- Telegram Bot 命令入口

## 当前运行约定

这个项目当前**不依赖系统 Python 环境完整性**。
宿主机的 `/usr/bin/python3` 缺少完整 `venv/pip` 能力，因此项目采用：
- 运行解释器：`/usr/local/python3/bin/python3.14`
- 项目本地依赖目录：`./.deps`
- 兼容入口：`OCI_Master.py` 会自动把 `./.deps` 注入 `sys.path`

也就是说，正常情况下直接运行下面这些命令即可，不需要手工再拼 `PYTHONPATH`。

## 目录说明

- `OCI_Master.py`：兼容入口
- `oci_master/`：主代码包
- `oci_master/services/`：业务模块
- `oci_master_config.json`：实际配置
- `oci_master_config.example.json`：配置示例
- `.deps/`：项目本地 Python 依赖目录
- `run_oci_master.sh`：推荐启动脚本

## 推荐启动方式

### CLI 菜单

> ./run_oci_master.sh

### Telegram Bot 轮询

> ./run_oci_master.sh telegram

### 直接执行 action

> ./run_oci_master.sh run user_info
> ./run_oci_master.sh run usage_fee
> ./run_oci_master.sh run region_subscriptions
> ./run_oci_master.sh run bucket_info
> ./run_oci_master.sh run audit_events:10
> ./run_oci_master.sh run policies
> ./run_oci_master.sh run list_instances
> ./run_oci_master.sh run instance_detail:oracle-arm
> ./run_oci_master.sh run instance_network:oracle-arm
> ./run_oci_master.sh run open_ingress_preview:oracle-arm:22:1.2.3.4/32
> ./run_oci_master.sh run cleanup_temp_rules_preview:oracle-arm:22:1.2.3.4/32

## 也可直接运行兼容入口

> /usr/local/python3/bin/python3.14 OCI_Master.py
> /usr/local/python3/bin/python3.14 OCI_Master.py telegram
> /usr/local/python3/bin/python3.14 OCI_Master.py run list_instances

`OCI_Master.py` 已自动注入 `.deps`，因此不必再额外写 `PYTHONPATH`。

## Telegram 支持命令

> /user_info
> /usage_fee
> /regions
> /bucket_info
> /audit_events 10
> /policies
> /create_safe_policy
> /delete_policy 名称
> /instances
> /instance_detail <名称|OCID>
> /instance_start <名称|OCID>
> /instance_stop <名称|OCID>
> /instance_restart <名称|OCID>
> /instance_network <名称|OCID>
> /netsec_open <名称|OCID> <端口> <CIDR>
> /netsec_close_temp <名称|OCID> <端口> <CIDR>
> /run <action>

## 配置说明

当前配置同时支持两种写法：

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

### 新写法（推荐，便于多账号）

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
        "default_compartment_names": ["Prod" ]
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

说明：
- `instances.default_compartment_ids` / `instances.default_compartment_names` 是全局默认过滤。
- `profiles.<name>.instance_defaults.*` 会覆盖全局默认过滤，适合多账号分开设白名单。
- 两者都不配时，仍保持旧行为：遍历全部可访问 compartment。
- `telegram_page_size` 控制 Telegram 实例列表每页数量。
- `network_security.quick_open_allowed_tcp_ports` 只控制 Telegram 端口页里的“快捷按钮”有哪些，默认仅 22/80/443/3389。
- 现在命令式入口与 Telegram 输入态都支持自定义单个 TCP 端口；仍限制为 `1-65535`，且不支持端口段/多端口/UDP。
- `network_security.default_source_cidr` 仅作为 CLI 交互输入时的默认值；Telegram/CLI action 仍建议显式传 CIDR。

## 已验证情况

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

实例动作链路已接好，但是否执行真实启停/重启应按现场需要谨慎操作。
网络快捷操作当前只做低风险范围：仅主 VNIC 关联对象、仅 ingress、仅单个 TCP 端口、执行前先预览。

## 实例管理补充说明

- Telegram `/instances` 现在支持分页浏览，不再只截前几个固定实例。
- 新增 `/regions`、`/bucket_info`、`/audit_events [N]` 以及对应 `/run region_subscriptions`、`/run bucket_info`、`/run audit_events[:N]`。
- Object Storage 当前只做只读查看：namespace、bucket 列表、compartment、创建时间、public access、storage tier、versioning、auto tiering、approximate object count/size。
- Audit Events 当前只做只读查看，走 Identity Domain `/admin/v1/AuditEvents`，按旧版展示 message / actor / clientIp / timestamp。
- 实例列表按钮与动作按钮全部改用短 token 映射，避免把超长 OCID 直接塞进 `callback_data`。
- `/instance_start`、`/instance_stop`、`/instance_restart` 以及 Telegram 按钮动作，提交后会补一次短暂状态复查。
- `/instance_network` 与实例详情页按钮可查看该实例相关的 VNIC / Subnet / NSG / Security List 概览，并继续点进 network/security 按钮流。
- Telegram 网络/安全按钮流现已支持：实例详情 → 网络/安全概览 → 选择“开放临时端口 / 清理临时规则” → 快捷端口按钮或“输入自定义端口” → 默认或自定义 CIDR → 预览 → 确认 → 执行回执。
- 端口选择页默认使用 `network_security.quick_open_allowed_tcp_ports` 生成快捷按钮，但不再把它当成硬限制；CIDR 支持一键使用默认值或进入输入式自定义。
- `/netsec_open`、`/netsec_close_temp` 与 `run open_ingress_preview/apply`、`run cleanup_temp_rules_preview/apply` 已可直接接受任意合法单个 TCP 端口，并继续统一走预览/确认/回执链路。
- 删除临时规则只匹配本工具写入的临时描述前缀 `oci-master-temp`，避免误删已有长期规则。
- 如果实例仍处于 `STARTING` / `STOPPING` / `RESETTING` 等过渡态，回执会明确提示稍后复查。

## 已知注意事项

- 当前 `OCI_Master.py` 启动时会尝试清屏；在无 `TERM` 环境下可能看到 `TERM environment variable not set`，不影响功能。
- 如果后续要做长期部署，建议再补一个 systemd service 文件，把 `run_oci_master.sh telegram` 收成正式服务。
- Audit Events 依赖当前 profile 对 Identity Domain 审计接口有权限；若租户/域权限不足，会直接报 OCI/HTTP 错误。
- Object Storage bucket 统计字段使用 approximateCount / approximateSize，属于 OCI 近似值，不保证秒级精确。
- 当前快捷网络修改优先选主 VNIC 关联的第一个 NSG；若主 VNIC 没 NSG，则回落到主 VNIC 所在 Subnet 的第一个 Security List。这样是为了先保守上线，不碰附属 VNIC / IPv6 / 更复杂拓扑。
