# Agent Prompt：Human Review（队列表格 + 整页 Review & Amend）

## 任务
把 Human Review 改成两页结构，设计与 `human-review.html` 完全一致。沿用 Orbyte / MouManTAI 现有组件和 token，不新建样式体系；**不用抽屉、侧滑面板或弹窗承载审核页**。没有数据显示 `Not available`；不得出现 mock 文案。只改前端实现与 API 集成，不改后端业务规则。**目标是最终可用的真实端到端流程，不是 UI 假演示**：先审查现有路由、组件、API client、types、backend contract 和 capability gates；已有后端能力必须真实接入并测试；缺失能力仍要完成可实现的前端结构、loading/error/disabled 状态，并输出准确的后端 API 需求清单交给 Backend Owner（路径仅作为建议，不可假定已存在）。不得添加 mock 成功、浏览器内模拟权限、假记录、前端自建 follow-up timer 或绕过服务端验证。所有按钮是否可用只读后端返回的 `allowed_actions`/capabilities 及原因，前端不推断进展、权限或订单是否可接受。**保留现有完成的布局、样式和交互，仅针对下面明确列出的差距调整。**

## 路由
- 队列：`/inbox/human-review`（进入即显示整宽表格，不默认选中任何任务）
- 审核页：`/inbox/human-review/{taskId}`（整页）；左上返回箭头回队列，浏览器返回键有效。
- 侧边栏保持 Inbox → Human Review 高亮。
- Inbox → Customer Messages 的 Amend 可以复用同一 Review Detail 内容和组件，但应保留当前 Inbox 的入口/返回上下文；Human Review 的路由仍必须是独立整页，不能因为共享组件而变成 modal。
- 从审核页到 Communication Center / Follow-Up Queue / Order / Customer Message 的导航保留稳定的 context、message、issue、draft、communication、order 标识；只使用已存在并校验过的真实路由和对象 ID，找不到对象不跳到错误的通用页面。

## 页 1：队列
1. 页头：圆形图标 + “Human Review” + 副标题 “Review customer inquiries, unverified model candidates and context conflicts with full audit protection.”；右侧 Refresh。
2. 4 张 KPI 卡：Open tasks / Immediate attention / Failed extractions / Identity unverified。
3. 胶囊过滤：All inquiries (n) / Failed extractions (n) / Pending / unprocessed (n)。
4. 过滤卡：Search、Task type、Channel、Assigned to（Everyone / Me / Unassigned）、Reset。
5. 表格列：Received（可排序）、Customer and message（名字加粗 + 渠道徽章 + 一行预览，最多 90 字符）、**Task type**、Status（Processing 徽章 + 身份未验证徽章）、Priority（可排序，High 红色）、Assigned、**Review 按钮（主色）**。整行可点击，也支持 Tab 聚焦后按 Enter。
6. 底部：Showing x to y of z entries、Rows per page、分页。
7. 空状态：“No review tasks / Tasks appear here when a message needs a person.”

**Task type 必须显示，因为审核员要靠它选方案。** 12 类：No progress after 2 follow-ups / Follow-up limit reached / No reply after reminder / Identity or order link unclear / Field conflict / Commercial risk inquiry / Knowledge gap or private data / Processing failed / Ambiguous customer reply / Reply unavailable / Supplier or customer unknown / Low-confidence extraction。

## 页 2：Review & Amend（整页，从上到下，顺序不可改）
1. **页头**：返回箭头 + 标题 “Review & Amend” + 信息状态徽章（如 INFORMATION_PARTIAL）+ 版本徽章（如 v1）；副标题为渠道 · 接收时间 · Context ID；**右上角 “More actions ⋯” 菜单**：↻ Reprocess extraction、Forward for manager review、Mark unresolved、Open customer message。
2. **四个状态格**：Processing / Information / Identity / Review。
3. **任务横幅**（浅蓝、左侧蓝色竖线）：任务类型 + 原因；High 优先级加红色 “Immediate attention” 徽章；小字 “What you can do: …” 列出该类型可用的审核员动作。
4. **红色提示条**：“Information needs review  N missing · N conflicts” + Missing 字段列表。
5. **未保存提示条**（仅在有修改并点返回时出现）：“Unsaved review changes will be lost.” + Keep editing / Discard and close。
6. **四个下划线 Tab**：Review & Amend（默认）/ Customer reply / Identity & order / History & audit。
7. **固定底栏**（仅 Review & Amend Tab）：左侧 “No field changes yet” 或 “N field changes not saved”；右侧 Cancel、Save changes、Save & Accept（无修改时后两者置灰）。**Save & Accept 仅表示接受/确认 extraction review 的修正版本（若后端如此定义），绝不表示接受订单**；如后端语义不明确，先核对 contract，必要时改成准确的 `Save & Confirm Review`/适用文案。

