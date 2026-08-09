# OCI Tool 项目审查与优化建议

**审查日期：** 2026-08-09
**项目路径：** `/opt/oci-tool`
**审查范围：** 架构、业务逻辑、安全性、可靠性、测试、依赖、systemd 运维
**审查方式：** 只读源码检查、静态检查、安全测试、生产解释器环境验证；未调用 OCI 写接口，未修改或重启正式服务。

## 一、结论

项目已具备 CLI 与 Telegram Bot 两套入口，覆盖租户、区域、Bucket、账单、实例、网络安全和密码策略管理。但当前不宜在未补强情况下继续扩大生产写操作范围。

首要问题不是大规模重构，而是以下生产安全和正确性风险：

1. Telegram 白名单漏配时默认放行。
2. NSG 新增、删除规则使用错误 API 语义。
3. callback 状态未绑定用户，无 TTL 和一次性消费。
4. 停机、重启、策略删除存在绕过确认的路径。
5. Security List 整体更新缺少 ETag 并发保护。
6. 现有 7 个测试全部报错，无法提供回归基线。
7. systemd 以 root 运行，解释器和依赖部署不可复现。

建议先完成最小安全闭环，再处理性能和模块拆分。

## 二、已验证基线

| 检查项 | 结果 |
|---|---|
| Python 编译检查 | `RC=0` |
| Python 3.14 OCI SDK 导入 | `RC=0`，OCI SDK `2.152.1` |
| Python 3.14 Requests 导入 | `RC=0`，Requests `2.33.1` |
| `unittest discover` | `RC=1`，7 个测试全部 ERROR |
| Shell 语法检查 | `RC=0` |
| systemd unit 静态验证 | `RC=0` |
| 服务状态 | active、enabled |
| Git diff 检查 | `RC=0` |
| OCI 生产写操作 | 未执行 |
| 服务重启 | 未执行 |

测试命令：

```bash
/usr/local/python3/bin/python3.14 -m unittest discover -s tests -v
```

当前结果：

```text
Ran 7 tests
FAILED (errors=7)
```

## 三、P0：必须优先修复

### 1. Telegram 鉴权默认放行

**位置：** `oci_master/telegram_bot.py:97-116,329-334`

当前逻辑把空白名单解释为“不限制”：

```python
chat_ok = not self.allowed_chat_ids or chat_id in self.allowed_chat_ids
user_ok = not self.allowed_user_ids or user_id in self.allowed_user_ids
```

**影响：** 漏配 `allowed_chat_ids` 或 `allowed_user_ids` 时，任意 Telegram 用户可能调用 OCI 查询及写操作。

**最小修复：**

- `validate()` 要求 `allowed_chat_ids` 和 `allowed_user_ids` 均非空。
- `is_authorized()` 改为 fail-closed。
- 群聊同时校验 chat ID 与 user ID。
- 若未来需要公开只读模式，增加独立显式配置，不能复用管理入口。

**验证：** 空列表、仅聊天列表、仅用户列表均应拒绝启动；只有两个 ID 同时匹配才授权。

### 2. NSG 新增规则调用错误 API

**位置：** `oci_master/services/network_security.py:945-957`

当前代码构造新增规则模型，却调用：

```python
update_network_security_group_security_rules()
```

OCI SDK 已核实：新增规则应调用：

```python
add_network_security_group_security_rules()
```

并使用：

```python
oci.core.models.AddNetworkSecurityGroupSecurityRulesDetails
```

**影响：** NSG 新增规则可能被 API 拒绝，或产生不符合预期的结果。

**最小修复：** 只替换该调用和请求模型，不新增抽象。

### 3. NSG 删除规则语义错误

**位置：**

- `oci_master/services/network_security.py:275-298`
- `oci_master/services/network_security.py:1128-1150`

当前实现读取全部规则、排除待删除规则，再调用更新 API。OCI NSG 更新接口不会把“未出现在请求中的规则”解释为删除。

正确接口：

