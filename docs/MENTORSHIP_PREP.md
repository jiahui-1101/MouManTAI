# Alpha Red mentorship preparation — PromiseFlow

**For the 25 October 2026 submission.** PromiseFlow is the presentation name; this repository and app still say MouManTAI. The main snapshot at the start of this showcase update is `34ce33a` (23 October). The [README](../README.md) gives the product and demo narrative. This brief distinguishes the intended four-capability workflow from what has been observed in code and tests. The inbox's WhatsApp, Email and Telegram examples are synthetic envelopes; no official channel connector is live.

## Five highest-priority questions to ask live

1. **Which single customer commitment failure would you want us to demonstrate end to end for a real SME, and what outcome would convince you it matters?** This sets the hero journey and the Problem-Solution Fit evidence.
2. **Where is our real differentiation: detecting affected promises, comparing constrained recovery, or recording verified customer agreement and outcome? What feels least distinctive?** This guides the Innovation story and scope cuts.
3. **For a 25 October preliminary demo, what proof would you expect beyond a polished screen: persisted state, a manager decision, a customer response, failure handling, or a measured time saving?** This directs Feasibility and Clarity work.
4. **Without an Orbyte API or sandbox, what conceptual interface and partner responsibilities would make this credible within the Orbyte ecosystem?** This sets an honest integration proposal.
5. **Which existing system or habit would an SME replace first, and what price or time-saving hypothesis would be worth testing in a pilot?** This shapes adoption and validation rather than assuming willingness to pay.

## A. Rubric readiness analysis

The official preliminary weights are **Innovation & Creativity 30%**, **Problem-Solution Fit 25%**, **Feasibility of Build 25%**, and **Clarity of Proposal 20%**. Risks below are editorial judgments, **not judge scores**.

| Criterion | What the rubric expects | Design response and current evidence | Weakness / unanswered question | Risk | Improvement before 25 October |
|---|---|---|---|---|---|
| Innovation & Creativity (30%) | A distinctive way to solve the challenge. | Commitment-centric lifecycle; change → impact → recovery → confirmation; explicit human approval and separate fulfilment. Core states, F2 evaluator, F3 plans and F4 response code exist. | A mentor may see this as an order dashboard plus alerts unless one connected journey shows the difference. No comparative user evidence. | **HIGH** | Demonstrate one change causing impact, constrained choices, authorized action and outcome trail under one commitment ID. Explain why a chatbot or reminder cannot establish these states. |
| Problem-Solution Fit (25%) | A clear SME pain point, users and plausible value. | Catering/supplier-delay example directly matches disconnected information. Synthetic seed and read-only recovery scenario make it explainable. | No observed SME interview, pilot demand, willingness-to-pay or measured coordination burden in repo. Scenario has not been validated with an SME. | **HIGH** | Ask mentor which failure is common; obtain 1–2 SME reactions if feasible; define baseline and one measurable outcome. Avoid invented savings. |
| Feasibility of Build (25%) | A credible, working MVP with a realistic path to delivery. | Mounted FastAPI routes/UI for F1–F4; audit/outbox and version checks; selected handshake suite passed 19 with 1 PostgreSQL skip. Frontend typecheck/build passed and Vitest reported 475 passed, 5 skipped. | Normal worker gates key subscribers; affirmative authority is isolated; no independently observed full browser/worker/PostgreSQL journey. | **HIGH** | Rehearse a disposable, seeded, same-commitment E2E flow; record API/UI state, event and audit IDs, failures, test command and exact result. Keep display-only flow visibly labelled. |
| Clarity of Proposal (20%) | An understandable solution, focused demo and believable claims. | README now opens with problem, solution, differentiator, simple scenario, four capabilities and status. | Two names (PromiseFlow/MouManTAI), complex internal vocabulary, and mixed historical `TEAM_LOG` entries can confuse reviewers. | **MEDIUM** | Pick a single presentation name in slides, say the repo codename once, and use a two-minute demo with clear “working / synthetic / planned” labels. |

**Evidence rule:** the system requirements describe targets, not completion. `docs/TEAM_LOG.md` includes earlier “12/12 E2E” service/TestClient claims and later live integration blockers. Current mounted code and a fresh reproducible run should decide what is demonstrated. No rubric score, deployment, accuracy, ROI or live Orbyte link is asserted.

## B. Strategic mentorship questions

The first five above are the live shortlist. The full set below gives the reason, rubric link and decision each answer would change.

