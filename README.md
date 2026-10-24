> [!IMPORTANT]
> ## 📁 Submission Documents
> Official SDC 2026 submission files are in [`submission/`](submission/).

# MouManTAI

<p align="center">
  <b>An AI operations layer that helps Malaysian SMEs turn messy customer and supplier messages into reliable, protected customer commitments.</b>
</p>

<p align="center">
  <b>Protect the promise, even when the plan changes.</b> · <i>Mou man tai</i> (冇問題) — "no problem".
</p>

<p align="center">
  <img alt="React" src="https://img.shields.io/badge/Frontend-React%2019%20%2B%20Vite-61DAFB?style=for-the-badge&logo=react&logoColor=black">
  <img alt="TypeScript" src="https://img.shields.io/badge/Language-TypeScript-3178C6?style=for-the-badge&logo=typescript&logoColor=white">
  <img alt="FastAPI" src="https://img.shields.io/badge/Backend-FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white">
  <img alt="Python" src="https://img.shields.io/badge/Python-3.11--3.14-3776AB?style=for-the-badge&logo=python&logoColor=white">
  <img alt="PostgreSQL" src="https://img.shields.io/badge/Database-PostgreSQL%2016-4169E1?style=for-the-badge&logo=postgresql&logoColor=white">
</p>

<p align="center">
  <img alt="OR-Tools" src="https://img.shields.io/badge/Optimisation-OR--Tools%20CP--SAT-4285F4?style=for-the-badge&logo=google&logoColor=white">
  <img alt="RunPod" src="https://img.shields.io/badge/GPU-RunPod%20Serverless-673AB7?style=for-the-badge">
  <img alt="Qwen3" src="https://img.shields.io/badge/LLM-Qwen3--4B--Instruct--2507-FF6A00?style=for-the-badge">
  <img alt="GLiNER" src="https://img.shields.io/badge/NER-GLiNER%20multi%20v2.1-FFD21E?style=for-the-badge&logo=huggingface&logoColor=black">
  <img alt="Replit" src="https://img.shields.io/badge/Built%20on-Replit-F26207?style=for-the-badge&logo=replit&logoColor=white">
  <img alt="Docker" src="https://img.shields.io/badge/Runtime-Docker%20Compose-2496ED?style=for-the-badge&logo=docker&logoColor=white">
</p>

---

## Table of Contents

