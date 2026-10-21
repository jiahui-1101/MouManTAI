# P1 BATCH 5 handoff — 2026-10-21 (Actual P1 → Core → P2 Integration)

当前分支 `feat/p1-context-intelligence`；本次实现提交：
- 适配器与发布守卫：`a5cb3ac` (`feat(p1): implement CoreIntegrationFacade adapter and context publication eligibility`)
- P5 核心已确认条款保护：`f3c3b7c` (`feat(p5): preserve confirmed commitment terms through proposed amendments`)
- P2 评估器与 Outbox 消费者：`52f90dd` (`feat(p1): connect outbox event dispatching and P2 feasibility evaluator`)
- 宿主应用挂载与前端集成：`d5af49c` (`feat(p1): mount P1 routes in app shell and frontend navigation`)
- 端到端真实数据库集成测试集：`c626326` (`test(p1): add end-to-end P1 Core P2 integration test suite`)

### 1. 核心交付与业务边界规则落实
- **零猜测原则驱动的 CoreContextPublisher (`backend/app/context/core_publisher.py`)**：
  - 发布资格守卫 (`check_eligibility`)：只有当上下文达到 `INFORMATION_READY`、客户身份已建立且非未核实（`LINK_VERIFIED` 或 `SUGGESTED`）、包含有效条目清单 (`requested_items`) 且交期/限定词完整有效时，才允许向 Core 提报。
  - 严格阻断未就绪/冲突数据：凡处于 `INFORMATION_PARTIAL`、`CONFLICT`、`UNRESOLVED`、身份未核实 (`UNVERIFIED`/`AMBIGUOUS`) 或无客户绑定的上下文，直接拦截抛出 `IneligibleContextError`，**绝不静默向 Core 投递未完备或歧义上下文**。
  - 幂等提报与双向指针：成功提报后在 P1 `OrderContextRecord` 记录 `core_commitment_id` 与 `published_to_core_at`，支持依据 `context_id` 进行幂等防重。
- **已确认条款绝不静默覆写 (Preserve Confirmed Terms through Proposed Amendments, Invariant 1 & 6)**：
  - 更新 `CoreIntegrationFacade.handle_context_updated` (`backend/app/core/integration.py`)：当 P1 针对已处于 `CONFIRMED` 协议状态的承诺提交上下文变更且提取条款存在实质差异时，**绝不在原地覆写已确认的承诺条款**。
  - 自动转入提议流程：系统通过 `CommitmentProposalRecord` 创建激活态提议（`AgreementState.OFFERED`），记录完整 `ProposedChanges`，并对外派发 `commitment.proposal_offered` 事件，维持基准履约协议权威性。
- **真实 P2 可行性评估集成与纯函数调用 (`backend/app/context/p2_consumer.py`)**：
  - 严谨订阅 Core 事件：订阅 `commitment.context_ready` 与 `commitment.proposal_offered`。
  - 标准快照解析 (`resolve_snapshot_for_commitment`)：不凭空捏造库存，利用 P2 标准生产样例或只读快照构建 `EvaluationSnapshot`，并将请求/提议变动精准映射为 `ProposedChanges`（数量、交期限定、开始工时）。
  - 调用 P2 官方纯函数：`evaluate(snapshot, proposed_changes, commitment)`，将计算得出的可行性状态 (`FEASIBLE` / `INFEASIBLE` / `CONDITIONAL`)、工作负载工时、瓶颈约束、前提假设与证据溯源写入 `FeasibilityAssessmentRecord`。
  - 幂等消费防线：通过 `ProcessedEventRecord` 登记 `(tenant_id, event_id, consumer_name)`，针对同一事件的重复调度自动跳过无操作，绝不重复触发状态流转。
  - 事务与回滚安全：若评估或下游写入失败，事务安全回退，Outbox 事件状态转入 `FAILED` 并保留 `last_error` 供补偿重试。
  - 陈旧版本防线：利用 `is_stale_event` 与版本单调递增约束，陈旧版本事件（版本号低于当前承诺版本）拒绝覆盖新状态。
