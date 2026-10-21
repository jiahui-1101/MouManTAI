# P1 TASK 2B-FIX handoff — 2026-10-21

当前分支 `feat/p1-context-intelligence`；本次起点 `772bb1e`，最新实现提交 `601c04f`。**本任务没有 push、merge、TASK 2C 或模型集成。**

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
