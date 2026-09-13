"""Synthetic browser contract; every API response is intercepted."""
import json
import os
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

base = os.environ.get('REZEF_BROWSER_BASE', 'http://127.0.0.1:5203')
output = Path(os.environ.get('REZEF_BROWSER_OUTPUT', '/private/tmp/rezef-payable-browser'))
output.mkdir(parents=True, exist_ok=True)
data = {'bills': [{'id': 1, 'external_id': 'BILL-1', 'number': 'BILL-1', 'vendor_name': 'Synthetic supplier',
    'vendor_id': 2, 'amount': '1000.00', 'balance': '1000.00', 'currency': 'ILS', 'status': 'received'}],
    'requests': [], 'funding_accounts': [], 'pagination': {'has_more': False}, 'limitations': [],
    'bank_movements': [{'id': 3, 'external_id': 'BANK-3', 'date': '2026-09-06', 'amount': '-400.00',
        'currency': 'ILS', 'provisional': False, 'source_status': 'BOOKED', 'reconciled': False},
        {'id': 4, 'external_id': 'BANK-4', 'date': '2026-09-06', 'amount': '-600.00',
        'currency': 'ILS', 'provisional': True, 'source_status': 'PENDING', 'reconciled': False}]}
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={'width': 1440, 'height': 1100})
    page.add_init_script("localStorage.setItem('auth_token','synthetic');localStorage.setItem('active_org_id','1')")
    writes, errors = [], []
    def route(r):
        url = r.request.url
        if not url.startswith(base + '/'):
            r.abort(); return
        if '/api/' not in url:
            r.continue_(); return
        if r.request.method != 'GET': writes.append(url)
        if url.endswith('/admin/auth/me'):
            response = {'id': 1, 'organization_id': 1, 'email': 'synthetic@example.invalid', 'full_name': 'Synthetic', 'role': 'admin'}
        elif url.endswith('/admin/auth/organizations'): response = [{'id': 1, 'name': 'Synthetic'}]
        elif '/financial/payables/workbench' in url: response = data
        elif url.endswith('/financial/payables/requests'):
            body = r.request.post_data_json
            assert body['bill_id'] == 1 and body['amount'] == '600' and body['idempotency_key']
            response = {'request_id': 5, 'bill_id': 1, 'amount': '600.00', 'currency': 'ILS',
                'approval_status': 'proposed', 'approval_payload': body, 'money_status': 'unknown',
                'settled_amount': '0.00', 'remaining_request_amount': '600.00', 'remaining_balance': '1000.00',
                'settlement_history': [], 'payment_url': None, 'error': None}
            data['requests'] = [response]
        elif url.endswith('/approvals/5/approve'):
            data['requests'][0]['approval_status'] = 'approved'; response = {}
        elif url.endswith('/requests/5/execute'):
            data['requests'][0].update(approval_status='verified', money_status='pending'); response = {}
        elif url.endswith('/requests/5/settle'):
            assert r.request.post_data_json['bank_transaction_id'] == 3
            data['requests'][0].update(settled_amount='400.00', remaining_request_amount='200.00',
                remaining_balance='600.00', money_status='partially_bank_settled',
                settlement_history=[{'bank_transaction_id': 3, 'bank_external_id': 'BANK-3', 'amount': '400.00', 'status': 'active'}])
            data['bills'][0]['balance'] = '600.00'; data['bank_movements'][0]['reconciled'] = True; response = {}
        elif url.endswith('/requests/5/reverse'):
            data['requests'][0]['settlement_history'][0]['status'] = 'reversed'
            data['bills'][0]['balance'] = '1000.00'; response = {}
        else:
            r.fulfill(status=503, json={'detail': 'Synthetic unavailable service'}); return
        r.fulfill(status=200, json=response)
    page.route('**/*', route)
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.goto(base + '/supplier-payments')
    expect(page.get_by_role('heading', name='Supplier payments and bank evidence')).to_be_visible()
    assert not writes
    for label, value in [('Bill', '1'), ('Withholding decision', 'not_required')]: page.get_by_label(label, exact=True).select_option(value)
    for label, value in [('Payment amount', '600'), ('Beneficiary name', 'Synthetic supplier'),
            ('Beneficiary account', '12-345-67890'), ('Beneficiary evidence', 'Reviewed supplier bank confirmation and account identity'),
            ('Withholding evidence', 'Owner reviewed the payer obligation and supplier evidence')]: page.get_by_label(label, exact=True).fill(value)
    page.get_by_role('button', name='Prepare supplier proposal').click()
    page.get_by_role('button', name='Approve exact proposal').click()
    page.get_by_role('button', name='Execute approved request').click()
    expect(page.get_by_text('Money: pending', exact=False)).to_be_visible()
    page.get_by_label('Request', exact=True).select_option('5')
    expect(page.get_by_label('Bank outflow').locator('option[value="4"]')).to_have_attribute('disabled', '')
    page.get_by_label('Bank outflow').select_option('3')
    page.get_by_label('Bank decision evidence').fill('Reviewed exact supplier reference and booked bank evidence')
    page.get_by_role('button', name='Record reviewed settlement').click()
    expect(page.get_by_text('Awaiting bank evidence: 200.00', exact=False)).to_be_visible()
    page.get_by_role('button', name='Reverse local settlement').click()
    expect(page.get_by_text('BANK-3 · 400.00 ILS · reversed')).to_be_visible()
    assert len(writes) == 5
    page.screenshot(path=str(output / '2026-09-06-payable-workbench.png'), full_page=True)
    page.set_viewport_size({'width': 390, 'height': 844})
    page.wait_for_timeout(100)
    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
    assert not errors, errors
    result = {'passed': True, 'synthetic_only': True, 'provider_requests': 0,
        'checks': ['DB-only screen', 'reviewed proposal', 'separate approval and execution', 'pending is not paid',
            'provisional blocked', 'partial bank settlement', 'reversal history', 'mobile width', 'no JS errors']}
    (output / '2026-09-06-payable-workbench-browser.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result)); browser.close()
