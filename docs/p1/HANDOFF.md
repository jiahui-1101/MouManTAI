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
