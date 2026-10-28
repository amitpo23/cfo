// The open dashboard polls this often so a budget save on another screen shows up
// without a manual refresh. The token is the plan version plus the newest budget
// row, which is what the server compares before it will reuse a published snapshot.
export const DASHBOARD_POLL_MS = 3000;

export type DashboardRevision = {
  plan_version?: string | null;
  budget_updated_at?: string | null;
};

export function revisionToken(revision: DashboardRevision | null | undefined): string {
  if (!revision) return '';
  return `${revision.plan_version ?? ''}@${revision.budget_updated_at ?? ''}`;
}

// The first observation only records the token. A later different token means
// the plan or a budget row changed and the view should be loaded again.
export function shouldReloadView(previous: string | null, next: string): boolean {
  return previous !== null && next !== previous;
}