```python
remove_network_security_group_security_rules()
```

正确模型：

```python
oci.core.models.RemoveNetworkSecurityGroupSecurityRulesDetails(
    security_rule_ids=rule_ids,
)
```

**影响：** 删除可能无效，也可能产生模型校验或 API 错误；Telegram 回执可能与 OCI 实际状态不一致。

**最小修复：** 收集规则 ID，调用 remove API；执行后重新读取 NSG，确认目标规则 ID 已不存在。

### 4. callback 状态可跨用户重放

**位置：** `oci_master/telegram_bot.py:142-149,210-220,654-657,987-1000,1410-1424`

当前状态：

- token 未绑定 `chat_id/user_id`
- token 缺少随机 nonce
- 无 TTL
- 无一次性消费
- 状态字典无容量上限

**影响：** 同一授权群内其他用户、转发的旧按钮或重复点击可能重放网络规则、实例或策略写操作。

**最小修复：**

- 使用 `secrets.token_urlsafe()` 生成短随机 nonce。
- 状态保存 `chat_id`、`user_id`、`action`、`target`、`created_at`。
- 使用 `time.monotonic()` 实现 60 秒 TTL。
- 危险操作执行前原子 `pop()`，保证单次消费。
- 增加容量上限和过期清理。
- 单实例部署暂不引入 Redis。

**验证：** 用户 A 创建、用户 B 点击必须拒绝；过期按钮必须拒绝；连续点击只能执行一次；重启后明确提示会话失效。

## 四、P1：首批同步处理

### 1. 危险命令绕过确认流程

**位置：**

- `oci_master/telegram_bot.py:725-753,1441-1452,1742-1761`
- `oci_master/services/policies.py:293-309`

以下路径可能直接执行：

- `/instance_stop`
- `/instance_restart`
- `/delete_policy NAME`

策略删除路径使用 `auto_approve=True`。

**最小修复：** 命令只创建短时确认状态，不直接调用 OCI；确认状态绑定用户、聊天、动作和目标。执行前重新读取实例状态。策略删除确认记录不可变标识；旧按钮不得删除后来创建的同名策略。

### 2. Security List 整体更新缺少并发保护

**位置：** `oci_master/services/network_security.py:300-316,965-983,1158-1175`

当前流程读取完整规则后整体覆盖更新，但未传读取响应的 ETag/`if_match`。

**影响：** OCI Console、Terraform 或其他进程并发修改时，旧快照可能覆盖外部更新。

**最小修复：** 保留 `get_security_list()` 响应 ETag，更新时传 `if_match`。遇到 `412 Precondition Failed` 时停止，重新读取并要求用户重新确认；禁止静默覆盖或盲目重试。

### 3. 默认网络开放策略过宽

**位置：**

- `oci_master/config.py:123-137`
- `oci_master/services/network_security.py:737-744,854-878`
- `oci_master_config.example.json:24-26`

问题：

- 默认 CIDR 支持 `0.0.0.0/0`。
- 快捷端口包含 SSH/RDP。
- `_normalize_port()` 接收 `allowed_ports`，但未校验端口是否属于该列表。

**最小修复：**

- 默认来源要求显式输入，或默认单地址 `/32`。
- 普通流程只允许配置端口。
- `0.0.0.0/0` 使用独立高风险开关。
- 公网 SSH/RDP 和自定义端口增加二次确认，明确显示实例、端口和 CIDR。

### 4. Telegram Token 可能进入错误日志

**位置：** `oci_master/telegram_bot.py:102,118-127,1456-1460,1764-1785`

Telegram Bot token 位于请求 URL。原始 `requests` 异常可能包含完整 URL，并被写入 journald 或发送给用户。

**最小修复：** 用户只收到固定错误码；日志记录异常类型、HTTP 状态和脱敏摘要，不记录 URL、响应体、请求对象或配置。统一过滤 token。若怀疑已泄露，立即通过 BotFather 轮换。

### 5. Telegram 更新可能在处理成功前确认

