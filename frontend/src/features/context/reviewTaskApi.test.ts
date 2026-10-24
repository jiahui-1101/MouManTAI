import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  detectReviewTaskCapability,
  getReviewTask,
  listReviewTasks,
  resetReviewTaskCapabilityCache,
  resolveReviewTask,
} from './reviewTaskApi';
import { operationalApi } from './operationalApi';
import type { StoredMessage, OrderContextRecord } from './types';

const mockStoredMessage: StoredMessage = {
  message_id: 'msg_test_001',
  raw: {
    tenant_id: 'test_tenant',
    channel: 'EMAIL',
    provider_message_id: 'provider_001',
    sender_identity_id: 'bob@example.com',
    sender_alias: 'Bob Dylan',
    received_at: '2026-10-24T12:00:00Z',
    text: 'Need 50 sourdough loaves for morning delivery.',
  },
  provider: 'GMAIL_API',
  source_label: 'Gmail',
  content_sha256: 'sha256_mock_hash_bob',
  processing_status: 'PROCESSING_FAILED',
  extractor_version: 'p1-v6',
  ingested_at: '2026-10-24T12:00:00Z',
  updated_at: '2026-10-24T12:00:00Z',
};

const mockContext: OrderContextRecord = {
  context_id: 'ctx_test_001',
  tenant_id: 'test_tenant',
  order_id: 'ORD-TEST-1',
  customer_identity_status: 'UNVERIFIED',
  status: 'INFORMATION_PARTIAL',
  requested_items: [{ sku: 'SOURDOUGH', quantity: '50', unit: 'pcs' }],
  context_version: 3,
  created_at: '2026-10-24T12:00:00Z',
  updated_at: '2026-10-24T12:00:00Z',
};

describe('reviewTaskApi adapter', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    resetReviewTaskCapabilityCache();
  });

  describe('detectReviewTaskCapability', () => {
    it('detects AUTHORITATIVE when /v1/reviews returns 200', async () => {
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({ items: [], total: 0 }),
      }));

      const capability = await detectReviewTaskCapability();
      expect(capability).toBe('AUTHORITATIVE');
    });

    it('detects PROVISIONAL when /v1/reviews returns 404', async () => {
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
        ok: false,
        status: 404,
      }));

      const capability = await detectReviewTaskCapability();
      expect(capability).toBe('PROVISIONAL');
    });
  });

  describe('listReviewTasks', () => {
    it('calls GET /v1/reviews in authoritative mode with query params', async () => {
      const mockBackendTask = {
        task_id: 'task_backend_1',
        tenant_id: 'test_tenant',
        task_type: 'AMBIGUITY',
        status: 'OPEN',
        priority: 'HIGH',
        snippet: 'Sample task',
        created_at: '2026-10-24T12:00:00Z',
        updated_at: '2026-10-24T12:00:00Z',
        version: 1,
      };

      const fetchMock = vi.fn()
        // First call: capability check
        .mockResolvedValueOnce({ ok: true, status: 200 })
        // Second call: query list
        .mockResolvedValueOnce({
          ok: true,
          status: 200,
          json: async () => ({ items: [mockBackendTask], total: 1 }),
        });

      vi.stubGlobal('fetch', fetchMock);

      const result = await listReviewTasks({ status: 'OPEN', priority: 'HIGH', limit: 10 });
      expect(result.mode).toBe('AUTHORITATIVE_BACKEND_QUEUE');
      expect(result.tasks).toHaveLength(1);
      expect(result.tasks[0].task_id).toBe('task_backend_1');
      expect(result.tasks[0].source_mode).toBe('AUTHORITATIVE_BACKEND_QUEUE');
    });

    it('falls back to operationalApi.list in provisional mode', async () => {
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 404 }));
      vi.spyOn(operationalApi, 'list').mockResolvedValue({
        items: [mockStoredMessage],
        total: 1,
        limit: 50,
        offset: 0,
      });

      const result = await listReviewTasks({ search: 'sourdough' });
      expect(result.mode).toBe('PROVISIONAL_INQUIRY_PROJECTION');
      expect(result.tasks).toHaveLength(1);
      expect(result.tasks[0].task_id).toBe('msg_test_001');
      expect(result.tasks[0].task_type).toBe('FAILED_EXTRACTION');
      expect(result.tasks[0].priority).toBe('HIGH');
      expect(result.tasks[0].source_mode).toBe('PROVISIONAL_INQUIRY_PROJECTION');
    });

    it('gets a single task projecting from operationalApi.detail in provisional mode', async () => {
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 404 }));
      vi.spyOn(operationalApi, 'detail').mockResolvedValue(mockStoredMessage);

      const task = await getReviewTask('msg_test_001');
      expect(task.task_id).toBe('msg_test_001');
      expect(task.source_mode).toBe('PROVISIONAL_INQUIRY_PROJECTION');
    });
  });

  describe('resolveReviewTask', () => {
    it('calls POST /v1/reviews/{id}/resolve in authoritative mode', async () => {
      const fetchMock = vi.fn()
        .mockResolvedValueOnce({ ok: true, status: 200 }) // capability
        .mockResolvedValueOnce({
          ok: true,
          status: 200,
          json: async () => ({
            task_id: 'task_001',
            status: 'RESOLVED',
            resolved_by: 'user_staff_01',
            resolved_at: '2026-10-24T12:00:00Z',
            resolution: 'RESOLVED_WITH_EDITS',
          }),
        });

      vi.stubGlobal('fetch', fetchMock);

      const response = await resolveReviewTask('task_001', {
        expected_task_version: 1,
        resolution: 'RESOLVED_WITH_EDITS',
        field_edits: { requested_items: [{ sku: 'SOURDOUGH', quantity: '50', unit: 'pcs' }] },
      });

      expect(response.status).toBe('RESOLVED');
      expect(response.resolution).toBe('RESOLVED_WITH_EDITS');
    });

    it('falls back to operationalApi.reviewContext in provisional mode', async () => {
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 404 }));
      vi.spyOn(operationalApi, 'reviewContext').mockResolvedValue({
        ...mockContext,
        context_version: 4,
      });

      const response = await resolveReviewTask(
        'msg_test_001',
        {
          expected_task_version: 3,
          resolution: 'RESOLVED_WITH_EDITS',
          field_edits: { requested_items: [{ sku: 'SOURDOUGH', quantity: '50', unit: 'pcs' }] },
          note: 'Confirmed packaging',
        },
        'ctx_test_001'
      );

      expect(operationalApi.reviewContext).toHaveBeenCalledWith(
        'ctx_test_001',
        {
          expected_context_version: 3,
          action: 'EDIT_FIELD',
          field_edits: { requested_items: [{ sku: 'SOURDOUGH', quantity: '50', unit: 'pcs' }] },
          note: 'Confirmed packaging',
        },
        expect.any(Object)
      );
      expect(response.updated_context_version).toBe(4);
      expect(response.status).toBe('RESOLVED');
    });

    it('throws error when contextId is absent in provisional mode', async () => {
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 404 }));

      await expect(
        resolveReviewTask('msg_test_001', {
          expected_task_version: 1,
          resolution: 'RESOLVED_WITH_EDITS',
        })
      ).rejects.toThrow(/Target context ID required/i);
    });
  });
});
