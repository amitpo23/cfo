import { describe, expect, it } from 'vitest';
import { candidateKey, defaultCandidate, documentsNear, entityLabel, gapAccepted, matchGap, type MatchRow } from './bankMatchModel';

function row(partial: Partial<MatchRow>): MatchRow {
  return {
    id: 1, date: '2026-10-05', amount: -100, counterparty: '', description: '', category: 'suppliers',
    status: 'open', status_he: 'ממתין להחלטה', note: null, matched: null, auto_match: null, candidates: [],
    ...partial,
  };
}

const best = { entity_type: 'bill' as const, entity_id: 7, score: 0.9, amount: 100, date: '2026-10-04', name: 'א' };
const auto = { entity_type: 'expense' as const, entity_id: 9, score: null, amount: 90, date: null, name: 'ב' };

describe('defaultCandidate', () => {
  it('is null when no document fits — nothing is guessed', () => {
    expect(defaultCandidate(row({}))).toBeNull();
  });

  it('prefers the auto match over the best score', () => {
    const picked = defaultCandidate(row({ candidates: [best, auto], auto_match: { entity_type: 'expense', entity_id: 9 } }));
    expect(picked && candidateKey(picked)).toBe('expense:9');
  });

  it('falls back to the best score', () => {
    expect(defaultCandidate(row({ candidates: [best] }))?.entity_id).toBe(7);
  });
});

describe('entityLabel', () => {
  it('names the document type in Hebrew', () => {
    expect(entityLabel('bill', 3)).toBe('חשבון ספק #3');
  });
});

describe('1:N match', () => {
  const z1 = { entity_type: 'invoice' as const, entity_id: 1, score: null, amount: 4000, date: '2026-10-01', name: 'Z' };
  const z2 = { entity_type: 'invoice' as const, entity_id: 2, score: null, amount: 6000, date: '2026-10-02', name: 'Z' };
  const refund = { entity_type: 'expense' as const, entity_id: 3, score: null, amount: 100, date: '2026-09-25', name: 'החזר', credit: true };
  const old = { entity_type: 'bill' as const, entity_id: 4, score: null, amount: -50, date: '2026-06-01', name: 'ישן' };

  it('a Max deposit = Σ invoices − fee, within ₪1', () => {
    const gap = matchGap(9700.4, [z1, z2], 300);
    expect(gap).toBe(0.4);
    expect(gapAccepted(gap)).toBe(true);
    expect(gapAccepted(matchGap(9700.4, [z1, z2], 0))).toBe(false);
  });

  it('a refund on a card statement reduces the charge', () => {
    const fuel = { ...z1, entity_type: 'expense' as const, amount: -1000 };
    const office = { ...z2, entity_type: 'expense' as const, amount: -600 };
    expect(matchGap(-1500, [fuel, office, refund], 0)).toBe(0);
  });

  it('offers documents dated near the bank row only', () => {
    expect(documentsNear([z1, refund, old], { date: '2026-10-15' }).map((doc) => doc.entity_id)).toEqual([1, 3]);
  });
});