| # | Open-ended question | Why it matters | Rubric | Decision informed |
|---|---|---|---|---|
| 1 | Which single customer commitment failure would you want demonstrated end to end for a real SME, and what outcome would convince you it matters? | Anchors the product in a concrete repeated pain. | Problem-Solution Fit; Feasibility | Select hero scenario and proof. |
| 2 | Where is our real differentiation: detecting affected promises, comparing constrained recovery, or recording verified agreement and outcome? What feels least distinctive? | Tests the innovation claim against sponsor expectations. | Innovation | Emphasize one decisive advantage; cut weaker claims. |
| 3 | For the preliminary demo, what proof would you expect beyond a polished screen: persisted state, a manager decision, customer response, failure handling, or measured time saving? | Prevents a fixture-only presentation being mistaken for a working journey. | Feasibility; Clarity | Allocate final test/rehearsal time. |
| 4 | Without an Orbyte API or sandbox, what conceptual interface and partner responsibilities would make this credible within Orbyte? | Clarifies the legitimate integration story. | Innovation; Feasibility | Define adapter boundary and sponsor handoff. |
| 5 | Which existing system or habit would an SME replace first, and what price or time-saving hypothesis is worth testing? | Exposes adoption friction and willingness to pay. | Problem-Solution Fit | Pilot and business-model hypothesis. |
| 6 | Which type of SME would feel this pain often enough to adopt first: catering, light manufacturing, custom orders or another segment? | Broad “SME” positioning may be too diffuse. | Problem-Solution Fit | Initial vertical and fixture language. |
| 7 | Which recovery choices should always require an owner or manager, and which low-risk internal tasks could be pre-authorized? | Balances trust, speed and workload. | Feasibility; Problem-Solution Fit | Approval policy and demo scope. |
| 8 | What information must a small-business owner see to trust or reject a recovery suggestion in under a minute? | Tests usability of cost, time, uncertainty and source evidence. | Clarity; Problem-Solution Fit | Screen priorities and explanation. |
| 9 | What baseline and pilot measure would best demonstrate value: time to detect risk, time to resolve it, on-time delivery, or fewer manual contacts? | Turns hoped-for impact into a testable claim. | Problem-Solution Fit | Measurement plan. |
| 10 | What failure or ambiguous customer response would you most want us to show, and what should the product do visibly? | Shows safe handling rather than a happy-path only demo. | Feasibility; Clarity | Negative-case demo choice. |
| 11 | How much configuration should a new SME be expected to do before first value, and what should be supplied by an ecosystem partner? | Tests whether “reusable” can be adopted economically. | Innovation; Feasibility | Onboarding and integration scope. |

## C. Non-technical explanation

### 20-second elevator pitch

“When a supplier is late, a small business can miss a customer promise before anyone notices. PromiseFlow connects the order, stock and supplier change, shows which promise is at risk and offers recovery choices. A manager approves important actions, and the customer’s answer and actual delivery are tracked separately.”

### 60–90-second product explanation

“Imagine a caterer promising 100 lunch boxes by 3 pm. The packaging supplier says 20 boxes will arrive too late. Normally the owner checks several chats and spreadsheets, calls around, and may overlook another affected order. PromiseFlow is designed to hold the customer promise as one trackable record. It links the supplier update to the right order, checks whether the deadline is still possible, and compares choices such as sourcing packaging elsewhere or proposing a later delivery. Each choice shows its cost, delay and what remains uncertain. A manager must approve a consequential step. If the promise changes, the customer is asked to accept the exact revised terms; a sent message is not assumed accepted. Even after acceptance, the order is only fulfilled when separate delivery evidence exists. Our current prototype has the modules and synthetic data for this approach; we are still validating a single fully connected live demo.”

### F1–F4 in one sentence each

- **F1:** Understand the incoming order or supplier message and show the source and uncertain fields.
- **F2:** Check whether the promise still fits stock and time, and find other promises affected by a change.
- **F3:** Compare practical recovery choices, obtain a manager decision and record a permitted action.
- **F4:** Communicate an approved change, understand the explicit customer response and follow up when needed.

The shared commitment record keeps all four talking about the same promise; it is their common foundation.

### Two-minute business-oriented demo narration

