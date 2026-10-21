import React, { useEffect, useState } from 'react';
import type { AttachmentRecord, DocumentExtractionResult, DocumentEvidence } from './types';
import { operationalApi, type OperationalApi } from './operationalApi';

export interface ExtractedDocField {
  field_name?: string;
  value?: string;
  sku?: string;
  product_name?: string;
  quantity?: number;
  unit?: string;
  validation_status?: string;
  quote?: string;
  page_number?: number;
  disclaimer?: string;
  is_payment_evidence?: boolean;
}

export interface AttachmentViewerProps {
  evidenceRef: string;
  onClose: () => void;
  api?: OperationalApi;
}

export const AttachmentViewer: React.FC<AttachmentViewerProps> = ({
  evidenceRef,
  onClose,
  api = operationalApi,
}) => {
  const [record, setRecord] = useState<AttachmentRecord | null>(null);
  const [extraction, setExtraction] = useState<DocumentExtractionResult | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [extracting, setExtracting] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const metadata = await api.getAttachmentMetadata(evidenceRef);
        if (active) setRecord(metadata);
        try {
          const ext = await api.getAttachmentExtraction(evidenceRef);
          if (active) setExtraction(ext);
        } catch {
          // If no extraction yet, leave null
        }
      } catch (err: unknown) {
        if (active) setError(err instanceof Error ? err.message : 'Failed to load attachment');
      } finally {
        if (active) setLoading(false);
      }
    }
    load();
    return () => {
      active = false;
    };
  }, [evidenceRef, api]);

  const handleExtract = async () => {
    setExtracting(true);
    setError(null);
    try {
      const res = await api.extractAttachment(evidenceRef);
      setExtraction(res);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Document extraction failed');
    } finally {
      setExtracting(false);
    }
  };

  const contentUrl = `/v1/attachments/${encodeURIComponent(evidenceRef)}/content`;

  return (
    <div className="attachment-viewer-backdrop" data-testid="attachment-viewer-modal" role="dialog" aria-modal="true">
      <div className="attachment-viewer-card">
        <header className="attachment-viewer-header">
          <div>
            <h3>{record?.filename ?? 'Attachment Inspection'}</h3>
            <span className="attachment-evidence-ref">Ref: {evidenceRef}</span>
          </div>
          <div className="attachment-header-actions">
            <a
              href={contentUrl}
              target="_blank"
              rel="noreferrer"
              className="attachment-download-link"
              download={record?.filename}
            >
              Download Original
            </a>
            <button className="button button-secondary" onClick={onClose} aria-label="Close attachment viewer">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" style={{ marginRight: '6px' }}>
                <line x1="18" y1="6" x2="6" y2="18"></line>
                <line x1="6" y1="6" x2="18" y2="18"></line>
              </svg>
              Close
            </button>
          </div>
        </header>

        {loading && <div className="loading-state">Loading document metadata...</div>}
        {error && <div className="error-banner">{error}</div>}

        {record && (
          <div className="attachment-metadata-strip">
            <span><strong>Format:</strong> {record.media_type}</span>
            <span><strong>Size:</strong> {(record.size_bytes / 1024).toFixed(1)} KB</span>
            <span><strong>SHA-256:</strong> {record.content_sha256.substring(0, 12)}…</span>
          </div>
        )}

        <div className="attachment-viewer-body">
          {/* Left panel: Preview */}
          <div className="attachment-preview-pane">
            <h4>Document Preview</h4>
            {record?.media_type.startsWith('image/') ? (
              <div className="attachment-image-container">
                <img src={contentUrl} alt={record.filename} className="attachment-preview-img" />
              </div>
            ) : record?.media_type === 'application/pdf' ? (
              <div className="attachment-pdf-container">
                <iframe src={contentUrl} title="PDF Preview" className="attachment-preview-frame" />
              </div>
            ) : (
              <div className="unsupported-preview">Preview not supported for this media type.</div>
            )}
          </div>

          {/* Right panel: OCR & Document Extraction */}
          <div className="attachment-extraction-pane">
            <div className="extraction-pane-header">
              <h4>Traceable Extraction & OCR</h4>
              <button
                className="button button-primary"
                onClick={handleExtract}
                disabled={extracting}
                data-testid="extract-btn"
              >
                {extracting ? 'Extracting...' : 'Run Extraction / OCR'}
              </button>
            </div>

            {/* UNVERIFIED PAYMENT EVIDENCE ALERT */}
            {extraction?.is_payment_notice && (
              <div className="unverified-payment-banner" data-testid="unverified-payment-alert">
                <div className="alert-icon">
                  <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                    <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path>
                    <line x1="12" y1="9" x2="12" y2="13"></line>
                    <line x1="12" y1="17" x2="12.01" y2="17"></line>
                  </svg>
                </div>
                <div className="alert-body">
                  <strong>UNVERIFIED EVIDENCE: Payment Screenshot / Bank Slip</strong>
                  <p>
                    Bank slips, transfer receipts, and payment screenshots are strictly unverified evidence.
                    P1 never infers verified payment, identity, or fulfillment from user-uploaded slips.
                  </p>
                </div>
              </div>
            )}

            {extraction ? (
              <div className="extraction-content">
                <div className="extraction-status-row">
                  <span className={`status-badge status-${extraction.status.toLowerCase()}`}>
                    Status: {extraction.status}
                  </span>
                  <span>Pages: {extraction.page_count}</span>
                  {extraction.diagnostic && <small className="extraction-diagnostic">{extraction.diagnostic}</small>}
                </div>

                {/* Structured Extracted Fields */}
                <div className="extracted-fields-group">
                  <h5>Extracted Structured Fields</h5>
                  {(() => {
                    const fields = (extraction.extracted_fields as ExtractedDocField[] | undefined) || [];
                    if (fields.length === 0) {
                      return <p className="no-fields-notice">No order fields detected from document text.</p>;
                    }
                    return (
                      <ul className="extracted-fields-list">
                        {fields.map((field, idx) => {
                          const statusStr = field.validation_status || 'UNKNOWN';
                          return (
                            <li key={idx} className="extracted-field-card" data-testid="extracted-field">
                              <div className="field-title">
                                <span className="field-name">{field.field_name}</span>
                                <span className={`field-status-badge status-${statusStr.toLowerCase()}`}>
                                  {statusStr}
                                </span>
                              </div>
                              {field.value && <div className="field-value"><strong>Value:</strong> {field.value}</div>}
                              {field.sku && (
                                <div className="field-item-details">
                                  <span><strong>SKU:</strong> {field.sku}</span>
                                  <span><strong>Qty:</strong> {field.quantity} {field.unit}</span>
                                </div>
                              )}
                              {field.quote && (
                                <blockquote className="field-quote">
                                  "{field.quote}" {field.page_number && <small>(Page {field.page_number})</small>}
                                </blockquote>
                              )}
                              {field.disclaimer && (
                                <div className="field-disclaimer">{field.disclaimer}</div>
                              )}
                            </li>
                          );
                        })}
                      </ul>
                    );
                  })()}
                </div>

                {/* Evidence quotes and bounding boxes */}
                {(() => {
                  const evItems = (extraction.evidence_items as DocumentEvidence[] | undefined) || [];
                  return (
                    <div className="evidence-items-group">
                      <h5>Text Evidence & Bounding Boxes ({evItems.length})</h5>
                      <div className="evidence-items-scroll">
                        {evItems.map((ev: DocumentEvidence) => (
                          <div
                            key={ev.evidence_id}
                            className={`evidence-item-card ${ev.is_payment_evidence ? 'payment-evidence' : ''}`}
                            data-testid="evidence-item"
                          >
                            <div className="evidence-meta">
                              <span className="evidence-method">{ev.method} ({ev.method_version})</span>
                              <span>Page {ev.page_number}</span>
                              {ev.confidence !== null && ev.confidence !== undefined && (
                                <span className="evidence-confidence">
                                  Conf: {(ev.confidence * 100).toFixed(1)}%
                                </span>
                              )}
                            </div>
                            <div className="evidence-quote">"{ev.quote}"</div>
                            {ev.bounding_box && (
                              <div className="evidence-bbox">
                                BBox: [{ev.bounding_box.x0}, {ev.bounding_box.y0}, {ev.bounding_box.x1}, {ev.bounding_box.y1}]
                              </div>
                            )}
                          </div>
                        ))}
                      </div>
                    </div>
                  );
                })()}
              </div>
            ) : (
              <div className="no-extraction-placeholder">
                <p>No document extraction has been performed yet.</p>
                <p>Click <strong>"Run Extraction / OCR"</strong> above to inspect machine-readable PDF text or execute PaddleOCR.</p>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
