# OCI Master Telegram Security List 向导改造需求与验收清单

## 1. 项目背景

当前 OCI Master Telegram 工具中的 Security List 管理能力，原本偏向“手输 OCID + 直接执行命令”的模式。为了提升交互效率和可用性，需要把 `/sl_menu` 改造成 **实例优先（instance-first）** 的 Telegram 向导流，并把 Security List 的查看、新增、删除、替换规则操作都收口进同一套状态机。

本轮工作重点不是新增独立模块，而是 **直接修改现有 `OCI_Master.py`**，复用已有 Telegram Bot 主处理逻辑、菜单状态管理函数和 OCI 规则构造 / apply 能力。

---

## 2. 目标需求（可信版）

### 2.1 总体目标

将 `/sl_menu` 从“输入 Security List OCID 后执行动作”改造成以下主流程：

1. 用户进入 `/sl_menu`
2. 选择操作类型
   - 查看规则
   - 新增入站规则
   - 新增出站规则
   - 删除入站规则
   - 删除出站规则
   - 替换入站规则
   - 替换出站规则
3. 选择实例
4. 选择该实例关联的 Security List
5. 进入对应向导或详情页
6. 完成提交、取消或返回上一步

### 2.2 明确约束

- 必须优先修改：
  - `OCI_Master.py`
- 必须复用现有状态函数：
  - `_menu_key(chat_id, user_id)`
  - `_get_menu_state(chat_id, user_id)`
  - `_set_menu_state(chat_id, user_id, state)`
  - `_clear_menu_state(chat_id, user_id)`
- 不要另起一个全新的 Telegram 菜单模块。
- 回调数据必须避免直接携带长 OCID，防止 Telegram `callback_data` 超长。
- 必须兼容“按钮选择”和“用户手工文本输入”两种交互路径。
- 编写代码后必须做自审与验证。

### 2.3 现有已确认能力

代码中已存在以下基础能力，可直接复用：

- 实例枚举：`_list_instances(config)`
- 实例网络拓扑获取：`_fetch_instance_network_topology(config, instance_id)`
- Security List 聚合：`_list_security_list_candidates(config)`
- 安全列表详情获取：`_fetch_security_list(config, security_list_id)`
- Security List 规则新增 / 删除 / 替换命令与 apply 能力
- Telegram Bot 主命令与 callback handler
- 菜单会话状态持久化（`.telegram_menu_sessions.json`）

---

## 3. 当前已完成项（可作为已有基础）

### 3.1 实例优先主链路已落地

已实现 `/sl_menu` 的实例优先主流程：

- 动作选择 → 实例选择 → 实例关联 Security List 选择 → 后续动作

已涉及的关键函数 / 路由包括：

- `build_sl_root_keyboard()`
- `_render_instance_picker_page(...)`
- `_get_instance_security_list_candidates(instance_id)`
- `_render_instance_security_list_page(...)`
- `_render_sl_action_menu(...)`
- callback handler 中的：
  - `slm:start:`
  - `slm:instances:`
  - `slm:inst:`
  - `slm:pick:`

### 3.2 callback_data 短 token 化已完成（第一版）

为规避 Telegram callback_data 长度风险，已将回调中的长 OCID 改为短 token。

当前实际方案：

- `i1 / i2 / ...` → instance token
- `s1 / s2 / ...` → security list token
- `r1 / r2 / ...` → rule token

token → 真正 OCID/序号 的映射保存在当前 menu state 中。

### 3.3 常用快捷按钮已补（第一版）

#### CIDR 快捷按钮

- `0.0.0.0/0`
- `::/0`
- `10.0.0.0/8`
- `192.168.0.0/16`
- 自定义输入

#### 端口快捷按钮

- `22`
- `80`
- `443`
- `25000-25100`
- 自定义输入

### 3.4 已确认的验证结果

已完成以下验证：

- `python3 -m py_compile OCI_Master.py` → **RC=0**
- 本地轻量验证：
  - 回调形态已从长 OCID 变为短 token
  - 例如：
    - `slm:inst:add_ingress:i1`
    - `slm:pick:add_ingress:i1:s1`
    - `slm:protocol:add_ingress:s1:6`
- `oci-master-telegram.service` 当前状态已核验为：
  - `active (running)`

---

## 4. 剩余问题清单（重点交给其他模型继续处理）

### 问题 1：向导状态机未完全闭环

当前 Security List 向导虽然已有主链路，但“按钮流 + 用户文本输入流”还未完全统一到一套稳定状态机中。

#### 具体表现

