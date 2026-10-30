export type MatchStatus = 'approved' | 'check' | 'missing_doc' | 'open';

export type Candidate = {
  entity_type: 'invoice' | 'bill' | 'expense';
  entity_id: number;
  score: number | null;
  amount: number;
  date: string | null;
  name: string;
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
  matched: { entity_type: string; entity_id: number } | null;
  auto_match: { entity_type: string; entity_id: number } | null;
  candidates: Candidate[];
};

export type Bucket = { count: number; amount: number };

export type MatchReport = {
  start: string;
  end: string;
  rows: MatchRow[];
  summary: Record<MatchStatus | 'total', Bucket> & { balanced: boolean; done: boolean };
  partial_banner?: { text_he?: string | null };
  read_only?: boolean;
};

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
