> LEGACY v1 compatibility reference. Current target: [v2.2 System](../REQUIREMENTS_SYSTEM.md).

# MouManTAI — System Requirements & Integration Contract

> **版本**：1.0 · **冻结日期**：2026-10-20 · **交付检查日**：2026-10-25
> **定位**：SDC Domain 2 / Orbyte-compatible SME automation product
> **文档性质**：团队共同遵守的需求基线；包括 **25 Oct 必交范围** 与 **Production Target**。未经团队记录的决定，不得悄悄扩大范围。
> **Feature ownership**：F1 → P1；F2 → P2；F3 → P3；F4 → P4；Shared Core/Integration → P5。**所有人均负责各自的 Frontend、Backend 和 Tests**。

## 0. One-Sentence Product Definition

**MouManTAI is an intelligent commitment assurance and recovery system for SMEs:** it links fragmented business information to customer commitments, verifies feasibility, detects cascading operational impact, coordinates human-governed recovery, and verifies communication and actual outcomes.

**核心业务问题**：SME 的客户要求、库存、供应商和产能数据分散。商家已经答应客户的交付事项一旦受运营变化影响，难以及时找出受影响承诺、评估补救选择和验证落实结果。

**核心差异化**：
1. **Commitment-Centric Intelligence**：有状态、有版本、有证据的客户承诺是系统中心，而非独立聊天机器人或 ERP。
2. **Change → Impact → Action**：变化触发重新计算受影响承诺和经约束验证的补救行动。
3. **Evidence-Grounded Closed Loop**：`SENT ≠ ACCEPTED ≠ FULFILLED`；批准 ≠ 执行成功；预测 ≠ 已确认事实。

**比赛合规边界**：不处理真实付款、不办理法定申报、不提供法律/财务建议；只使用团队合成数据做展示。Orbyte 没有官方 API / Sandbox；所有 Orbyte 端点和适配器均为本项目的**假设接口**，不得宣称已经接通真实平台。初赛需可运行的单条 Trigger → Data → Decision → Human Approval → Outcome + Audit Journey；不要求生产全功能。

## 1. Scope & Priorities

**P0 — 25 Oct 必须可运行（影响提交）**：
- [ ] Web App 可通过 README 的步骤启动；没有硬编码生产密钥；有健康检查和错误状态。
- [ ] **Commitment Registry**：至少支持 request/proposal/confirmed/risk/recovery/fulfilment 的独立状态与版本；保留原始条款和 Evidence references。
- [ ] **F1**：消息输入（至少一个可用合成渠道接入）、字段提取/验证、订单上下文更新；有不确定/冲突安全处理。
- [ ] **F2**：给出可复算的库存/BOM/交期可行性；Supplier Delay 或 Capacity Change 触发受影响承诺重新计算。
- [ ] **F3**：至少两种经过 F2 同一验证引擎评估的恢复选择；展示成本与风险；有 consequential action 的人工批准；确实更改合成运营数据或任务状态；记录结果。
- [ ] **F4**：消息草稿及通信状态；关联方案版本的同意/拒绝/歧义；客户接受与真实履约状态分别管理；跟进或升级机制至少一条可运行。
- [ ] F1→F2→F3→F4 在**同一个 `tenant_id + commitment_id`** 上端到端跑通；数据库保存 evidence/audit/version。
- [ ] 提供至少正常、异常、模糊确认、重复事件、过期批准五组自动化测试；明确测试基线和准确率定义。
- [ ] Frontend 覆盖 loading/empty/error/review/success，不以“API 返回 200”冒充业务完成。

**P1 — 若 P0 已完成再做**：更多消息模板、真实某一个渠道接入、复杂 OR-Tools 排程、展示更详细的 Dependency Graph、增加多语言抽取评估样本、性能与安全强化。

**P2 — Production Roadmap（不是本次截止前承诺）**：WhatsApp/Gmail/Outlook/Telegram 完整 OAuth/Webhook；Temporal 高可用、OPA、完整多租户运营、GPU serving、Chronos-2/LightGBM 预测、全套外部库存/ERP 连接、正式支付状态读取、长期 Case Memory / ML learning。

