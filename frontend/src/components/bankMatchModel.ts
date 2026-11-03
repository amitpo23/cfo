export type MatchStatus = 'approved' | 'check' | 'missing_doc' | 'open';

export type EntityType = 'invoice' | 'bill' | 'expense';

/** A book document. ``amount`` is its signed effect on the bank: a sale is +, a bill or expense −, a credit flips it. */
export type Candidate = {
  entity_type: EntityType;
  entity_id: number;
  score: number | null;
  amount: number;
  date: string | null;
  name: string;
  credit?: boolean;
};

export type MatchedLine = { entity_type: EntityType; entity_id: number; amount: number };

export type Matched = {
  kind: 'documents' | 'category' | null;
  documents: MatchedLine[];
  fee: number | null;
  category: string | null;
  category_he: string | null;
  target_account: string | null;
};

export type MatchRow = {
  id: number;
  date: string;
  amount: number;
  counterparty: string;
  description: string;
  category: string;
  status: MatchStatus;
  status_he: string;
  note: string | null;
  matched: Matched | null;
  auto_match: { entity_type: string; entity_id: number } | null;
  candidates: Candidate[];
  warning?: { code: string; label_he: string; invoices: number[] } | null;
};

export type Bucket = { count: number; amount: number; abs_amount?: number };

export type MatchReport = {
  start: string;
  end: string;
  rows: MatchRow[];
  summary: Record<MatchStatus | 'total', Bucket> & {
    balanced: boolean; decided: boolean; done: boolean; coverage_ok: boolean; warnings?: number;
  };
  categories?: Record<string, string>;
  documents?: Candidate[];
  partial_banner?: { text_he?: string | null };
  closing?: { done: boolean; label_he: string };
  read_only?: boolean;
};

/** The server accepts a 1:N approval when |bank − (Σ documents − fee)| ≤ this. */
export const TOLERANCE = 1;

const ENTITY_HE: Record<string, string> = { invoice: 'חשבונית', bill: 'חשבון ספק', expense: 'הוצאה' };

export function entityLabel(entityType: string, entityId: number): string {
  return `${ENTITY_HE[entityType] || entityType} #${entityId}`;
}

/** The candidate an אשר would apply: the owner's pick, else the auto match, else the best score. */
export function defaultCandidate(row: MatchRow): Candidate | null {
  if (row.auto_match) {
    const auto = row.candidates.find(
      (item) => item.entity_type === row.auto_match?.entity_type && item.entity_id === row.auto_match?.entity_id,
    );
    if (auto) return auto;
  }
  return row.candidates[0] ?? null;
}

export function candidateKey(candidate: Pick<Candidate, 'entity_type' | 'entity_id'>): string {
  return `${candidate.entity_type}:${candidate.entity_id}`;
}

function shiftDays(iso: string, days: number): string {
  const at = new Date(`${iso.slice(0, 10)}T00:00:00Z`);
  at.setUTCDate(at.getUTCDate() + days);
  return at.toISOString().slice(0, 10);
}

/** Documents to pick from for one row: dated 45 days before to 7 days after it (undated ones stay). */
export function documentsNear(documents: Candidate[], row: Pick<MatchRow, 'date'>): Candidate[] {
  const low = shiftDays(row.date, -45);
  const high = shiftDays(row.date, 7);
  return documents.filter((doc) => !doc.date || (doc.date >= low && doc.date <= high));
}

/** Bank amount minus (Σ picked documents − fee). Zero is a full match. */
export function matchGap(bankAmount: number, picked: Candidate[], fee: number): number {
  const explained = picked.reduce((sum, doc) => sum + doc.amount, 0) - fee;
  return Math.round((bankAmount - explained) * 100) / 100;
}

export function gapAccepted(gap: number): boolean {
  return Math.abs(gap) <= TOLERANCE;
}