- [Team Information](#team-information)
- [Links](#links)
- [Track & Problem Statement](#track--problem-statement)
- [Introduction](#introduction)
- [System Flow](#system-flow)
- [System Architecture](#system-architecture)
- [Core Features](#core-features)
- [Innovation](#innovation)
- [Technical Deep Dive](#technical-deep-dive)
- [Technical Stack](#technical-stack)
- [Installation](#installation)
- [Environment Variables](#environment-variables)
- [Deployment](#deployment)
- [API Reference](#api-reference)
- [Project Structure](#project-structure)
- [Testing & CI](#testing--ci)
- [How We Use Replit](#how-we-use-replit-required)
- [How We Use RunPod](#how-we-use-runpod-required)
- [Challenges & Learnings](#challenges--learnings)
- [Future Improvements](#future-improvements)
- [Team](#team)
- [Submission Checklist](#submission-checklist)
- [License](#license)

---

## Team Information

| Field                 | Details                                              |
| --------------------- | ---------------------------------------------------- |
| **Team Name**         | XMM                                                  |
| **Team Domain**       | Domain 2 — Orbyte Smart SME Challenge                |
| **SDG Track (1–17)**  | SDG 8 — Decent Work and Economic Growth (8.2, 8.3)   |
| **Team Leader**       | Wong Jia Hui                                         |
| **University**        | Universiti Teknologi Malaysia (UTM)                  |
| **Number of Members** | 5                                                    |

## Links

| Resource          | Link                                         |
| ----------------- | -------------------------------------------- |
| GitHub Repository | https://github.com/jiahui-1101/MouManTAI     |
| Replit Project    | [REPLIT PROJECT URL]                         |
| Live Prototype    | [LIVE APP URL]                               |
| RunPod Endpoint   | `https://api.runpod.ai/v2/<endpoint-id>/run` (ID kept in Secrets) |
| Slide Deck        | [SLIDE DECK URL]                             |
| Pitching Video    | [YOUTUBE URL]                                |

---

## Track & Problem Statement

**Hackathon:** SDC Hackathon 2026
**Domain:** Domain 2 — Orbyte Smart SME Challenge
**SDG:** SDG 8 — Decent Work and Economic Growth (target 8.2 productivity through technological upgrading, target 8.3 support for micro, small and medium-sized enterprises)
**Project Name:** MouManTAI
**Solution Type:** AI-assisted operations layer — FastAPI modular monolith + React SME Command Center + RunPod GPU inference + OR-Tools optimisation

### Problem

Malaysia's 1.29 million MSMEs make up 96.2% of all businesses and 39.7% of GDP, yet ~77% remain at a basic stage of digitalisation. In a typical catering SME, one customer promise is spread across a WhatsApp chat, a stock spreadsheet and a separate supplier conversation. Owners rebuild orders by hand, accept orders they cannot fulfil, and scramble when a supplier is late.

The work is spread across three disconnected places:

- **Conversations** — customers and suppliers on WhatsApp, Telegram and email, in English, Bahasa Malaysia and Chinese, often in the same thread.
- **Operational records** — stock, lot expiry, recipes / bills of materials, production capacity, incoming supply and existing orders, usually in spreadsheets.
- **Human decisions** — an owner deciding whether to accept an order, pay more for another supplier, or ask a customer to accept new terms.

When a supplier is late, a reminder does not answer the real questions: **which promises are affected, which alternatives are actually feasible, who approved the change, did the customer agree to the new terms, and was the order actually delivered?**

---

## Introduction

### Solution

MouManTAI connects **Customer, SME and Supplier** in one evidence-backed commitment workflow — **Understand → Decide → Anticipate → Recover → Learn**. Qwen3 and GLiNER interpret messages; a deterministic feasibility engine and Google OR-Tools CP-SAT support the owner's decision; every emergency action executes only after explicit human approval.

| Stage | What MouManTAI does |
|---|---|
| **Understand** | Reads customer and supplier messages and attachments, extracts order terms with exact source spans, asks targeted clarification questions, and routes anything uncertain to Human Review. |
| **Decide** | Checks stock, lots, BOM and capacity for each order; compares multi-order plans with OR-Tools CP-SAT; lets the SME accept exact terms and reserve resources in one step. |
| **Anticipate** | Forecasts demand and supply risk from validated history and raises advisory alerts before a disruption becomes a breach. |
| **Recover** | When a supplier changes, identifies only the affected commitments, ranks recovery options by cost, delay and risk, and executes the chosen plan after **Approve & Execute**. |
| **Learn** | Records decisions, approvals and verified outcomes in Decision Memory, so the next similar case starts from evidence instead of memory. |

**Three perspectives, one shared decision core:**

- **Customer** — orders and asks questions through the messaging channels they already use; receives factual status milestones; explicitly accepts or rejects revised proposals.
- **SME** — works in the MouManTAI Command Center: inbox, Human Review, Pending Acceptance, calendar, portfolio comparison, supplier comparison, recovery and communications.
- **Supplier** — sends quotations, specifications, availability and ETA changes through existing channels; claims are kept separate from verified delivery history.

### Key Features

- **Customer Inbox & conversational ordering** — messages and attachments become order drafts with source evidence; targeted clarification; Human Review after two answered attempts without progress; Pending Acceptance, never auto-confirmed.
- **SME Command Center & calendar** — stock, lot expiry, BOM and capacity feasibility; accepted vs pending workload; exact-terms acceptance with resource reservation.
- **Multi-order optimisation** — FCFS, Profit and Expiry-Aware strategies with OR-Tools CP-SAT, every plan re-validated by the feasibility engine.
- **Supplier comparison** — category specification templates (food packaging, perishables, general supplies); Qualified / Conditional / Incompatible; verified history vs supplier claims.
- **Emergency Change-to-Action** — affected-order impact, recovery options with cost and delay, **Approve & Execute** with separate audited approval and execution.
- **Customer status & milestones, Forecasting, Decision Memory** — factual updates, advisory risk outlook, and a record of decisions and verified outcomes.

---

## System Flow

The end-to-end journey of one commitment, from the first customer message to a verified outcome. The supplier-delay branch joins the same commitment.

```mermaid
flowchart LR
    MSG["Customer message<br/>WhatsApp · Telegram · Gmail"] --> MI["Message Intelligence<br/>rules → GLiNER → Qwen3"]
    MI --> DRAFT["Order draft<br/>every field has a source span"]
    DRAFT --> COMPLETE{"Information<br/>complete?"}
    COMPLETE -- "No" --> CLAR["Targeted clarification<br/>per unresolved issue"]
    CLAR -- "Progress" --> COMPLETE
    CLAR -- "2 answered attempts<br/>without progress" --> HR["Human Review"]
    HR --> PA
    COMPLETE -- "Yes" --> PA["Pending Acceptance"]
    PA --> FEAS["Feasibility engine<br/>stock · lots · BOM · capacity"]
    FEAS <--> OPT["CP-SAT portfolio<br/>FCFS · Profit · Expiry-Aware"]
    FEAS --> DEC{"SME decision<br/>on exact terms"}
    DEC -- "Accept" --> RES["Reserve resources<br/>Commitment CONFIRMED"]
    DEC -- "Reject" --> INF["Customer informed"]
    RES --> MIL["Factual status milestones"]
    SUP["Supplier delay"] --> IMP["Impact on affected<br/>commitments only"]
    RES -.-> IMP
    IMP --> REC["Recovery options<br/>cost · delay · risk"]
    REC --> AE["Approve & Execute<br/>two audited commands"]
    AE --> CONF["Customer confirms<br/>revised proposal"]
    CONF --> FUL["Verified fulfilment"]
    MIL --> FUL
    FUL --> DM["Decision Memory"]
```

---

## System Architecture

MouManTAI is a **modular monolith**: one FastAPI application with clearly owned modules, one PostgreSQL 16 database, and one outbox worker. Modules talk to each other through typed contracts and outbox events, not through shared mutable state. Heavy model inference runs outside the API on a RunPod Serverless GPU endpoint.

```mermaid
flowchart TB
    subgraph CH["Channels"]
        direction LR
        TG["Telegram Bot API<br/>polling or webhook"]
        GM["Gmail API<br/>OAuth 2.0 polling"]
        WA["WhatsApp Cloud API<br/>HMAC-verified webhook"]
        ATT["Attachments<br/>PDF · images"]
    end

    subgraph FE["Frontend · React 19 + Vite · SME Command Center"]
        direction LR
        F_OV["Overview & Calendar"]
        F_IN["Inbox & Human Review"]
        F_OR["Orders & Portfolio"]
        F_SU["Suppliers"]
        F_RC["Recovery"]
        F_CM["Communications & Confirmations"]
        F_AC["Activity / Audit"]
    end

    subgraph API["FastAPI modular monolith · backend/app"]
        direction TB
        subgraph UND["Understand"]
            CTX["context<br/>ingest · extract · associate · review · publish"]
            CONV["conversations<br/>clarification · factual replies"]
            ORD["orders<br/>exact terms · context mapping"]
        end
        subgraph DEC["Decide"]
            FEA["feasibility<br/>ATP · BOM · capacity · impact"]
            OPT["optimization<br/>OR-Tools CP-SAT"]
            SUPI["suppliers + sourcing<br/>spec comparison · history · RFQ"]
        end
        subgraph ARL["Anticipate · Recover · Learn"]
            FC["forecasting"]
            RECV["recovery<br/>plans · approval · actions"]
            COMM["communication<br/>drafts · outbound · confirmations · follow-ups"]
            DMEM["decision_memory"]
            OPR["operational_reporting"]
        end
        subgraph CORE["Core"]
            REG["Commitment Registry<br/>versioned · audited · reservations"]
            OBX["Transactional outbox"]
        end
        INTG["integrations<br/>business ports"]
    end

    subgraph DATA["Data & workers"]
        PG[("PostgreSQL 16<br/>Alembic migrations")]
        WK["Outbox worker<br/>python -m app.worker"]
    end

    subgraph EXT["External services"]
        RP["RunPod Serverless GPU<br/>GLiNER multi v2.1 + Qwen3-4B-Instruct-2507"]
        RAI["Replit AI Integrations<br/>ReplyGenerator adapter · switched off until verified"]
        ORB["Orbyte business hub<br/>data · identity · review tasks"]
    end

    CH --> CTX
    FE <-->|"REST /v1 · TanStack Query"| API
    CTX -->|"/run → /status"| RP
    CONV --> RAI
    COMM --> RAI
    INTG <--> ORB
    CTX --> REG
    ORD --> REG
    FEA <--> REG
    OPT --> FEA
    SUPI --> RECV
    RECV <--> REG
    COMM <--> REG
    FC --> FEA
    DMEM --> REG
    OPR --> REG
    REG --> OBX
    REG --> PG
    OBX --> PG
    WK -->|"poll · dispatch · retry"| PG
    WK --> FEA
    WK --> RECV
    WK --> COMM
```

**Architecture layers**

| Layer | Responsibility |
|---|---|
| **Channels** | Telegram (long polling with persistent offsets, or webhook with secret-token check), Gmail (OAuth 2.0 with refresh token and incremental history cursor), WhatsApp Cloud API (challenge verification and `X-Hub-Signature-256` HMAC check), plus PDF/image attachments. |
| **Frontend** | One SME Command Center with sidebar workspaces: Dashboard, Inbox, Orders, Planning, Suppliers, Recovery, Communications, Insights. Customers and suppliers interact through messaging, so no separate portal is required. |
| **Understand** | `context`, `conversations` and `orders` turn messages into versioned, evidence-backed order contexts and canonical `OrderTerms`. |
| **Decide** | `feasibility` is the single calculation authority; `optimization` searches multi-order portfolios; `suppliers` and `sourcing` compare offers against SME hard requirements. |
| **Anticipate · Recover · Learn** | `forecasting`, `recovery`, `communication`, `decision_memory` and `operational_reporting`. |
| **Core** | The Commitment Registry owns commitment identity, version, the five state dimensions, audit records, resource reservations and the transactional outbox. |
| **Data & workers** | PostgreSQL 16 (SQLAlchemy 2 + psycopg 3, Alembic migrations) and the outbox worker that dispatches events to subscribers with retry, back-off and dead-lettering. |
| **External services** | RunPod Serverless GPU for GLiNER/Qwen inference, Orbyte through `integrations/business_ports.py`, and a Replit AI Integrations reply-wording adapter that stays switched off until it passes verification (replies use approved templates today). |

---

## Core Features

### 1. Multi-Channel Customer Inbox

Customer and supplier messages arrive through real channel adapters in `backend/app/context/channels/`:

- **Telegram Bot API** — long polling via `getUpdates` with a persistent offset (no duplicate updates across restarts), or webhook mode verified with a secret token. Webhook and polling conflicts are resolved automatically.
- **Gmail API** — Google OAuth 2.0 authorisation, automatic access-token refresh, incremental inbox polling with a restart-safe history cursor, pagination and duplicate prevention.
- **WhatsApp Cloud API** — `GET` challenge verification (`hub.verify_token`) and `POST` signature verification with HMAC-SHA256 over the raw body using the Meta app secret.

A channel manager starts configured workers on API startup and stops them on shutdown. Every inbound message is stored once with its provenance (channel, sender, provider message ID, received time, tenant) and shown in the **Customer Messages** inbox (`/inbox`) with its extraction status.

### 2. Message Intelligence — the cheapest reliable layer first

Interpretation follows a strict escalation ladder. A model is called only when cheaper layers cannot resolve the order, and no model output becomes a fact without validation.

```mermaid
flowchart TD
    IN["Stored message<br/>text + attachment text"] --> L0["L0 · Deterministic rules<br/>catalog SKU aliases · quantity · unit<br/>delivery date or deadline · order reference"]
    L0 --> Q0{"Rules resolved all<br/>required terms?"}
    Q0 -- "Yes, or non-order inquiry,<br/>or timezone-only gap" --> NOAI["No model call<br/>routing reason recorded"]
    Q0 -- "No" --> EN{"P1_AI_ENABLED and<br/>endpoint configured?"}
    EN -- "No" --> RULES["Keep rule fields<br/>unresolved fields stay open"]
    EN -- "Yes" --> L1["L1 · GLiNER multi v2.1<br/>labelled spans · threshold 0.35"]
    L1 --> Q1{"Meaningful ambiguity<br/>still remains?"}
    Q1 -- "No" --> VAL
    Q1 -- "Yes and qwen in P1_AI_STAGES" --> L2["L2 · Qwen3-4B-Instruct-2507<br/>strict JSON · greedy decoding · 768 new tokens"]
    L2 --> VAL["Schema + span validation<br/>pinned model ID and revision<br/>quote must equal source[start:end]"]
    VAL -- "Valid" --> RECON["Reconcile against rule fields<br/>proposal · duplicate · conflict · rejected"]
    VAL -- "Invalid · timeout · unavailable" --> RULES
    NOAI --> HR["Order draft + Human Review<br/>every field keeps its evidence"]
    RULES --> HR
    RECON --> HR
```

- **L0 rules** (`deterministic_extraction.py`) handle multilingual SKU aliases from an approved catalogue (for example "burger", "bgr", "汉堡"), quantities, unit normalisation, timezone-aware delivery dates and deadlines, rescheduling phrases and self-corrections. Every observation stores exact Unicode code-point offsets `[start, end)`.
- **Routing** (`context/ai/service.py`) skips the GPU for non-order inquiries ("berapa harga", "请问多少"), fully resolved orders, unsupported-unit cases that need an authorised human, and timezone-only gaps that a model cannot fix. The reason is stored with the message.
- **L1 GLiNER** proposes product, quantity, unit and delivery spans. **L2 Qwen3** runs only when ambiguity remains, for example a corrected date or several items in one sentence. Its system prompt treats incoming text as untrusted data, requires the smallest exact original substring, and never translates.
- **Validation** (`context/ai/protocol.py`) rejects any output whose model ID or revision differs from the pinned pair, whose status is not `ok`, or whose quote does not exactly match the source span. Model candidates can only become *proposals*; a conflict with a valid rule field is marked `CONFLICT` for a human.

### 3. Evidence-Backed Documents and Attachments

`document_extractor.py` reads PDFs with **PyMuPDF** and images with **PaddleOCR** only when text extraction is not possible. Each attachment gets an `evidence_ref`, page count, per-page rendering and stored extraction output. The **Attachment Viewer** and **Extraction Provenance** panels in the inbox show which page and which text each field came from. OCR output is evidence for review, never proof of payment.

### 4. Conversational Ordering and Adaptive Clarification

`conversations/clarification.py` tracks each **`UnresolvedIssue`** (`SKU`, `QUANTITY`, `DELIVERY`, `CHOICE`, `FULFILMENT`) as its own versioned record:

- Deterministic validators — catalogue, allowed units, maximum quantity, business timezone, delivery windows, fulfilment method and address fields — decide whether an answer made progress. Model confidence never does.
- After **two consecutive answered attempts without progress** (`TWO_ANSWERED_NO_PROGRESS`) the issue moves to **Human Review**. Risk flags escalate immediately, and a global budget on questions and conversation age also applies.
- No-reply handling is separate: one deduplicated reminder after the configured delay, then expiry or review. Idle time and failed sends never count as "no progress".

### 5. Human Review and Pending Acceptance

Complete, valid requests go to **Pending Acceptance**; unresolved or risky ones go to a separate **Human Review** queue (`/inbox/human-review`). The review drawer shows the original message, highlighted source spans, rule and model candidates with their method (`RULE`, `MODEL`, `HUMAN`), and any conflicts. Reviewer edits are saved as new context versions with `HUMAN` provenance tied to the current message text. A context is published to the Commitment Registry only after it passes the publication gates in `context/core_publisher.py`.

Identity is handled conservatively (`association_service.py`): an extracted order reference alone never authorises a link, and identity is never inferred from name similarity or model output.

### 6. Deterministic Feasibility Engine

`backend/app/feasibility/` is the **single calculation authority** used for new orders, accepted orders, optimisation plans and recovery options:

- **Inventory ATP** (`inventory.py`) — time-phased available-to-promise across all confirmed competing demand, including lot expiry.
- **BOM expansion** (`bom.py`) — recursive bill-of-materials expansion over an immutable snapshot.
- **Capacity** (`capacity.py`) — exact half-open interval validation of non-preemptible bookings against real working windows, not just a daily minutes budget.
- **Supplier pipeline** (`supplier_pipeline.py`) — incoming supply with typed evidence linkage.
- **Impact** (`impact.py`) — when an operational fact changes, discovers dependent commitments and recalculates before/after feasibility with the same evaluator.
- **Currentness** (`currentness.py`) — every result is tied to a snapshot version; a stale snapshot is rejected.

Results are `FEASIBLE`, `CONDITIONAL`, `INFEASIBLE` or `UNKNOWN`. A timeout or missing data returns `UNKNOWN`, never a false `INFEASIBLE` or a false `FEASIBLE`. The **Commitment Feasibility** (`/commitments/:id`) and **Impact Detail** (`/impact/:id`) pages show material shortages, capacity conflicts and the evidence behind each line.

### 7. SME Decision, Exact-Terms Acceptance and Calendar

`orders/terms.py` defines canonical **`OrderTerms`** with exact decimal arithmetic (no float, at most six fractional digits, no rounding of commercial values) and a deterministic terms hash. Acceptance requires the expected revision and expected terms hash, so the SME accepts exactly the terms the customer asked for — never a silently changed version. `orders/context_mapping.py` maps a reviewed P1 order context to an `AcceptanceCandidate`, and `orders/p1_source_reader.py` reads it only through a trusted tenant scope.

Accepting reserves resources through the Core reservation service (`core/reservations.py`: snapshot, reserve, release, consume), and only then does the commitment's agreement become `CONFIRMED`. The **Order Decision Workspace** and **Calendar** (`/orders`, `/calendar`) show accepted versus pending workload per day and per resource.

### 8. Multi-Order Optimisation with OR-Tools CP-SAT

When orders compete for the same stock or capacity, the SME can compare three portfolio strategies on `/planning/portfolio`:

| Strategy | Objective | Availability rule |
|---|---|---|
| **FCFS** | Respect arrival order | Always available |
| **Profit** | Maximise contribution | Only when sourced revenue and complete incremental cost exist; otherwise `PROFIT_COMPARISON_UNAVAILABLE` |
| **Expiry-Aware** | Use lots before they expire | Only when every lot has an expiry; otherwise `EXPIRY_COMPARISON_UNAVAILABLE` |

`optimization/cp_sat.py` compiles a versioned **`P2ConstraintSpec`** (lots, material requirements, resource windows, fixed jobs, production tasks) into a CP-SAT model. Quantities are scaled to integers exactly (`scaling.py`) with overflow checks. The solver is bounded by `max_time_in_seconds`, a fixed `random_seed` and a set number of search workers. Each projected portfolio is fingerprinted (SHA-256 digests of allocations and schedule) and **re-validated by the same feasibility engine** through the joint verifier. Any disagreement returns `VALIDATION_MISMATCH`, and the plan is not shown as valid. Optimisation is advisory: it never accepts or reserves an order.

### 9. Supplier Comparison and Sourcing

`suppliers/comparison.py` checks **hard requirements before price**. Each tenant has versioned category specifications; editable starter templates cover:

| Category | Hard fields |
|---|---|
| Food packaging (`food_container`) | `capacity_ml`, `material`, `food_safe` |
| Perishables (`perishable_ingredient`) | `grade`, `storage_requirement` |
| General supplies (`general_supply`) | `sku`, `unit` |

Offers are classified **Qualified** (all hard fields match), **Conditional** (missing evidence) or **Incompatible** (a hard field is violated). If the specification itself is unknown, the comparison fails closed. `sourcing/` adds delivery-history analysis that separates **verified history** from **supplier claims**, a side-by-side dossier, a common RFQ draft, reply consolidation, a selection preview, and a hand-off to Recovery as an `ALTERNATIVE_SUPPLY` option that stays `CONDITIONAL` until availability and approval are verified. The SME always picks the supplier and records the reason.

### 10. Emergency Change-to-Action — Approve & Execute

When a supplier delay puts a commitment at risk, MouManTAI moves from impact to a governed recovery:

```mermaid
sequenceDiagram
    autonumber
    actor SUP as Supplier
    participant P1 as Inbox and Message Intelligence
    participant P2 as Feasibility engine
    participant CORE as Commitment Registry and Outbox
    participant P3 as Recovery
    actor MGR as SME Manager
    participant P4 as Communication
    actor CUS as Customer

    SUP->>P1: 20 boxes will arrive after the 3 pm production cutoff
    P1->>P2: Supplier ETA change with source evidence
    P2->>P2: Recalculate ATP, BOM and capacity on a fresh snapshot
    P2->>CORE: Impact assessment for affected commitments only
    CORE-->>P3: Outbox event commitment.at_risk
    P3->>P2: Validate each recovery option with the same engine
    P3-->>MGR: Ranked options with cost in MYR, delay and risk
    MGR->>P3: Approve and Execute (one click)
    P3->>CORE: APPROVE_PLAN bound to plan, snapshot and commitment version
    CORE-->>P3: Approval record and approval_id
    P3->>P3: Revalidate snapshot, scope and expiry
    alt Snapshot still current
        P3->>CORE: EXECUTE_APPROVED_PLAN with idempotency key
        CORE-->>P3: Separate execution record
    else Snapshot changed or approval expired
        P3-->>MGR: Re-approval required
    end
    P3->>P4: Request communication for the revised terms
    P4-->>MGR: Draft for message review
    MGR->>P4: Approve draft
    P4->>CUS: Revised proposal, version 2
    CUS->>P4: OK, 4 pm delivery is fine
    P4->>CORE: confirmation.accepted for proposal version 2
    CORE->>CORE: Agreement CONFIRMED, fulfilment tracked separately
```

- **Recovery options** — `RESCHEDULE_PARTIAL_FULFILMENT` and `ALTERNATIVE_SUPPLY`, each persisted against the exact feasibility source and Core risk evidence (`durable_plans.py`).
- **Ranking** (`ranking.py`) — a lower-is-better weighted score over additional cost (MYR), delivery delay (minutes), number of affected commitments, operational disruption, supplier uncertainty and whether customer confirmation is required. Options that break a hard constraint are excluded with reasons.
- **Approval** (`core/manager_approval.py`) — a manager approval is bound to `plan_id`, `plan_version`, `snapshot_version` and `core_commitment_version`, has an expiry, and is single-use. Request-revision, reject and revoke are separate commands.
- **Approve & Execute** — one click in the UI, two backend commands (`/approve`, then `/execute` with an idempotency key), two audit records. **Approve Only** leaves the plan approved and awaiting execution. If execution fails or times out, the UI shows the real state and never repeats side effects blindly.

### 11. Closed-Loop Communication, Confirmation and Customer Status

`backend/app/communication/` owns every outbound message and customer response:

- **Drafts** (`drafting.py`, `templates.py`) — version-safe plain-text drafts from approved templates.
- **Message review** (`review.py`) — approval to send a message is separate from approval of a business proposal.
- **Outbound** (`outbound.py`, `providers.py`) — a durable one-submission intent; an uncertain or crashed send is never replayed automatically. `DELIVERY_UNKNOWN` is a real state. Sending goes through the `OutboundProvider` interface. The current provider is a network-free local sender whose outcomes (sent, failed, delivery unknown) are configured on the server, so the full review → send → confirmation loop runs end to end without contacting customers. Inbound Telegram, Gmail and WhatsApp adapters are live; connecting outbound sends to those same channels is listed under [Future Improvements](#future-improvements).
- **Confirmations** (`confirmations.py`, `response_rules.py`) — the customer's reply is matched to one proposal version. Conservative full-message rules mean a partial phrase never counts as acceptance; an ambiguous "OK" with several open proposals stays unresolved.
- **Follow-ups** (`followup.py`) — deterministic scheduling; each reminder is a new authorised contact intent, not a retry of the original send.
- **Recipient preferences** — channel and opt-out per recipient.
- **Customer status & milestones** — `operational_reporting/planning.py` plans template-based factual milestone messages with consent and dedupe gates. `ORDER_ACCEPTED` means the SME accepted and reserved; `COMPLETED` appears only after evidenced fulfilment.

The **Communication Center**, **Confirmation Workspace** and **Follow-up Queue** pages (`/communications`, `/confirmations/:id`, `/communications/follow-ups`) show message state, customer response and the linked proposal side by side.

### 12. Factual Replies — Templates First, Replit AI Wording Next

`conversations/replies.py` defines the `ReplyGenerator` interface. A `PublicKnowledgePolicy` allowlist limits replies to approved public fields (`faq_answer`, `fixed_price`, `business_hours`, `business_address`). A fact is used only if it is `PUBLIC`, approved, sourced, current, and belongs to the tenant; conflicting facts or any risk flag route to Human Review. The `TemplateGenerator` builds every reply today from the approved facts. The `ReplitGenerator` (provider `REPLIT`) is the adapter for natural wording through Replit AI Integrations; it is intentionally switched off and reports `INFERENCE_PROVIDER_UNAVAILABLE` until its endpoint, privacy and timeout checks pass, so replies fall back to the approved template. Once enabled, any generated draft that does not preserve the approved facts and evidence exactly will still fall back to the template. Custom quotes, discounts and delivery guarantees always need SME review.

### 13. Forecasting and Predictive Alerts

`backend/app/forecasting/` is read-only and advisory:

- Baselines: `Naive`, `SeasonalNaive` and `MovingAverage`.
- **Expanding-origin backtesting** with no access to later observations at each origin, and model comparison on the same holdout.
- Source validation of the supplied history before any forecast is made.
- Risk alerts for demand, forward stockout or expiry, capacity or deadline (delegated to the feasibility engine), and supplier reliability.

A forecast risk is never treated as a confirmed disruption, and it never triggers approval or execution by itself.

### 14. Decision Memory

`backend/app/decision_memory/` builds a case from exact stage references (message → decision → approval → action → outcome) taken from one consistent read snapshot. Retrieval of similar past cases is deterministic and runs only after evidence and policy gates. An outcome is reconciled only with independent operational evidence, and lessons report counts with explicit denominators and limitations. Governance suggestions are proposals only; the module has no write or execution path.

### 15. Commitment Registry, Audit and Activity

Every commitment has one identity, a version number and **five independent state dimensions** — agreement, feasibility, risk, recovery and fulfilment — each with its own allowed transitions. Every consequential change writes an audit record and an outbox event in the same transaction. The **Activity** page (`/activity`) and `GET /v1/commitments/{id}/timeline` show who did what, when, and on which version.

```mermaid
stateDiagram-v2
    direction LR

    state "Agreement (Core)" as AGR {
        state "REQUESTED" as A_REQ
        state "OFFERED" as A_OFF
        state "CONFIRMED" as A_CON
        state "REJECTED" as A_REJ
        state "CANCELLED" as A_CAN
        [*] --> A_REQ
        A_REQ --> A_OFF : SME offer or revised proposal
        A_OFF --> A_CON : exact assent to this version
        A_OFF --> A_REJ : customer rejects
        A_REQ --> A_CAN
        A_OFF --> A_CAN
        A_CON --> A_CAN
    }

    state "Recovery approval" as APR {
        state "PENDING" as P_PEN
        state "APPROVED" as P_APP
        state "REJECTED" as P_REJ
        state "EXPIRED" as P_EXP
        state "INVALIDATED" as P_INV
        [*] --> P_PEN
        P_PEN --> P_APP : APPROVE_PLAN
        P_PEN --> P_REJ
        P_APP --> P_EXP : approval window ends
        P_APP --> P_INV : plan or snapshot changed
    }

    state "Recovery execution" as EXE {
        state "VALIDATED" as E_VAL
        state "EXECUTING" as E_RUN
        state "VERIFYING" as E_VER
        state "SUCCEEDED" as E_OK
        state "FAILED" as E_FAIL
        state "NEEDS_REPLAN" as E_RE
        [*] --> E_VAL : EXECUTE_APPROVED_PLAN revalidates
        E_VAL --> E_RUN
        E_RUN --> E_VER
        E_VER --> E_OK
        E_VER --> E_FAIL
        E_VAL --> E_RE : stale data
    }

    state "Outbound message" as MSGS {
        state "DRAFT" as M_DR
        state "PENDING_APPROVAL" as M_PA
        state "QUEUED" as M_Q
        state "SENT" as M_S
        state "DELIVERED" as M_D
        state "DELIVERY_UNKNOWN" as M_U
        [*] --> M_DR
        M_DR --> M_PA
        M_PA --> M_Q
        M_Q --> M_S
        M_S --> M_D
        M_S --> M_U
    }

    state "Customer response" as CNF {
        state "AWAITING_RESPONSE" as C_AW
        state "ACCEPTED" as C_ACC
        state "REJECTED" as C_REJ
        state "COUNTEROFFER_RECEIVED" as C_CO
        state "CLARIFICATION_REQUIRED" as C_CL
        [*] --> C_AW
        C_AW --> C_ACC
        C_AW --> C_REJ
        C_AW --> C_CO
        C_AW --> C_CL
    }

    state "Fulfilment (Core)" as FUL {
        state "NOT_STARTED" as F_NS
        state "IN_PROGRESS" as F_IP
        state "PARTIALLY_FULFILLED" as F_PF
        state "FULFILLED" as F_OK
        state "UNVERIFIED" as F_UV
        [*] --> F_NS
        F_NS --> F_IP
        F_IP --> F_PF
        F_PF --> F_OK
        F_IP --> F_OK
        F_IP --> F_UV
        F_UV --> F_OK : trusted evidence
    }

    APR --> EXE : APPROVED ≠ EXECUTED
    MSGS --> CNF : SENT ≠ ACCEPTED
    CNF --> AGR : explicit acceptance only
    AGR --> FUL : ACCEPTED ≠ FULFILLED

    note right of AGR
        REQUESTED ≠ CONFIRMED
    end note
```

---

## Innovation

Chat apps carry the conversation, spreadsheets carry the stock, and basic order tools carry a status field. None of them connects a message to a promise, the promise to the resources behind it, and a change to a governed, confirmed recovery. MouManTAI adds that missing layer.

| Need | Chat apps | Spreadsheets | Basic order tools | MouManTAI |
|---|---|---|---|---|
| Understand a messy multilingual order | Staff re-type details | Manual entry | Form fields only | Rules → GLiNER → Qwen3 with exact source spans |
| Check if an order can be fulfilled | — | Manual formulas | Stock count only | Time-phased ATP, lot expiry, BOM and capacity on a versioned snapshot |
| Handle competing orders | — | Gut feeling | First come, first served | CP-SAT portfolios re-validated by the same feasibility engine |
| React to a supplier delay | Someone reads it | Someone recalculates | Status flag | Impact on affected commitments only, ranked recovery options |
| Govern a costly change | Verbal "ok" | — | Single "approve" flag | Version-bound approval and separate execution, both audited |
| Know the outcome | Read back the chat | — | One status | Message, agreement and fulfilment tracked as separate states |

**What is new:**

1. **Evidence-backed commitments with source spans.** Every extracted field stores the message ID, the exact quote and its `[start, end)` offsets, and the method that produced it (`RULE`, `MODEL`, `HUMAN`). A reviewer can always see *why* the system believes a quantity or deadline, and a model quote that does not match the source is rejected.
2. **Cheapest-reliable-layer selective AI.** Deterministic rules handle most messages at no GPU cost. GLiNER runs only when rules leave required terms unresolved, and Qwen3 only when real ambiguity remains. Every skipped or failed stage records a routing reason, and AI never calculates stock, grants authority or certifies delivery.
3. **CP-SAT plans re-validated by the same feasibility engine.** The optimiser searches, but the feasibility engine decides. Every projected portfolio is fingerprinted and checked by the same evaluator used for single orders, so a solver bug or modelling gap cannot produce a plan the business cannot keep.
4. **Version-bound human approval with separate approval and execution records.** One *Approve & Execute* click produces two commands and two audit records. Approval is bound to plan, snapshot and commitment versions, expires, and is consumed once. If the data changes, re-approval is required.
5. **Closed-loop confirmation that tracks agreement and fulfilment separately.** `SENT ≠ ACCEPTED ≠ FULFILLED`. Customer acceptance is matched to an exact proposal version, and fulfilment needs its own evidence. The owner always knows which step a promise is really at.
6. **Decision Memory.** Decisions, approvals, actions and verified outcomes are assembled into cases that can be retrieved for the next similar disruption, with explicit evidence gates and denominators instead of anecdotes.
7. **Complements existing tools instead of replacing them.** SMEs keep WhatsApp, Telegram, Gmail and their spreadsheets. MouManTAI adds commitment assurance on top, and connects to Orbyte through narrow business ports for data, identity and review tasks.

---

## Technical Deep Dive

### How the modules connect

Modules call each other through typed Pydantic contracts and communicate state changes through the **transactional outbox**. A Core write and its outbox event are committed in one database transaction; the worker then delivers the event to registered subscribers.

```mermaid
flowchart LR
    CTX["context<br/>publish order context"] -->|"commitment.context_ready"| CORE[("Commitment Registry")]
    ORD["orders<br/>accept exact terms"] -->|"commitment.created / confirmed"| CORE
    CORE --> OBX["outbox_events<br/>PENDING · PUBLISHED · FAILED · DEAD_LETTER"]
    OBX --> WK["Outbox worker"]
    WK -->|"commitment.confirmed"| P2C["feasibility consumer<br/>p2_confirmed_evaluator"]
    P2C -->|"assessment + impact"| CORE
    WK -->|"commitment.at_risk"| P3T["recovery trigger<br/>p3.recovery_trigger.v1"]
    P3T --> REC["recovery plans<br/>approval · execution"]
    REC -->|"recovery.plan_approved<br/>recovery.communication_requested"| CORE
    WK -->|"confirmation.accepted / rejected /<br/>counteroffer_received"| P5C["core confirmation consumer"]
    P5C -->|"agreement transition"| CORE
    WK -->|"rejection or counteroffer"| P3R["recovery replanning"]
```

The outbox worker (`app/worker.py`, `core/outbox.py`) polls pending events, executes each subscriber, records processed events for idempotency, skips stale events whose commitment version has moved on, retries with exponential back-off (`2^attempt` seconds, capped at one hour), and moves an event to `DEAD_LETTER` after five failed attempts. Dead-lettered events can be requeued.

### Backend modules

| Module | How it works | Connects to |
|---|---|---|
| **`context`** | Ingests messages from channels, stores attachments, runs L0 rules and optional GLiNER/Qwen proposals, reconciles fields to the canonical set (`sku`, `quantity`, `unit`, `requested_delivery_at`), associates messages with verified customers and orders, records versioned human reviews, and publishes eligible contexts to Core. Persistence lives in `postgres_repository.py`. | `channels`, RunPod, `orders`, Core |
| **`conversations`** | Pure, versioned clarification decisions per unresolved issue, plus the factual reply pipeline (`ReplyGenerator`, `TemplateGenerator`, `ReplitGenerator`). | `context`, `communication` |
| **`orders`** | Canonical `OrderTerms`, exact-terms comparison and guard, P1 context → acceptance-candidate mapping, trusted P1 source reader and a read-only status projection. | `context`, Core reservations |
| **`feasibility`** | ATP, BOM, capacity, supplier pipeline and impact calculations over immutable snapshots; Core-backed assessment history and impact readers; consumer for `commitment.confirmed`. | Core, `optimization`, `recovery`, `forecasting` |
| **`optimization`** | Compiles a feasibility-authored constraint spec into CP-SAT, solves FCFS / Profit / Expiry-Aware, digests each result and sends it back through the joint verifier. | `feasibility` |
| **`suppliers` / `sourcing`** | Specification-first offer comparison, delivery-history metrics, dossier, RFQ draft, reply consolidation, selection preview and alternative-supply hand-off. | `recovery`, `communication` |
| **`recovery`** | Persists recovery cases from `commitment.at_risk`, generates and ranks plans, maps them to feasibility proposals, handles approval requests and decisions, executes allow-listed, version-checked internal actions, and hands customer-facing changes to communication. | Core, `feasibility`, `communication` |
| **`communication`** | Communication requests, drafts, message review, send eligibility, durable outbound, confirmations, inbound response processing, follow-ups and recipient preferences. | Core, `recovery`, channels |
| **`core`** | Commitments, proposals, transitions, fulfilment evidence, action evidence, audit, resource reservations, manager approval, policy checks, integration facade and the outbox dispatcher. | every module |
| **`forecasting`** | Baseline forecasts, leakage-free backtests, validated series and risk alerts. | `feasibility` (forward scenarios), `sourcing` (supplier history) |
| **`decision_memory`** | Case assembly, gated retrieval, outcome reconciliation and lesson summaries. | Core audit, `recovery`, `communication` |
| **`operational_reporting`** | Status projections, milestone notification planning, feedback readiness and daily planned-vs-actual reports. | Core, `communication` |
| **`integrations`** | `BusinessDataReader`, `BusinessCommandPort` (reservation command and receipt binding) and `ApprovalNotificationPort` — the narrow seams for Orbyte. | Orbyte, Core |

### Commitment state machine

`core/service.py` defines allowed transitions per dimension. For example, agreement can only move `REQUESTED → OFFERED → CONFIRMED`; fulfilment can never leave `FULFILLED`; recovery must pass `PENDING_APPROVAL` before `EXECUTING`. Unrestricted `PATCH` on a commitment is rejected; every change goes through a typed command (`/proposals`, `/confirm-proposal`, `/record-fulfilment`, `/transitions`) with an expected version, so concurrent edits fail with a version conflict instead of overwriting each other.

### AI and GPU path

```text
backend (EndpointAdapter)                      RunPod Serverless worker
--------------------------                      ------------------------
POST {P1_AI_ENDPOINT_URL}  (/run)  ─────────►   queue job
  body: {"input": InferenceInput,                runpod.serverless.start(handler)
         "policy": {executionTimeout: 90000,      ├─ GLiNER urchade/gliner_multi-v2.1 @ pinned revision
                    ttl: 120000}}                 └─ Qwen/Qwen3-4B-Instruct-2507 @ pinned revision
GET  …/status/{job_id}  (poll, back-off ≤ 3 s)    bf16 on supported GPUs, otherwise fp16
POST …/cancel/{job_id}  (on local timeout)       returns InferenceOutput + runtime metrics
validate_evidence(output, request)
```

- **Transport** (`context/ai/endpoint.py`) — HTTPS only (loopback HTTP allowed for local work), no credentials in URLs, bearer token from `P1_AI_API_KEY`, concurrency of one, **no automatic POST retries**, 128 KiB response budget, local timeout `P1_AI_TIMEOUT_SECONDS` (default 125 s). In `runpod` mode the URL must end in `/run` or `/runsync`; with `/run` the adapter polls `/status/{id}` until `COMPLETED` and sends a best-effort `/cancel/{id}` on timeout.
- **Input bounds** (`protocol.py`) — at most four source messages and 4,000 characters in total; over-budget input is refused rather than silently truncated.
- **Worker image** (`context/ai/Dockerfile`) — digest-pinned `pytorch/pytorch:2.7.1-cuda12.8-cudnn9-runtime` base with pinned `gliner`, `transformers`, `runpod` and related packages from `requirements-gpu.txt`. Models load lazily on the first job.
- **Stage control** — `P1_AI_ENABLED` turns the model path on; `P1_AI_STAGES` selects stages. The code default is `gliner` only, so Qwen (L2) requires an explicit opt-in; `.env.example` and Docker Compose set `gliner,qwen`.
- **Failure codes** — only fixed codes cross the boundary (`timeout`, `endpoint_http_error`, `model_mismatch`, `evidence_mismatch`, …); provider bodies and credentials are never echoed. On any failure, extraction keeps the rule fields and routes to Human Review.

### Security and trust boundaries

- **Tenant scoping and roles** — every request carries a tenant and actor; Owner, Manager and Staff permissions are checked on the server (`core/policy.py`), not just hidden in the UI.
- **Identity mode** — for local runs and CI, identity comes from `X-Tenant-ID` / `X-Actor-ID` headers, enabled only when `MOUMANTAI_SYNTHETIC_MODE=1`; otherwise those routes return `403 SYNTHETIC_IDENTITY_DISABLED`. **Header-based identity is for local runs and tests only and is not production authentication.** In an Orbyte deployment, identity is supplied by the Orbyte identity port.
- **Server-owned keys** — the isolated end-to-end routes (`/assess`, supplier-delay events) are mounted only when `MOUMANTAI_ISOLATED_E2E=1` and require a server-owned key of at least 32 characters.
- **Consistent errors** — every error returns `{code, message, correlation_id, details}`; validation errors return locations only, never echoing input that may contain personal data.
- **Secrets** — `.env.example` holds placeholders only, and CI scans it for real key patterns.

### Frontend

The React 19 SPA (`frontend/src`) uses React Router 7 and TanStack Query 5. `shared/api.ts` adds tenant and actor headers and normalises errors; the Vite dev server proxies `/v1` and `/health` to the API.

| Feature folder | Pages and components |
|---|---|
| `features/overview` | Command Center overview — commitments needing attention by category and severity |
| `features/context` | `DurableInbox`, `AttachmentViewer`, `ExtractionProvenance`, `FieldEvidence`, `ReviewDrawer`, `HumanReviewPage`, `OrderContextDetail`; generated OpenAPI types in `generated/` |
| `features/orders` | `OrderQueuePage`, `OrderDetailPage`, `OrderDecisionWorkspace`, `CalendarSchedulingPage`, `PortfolioComparisonPage` |
| `features/feasibility` | `CommitmentFeasibilityPage`, `ImpactDetailPage` |
| `features/suppliers` | `SupplierWorkspace` — directory, offer comparison, supplier detail |
| `features/recovery` | `RecoveryCaseRoutePage`, `RecoveryPage` (plans, ranking, approval) |
| `features/communication` | `CommunicationCenterPage`, `ManagerReview`, `OutboundPanel`, `ConfirmationWorkspacePage`, `FollowUpQueuePage`, `RecipientPreferences` |
| `features/activity` | `ActivityPage` — audit timeline |
| `shared/` | `ApprovalActionControl`, `ConfirmationDialog`, `VersionConflictBanner`, `EvidenceTierBadge`, `StatusBadge`, `StateTimeline`, `UncertaintyNote`, `ErrorBoundary` |

Design rules carried through the UI: pending states never use a success colour; a version conflict shows a banner instead of overwriting; uncertainty is shown explicitly; and every consequential action asks for confirmation first.

---

## Technical Stack

### Frontend

| Technology | Use |
|---|---|
| React 19 + TypeScript 5.9 | SME Command Center SPA |
| Vite 7 | Dev server with API proxy, production build |
| React Router 7 | Workspace routing |
| TanStack Query 5 | Server state, caching, mutations |
| openapi-typescript | Types generated from the backend OpenAPI schema |
| Vitest 5 + Testing Library + jsdom | Component and integration tests |

### Backend

| Technology | Use |
|---|---|
| Python 3.11–3.14 | Runtime (`requires-python = ">=3.11,<3.15"`) |
| FastAPI + Uvicorn | HTTP API, channel webhooks, background channel workers |
| Pydantic v2 + pydantic-settings | Strict contracts (`extra="forbid"`), settings |
| SQLAlchemy 2 + psycopg 3 | ORM and PostgreSQL driver |
| Alembic | Versioned schema migrations, single-head check in CI |
| Google OR-Tools CP-SAT | Multi-order optimisation (`optimization` extra) |
| httpx | RunPod, Telegram, Gmail and WhatsApp clients |

### Database

| Technology | Use |
|---|---|
| PostgreSQL 16 | Primary store — Docker Compose `postgres:16-alpine` locally, `postgres:16` service in GitHub Actions |
| SQLite | Fallback for local tests when no PostgreSQL driver is available |

### AI / Compute

| Technology | Use |
|---|---|
| GLiNER `urchade/gliner_multi-v2.1` | L1 multilingual entity spans |
| Qwen `Qwen/Qwen3-4B-Instruct-2507` | L2 selective interpretation of ambiguous messages |
| RunPod Serverless | GPU endpoint for GLiNER and Qwen (async `/run` queue) |
| PyMuPDF · PaddleOCR | PDF text and image OCR for attachments |
| Replit AI Integrations | Reply-wording adapter behind `ReplyGenerator`, switched off until verified (templates used today) |

### Hosting / Dev

| Technology | Use |
|---|---|
| Replit | Shared Workspace, Replit Agent, Deployments, Secrets |
| Docker Compose | `db`, `api` and `worker` services |
| GitHub Actions | Backend, PostgreSQL, optimisation, frontend and hygiene checks |

---

## Installation

### Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Docker + Docker Compose | Docker Desktop (Linux engine) or Docker Engine | Runs `db`, `api`, `worker` |
| Python | 3.11 – 3.14 | Only for running the backend outside Docker |
| Node.js + npm | Node 20+ | Frontend |
| PostgreSQL | 16 | Provided by Compose; bring your own when running on Replit |

Default ports: PostgreSQL `5433` (host) → `5432` (container), API `8000`, Vite `5173`.

### Option 1 — Run on Replit (Recommended)

1. Open the [Replit Project]([REPLIT PROJECT URL]) or import this repository via **Create → Import from GitHub**.
2. In **Secrets**, add the variables listed in [`.env.example`](.env.example) — at minimum `DATABASE_URL` (a PostgreSQL 16 database), and for GPU extraction `P1_AI_ENABLED=true`, `P1_AI_ENDPOINT_MODE=runpod`, `P1_AI_ENDPOINT_URL`, `P1_AI_API_KEY` and `P1_AI_STAGES=gliner,qwen`.
3. In the Shell, install, migrate and start the API:

   ```bash
   python -m pip install -e './backend[dev,optimization]'
   python -m alembic -c backend/alembic.ini upgrade head
   python scripts/seed_demo.py
   python -m uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port 8000
   ```

4. In a second Shell tab, start the frontend:

   ```bash
   cd frontend && npm ci && npm run dev
   ```

### Option 2 — Run Locally with Docker Compose

```bash
git clone https://github.com/jiahui-1101/MouManTAI.git
cd MouManTAI
cp .env.example .env                 # then set a local PostgreSQL password
export MOUMANTAI_SYNTHETIC_MODE=1    # header-based local identity for the Vite frontend
export P1_AI_ENABLED=false           # rules-only extraction; set true + endpoint for GPU extraction
docker compose up -d --build
curl http://localhost:8000/health    # {"status":"ok","service":"moumantai-api",...}
```

Windows PowerShell:

```powershell
Copy-Item .env.example .env
$env:MOUMANTAI_SYNTHETIC_MODE = '1'
$env:P1_AI_ENABLED = 'false'
docker compose up -d --build
Invoke-RestMethod http://localhost:8000/health
```

The `api` service runs `alembic upgrade head`, seeds the starter commitments with `scripts/seed_demo.py`, then starts Uvicorn. The `worker` service starts the outbox dispatcher once the API is healthy.

Then start the frontend:

```bash
cd frontend
npm ci
npm run dev          # Windows PowerShell: npm.cmd run dev
```

Open `http://localhost:5173/overview`. The frontend calls `http://localhost:8000` by default; set `VITE_API_BASE_URL` before starting Vite to change it.

### Option 3 — Backend outside Docker

```bash
docker compose up -d db
python -m venv backend/.venv
backend/.venv/bin/python -m pip install -e './backend[dev,optimization]'   # Windows: backend\.venv\Scripts\python.exe
export DATABASE_URL='postgresql+psycopg://moumantai:<local-password>@localhost:5433/moumantai'
export MOUMANTAI_SYNTHETIC_MODE=1
backend/.venv/bin/python -m alembic -c backend/alembic.ini upgrade head
backend/.venv/bin/python scripts/seed_demo.py
backend/.venv/bin/python -m uvicorn app.main:app --app-dir backend --reload --port 8000
```

Use the same `DATABASE_URL` for migration, seed and API. `scripts/run_backend.py` is a shortcut that loads `.env` and starts Uvicorn.

### Run Tests

```bash
python -m pytest backend/tests -q                 # from the repository root
cd frontend && npm run typecheck && npm test && npm run build
```

---

## Environment Variables

All values below are placeholders. Copy `.env.example` to `.env` locally, or add the keys to **Replit Secrets**. Never commit real values.

| Variable | Example / default | Purpose |
|---|---|---|
| `POSTGRES_DB` | `moumantai` | Database name for the Compose `db` service |
| `POSTGRES_USER` | `moumantai` | Database user |
| `POSTGRES_PASSWORD` | `replace_with_local_postgres_password` | Database password |
| `POSTGRES_HOST` | `localhost` | Database host |
| `POSTGRES_PORT` | `5433` | Host port mapped to container port 5432 |
| `DATABASE_URL` | `postgresql+psycopg://moumantai:<password>@localhost:5433/moumantai` | SQLAlchemy URL (SQLite `sqlite:///./test_live.db` for local fallback) |
| `HOST` / `PORT` | `0.0.0.0` / `8000` | API bind address |
| `ENVIRONMENT` | `development` | `production` disables the isolated preview routes |
| `LOG_LEVEL` | `info` | Log level |
| `CORS_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173,http://localhost:3000` | Allowed browser origins |
| `VITE_API_BASE_URL` | `http://localhost:8000` | Frontend API base URL |
| `P1_AI_ENABLED` | `true` | Enable the GLiNER/Qwen proposal path (`false` = rules only) |
| `P1_AI_ENDPOINT_MODE` | `runpod` | `runpod` (async queue) or `direct` (synchronous HTTP) |
| `P1_AI_ENDPOINT_URL` | `https://api.runpod.ai/v2/replace_with_runpod_endpoint_id/run` | Inference endpoint; must end in `/run` or `/runsync` in `runpod` mode |
| `P1_AI_API_KEY` | `replace_with_runpod_api_key` | RunPod API key (bearer token) |
| `P1_AI_STAGES` | `gliner,qwen` | Ordered stages; code default is `gliner` only |
| `P1_AI_TIMEOUT_SECONDS` | `125` | Client-side inference timeout (code default, max 180) |
| `P1_PRODUCT_CATALOG_PATH` | `/app/app/context/catalogs/catalog.json` | Product alias catalogue (set by Compose) |
| `P1_DATABASE_URL` | `postgresql+psycopg://…/moumantai` | Database for P1 services |
| `P1_TEST_DATABASE_URL` | `postgresql+psycopg://…/moumantai_test` | Disposable database for P1 PostgreSQL tests |
| `TELEGRAM_BOT_TOKEN` | `replace_with_telegram_bot_token` | Telegram bot |
| `TELEGRAM_MODE` | `polling` | `polling` or webhook |
| `TELEGRAM_WEBHOOK_URL` / `TELEGRAM_WEBHOOK_SECRET` | commented out | Webhook mode settings |
| `TELEGRAM_POLL_INTERVAL` / `TELEGRAM_POLL_TIMEOUT` | `2.0` / `20` | Polling cadence |
| `TELEGRAM_TENANT_ID` / `TELEGRAM_AUTO_START` | `synthetic_tenant_a` / `true` | Tenant and auto-start |
| `GMAIL_CLIENT_ID` / `GMAIL_CLIENT_SECRET` | `replace_with_google_oauth_client_id` / `…secret` | Google OAuth client |
| `GMAIL_REFRESH_TOKEN` | `replace_with_google_oauth_refresh_token` | Offline access |
| `GMAIL_REDIRECT_URI` | `http://localhost:8000/v1/channels/gmail/oauth/callback` | OAuth callback |
| `GMAIL_POLL_INTERVAL` / `GMAIL_QUERY` | `30.0` / `label:INBOX` | Polling settings |
| `GMAIL_TENANT_ID` / `GMAIL_AUTO_START` | `synthetic_tenant_a` / `true` | Tenant and auto-start |
| `WHATSAPP_PHONE_NUMBER_ID` | `replace_with_whatsapp_phone_number_id` | WhatsApp Cloud API number |
| `WHATSAPP_ACCESS_TOKEN` | `replace_with_whatsapp_permanent_access_token` | Cloud API token |
| `WHATSAPP_APP_SECRET` | `replace_with_meta_app_secret` | HMAC signature verification |
| `WHATSAPP_VERIFY_TOKEN` | `replace_with_meta_webhook_verify_token` | Webhook challenge |
| `WHATSAPP_TENANT_ID` | `synthetic_tenant_a` | Tenant |
| `OUTBOX_POLL_INTERVAL` | `1.0` | Outbox worker poll interval (seconds) |
| `INTEGRATION_MODE` | `SYNTHETIC` | Business integration mode |
| `MOUMANTAI_SYNTHETIC_MODE` | `0` | `1` enables header-based identity for local runs and tests only |
| `MOUMANTAI_ISOLATED_E2E` | `0` | `1` mounts isolated end-to-end routes and worker subscribers |
| `MOUMANTAI_ISOLATED_E2E_KEY` | `replace_with_server_owned_key_of_at_least_32_chars` | Server-owned key for isolated routes |
| `LIVE_API` | `0` | `1` runs HTTP smoke tests against port 8000 |
| `P4_RUNTIME_MODE` / `APP_ENV` / `P4_SYNTHETIC_TENANTS` | `SYNTHETIC` / `synthetic` / `synthetic_tenant_a` | Communication runtime settings for local development |

---

## Deployment

```mermaid
flowchart LR
    subgraph USER["Browser"]
        UI["React SPA<br/>SME Command Center"]
    end

    subgraph VITE["Vite dev server · :5173"]
        PX["Proxy /v1 · /health"]
    end

    subgraph COMPOSE["Docker Compose · docker-compose.yml"]
        DB[("db<br/>postgres:16-alpine<br/>host 5433 → 5432<br/>volume moumantai-postgres<br/>healthcheck pg_isready")]
        API["api<br/>backend/Dockerfile · python:3.11-slim<br/>alembic upgrade head → seed → uvicorn :8000<br/>healthcheck /health"]
        WK["worker<br/>python -m app.worker<br/>outbox dispatcher"]
    end

    subgraph EXT["External services"]
        RP["RunPod Serverless<br/>/run · /status · /cancel"]
        CHN["Telegram · Gmail · WhatsApp Cloud API"]
        RAI["Replit AI Integrations<br/>adapter switched off until verified"]
        ORB["Orbyte business ports"]
    end

    subgraph CI["GitHub Actions"]
        GHA["pytest · CP-SAT · Vitest · tsc · build<br/>postgres:16 service"]
    end

    UI --> PX --> API
    API -->|"depends_on: healthy"| DB
    WK -->|"depends_on: api healthy"| API
    WK --> DB
    API --> RP
    CHN --> API
    API --> RAI
    API <--> ORB
```

| Target | How |
|---|---|
| **Replit Deployments** | Target host for the live prototype — link pending: [LIVE APP URL]. `DATABASE_URL`, `P1_AI_*` and channel credentials go in Replit Secrets; the database is PostgreSQL 16, migrated with `alembic upgrade head`. |
| **Docker Compose** | `docker compose up -d --build` starts `db`, `api` and `worker`, with health-gated start-up order. |
| **RunPod GPU worker** | Build `backend/app/context/ai/Dockerfile` from the repository root, deploy it as a RunPod Serverless endpoint, and point `P1_AI_ENDPOINT_URL` at `https://api.runpod.ai/v2/<endpoint-id>/run`. |
| **Channels** | Telegram polling needs no public URL; Telegram webhook and WhatsApp webhook need the public API URL (`/v1/channels/telegram/webhook`, `/v1/channels/whatsapp/webhook`). |

---

## API Reference

All business routes are under `/v1`. Requests carry `X-Tenant-ID` and `X-Actor-ID`; mutating commands carry an expected version and, where relevant, an idempotency key. The full route inventory is in [`docs/BACKEND_ROUTE_INVENTORY.json`](docs/BACKEND_ROUTE_INVENTORY.json), and FastAPI serves interactive docs at `/docs`.

### System

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/health` | Liveness and version |

### Channels

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/v1/channels/status` | Channel readiness and diagnostics |
| POST | `/v1/channels/poll` | Trigger one polling cycle |
| POST | `/v1/channels/telegram/webhook` | Telegram updates (secret-token verified) |
| GET · POST | `/v1/channels/whatsapp/webhook` | Meta challenge and HMAC-verified messages |
| GET | `/v1/channels/gmail/oauth/authorize` · `/oauth/callback` · `/verify` | Gmail OAuth flow |

### Messages, contexts and attachments

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/v1/messages/ingest` | Ingest a message |
| GET | `/v1/messages` · `/v1/messages/{message_id}` | List and read messages |
| POST | `/v1/messages/{message_id}/process` | Run extraction |
| GET | `/v1/messages/{message_id}/extraction` · `/attempts` | Extraction result and attempts |
| GET · POST | `/v1/messages/{message_id}/association` | Customer and order association |
| POST | `/v1/contexts/from-message/{message_id}` | Create order context |
| GET · PATCH | `/v1/contexts/{context_id}` | Read or amend a context |
| GET | `/v1/contexts/by-order/{order_id}` · `/v1/contexts/catalog` | Lookup and product catalogue |
| POST | `/v1/contexts/{context_id}/review` · `/publish` | Human review and publish to Core |
| GET | `/v1/contexts/{context_id}/versions` · `/reviews` | Version and review history |
| POST | `/v1/attachments/upload` · `/v1/attachments/{evidence_ref}/extract` | Upload and extract |
| GET | `/v1/attachments/{evidence_ref}/content` · `/metadata` · `/page-count` · `/pages/{n}` · `/extraction` | Evidence access |

### Commitments and Core

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/v1/overview` | Command Center summary |
| POST · GET | `/v1/commitments` | Create and list commitments |
| GET | `/v1/commitments/{id}` · `/timeline` | Commitment and audit timeline |
| POST | `/v1/commitments/{id}/proposals` | Offer a versioned proposal |
| POST | `/v1/commitments/{id}/confirm-proposal` | Record exact customer assent |
| POST | `/v1/commitments/{id}/record-fulfilment` | Record fulfilment with evidence |
| POST | `/v1/commitments/{id}/transitions` | Guarded state transition |
| POST | `/v1/commitments/{id}/recovery/start` · `/recovery/execute` | Core recovery lifecycle |
| POST | `/v1/integration/context-updated` | Context update from P1 |
| GET | `/v1/audit` · `/v1/events/{event_id}` | Audit records and domain events |
| GET | `/v1/resources/snapshot` | Stock and reservation snapshot |
| POST | `/v1/resources/reserve` | Reserve resources |

### Feasibility

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/v1/commitments/{id}/assessments` · `/assessments/{assessment_id}` | Assessment history |
| GET | `/v1/impacts/{impact_id}` | Impact detail |
| POST | `/v1/commitments/{id}/assess` | Run an assessment (isolated mode, server key) |
| POST | `/v1/operations/events/supplier-delay` | Supplier delay → impact (isolated mode, server key) |

### Recovery

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/v1/recovery/cases/{commitment_id}` · `/trigger` | Recovery case and trigger |
| POST | `/v1/recovery/cases/{commitment_id}/generate` | Generate ranked plans |
| GET | `/v1/recovery/cases/{commitment_id}/plans` | List plans |
| GET | `/v1/recovery/plans/{plan_id}` · `/evaluation` | Plan and feasibility evaluation |
| POST | `/v1/recovery/plans/{plan_id}/approval-requests` | Request approval |
| POST | `/v1/recovery/plans/{plan_id}/approve` · `/reject` · `/request-revision` · `/revoke` | Approval decisions |
| GET | `/v1/recovery/plans/{plan_id}/approvals` | Approval history |
| POST | `/v1/recovery/plans/{plan_id}/execute` | Execute an approved plan |
| GET | `/v1/recovery/plans/{plan_id}/actions` | Executed actions |
| POST | `/v1/recovery/plans/{plan_id}/request-communication` | Hand off to communication |

### Communications, confirmations and follow-ups

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/v1/communications/requests` | Create communication request |
| GET | `/v1/communications` · `/summary` · `/{communication_id}` | List, summary, detail |
| POST | `/v1/communications/{id}/prepare` | Prepare draft |
| GET | `/v1/communications/{id}/drafts/{draft_id}` · `/review` · `/send-eligibility` | Draft, review, eligibility |
| POST | `/v1/communications/{id}/drafts/{draft_id}/approve` · `/reject` · `/send` | Review and send |
| GET | `/v1/communications/{id}/outbound` | Outbound attempts |
| GET · POST | `/v1/communications/recipient-preferences` | Recipient preferences |
| GET | `/v1/communications/runtime-capabilities` | Provider capabilities |
| POST · GET | `/v1/confirmations` · `/v1/confirmations/{id}` · `/attempts` | Confirmations |
| POST | `/v1/confirmations/{id}/respond` · `/revoke` · `/v1/confirmations/process-inbound` | Customer responses |
| GET · POST | `/v1/follow-ups` · `/v1/follow-ups/run-due` · `/v1/follow-ups/{task_id}/cancel` | Follow-up scheduling |

---

## Project Structure

```text
MouManTAI/
├── .github/
│   └── workflows/
│       ├── ci.yml                         # Backend, PostgreSQL, CP-SAT, frontend and hygiene jobs
│       ├── backend-forecasting.yml        # Forecasting test suite
│       ├── backend-decision-memory.yml    # Decision Memory test suite
│       └── p1-source-reader-postgres.yml  # P1 reader against migrated PostgreSQL, zero skips
├── backend/
│   ├── Dockerfile                         # python:3.11-slim image for api and worker
│   ├── alembic.ini
│   ├── pyproject.toml                     # moumantai-backend; extras: dev, test, optimization
│   ├── requirements-dev.lock.txt
│   ├── app/
│   │   ├── main.py                        # FastAPI app, routers, CORS, error handlers, /health
│   │   ├── worker.py                      # Outbox dispatcher entrypoint
│   │   ├── db/                            # SQLAlchemy base and session (PostgreSQL, SQLite fallback)
│   │   ├── context/                       # Understand: channels, extraction, AI, review, publish
│   │   │   ├── ai/                        #   protocol, endpoint adapter, routing service, GPU worker + Dockerfile
│   │   │   ├── channels/                  #   Telegram, Gmail, WhatsApp adapters, manager, cursor state
│   │   │   ├── catalogs/catalog.json      #   Multilingual product alias catalogue
│   │   │   ├── experiments/               #   GPU evaluation runners and fixtures
│   │   │   ├── fixtures/                  #   Message fixtures
│   │   │   ├── deterministic_extraction.py#   L0 rules with code-point spans
│   │   │   ├── document_extractor.py      #   PyMuPDF + PaddleOCR
│   │   │   ├── reconciliation.py          #   Canonical field reconciliation
│   │   │   ├── association_service.py     #   Verified customer / order association
│   │   │   ├── core_publisher.py          #   Publication gates into Core
│   │   │   ├── postgres_repository.py     #   P1 persistence
│   │   │   ├── router.py                  #   /v1/messages, /v1/contexts, /v1/attachments
│   │   │   └── tests/
│   │   ├── conversations/                 # clarification.py, replies.py (ReplyGenerator)
│   │   ├── orders/                        # terms.py, context_mapping.py, p1_source_reader.py, status.py
│   │   ├── feasibility/                   # inventory, bom, capacity, impact, supplier_pipeline, consumer
│   │   │   └── tests/
│   │   ├── optimization/                  # cp_sat.py, scaling.py, service.py, validation.py
│   │   │   └── tests/
│   │   ├── suppliers/                     # comparison.py — specification-first offer comparison
│   │   ├── sourcing/                      # history, dossier, rfq, replies, selection, recovery_handoff
│   │   ├── recovery/                      # triggers, durable_plans, ranking, proposal_mapping, durable_actions
│   │   ├── communication/                 # drafting, review, outbound, confirmations, follow-ups
│   │   │   └── tests/
│   │   ├── core/                          # commitments, audit, outbox, reservations, manager_approval, policy
│   │   ├── forecasting/                   # baselines, backtesting, risk, scenarios, source_validation
│   │   │   └── tests/
│   │   ├── decision_memory/               # assembly, retrieval, outcome, lessons, governance
│   │   │   └── tests/
│   │   ├── operational_reporting/         # status projection, milestone planning, daily reports
│   │   │   └── tests/
│   │   └── integrations/                  # business_ports.py — Orbyte seams
│   ├── migrations/
│   │   ├── env.py
│   │   └── versions/                      # 0001_foundation … 0017_p1_real_channel_provenance
│   └── tests/
│       ├── integration/                   # Cross-module and PostgreSQL scenario tests
│       ├── v2_2/                          # Terms, clarification, replies, sourcing, supplier comparison
│       └── test_*.py                      # Registry, outbox, recovery, reservations, migrations, API
├── frontend/
│   ├── index.html · dev.html
│   ├── package.json · package-lock.json
│   ├── vite.config.ts                     # Dev proxy to the API, Vitest config
│   ├── tsconfig*.json
│   ├── public/images/                     # Logos and avatar
│   └── src/
│       ├── App.tsx · main.tsx             # Routes and providers
│       ├── layout/                        # AppShell, Sidebar, navigation
│       ├── pages/                         # OverviewPage, FeaturePlaceholder
│       ├── features/
│       │   ├── overview/                  # Command Center overview
│       │   ├── context/                   # Inbox, Human Review, attachments, provenance
│       │   ├── orders/                    # Queue, detail, decisions, calendar, portfolio
│       │   ├── feasibility/               # Commitment feasibility, impact detail
│       │   ├── suppliers/                 # Directory, comparison, detail
│       │   ├── recovery/                  # Recovery cases and plans
│       │   ├── communication/             # Communication Center, confirmations, follow-ups
│       │   └── activity/                  # Audit timeline
│       ├── shared/                        # API client, auth, approval controls, status UI
│       ├── dev/                           # P1 developer console
│       └── test/                          # Vitest setup
├── contracts/
│   ├── types.ts                           # TypeScript mirror of backend/app/core/schemas.py
│   ├── fixtures/                          # Cross-feature dataset and feasibility example
│   └── README.md
├── docs/
│   ├── requirements/                      # Per-module requirements and v2.2/ source of truth
│   ├── design/                            # Orbyte design system, UI specs, references
│   ├── handoffs/ · planning/ · reports/   # Integration hand-offs and progress reports
│   ├── p1/                                # Extraction pipeline audits and evaluation report
│   ├── rfcs/                              # Constraint spec / joint portfolio RFC
│   ├── evidence/                          # PostgreSQL CI and handshake logs
│   ├── legacy/                            # v1 agent rules
│   ├── BACKEND_ROUTE_INVENTORY.json       # Route inventory
│   ├── BACKEND_SCHEMA_INVENTORY.md
│   ├── REQUIREMENTS_SYSTEM.md
│   ├── MENTORSHIP_PREP.md
│   └── TEAM_LOG.md
├── scripts/
│   ├── seed_demo.py                       # Seeds starter commitments (run by Compose)
│   ├── seed_demo_communication.py         # Seeds communication records
│   ├── reset_and_seed_test_db.py
│   ├── run_backend.py                     # Loads .env and starts Uvicorn
│   ├── evaluate_metrics.py                # Extraction metrics benchmark
│   ├── colab_gpu_worker.py · colab_gliner_standalone.py  # Standalone GPU worker hosts
│   └── start_p1.ps1                       # Windows P1 start helper
├── AZ03-Fix-Review/                       # Staged review fix for the orders feature
├── submission/                            # Official SDC submission PDFs
├── AGENTS.md                              # Repository instructions
├── IMPLEMENTATION_BLUEPRINT.md
├── REQUIREMENTS_SYSTEM.md · REQUIREMENTS_BACKEND.md · REQUIREMENTS_FRONTEND.md
├── REVIEW_DECISIONS.md
├── conftest.py
├── docker-compose.yml                     # db, api, worker
├── .env.example                           # Placeholder configuration
└── README.md
```

---

## Testing & CI

### Local

```bash
# Backend (repository root)
python -m pytest backend/tests -q
python -m pytest backend/app/feasibility/tests backend/app/communication/tests -q
python -m pytest backend/app/optimization/tests -q        # needs the optimization extra (OR-Tools)
python -m pytest backend/app/forecasting/tests backend/app/decision_memory/tests -q

# PostgreSQL-authoritative run (disposable database only)
REQUIRE_POSTGRES=1 TEST_DATABASE_APPROVED=1 \
TEST_DATABASE_URL='postgresql+psycopg://postgres:postgres@localhost:5432/p4_test_moumantai_suite' \
python -m pytest backend/tests -v -rs

# Frontend
cd frontend
npm run typecheck
npm test
npm run build
```

### GitHub Actions

| Workflow / job | What it checks |
|---|---|
| `ci.yml` · **Backend Tests** | `compileall` syntax check, then pytest for `backend/tests`, feasibility and communication (Python 3.12) |
| `ci.yml` · **Backend Tests (PostgreSQL Authoritative)** | `postgres:16` service, single Alembic head check, full backend suite with `REQUIRE_POSTGRES=1`, and a **zero-skipped-tests** gate on the JUnit report |
| `ci.yml` · **Feature Suites** | Feasibility and communication packages |
| `ci.yml` · **Backend Optimization** | Real OR-Tools CP-SAT tests |
| `ci.yml` · **Frontend Checks** | Node 20, `npm ci`, `tsc --noEmit`, Vitest, production build |
| `ci.yml` · **Hygiene & Secret Checks** | `.env.example` scanned for real key patterns; legacy branding check |
| `backend-forecasting.yml` | Forecasting suite |
| `backend-decision-memory.yml` | Decision Memory suite |
| `p1-source-reader-postgres.yml` | P1 source reader against a migrated `postgres:16` database, with minimum discovered tests and zero skips |

Key test areas: amendment protection, stale-version and snapshot races, tenant isolation, duplicate and stale outbox events, approval binding and expiry, legacy execute safety, reservation contention, AI routing and adversarial prompt guards, span validation, multilingual delivery semantics, and cross-module PostgreSQL scenarios.

---

## How We Use Replit *(Required)*

- **Development:** the team builds and reviews MouManTAI in a shared Replit Workspace, with Replit Agent assisting the build, code review and documentation. The pitch deck is built in the same workspace as a Replit slides artifact.
- **Hosting:** **Replit Deployments** is the target host for the live prototype (link pending: [LIVE APP URL]). It connects to a **PostgreSQL 16** database through `DATABASE_URL`, with the schema applied by Alembic migrations.
- **AI:** customer replies are built from approved factual templates today. The `ReplyGenerator` interface already includes a `ReplitGenerator` adapter (provider `REPLIT`) for **Replit AI Integrations** wording; it stays switched off until its endpoint, privacy and timeout checks pass. Once enabled, any wording that does not preserve the approved facts still falls back to the template.
- **Secrets:** all keys (`DATABASE_URL`, `P1_AI_API_KEY`, `P1_AI_ENDPOINT_URL`, channel tokens) are stored in Replit Secrets, never in the code.

📄 Proof of use: [`submission/SDC2026_TeamName_Replit_POU.pdf`](submission/SDC2026_TeamName_Replit_POU.pdf)

## How We Use RunPod *(Required)*

- **Workload:** GLiNER multi v2.1 (`urchade/gliner_multi-v2.1`) and Qwen3-4B-Instruct-2507 (`Qwen/Qwen3-4B-Instruct-2507`) inference for entity extraction and message interpretation, both pinned to exact Hugging Face revisions.
- **Setup:** deployed as a **RunPod Serverless Endpoint** from `backend/app/context/ai/Dockerfile` (digest-pinned PyTorch 2.7.1 / CUDA 12.8 base, `runpod` handler). Calls use the asynchronous **`/run`** queue with `/status` polling, a RunPod execution timeout of 90 s and a job TTL of 120 s, and best-effort `/cancel` on a local timeout.
- **Integration:** the backend calls the endpoint with `P1_AI_ENDPOINT_MODE=runpod`, `P1_AI_ENDPOINT_URL` and `P1_AI_API_KEY`, running the stages listed in `P1_AI_STAGES=gliner,qwen`. GLiNER runs only when rules cannot resolve the order, and Qwen only when ambiguity remains. If the endpoint is unavailable, extraction falls back to deterministic rules and Human Review.

📄 Proof of use: [`submission/SDC2026_TeamName_Runpod_POU.pdf`](submission/SDC2026_TeamName_Runpod_POU.pdf)

---

## Challenges & Learnings

- **Keeping AI useful without letting it decide facts:** models propose, deterministic rules and people decide. Exact span validation turned out to be the simplest way to make model output reviewable.
- **Making a solver trustworthy:** every CP-SAT plan is re-validated by the same feasibility engine used for single orders, and exact integer scaling avoids rounding errors in quantities and money.
- **Designing human approval that is safe but not slow:** one **Approve & Execute** click backed by two audited commands, bound to the exact plan and snapshot version.
- **Separating states people usually merge:** treating message sent, customer accepted and order fulfilled as different states removed a whole class of "we thought it was confirmed" errors.
- **Reliable events between modules:** a transactional outbox with idempotent consumers, stale-event checks and dead-lettering kept modules decoupled without losing events.

## Future Improvements

- [ ] Official Orbyte, WhatsApp Business and email provider connectors, including outbound sending through the live channels
- [ ] Switch on Replit AI Integrations reply wording after endpoint, privacy and timeout verification
- [ ] Pilot with real Malaysian SMEs and measure order-to-decision time
- [ ] Supplier RFQ coordination

## Team

| Name          | Role                                   |
| ------------- | -------------------------------------- |
| Wong Jia Hui  | Team Lead · Recovery & approval        |
| Bong Zi Shan  | Message intelligence & customer inbox  |
| Lee Mei Shuet | Feasibility & optimisation             |
| Loh Su Ting   | Communication & customer status        |
| Gan Rui En    | Commitment registry & integration      |

Prepared for the **SDC Hackathon 2026 Domain 2 — Orbyte Smart SME Challenge**, with thanks to **Alpha Red Solutions**.

---

## Submission Checklist

- [x] Team domain and SDG track filled in
- [ ] Team name, slide deck, video, live app and Replit links added
- [ ] Replit and RunPod proof of use in `submission/`
- [x] Preliminary submission (`SDC2026_TeamName_Preliminary.pdf`)
- [x] Technology declaration (`SDC2026_TeamName_TechDeclaration.pdf`)
- [ ] Files renamed with team name
- [ ] "How to Run" verified from a clean environment
- [x] No API keys or secrets committed

## License

Apache License 2.0 — see [LICENSE](LICENSE).