**禁止为 P2 推迟 P0**；不准将尚未运行的功能写成“implemented”。

## 2. Roles & Boundaries

| Owner | Domain (backend + frontend + tests) | Hard boundary |
|---|---|---|
| P1 | F1 Business Context、`/inbox`、`/orders/:id` | 不判定付款到账、不修改 Confirmed Commitment、不判断库存可行性 |
| P2 | F2 Feasibility + Impact、`/commitments/:id`、`/impact/:id` | 仅计算/发布结果；不自行执行采购、修改已有客户条款 |
| P3 | F3 Recovery + Approval + Action、`/recovery/:id` | 复用 P2 可行性校验；未授权不得执行重要动作 |
| P4 | F4 Communication + Confirmation、`/communications`、`/confirmations/:id` | 不将 Sent/Read 当 Accepted，不将 Accepted 当 Fulfilled |
| P5 | Commitment Core、Audit、Contracts、App shell、`/overview`、`/activity` | 协调集成但不替代其他人完成其 feature UI 或 tests |

### 2.1 Shared Business Model

- **Request**：客户表达需求，不一定已经被商家答应。
- **OrderContext**：某笔订单涉及的、可持续更新的结构化上下文。
- **Commitment**：具体、可确认、可追踪的商业交付承诺（一个订单可包含多项）。
- **Proposal**：针对某 Commitment 的条款建议，有版本和有效期。
- **FeasibilityAssessment**：在特定数据快照下经计算的约束结果。
- **RecoveryCase / RecoveryPlan**：对某风险的应对选择与操作计划。
- **Communication / Confirmation**：发送动作和对具体提案条款的确认事实。
- **FulfilmentEvidence**：实际履约证据，由可信的运营来源提供。

### 2.2 Separate State Dimensions (DO NOT flatten)

| Dimension | Values |
|---|---|
| Agreement | `REQUESTED`, `OFFERED`, `CONFIRMED`, `REJECTED`, `CANCELLED` |
| Feasibility | `NOT_ASSESSED`, `FEASIBLE`, `CONDITIONAL`, `INFEASIBLE`, `UNKNOWN` |
| Risk | `NORMAL`, `AT_RISK`, `BREACHED`, `RESOLVED` |
| Recovery | `NONE`, `PLANNING`, `PENDING_APPROVAL`, `EXECUTING`, `COMPLETED`, `RECOVERY_REQUIRED` |
| Fulfilment | `NOT_STARTED`, `IN_PROGRESS`, `PARTIALLY_FULFILLED`, `FULFILLED`, `UNVERIFIED` |

**必须满足的业务不变量**：
1. `REQUESTED` ≠ `CONFIRMED`；必须存在有效确认/授权证据才可确认条款。
2. `CONFIRMED` + `AT_RISK` 是合法组合，不把原承诺抹掉。
3. 改数量、交期或关键条款必须新 `commitment_version` / Proposal，保留历史。
4. `FEASIBLE` 是特定 snapshot 的评估；不保证未来一定交付，不构成自动接受订单。
5. 批准仅对固定 `plan_version`, `snapshot_version`, `approval_scope` 生效；执行前再次校验。过期/版本变化 → block/replan。
6. `MESSAGE_SENT`, `DELIVERED`, `READ`, `ACCEPTED`, `FULFILLED` 是不同事实。
7. 不把 Receipt OCR 当作可信的付款到账证明；无生产真实付款处理。
8. 同一已预留资源不能被两个行动并发重复分配；Commitment 记录按版本安全更新。
9. 任何重要状态变化必须写入 Audit/Outbox，且未通过条件时维持旧状态。
10. AI 可以解释/推荐/抽取，但不能覆盖 Hard Constraints、身份校验或 Approval Policy。

## 3. Canonical Data Contracts (contract-first)

> 下列 JSON 为契约示意，**字段名称和 enum 是第一天需要冻结的基线**；新增字段可向后兼容，破坏性变更需要团队共同批准。所有 ID 均为字符串，时间均为 offset-aware ISO 8601，货币金额使用 decimal string。

### 3.1 `BusinessContext`

