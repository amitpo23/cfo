// Mirrors ISRAEL_INVOICE_ALLOCATION_THRESHOLDS in
// src/cfo/services/israeli_tax_rules.py (amount before VAT, strict >).
// The backend returns the authoritative warning; this one is for the form.
const ALLOCATION_THRESHOLDS: ReadonlyArray<[string, number]> = [
  ['2026-06-01', 5000],
  ['2026-01-01', 10000],
  ['2025-01-01', 20000],
];

const ALLOCATION_DOCUMENT_TYPES = new Set(['invoice', 'invoice_receipt']);

export function normalizeTaxId(raw: string): { value: string | null; error: string | null } {
  const value = raw.replace(/[\s-]/g, '');
  if (!value) return { value: null, error: null };
  if (!/^\d{9}$/.test(value)) return { value: null, error: 'ח.פ / ע.מ חייב להכיל 9 ספרות בדיוק' };
  return { value, error: null };
}

export function allocationWarning(
  documentType: string,
  netTotal: number,
  taxId: string | null,
  issueDate: string,
): string | null {
  if (!ALLOCATION_DOCUMENT_TYPES.has(documentType) || taxId) return null;
  const threshold = ALLOCATION_THRESHOLDS.find(([from]) => issueDate >= from)?.[1];
  if (threshold === undefined || netTotal <= threshold) return null;
  return `הסכום לפני מע״מ מעל ₪${threshold.toLocaleString('en-US')} ואין ח.פ / ע.מ — SUMIT לא יבקש מספר הקצאה, והלקוח לא יוכל לנכות את המע״מ.`;
}
