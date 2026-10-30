import { describe, expect, it } from 'vitest';
import { candidateKey, defaultCandidate, entityLabel, type MatchRow } from './bankMatchModel';

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