```json
{
  "tenant_id": "tenant_demo_01",
  "context_id": "ctx_001",
  "source_message_ids": ["msg_001"],
  "customer_id": "cust_001",
  "customer_identity_status": "LINK_VERIFIED",
  "order_id": "ord_001",
  "requested_items": [{"sku":"BURGER","quantity":"100","unit":"pcs"}],
  "requested_delivery_at": "2026-10-24T15:00:00+08:00",
  "field_evidence": {"quantity": ["ev_msg_001"]},
  "conflicts": [],
  "missing_fields": [],
  "context_version": 1,
  "status": "READY"
}
```

### 3.2 `Commitment`

```json
{
  "tenant_id": "tenant_demo_01", "commitment_id": "com_001",
  "order_id": "ord_001", "customer_id": "cust_001",
  "terms": {"sku": "BURGER", "quantity": "100", "unit":"pcs", "deadline":"2026-10-24T15:00:00+08:00"},
  "agreement_state": "CONFIRMED", "feasibility_state": "FEASIBLE",
  "risk_state": "NORMAL", "recovery_state":"NONE", "fulfilment_state":"NOT_STARTED",
  "commitment_version": 2, "evidence_refs": ["ev_confirm_001"],
  "updated_at": "2026-10-20T20:00:00+08:00"
}
```

### 3.3 `FeasibilityAssessment`

```json
{
  "assessment_id":"fa_001", "tenant_id":"tenant_demo_01", "commitment_id":"com_001",
  "commitment_version":2, "snapshot_version":142, "status":"INFEASIBLE",
  "constraints":[{"code":"MATERIAL_SHORTAGE","resource_id":"PACKAGING","shortage":"20","unit":"pcs"}],
  "affected_commitment_ids":["com_001","com_002"],
  "evidence_refs":["ev_stock_001","ev_supplier_003"],
  "solver_status":"NOT_RUN", "assessed_at":"2026-10-20T20:05:00+08:00"
}
```

### 3.4 `RecoveryPlan`

```json
{
  "tenant_id":"tenant_demo_01", "recovery_case_id":"rc_001", "plan_id":"plan_a",
  "plan_version":1, "commitment_id":"com_001", "based_on_assessment_id":"fa_001",
  "snapshot_version":142, "feasibility_status":"CONDITIONAL",
  "estimated_extra_cost":"80.00", "currency":"MYR", "estimated_delay_minutes":0,
  "risks":["SUPPLIER_AVAILABILITY_PENDING"],
  "actions":[{"action_id":"act_001","type":"CREATE_PURCHASE_REQUEST","requires_approval":true,"idempotency_key":"plan_a_act_001"}],
  "approval_state":"PENDING", "execution_state":"NOT_STARTED"
}
```

### 3.5 `CommunicationRequest` and `Confirmation`

```json
{
  "communication_id":"comm_001", "tenant_id":"tenant_demo_01", "commitment_id":"com_001",
  "proposal_id":"proposal_003", "proposal_version":3,
  "recipient_identity_id":"identity_001", "channel":"MOCK_WHATSAPP",
  "message_status":"DRAFT", "message_template_key":"delivery_change_v1",
  "approval_state":"PENDING", "confirmation_id":"conf_001",
  "confirmation_state":"AWAITING_RESPONSE", "expires_at":"2026-10-22T20:00:00+08:00"
}
```

### 3.6 `DomainEvent`

```json
{
  "event_id":"evt_001", "schema_version":1, "event_type":"commitment.at_risk",
  "tenant_id":"tenant_demo_01", "commitment_id":"com_001",
  "commitment_version":2, "correlation_id":"corr_001", "causation_id":"evt_supplier_delay",
  "occurred_at":"2026-10-20T20:06:00+08:00", "payload":{"assessment_id":"fa_001"}
}
```

**不允许**：每个 Feature Owner 独立发明同名字段含义、在 Event Payload 中存密码/密钥、在不同表修改独立的 Commitment State。

## 4. Feature-to-Feature Handshake