- **应用壳层挂载与全局路由集成 (P5 决策 H1.1-Q3 对齐)**：
  - 后端：P1 在 `backend/app/context/__init__.py` 导出 `context_router`；`backend/app/main.py` 由 P5 在 Task T5.2 中统一挂载。
  - 前端：P1 在 `frontend/src/features/context/index.ts` 导出 `<DurableInbox />` 与 `<OrderContextDetail />`；`frontend/src/App.tsx` 由 P5 在 Task T5.2 中统一挂载。
  - Core 条款保护（H1.1-Q1）：P5 确认在 Task T5.2 中直接采纳并合入 `handle_context_updated` 提案逻辑。
  - Alembic 迁移（H1.1-Q2）：P1 保持 `p1_dev` 显式初始化，P5 将在 `0006_recovery_cases` 后统一排期 `0007_order_contexts.py`。
  - 纯净 PR 边界：本 PR 严格仅包含 P1 归属文件（`backend/app/context/`, `frontend/src/features/context/`, `backend/tests/`）。
- **真实 PostgreSQL 端到端 8 场景集成测试矩阵 (`backend/tests/integration/test_p1_core_p2_e2e.py`)**：
  1. `test_scenario_1_new_request_through_p1_to_core_and_p2`：新消息提取成 ready 上下文，提报 Core 创建承诺，派发事件触发 P2 评估并持久化可行性评定。
  2. `test_scenario_2_reviewed_correction_updates_context_and_re_evaluates`：人工修正数量并提报，Core 更新条款并触发 P2 重新计算可行性（120 数量导致产能瓶颈）。
  3. `test_scenario_3_ambiguous_identity_blocks_unsafe_publication`：歧义客户身份被资格守卫严格拦截，阻止产生未受权承诺。
  4. `test_scenario_4_confirmed_term_change_becomes_proposal`：针对已确认的承诺提出数量变更，原承诺条款保持不变，自动生成激活提议并派发提议评估事件。
  5. `test_scenario_5_duplicate_event_causes_no_duplicate_transition`：同一 Outbox 事件被调度两次，幂等消费表拦截重复流转。
  6. `test_scenario_6_old_version_cannot_replace_newer_state`：P1 乐观锁拒绝陈旧版本修正，Outbox 派发器拒绝陈旧版本覆盖。
  7. `test_scenario_7_failure_retry_preserves_consistency`：消费者抛出异常后数据库安全回滚，Outbox 标记为 `FAILED` 可重试。
  8. `test_scenario_8_wrong_tenant_cannot_access_messages_contexts_or_evidence`：跨租户请求完全无法读取异租户消息、上下文或订单。

### 2. 验证结果
- **真实 PostgreSQL E2E 集成测试**：
  - `backend/tests/integration/test_p1_core_p2_e2e.py`：**8 passed in 1.45s**（100% 覆盖 8 大跨域协同场景）。
- **后端全量回归**：
  - P1 领域测试 + Core 跨域集成测试：全量通过。
- **前端全量回归与生产打包**：
  - 前端测试：**149 passed, 5 skipped (LiveApiSmoke), 0 failed**。
  - 前端构建：`npm run build` 成功通过（0 错误）。

---

# P1 BATCH 4 handoff — 2026-10-21 (Attachment Evidence, PDF Text and Image OCR)

当前分支 `feat/p1-context-intelligence`；本次实现提交：
- 阶段 4A（附件存储、安全校验与证据模型）：`c364c07` (`feat(p1): implement tenant-scoped attachment storage and magic byte validation`)
- 阶段 4B（有界 PyMuPDF 机器可读文本提取）：`d5e25a3` (`feat(p1): implement bounded PyMuPDF text extraction with page references`)
- 阶段 4C（PaddleOCR 图像识别与未验证支付防线）：`2937d59` (`feat(p1): implement PaddleOCR image recognition and unverified payment guard`)
- 阶段 4D（前端 AttachmentViewer、OCR 证据展示与收件箱集成）：`ef58ac3` (`feat(p1): implement AttachmentViewer, OCR evidence display, and inbox integration`)