**位置：** `oci_master/telegram_bot.py:245-252,1462-1466,1776-1786`

**影响：** 处理失败后更新可能无法重新获取，消息永久丢失。

**最小修复：** 仅在业务处理完成后推进 offset；明确处理失败策略。读取操作可有限重试，非幂等写操作不可盲目重试。

### 6. 测试基线失效

**位置：**

- `tests/test_bucket_info.py`
- `tests/test_region_subscriptions.py`

测试仍 patch 已删除的 `OCI_Master.*` 导出，错误包括：

- `get_oci_config`
- `get_bucket_info_data`
- `render_bucket_info_telegram`
- `get_region_subscriptions_data`
- `render_region_subscriptions_telegram`

实际实现已迁移到 `oci_master.services.tenant_insights` 等模块。

**最小修复：** 测试直接 import 实际模块，并 patch 被测模块实际查找符号的位置。不要恢复旧 `OCI_Master.*` 兼容导出。

**首批新增测试：**

- 空白名单拒绝启动。
- callback owner、TTL、单次消费。
- NSG add/remove 使用正确 API 和模型。
- Security List `if_match` 与 412 行为。
- 危险文本命令不能绕过确认。
- 日志不包含 Bot token。

### 7. Python 环境与依赖不可复现

**位置：**

- `requirements.txt:1-2`
- `run_oci_master.sh`
- `scripts/setup_systemd.sh:12,29,151`

当前 `requirements.txt` 只有无版本约束的 `oci` 和 `requests`。正式服务使用 Python 3.14，而安装脚本默认使用 `/usr/bin/python3`；现场系统 Python 导入 OCI 失败。

**最小修复：**

- 建立 `/opt/oci-tool/.venv`。
- 测试、启动脚本和 systemd unit 统一使用 `.venv/bin/python`。
- 固定已验证依赖版本或生成受审计 lock 文件。
- 安装前执行 `import oci, requests` 与 `pip check`。

### 8. systemd 权限和隔离不足

**位置：** `/etc/systemd/system/oci-master-telegram.service`

现场配置包含：

```ini
User=root
ProtectHome=no
ProtectSystem=no
NoNewPrivileges=no
Restart=always
```

**最小修复：** 使用专用服务用户，仅授予读取 OCI 配置和运行配置所需权限；启用 `NoNewPrivileges=yes`、`PrivateTmp=yes`、`ProtectSystem=strict`，再用 `ReadWritePaths=` 开放必要目录。先在 canary unit 验证，避免直接影响正式服务。

### 9. `setup_systemd.sh --dry-run` 仍有副作用

**位置：** `scripts/setup_systemd.sh:30,133-140,166-168`

当前演练一遍仍可能创建目录、复制文件、创建备份或覆盖 unit。

**最小修复：** 所有写操作统一经过无副作用执行层。演练一遍仅显示目标路径、命令和 diff，不执行 `mkdir`、`cp`、`mv`、`systemctl`。重定向写文件需单独处理，不能只包装 shell 命令。

## 五、P2：安全闭环后处理

### 1. 超长路由函数

**位置：**

- `oci_master/telegram_bot.py:987-1460`，`handle_callback_query()` 约 474 行
- `oci_master/telegram_bot.py:1462-1768`，`process_update()` 约 307 行

**最小修复：** 按现有 callback 前缀拆成少量私有 handler；顶层只做解析、授权和分派。先补测试，再拆分，不做大规模框架重写。

### 2. CLI 与 Telegram 命令分派重复

**位置：**

- `oci_master/app.py:122-205`
- `oci_master/telegram_bot.py:693-879,1639-1768`

**最小修复：** 提取返回结构化结果的最小 action dispatcher；CLI 和 Telegram 只保留输入适配与渲染。待 P0/P1 稳定后实施。

### 3. 单实例操作重复扫描全租户

**位置：**

- `oci_master/services/instances.py:88-141,308-313,415-426`
- `oci_master/services/network_security.py:341-344`

