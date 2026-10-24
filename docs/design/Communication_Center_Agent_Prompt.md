# Agent Prompt：Communication Center（生产版）

## 任务
把 `communication-center.html` 接入 Orbyte / MouManTAI 前端并上线。页面**所有功能都已实现**，由后端数据和权限驱动。**不要加任何 mock、synthetic、example 数据或标签。**没有数据时显示 `Not available`（加原因 + Try again）；数据一到，所有功能完整可用。

## 页面职责
Communication Center 管理对外沟通：草稿、审批、发送、发送记录、客户确认、Follow-Up、收件人偏好。FAQ 知识库维护在 Settings / Business Knowledge；FAQ 回复只是 `purpose = FAQ` 的 outbound message，出现在 Sending History。Inbox 负责识别与澄清，Human Review 负责人工介入。

## 布局
1. 页头：标题、Refresh、+ New draft。
2. 能力横幅：仅当 `/capabilities` 返回受限或失败时显示，写明原因。
3. 4 张 KPI 卡：Messages / Awaiting approval / Sent / Needs attention。
4. 左侧分组导航（每项有数量和一句话说明用途）：
   - **Work**：Needs action（默认）、Drafts & Approvals
   - **Track**：Sending History、Customer Confirmations、Follow-Up Queue
   - **Manage**：Recipient Preferences、Communication Requests
5. 中间：Needs action 用 Approve / Fix delivery / Review replies / Follow up 过滤；其他区用搜索 + 状态过滤 + 可排序表 + 分页。
6. 右侧详情面板：选中行后出现，含状态、四个独立状态格、操作按钮。

## 功能（全部已在原型实现）
- **Messages**：Preview；按状态显示 Edit draft / Validate / Request approval / Approve / Reject / Send / Retry send / Check provider status。
- **New draft**：收件人只列已验证且已授权者；渠道只列其允许渠道；AMENDMENT 绑定提案版本。
- **Customer Confirmations**：显示五种回应（ACCEPT/REJECT/COUNTEROFFER/CLARIFICATION/UNKNOWN）；Link to proposal version、Send to Human Review。
- **Follow-Up Queue**：Send reminder、Escalate to Human Review、Cancel follow-up、Mark expired；显示已发次数/上限、上次、下次到期、允许时段、升级原因。
- **Recipient Preferences**：偏好渠道、退订提醒、保存。

## 按钮规则（安全）
- 按钮是否可用**只读后端**：`allowed_actions[verb] === true`。否则置灰，旁边显示 `blocked_reasons[verb]`。前端不推断权限，也不推断“有没有进展”“订单是否可接受”。
- 点击后等待后端响应，成功才刷新并提示；失败在面板显示后端原因。**不做乐观成功。**
- `DELIVERY_UNKNOWN` 不显示重发，只有 Check provider status。发送失败、等待回复都不算“无进展”。
- 四个状态永不合并：Message sent / Terms accepted / Action completed / Fulfilled（只读核心服务）。“OK” 类含糊回复不算接受。
- 不写死任何时限数字，全部显示后端返回的值。
- 不做：订单 Accept/Reject、Proposal 条款编辑（只提供跳转链接）。

## 数据接口（需后端确认路径，集中在 HTML 的 `EP` 常量，`window.COMM_API_BASE` 默认 `/api/communication`）
GET：`/messages` `/confirmations` `/followups` `/recipients` `/capabilities`（返回数组或 `{items:[]}`）
POST：`/messages`，`/messages/{id}/{validate|request_approval|approve|reject|send|retry|check_status}`，`/confirmations/{id}/{link|review}`，`/followups/{id}/{remind|escalate|cancel|expire}`；PUT：`/recipients/{id}`

字段（snake_case）：
- message：`id purpose status recipient channel simulated updated_at source inquiry body approval terms_state action_state fulfilment_state failure_reason allowed_actions blocked_reasons`
- confirmation：`id proposal version response note received_at resolved allowed_actions blocked_reasons`
- followup：`id proposal recipient position reminders_sent reminders_max last_reminder_at next_due_at due window escalation_reason allowed_actions blocked_reasons`
- recipient：`id name contact channel channels preferred consent verified opted_out capability allowed_actions blocked_reasons`
- capabilities：`organization blocked reason can_draft draft_reason`
- `simulated: true` 仅在后端明确标记模拟渠道时才显示 “simulated”（规范要求），前端不自行添加。

## 验收清单
- [ ] 无数据时每区显示 Not available + 原因 + Try again；零条数据显示 Nothing here yet
- [ ] 后端返回数据后，所有操作按 `allowed_actions` 启用，无需改前端
- [ ] 置灰按钮旁有后端原因
- [ ] 无任何 mock / synthetic / example 文案
- [ ] 与现有 Orbyte 组件、token 一致；桌面、移动、深色可用

## 待向后端确认
1. 以上接口路径和字段名。
2. `UNRESOLVED` 与 AMBIGUOUS / CONFLICTING 的映射。
3. CLARIFICATION 是否需要员工批准（由 `allowed_actions` 体现）。