### 1. 核心交付与安全规则落实
- **租户隔离的附件存储与魔数真实性校验 (`p1_dev.attachments`)**：
  - 严格限制支持的文件格式与魔数签名（PDF `%PDF-`、PNG `\x89PNG\r\n\x1a\n`、JPEG `\xff\xd8\xff`），拦截伪装扩展名的恶意文件与非白名单格式（如 `.exe` 返 415）。
  - 最大单附件尺寸硬限制为 10MB（超额返 413 `AttachmentLimitExceeded`）。
  - 路径遍历防御：净化文件名，拦截 `../`、`/`、`\` 等危险路径穿越字符。
  - 租户严格隔离：附件与凭证引用（`evidence_ref`）严格限定在调用租户命名空间下，拒绝客户端控制的文件系统路径，不发起任意远程 URL 拉取。
- **有界且可溯源的 PDF 文本提取 (`PyMuPDF`)**：
  - 页数上限约束：`MAX_PDF_PAGES = 10`，若文档超过 10 页则截取前 10 页处理并置 `status="PARTIAL"` 附加明确诊断信息。
  - 逐页提取文本块，记录页码（1-indexed）与文本块精确外接矩形框（`BoundingBox`，[x0, y0, x1, y1]）。
  - 扫描件与纯文本 PDF 区分：对无文本块的 PDF 自动标识为扫描件/纯图片 PDF。
  - 来源证据边界：文档证据采用 `DocumentEvidence`（包含 `evidence_ref`, `page_number`, `bounding_box`, `quote`, `method="PDF_TEXT"`），与原始消息的字符偏移量（`start`/`end`）严格区分，**绝不为附件捏造消息字符代码点偏移**。
- **真实 PaddleOCR 图像与扫描件文字识别**：
  - 针对 Windows AMD64 运行时与 Paddle 3.3.1 的 oneDNN 兼容性问题，启用 `PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT=False` 消除底层 PIR 异常，平稳运行 `PaddleOCR`。
  - 图像尺寸有界防护：限制最大图像分辨率为 4096×4096 px，防止超大图像耗尽计算资源。
  - 识别行文本、置信度分数（`rec_scores`）与精确像素外接多边形/边界框（`rec_boxes`）。
- **未验证支付截图/水单防线 (Payment Screenshot Guard)**：
  - 关键规则落实：检测银行水单、DuitNow 转账凭据、收据关键词（如 `DuitNow`、`Transfer Successful`、`Bank Slip`、`Amount RM` 等）。
  - 命中时强制设置 `is_payment_notice = True`，所有关联文档证据均标记 `is_payment_evidence = True`。
  - 状态强制为 `UNVERIFIED_EVIDENCE`，并附加法定免责警示：*“Bank slips, transfer receipts, and payment screenshots are strictly unverified evidence. P1 never infers verified payment, identity, or fulfillment from user-uploaded slips.”*
  - **绝不凭借支付截图自动推定已收款、客户身份已确认或订单已履约**。
- **持久化端点与服务 API**：
  - `POST /v1/attachments/upload`：多部分附件上传与魔数校验。
  - `GET /v1/attachments/{evidence_ref}/content`：受权下载与内联预览。
  - `GET /v1/attachments/{evidence_ref}/metadata`：租户范围内元数据检索。
  - `POST /v1/attachments/{evidence_ref}/extract`：执行并持久化 PDF 文本/OCR 提取。
  - `GET /v1/attachments/{evidence_ref}/extraction`：获取已持久化的文档提取结果。
- **前端操作型文档与 OCR 视窗 (`AttachmentViewer`)**：
  - 支持原件受权预览（图像与 PDF 内联预览）及原件下载。
  - 一键执行 `[🔍 Run Extraction / OCR]`。
  - 突出的未验证支付警报条：以醒目红/黄警报框明确提示支付凭证未验证。
  - 提取条款列表：结构化呈现提取到的订单号、交期、商品/数量及来源引用。
  - 识别文本块与 Bounding Box 滚动列表：展示页码、方法、置信度（百分比）与坐标框。
  - 收件箱联动：`DurableInbox` 详情面板集成“Attachments & Document Evidence”卡片列表，支持合成文件上传与一键调出 `AttachmentViewer` 模态弹窗。

### 2. 验证结果
- **后端测试集**：
  - `backend/app/context/tests/test_attachment_storage.py`（4 passed）
  - `backend/app/context/tests/test_pdf_extraction.py`（5 passed）
  - `backend/app/context/tests/test_image_ocr.py`（5 passed）
  - 全量后端回归：**284 passed, 2 skipped, 0 failed**。
- **前端测试集与构建**：
  - `frontend/src/features/context/AttachmentViewer.test.tsx`（4 passed）
  - 全量前端回归：**149 passed, 5 skipped (LiveApiSmoke), 0 failed**。
  - 前端类型校验与构建：`tsc -b && vite build` 成功（0 errors）。

---

# P1 BATCH 3 handoff — 2026-10-21 (Context Lifecycle, Version History and Human Review)

当前分支 `feat/p1-context-intelligence`；本次实现提交：
- 存储与模型：`8c18730` (`feat(p1): implement OrderContext models, optimistic concurrency, and storage in p1_dev`)
- 业务服务与 API 接口：`d38f6c5` (`feat(p1): implement ContextService, review endpoints, message merge, and optimistic locking`)
- 前端审阅抽屉、上下文详情与收件箱联动：`5e73ff0` (`feat(p1): implement OrderContextDetail, ReviewDrawer, and context actions in DurableInbox`)

### 1. 核心交付与业务规则落实
- **OrderContext 独立存储 (`p1_dev.order_contexts`)**：
  - 字段：`context_id`, `tenant_id`, `order_id`, `customer_id`, `customer_identity_status`, `status` (`INFORMATION_READY`, `INFORMATION_PARTIAL`, `CONFLICT`, `UNRESOLVED`), `requested_items`, `requested_delivery_at`, `delivery_qualifier`, `special_instructions`, `missing_fields`, `conflicts`, `source_message_ids`, `field_evidence`, `context_version`, `last_reviewed_by`, `last_reviewed_role`, `created_at`, `updated_at`。
- **全链路不可变快照审计 (`p1_dev.order_context_versions`)**：
  - 每次上下文演进（创建、合并后续消息、人工字段修订、人工接受）均自动沉淀带版本号的不可变版本快照，记录变更类型（`INITIAL_CREATION`, `MESSAGE_MERGE`, `HUMAN_EDIT`, `HUMAN_ACCEPT`）、操作人（`actor_id`/`actor_role`）及理由。
- **后续消息安全合并与冲突检测 (Follow-up Message Merge)**：
  - 后续消息到达同一订单时自动演化现有上下文，但**绝不静默覆盖已有已验证条款**。
  - 若后续消息对已存在字段产生实质性分歧（如 SKU 改变、数量由 50 变为 100、交期改变等），安全转为 `CONFLICT` 状态，将分歧详细记录于 `conflicts` 列表，保留基线数据供人工决策。
- **人工审核与字段修正 (`p1_dev.context_reviews`)**：
  - 审核端点：`POST /v1/contexts/{context_id}/review`（支持 `EDIT_FIELD`, `ACCEPT_EXTRACTION`, `REQUEST_MORE_INFO`, `MARK_UNRESOLVED` 操作）及 `PATCH /v1/contexts/{context_id}`。
  - 完整记录经办人身份（`X-Actor-ID`）、角色（`X-Actor-Role`）、审核说明（`note`）、具体字段差异对照（`field_changes`）及前后版本号跳变（`context_version_before` → `context_version_after`）。
- **数据库级与 API 级乐观并发控制 (Optimistic Concurrency)**：
  - 审核与修改操作必须携带 `expected_context_version`；
  - 借助数据库行级锁与版本对比校验，陈旧请求直接返回 HTTP 409 Conflict（`StaleContextVersion`），杜绝多人并发审核时的覆盖与状态脏写。
- **RESTful API 清单**：
  - `GET /v1/contexts/{context_id}`：获取上下文详情。
  - `GET /v1/contexts/by-order/{order_id}`：根据订单号获取上下文。
  - `POST /v1/contexts/from-message/{message_id}`：由消息自动触发提取、关联与上下文生成/合并。
  - `POST /v1/contexts/{context_id}/review`：人工提交审核决定或字段修订。
  - `PATCH /v1/contexts/{context_id}`：人工直接编辑上下文。
  - `GET /v1/contexts/{context_id}/versions`：获取该上下文的所有历史版本快照。
  - `GET /v1/contexts/{context_id}/reviews`：获取该上下文的人工审核历史记录。
- **前端操作型界面**：
  - `ReviewDrawer` (FE-02)：提供抽屉式交互，支持直接修正 SKU、数量、单位、交期/限定词、特殊指示，并附带审阅笔记和四种标准决断操作。
  - `OrderContextDetail` (FE-03)：展示商品明细表格、原文 Unicode 代码点证据引用片段、维度卡片、安全冲突警告条、字段缺失警告条，以及可展开的历史版本与人工审核时间线。
  - `DurableInbox` 消息详情操作联动：对于 `PROCESSED` 消息，提供一键打开 `[📋 Generate / View Order Context]` 弹窗，直观查看与审阅上下文。

### 2. 验证结果
- **后端测试**：
  - `backend/app/context/tests/test_order_context_storage.py`（4 个存储与并发单测全部通过）。
  - `backend/app/context/tests/test_context_api.py`（3 个端到端 API 单测全部通过）。
  - P1 后端测试集：**280 passed, 2 skipped, 0 failed**。
- **前端测试与打包**：
  - `frontend/src/features/context/OrderContextDetail.test.tsx`（6 个组件与交互单测全部通过）。
  - 前端测试集：**135 passed, 5 skipped (LiveApiSmoke), 0 failed**。
  - 前端类型校验与构建：`tsc -b && vite build` 成功（0 错误，耗时 1.35s）。

---

# P1 BATCH 2 handoff — 2026-10-21 (Verified Identity and Order Association)

当前分支 `feat/p1-context-intelligence`；本次实现提交：
- 模型、合成客户/订单目录与存储：`4457c75` (`feat(p1): implement identity association models, synthetic directory, and storage`)
- 关联服务与 API 接口：`5f1bc10` (`feat(p1): add association API endpoints with actor tracking and optimistic concurrency`)
- 前端关联面板 UI 与组件单测：`d351cbe` (`feat(p1): add identity and order association panel to DurableInbox UI`)

### 1. 核心交付与安全规则落实
- **身份边界分离**：严格区分平台标识（PlatformIdentity，如手机号/channel）、客户主数据（CustomerAccount）、已验证绑定（Verified Link）与推测候选（Suggested Match）。
- **零猜测防篡改底线**：
  - 绝不凭发件人名字相似度（name similarity）或模型输出自动绑定客户身份。
  - 提取出的订单号引用（如 `ORD-1001`）**单独绝不是授权凭据**：陌生人发送合法订单号仅作为候选记录（`LINK_CANDIDATE`），强制人工授权。
  - 跨客户订单引用安全冲突拦截：已验证客户引用属于其他客户的订单时，立即触发并持久化 `SECURITY CONFLICT` 警报（`CONFLICT` 状态）。
  - 绝不擅自决策：同一客户存在多个进行中订单且消息未指明单号时，绝不随机选取，全量列出候选订单及判定依据。
- **持久化与审计 (`p1_dev.message_associations`)**：
  - 存储：`association_id`, `tenant_id`, `message_id`, `status`, `verified_customer`, `verified_order`, `candidates`, `conflicts`, `last_decision`, `version`, `updated_at`。
  - 人工决断接口：`POST /v1/messages/{id}/association`，完整持久化决策（`CONFIRMED`/`REJECTED`）、经办人（actor_id）、角色（actor_role）、时间戳、证据与理由。
  - 乐观并发保护：请求必须携带 `expected_version`，并发陈旧请求直接安全返回 `409 Conflict`，杜绝覆盖。
- **前端关联面板 (`DurableInbox`)**：
  - 展现已验证身份 vs 推测身份状态徽标与版本。
  - 候选卡片列表呈现匹配类型（`TRUSTED_SENDER`, `EXTRACTED_ORDER_REF`）、置信度与详细理由。
  - 一键确认（`✓ Confirm link`）与拒绝（`✗ Reject / Unlink`）操作，带防重与错误恢复机制。
  - 审计回溯卡片：清晰展示最后一次裁决的操作人、角色、时间与原因。

### 2. 验证结果
- **后端测试**：
  - 新增 `backend/app/context/tests/test_association_models_and_storage.py`（7 个端到端与安全隔离单测全部通过）。
  - 覆盖已验证关联、未知发件人防冒充、多订单候选消歧、跨租户与跨客户订单冲突、人工裁决防重及乐观锁（409）。
  - P1 后端全量测试集：**303 passed, 0 failed**。
- **前端测试与打包**：
  - `DurableInbox.test.tsx` 新增端到端关联与裁决测试（10 个用例全部通过）。
  - 前端全量测试集：**129 passed, 5 skipped (LiveApiSmoke), 0 failed**。
  - 前端类型校验与构建：`tsc -b && vite build` 成功（0 错误，耗时 1.62s）。

---

# P1 TASK 2C handoff — 2026-10-21

当前分支 `feat/p1-context-intelligence`；本次实现提交：
- 后端：`2dcab66` (`feat(p1): persist deterministic extraction and implement processing API`)
- 前端：`1527f8e` (`feat(p1): integrate extraction processing and evidence highlights in DurableInbox`)
- 证据校验与失败重试：`9eb0c4c` (`feat(p1): validate source evidence spans before persistence and add failed attempt test`)

### 1. 核心交付与实现内容
- **持久化抽取存储 (`p1_dev.extraction_attempts`)**：
  - 新增字段：`attempt_id`, `tenant_id`, `message_id`, `extractor_version`, `input_content_sha256`, `status`, `fields` (JSONB), `diagnostic`, `started_at`, `completed_at`。
  - 行级锁与并发保护：`process(tenant_id, message_id, reprocess=False)` 使用 `with_for_update()` 避免同一消息被并发重复处理（并发返回 409 `ProcessingConflict`）。
  - 幂等性保证：同一输入与相同抽取版本默认复用已有 Attempt，不重复计算；显式 `reprocess=True` 时创建新 Attempt 并完整保留历史版本审计追踪。
  - 证据强校验：入库前逐一校验 `evidence.start`/`evidence.end` 并在不可变消息文本上验证实际切片内容等于 `evidence.quote`，失配或越界将安全转入 `PROCESSING_FAILED` 并记录 diagnostic。
- **处理与检索 API**：
  - `POST /v1/messages/{message_id}/process?reprocess={true|false}`：触发抽取并持久化结果与状态。
  - `GET /v1/messages/{message_id}/extraction`：获取最新一次抽取结果及字段（404 若未处理或消息不存在）。
  - `GET /v1/messages/{message_id}/attempts`：获取消息的所有历史抽取记录（按 `started_at DESC` 排序）。
  - 错误与脱敏：严格保留 503 `PersistenceUnavailable` 数据库连接串脱敏逻辑；提供明确的 404 及 409 ApiError 规范。
- **操作型前端界面 (`DurableInbox`)**：
  - 接入真实后端 API (`process`, `getExtraction`, `listAttempts`)。
  - 消息列表支持直接触发 Process，消息详情支持触发 Process / Reprocess。
  - 证据精准高亮：基于 `Array.from(text)` Unicode 代码点切片，通过 `<mark className="p1-span-highlight">` 渲染精确源文本证据高亮。
  - 明确标注来源与版本：显示 `RULE (p1-deterministic-v3)`，清晰展示提取字段表格（字段、值、状态、限定词、原文片段引用）。
  - 审计历史：详情面板展示完整的历史抽取尝试时间与状态列表。
- **契约安全边界 (Contract Safety)**：
  - 候选抽取（Candidate Extraction）只保存在 P1 的暂存表与消息记录中，**绝不自动提权至共享 Core `BusinessContext`**，亦不将状态置为 `CONFIRMED` 或假定 `READY`。

### 2. 验证结果
- **后端测试**：
  - 新增 `backend/app/context/tests/test_persisted_extraction.py`（8 个端到端持久化与并发测试全部通过）。
  - 包含 engine 重启后持久化完备性、幂等性、reprocess 历史保留、多线程并发锁保护、跨租户隔离、抽取失败记录与安全重试、API 404/409 边界测试。
  - P1 测试集全绿（296 passed / 0 failed, 1 Starlette warning）。
- **前端测试与构建**：
  - `DurableInbox.test.tsx` 扩充 9 个端到端用例，覆盖处理、重新处理、代码点高亮与历史列表呈现。
  - 前端全量测试：128 passed, 5 skipped (LiveApiSmoke), 0 failed。
  - 前端类型与打包：`tsc -b && vite build` 成功（0 错误，耗时 1.05s）。

---

# P1 TASK 2B-FIX handoff — 2026-10-21

- 修复：lower bounds/近似/区间/试探不变 EXACT；独立多表达式和跨句 date/time 不取第一项或拼接；缺失时区不补默认；yearless 日期不补年份；DST gap/fold 不自动定 offset；相对日期按 message_at（否则 received_at）而非处理时钟；延迟接收、过去日期保持复核；非法 time token 不截断或回退 DATE_ONLY；SKU/unit 别名歧义不标 VALID。
- 原文、hash 和 message metadata 不变；source spans 为 Unicode code points。DATE_ONLY 仍为日期字符串，没有午夜；DATE_ONLY 的原 EXACT/DEADLINE relation 保留在 metadata。
- 当前策略只覆盖声明支持的窄语法。没有 trusted tenant default；显式 envelope timezone 仅是声明来源。旧数据隐式默认被持久化后的 provenance 和 retry fingerprint 兼容性仍需独立检查；不静默迁移旧记录。
- 最终检查：focused 139 passed / 0 skipped；加载本地 P1 PostgreSQL 测试配置后，P1 + P5 后端 295 passed / 0 skipped（13.95s，1 个既有 Starlette/httpx warning）。没有前端改动，所以未重跑前端或浏览器；没有模型 benchmark。P5 既有测试 fixture 使用 SQLite，未新增该基础设施，也不等同 P5 PostgreSQL 部署验证。
- 提交：`fcee8cc`、`5d70f91`、`9e492f5`、`9c6a1ed`、`a8b78a8`、`601c04f`。每组必要测试通过后独立提交；命令、复现样本及各阶段结果见 [验证记录](P1_02B_FIX_VALIDATION.md)。
- 实际 P5 `backend/app/core/schemas.py` 未改：DATE_ONLY 不接受为 datetime，qualifier 不接受；PARTIAL/AMBIGUOUS 不可直接传入；现有 READY alias 会归一化为 INFORMATION_READY，但本次没有批准新的完整性/身份 gate。requested_items 至少一项也限制无商品的 partial context。
- 可继续考虑 TASK 2C 的有界 provisional persistence 设计，**不能据此直接发布完整 P5 BusinessContext/自动 READY**。接入前需 P5/受影响 owner 确认日期、限定词、readiness 和 identity 映射，以及 source/freshness/legacy data policy。本次没有实现或更改共享契约。
- 文档由本次显式任务要求更新；只作本地提交。无未完成或未提交的实现代码；本地样本输出在忽略的 `.local/p1-task2b-safety-evidence.json`。

## Historical TASK 2A handoff (保留历史，不代表当前分支已 push)

- Working branch: `feat/p1-context-intelligence`; verified starting AI spike commit `d5dfd62`, clean worktree. Local implementation commit: `42087a8`.
- `extract_explicit_fields(StoredMessage, catalog=...)` returns existing ExtractionResult/ExtractedField/FieldEvidence types. No ingestion/API/UI/DB integration or BusinessContext readiness change.
- Supports literal `ORD-<digits>` / `synthetic_order_<alphanumeric>` references (UNRESOLVED, never an authorized order link), exact English burger/burgers aliases, and a single immediately preceding positive ASCII integer count, optionally pcs/pieces. Catalog is supplied explicitly, tenant filtered; PROVISIONAL_PRODUCTS mirrors the existing synthetic BURGER/pcs fixtures, not an approved SKU registry.
- No implicit units. Explicit unsupported units, signs, fractions or nonpositive counts are not VALID. Product lists, alternatives, repeated product mentions, negation, additional numbers and non-prefix counts defer quantity association. Unknown products stay unresolved. No arbitrary multi-item pairing.
- Evidence preserves message ID, exact original quote, method RULE/version p1-explicit-v1, [start,end) Unicode code-point offsets; emoji example tested. Stored text and all original persisted message metadata remain unchanged.
- Exact validation: `.venv/Scripts/python.exe -m pytest backend/app/context/tests/test_deterministic_extraction.py backend/app/context/tests/test_schemas.py backend/app/context/tests/test_fixtures.py -q` => **67 passed**, including 25 new extraction cases, one existing Starlette/httpx deprecation warning. `git diff --check` passed. Models, frontend builds and unrelated DB checks were not rerun for this opt-in backend-only function.
- No production dependency on experiment runner/evaluation data, no dependency upgrades. No incomplete implementation files. Documents/report history retained locally; user authorizes push of code only, excluding new docs/README/generated observations. Clean publication history and final remote hash recorded below after publishing.
- Remaining: approved SKU/alias catalog and order-reference grammar, item association beyond this narrow subset, date normalization, persistent extraction/version/review handling. Next task: finish P1-02 normalization/date handling, persist results, connect processing API/UI in separate bounded increments. No next package started.

Publication completed: `feat/p1-context-intelligence` local HEAD and GitHub remote both verified as `aa0bbbfa3413e09534e7db58f1a764c4ed3b3de8`. This is the published implementation hash corresponding to original `42087a8`. All P1 source/test changes were preserved exactly. Previous AI code/test commits also published; new docs/README/generated observations excluded from every published commit. No force-push or merge.

Complete original local history, reports and local documentation commit `3f99ebd` retained at `archive/p1-task2a-with-docs-20261021`. This handoff, spike REPORT.md and observations.json are local-only via .git/info/exclude. Publication rechecks: focused extraction/schema/fixtures 67 passed; isolated spike code unit tests 20 passed (no model benchmark). Worktree has no pending code changes; local-only handoff updates intentionally uncommitted. Next work remains as stated above; stop here.
