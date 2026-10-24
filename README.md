> [!IMPORTANT]
> ## 📁 Submission Documents
> The current `main` snapshot does not include a `submission/` directory. Add and verify official SDC 2026 submission files before treating the checklist or proof-of-use links below as complete.

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
  <img alt="RunPod historical inference use" src="https://img.shields.io/badge/Historical%20Inference-RunPod%20Serverless-673AB7?style=for-the-badge">
  <img alt="Qwen3" src="https://img.shields.io/badge/LLM-Qwen3--4B--Instruct--2507-FF6A00?style=for-the-badge">
  <img alt="GLiNER" src="https://img.shields.io/badge/NER-GLiNER%20multi%20v2.1-FFD21E?style=for-the-badge&logo=huggingface&logoColor=black">
  <img alt="Replit development use" src="https://img.shields.io/badge/Development-Replit-F26207?style=for-the-badge&logo=replit&logoColor=white">
  <img alt="Docker" src="https://img.shields.io/badge/Runtime-Docker%20Compose-2496ED?style=for-the-badge&logo=docker&logoColor=white">
</p>

---

## Table of Contents

- [Team Information](#team-information)
- [Links](#links)
- [Track & Problem Statement](#track--problem-statement)
- [Introduction](#introduction)
- [Quick Product Walkthrough](#quick-product-walkthrough)
- [System Flow](#system-flow)
- [System Architecture](#system-architecture)
- [Core Features](#core-features)
- [Innovation](#innovation)
- [Business Impact & Measurement](#business-impact--measurement)
- [Technical Deep Dive](#technical-deep-dive)
- [Implementation Status & Verification Matrix](#implementation-status--verification-matrix)
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
| **SDG Track (1–17)**  | SDG 8 — Decent Work and Economic Growth (8.2, 8.3); relevant alignment with SDG 9.3 |
| **Team Leader**       | Wong Jia Hui                                         |
| **University**        | Universiti Teknologi Malaysia (UTM)                  |
| **Number of Members** | 5                                                    |

## Links

| Resource          | Link                                         |
| ----------------- | -------------------------------------------- |
| GitHub Repository | https://github.com/jiahui-1101/MouManTAI     |
| Replit Project    | Pending verified URL                         |
| Live Prototype    | Pending verified URL                         |
| RunPod Endpoint   | Historical inference use confirmed; endpoint URL and current availability unverified |
| Slide Deck        | Pending verified URL                         |
| Pitching Video    | Pending verified URL                         |

---

## Track & Problem Statement

**Hackathon:** SDC Hackathon 2026
**Domain:** Domain 2 — Orbyte Smart SME Challenge
**SDGs:** SDG 8 (Targets 8.2 and 8.3); relevant SDG 9 alignment (Target 9.3, small-enterprise integration into value chains and markets). This is intended alignment, not a claim of measured SDG impact.
**Project Name:** MouManTAI
**Solution Type:** AI-assisted operations layer — FastAPI modular monolith + React SME Command Center + PostgreSQL + optional external inference + OR-Tools optimisation

### Problem

In 2025, Malaysia had 1,292,580 MSMEs, 96.2% of all establishments, and MSMEs contributed 39.7% of GDP, according to SME Corp Malaysia and DOSM's 2025 statistics. A separate historical estimate said about 77% of MSMEs remained at a basic digitalisation stage; the 2021 source attributes this figure to consulting-firm estimates but does not identify the underlying firm or method, so it should not be read as a 2026 measurement. [SME Corp Malaysia, Profile of MSMEs in 2015–2025](https://smecorp.gov.my/index.php/en/policies/2020-02-11-08-01-24/profile-and-importance-to-the-economy) · [DOSM, MSMEs Performance 2025](https://www.dosm.gov.my/site/downloadrelease?id=micro-small--medium-enterprises-msmes-performance-2025&lang=English) · [SME Corp Malaysia, Challenges in Digital Adoption (2021)](https://www.smecorp.gov.my/index.php/en/resources/2015-12-21-10-55-22/news/4461-challenges-in-digital-adoption) · [UN SDG 9, Target 9.3](https://sdgs.un.org/goals/goal9).

In a typical catering SME, one customer promise is spread across a WhatsApp chat, a stock spreadsheet and a separate supplier conversation. Owners rebuild orders by hand, accept orders they cannot fulfil, and scramble when a supplier is late. MouManTAI addresses this operational problem; its business outcomes remain a value hypothesis until measured with real SMEs.

The work is spread across three disconnected places:

- **Conversations** — customers and suppliers on WhatsApp, Telegram and email, in English, Bahasa Malaysia and Chinese, often in the same thread.
- **Operational records** — stock, lot expiry, recipes / bills of materials, production capacity, incoming supply and existing orders, usually in spreadsheets.
- **Human decisions** — an owner deciding whether to accept an order, pay more for another supplier, or ask a customer to accept new terms.

When a supplier is late, a reminder does not answer the real questions: **which promises are affected, which alternatives are actually feasible, who approved the change, did the customer agree to the new terms, and was the order actually delivered?**

---

## Introduction

### Solution

MouManTAI connects **Customer, SME and Supplier** in one evidence-backed commitment workflow — **Understand → Decide → Anticipate → Recover → Learn**. Deterministic processing handles known cases; Qwen interprets uncertain meaning, with Gemini API fallback on specified Qwen failures and evidence validation before Human Review or an authorized next step. GLiNER can provide additional extraction evidence where useful. A deterministic feasibility engine and Google OR-Tools CP-SAT support the owner's decision; every emergency action requires explicit authorized human plan approval before separate execution.

| Stage | What MouManTAI does |
|---|---|
| **Understand** | Receives customer and supplier messages through Telegram, official WhatsApp Cloud API and Email; processes text and attachments, extracts order terms with source evidence, asks targeted clarification questions, and routes uncertainty to Human Review. |
| **Decide** | Checks clearly labelled Mock stock, lots, BOM and capacity; compares competing plans with OR-Tools CP-SAT; lets an authorized SME accept exact agreed terms after fresh feasibility and a guarded Mock reservation. |
| **Anticipate** | Forecasts demand and supply risk from validated history and raises advisory alerts before a disruption becomes a breach. |
| **Recover** | When verified supplier evidence indicates delay, identifies affected commitments, ranks recovery options by cost, delay and risk, and executes the chosen scoped plan only after explicit human approval and fresh revalidation. |
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

### Quick Product Walkthrough

```mermaid
flowchart LR
    MSG["Customer & Supplier Messages<br/>Telegram · WhatsApp · Email"] --> VERIFY["Verify & Understand<br/>Contact Registry · evidence extraction<br/>deterministic rules · selective AI<br/>clarification / Human Review"]
    VERIFY --> DECIDE["Decide & Commit<br/>P2 over Mock resources<br/>CP-SAT advice · exact-term SME acceptance<br/>guarded reservation"]
    DECIDE --> RECOVER["Anticipate & Recover<br/>demand and supplier risk<br/>impact · ranked alternatives<br/>authorized approval · separate revalidated execution"]
    RECOVER --> COMM["Communicate & Learn<br/>authorized same-origin message<br/>exact assent · independent fulfilment evidence<br/>audit · Decision Memory"]
```

For example, a customer orders through WhatsApp. MouManTAI preserves the message, extracts terms with source evidence, checks available Mock resources, and presents the request for SME acceptance. Later, a verified supplier reports a delivery delay. MouManTAI identifies affected commitments, proposes feasible recovery alternatives, and executes only an explicitly approved plan. It contacts the customer through the originating channel and tracks customer agreement separately from actual fulfilment. The final Telegram, WhatsApp and Email channels are real API integration targets; Orbyte inventory, BOM and capacity remain Mock/Synthetic.

---

## System Flow

Target end-to-end journey for one commitment. The identity gate below safely persists inbound messages first; verified contacts may continue to the customer or supplier workflow. Unverified content may receive non-authoritative analysis, but cannot trigger commitment, supplier-authority or customer-assent actions. Current implementation and evidence tiers are in the [Implementation Status & Verification Matrix](#implementation-status--verification-matrix).

For first contact, an authorized human must confirm the Customer or Supplier role, tenant association and immutable channel identifiers; record the evidence, reviewer and audit decision. Rejected, suspicious or ambiguous identities stay held or enter review. Do not grant supplier authority, accept customer assent or merge cross-channel contacts from name similarity or AI confidence alone; cross-channel linking requires verified identity plus trustworthy Order ID/context.

```mermaid
flowchart LR
    IN["Provider inbound<br/>Telegram · WhatsApp Cloud API · Email"] --> DUR["Durable raw message<br/>provider IDs · provenance · tenant routing"]
    DUR --> CR{"Contact Registry<br/>identity and role verified?"}
    CR -- "Verified" --> MI["Evidence-based analysis<br/>preserve role · tenant · channel identity"]
    CR -- "Unknown / unverified" --> FHR["First-contact Human Review<br/>preserve message · confirm Customer or Supplier"]
    FHR -- "Authorized confirmation + audit" --> MI
    FHR -- "Rejected / suspicious / ambiguous" --> HOLD["Hold / reject / escalate<br/>no supplier authority or customer assent"]
    CR -- "Rejected / suspicious / ambiguous" --> HOLD
    MI --> ROUTE{"Relevant verified workflow?"}
    ROUTE -- "Customer order" --> DRAFT["OrderRequest draft<br/>every field has source evidence"]
    ROUTE -- "Supplier incident" --> SUP["Supplier delay evidence<br/>verified identity and context"]
    DRAFT --> COMPLETE{"Information<br/>complete?"}
    COMPLETE -- "No" --> CLAR["Targeted clarification<br/>per unresolved issue"]
    CLAR -- "Progress" --> COMPLETE
    CLAR -- "2 answered attempts<br/>without progress" --> HR["Human Review"]
    HR --> PA
    COMPLETE -- "Yes" --> PA["Pending Acceptance"]
    PA --> FEAS["Feasibility engine<br/>Mock stock · lots · BOM · capacity"]
    FEAS <--> OPT["CP-SAT portfolio<br/>FCFS · Profit · Expiry-Aware"]
    FEAS --> DEC{"SME decision<br/>on exact terms"}
    DEC -- "Accept exact agreed terms" --> RES["Guarded Mock reservation<br/>Commitment CONFIRMED"]
    DEC -- "Reject" --> INF["Customer informed"]
    RES --> MIL["Factual status milestones"]
    SUP --> IMP["Impact on affected<br/>commitments only"]
    RES -.-> IMP
    IMP --> REC["Recovery options<br/>cost · delay · risk"]
    REC --> AE["Approve & Execute<br/>two audited commands"]
    AE --> CONF["Approved same-origin proposal<br/>customer reply is separate assent"]
    CONF --> FUL["Verified fulfilment"]
    MIL --> FUL
    FUL --> DM["Decision Memory"]
```

---

## System Architecture

MouManTAI's target is a **modular monolith**: one FastAPI application with clearly owned modules, one PostgreSQL 16 database, and durable asynchronous processing through an outbox/worker. Modules talk through typed contracts and outbox events, not shared mutable state. Telegram, official Meta WhatsApp Cloud API test number, and Email are real transport targets; Orbyte inventory and external business authority remain explicitly Mock/Synthetic for this hackathon. Heavy model inference may run outside the API when a RunPod endpoint is configured and verified.

```mermaid
flowchart TB
    subgraph CH["Channels"]
        direction LR
        TG["Telegram Bot API<br/>polling or webhook"]
        GM["Email providers<br/>Gmail inbound adapter; evaluate Resend inbound"]
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
        LLM["Qwen semantic API<br/>Gemini fallback on specified failure"]
        RP["Optional RunPod compute<br/>configure and verify before use"]
        RAI["Optional Replit reply wording<br/>approved templates remain safe default"]
        ORB["Orbyte business data<br/>MOCK / SYNTHETIC<br/>inventory · BOM · capacity"]
    end

    CH --> CTX
    FE <-->|"REST /v1 · TanStack Query"| API
    CTX --> LLM
    CTX -. optional configured compute .-> RP
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
| **Real communication channels** | Telegram Bot API, official WhatsApp Cloud API test number, and real Email. Customer and supplier messages use their provider events; replies use the originating channel when permitted. An API acknowledgment is not delivery, assent or fulfilment. |
| **Current adapter starting points** | Telegram polling/webhook and WhatsApp webhook code, plus Gmail OAuth/polling code. Evaluate Resend inbound first for Email; a verified outbound provider and thread correlation are required. Adapter code alone does not establish real provider E2E; see the status matrix. |
| **Mock business authority** | Orbyte inventory, BOM, capacity, supplier availability, resource reads/reservations and receipts use deterministic tenant/version-scoped Mock data and adapters. Internal P2, CP-SAT, approval, guarded reservation logic, PostgreSQL transitions and audit are real application behavior over disclosed Mock inputs. |
| **Frontend** | One SME Command Center with sidebar workspaces: Dashboard, Inbox, Orders, Planning, Suppliers, Recovery, Communications, Insights. Customers and suppliers interact through messaging, so no separate portal is required. |
| **Understand** | `context`, `conversations` and `orders` turn messages into versioned, evidence-backed order contexts and canonical `OrderTerms`. |
| **Decide** | `feasibility` is the single calculation authority; `optimization` searches multi-order portfolios; `suppliers` and `sourcing` compare offers against SME hard requirements. |
| **Anticipate · Recover · Learn** | `forecasting`, `recovery`, `communication`, `decision_memory` and `operational_reporting`. |
| **Core** | The Commitment Registry owns commitment identity, version, the five state dimensions, audit records, resource reservations and the transactional outbox. |
| **Data & workers** | PostgreSQL 16 (SQLAlchemy 2 + psycopg 3, Alembic migrations) and the outbox worker that dispatches events to subscribers with retry, back-off and dead-lettering. |
| **External services** | Configurable Qwen then Gemini API fallback for semantic analysis; optional RunPod compute where configured; optional Replit reply wording with approved factual templates as the safe default; isolated Mock Orbyte business-data ports. |

---

## Core Features

### 1. Multi-Channel Customer Inbox

The final system receives real customer and supplier messages through provider adapters. Existing inbound adapter code is in `backend/app/context/channels/`; current evidence and missing E2E gates are summarized in the [verification matrix](#implementation-status--verification-matrix).

- **Telegram Bot API** — long polling via `getUpdates` with a persistent offset (no duplicate updates across restarts), or webhook mode verified with a secret token. Webhook and polling conflicts are resolved automatically.
- **Email** — retain the Gmail API OAuth/polling adapter (token refresh, history cursor, pagination and deduplication). Evaluate Resend inbound first for hosted/test receipt, body and attachment retrieval; select and verify legitimate outbound sending separately, preserving `Message-ID`, `In-Reply-To`, `References` and thread correlation.
- **WhatsApp Cloud API** — `GET` challenge verification (`hub.verify_token`) and `POST` signature verification with HMAC-SHA256 over the raw body using the Meta app secret.

The target ingestion flow is `Provider webhook/poll → provider authentication → durable raw envelope → tenant/channel routing → deduplication → Contact Registry → attachment processing → deterministic extraction → selective Qwen/Gemini → evidence validation → order/incident routing → Human Review or authorized next action`. Preserve provider/account, immutable sender, message and thread IDs, timestamps, evidence/attachment references, trace/correlation ID and processing state. Webhooks are acknowledged only after durable handoff appropriate to provider retry rules; slow work is asynchronous. A channel manager starts configured inbound workers and stops them on shutdown.

### 2. Message Intelligence — the cheapest reliable layer first

Interpretation follows a strict escalation ladder. A model is called only when cheaper layers cannot resolve the order, and no model output becomes a fact without validation.

```mermaid
flowchart TD
    IN["Stored message<br/>text + attachment text"] --> L0["L0 · Deterministic rules<br/>catalog SKU aliases · quantity · unit<br/>delivery date or deadline · order reference"]
    L0 --> Q0{"Rules resolved all<br/>required terms?"}
    Q0 -- "Yes, or non-order inquiry,<br/>or timezone-only gap" --> NOAI["No model call<br/>routing reason recorded"]
    Q0 -- "No" --> QWEN["Selective Qwen interpretation<br/>bounded request; source evidence"]
    QWEN --> VQ["Schema + evidence validation<br/>source refs · contradictions · policy"]
    VQ -- "Valid and usable" --> RECON["Reconcile with deterministic fields<br/>proposal · duplicate · conflict · rejected"]
    VQ -- "API error · timeout · invalid output" --> GEM["Gemini API fallback<br/>bounded attempt"]
    GEM --> VG["Validate schema + evidence again"]
    VG -- "Valid and usable" --> RECON
    VG -- "Unavailable · invalid · uncertain" --> HR
    NOAI --> HR["Order draft + Human Review<br/>every field keeps its evidence"]
    RECON --> HR
```

- **L0 rules** (`deterministic_extraction.py`) handle multilingual SKU aliases from an approved catalogue (for example "burger", "bgr", "汉堡"), quantities, unit normalisation, timezone-aware delivery dates and deadlines, rescheduling phrases and self-corrections. Every observation stores exact Unicode code-point offsets `[start, end)`.
- **Routing** (`context/ai/service.py`) skips the GPU for non-order inquiries ("berapa harga", "请问多少"), fully resolved orders, unsupported-unit cases that need an authorised human, and timezone-only gaps that a model cannot fix. The reason is stored with the message.
- **Selective semantic route** — when rules cannot settle meaning, Qwen is first; Gemini API is the bounded fallback on Qwen API failure, timeout or structured/schema/evidence validation failure. If neither yields trustworthy evidence, route to Human Review. Existing GLiNER stages may provide extraction evidence where useful; GLiNER does not replace the Qwen-first semantic route.
- **Validation and privacy** — validate permitted output types, schema, source refs, confidence/useability flags and contradictions after either model; valid JSON alone is insufficient. Bound time, attempts, tokens and spend; minimize or redact personal data. If safe redaction is not possible and a model is required, route to Human Review without external disclosure. Model output proposes facts for review and never authorizes business action.

### 3. Evidence-Backed Documents and Attachments

`document_extractor.py` uses **PyMuPDF** for machine-readable PDF text and **PaddleOCR** for images/scanned pages when supported by the runtime. Preserve the original attachment, content/type limits and provenance. Each extraction records an `evidence_ref`, status and source location; OCR text is evidence for review, never proof of payment. If extraction fails, keep the message, mark the attachment `UNVERIFIED` or `EXTRACTION_FAILED`, create Human Review for any dependent facts and continue only with independently supported body text. Never infer an unsupported SKU, price, quantity, delivery term or assent from an unreadable file. Runtime and acceptance coverage are listed in the verification matrix.

### 4. Conversational Ordering and Adaptive Clarification

`conversations/clarification.py` tracks each **`UnresolvedIssue`** (`SKU`, `QUANTITY`, `DELIVERY`, `CHOICE`, `FULFILMENT`) as its own versioned record:

- Deterministic validators — catalogue, allowed units, maximum quantity, business timezone, delivery windows, fulfilment method and address fields — decide whether an answer made progress. Model confidence never does.
- After **two consecutive answered attempts without progress** (`TWO_ANSWERED_NO_PROGRESS`) the issue moves to **Human Review**. Risk flags escalate immediately, and a global budget on questions and conversation age also applies.
- No-reply handling is separate: one deduplicated reminder after the configured delay, then expiry or review. Idle time and failed sends never count as "no progress".

### 5. Human Review and Pending Acceptance

Complete, valid requests go to **Pending Acceptance**; unresolved or risky ones go to a separate **Human Review** queue (`/inbox/human-review`). The review drawer shows the original message, highlighted source spans, rule and model candidates with their method (`RULE`, `MODEL`, `HUMAN`), and any conflicts. Reviewer edits are saved as new context versions with `HUMAN` provenance tied to the current message text. A context is published to the Commitment Registry only after it passes the publication gates in `context/core_publisher.py`.

Identity is handled conservatively (`association_service.py`): an extracted order reference alone never authorises a link, and identity is never inferred from name similarity or model output.

The final **Contact Registry** starts each new person as `UNVERIFIED`. An authorized human confirms Customer or Supplier role, tenant and immutable channel identifiers. Subsequent routing requires the exact verified identity and trustworthy Order ID/context; cross-channel merges require verified identity evidence. Spoofing, mismatches, revocation or ambiguous links fail closed or enter Human Review. Verification actor, time, method, evidence and revocation history are auditable.

### 6. Deterministic Feasibility Engine

`backend/app/feasibility/` is the **single calculation authority** used for new orders, accepted orders, optimisation plans and recovery options. It runs real application algorithms against clearly labelled Mock/Synthetic Orbyte inventory, BOM, capacity and supplier snapshots; no live Orbyte inventory or reservation endpoint is claimed:

- **Inventory ATP** (`inventory.py`) — time-phased available-to-promise across all confirmed competing demand, including lot expiry.
- **BOM expansion** (`bom.py`) — recursive bill-of-materials expansion over an immutable snapshot.
- **Capacity** (`capacity.py`) — exact half-open interval validation of non-preemptible bookings against real working windows, not just a daily minutes budget.
- **Supplier pipeline** (`supplier_pipeline.py`) — incoming supply with typed evidence linkage.
- **Impact** (`impact.py`) — when an operational fact changes, discovers dependent commitments and recalculates before/after feasibility with the same evaluator.
- **Currentness** (`currentness.py`) — every result is tied to a snapshot version; a stale snapshot is rejected.

Results are `FEASIBLE`, `CONDITIONAL`, `INFEASIBLE` or `UNKNOWN`. A timeout or missing data returns `UNKNOWN`, never a false `INFEASIBLE` or a false `FEASIBLE`. The **Commitment Feasibility** (`/commitments/:id`) and **Impact Detail** (`/impact/:id`) pages show material shortages, capacity conflicts and the evidence behind each line.

### 7. SME Decision, Exact-Terms Acceptance and Calendar

`orders/terms.py` defines canonical **`OrderTerms`** with exact decimal arithmetic (no float, at most six fractional digits, no rounding of commercial values) and a deterministic terms hash. SME acceptance requires the expected revision/hash and exact customer-agreed terms: an unchanged original request or a specific versioned proposal to which the customer assented. Changed quantity, SKU, date, price, fees, location or conditions require a separate proposal and exact assent before acceptance; preserve the customer's original terms. `orders/context_mapping.py` maps a reviewed order context to an `AcceptanceCandidate`, and `orders/p1_source_reader.py` reads it only through a trusted tenant scope.

After fresh P2 feasibility, an authorized SME decision and exact-term/version checks, reservation runs through the Core reservation service (`core/reservations.py`: snapshot, reserve, release, consume) against Mock resources. The commitment becomes `CONFIRMED` only after the valid reservation result. The **Order Decision Workspace** and **Calendar** (`/orders`, `/calendar`) show accepted versus pending workload per day and per resource.

### 8. Multi-Order Optimisation with OR-Tools CP-SAT

When orders compete for the same stock or capacity, the SME can compare three portfolio strategies on `/planning/portfolio`:

| Strategy | Objective | Availability rule |
|---|---|---|
| **FCFS** | Respect arrival order | Always available |
| **Profit** | Maximise contribution | Only when sourced revenue and complete incremental cost exist; otherwise `PROFIT_COMPARISON_UNAVAILABLE` |
| **Expiry-Aware** | Use lots before they expire | Only when every lot has an expiry; otherwise `EXPIRY_COMPARISON_UNAVAILABLE` |

`optimization/cp_sat.py` compiles a versioned **`P2ConstraintSpec`** (lots, material requirements, resource windows, fixed jobs, production tasks) into a CP-SAT model. Quantities are scaled to integers exactly (`scaling.py`) with overflow checks. The solver is bounded by `max_time_in_seconds`, a fixed `random_seed` and a set number of search workers. Each projected portfolio is fingerprinted (SHA-256 digests of allocations and schedule) and **re-validated for the full portfolio and each selected order by the shared P2 feasibility authority**. Any disagreement returns `VALIDATION_MISMATCH`, and the plan is not shown as valid. Optimization is advisory over Mock inputs: it never accepts or reserves an order.

### 9. Supplier Comparison and Sourcing

`suppliers/comparison.py` checks **hard requirements before price**. Each tenant has versioned category specifications; editable starter templates cover:

| Category | Hard fields |
|---|---|
| Food packaging (`food_container`) | `capacity_ml`, `material`, `food_safe` |
| Perishables (`perishable_ingredient`) | `grade`, `storage_requirement` |
| General supplies (`general_supply`) | `sku`, `unit` |

Offers are classified **Qualified** (all hard fields match), **Conditional** (missing evidence) or **Incompatible** (a hard field is violated). If the specification itself is unknown, the comparison fails closed. `sourcing/` adds delivery-history analysis that separates **verified history** from **supplier claims**, a side-by-side dossier, an unsent common RFQ draft, reply consolidation, a selection preview, and a hand-off to Recovery as an `ALTERNATIVE_SUPPLY` option that stays `CONDITIONAL` until availability and approval are verified. An RFQ draft is not a purchase order; actual supplier sends and replies require authorized real-channel transport. The SME always picks the supplier and records the reason.

### 10. Emergency Change-to-Action — Approve & Execute

When a real, verified supplier message indicates a delay, MouManTAI moves from impact to a governed recovery using Mock Orbyte resources:

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

    SUP->>P1: Real provider message: 20 boxes arrive after the 3 pm cutoff
    P1->>P2: Supplier ETA change with source evidence
    P2->>P2: Recalculate ATP, BOM and capacity over Mock data
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
    P4->>CUS: Approved proposal on customer's originating channel
    CUS->>P4: Actual reply, correlated to contact/order/thread
    P4->>CORE: confirmation.accepted for proposal version 2
    CORE->>CORE: Agreement CONFIRMED only for exact assent; fulfilment separate
```

- **Recovery options** — `RESCHEDULE_PARTIAL_FULFILMENT` and `ALTERNATIVE_SUPPLY`, each persisted against the exact feasibility source and Core risk evidence (`durable_plans.py`).
- **Ranking** (`ranking.py`) — a lower-is-better weighted score over additional cost (MYR), delivery delay (minutes), number of affected commitments, operational disruption, supplier uncertainty and whether customer confirmation is required. Options that break a hard constraint are excluded with reasons.
- **Approval** (`core/manager_approval.py`) — a manager approval is bound to `plan_id`, `plan_version`, `snapshot_version` and `core_commitment_version`, has an expiry, and is single-use. Request-revision, reject and revoke are separate commands.
- **Approve & Execute** — one click in the UI, two backend commands (`/approve`, then `/execute` with an idempotency key), two audit records. **Approve Only** leaves the plan approved and awaiting execution. If execution fails or times out, the UI shows the real state and never repeats side effects blindly.

### 11. Closed-Loop Communication, Confirmation and Customer Status

`backend/app/communication/` owns every outbound message and customer response:

- **Drafts** (`drafting.py`, `templates.py`) — version-safe plain-text drafts from approved templates.
- **Message review** (`review.py`) — approval to send a message is separate from approval of a business proposal.
- **Outbound** (`outbound.py`, `providers.py`) — a durable, idempotent intent is sent through a provider adapter on the same channel as the inbound message. Respect recipient identity, channel capability, consent and opt-out; use Human Review for consequential business messages. If the origin cannot be used, return `CANNOT_SEND_ON_ORIGIN_CHANNEL` and require deliberate authorized fallback instead of silently switching channels.
- **Receipts and replies** — store the provider request/reference and correlate later provider status events. Distinguish drafted, awaiting review, queued, provider accepted/sent, delivered, read, failed and unknown only where supported. HTTP success alone never means delivered/read; `SENT` or `DELIVERED` is not customer assent, and assent is not fulfilment.
- **Confirmations** (`confirmations.py`, `response_rules.py`) — the customer's reply is matched to one proposal version. Conservative full-message rules mean a partial phrase never counts as acceptance; an ambiguous "OK" with several open proposals stays unresolved.
- **Follow-ups** (`followup.py`) — deterministic scheduling; each reminder is a new authorised contact intent, not a retry of the original send.
- **Recipient preferences** — verified channel identity, recipient consent and opt-out per contact and channel.
- **Customer status & milestones** — `operational_reporting/planning.py` plans template-based factual milestone messages with consent and dedupe gates. `ORDER_ACCEPTED` means the SME accepted and reserved; `COMPLETED` appears only after evidenced fulfilment.

The **Communication Center**, **Confirmation Workspace** and **Follow-up Queue** pages (`/communications`, `/confirmations/:id`, `/communications/follow-ups`) show message state, customer response and the linked proposal side by side.

### 12. Factual Replies — Templates First, Replit AI Wording Next

`conversations/replies.py` defines the `ReplyGenerator` interface. A `PublicKnowledgePolicy` allowlist limits factual replies to approved public fields (`faq_answer`, `fixed_price`, `business_hours`, `business_address`). A fact must be public, approved, sourced, current and tenant-authorized; conflicts, privacy-sensitive content or risk route to Human Review. The `TemplateGenerator` provides the deterministic factual baseline. Optional Replit AI Integrations may improve wording only after its endpoint, privacy and timeout checks pass; generated wording cannot alter the approved facts or their evidence. Custom quotes, discounts, private business data and delivery guarantees require Human Review before sending.

### 13. Forecasting and Predictive Alerts

`backend/app/forecasting/` is read-only and advisory:

- Baselines: `Naive`, `SeasonalNaive` and `MovingAverage`.
- **Expanding-origin backtesting** with no access to later observations at each origin, and model comparison on the same holdout.
- Source validation of the supplied history before any forecast is made.
- Risk alerts for demand, forward stockout or expiry, capacity or deadline (delegated to the feasibility engine), and supplier reliability.

A forecast risk is never treated as a confirmed disruption, and it never triggers approval or execution by itself. Seeded demand series and backtests are visibly `DEMO` / `SYNTHETIC`; they demonstrate the pipeline, not measured production accuracy or predictive lift. Real performance claims require genuine time-ordered holdout data and outcome evidence.

### 14. Decision Memory

`backend/app/decision_memory/` builds a case from exact stage references (message → decision → approval → action → outcome) taken from one consistent read snapshot. Retrieval of similar past cases is deterministic and runs only after evidence and policy gates. Seeded case history is `DEMO` / `SYNTHETIC`, not a verified real transaction or proof of learned quality. Outcomes are reconciled only with independent operational evidence, and lessons report denominators and limitations. Governance suggestions are proposals only; the module has no write or execution path.

### 15. Commitment Registry, Audit and Activity

Every commitment has one identity, a version number and **five independent state dimensions** — agreement, feasibility, risk, recovery and fulfilment — each with its own allowed transitions. Every consequential change writes an audit record and an outbox event in the same transaction. The **Activity** page (`/activity`) and `GET /v1/commitments/{id}/timeline` show who did what, when, and on which version.

The state boundaries are part of the product contract: `REQUESTED ≠ CONFIRMED`; `FEASIBLE ≠ GUARANTEED`; `APPROVED ≠ EXECUTED`; `SENT ≠ ACCEPTED ≠ FULFILLED`; a supplier promise is not received inventory; predicted demand is not accepted demand; AI confidence is not identity or authority; an RFQ draft is not a purchase order; and a synthetic resource receipt is not an Orbyte execution.

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
| Understand a messy multilingual order | Staff re-type details | Manual entry | Form fields only | Deterministic rules → Qwen → Gemini fallback, with validated source evidence and optional GLiNER extraction |
| Check if an order can be fulfilled | — | Manual formulas | Stock count only | Time-phased ATP, lot expiry, BOM and capacity on a versioned snapshot |
| Handle competing orders | — | Gut feeling | First come, first served | CP-SAT portfolios re-validated by the same feasibility engine |
| React to a supplier delay | Someone reads it | Someone recalculates | Status flag | Impact on affected commitments only, ranked recovery options |
| Govern a costly change | Verbal "ok" | — | Single "approve" flag | Version-bound approval and separate execution, both audited |
| Know the outcome | Read back the chat | — | One status | Message, agreement and fulfilment tracked as separate states |

**What is new:**

1. **Evidence-backed commitments with source spans.** Every extracted field stores the message ID, the exact quote and its `[start, end)` offsets, and the method that produced it (`RULE`, `MODEL`, `HUMAN`). A reviewer can always see *why* the system believes a quantity or deadline, and a model quote that does not match the source is rejected.
2. **Cheapest-reliable-layer selective AI.** Deterministic rules handle known cases first; Qwen handles unresolved semantics, with Gemini as a bounded fallback on specified Qwen failures. GLiNER may add extraction evidence where useful. Every model output is validated against source evidence, and AI never calculates stock, grants authority or certifies delivery.
3. **CP-SAT plans re-validated by the same feasibility engine.** The optimiser searches, but the feasibility engine decides. Every projected portfolio is fingerprinted and checked by the same evaluator used for single orders, so a solver bug or modelling gap cannot produce a plan the business cannot keep.
4. **Version-bound human approval with separate approval and execution records.** One *Approve & Execute* click produces two commands and two audit records. Approval is bound to plan, snapshot and commitment versions, expires, and is consumed once. If the data changes, re-approval is required.
5. **Closed-loop confirmation that tracks agreement and fulfilment separately.** `SENT ≠ ACCEPTED ≠ FULFILLED`. Customer acceptance is matched to an exact proposal version, and fulfilment needs its own evidence. The owner always knows which step a promise is really at.
6. **Decision Memory.** Decisions, approvals, actions and verified outcomes are assembled into cases that can be retrieved for the next similar disruption, with explicit evidence gates and denominators instead of anecdotes.
7. **Complements existing tools instead of replacing them.** SMEs keep WhatsApp, Telegram, Gmail and their spreadsheets. MouManTAI adds commitment assurance on top, and connects to Orbyte through narrow business ports for data, identity and review tasks.

---

## Business Impact & Measurement

These KPIs define how a future SME pilot can evaluate operational usefulness, productivity and commitment reliability. They are measurement definitions, not achieved results. Baseline, target and actual are **Not measured — requires SME pilot data** until timestamped, independently reviewable pilot evidence exists.

| KPI | Calculation and required evidence | SME relevance and limitations | Baseline / target / actual |
|---|---|---|---|
| **Risk Detection Latency** | For each verified supplier-risk event, alert creation time minus durable receipt time of the source evidence. Correlate the provider message ID, durable `received_at`, evidence reference and alert `created_at`. | Measures how quickly owners learn which commitments may be at risk. Depends on provider delivery, durable queueing, OCR/model latency and reliable clocks; measure provider and processing delay separately where possible. | Not measured — requires SME pilot data |
| **Order Decision Time** | Authorized final SME decision time minus the time a complete, valid request entered `PENDING_ACCEPTANCE`. Record request/version, completeness decision, `pending_acceptance_at` and authorized decision timestamp. | Measures time from decision-ready order to acceptance/rejection. Excludes time spent obtaining missing customer information; completeness rules must be applied consistently across baseline and pilot. | Not measured — requires SME pilot data |
| **Recovery Completion Rate** | Recovery cases with independently evidenced successful resolution by their evaluation deadline ÷ all recovery cases whose evaluation deadline falls in the measurement period × 100. Use case ID, evaluation deadline, resolution time and independent fulfilment or operational evidence. | Measures whether recovery plans resolve disruptions rather than merely being approved or executed. Results depend on correct case linkage, evidence availability and a consistent deadline policy; report unresolved and unverified cases separately. | Not measured — requires SME pilot data |
| **Manual Handling Steps** | Count logged human administrative actions per order from receipt to closure, including manual entry, checks, coordination and approvals. Use timestamped actor/action audit events; exclude automated processing and count repeated actions transparently. | Indicates administrative effort and adoption friction. Approval remains necessary for consequential decisions, and more complex orders naturally need more review; compare similar order types and report the action taxonomy. | Not measured — requires SME pilot data |
| **On-Time Commitment Fulfilment Rate** | Commitments due during the period with independent evidence of fulfilment at or before the agreed deadline ÷ all commitments due during the period × 100. Use the exact confirmed deadline/version and fulfilment evidence timestamp. | Measures reliability of customer promises. Do not count message sent, customer assent, supplier promise or synthetic receipt as fulfilment; disclose missing evidence, partial fulfilment and deadline changes separately. | Not measured — requires SME pilot data |

Together, these measures can test whether MouManTAI reduces avoidable handling time and helps SMEs protect commitments, supporting the intended SDG 8 productivity and business-growth alignment. For adoption and scalability, report results by SME, order volume, channel and order type rather than pooling unlike workloads without context. Any real-world impact claim requires a documented baseline, consented SME pilot, defined cohort and period, and independently reviewable outcomes; synthetic tests do not establish business impact.

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
| **`context`** | Ingests provider messages, stores attachments, runs L0 rules and useful extraction stages, reconciles fields to canonical terms, associates messages through verified contact/order evidence, records versioned human reviews, and publishes eligible contexts to Core. Final semantic fallback is Qwen → Gemini with evidence validation. | `channels`, configured model providers, `orders`, Core |
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

### Existing RunPod adapter (implementation detail)

The current RunPod adapter supports GLiNER/Qwen inference as described below. The final semantic route is Qwen first with Gemini fallback; this adapter does not yet implement the Gemini fallback, as recorded in the status matrix.

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
- **Failure codes** — only fixed codes cross the boundary (`timeout`, `endpoint_http_error`, `model_mismatch`, `evidence_mismatch`, …); provider bodies and credentials are never echoed. In this current adapter, failure preserves rule fields and routes to Human Review; the final Qwen-to-Gemini fallback remains a separate target requirement.

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

## Implementation Status & Verification Matrix

The final architecture above describes the intended v2.2 product. Implementation evidence was reviewed against code baseline `main` at `f6eca1ac93b382c2ffe68965e18b55f12e03d322` (24 Oct 2026). PRs #86, #87 and #89 are merged and included in that snapshot; #89 adds pure channel-framing helpers and tests but does not wire runtime persistence/provider E2E. PRs #81–#85, #88 and #90 were open at review time and are not counted as merged capabilities. No channel has `REAL_CHANNEL_VERIFIED` evidence in the reviewed sources.

| Capability | Final Required Behavior | Current Evidence | Verification Status | Remaining Gate |
|---|---|---|---|---|
| Telegram inbound / outbound / reply | Real Bot API ingress, provider IDs and same-chat replies | Inbound starting code/tests: `backend/app/context/channels/telegram.py`, `backend/app/context/tests/test_telegram_channel.py`; merged PR #89 adds pure framing tests, not runtime wiring; P4 uses `LocalMockProvider` in `backend/app/communication/providers.py` | `IMPLEMENTED_NOT_E2E_VERIFIED` inbound; `SYNTHETIC_ONLY` outbound | Configure bot/webhook secret and prove provider message, authorized reply, receipt and correlated customer reply |
| WhatsApp inbound / outbound / reply | Official Meta Cloud API test number; actual sends, callbacks and replies within number/template/window restrictions | Inbound webhook code/tests: `backend/app/context/channels/whatsapp.py`, `backend/app/context/tests/test_whatsapp_channel.py`; merged PR #89 adds pure framing tests, not runtime wiring; no real outbound E2E record found | `IMPLEMENTED_NOT_E2E_VERIFIED` inbound; `SYNTHETIC_ONLY` outbound | Configure official test number, allowed recipients, webhook signatures/status callbacks and prove send/reply E2E |
| Email inbound / outbound / threaded reply | Genuine receipt and send, body/attachment retrieval and thread correlation | Gmail OAuth/polling starting code/tests: `backend/app/context/channels/gmail.py`, `backend/app/context/tests/test_gmail_channel.py`; merged PR #89 adds pure framing tests, not runtime wiring; no selected real outbound sender/threaded E2E evidence | `IMPLEMENTED_NOT_E2E_VERIFIED` inbound adapter; outbound `IN_PROGRESS` | Evaluate Resend inbound first (test address, webhook, body and attachments); select outbound separately; authorize verified From/Reply-To and prove IDs, headers, media and reply correlation |
| Contact Registry / first-contact verification | Human verifies role, tenant and immutable channel IDs; safe cross-channel linking | No merged Contact Registry implementation or provider-level verification trace identified; next-phase requirements are described in the unmerged PR #88 handoff | `IN_PROGRESS` | Implement registry, audit/revocation and fail-closed spoof, tenant, ambiguity and cross-channel tests |
| Message extraction and Qwen → Gemini | Deterministic first, Qwen as first semantic model, Gemini fallback on specified failure, schema/evidence validation | Current context AI route/protocol and GLiNER/Qwen components under `backend/app/context/ai/`; main has no evidenced Gemini fallback or live inference trace | `IN_PROGRESS` | Implement bounded Qwen/Gemini routing, redaction, validation and fallback tests; record provider evidence |
| PDF/image/OCR positive and failure paths | Parse supported files; preserve provenance; failed dependency/extraction creates Human Review without invented terms | `backend/app/context/document_extractor.py` and context tests; release audit records `test_e2e_11_pdf_image_evidence_traceable_payment_unverified` failed (`FAILED` vs expected `SUCCESS`) with PyMuPDF/PaddleOCR absent | `BLOCKED` | Install/check runtime dependencies; pass positive and malformed/unreadable tests; verify failure-to-Review behavior |
| Customer OrderRequest and acceptance | Real ingress → verified contact → versioned request → fresh P2 → authorized exact-term SME acceptance | Existing terms/context/Core components; durable Mock OrderRequest flow and API are in unmerged PR #81 | `IN_PROGRESS` | Merge/review separately; verify real ingress binding, exact version, authorization, PostgreSQL, audit and UI journey |
| Mock Orbyte reservation and receipt | Actual guarded internal operation over disclosed Mock resources; never live Orbyte authority | Core reservation and business-port code/tests; PR #81 describes persisted Mock receipts and concurrency cases but remains unmerged | `SYNTHETIC_ONLY` | Verify merged persisted reservation, idempotency/concurrency/unknown outcomes and receipt-to-commitment audit |
| P2 feasibility and supplier impact | Shared deterministic evaluator over tenant/version-scoped Mock inventory, BOM and capacity | `backend/app/feasibility/` engines/tests and synthetic integration handoffs; no live Orbyte data source | `SYNTHETIC_ONLY` | Verify end-to-end P2 against Mock OrderRequests, freshness and supplier impact linkage; keep Mock labels visible |
| OR-Tools CP-SAT optimization | FCFS, Profit and Expiry-Aware; hard constraints, exact scaling and full P2 revalidation | `backend/app/optimization/` and merged CP-SAT tests/handoff; optimizer is advisory over synthetic constraints | `SYNTHETIC_ONLY` | Verify registered full-portfolio source/API/UI path; preserve missing-input, timeout and P2-mismatch fail-closed states |
| Supplier comparison and RFQ | Hard specifications before price; Qualified/Conditional/Incompatible; unsent RFQ draft distinct from authorized send | `backend/app/sourcing/` comparison logic and tests; persisted synthetic supplier API / RFQ work is in open PR #83 | `SYNTHETIC_ONLY` | Verify persisted source/evidence and SME choice; real authorized provider send/reply remains a channel gate |
| Emergency Recovery approval and execution | Real verified supplier incident; scoped human plan approval, separate revalidated execute command; Mock action receipt | Recovery modules and synthetic supplier-delay tests/handoffs; no real supplier-channel-to-customer-channel journey evidenced | `SYNTHETIC_ONLY` | Link real verified message to alert/impact; prove approval/execution separation, Mock receipt and correlated audit |
| Customer communication and explicit assent | Same-origin real send/reply, truthful provider states, exact proposal/version assent separate from fulfillment | P4 communication/confirmation code and `LocalMockProvider`; no real provider receipts or customer replies in reviewed evidence | `SYNTHETIC_ONLY` | Add real outbound adapters, consent/opt-out, origin-channel failure and actual reply/assent E2E |
| Forecasting and Decision Memory | Baselines/backtests and provenance-aware case retrieval; synthetic history labelled Demo-only | Existing `backend/app/forecasting/` and `backend/app/decision_memory/` modules; persisted synthetic APIs/fixtures in open PRs #84 and #88 | `SYNTHETIC_ONLY` | Merge/review API work; retain synthetic labels; validate performance only with genuine held-out history and outcomes |
| PostgreSQL, audit, outbox and worker reliability | Durable raw intake/outbox, idempotency, retries, reconciliation, tenant isolation and truthful unknown state | SQLAlchemy/Alembic/Core/outbox implementation and PostgreSQL CI suites in main; no real-provider cold-start/send reconciliation evidence | `IMPLEMENTED_NOT_E2E_VERIFIED` | Verify durable provider webhook handoff, restart/replay, duplicate/out-of-order events, retries and real send reconciliation |
| Frontend browser integration | Main business pages consume backend status/review APIs and show evidence tiers, failures and Mock labels | React pages and component tests exist; latest PR #88 handoff says new Mock APIs are not wired and browser-to-provider E2E is not complete | `IN_PROGRESS` | Wire backend/API clients and run browser → API → PostgreSQL → provider → UI E2E |
| Replit development use | Replit used for development/code changes; no implication of live hosting or AI-integration use | Owner confirms Replit was used to write and modify project code; no workspace export or Replit Proof-of-Use PDF is in `main` | `OWNER_CONFIRMED_HISTORICAL_USE` | Add verified project URL and `submission/SDC2026_XMM_Replit_POU.pdf` when available; keep hosting status separate |
| RunPod GLiNER/Qwen inference | Optional historical inference path; current endpoint and Gemini fallback must be assessed separately | Owner confirms FastAPI previously ran GLiNER multi v2.1 and Qwen3-4B-Instruct-2507 inference; endpoint adapter/image are in `backend/app/context/ai/`; no POU PDF or runtime log is in `main` | `OWNER_CONFIRMED_HISTORICAL_USE` | Attach `submission/SDC2026_XMM_Runpod_POU.pdf`; current endpoint availability and complete Qwen→Gemini path remain unverified |
| Vercel, Render and database deployment | Vercel frontend, Render FastAPI/webhooks, durable PostgreSQL and an available async worker | Local Docker Compose and provider adapters are in main; no verified Vercel/Render deployment URL/configuration or cold-start evidence identified | `IN_PROGRESS` | Provision target services; verify HTTPS, durable intake, worker availability, cold starts, retries and database lifecycle; no always-on claim |

`REAL_CHANNEL_VERIFIED` requires actual authorized provider callbacks/API calls and replies for that channel and test mode. `MOCK_RESOURCE_VERIFIED` requires verified internal calculation, approval, reservation, persistence and tests over disclosed Mock resources. Neither is inferred from unit tests, mocked SDKs, an OpenAPI route or an unmerged PR. `SYNTHETIC_ONLY` means fixture/demo evidence without real provider evidence. `BLOCKED` records a known release gate, not an acceptable final state.

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
| httpx | Existing RunPod, Telegram, Gmail and WhatsApp clients; provider adapters for the final Email and outbound paths |

### Database

| Technology | Use |
|---|---|
| PostgreSQL 16 | Primary store — Docker Compose `postgres:16-alpine` locally, `postgres:16` service in GitHub Actions |
| SQLite | Fallback for local tests when no PostgreSQL driver is available |

### AI / Compute

| Technology | Use |
|---|---|
| Deterministic rules | First path for known fields, normalization, deduplication and safe public FAQ eligibility |
| Qwen | First selective semantic interpreter when rules are insufficient |
| Gemini API | Required bounded fallback on Qwen error, timeout or structured/evidence validation failure |
| GLiNER `urchade/gliner_multi-v2.1` | Existing optional multilingual span-extraction support where useful; not a replacement for Qwen-first semantics |
| RunPod Serverless | Optional external compute adapter; configure and verify before describing as active |
| PyMuPDF · PaddleOCR | PDF text and image OCR for attachments |
| Replit AI Integrations | Reply-wording adapter behind `ReplyGenerator`, switched off until verified (templates used today) |

### Hosting / Dev

| Technology | Use |
|---|---|
| Replit | Development/collaboration and hackathon Proof of Use |
| Docker Compose | `db`, `api` and `worker` services |
| GitHub Actions | Backend, PostgreSQL, optimisation, frontend and hygiene checks |

**Preferred application deployment target:** Vercel for the React/TypeScript frontend, Render for FastAPI and public webhooks, and durable PostgreSQL. RunPod is optional inference compute. These are target choices; see the status matrix for deployment evidence.

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

### Option 1 — Run in Replit (Development / Hackathon)

1. Import this repository via **Create → Import from GitHub**. The project URL is pending owner verification.
2. For a development run, configure only the variables required by the selected features in [`.env.example`](.env.example). Use synthetic data and local identity only for development; do not infer production readiness from this option.
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

The first table lists variables present in the repository's current configuration. Values are placeholders. Copy `.env.example` to `.env` locally or configure secrets in the chosen host; never commit real values. The second table records additional target-only provider configuration to plan for. Those names are illustrative and do not imply that the current application reads them or that a provider is deployed.

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
| `RESEND_API_KEY` | Not configured | **Target configuration only:** candidate outbound email API credential if Resend is selected; evaluate Resend inbound separately and confirm actual variable name before deployment |
| `RESEND_WEBHOOK_SECRET` | Not configured | **Target configuration only:** verify inbound email webhook signatures; confirm selected provider and actual variable name |
| `EMAIL_FROM` / `EMAIL_REPLY_TO` | Not configured | **Target configuration only:** verified sender identity and reply routing; configure only after domain/provider verification |
| `QWEN_API_KEY` / `QWEN_BASE_URL` | Not configured | **Target configuration only:** Qwen provider credentials and endpoint, if direct provider routing is selected |
| `GEMINI_API_KEY` / `GEMINI_MODEL` | Not configured | **Target configuration only:** Gemini bounded fallback credentials and model; this README does not claim deployed capability |
| `LLM_REQUEST_TIMEOUT_SECONDS` | Not configured | **Target configuration only:** bounded provider request timeout; exact supported setting to be implemented and verified |
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
        LLM["Qwen semantic API → Gemini fallback<br/>provider deployment unverified"]
        RP["Optional RunPod compute<br/>deployment unverified"]
        CHN["Telegram · Gmail · WhatsApp Cloud API<br/>Email provider selection pending"]
        RAI["Replit AI Integrations<br/>adapter switched off until verified"]
        ORB["Orbyte business ports<br/>MOCK / SYNTHETIC"]
    end

    subgraph CI["GitHub Actions"]
        GHA["pytest · CP-SAT · Vitest · tsc · build<br/>postgres:16 service"]
    end

    UI --> PX --> API
    API -->|"depends_on: healthy"| DB
    WK -->|"depends_on: api healthy"| API
    WK --> DB
    API --> LLM
    API -. optional configured compute .-> RP
    CHN --> API
    API --> RAI
    API <--> ORB
```

| Target | How |
|---|---|
| **Vercel + Render + PostgreSQL** | Preferred target: Vercel frontend, Render FastAPI/public webhooks and durable PostgreSQL with an available async worker. No deployment or provider end-to-end verification is claimed; see the status matrix. |
| **Docker Compose** | `docker compose up -d --build` starts `db`, `api` and `worker`, with health-gated start-up order. |
| **RunPod GPU worker** | Optional compute target. The repository has an endpoint adapter and worker image; configure endpoint credentials and verify the live endpoint before describing it as active. |
| **Channels** | Telegram polling needs no public URL; Telegram and WhatsApp webhooks need a public HTTPS API URL. Email provider selection and inbound/outbound production setup remain pending. |

For the target deployment, require HTTPS, durable inbox/outbox storage, idempotent intake and send attempts, retry/backoff and reconciliation for uncertain send outcomes, and an available worker. Verify host sleep/cold-start behavior, webhook delivery and database persistence under the selected plans. These are deployment acceptance checks, not verified properties of a current deployment.

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
├── submission/                            # Not present in this main snapshot; add verified submission files
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

- **Development:** The team used Replit to write and modify MouManTAI project code. The resulting code is maintained in this GitHub repository; repository history does not identify which edits were made in Replit. No claim is made that Replit Agent, Multiplayer or Replit Slides were used.
- **Hosting:** Replit was used for development, not verified live application hosting. The preferred application deployment remains Vercel for the frontend, Render for FastAPI/webhooks and durable PostgreSQL; see the status matrix for deployment evidence.
- **AI:** customer replies are built from approved factual templates today. The `ReplyGenerator` interface already includes a `ReplitGenerator` adapter (provider `REPLIT`) for **Replit AI Integrations** wording; it stays switched off until its endpoint, privacy and timeout checks pass. Once enabled, any wording that does not preserve the approved facts still falls back to the template.
- **Secrets:** store development secrets in a secret manager, never in code. The presence of provider configuration in documentation does not establish that a service was deployed.

📄 Proof of use: `submission/SDC2026_XMM_Replit_POU.pdf` — pending; this file is not present in the current `main` snapshot.

## How We Use RunPod *(Required)*

- **Historical use:** The owner confirms that MouManTAI's FastAPI backend previously integrated with RunPod Serverless and successfully ran GLiNER multi v2.1 and Qwen3-4B-Instruct-2507 inference tasks. This confirms historical use only; current endpoint availability has not been independently reconfirmed.
- **Integration path:** `FastAPI Backend → RunPod Serverless → GLiNER / Qwen → Backend Response → Evidence Validation`. The repository contains the RunPod endpoint adapter and worker image (`backend/app/context/ai/endpoint.py`, `backend/app/context/ai/Dockerfile`) and `P1_AI_*` settings. GLiNER supports multilingual entity/field extraction; Qwen is the selective semantic interpreter after deterministic rules. Outputs must pass schema and source-evidence validation before use.
- **Current readiness:** No current endpoint state is asserted. Historical GLiNER/Qwen success does not prove current availability, real-channel E2E, production hosting or the separate Qwen-to-Gemini fallback.

📄 Proof of use: `submission/SDC2026_XMM_Runpod_POU.pdf` — pending; this file is not present in the current `main` snapshot.

---

## Challenges & Learnings

- **Keeping AI useful without letting it decide facts:** models propose, deterministic rules and people decide. Exact span validation turned out to be the simplest way to make model output reviewable.
- **Making a solver trustworthy:** every CP-SAT plan is re-validated by the same feasibility engine used for single orders, and exact integer scaling avoids rounding errors in quantities and money.
- **Designing human approval that is safe but not slow:** one **Approve & Execute** click backed by two audited commands, bound to the exact plan and snapshot version.
- **Separating states people usually merge:** treating message sent, customer accepted and order fulfilled as different states removed a whole class of "we thought it was confirmed" errors.
- **Reliable events between modules:** a transactional outbox with idempotent consumers, stale-event checks and dead-lettering kept modules decoupled without losing events.

## Future Improvements

- [ ] Production Orbyte API when access and contract are available; current business data remains Mock/Synthetic
- [ ] Broader provider/account onboarding, tenant-safe identity, operational monitoring and reliability evidence for live channel journeys
- [ ] Switch on Replit AI Integrations reply wording after endpoint, privacy and timeout verification
- [ ] Pilot with consenting Malaysian SMEs and measure order-to-decision time, forecast quality and operational outcomes
- [ ] Expand supplier marketplace integrations after the guarded RFQ draft and approval journey is validated

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
- [ ] Required submission PDFs attached under `submission/`
- [ ] Preliminary submission (`submission/SDC2026_XMM_Preliminary.pdf`) — file not present in the current `main` snapshot
- [ ] Technology declaration (`submission/SDC2026_XMM_TechDeclaration.pdf`) — file not present in the current `main` snapshot
- [ ] Replit proof of use (`submission/SDC2026_XMM_Replit_POU.pdf`) — file not present in the current `main` snapshot
- [ ] RunPod proof of use (`submission/SDC2026_XMM_Runpod_POU.pdf`) — file not present in the current `main` snapshot
- [ ] Files renamed with team name
- [ ] "How to Run" verified from a clean environment
- [x] No API keys or secrets committed

## License

The project declares Apache License 2.0; the license text file is not present in the current `main` snapshot.
