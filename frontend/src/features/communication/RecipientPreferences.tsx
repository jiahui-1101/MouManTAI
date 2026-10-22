import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, apiRequest, authHeaders, type RequestAuthHeaders } from "../../shared/api";
import { communicationKeys } from "./api";
import { reasonText } from "./presentation";
import { formatKLTimestamp } from "../../shared/date";
import { ApiErrorReference } from "./P4Feedback";

export interface RuntimeCapabilities {
  tenant_id: string; mode: "SYNTHETIC" | "CLOSED"; label: string;
  can_record_preferences: boolean; can_revoke_preferences: boolean;
  integrated_demo_ready: boolean; blockers: string[];
}
export interface RecipientPreference {
  tenant_id: string; customer_id: string; channel: "MOCK_EMAIL" | "MOCK_WHATSAPP" | "MOCK_TELEGRAM";
  consent_status: "OPTED_IN" | "OPTED_OUT"; consent_purpose: string; recipient_identity_id: string;
  consent_evidence_ref: string; source: "SYNTHETIC_FIXTURE";
  consent_expires_at: string; version: number; updated_at: string; updated_by_actor_id: string;
  allowed_contact_hours: { start_hour: number; end_hour: number }; timezone: string;
}
const base = "/v1/communications";
function problem(error: unknown) {
  return error instanceof ApiError ? reasonText(error.code) : "Cannot reach the preference service. Retry after checking your connection.";
}
function scoped<T extends { tenant_id: string }>(value: T, auth: RequestAuthHeaders): T {
  if (value?.tenant_id !== auth.tenantId) throw new ApiError(409, "RESPONSE_SCOPE_MISMATCH", "Preference response scope mismatch");
  return value;
}
function checkedCapabilities(value: RuntimeCapabilities, auth: RequestAuthHeaders) {
  scoped(value, auth);
  if (!["SYNTHETIC", "CLOSED"].includes(value.mode) ||
      [value.can_record_preferences, value.can_revoke_preferences, value.integrated_demo_ready].some(flag => typeof flag !== "boolean") ||
      !Array.isArray(value.blockers) || value.blockers.some(code => typeof code !== "string")) {
    throw new ApiError(409, "UNSUPPORTED_RESPONSE", "Unsupported runtime capability response");
  }
  return value;
}
function checkedPreference(value: RecipientPreference, auth: RequestAuthHeaders) {
  scoped(value, auth);
  if (!["OPTED_IN", "OPTED_OUT"].includes(value.consent_status) ||
      !["MOCK_EMAIL", "MOCK_WHATSAPP", "MOCK_TELEGRAM"].includes(value.channel) ||
      value.consent_purpose !== "TRANSACTIONAL_REVISED_TERMS" || value.source !== "SYNTHETIC_FIXTURE" ||
      !Number.isSafeInteger(value.version) || value.version < 1 ||
      !Number.isFinite(Date.parse(value.consent_expires_at)) || !Number.isFinite(Date.parse(value.updated_at))) {
    throw new ApiError(409, "UNSUPPORTED_RESPONSE", "Unsupported preference response");
  }
  return value;
}