- 选完协议后，CIDR 输入流程仍需继续完善
- 自定义 CIDR 输入、端口输入、描述输入之间的状态切换未完全闭环
- 用户发送文本时，可能与当前 `awaiting` 状态不一致

#### 验收标准

- 对新增 / 替换规则流程：
  - 选择协议后，必须明确进入 CIDR 步骤
  - 选择 / 输入 CIDR 后，必须明确进入端口步骤（若协议需要端口）
  - 选择 / 输入端口后，必须明确进入描述步骤
  - 描述完成后，必须进入确认页
- 所有状态切换必须只依赖现有 menu state，不允许“漂移状态”
- 用户在任一步发送文本时，程序能够根据 `awaiting` 做正确解析
- 非当前步骤的文本不得误写到别的字段

---

### 问题 2：自定义 CIDR 输入缺少严格校验

目前已有 CIDR 快捷按钮，但自定义输入还需要补强校验和报错反馈。

#### 需要处理

- 校验 IPv4 CIDR 合法性
- 校验 IPv6 CIDR 合法性
- 对明显非法输入给出可理解报错
- 不要因为非法 CIDR 导致状态机错乱

#### 验收标准

- 输入合法 IPv4 CIDR（如 `0.0.0.0/0`、`192.168.1.0/24`）可进入下一步
- 输入合法 IPv6 CIDR（如 `::/0`、`2001:db8::/32`）可进入下一步
- 输入非法内容（如 `abc`、`1.1.1.1`、`999.999.999.999/33`）时：
  - 明确返回错误提示
  - 仍停留在 CIDR 输入步骤
  - 之前已选的 action / instance_id / sl_id / protocol 不丢失

---

### 问题 3：自定义端口 / 端口范围输入缺少严格校验

目前已有端口快捷按钮，但自定义端口输入还未完全收口。

#### 需要处理

- 支持单端口，例如：`22`
- 支持范围端口，例如：`25000-25100`
- 校验端口范围合法性
- 将解析结果稳定写入 `port_min` / `port_max`

#### 验收标准

- 输入 `22` → `port_min=22`，`port_max=22`
- 输入 `443` → `port_min=443`，`port_max=443`
- 输入 `25000-25100` → `port_min=25000`，`port_max=25100`
- 输入非法值（如 `0`、`65536`、`100-99`、`abc`）时：
  - 明确报错
  - 保持在端口输入步骤
  - 不破坏现有 state

---

### 问题 4：ALL / ICMP 等无需端口协议的分支要明确

不是所有协议都应该进入端口步骤。

#### 需要处理

- `ALL` 协议
- `ICMP`（以及若代码中未来扩展的 IPv6 ICMP）

#### 验收标准

- 当协议无需端口时：
  - 选完协议、CIDR 后直接进入描述步骤
  - `port_min` / `port_max` 保持空或符合现有实现预期
- 不应错误弹出端口输入步骤

---

### 问题 5：返回链路不完整，缺少“返回上一步”

目前主菜单返回已存在，但多步向导中的“返回上一步”仍不完整。

#### 需要处理

至少覆盖以下链路：

- 协议选择页 → 返回 Security List 动作页
- CIDR 输入页 → 返回协议选择页
- 端口输入页 → 返回 CIDR 输入页
- 描述输入页 → 返回端口页或 CIDR 页（取决于协议）
- 确认页 → 返回描述页

#### 验收标准

- 每一步都至少有一个稳定的“返回上一步”入口
- 返回时：
  - 已有 state 不错乱
  - 不跳错实例
  - 不跳错 Security List
  - 不丢失 token 映射
- 返回后重新选择时，可继续正确提交

---

### 问题 6：delete / replace 链路仍需重点审查

删除和替换操作相比新增更容易出现状态错位。

#### 风险点

- `rule_index` 与选中规则不一致
- 回退后重新进入时，规则 token 失效
- `replace_*` 在重新选协议/CIDR/端口后覆盖了错误规则

#### 验收标准

- `delete_ingress` / `delete_egress`：
  - 选择规则后进入确认页
  - 确认页显示的规则序号与用户选择一致
  - 提交时操作的就是该条规则
- `replace_ingress` / `replace_egress`：
  - 选择规则后进入新规则向导
  - 最终提交替换的是所选规则，而非其它序号
  - 返回上一步/取消后再重新选规则，状态仍一致

---

### 问题 7：真实 Telegram 端到端回归还没完成

当前已有编译和轻量本地验证，但还缺完整 Telegram 交互回归。

#### 验收标准

必须至少完成一次真实 Telegram 端到端验证，覆盖：

1. `/sl_menu`
2. 选择实例
3. 选择 Security List
4. 选择一种操作：
   - 新增规则
   - 删除规则
   - 替换规则