### Tab：Review & Amend
左右两张卡，各自内部滚动（最高约 68vh），窄屏改为上下：
- **左：Original message**。说明 “Select a field to locate its source evidence.”；蓝色提示 “Extraction evidence does not authorize a price, discount or delivery promise.”；原文块（左侧蓝竖线，保留换行），被提取内容黄色高亮；选中字段时对应高亮加蓝色描边并滚动到可见。
- **右：Extracted fields**。说明 “Edit values supported by the original request. Every change needs an audit reason.” 每个字段一张卡：标签（必填加红色 *，重大字段标 “(major field)”）+ 右侧字段状态徽章（VALID 绿 / MISSING、AMBIGUOUS、UNVERIFIED 琥珀 / CONFLICTING、UNSUPPORTED 红；后端有具体原因时显示原因，如 “Missing or invalid offset”）、输入框、提示小字、可折叠 “Evidence (n)”（证据引用 + Locate in message 按钮）、需要时有 Timing qualifier 下拉（Unresolved / Exact / Before / After / Around）。已修改字段左侧显示蓝色竖线；聚焦字段时自动高亮原文证据。身份字段不可直接编辑，只能去 Identity & order 处理。
- **保存**：点 Save changes / Save & Accept 弹确认框，必须填写 **Reason**（写入审计）；若改了重大字段，还要勾选 “I confirm the change to a major field.”。保存追加新版本，保留原值和证据。后端成功后才提示 “Saved. Audit entry recorded.”。在 Human Review 入口必须根据任务类型与真实 allowed_actions 显示独立的 Resolve review / Mark unresolved / Escalate 等审核决策（如后端支持），不得仅用字段保存按钮冒充任务已解决。

### Tab：Customer reply（即 “Send customer update”）
左右两卡：
- **左 Conversation with customer**：每个问题 “已问次数 · 无进展次数”、剩余追问预算；说明 “等待回复和发送失败不算无进展”；身份未验证时提示 “Customer-specific information stays private until linkage is confirmed.”
- **右 Customer update**：Purpose（CLARIFICATION / Commercial reply / Manual reply）、Channel（只列已验证或已授权）、Message 文本框；按钮 **Request more information**（生成追问草稿）、**Preview**、**Request approval**、**Send customer update**（主色）。不可用时在上方显示后端给的原因（如 “Sender identity is unverified. Sending is blocked until identity is verified.”）。发出后的记录在 Communication Center 查看；发送状态按真实服务商状态显示，不能因为生成了文字就显示成已发出。**Customer Reply 留在当前 Tab，不要强制跳到 Follow-Up Queue**；发送、草稿和审批应复用 Communication Center 的已实现 API 与组件，并提供 `View in Communication Center` / `View follow-up` 的上下文入口（仅当有真实关联对象）。