export function RecipientPreferences({ auth }: { auth: RequestAuthHeaders }) {
  // Parent session remounts on tenant/actor change; old scoped responses stay isolated.
  const client = useQueryClient();
  const [open, setOpen] = useState(false);
  const [customer, setCustomer] = useState("");
  const [channel, setChannel] = useState<RecipientPreference["channel"]>("MOCK_EMAIL");
  const [evidence, setEvidence] = useState("");
  const [expiry, setExpiry] = useState("");
  const [pending, setPending] = useState<Record<string, unknown> | null>(null);
  const capabilities = useQuery({ queryKey: [...communicationKeys.scope(auth), "runtime-capabilities"],
    queryFn: async ({ signal }) => checkedCapabilities(await apiRequest<RuntimeCapabilities>(`${base}/runtime-capabilities`,
      { headers: authHeaders(auth), signal }), auth), retry: false, staleTime: 0 });
  const preferences = useQuery({ queryKey: [...communicationKeys.scope(auth), "preferences"],
    queryFn: async ({ signal }) => {
      const values = await apiRequest<RecipientPreference[]>(`${base}/recipient-preferences`, { headers: authHeaders(auth), signal });
      if (!Array.isArray(values)) throw new ApiError(409, "UNSUPPORTED_RESPONSE", "Expected preference list");
      return values.map(value => checkedPreference(value, auth));
    }, enabled: open && capabilities.data?.mode === "SYNTHETIC", retry: false, staleTime: 0 });
  const save = useMutation({ mutationFn: async (body: Record<string, unknown>) => checkedPreference(
    await apiRequest<RecipientPreference>(`${base}/recipient-preferences`, {
      method: "POST", headers: authHeaders(auth), body: JSON.stringify(body) }), auth),
    onSuccess: () => { setPending(null); setEvidence(""); void client.invalidateQueries({ queryKey: communicationKeys.scope(auth) }); } });
  const current = preferences.data?.find(row => row.customer_id === customer && row.channel === channel);
  const ready = capabilities.isSuccess && !capabilities.isFetching;
  const stage = (row?: RecipientPreference) => {
    if (save.isPending || !evidence.trim() || (!row && !expiry)) return;
    save.reset();
    setPending({ request_key: crypto.randomUUID(), customer_id: row?.customer_id ?? customer,
      channel: row?.channel ?? channel, consent_purpose: "TRANSACTIONAL_REVISED_TERMS",
      consent_status: row ? "OPTED_OUT" : "OPTED_IN", source: "SYNTHETIC_FIXTURE",
      consent_evidence_ref: evidence, consent_expires_at: row?.consent_expires_at ?? new Date(expiry).toISOString(),
      expected_version: row?.version ?? current?.version ?? 0,
      allowed_contact_hours: row?.allowed_contact_hours ?? { start_hour: 0, end_hour: 24 },
      timezone: row?.timezone ?? "Asia/Kuala_Lumpur" });
  };
  return <section className="cc-preferences" aria-label="Authority and recipient preferences">
    {capabilities.isFetching ? <p role="status">Checking communication authority…</p> : capabilities.isError ?
      <div role="alert" className="cc-error p4-authority-notice"><p>{problem(capabilities.error)}</p><ApiErrorReference error={capabilities.error} /><button className="btn btn-secondary" onClick={() => void capabilities.refetch()}>Retry authority status</button></div> :
      capabilities.data ? <>
        <p className="cc-demo-label">{capabilities.data.mode === "SYNTHETIC" ? "Synthetic Demo — No Real Messages Sent" : "Production authority unavailable — actions remain blocked"}</p>
        {!capabilities.data.integrated_demo_ready && <details><summary>Integration dependencies pending</summary>
          <ul>{capabilities.data.blockers.map(code => <li key={code}>{reasonText(code)}</li>)}</ul>
        </details>}
      </> : null}
    <button className="btn btn-secondary" aria-expanded={open} onClick={() => setOpen(value => !value)}>Recipient preferences</button>
    {open && <div>
      <p className="muted">Transactional revised terms only. Verified contact does not imply consent. Synthetic fixture permissions expire and never authorize real sending.</p>
      {capabilities.data?.mode !== "SYNTHETIC" ? <p>Explicit synthetic scope or trusted production authorization is required.</p> : <>
        {preferences.isFetching ? <p role="status">Loading recipient preferences…</p> : preferences.isError ?
          <div role="alert" className="cc-error"><p>{problem(preferences.error)}</p><ApiErrorReference error={preferences.error} /><button className="btn btn-secondary" onClick={() => void preferences.refetch()}>Retry preferences</button></div> :
          preferences.data?.length ? <ul className="cc-preference-list">{preferences.data.map(row => <li key={`${row.customer_id}:${row.channel}`}>
            <strong>{row.customer_id}</strong> · {row.channel} · {row.consent_status}<br />
            <span>{row.consent_purpose} · Evidence: {row.consent_evidence_ref}</span><br />
            <span>Last updated {formatKLTimestamp(row.updated_at)} · {row.updated_by_actor_id}</span><br />
            <button className="btn btn-secondary" disabled={!ready || !capabilities.data?.can_revoke_preferences || row.consent_status === "OPTED_OUT" || !evidence.trim() || save.isPending || !!pending}
              onClick={() => stage(row)}>Revoke {row.customer_id} {row.channel}</button>
          </li>)}</ul> : <p>No recipient permissions recorded. Missing permission never means opt-in.</p>}
        <form className="cc-preference-form" onSubmit={event => { event.preventDefault(); stage(); }}>
          <label>Customer ID<input value={customer} onChange={event => setCustomer(event.target.value)} required /></label>
          <label>Preference channel<select value={channel} onChange={event => setChannel(event.target.value as RecipientPreference["channel"])}>
            {["MOCK_EMAIL", "MOCK_WHATSAPP", "MOCK_TELEGRAM"].map(value => <option key={value}>{value}</option>)}
          </select></label>
          <label>Synthetic consent evidence reference<input value={evidence} onChange={event => setEvidence(event.target.value)} placeholder="synthetic:consent:fixture_reference" required pattern="synthetic:consent:[A-Za-z0-9_-]+" /></label>
          <label>Permission expiry (your local time)<input type="datetime-local" value={expiry} onChange={event => setExpiry(event.target.value)} required /></label>
          <p>Purpose: Transactional revised terms · Contact hours: 00:00–24:00 Asia/Kuala_Lumpur</p>
          <button className="btn btn-secondary" disabled={!ready || !capabilities.data?.can_record_preferences || !preferences.isSuccess || preferences.isFetching || save.isPending || !!pending}>Record synthetic permission</button>
        </form>
        {!capabilities.data?.can_record_preferences && <p>Recording permission requires a manager and P1's typed verified contact contract.</p>}
        {pending && <div role="group" aria-label="Confirm preference change">
          <p>Confirm {String(pending.consent_status)} for {String(pending.customer_id)} on {String(pending.channel)}?</p>
          <button className="btn btn-primary" disabled={save.isPending || !ready ||
            !(pending.consent_status === "OPTED_OUT" ? capabilities.data?.can_revoke_preferences : capabilities.data?.can_record_preferences)}
            onClick={() => save.mutate(pending)}>Confirm preference change</button>
          <button className="btn btn-secondary" disabled={save.isPending} onClick={() => { setPending(null); save.reset(); }}>Cancel preference change</button>
        </div>}
        {save.isError && <div role="alert" className="cc-error"><p>{problem(save.error)} Refresh preferences after a conflict. Retrying this confirmation uses the same request key.</p><ApiErrorReference error={save.error} /></div>}
        {save.isSuccess && <p role="status">Preference change persisted. Sending still requires current approval and eligibility.</p>}
      </>}
    </div>}
  </section>;
}
