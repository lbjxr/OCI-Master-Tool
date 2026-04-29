# OCI Master 当前功能清单（2026-04-29）

这份清单用于说明：
- **当前新版本已经迁移完成的功能**
- **旧版仍未迁移的功能**
- **当前明确保持不做 / 暂缓的边界**

项目位置：`/root/.openclaw/workspace/uploads/oci-master`
旧版参考：`/root/.openclaw/workspace/tmp/projects/OCI-Master-Tool`

---

## 一、当前已迁移完成的功能

### 1. 基础账号与账单
- 当前用户详细信息
- 本月费用账单导出 / Telegram 展示
- 密码策略看板
- 创建/修复永不过期安全策略
- 删除冗余密码策略

### 2. 实例管理
- 列出实例
- 查看实例详情
- 启动实例
- 停止实例
- 重启实例
- Telegram 实例列表分页
- Telegram 实例详情按钮流
- 动作回执与状态展示

### 3. 网络 / 安全（当前主线）
- 查看实例网络 / 安全概览
- 查看更多网络对象明细（分页/分段）
- 查看现有入站规则
- 查看本工具临时规则
- 放行临时入站规则（预览 -> 确认 -> 执行）
- 清理临时规则（预览 -> 确认 -> 执行）
- 自定义端口输入（单个合法 TCP 端口）
- 自定义 CIDR 输入
- 临时规则删除结果页返回并刷新

### 4. 网络 / 安全当前已具备的 Telegram 体验
- `🌐 网络/安全` 入口
- `🛡️ 查看现有规则`
- `🧪 临时规则管理`
- `🔓 放行临时端口`
- `🧹 清理临时规则`
- `🔎 查看更多明细`
- 规则列表分页
- 临时规则页内多选、统一预览、统一确认删除
- 规则列表紧凑展示（重点看协议 / 端口 / 来源 / 临时标记）

### 5. Region / Bucket / Audit
- Region subscriptions
  - CLI
  - `run region_subscriptions`
  - Telegram `/regions` `/region_subscriptions`
  - 主菜单按钮 `Region`
- Bucket / Object Storage 基础信息（只读）
  - CLI
  - `run bucket_info`
  - Telegram `/bucket_info`
  - 主菜单按钮 `Bucket`
- Audit Events（只读）
  - CLI
  - `run audit_events[:N]`
  - Telegram `/audit_events [N]`
  - 主菜单按钮 `Audit`

### 6. CLI / run action / Telegram 三套入口
当前大多数主功能都已接上：
- CLI 主菜单
- `run <action>`
- Telegram 命令与按钮流

---

## 二、当前项目已明确建立的边界

### 网络 / 安全部分当前**只做**
- 主 VNIC 关联对象优先
- ingress 规则
- 单个 TCP 端口
- 临时规则
- 预览后确认
- 本工具临时规则的低风险清理

### 当前**没有做 / 暂不做**
- UDP
- 端口范围（如 10000-20000）
- 多端口一键提交
- egress 管理主线
- 路由表改动
- 子网结构改动
- IPv6 改造
- 附属 VNIC 改造
- 任意长期规则随意编辑
- 任意普通规则批量删除

---

## 三、旧版仍未迁移的主要功能

以下是从旧版梳理后，当前**还没有正式迁进来**、或者**只迁了一部分思路**的功能。

### A. Security List / 网络规则更自由的编辑能力
旧版有这些能力，但当前新版本没有完整迁入：
- `add_security_list_egress_rule`
- `remove_security_list_egress_rule`
- `replace_security_list_ingress_rule`
- `replace_security_list_egress_rule`

说明：
- 这些属于更自由的网络规则编辑
- 风险明显高于当前“临时规则放行 / 清理”主线
- 目前是**故意未迁移**，不是忘了

### B. Security List 候选目标选择
旧版有：
- `_list_security_list_candidates`
- `render_security_list_candidates_telegram`

当前状态：
- 新版本主要还是自动选择主 VNIC 关联目标
- 没把“候选安全列表/目标对象手动选择”完整迁出来

### C. 更完整的实例候选 / 实例信息风格
旧版有：
- `render_instance_candidates_telegram`
- `render_instance_info_telegram`

当前状态：
- 新版实例主线已经可用
- 但旧版某些更细的候选展示风格还没专门回迁

### D. Object Storage 更深层功能
当前仅迁了 Bucket/Object Storage 基础信息（只读）
未迁内容包括：
- object 列表子视图
- 更深的对象级查看
- 更复杂的对象筛选/浏览

### E. Audit Events 更细粒度功能
当前只做了：
- 最近事件查看
- 基础字段展示

未迁内容包括：
- 更复杂的 filter / sort 入口
- 更丰富的审计字段折叠/分页

---

## 四、当前建议的后续优先级

如果后续还要继续迁移，建议优先级如下：

### 第一优先级（低风险、独立、值钱）
1. Audit Events 增加 filter / sort 参数入口
2. Bucket / Object Storage 增加 object 列表子视图（只读）
3. Security List 候选目标选择（更明确当前改的是哪个对象）

### 第二优先级（中等风险）
4. 更细的 Security List / NSG 查看与选择式管理
5. 更完整的实例候选 / 信息风格回迁

### 第三优先级（高风险，不建议现在做）
6. egress 主线编辑
7. 规则替换能力
8. 路由 / 子网 / IPv6 / 附属 VNIC 等结构级改动

---

## 五、当前建议的验收入口

### Telegram
- `/user_info`
- `/usage_fee`
- `/policies`
- `/instances`
- `/instance_network <实例>`
- `/instance_rules <实例>`
- `/instance_temp_rules <实例>`
- `/netsec_open <实例> <端口> <CIDR>`
- `/netsec_close_temp <实例> <端口> <CIDR>`
- `/regions`
- `/bucket_info`
- `/audit_events 5`

### CLI / run
- `./run_oci_master.sh run user_info`
- `./run_oci_master.sh run usage_fee`
- `./run_oci_master.sh run policies`
- `./run_oci_master.sh run list_instances`
- `./run_oci_master.sh run instance_detail:<实例>`
- `./run_oci_master.sh run instance_network:<实例>`
- `./run_oci_master.sh run instance_rules:<实例>`
- `./run_oci_master.sh run instance_temp_rules:<实例>`
- `./run_oci_master.sh run open_ingress_preview:<实例>:<端口>:<CIDR>`
- `./run_oci_master.sh run cleanup_temp_rules_preview:<实例>:<端口>:<CIDR>`
- `./run_oci_master.sh run region_subscriptions`
- `./run_oci_master.sh run bucket_info`
- `./run_oci_master.sh run audit_events:5`

---

## 六、一句话结论

当前这版 `oci-master` 已经完成从“单文件小脚本”到“可用的 OCI Telegram/CLI 运维控制台”的第一阶段迁移：
- **实例主线**已可用
- **网络 / 安全主线**已可用
- **Region / Bucket / Audit** 已补上基础查看
- 高风险网络结构能力仍然故意未放开

后续若继续演进，应优先做：
- 低风险只读扩展
- 更明确的目标对象选择
- 更细的审计 / 对象列表体验
而不是贸然扩到高风险网络结构编辑。
