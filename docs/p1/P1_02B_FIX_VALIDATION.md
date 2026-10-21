# P1 TASK 2B-FIX — extraction safety validation

2026-10-21（Asia/Singapore）。分支 `feat/p1-context-intelligence`，起点 `772bb1e`，初始工作区干净。
已逐项检查 `7c6ab30`、`243fab1`、`9a83e3b`、`772bb1e`；需求读取自当前实际路径：根 `AGENTS.md`、`docs/REQUIREMENTS_SYSTEM.md`、`docs/requirements/PERSON_1_CONTEXT_REQUIREMENTS.md`、近期 `docs/TEAM_LOG.md`。未发现 backend/docs 下额外 AGENTS。
本任务只修改 P1 的纯提取器、本地 envelope 默认值、测试和文档；不改变 P5 schema、API/处理流程、数据库基础设施或模型集成，不 push、不 merge。

## 修复及可复现证据

固定基准：`received_at=2026-10-20T02:00:00Z`，显式 `Asia/Kuala_Lumpur`；DST 样本单独显式使用 `America/New_York` 和固定日期。

| 输入/场景 | 修复前实测 | 修复后实测 |
|---|---|---|
| `Deliver tomorrow after 3pm` | VALID / EXACT / 2026-10-21 15:00 | UNRESOLVED / null，不丢弃 lower-bound 语义 |
| `tomorrow at 3pm; ...2026-10-24 at 4pm`，或句号分隔 | 静默选择第一个 | UNRESOLVED，保留冲突原文证据 |
| `Deliver tomorrow; call at 3pm` | 日期、时间被跨句拼接 | UNRESOLVED |
| envelope 省略 business_timezone | 自动 Asia/Kuala_Lumpur | None；相对/本地交期 UNRESOLVED |
| `10月24日`（有/无时区） | 隐式取来源年份，无时区 helper 甚至使用 2026 | UNRESOLVED，原文保留；不补年份 |
| `2026-03-08 02:30`，New York | VALID -05:00（不存在的墙钟时间） | UNRESOLVED（nonexistent） |
| `2026-11-01 01:30`，New York | VALID -04:00（任取 fold） | UNRESOLVED（ambiguous） |
| Oct 20 发出的 tomorrow，Oct 21 接收，message_at 存在 | 按 received_at 算成 Oct 22 | 按 message_at 算成 Oct 21，记录来源 |
| 同一原请求延迟至 Oct 23 接收 | 重算成新的未来请求 | UNRESOLVED；metadata 保留 Oct 21 的原候选，不滚动日期 |
| `25点`、`3:99pm`、`15:000`、秒字段、`3pmx` | 部分解析成合法时间，或回退 DATE_ONLY | INVALID，不截取合法后缀或回退日期 |
| `3:30pm`；完整中文年月日 | 多个 regex 重叠 | 一个 token；先占用完整表达式再验证 |
| `maybe at 3pm`、`around`、`between`、`not before`、显式文本时区 | 部分误标 EXACT | UNRESOLVED；不支持的限定不强行投射至 enum |
| 过去日期/当天已过时刻 | VALID | UNRESOLVED；保留 candidate_delivery_value |
| `before 2026-10-24` | DATE_ONLY 丢弃限定关系 | DATE_ONLY 日期字符串，metadata.date_relation=DEADLINE；没有午夜 |
| 同一别名对应多个 SKU 或单位 | SKU 候选标 VALID | SKU 与关联数量 UNRESOLVED |

每组先加入失败回归再修复；原始失败计数依次为表达式 25、来源上下文 8、DST/过去日期 6、句间/额外边界 7、catalog 歧义 2、非法后缀/试探表达 6。正例始终保留；没有删除失败标准。当前新增安全测试共 77 项。

## 明确策略与范围

