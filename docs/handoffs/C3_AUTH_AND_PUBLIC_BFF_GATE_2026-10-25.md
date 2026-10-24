# C3 authority and public BFF gate — 25 October 2026

## Owner decision and scope

The owner authorized **one temporary Demo Admin** for the isolated hackathon staging environment. The server-configured tenant and manager ID, scrypt password verifier, private isolated API key and TLS credentials stay outside the frontend bundle and Git. There is no registration or browser-selected authority. This does not approve general production SaaS identity.

The new HTTPS gateway in `frontend/demoGateway.mjs` serves the built SPA and proxies an exact allowlist to a private FastAPI instance. It issues opaque, HttpOnly, Secure, SameSite=Strict 20-minute cookies, verifies exact Origin and CSRF, rate limits login, supports logout and rejects forged tenant/actor/key headers. A single gateway replica holds sessions in memory; restarting it revokes every session. `docker-compose.demo-admin.yml` keeps FastAPI and PostgreSQL off public ports. P4 outbound is explicitly disabled. `frontend/hosting/public-guard.conf` remains the fail-closed static fallback if the Demo Admin topology cannot be provided.

C3 `POST /v1/c3/reviews/{id}/decide` is available only when isolated staging, the private key, fixed tenant/manager and `MOUMANTAI_DEMO_ADMIN_AUTH=1` all hold. `trusted_isolated_manager` verifies manager identity server-side. `C3ReviewService.decide` locks the review, checks revision, source freshness and request key, and records actor, reason and grant evidence. Approve/reject/correct decide **classification only**. No OrderRequest, P2, P3 or P4 mutation follows. Orders retain their existing review, exact-terms acceptance, reservation and audit guards.

## Public staging limits

The local HTTPS/Chrome demo uses a self-signed test certificate and a synthetic fixture marked `REAL/VERIFIED` to exercise the provider provenance contract. That fixture is **not** evidence of a live Telegram/WhatsApp/email webhook. Production `ENVIRONMENT=production` still disables synthetic C3 and Orders routes. A public demo requires an isolated host, real TLS certificate, strict firewall, private Compose network and server-side secret provisioning described in the Demo Admin runbook. Without these, Public HTTPS Staging remains **NO-GO**.

The previous P5 production identity contract is still absent. After the hackathon, replace this single-admin gateway with a P5 authenticated principal/manager permission and revocable shared session store before any multi-user or SaaS deployment. Do not carry the isolated key or synthetic header identity into a public FastAPI listener.