| Producer → Consumer | Contract | Trigger / Required behavior |
|---|---|---|
| P1 → P5 / P2 | `BusinessContext` + `business.context_updated` | 可用 context 新建 Request / 触发 Feasibility；冲突不得直接确认 |
| P2 → P5 / P3 | `FeasibilityAssessment` + `commitment.at_risk` | 仅对经确认受影响的承诺触发恢复；数据不足用 UNKNOWN |
| P3 → P5 / P4 | `RecoveryPlan` + `recovery.communication_requested` | 审批及 revalidate 之后请求沟通；不要用 AI 草稿直接发送 |
| P4 → P5 / P3 | `confirmation.accepted|rejected|counteroffer_received` | Core 校验 Proposal Version；拒绝触发 replan |
| P3 / Operational Adapter → P5 / P2 | `recovery.action_completed`, `commitment.fulfilment_verified` | 核验事实后更新业务状态并重新评估 |

**纯计算 API（内部契约）**：`POST /internal/feasibility/evaluate` 接 `BusinessContext/Commitment + OperationalSnapshot + proposed_changes?` 返回 `FeasibilityAssessment`；F3 必须调用或复用 P2 引擎，不能重复自己算库存。

**对外主要 API（建议）**：`POST /v1/messages/ingest`、`GET /v1/contexts/{id}`、`POST /v1/commitments/{id}/assess`、`GET /v1/commitments/{id}`、`POST /v1/recovery/cases/{id}/generate`、`POST /v1/recovery/plans/{id}/approve`、`POST /v1/recovery/plans/{id}/execute`、`POST /v1/confirmations/{id}/respond`、`GET /v1/audit?commitment_id=...`。具体路径定稿由 P5 负责，避免重复。

## 5. Frontend Requirements & Design System

**统一 Stack**：React + TypeScript + Vite、Tailwind、shadcn/ui、React Router、TanStack Query、React Hook Form + Zod（可按需求）、Vitest/RTL。Graph 可用 React Flow；不要为图形牺牲可运行流程。HTTP Client 全组统一 `fetch` 或 Axios 一种。

**页面所有权**：
- P5: `/overview`, `/activity`, app shell, navigation, permission context, shared badges/dialog/toast, API client。
- P1: `/inbox`, `/orders/:id`；源消息、字段、evidence、review/correction。
- P2: `/commitments/:id`, `/impact/:id`；可行性、约束、变化前后影响。
- P3: `/recovery/:id`；Option Compare、审批、执行记录。
- P4: `/communications`, `/confirmations/:id`；草稿、发送状态、接受/拒绝/Counteroffer。

**所有页面**：Loading、Empty、Error、Permission Denied、Retry、Success、Unresolved；显示来源与更新时间；重要动作二次确认；禁止 UI 直接把 API submitted 当 done；与 API enums 一致。每个人负责自己页面的 Responsive 基础与 Accessibility（表单 label、keyboard、contrast）。

## 6. Backend & Data Design

**推荐基础**：Python FastAPI、Pydantic v2、SQLAlchemy + Alembic、PostgreSQL、Pytest、Docker Compose。为并行开发允许 Memory Fake Repository 与 fixtures，但最终 E2E 使用真实 DB。

**Suggested modules**：`app/core`、`app/context`、`app/feasibility`、`app/recovery`、`app/communication`、`app/integrations`。避免横向复制 Domain Entities；共享类型从 `contracts/` 导出。

**源事实归属**：库存数量属于库存数据源；消息属于渠道数据源；MouManTAI 保存可复算 snapshot、承诺及解释/审计，而不是默默替代 ERP 的库存真相。

**可靠性**：At-least-once event handling、unique `event_id`、idempotent consumers、transactional outbox（P0 可用同 DB outbox + worker）、optimistic concurrency on commitment version。错误不能被吞并；业务失败状态与 HTTP 失败区分。外部副作用执行前做 precondition & version check。

**安全**：tenant scoping、role-based approval、API-side permission check、no cross-tenant retrieval、redacted logs、mock credentials only、untrusted inbound prompt injection isolation、no unapproved real payment or external side effect。

## 7. Testing & Acceptance Matrix

