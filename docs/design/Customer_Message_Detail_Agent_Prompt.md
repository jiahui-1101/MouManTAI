# Agent Prompt：Customer Messages 详情页（整页版）

## 任务
把 Customer Messages 的详情从**右侧抽屉**改成**整页**，设计与 `customer-message-detail.html` 完全一致。只改前端展示，不改后端接口、数据字段和业务规则。使用现有 Orbyte / MouManTAI 的组件和设计 token，不新建样式体系。页面中不得出现 mock、example 文案；没有数据显示 `Not available`。

## 路由
- 列表：`/inbox/customer-messages`
- 详情：`/inbox/customer-messages/{messageId}`（整页，不是抽屉、弹层或侧滑面板）
- 详情页左上角返回箭头回到列表，浏览器返回键同样有效。
- 侧边栏保持 Inbox → Customer Messages 高亮。

## 列表页
- 页头：圆形图标 + 标题 “Customer Messages” + 副标题 “Inspect original messages, extraction evidence and verified identity links.”
- 过滤卡：Search messages、Channel、Reset。
- 表格列：Received at、Original message（发件人加粗 + 一行预览，最多 90 字符）、Source（徽章）、Review。
- 整行可点击，也可键盘 Tab 聚焦后按 Enter 打开详情。
- 无结果显示 “No messages match / Reset the filters.”

## 详情页结构（从上到下，顺序不可改）
1. **页头**：左侧返回按钮（仅箭头，`aria-label="Back to Customer Messages"`）+ 标题 “Original message” + 副标题 “Persisted source · real provider”；**右上角放次按钮 “↻ Reprocess extraction”**（窄屏自动换行到标题下方）。
2. **发件人卡**：圆形头像（发件人首字母，浅红底红字）、名字加 Source 徽章（如 Gmail）、下一行 邮箱 · 接收时间。
3. **四个状态格**（4 列，窄屏 2 列；标签大写小字，值加粗）：Processing / Information / Identity / Review。
4. **两栏布局**：左侧主卡片，右侧固定宽 340px 的 Review summary 卡（卡片窄屏时移到主卡片下方）。

## 主卡片：五个下划线 Tab
Tab 样式同 Notifications & Settings：选中项蓝色文字 + 3px 蓝色下划线。默认打开 **Message**。

| Tab | 内容 |
| --- | --- |
| Message | ① 浅蓝提示框 “Customer reply”（说明本记录不提供询价资格、公开知识或已生成/已发送回复，提取证据不等于授权回答价格、折扣或交付问题）② 标题 “Original message” ③ 原文块：左侧 4px 蓝色竖线、浅底、保留换行；被提取的数值和名称用黄色高亮（`<mark>`） |
| Extraction evidence | ① **Extracted fields 字段表放最前**（Field / Value / Method / Status / Evidence quote），Field 用等宽字体，Value 为空显示 “—” 并附 “Pending review” 徽章，Status 用徽章（UNRESOLVED、MISSING 为琥珀色，ACCEPTED 绿色，REJECTED 红色），Evidence quote 用等宽字体，备注（如 Missing business timezone）显示在下方小字 ② 红色提示条显示模型警告（如 “Manual review required.”）③ “Extraction attempt”：等宽小字 `Attempt {id} · Started … · Completed …`，一行 Decision policy 徽章 + Pipeline version 代码，然后**每个模型一个默认折叠的 `<details>`**（标题左为模型名徽章，右为状态徽章：成功绿色、失败红色；展开后显示 Compute device、Model ID、Latency、Output）④ 折叠项 “Raw model observations and normalization” + 数量徽章 |
| Identity & order | 标题 + 右侧状态徽章（如 UNVERIFIED (v1)）；Verified customer、Verified order；红色文字按钮 “Reject / Unlink”（无关联时置灰） |
| Attachments | 标题 “Attachments & document evidence” + 右侧 “Upload attachment” 按钮；无附件时显示 “No attachments are associated with this message. You can upload a PDF or image to inspect document text and OCR.”；上传接受 PDF 和图片 |
| Technical metadata | 标题 “Envelope & ingestion technical metadata” + 属性数量徽章；Provider ID（等宽）、Source、Received；其余属性按键值对列出 |