“Here is a synthetic catering scenario. The business has promised an order by a deadline. The packaging supplier moves delivery beyond the production cutoff. On this screen we can see the shortage and why it matters to the customer promise. The recovery view compares two choices: try another supplier at an estimated extra cost, or ask the customer for another day. Notice the assumptions: alternative stock is not yet confirmed, and the revised date is not automatically agreed. We can click a choice to focus discussion; this particular walkthrough is read-only, so that click does not approve or execute anything. In the seeded application we can inspect a commitment’s separate agreement, risk and fulfilment states and its timeline. In the full workflow we are building toward, a manager would approve a specific current plan, the system would carry out only the permitted synthetic action, and any changed customer terms would be offered for explicit confirmation. A reply would update agreement only when it matches the current proposal. Delivery would still need its own proof. For this session, the verified evidence is the existing modules, synthetic screens and selected integration tests; a fully connected live rehearsal is our highest priority before submission.”

## D. Difficult mentor questions and suggested responses

| Mentor question | Evidence-grounded response |
|---|---|
| Why is this innovative? | The unit of work is a versioned customer promise. A change is assessed against operational constraints, followed through approval, communication and evidenced outcome. The design is distinctive; we have not proven market superiority. |
| Why not just use ChatGPT? | A chat answer can help explain a situation, but it does not by itself own current stock, enforce approval and versions, or prove whether the customer accepted and delivery happened. Our prototype uses deterministic rules and validated records for those decisions. |
| How is it different from an ERP or order management system? | It is a focused layer for protecting commitments across disconnected sources, with change-to-impact-to-action and an audit trail. A real deployment would integrate with existing order and inventory systems rather than replace them. |
| Are four capabilities too broad? | They are stages of one journey, not four standalone products. Before submission we will prioritize one scenario and defer extra connectors and advanced AI. The current integration gap is precisely why scope discipline matters. |
| Why would small businesses pay? | We hypothesize value from less coordination and fewer missed promises, but have no willingness-to-pay evidence yet. We would test one workflow with SMEs, measure time and errors, and discuss a modest subscription only after validation. |
| How does it fit Orbyte without a live API? | We can show proposed input/output boundaries and a simulated adapter. We cannot claim platform compatibility until Alpha Red or Orbyte provides an official contract or sandbox. |
| How can users trust AI recovery advice? | Options must expose source facts, assumptions and constraints; unknown supply remains unknown. Business rules and manager authorization gate action. A 26-case F1 evaluation artifact exists, but we have not reproduced remote inference or validated performance in an SME pilot; neither establishes recovery recommendation accuracy. |
| How do we measure impact? | Establish a manual baseline and record time to identify affected commitments, time to decide, exceptions, on-time fulfilment and audit completeness across a pilot sample. We currently report no measured business impact. |
| What is actually working today? | Mounted F1–F4 APIs and screens, a shared registry, synthetic fixtures, and selected cross-feature tests. This audit's handshake suite passed 19 and skipped one PostgreSQL test; frontend typecheck/build passed and Vitest reported 475 passed, 5 skipped. A full live journey, production auth and real channel/Orbyte connections are not verified. |
| What is the biggest risk before submission? | A persuasive but disconnected demo could overstate readiness. We need one repeatable same-commitment flow with persisted events, current approval, customer response and an auditable outcome, or label each missing stage honestly. |

## E. Live meeting order

Ask the [five priority questions](#five-highest-priority-questions-to-ask-live) first. Use questions 6–11 only if time remains or a mentor opens the relevant topic. Capture each answer as a product decision and owner, not just a quote.

## F. Priorities for 25 October

1. **One controlled journey:** P5 and the relevant owners should run one synthetic change through the current API, worker and database under the same tenant/commitment ID, with exact prerequisites and failure behavior. Do not broaden scope to more channels or models.
2. **Truthful evidence:** record command, code revision, database type, relevant IDs, before/after state, approval scope, customer response and audit entries. A passing unit test and a screen fixture count as separate evidence, not a combined live flow.
3. **Usability:** make the demo show what changed, why the promise is at risk, which options are conditional, what needs manager approval and what the customer has actually agreed to. Rehearse a two-minute narration.
4. **Submission clarity:** use PromiseFlow consistently in the presentation, identify MouManTAI as the repository codename once, and have P5/release owner review shared documentation and status claims.

**Open dependencies:** approved disposable PostgreSQL and migration rehearsal; normal-vs-isolated subscriber wiring; trusted production actor/contact/channel authority; P3 response handling and actual consequential execution; one current end-to-end UI/API/worker run. These are distinct from the implemented mock and test paths. No official Orbyte contract is available.