### Customer Reply ↔ Communication Center ↔ Follow-Up Queue（必须真实集成）
- **职责边界**：Customer Reply 用于当前消息的撰写、预览、提交审批和发送；Communication Center 是 draft/approval/sending/history 的真实记录中心；Follow-Up Queue 是需要客户答复的 clarification 等问题的后续追踪。**不是每个回复都进 Follow-Up Queue**（FAQ、纯通知等不应凭前端创建追问）。
- **数据关联**：沿真实后端 ID 显示并保留 `message_id`/`context_id`、`customer_id`（仅验证后）、`order_id`（仅可信关联后）、`issue_id`、`draft_id`、`communication_id`、`follow_up_id`，具体字段名以实际 contract 为准。可以从 detail 跳转到对应 Communication Center 记录及具体 follow-up item；返回后仍保留所选任务与 Tab。不存在关联记录时显示 `Not available` 或解释原因，不生成假的链接。
- **生命周期**：`Draft → Preview/Revalidation → Approval (if required) → Authorized Send → Persisted History → Awaiting Reply (if applicable) → Reminder Due/Sent → Reply/Review/Escalation`。不得仅因点击 Send 就判断发送成功、客户接受或订单完成；**SENT ≠ ACCEPTED ≠ FULFILLED**。发送失败和等待回复均不能算客户无进展；提醒预算与 no-progress 计数全部来自后端的 issue-level 状态。
- **Follow-Up 状态**：按后端真实状态显示 `Awaiting customer reply`、`Reminder due`、`Reminder sent`、`Review/expired`、`Provider send failure`（若 contract 有对应字段）；在 Conversation with customer 展示每个 issue 的尝试次数、剩余预算、最后一次沟通、收到的客户回复和时间线。没有后端字段时显示 `Not available`，不能推算天数/次数/自动提醒。
- **收到答复**：只通过已有的可信 inbound/intake 流程更新原始 issue 或 context，保留 evidence 与 audit；不要凭客户名字相似自动认领身份或订单。来自客户的 clarification/COUNTEROFFER 等若需要人工判断，应通过后端真实 review 状态显示，不能由前端强行标为已解决。
- **安全与失败**：保留 `DRAFT_REVALIDATION_UNAVAILABLE`、`PRODUCTION_AUTH_UNAVAILABLE`、身份未验证、consent 缺失、approval 不可用、provider failure、503 等的真实错误呈现与操作禁用；不可使用 mock credential、synthetic token 或浏览器直连 provider。**可完成真实接入的优先接好；缺少后端时不要删除按钮布局，而要有清晰禁用原因与精确待实现 API 说明。**

### Tab：Identity & order
身份状态徽章；说明 “Name or meaning similarity never verifies identity. Linking needs your confirmation.”；Verified customer、Candidate orders（无则 “None found”）；按钮 Link to Order（必须人工确认并显示候选订单和理由）、Reject / Unlink（红字）、Open customer message；小字 “Accepting or rejecting an order happens only on the order page.”

### Tab：History & audit
时间线（新在上）：谁、何时、为什么、证据。包括消息到达、提取尝试、路由到 Human Review、每次审核员决定。

## 入口差异和 Review 状态
- Inbox Customer Messages → Amend：聚焦 extraction、missing fields、evidence 与 correction；可复用四 Tab，但保留消息上下文和 Inbox 返回入口。
- Human Review → Review：同一详情布局外还必须显示 review task type、priority、reason、assignee、allowed reviewer decisions 和审核完成/升级的真实状态；不同 task type 对应的操作只能来自后端 allowed_actions，不能因界面相同就假定动作相同。
- `Save changes`、`Save & Accept`、`Resolve review`、`Mark unresolved`、`Forward for manager review` 是不同业务意图；是否合并由真实后端 contract 决定。不要以保存字段代表 resolution，更不要以 review acceptance 代表订单接受。
- 每次人工决定都必须保留 actor、time、reason、evidence、previous/new value、version 和 authoritative response；无审计端点时不显示操作成功。

## 交互规则
- **More actions** 三项都弹确认框：Reprocess（可重复执行，不产生重复记录）、Forward for manager review（需备注）、Mark unresolved（需原因，且界面不能显示成已解决）。成功后写入审计。
- 有未保存修改时，返回、关闭页面都要提示。
- 订单进入 Pending Acceptance 后从队列消失，不能两边同时出现。
- **永远不做**：自动接受订单（接受 / 拒绝 / Proposal / 条款差异只在订单页，这里只放跳转链接）；把名字相似当作身份验证；向身份未验证的发件人透露客户专属信息；自动发送没有依据的回答。
- 所有写操作等后端成功后再显示成功；失败显示后端原因。

