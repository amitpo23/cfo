const SLUG = /^[a-z0-9][a-z0-9-]{2,47}$/;

export function dashboardLoginHref(slug: string): string {
  if (!SLUG.test(slug)) return '/?login=1';
  return `/?login=1&next=${encodeURIComponent(`/d/${slug}`)}`;
}

/** A post-login return path is only a dashboard address on this origin. */
export function safeDashboardReturn(next: string | null | undefined): string | null {
  if (!next) return null;
  let value = next.trim();
  if (value.includes('\\') || value.includes('\n') || value.includes('\r')) return null;
  try {
    value = decodeURIComponent(value);
  } catch {
    return null;
  }
  if (!value.startsWith('/') || value.startsWith('//') || value.includes('\\')) return null;
  const path = value.split(/[?#]/, 1)[0].replace(/\/+$/, '');
  const match = /^\/d\/([a-z0-9][a-z0-9-]{2,47})$/.exec(path);
  if (!match || !SLUG.test(match[1])) return null;
  return path;
}

export function safeLoginHref(candidate: string | null | undefined, slug: string): string {
  const fallback = dashboardLoginHref(slug);
  if (!candidate || !candidate.startsWith('/?login=1')) return fallback;
  const next = new URLSearchParams(candidate.slice(2)).get('next');
  if (safeDashboardReturn(next) !== (SLUG.test(slug) ? `/d/${slug}` : null)) return fallback;
  return candidate;
}