5. 走完：
   - 快捷按钮路径
   - 至少一条自定义输入路径
6. 到达确认页
7. 验证返回链路至少一次

建议至少对以下场景分别验证：

- 新增 ingress（TCP + 端口）
- 新增 egress（ALL 或 ICMP，无端口）
- 删除 ingress
- 替换 ingress

---

## 5. 建议的技术实现方向

### 5.1 保持单一状态源

所有中间态都应保存在当前用户的 menu state 中，例如：

```python
{
  "action": "add_ingress",
  "instance_id": "ocid1.instance...",
  "sl_id": "ocid1.securitylist...",
  "rule_index": 2,
  "protocol": "6",
  "cidr": "0.0.0.0/0",
  "port_min": 22,
  "port_max": 22,
  "description": "ssh",
  "awaiting": "description",
  "tokens": {
    "i1": "ocid1.instance...",
    "s1": "ocid1.securitylist...",
    "r1": "1"
  }
}
```

不要把关键上下文分散到多个旁路变量或新的持久化结构中。

### 5.2 建议为每一步补专用渲染函数

可以考虑继续拆分但仍留在 `OCI_Master.py` 内，例如：

- `_render_sl_protocol_step(...)`
- `_render_sl_cidr_step(...)`
- `_render_sl_port_step(...)`
- `_render_sl_description_step(...)`
- `_render_sl_confirm_step(...)`

目的不是模块化炫技，而是降低 callback handler 中 if/else 分支爆炸。

### 5.3 用户文本输入处理要与 awaiting 绑定

建议梳理 Telegram 普通文本消息处理逻辑，明确：

- 如果当前 state 的 `awaiting == "cidr"`，则文本按 CIDR 解析
- 如果 `awaiting == "port"`，则文本按端口解析
- 如果 `awaiting == "description"`，则文本按描述处理
- 若用户发 `/cancel` 或相应命令，可清理当前 SL 向导状态

---

## 6. 必做验证清单

完成修改后，至少执行以下验证：

### 6.1 编译检查

```bash
python3 -m py_compile OCI_Master.py
```

**验收标准：** RC=0

### 6.2 本地轻量验证

至少验证：

- 实例按钮 callback_data 不含长 OCID
- 安全列表按钮 callback_data 不含长 OCID
- 协议按钮 callback_data 不含长 OCID
- 自定义 CIDR / 端口流程能落到正确 state
- delete / replace 的 rule token 能正确映射

**验收标准：** 所有关键路径输出符合预期

### 6.3 服务验证

如修改已部署版本，检查：

```bash
systemctl restart oci-master-telegram.service
systemctl --no-pager -l status oci-master-telegram.service
```

**验收标准：**

- restart 成功
- service 为 `active (running)`
- 无明显 traceback / 启动异常

### 6.4 真实 Telegram 端到端回归

**验收标准：** 至少 1 次完整成功路径 + 1 次错误输入路径 + 1 次返回上一步路径

---

## 7. 当前仓库与环境事实（可供接手模型参考）

### 文件路径

- 主要修改文件：
  - `/root/.openclaw/workspace/tmp/OCI-Master-Tool/OCI_Master.py`
- 当前目录中已看到状态文件：
  - `/root/.openclaw/workspace/tmp/OCI-Master-Tool/.telegram_menu_sessions.json`

### 当前已核验状态

- `git status --short` 看到：
  - `M OCI_Master.py`
  - `?? .telegram_menu_sessions.json`
- `python3 -m py_compile OCI_Master.py`：已核验通过
- `oci-master-telegram.service`：已核验 `active (running)`

### 注意事项

- 不要把阶段性口头汇报当作最终事实；修改前后应重新核验代码和运行状态
- 继续遵守“直接改 `OCI_Master.py`，不要另起新模块”的约束
- `.telegram_menu_sessions.json` 可能与 token/state 的持久化有关，继续改状态机时必须留意兼容性

---

## 8. 交付物要求

如果由其他模型继续处理，建议最终至少交付：

1. 修改后的 `OCI_Master.py`
2. 一份简短变更说明（改了哪些 callback / 状态处理）
3. 一份验证报告，至少包含：
   - py_compile 结果
   - 本地轻量验证结果
   - systemd 状态
   - Telegram 端到端回归结果

---

## 9. 一句话总结

这不是从零开始的项目，而是一个**已经完成实例优先主链、短 token 化和快捷按钮第一版**的半收口改造任务。剩余核心工作是：

> 把 Security List 向导的“按钮输入 + 文本输入 + 返回链路 + delete/replace 一致性 + 真机回归”彻底闭环。