**影响：** 单次详情或操作触发全 Compartment 枚举和逐实例 VNIC 查询，形成 N+1 OCI 请求。

**最小修复：** OCID 直接调用 `get_instance()`；按名称查询时使用轻量列表，IP 仅在真正需要时查询。

### 4. 宽泛异常掩盖编程错误

**位置：** `oci_master/services/instances.py:116-123,195-208`

**最小修复：** 只捕获 `oci.exceptions.ServiceError` 和明确网络异常；`AttributeError`、`TypeError` 等编程错误保留 traceback 并继续抛出。

### 5. 配置校验弱、默认值重复

**位置：**

- `oci_master/config.py:13-55,95-138`
- `oci_master/telegram_bot.py:518,528,1088,1147,1528`

**最小修复：** 在 `load_app_config()` 集中校验必需键和类型；UI 只读取规范化后的 runtime 配置，不维护第二套默认值。

## 六、推荐实施顺序

### 第一批：安全与正确性闭环

1. Telegram 鉴权改为 fail-closed。
2. 修正 NSG add/remove API。
3. callback 增加随机 nonce、owner、TTL、容量上限和单次消费。
4. 为停机、重启、策略删除补统一确认。
5. 修测试 import/patch 路径，恢复绿色基线。
6. Telegram 异常和日志脱敏。
7. Security List 增加 ETag/`if_match`。
8. 限制公网 CIDR 和自定义端口。

### 第二批：部署可靠性

1. 建项目 `.venv`，固定依赖。
2. 测试、脚本和 unit 统一解释器。
3. 修复 `setup_systemd.sh` 演练一遍副作用。
4. systemd 改专用用户并逐步启用沙箱。
5. 增加最小 CI：编译、`unittest discover`、依赖检查。

### 第三批：性能与可维护性

1. 优化实例查询，避免全租户 N+1 扫描。
2. 拆分长 callback/update 函数。
3. 合并重复 action 分派和配置默认值。
4. 收窄宽泛异常捕获。

## 七、验收标准

第一批完成后至少满足：

- 空白名单配置无法启动 Bot。
- 未授权用户不能触发任何查询或写操作。
- NSG 新增、删除分别调用 OCI SDK 正确接口。
- 危险 callback 绑定 owner，60 秒过期，只能消费一次。
- 文本命令不能绕过停机、重启、删除确认。
- Security List 并发变化返回 412 时不覆盖外部修改。
- 日志和用户错误消息不包含 Telegram token、凭据、请求 URL 或 OCI 请求对象。
- 所有单元测试通过，测试运行 `RC=0`。
- systemd 安装演练一遍不产生文件或服务状态变化。
- 正式服务不以 root 运行，且使用项目固定解释器。

## 八、变更边界

本审查和本文档编写期间：

- 未修改业务代码。
- 未修改正式配置。
- 未调用 OCI 写接口。
- 未提交 Git。
- 未部署或重启服务。
- 未记录任何凭据、Token、密码、私钥、连接字符串、OCID 或 IP。

> 注：以上“变更边界”是审查阶段记录，后续实施记录见下方“九、实施进度与后续任务”。

## 九、实施进度与后续任务

### 已完成并已部署

1. Telegram 白名单 fail-closed 鉴权。
2. NSG 新增规则改用 `add_network_security_group_security_rules()`。
3. NSG 删除规则改用 `remove_network_security_group_security_rules()`，并回读确认。
4. Callback 增加随机 nonce、owner、60 秒 TTL、容量上限和单次消费。
5. `/instance_stop`、`/instance_restart`、`/delete_policy` 增加统一确认流程。
6. Security List 更新增加 ETag / `if_match`，缺少 ETag 或返回 412 时拒绝覆盖。
7. 默认公网 CIDR 收紧，`0.0.0.0/0` 需显式开关；自定义端口标记高风险二次确认。
8. Telegram 请求异常和用户错误消息脱敏。

最近一次正式服务验证：