| ID | Scenario | Expected authoritative result |
|---|---|---|
| E2E-01 | Customer requests 100 units; verified constraints allow | Request context populated; feasibility evidence; proposal/confirmation follows policy |
| E2E-02 | Supplier ETA moves after confirmed order | P2 recomputes affected commitments; only truly impacted IDs flagged |
| E2E-03 | Two recovery plans (low cost late vs high cost on time) | Both compared from same snapshot; no absolute “best”; approval required where consequential |
| E2E-04 | Manager approves stale plan; stock changed in meantime | Execution blocked, review/replan; no unauthorized stock mutation |
| E2E-05 | Customer says vague “OK” to several proposals | `UNKNOWN` / request clarification, never auto-confirm |
| E2E-06 | Correct signed confirmation for proposal V2 after V3 created | Reject stale confirmation; preserve V3 and audit |
| E2E-07 | Message sent, but no reply | Message sent state updates; confirmation remains pending; fulfilment not done |
| E2E-08 | Duplicate webhook / action retry | Exactly one logical state transition and no duplicate external operation |
| E2E-09 | Receipt screenshot uploaded without trustworthy transaction | Evidence recorded, verified payment remains unknown |
| E2E-10 | Worker crashes after action succeeds externally | Reconcile provider operation/idempotency; no blind re-execution |
| E2E-11 | Tenant A ID attempts to access Tenant B commitment | Access denied; no leakage in body, logs, vector retrieval |
| E2E-12 | Operational completion record received | Fulfilment state only updated when appropriate evidence is verified |

**Quantitative Metrics**：F1 intent/extraction accuracy, wrong context match; F2 false-feasible rate and impacted-commitment recall; F3 invalid-plan rate and unauthorized actions (target zero in tests); F4 false acceptance; E2E completion, audit completeness, median processing time. Report sample size and limitations, never claim production accuracy from synthetic tests.

## 8. Dates, Git & Release Controls

| Date | Team exit criterion |
|---|---|
| **20 Oct** | Contract freeze, example fixtures, branches, app shell and backend skeleton; owner/module ownership declared |
| **21 Oct** | Each owner working on independent full-stack vertical slice with unit tests / mocks |
| **22 Oct** | First integrated F1→Core→F2 and F3→F4 path against shared DB; visible pages use real API |
| **23 Oct** | Complete Trigger→Data→Decision→Human Approval→Outcome→Audit journey; negative-case tests |
| **24 Oct** | Feature freeze; regression/metric scripts; pitch proof; deploy and repo verification |
| **25 Oct** | Submission and final verification only; no speculative feature additions |

**Merge policy**：feature branches + PR; `contracts/` / `app/core` / migrations need P5 review and at least affected owner acknowledgment. PR must explain UI/API/schema changes, tests, failure states and audit effect. Feature owner responsible for frontend and backend and both sets of tests. P5 coordinates E2E but **不是大家的收尾工程师**。

**Change process**：任何冻结后的 scope/enum/API 变更先在 `TEAM_LOG.md` 写 Decision / Impact / Owner，再修改 Contract，最后合并代码。**AGENTS.md** 是 Agent 执行规则；所有 Agent 和成员须遵守此文件。

## 9. Final Scope Locks (do not re-open without evidence)

1. 不增加第五个业务 Feature；Shared Commitment Core 不算第五个 Feature。
2. 不实现 Self-Learning LLM / Continuous Fine-tuning；只有 Operational Feedback Loop 是 P0。
3. Payment 仅 Evidence + optional trusted status input；比赛不处理真实付款。
4. Predictive ML 属 Optional Roadmap；F2 deterministic constraints 优先。
5. F3 输出 **recommended under business preferences**，不是无法解释的绝对最佳。
6. F4 区分 `SENT`, `ACCEPTED`, `FULFILLED`，确认必须绑定身份、条款、版本。
7. Evidence 只能证明其适用的 claim；Supplier Promise ≠ Goods Received；Action Success ≠ Commitment Fulfilled。
8. 整合失败时优先维护 E2E 主流程，不扩增新渠道/模型/视觉特效。

## 10. Quick Product Summary

MouManTAI 把分散在 WhatsApp、Email、Telegram 与内部系统的业务数据转换成可追溯的客户承诺，通过库存、供应商和产能约束持续验证履约可行性；当变化威胁承诺时，它生成可行的恢复方案，经必要审批后协调执行和沟通，并以真实确认与履约证据完成闭环。
