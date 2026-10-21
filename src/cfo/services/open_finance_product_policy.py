"""Reviewed product contracts, independent of shared hostnames and OAuth shape.

Sources checked 2026-09-06: docs-financy.open-finance.ai/docs/getting-started,
create-a-payment, authentication and its llms.txt reference index. Missing from
that index means unreviewed for Financy, not proof that the provider cannot offer it.
"""
import re


def product_access_error(*, product, plan, method, path, body, connected_accounts, loans=False):
    if product not in {'open_finance', 'financy', 'unverified'}:
        return 'Provider product is unknown; owner configuration is required'
    if product == 'unverified':
        if method != 'GET' or 'refresh' in path:
            return 'Provider product must be verified before initiating a provider action'
        return None
    if product == 'open_finance':
        return None  # Platform authorization and scopes are still enforced by the provider.
    if plan not in {'starter', 'pro', 'ultra'}:
        return 'Financy API requires a verified paid plan (Starter, Pro or Ultra)'
    reads = (
        r'/providers', r'/bank-branches', r'/connections', r'/connections/[^/]+',
        r'/data/accounts', r'/data/accounts/[^/]+', r'/data/transactions', r'/data/transactions/[^/]+',
        r'/payments', r'/payments/[^/]+', r'/payments/[^/]+/status', r'/merchants', r'/merchants/[^/]+',
    )
    permitted = not loans and (
        (method == 'GET' and any(re.fullmatch(pattern, path) for pattern in reads)) or
        (method == 'POST' and path in {'/payments', '/pay/open-banking-init', '/merchants'}) or
        (method == 'DELETE' and bool(re.fullmatch(r'/(connections|merchants)/[^/]+', path))))
    if not permitted:
        return 'Operation is not reviewed for the Financy product; do not inherit Open Finance platform capabilities'
    if method == 'POST' and path in {'/payments', '/pay/open-banking-init'}:
        information = (body or {}).get('paymentInformation') or body or {}
        if not isinstance(information, dict):
            return 'Payment information must identify a connected account'
        parties = [information.get('creditorAccountNumber'), information.get('debtorAccountNumber')]
        if not any(isinstance(number, str) and number and number in connected_accounts for number in parties):
            return 'Financy payments require a debtor or creditor account with verified active connected-account evidence'
    return None
