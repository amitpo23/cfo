/** Team admin actions follow the membership role in the active organization. */

export function canManageTeam(
  platformRole: string | null | undefined,
  membershipRole: string | null | undefined,
): boolean {
  if (platformRole === 'super_admin') return true;
  return membershipRole === 'admin';
}