## 视觉规范
与 Customer Message Detail 一致：页面背景 `#f1f6fe`，卡片白底 1px 浅边框 14px 圆角，主色 `#0a5bd8`，按钮 9px 圆角字重 600，标题 28px；徽章胶囊 12px 字重 700（绿=成功、琥珀=待处理、红=失败或高风险、紫=模型信息、蓝=类别）；证据和 ID 用等宽字体 12px。深色模式全部走 token；≤1150px 左右分栏改上下，≤900px 隐藏侧边栏、底栏贴满宽度、状态格 2 列。Tab 用 `role="tablist"/"tab"`；所有按钮有可见焦点框；表格可横向滚动。

## 数据字段（对照现有接口）
task：`id name source received preview task pri assignee reason options processing info identity review ver meta text missing conflicts fields issues budget allowed why cand audit`
fields[]：`k l v s bad hint major req qual ev[]`；issues[]：`q asked np`；allowed：`request_info preview approval send`。

## 验收清单
- [ ] 进入 Human Review 先看到整宽表格，点击行或 Review 按钮才进审核页
- [ ] 审核页是整页，没有抽屉或遮罩；更多操作在右上角菜单
- [ ] 任务类型和原因在队列和审核页都可见
- [ ] 四个 Tab 内容与上文一致；Send customer update 有且受后端权限控制
- [ ] 每次保存都要审计原因；重大字段要明确确认
- [ ] 订单接受 / 拒绝不出现在本页
- [ ] 无数据显示 Not available；无 mock 文案
- [ ] 深色、移动端、键盘操作可用
- [ ] Inbox Amend 与 Human Review 共享 UI 但各自保留正确路由、返回方式和 reviewer actions
- [ ] Customer Reply 复用实际 Communication Center 的草稿/预览/复核/审批/发送/历史，不会伪造发送结果
- [ ] 有真实 follow-up 关联时可进入对应 Follow-Up Queue item；无关联时不创建假的跟进项目
- [ ] Clarification per-issue 时间线、追问预算、no-progress 及 reminder 仅使用后端真实状态
- [ ] 逐项验证身份/consent/approval/503/revalidation/provider 失败时操作受控且有准确错误提示
- [ ] 核对 `2026-10-28T10:00:00+08:00` ISO8601 offset validation：若确实符合接口格式，修复误报；若是业务校验失败，显示真实原因
- [ ] 输出已接入 API、缺失 API 和对应 request/response、状态及错误码清单；不得将未实现的 backend capability 声称为完成
- [ ] 运行相关 lint/typecheck/tests，简报结果；完成修改后本地 descriptive git commit，**不要 push**

## 实施顺序与交付要求
1. 查现有前端与后端 contract、allowed_actions/capabilities、路由、API clients，不要重复开发已有功能。
2. 保留现有页面排版，将缺少的 context-aware review actions、Communications/Follow-Up 深链、真实状态与 error/disabled handling 补齐。
3. 对已有 API 完成真实请求/响应联调（包括正常与失败路径）；没有可访问的测试环境时明确说明未验证，不得报成 E2E passed。
4. 对不存在或不完整的后端 API 输出 **Backend Action Required**：业务场景、建议 HTTP method/path（标注 proposed）、payload、response、allowed_actions/错误码、相关前端页面及阻塞程度；可以直接发给后端同伴实现。
5. 仅前端范围：**不得在本任务中创建、修改、伪造后端 API 或认证规则**。所有服务端能力完成后可以不改版面直接启用。

## 待向后端确认
1. 字段上的 UNRESOLVED 对应 AMBIGUOUS 还是 CONFLICTING。
2. CLARIFICATION 是否需要员工批准（由 `allowed.approval` 体现）。
3. `allowed` 的完整动作清单和各动作的原因码。

4. Review task resolution、escalation、audit 和 reviewer allowed_actions 的实际写 API、成功后的状态转移。
5. Draft revalidation、approval、authorized sending/history 和真实 auth/consent capability 是否可在部署环境调用。
6. issue-level follow-up/read、reminder/escalation、incoming reply link 的 API 及 ID 关联规则；若缺失，请后端提供可直接实现的接口。
7. Delivery datetime 的 offset 与 timing qualifier 具体格式、validator 规则。