- 规则版本 `p1-deterministic-v3`。原文与 StoredMessage 不变；所有字段使用原 message_id、RULE/version、原 quote 和 `[start,end)` Unicode code-point offsets。emoji、多个冲突片段和 NormalizedMessage 的原文校验均有回归。
- **时区**：本模块没有受信任 tenant 默认值。省略或 null 都不能提供解析上下文。显式值记录 `timezone_source=message.business_timezone`，这只是 envelope 声明来源，并非租户设置已验证。未来 host 若提供可信默认，须记录配置/租户来源；本次没有添加该行为。
- **相对日期**：`message_at_else_received_at_v1`，优先已保存的 message_at，否则回退 received_at；不读取处理时钟。message_at 晚于 received_at 要人工复核。source_timestamp/source_timestamp_source/received_at 写入 metadata；不据此验证消息真实性或身份。
- **年份**：年月日必须显式且格式无歧义。没有“今年/明年最近一次”推测策略；中文短日期、英文无年日期、歧义 slash 日期保留 UNRESOLVED。不会把未知年份编码为 2026。
- **DST**：参考 [Python ZoneInfo/fold 文档](https://docs.python.org/3/library/zoneinfo.html)。本实现分别测试 fold=0/1 经 UTC 往返，只接受唯一实际 UTC instant；零个为 gap，多个为 fold。没有自动移时或任取 offset。
- **过去日期**：相对于固定的 received_at 检查；instant 以 UTC 比较，DATE_ONLY 按业务日比较。同一天 DATE_ONLY 不因为午夜已过而过期。过去请求只作待复核观察，不滚动到未来，不假设业务例外。此校验不保证未来处理时仍及时，消费前仍需独立 freshness 策略。
- **表达式**：多个独立 date/time 一律不选第一个；被完整日期/12h token 覆盖的短 token 不计作第二表达式。句间 date+time 不合并。lower bound、范围、近似、试探、显式文本时区暂不支持，返回 UNRESOLVED。中文裸 1..12 点、中午3点、晚上12点等不能作为唯一精确时刻。
- **单位**：归一化不能越过 SKU 单位兼容性；BURGER/pcs 的 kg/box 请求 INVALID，没有换算。显式匹配的 kg/box 测试 catalog 可用整数计量。小数数量仍不受支持；多字中文单位未扩展。不新建或批准 SKU registry。
- VALID 表示局部规则通过，不等于身份、承诺、完整信息或 READY。解析器不会创建 BusinessContext，也不会触发工具、订单或付款操作。

## 实际 P5 契约检查与未决问题

检查文件为 `backend/app/core/schemas.py`，不是根据旧需求猜测。
直接 `BusinessContext.model_validate` 探针观察：DATE_ONLY `2026-10-24` 拒绝；带 offset 的 datetime 接受；`status=READY` 现有 validator 转成 INFORMATION_READY；PARTIAL 拒绝；AMBIGUOUS identity 拒绝；额外 qualifier 字段拒绝。

| 本地维度 | P5 当前实际结构 | 待 owner/P5 确认，不是本次批准的映射 |
|---|---|---|
| DATE_ONLY | requested_delivery_at 仅 offset-aware datetime 或 null | 日期/日期边界如何保存、如何请求补充时间；不可转成午夜 |
| EXACT / DEADLINE | BusinessContext 无 qualifier/range 字段；CommitmentTerms 使用 deadline | 不得把 EXACT 自动视为 deadline；before/by 的严格/包含边界也要确认。原文与限定必须保留 |
| readiness | INFORMATION_READY / INFORMATION_PARTIAL / CONFLICT / UNRESOLVED / PROCESSING_FAILED；已有 legacy READY 归一化 | 本地 PARTIAL 没有现成 alias；完整性门槛、日期欠缺、身份门槛需确认。本次不写 adapter、不改共享 enum |
| identity | UNVERIFIED / LINK_CANDIDATE / LINK_VERIFIED / CONFLICT | 本地 AMBIGUOUS 不是可直接传入的值，不能任意选成候选或冲突；LINK_VERIFIED 必须有可信验证证据 |
| 无商品的 partial | requested_items 至少一项 | 消息级 partial extraction 的持久化形状与发布 gate 待定，不能伪造商品来通过验证 |

另一个 legacy 风险：旧 envelope 已把隐含 Malaysia 默认值持久化为显式字符串，现存数据通常无法恢复最初是否省略。此次不迁移、不重写这些原始记录，不宣称已验证其 timezone provenance。旧请求省略 timezone 的 retry 还需单独检查新默认值与历史 fingerprint 的兼容性；既有数据库回归通过不证明覆盖所有历史数据。

## 精确验证命令与结果

从 `C:\XMUM\MouManTAI`：

```powershell
# 最终 focused：139 passed / 0 skipped
.venv/Scripts/python.exe -m pytest backend/app/context/tests/test_delivery_expression_safety.py backend/app/context/tests/test_delivery_context_safety.py backend/app/context/tests/test_delivery_instant_safety.py backend/app/context/tests/test_catalog_extraction_safety.py backend/app/context/tests/test_deterministic_extraction.py -o addopts='' -q --tb=short

# 完整相关后端：295 passed / 0 skipped / 1 warning，13.95s
. .\backend\app\context\dev\load-env.ps1 -Path .local/p1.env
.venv/Scripts/python.exe -m pytest backend/app/context/tests backend/tests -o addopts='' -q -ra

git diff 772bb1e..HEAD --check
```

warning 为原有 Starlette/httpx deprecation。P1 DB tests 使用已健康运行的 PostgreSQL（没有新建数据库基础设施）；P5 原有测试 fixture 使用自身 SQLite 内存引擎，这不证明 P5 PostgreSQL 部署或生产迁移通过。
本地 `.local/p1-task2b-safety-evidence.json` 保存七个固定样本的实际输入/输出，含 after、分号、yearless、DST gap/fold、25点和 DATE_ONLY；不纳入 Git。
未运行模型 benchmark、前端构建/浏览器 E2E 或 TASK 2C 持久化流程：此次没有相应功能改动，也不宣称这些流程已验证。P1 OpenAPI/client 生成物与未来流程应在接入任务中同步验证。

## 小提交与交接

| Commit | 修复边界 | 当时实际检查 |
|---|---|---|
| fcee8cc | modifiers、全 token 时间校验、重叠和多表达式 | 90 passed |
| 5d70f91 | 缺失时区、年份及 source timestamp policy | 含 schema/fixture 回归 147 passed |
| 9e492f5 | DST 与过去日期/延迟消息 | 117 passed |
| 9c6a1ed | 句间关联、中文午夜、offset 与 DATE_ONLY relation | 124 passed |
| a8b78a8 | SKU/单位别名歧义与兼容性 | 71 passed |
| 601c04f | 非法时间后缀与 tentative modifiers | 最终 focused 139 passed |

可继续向 TASK 2C 的**有界、provisional、保留 UNRESOLVED 的设计**推进；尚不能自动发布完整 P5 BusinessContext 或标记 INFORMATION_READY。正式接入前应先确认上述契约、历史时区 provenance、重试兼容性与消费时 freshness 策略。此次不实施 TASK 2C。没有未提交的实现改动，没有 push 或 merge。