- 服务：`oci-master-telegram.service`
- 状态：`active (running)`
- 工作目录：`/opt/oci-tool`
- 解释器：`/usr/local/python3/bin/python3.14`
- 最近部署 PID：`1787665`
- 未调用 OCI 写接口进行部署验证。

### 后续任务：共 9 项

#### P0/P1：测试与部署可靠性（4 项）

1. ~~修复剩余 7 个测试的旧 `OCI_Master.*` import/patch 路径，恢复完整测试绿色基线。~~ **已完成：27/27 测试通过**
2. ~~建立项目 `.venv`，固定 OCI SDK、Requests 等依赖版本。~~ **已完成：`pip check` 通过，已生成 `requirements.lock`**
3. ~~统一测试、启动脚本和 systemd unit 的项目解释器与依赖来源。~~ **已完成：正式服务已切换到 `.venv/bin/python`**
4. ~~修复 `scripts/setup_systemd.sh --dry-run` 的文件和 systemd 副作用。~~ **已完成：演练验证无文件和服务状态变化**

#### P1：运行权限与隔离（1 项）

5. ~~将 systemd 服务从 root 迁移到专用用户，并分阶段启用 systemd 沙箱；先使用 canary unit 验证。~~ **已完成：`oci-master` + systemd 沙箱已部署并验证**

#### P2：性能与可维护性（4 项）

6. ~~优化单实例查询，避免全租户扫描和 N+1 OCI 请求。~~ **已完成：OCID 直查，名称查询使用轻量列表；27/27 测试通过**
7. ~~拆分 `handle_callback_query()` 和 `process_update()` 长函数。~~ **已完成：提取 usage/menu callback 与消息路由前置 handler；新增 3 个路由回归测试；30/30 测试通过**
8. ~~合并 CLI / Telegram 重复 action 分派和配置默认值。~~ **已完成：提取共享 action 规范化函数，统一 Telegram runtime 默认值；新增任务8回归测试；34/34 测试通过。验证：`unittest discover`、`py_compile`、`bash -n`、`git diff --check` 均 RC=0。未重启正式服务，未调用 OCI 写接口。**
#### 9. ~~收窄实例服务中的宽泛异常捕获，保留编程错误 traceback。~~ **已完成：VNIC/IP 可选查询与状态复查仅捕获 OCI `ServiceError`、OCI/Requests 网络异常及内置超时/连接异常；`AttributeError`、`TypeError` 等编程错误向上抛出。新增 7 个异常边界测试通过。验证：针对性测试、完整 `unittest discover`、`py_compile`、`bash -n`、`git diff --check` 均 RC=0；已部署并重启正式服务，服务验证正常。**

当前 1-9 项任务均已完成；正式服务当前运行任务 8/9 版本，最近 PID：`1802608`，状态：`active (running)`，测试：`41/41` 通过。

## 十、第二轮逻辑与操作优化

本轮已完成代码、测试并部署正式服务：

1. Telegram 轮询 offset 改为业务处理成功后推进，失败时保留 offset 以便重试。
2. Telegram 轮询网络/处理异常日志脱敏，不输出原始异常、URL 或 Token。
3. 服务重启后向授权 chat 发送一次性提示，说明旧按钮流程失效且危险操作不会恢复。
4. 单次 Telegram update 增加轻量查询复用，避免同一实例详情重复查询。
5. 实例列表默认取消逐实例 VNIC/IP 查询，详情和网络页面仍按需查询。
6. CLI 账单错误改为固定错误提示 + 错误编号，不向用户显示原始异常。
7. `setup_systemd.sh` 默认生成 `oci-master`、项目 `.venv` 和完整 systemd 沙箱配置；`--dry-run` 保持无副作用。

验证结果：

- 完整测试：`47/47` 通过，`RC=0`
- Python 编译检查：`RC=0`
- Shell 语法检查：`RC=0`
- `git diff --check`：`RC=0`
- 未调用 OCI 写接口
- 已部署正式服务，最近 PID：`1814054`，状态：`active (running)`
