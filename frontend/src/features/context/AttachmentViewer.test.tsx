import { describe, expect, it, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { AttachmentViewer } from './AttachmentViewer';
import type { OperationalApi } from './operationalApi';
import type { AttachmentRecord, DocumentExtractionResult } from './types';

const mockMetadata: AttachmentRecord = {
  attachment_id: 'att_test_100',
  tenant_id: 'synthetic_tenant_a',
  evidence_ref: 'ev_att_test_100',
  filename: 'order_receipt.pdf',
  media_type: 'application/pdf',
  size_bytes: 20480,
  content_sha256: 'a1b2c3d4e5f67890123456789abcdef0123456789abcdef0123456789abcdef0',
  created_at: '2026-10-21T10:00:00Z',
};

const mockOrderExtraction: DocumentExtractionResult = {
  attachment_id: 'att_test_100',
  evidence_ref: 'ev_att_test_100',
  status: 'SUCCESS',
  document_type: 'PDF',
  page_count: 1,
  text_content: 'Purchase Order PO-2026-901\n50 pcs burgers\nDelivery 2026-11-15',
  extracted_fields: [
    {
      field_name: 'order_id',
      value: 'PO-2026-901',
      validation_status: 'UNRESOLVED',
      page_number: 1,
    },
    {
      field_name: 'item',
      sku: 'BURGER',
      product_name: 'Burger',
      quantity: 50,
      unit: 'pcs',
      validation_status: 'VALID',
      page_number: 1,
    },
    {
      field_name: 'requested_delivery_at',
      value: '2026-11-15',
      validation_status: 'VALID',
      page_number: 1,
    },
  ],
  evidence_items: [
    {
      evidence_id: 'ev:att_test_100:p1:b0',
      evidence_ref: 'ev_att_test_100',
      attachment_id: 'att_test_100',
      page_number: 1,
      quote: 'Purchase Order PO-2026-901',
      bounding_box: { x0: 50, y0: 72, x1: 200, y1: 90 },
      method: 'PDF_TEXT',
      method_version: 'p1-pdf-v1',
      confidence: 1.0,
      is_payment_evidence: false,
    },
  ],
  is_payment_notice: false,
  diagnostic: null,
  extracted_at: '2026-10-21T10:05:00Z',
};

const mockPaymentExtraction: DocumentExtractionResult = {
  attachment_id: 'att_test_100',
  evidence_ref: 'ev_att_test_100',
  status: 'SUCCESS',
  document_type: 'IMAGE',
  page_count: 1,
  text_content: 'DuitNow Transfer Successful\nAmount RM 350.00',
  extracted_fields: [
    {
      field_name: 'payment_notice',
      value: 'UNVERIFIED_EVIDENCE',
      validation_status: 'UNVERIFIED_EVIDENCE',
      disclaimer: 'Payment slips and receipts are strictly unverified evidence. P1 never infers verified payment, identity, or fulfilment.',
      page_number: 1,
    },
  ],
  evidence_items: [
    {
      evidence_id: 'ev:att_test_100:ocr:0',
      evidence_ref: 'ev_att_test_100',
      attachment_id: 'att_test_100',
      page_number: 1,
      quote: 'DuitNow Transfer Successful',
      bounding_box: { x0: 20, y0: 30, x1: 250, y1: 60 },
      method: 'OCR',
      method_version: 'p1-paddleocr-v1',
      confidence: 0.985,
      is_payment_evidence: true,
    },
  ],
  is_payment_notice: true,
  diagnostic: null,
  extracted_at: '2026-10-21T10:05:00Z',
};

function createMockApi(overrides: Partial<OperationalApi> = {}): OperationalApi {
  return {
    config: vi.fn(),
    list: vi.fn(),
    detail: vi.fn(),
    ingest: vi.fn(),
    process: vi.fn(),
    getExtraction: vi.fn(),
    listAttempts: vi.fn(),
    getAssociation: vi.fn(),
    decideAssociation: vi.fn(),
    getContext: vi.fn(),
    getContextByOrder: vi.fn(),
    createContextFromMessage: vi.fn(),
    reviewContext: vi.fn(),
    updateContext: vi.fn(),
    listContextVersions: vi.fn(),
    listContextReviews: vi.fn(),
    uploadAttachment: vi.fn(),
    extractAttachment: vi.fn().mockResolvedValue(mockOrderExtraction),
    getAttachmentExtraction: vi.fn().mockResolvedValue(mockOrderExtraction),
    getAttachmentMetadata: vi.fn().mockResolvedValue(mockMetadata),
    ...overrides,
  };
}

describe('AttachmentViewer', () => {
  it('renders metadata and order extraction results', async () => {
    const api = createMockApi();
    render(<AttachmentViewer evidenceRef="ev_att_test_100" onClose={vi.fn()} api={api} />);

    // Wait for metadata to load
    await waitFor(() => {
      expect(screen.getByText(/order_receipt\.pdf/i)).toBeInTheDocument();
    });

    expect(screen.getByText(/application\/pdf/i)).toBeInTheDocument();
    expect(screen.getByText(/20\.0 KB/i)).toBeInTheDocument();

    // Check extracted fields
    await waitFor(() => {
      expect(screen.getByText('PO-2026-901')).toBeInTheDocument();
      expect(screen.getByText(/50 pcs/i)).toBeInTheDocument();
      expect(screen.getByText('2026-11-15')).toBeInTheDocument();
    });

    // Check evidence item
    expect(screen.getByText(/PDF_TEXT \(p1-pdf-v1\)/i)).toBeInTheDocument();
    expect(screen.getByText(/"Purchase Order PO-2026-901"/i)).toBeInTheDocument();
  });

  it('prominently renders UNVERIFIED PAYMENT EVIDENCE banner when payment notice detected', async () => {
    const api = createMockApi({
      getAttachmentExtraction: vi.fn().mockResolvedValue(mockPaymentExtraction),
    });
    render(<AttachmentViewer evidenceRef="ev_att_test_100" onClose={vi.fn()} api={api} />);

    await waitFor(() => {
      const alert = screen.getByTestId('unverified-payment-alert');
      expect(alert).toBeInTheDocument();
      expect(alert).toHaveTextContent(/UNVERIFIED EVIDENCE: Payment Screenshot \/ Bank Slip/i);
      expect(alert).toHaveTextContent(/strictly unverified evidence/i);
    });
  });

  it('triggers extraction when clicking Run Extraction / OCR button', async () => {
    const extractMock = vi.fn().mockResolvedValue(mockOrderExtraction);
    const api = createMockApi({
      getAttachmentExtraction: vi.fn().mockRejectedValue(new Error('Not yet extracted')),
      extractAttachment: extractMock,
    });

    render(<AttachmentViewer evidenceRef="ev_att_test_100" onClose={vi.fn()} api={api} />);

    await waitFor(() => {
      expect(screen.getByTestId('extract-btn')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId('extract-btn'));

    await waitFor(() => {
      expect(extractMock).toHaveBeenCalledWith('ev_att_test_100');
      expect(screen.getByText('PO-2026-901')).toBeInTheDocument();
    });
  });

  it('calls onClose callback when clicking close button', async () => {
    const handleClose = vi.fn();
    const api = createMockApi();
    render(<AttachmentViewer evidenceRef="ev_att_test_100" onClose={handleClose} api={api} />);

    await waitFor(() => {
      expect(screen.getByLabelText(/close attachment viewer/i)).toBeInTheDocument();
    });

    fireEvent.click(screen.getByLabelText(/close attachment viewer/i));
    expect(handleClose).toHaveBeenCalledOnce();
  });
});
