"""Hebrew source-intake browser journey with all API responses synthetic."""
import base64
import json
import os
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

base = os.environ.get('REZEF_BROWSER_BASE', 'http://127.0.0.1:5203')
output = Path(os.environ.get('REZEF_BROWSER_OUTPUT', '/private/tmp/rezef-document-browser'))
output.mkdir(parents=True, exist_ok=True)
documents, writes, errors = [], [], []
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={'width': 1280, 'height': 1000})
    page.add_init_script("localStorage.setItem('auth_token','synthetic');localStorage.setItem('active_org_id','1')")
    def route(r):
        url, method = r.request.url, r.request.method
        if not url.startswith(base + '/'):
            r.abort(); return
        if '/api/' not in url:
            r.continue_(); return
        if method != 'GET': writes.append(url)
        if url.endswith('/admin/auth/me'):
            response = {'id': 1, 'organization_id': 1, 'email': 'synthetic@example.invalid', 'full_name': 'Synthetic', 'role': 'admin'}
        elif url.endswith('/admin/auth/organizations'): response = [{'id': 1, 'name': 'Synthetic'}]
        elif '/expenses/intake' in url:
            if url.endswith('/process'):
                payload = r.request.post_data_json
                row = next(d for d in documents if d['id'] == int(url.split('/')[-2]))
                assert payload['version'] == row['version']
                row.update(status='needs_review', attempts=1, version=3,
                    result={'message': 'חסר סכום מע״מ; נדרשת בדיקת מקור', 'extracted': {'amount_total': 118}})
                response = row['result']
            elif url.endswith('/source'):
                r.fulfill(status=200, content_type='application/pdf', body=b'%PDF-1.4 synthetic'); return
            elif method == 'POST':
                payload = r.request.post_data_json
                assert base64.b64decode(payload['content_base64']).startswith(b'%PDF')
                existing = next((d for d in documents if d['filename'] == payload['filename']), None)
                if existing:
                    response = {'document_id': existing['id'], 'status': 'duplicate'}
                else:
                    row = {'id': len(documents)+1, 'filename': payload['filename'], 'media_type': 'application/pdf',
                        'status': 'queued', 'version': 1, 'attempts': 0, 'expense_id': None, 'amount': None,
                        'updated_at': '2026-09-07T10:00:00', 'sources': [{'channel': 'upload', 'filename': payload['filename']}], 'result': None}
                    documents.append(row); response = {'document_id': row['id'], 'status': 'queued'}
            else: response = {'documents': documents, 'total': len(documents), 'sync_triggered': False}
        elif url.endswith('/expenses'): response = {'status': 'success', 'data': []}
        else:
            r.fulfill(status=503, json={'detail': 'Synthetic unavailable service'}); return
        r.fulfill(status=200, json=response)
    page.route('**/*', route)
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.goto(base + '/expenses')
    page.wait_for_load_state('networkidle')
    panel = page.get_by_role('region', name='תור מסמכי מקור')
    expect(panel.get_by_role('heading', name='מסמכי מקור ובדיקת ראיות')).to_be_visible()
    assert not writes
    page.screenshot(path=str(output / 'before.png'), full_page=True)
    files = [{'name': f'{n}.pdf', 'mimeType': 'application/pdf', 'buffer': b'%PDF-1.4 synthetic'} for n in ('one', 'two')]
    panel.get_by_label('העלאת מסמכים', exact=False).set_input_files(files)
    expect(panel.get_by_role('button', name='two.pdf', exact=False)).to_be_visible()
    panel.get_by_label('העלאת מסמכים', exact=False).set_input_files(files[:1])
    expect(panel.get_by_role('status').filter(has_text='כבר נקלט')).to_be_visible()
    panel.get_by_role('button', name='חילוץ נתונים לפי מכסת הארגון').click()
    expect(panel.locator('article').get_by_text('חסר סכום מע״מ; נדרשת בדיקת מקור')).to_be_visible()
    page.reload(); page.wait_for_load_state('networkidle')
    panel.get_by_role('button', name='one.pdf', exact=False).click()
    expect(panel.locator('article').get_by_text('חסר סכום מע״מ; נדרשת בדיקת מקור')).to_be_visible()
    page.set_viewport_size({'width': 390, 'height': 844})
    page.wait_for_function("document.querySelector('#main-navigation').getBoundingClientRect().right <= 1")
    expect(panel).to_have_attribute('dir', 'rtl')
    assert panel.evaluate('(el) => el.scrollWidth <= el.clientWidth + 1')
    panel.get_by_role('button', name='two.pdf', exact=False).click()
    expect(panel.get_by_role('heading', name='בדיקת two.pdf')).to_be_visible()
    page.screenshot(path=str(output / 'mobile.png'), full_page=True)
    assert len(documents) == 2 and len(writes) == 4 and not errors
    (output / 'evidence.json').write_text(json.dumps({'synthetic': True, 'external_requests_blocked': True,
        'journey': 'multiple uploads, replay, explicit extraction, missing evidence, reload, Hebrew RTL mobile',
        'documents': 2, 'writes': len(writes), 'javascript_errors': errors, 'passed': True}, indent=2))
    browser.close()