关键原则：**重要内容（原文、字段表）默认可见；技术细节（模型、设备、观察）默认折叠。** 每个 Tab 内不超过一屏半。

## Review summary 卡（右侧，桌面端 sticky）
标题 “Review summary”，键值行：Processing、Extracted fields（数量）、Unresolved fields（数量）、Identity、Attachments（数量）。
如有模型警告，显示红色提示 “Manual review required.”
两个纵向按钮，宽度撑满：
1. **Review & Amend**（主色按钮，有字段且不在修改状态时才可点）
2. **View Order Context**（次按钮）：有已验证订单时，跳转到 Orders 模块里该订单的整页详情（`/orders/{orderId}`），不在本页新增 Order Tab；没有已验证订单时置灰，按钮下方小字 “No verified order is linked yet. Link one in Identity & order.”
分隔线下的小字：“The reply above is not an authorisation to answer price, discount or delivery questions.”

## 交互
- **Review & Amend**：切到 Extraction evidence Tab，字段表的 Value 列变成输入框（`aria-label` 为字段名），表格下方右侧出现 Cancel 和 Save amendments。保存后退出修改状态并提示 “Amendments saved.”。保存必须调用后端，**成功后才**显示提示和更新值，失败显示后端原因。
- **Reprocess extraction**：弹确认框 “A new extraction attempt will run on this message. Current evidence is kept.”，确认后才调用后端。
- **Reject / Unlink**：弹确认框 “The identity and order association will be removed.”，确认后才调用。
- **Upload attachment**：打开文件选择，成功上传后刷新附件列表。
- 弹框：标题、说明、右下角 Cancel + Confirm（主色）。
- 提示条（toast）：右下角，约 3.5 秒消失，`role="status"`。

## 视觉规范
- 页面背景浅蓝（`#f1f6fe`），卡片白底、1px 浅边框、14px 圆角；主色蓝 `#0a5bd8`；按钮 9px 圆角、字重 600。
- 标题 28px、字重 600；字体沿用 Orbyte（Public Sans / 系统无衬线）；代码和证据用等宽字体 12px。
- 徽章：圆角胶囊、12px、字重 700；颜色语义固定：绿=成功/已接受，琥珀=待处理/未解析/缺失，红=失败/拒绝，紫=模型或策略信息，蓝=类别。
- 深色模式：所有颜色走 token，深色下重新定义；原文高亮保持黄色底深色字。
- 响应式：≤1150px 摘要卡移到下方并取消 sticky；≤800px 隐藏侧边栏、状态格 2 列、过滤卡单列。
- 无障碍：所有按钮有可见焦点框；Tab 使用 `role="tablist"` / `role="tab"` / `aria-selected`；表格可横向滚动不撑破页面；尊重 `prefers-reduced-motion`。

## 数据字段（后端返回，字段名需与现有接口对照）
message：`id name email source provider received text processing info identity review reply fields attempt customer order assoc attachments meta`
fields[]：`f v m s q n`（字段、值、方法、状态、证据引用、备注）
attempt：`id start end policy pipe models[] obs warn`；models[]：`n ok t dev id lat note`

## 验收清单
- [ ] 详情是整页，没有抽屉、侧滑或遮罩
- [ ] 顶部四个状态格一眼可见，不需要滚动
- [ ] 五个 Tab 内容与上表一致，字段表在 Extraction evidence 最前
- [ ] 模型、设备、观察默认折叠
- [ ] 右侧 Review summary 在桌面端固定，窄屏移到下方
- [ ] Reprocess extraction 在右上角，Review summary 只有两个按钮；View Order Context 无订单时置灰并显示原因，有订单时跳转 Orders 详情页；其余按钮的启用 / 置灰规则正确，破坏性操作有确认框
- [ ] 保存、重处理、解除关联、上传都等后端成功后才提示成功
- [ ] 无数据显示 Not available；无 mock 文案
- [ ] 深色模式、移动端、键盘操作可用
