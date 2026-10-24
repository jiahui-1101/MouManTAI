import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  detectClarificationCapability,
  getConversationIssues,
  resetClarificationCapabilityCache,
  sendClarification,
} from './clarificationApi';
import type { OrderContextRecord } from './types';

const mockContext: OrderContextRecord = {
  context_id: 'ctx_issue_1',
  tenant_id: 'tenant_main',
  order_id: 'ORD-ISSUE-1',
  customer_identity_status: 'UNVERIFIED',
  status: 'INFORMATION_PARTIAL',
  missing_fields: ['quantity', 'requested_delivery_at'],
  conflicts: ['Delivery date falls on a public holiday'],
  requested_items: [{ sku: 'SOURDOUGH', quantity: '', unit: 'pcs' }],
  context_version: 2,
  created_at: '2026-10-24T10:00:00Z',
  updated_at: '2026-10-24T10:00:00Z',
};

describe('clarificationApi adapter', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    resetClarificationCapabilityCache();
  });

  describe('detectClarificationCapability', () => {
    it('detects AUTHORITATIVE when endpoint returns 200', async () => {
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({ issues: [] }),
      }));

      const capability = await detectClarificationCapability('conv_01');
      expect(capability).toBe('AUTHORITATIVE');
    });

    it('detects PROVISIONAL when endpoint returns 404', async () => {
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
        ok: false,
        status: 404,
      }));

      const capability = await detectClarificationCapability('conv_01');
      expect(capability).toBe('PROVISIONAL');
    });
  });

  describe('getConversationIssues', () => {
    it('fetches authoritative issues when backend is available', async () => {
      const mockBackendResponse = {
        conversation_id: 'conv_auth_1',
        tenant_id: 'tenant_main',
        issues: [
          {
            issue_id: 'iss_backend_1',
            field_name: 'unit',
            proposed_candidates: ['box', 'pcs'],
            original_problem: 'Unit ambiguous',
            consecutive_no_progress_count: 1,
            status: 'AWAITING_REPLY',
            questions_sent: [],
            customer_responses: [],
          },
        ],
        total_turns_used: 1,
        max_turns_allowed: 2,
        has_escalated_issues: false,
      };

      const fetchMock = vi.fn()
        .mockResolvedValueOnce({ ok: true, status: 200 }) // capability
        .mockResolvedValueOnce({
          ok: true,
          status: 200,
          json: async () => mockBackendResponse,
        });

      vi.stubGlobal('fetch', fetchMock);

      const res = await getConversationIssues('conv_auth_1', mockContext);
      expect(res.source_mode).toBe('AUTHORITATIVE_BACKEND');
      expect(res.issues).toHaveLength(1);
      expect(res.issues[0].field_name).toBe('unit');
    });

    it('projects issues from context missing_fields and conflicts in provisional mode', async () => {
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 404 }));

      const res = await getConversationIssues('conv_prov_1', mockContext);
      expect(res.source_mode).toBe('PROVISIONAL_CONTEXT_PROJECTION');
      expect(res.conversation_id).toBe('conv_prov_1');
      // 2 missing fields (quantity, requested_delivery_at) + 1 conflict
      expect(res.issues).toHaveLength(3);
      expect(res.issues.map(i => i.field_name)).toEqual(['quantity', 'requested_delivery_at', 'conflict']);
      expect(res.total_turns_used).toBe(0);
      expect(res.max_turns_allowed).toBe(2);
      expect(res.has_escalated_issues).toBe(false);
    });

    it('returns empty issues array safely when context is null', async () => {
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 404 }));

      const res = await getConversationIssues('conv_prov_empty', null);
      expect(res.issues).toHaveLength(0);
      expect(res.has_escalated_issues).toBe(false);
    });
  });

  describe('sendClarification', () => {
    it('dispatches to POST /v1/conversations/{id}/clarify when authoritative', async () => {
      const fetchMock = vi.fn()
        .mockResolvedValueOnce({ ok: true, status: 200 }) // capability
        .mockResolvedValueOnce({
          ok: true,
          status: 200,
          json: async () => ({
            outbound_id: 'out_auth_999',
            delivery_status: 'SENT',
            sent_at: '2026-10-24T12:00:00Z',
          }),
        });

      vi.stubGlobal('fetch', fetchMock);

      const response = await sendClarification({
        conversation_id: 'conv_send_1',
        draft_text: 'Please confirm whether you want boxes or pieces.',
        issue_ids: ['iss_1'],
        channel: 'EMAIL',
        recipient_identity_id: 'alice@example.com',
      });

      expect(response.delivery_status).toBe('SENT');
      expect(response.backend_status).toBe('SENT');
      expect(response.outbound_id).toBe('out_auth_999');
    });

    it('returns PREVIEW_NOT_SENT in provisional mode without simulating external send', async () => {
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 404 }));

      const response = await sendClarification({
        conversation_id: 'conv_send_prov',
        draft_text: 'Please clarify delivery date.',
        issue_ids: ['iss_deliv'],
        channel: 'EMAIL',
        recipient_identity_id: 'bob@example.com',
      });

      expect(response.delivery_status).toBe('PREVIEW_NOT_SENT');
      expect(response.backend_status).toBe('PREVIEW_NOT_SENT');
      expect(response.error_reason).toContain('not deployed');
      expect(response.error_reason).toContain('PREVIEW ONLY · NOT SENT');
    });
  });
});
