"""Saved reports UI: synthetic API only, Hebrew RTL, reload and permission failure."""
import json
import os
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

base = os.environ.get('REZEF_BROWSER_BASE', 'http://127.0.0.1:5203')
output = Path(os.environ.get('REZEF_BROWSER_OUTPUT', '/private/tmp/rezef-reports-browser'))
output.mkdir(parents=True, exist_ok=True)
templates = [{'template_id': 'DEFAULT-PL', 'name': 'רווח והפסד', 'report_type': 'profit_loss'}]
schedules, history, errors, writes = [], [], [], []
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
        elif '/financial/reports/' in url:
            body = r.request.post_data_json if method == 'POST' else {}
            if url.endswith('/templates'):
                if method == 'POST': templates.append(dict(body, template_id='TPL-synthetic'))
                response = {'data': templates}
            elif url.endswith('/schedules'):
                if method == 'POST':
                    assert body['delivery_method'] == 'download'
                    schedules.append({'schedule_id': 'SCH-synthetic', 'name': body['name'], 'is_active': True, 'next_run': '2026-10-01T06:00:00'})
                response = {'data': schedules}
            elif url.endswith('/generate'):
                assert body['template_id'] == 'TPL-synthetic' and body['parameters']['month'] == 9
                history.append({'execution_id': 'RUN-synthetic', 'status': 'completed', 'started_at': '2026-09-07T10:00:00',
                    'error_message': None, 'result': {'report_id': 'RPT-synthetic', 'format': 'json', 'download_url': '/api/financial/reports/files/RPT-synthetic'}})
                response = {'data': {}}
            elif url.endswith('/history'): response = {'data': history}
            elif '/files/' in url:
                r.fulfill(status=200, content_type='application/json', body='{"synthetic":true}'); return
            elif url.endswith('/pause'):
                r.fulfill(status=403, json={'detail': 'ההרשאה בוטלה; התזמון לא שונה'}); return
            else:
                r.fulfill(status=503, json={'detail': 'Synthetic unavailable service'}); return
        else:
            r.fulfill(status=503, json={'detail': 'Synthetic unavailable service'}); return
        r.fulfill(status=200, json=response)
    page.route('**/*', route)
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.goto(base + '/reports'); page.wait_for_load_state('networkidle')
    panel = page.get_by_role('region', name='דוחות שמורים', exact=True)
    expect(panel.get_by_role('heading', name='דוחות שמורים ותזמונים')).to_be_visible()
    assert not writes
    page.screenshot(path=str(output / 'before.png'), full_page=True)
    panel.get_by_label('שם תבנית חדשה').fill('דוח סינתטי')
    panel.get_by_role('button', name='שמירת תבנית', exact=True).click()
    expect(panel.get_by_role('option', name='דוח סינתטי')).to_have_count(1)
    page.reload(); page.wait_for_load_state('networkidle')
    panel.get_by_label('תבנית דוח', exact=True).select_option('TPL-synthetic')
    panel.get_by_label('תקופת דוח').fill('2026-09')
    panel.get_by_role('button', name='הפקת דוח שמור').click()
    expect(panel.get_by_text('קובץ נשמר', exact=False)).to_be_visible()
    panel.get_by_label('שם תבנית חדשה').fill('תזמון סינתטי')
    panel.get_by_role('button', name='שמירת תזמון חודשי').click()
    expect(panel.get_by_text('תזמון סינתטי', exact=False)).to_be_visible()
    panel.get_by_role('button', name='השהיה', exact=True).click()
    expect(panel.get_by_role('status')).to_contain_text('ההרשאה בוטלה')
    with page.expect_download() as download:
        panel.get_by_role('button', name='הורדת הקובץ השמור').click()
    assert download.value.suggested_filename == 'RPT-synthetic.json'
    page.set_viewport_size({'width': 390, 'height': 844})
    page.wait_for_function("document.querySelector('#main-navigation').getBoundingClientRect().right <= 1")
    panel.get_by_label('שם תבנית חדשה').fill('בדיקת נייד')
    expect(panel).to_have_attribute('dir', 'rtl')
    assert panel.evaluate('(el) => el.scrollWidth <= el.clientWidth + 1')
    page.screenshot(path=str(output / 'mobile.png'), full_page=True)
    assert not errors and len(writes) == 4
    (output / 'evidence.json').write_text(json.dumps({'synthetic': True, 'external_requests_blocked': True,
        'journey': 'save template, reload, generate, save schedule, revoked permission, download, RTL mobile',
        'writes': len(writes), 'javascript_errors': errors, 'passed': True}, indent=2))
    browser.close()
