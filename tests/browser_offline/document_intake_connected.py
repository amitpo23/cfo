"""Real React → FastAPI → SQLite journey, with synthetic inputs and external sockets blocked.

Playwright forwards API requests to the real ASGI TestClient; no API responses or
business services are mocked. Only the SUMIT provider is synthetic. Restarting the application lifespan/connection pool
uses the same temporary database. The separate fixture-browser tests cover failures.
"""
import asyncio
import json
import os
import sys
import tempfile
from email.message import EmailMessage
from io import BytesIO
from pathlib import Path
from urllib.parse import urlsplit
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'scripts'), str(ROOT / 'src')]
from offline_guard import isolate_offline_audit
isolate_offline_audit()
work = Path(tempfile.mkdtemp(prefix='rezef-connected-document-'))
os.environ['DATABASE_URL'] = f'sqlite:///{work / "synthetic.db"}'
os.environ['REGISTRATION_SECRET'] = ''
os.environ['CHAT_RECEIPT_INTAKE_ENABLED'] = 'false'
from fastapi.testclient import TestClient
from cfo.api import app
from cfo.database import SessionLocal, engine
from cfo.models import DocumentIntake, Expense, Note, ReportRecord, SyncCheckpoint, User, UserRole, OrganizationSigningAuthority, IrreversibleActionRequest, Organization
from cfo.auth import create_access_token, get_password_hash
from cfo.services import membership_service
from cfo.services.expense_intake_email import EmailExpenseIntakeService
from playwright.sync_api import sync_playwright, expect
from reportlab.pdfgen import canvas
from PIL import Image

base = os.environ.get('REZEF_BROWSER_BASE', 'http://127.0.0.1:5203')
output = Path('/private/tmp/rezef-connected-document-browser'); output.mkdir(parents=True, exist_ok=True)
client = TestClient(app, raise_server_exceptions=False); client.__enter__()
registration = client.post('/api/admin/auth/register', json={'email': 'synthetic@example.com',
    'password': 'synthetic-test-password', 'full_name': 'בדיקה סינתטית'})
assert registration.status_code == 201, registration.text
identity = registration.json(); org_id = identity['user']['organization_id']
with SessionLocal() as db:
    db.get(Organization, org_id).api_credentials = {'company_id': '123', 'api_key': 'synthetic-only'}
    owner = db.query(User).filter_by(organization_id=org_id).one()
    signer = User(organization_id=org_id, email='synthetic-signer@example.com',
        password_hash=get_password_hash('synthetic-test-password'), full_name='מורשה חתימה סינתטי', role=UserRole.ADMIN, is_active=True)
    db.add(signer); db.flush()
    membership_service.grant(db, organization_id=org_id, user_id=signer.id, role=UserRole.ADMIN,
        granted_by_user_id=owner.id, status=membership_service.ACTIVE)
    db.add(OrganizationSigningAuthority(organization_id=org_id, user_id=signer.id,
        authority_type='authorized_signer', action_types=['sumit_writeback'], is_active=True, granted_by_user_id=owner.id))
    db.commit(); signer_token = create_access_token({'sub': signer.id})
provider_calls = []
class FakeSumit:
    company_id = '123'
    async def add_expense(self, request):
        assert request.is_draft is True and request.invoice_number == 'SYN-118'
        provider_calls.append({'invoice_number': request.invoice_number, 'draft': request.is_draft})
        return {'DocumentID': 991, 'expense_id': '991'}
def synthetic_connector(db, organization_id, **kwargs):
    assert organization_id == org_id and kwargs['preferred_source'] == 'sumit'
    return FakeSumit(), None, 'sumit'

def pdf(*texts):
    b = BytesIO(); c = canvas.Canvas(b)
    for text in texts: c.drawString(50, 700, text); c.showPage()
    c.save(); return b.getvalue()
packet, single = pdf('FIRST DOCUMENT', 'SECOND DOCUMENT'), pdf('SYNTHETIC INVOICE 118 ILS')
b = BytesIO(); Image.new('RGB', (30, 30), color='white').save(b, format='PNG')
mail = EmailMessage(); mail['From'] = 'source@example.invalid'; mail['Message-ID'] = '<synthetic-browser@example.invalid>'
mail.set_content('Synthetic source evidence')
mail.add_attachment(packet, maintype='application', subtype='pdf', filename='packet.pdf')
mail.add_attachment(single, maintype='application', subtype='pdf', filename='single.pdf')
mail.add_attachment(b.getvalue(), maintype='image', subtype='png', filename='photo.png')
with SessionLocal() as db:
    received = asyncio.run(EmailExpenseIntakeService(db, org_id, 'synthetic.invalid', 993, 'fake', 'fake')._process_email(mail.as_bytes()))
    assert received['created'] == 3 and db.query(Expense).count() == 0
    initial_checkpoints = db.query(SyncCheckpoint).count()

errors, writes, requests = [], [], []
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={'width': 1280, 'height': 1000})
    page.add_init_script(f"localStorage.setItem('auth_token', {json.dumps(identity['access_token'])});localStorage.setItem('active_org_id', '{org_id}')")
    def route(r):
        url = r.request.url
        if not url.startswith(base + '/'):
            r.abort(); return
        if '/api/' not in url:
            r.continue_(); return
        parsed = urlsplit(url); path = parsed.path + ('?' + parsed.query if parsed.query else '')
        headers = {key: value for key, value in r.request.headers.items() if key.lower() not in {'host', 'content-length'}}
        result = client.request(r.request.method, path, headers=headers, content=r.request.post_data)
        requests.append({'method': r.request.method, 'path': parsed.path, 'status': result.status_code})
        if r.request.method != 'GET': writes.append(parsed.path)
        r.fulfill(status=result.status_code, headers={key: value for key, value in result.headers.items()
            if key.lower() not in {'content-length', 'content-encoding', 'transfer-encoding'}}, body=result.content)
    page.route('**/*', route)
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.goto(base + '/expenses'); page.wait_for_load_state('networkidle')
    panel = page.get_by_role('region', name='תור מסמכי מקור')
    expect(panel.get_by_role('button', name='photo.png', exact=False)).to_be_visible()
    assert writes == []
    panel.get_by_label('העלאת מסמכים', exact=False).set_input_files([
        {'name': 'packet.pdf', 'mimeType': 'application/pdf', 'buffer': packet}])
    expect(panel.get_by_role('status').filter(has_text='כבר נקלט')).to_be_visible()
    panel.get_by_role('button', name='single.pdf', exact=False).click()
    panel.get_by_role('button', name='תיקון נתונים מהמקור').click()
    for label, value in {'ספק': 'ספק סינתטי', 'מספר עוסק': '520022732', 'תאריך המסמך': '2026-09-07',
            'מספר מסמך': 'SYN-118', 'סכום כולל': '118', 'לפני מע״מ': '100', 'מע״מ במסמך': '18', 'מטבע': 'ILS'}.items():
        panel.get_by_label('תיקון ' + label, exact=True).fill(value)
    panel.get_by_label('תיקון סוג מסמך', exact=True).select_option('tax_invoice')
    panel.get_by_label('סיבת התיקון והראיה שנבדקה').fill('בדיקה ידנית של נתוני המקור הסינתטי לפני יצירת טיוטת הוצאה')
    panel.get_by_role('button', name='שמירת בדיקת המקור').click()
    expect(panel.get_by_role('heading', name='בדיקת מקור מתועדת')).to_be_visible()
    # Correct classification and review the exact proposal in the actual UI.
    expense_row = page.locator('tr[id^="expense-"]')
    category = expense_row.locator('input:not([type="number"])')
    category.fill('office'); category.press('Tab')
    page.wait_for_load_state('networkidle')
    expense_row.get_by_role('button', name='מקור, הצעה וסטטוס תיוק').click()
    filing = page.get_by_role('region', name='אישור תיוק מקור')
    expect(filing.get_by_text('SYN-118', exact=True)).to_be_visible()
    filing.get_by_role('button', name='הצגת המקור להצעה').click()
    expect(filing.get_by_alt_text('תצוגת עמוד מקור')).to_be_visible()
    expect(filing.get_by_text('עמוד 1 מתוך 1', exact=False)).to_be_visible()
    page.wait_for_load_state('networkidle')
    assert filing.get_by_alt_text('תצוגת עמוד מקור').evaluate('(image) => image.naturalWidth > 0')
    filing.get_by_alt_text('תצוגת עמוד מקור').screenshot(path=str(output / 'source-preview.png'))
    filing.get_by_label('סיבת הצעת התיוק').fill('המקור והסיווג נבדקו — בקשת טיוטה סינתטית בלבד לצורך בדיקה')
    filing.get_by_role('button', name='שמירת הצעה לאישור תיוק').click()
    expect(filing.get_by_text('ממתין לאישור מורשה חתימה', exact=True)).to_be_visible()
    page.evaluate('(token) => localStorage.setItem("auth_token", token)', signer_token)
    filing.get_by_role('button', name='אישור ההצעה המדויקת').click()
    expect(filing.get_by_text('אושר לביצוע', exact=True)).to_be_visible()
    filing.get_by_label('סיבת ביטול האישור לפני ביצוע').fill('ביטול מקומי של אישור הבדיקה לפני כל בקשת ספק, תוך שימור ההיסטוריה')
    filing.get_by_role('button', name='ביטול האישור בידי מורשה חתימה').click()
    expect(filing.get_by_text('ההצעה נדחתה', exact=True)).to_be_visible()
    page.evaluate('(token) => localStorage.setItem("auth_token", token)', identity['access_token'])
    filing.get_by_role('button', name='שמירת הצעה לאישור תיוק').click()
    expect(filing.get_by_text('ממתין לאישור מורשה חתימה', exact=True)).to_be_visible()
    page.evaluate('(token) => localStorage.setItem("auth_token", token)', signer_token)
    filing.get_by_role('button', name='אישור ההצעה המדויקת').click()
    expect(filing.get_by_text('אושר לביצוע', exact=True)).to_be_visible()
    page.evaluate('(token) => localStorage.setItem("auth_token", token)', identity['access_token'])
    with patch('cfo.services.sync_engine.get_connector_for_org', synthetic_connector):
        filing.get_by_role('button', name='ביצוע בקשת הטיוטה המאושרת').click()
        expect(filing.get_by_text('הספק החזיר מזהה — נדרש אימות מסמך וספרים', exact=True)).to_be_visible()
    expect(filing.get_by_role('button', name='ביצוע בקשת הטיוטה המאושרת')).to_have_count(0)
    page.screenshot(path=str(output / 'filing.png'), full_page=True)
    filing.get_by_role('button', name='סגירת התצוגה').click()
    panel.get_by_text('ארגון עמודי PDF — פיצול או מיזוג', exact=True).click()
    panel.get_by_role('checkbox', name='packet.pdf', exact=True).check()
    panel.get_by_label('קבוצות עמודים לפיצול', exact=False).fill('1;2')
    panel.get_by_label('סיבת הפיצול או המיזוג').fill('נבדקו גבולות העמודים של שני מסמכים סינתטיים נפרדים')
    panel.get_by_role('button', name='אישור ושמירת חלוקת העמודים').click()
    expect(panel.get_by_role('button', name='packet — חלק 1.pdf', exact=False)).to_be_visible()
    # Restart the actual application lifespan and dispose its pooled DB connections.
    client.__exit__(None, None, None); engine.dispose()
    client = TestClient(app, raise_server_exceptions=False); client.__enter__()
    page.reload(); page.wait_for_load_state('networkidle')
    panel.get_by_role('button', name='packet — חלק 1.pdf', exact=False).click()
    expect(panel.get_by_role('heading', name='מקור העמודים')).to_be_visible()
    panel.get_by_role('button', name='עיון במקור — עמודים 1', exact=True).click()
    expect(panel.get_by_role('button', name='תיקון נתונים מהמקור')).to_have_count(0)
    panel.get_by_role('button', name='הצגת המקור', exact=True).click()
    expect(panel.get_by_text('עמוד 1 מתוך 2', exact=False)).to_be_visible()
    panel.get_by_role('button', name='עמוד הבא', exact=True).click()
    expect(panel.get_by_text('עמוד 2 מתוך 2', exact=False)).to_be_visible()
    page.goto(base + '/reports'); page.wait_for_load_state('networkidle')
    reports = page.get_by_role('region', name='דוחות שמורים', exact=True)
    reports.get_by_label('שם תבנית חדשה').fill('דוח בדיקה מחובר')
    reports.get_by_role('button', name='שמירת תבנית', exact=True).click()
    expect(reports.get_by_role('option', name='דוח בדיקה מחובר')).to_have_count(1)
    reports.get_by_label('תבנית דוח', exact=True).select_option(label='דוח בדיקה מחובר')
    reports.get_by_label('תקופת דוח').fill('2026-09')
    reports.get_by_role('button', name='הפקת דוח שמור').click()
    expect(reports.get_by_text('קובץ נשמר', exact=False)).to_be_visible()
    with page.expect_download() as download:
        reports.get_by_role('button', name='הורדת הקובץ השמור').click()
    download.value.save_as(str(output / 'synthetic-report.json'))
    page.reload(); page.wait_for_load_state('networkidle')
    expect(reports.get_by_role('button', name='הורדת הקובץ השמור')).to_be_visible()
    page.screenshot(path=str(output / 'reports.png'), full_page=True)
    page.goto(base + '/expenses'); page.wait_for_load_state('networkidle')
    panel.get_by_role('button', name='packet — חלק 1.pdf', exact=False).click()
    page.set_viewport_size({'width': 390, 'height': 844})
    page.wait_for_function("document.querySelector('#main-navigation').getBoundingClientRect().right <= 1")
    panel.get_by_role('heading', name='מקור העמודים').scroll_into_view_if_needed()
    page.screenshot(path=str(output / 'mobile-lineage.png'), full_page=True)
    assert not errors, errors
    with SessionLocal() as db:
        assert db.query(DocumentIntake).filter_by(organization_id=org_id).count() == 5
        expense = db.query(Expense).filter_by(organization_id=org_id).one()
        assert expense.status == 'submitted' and expense.total == 118 and expense.sumit_expense_id == '991'
        actions = db.query(IrreversibleActionRequest).filter_by(organization_id=org_id, action_type='sumit_writeback').order_by(IrreversibleActionRequest.id).all()
        assert len(actions) == 2 and actions[0].status == 'rejected'
        action = actions[1]
        assert action.status == 'executed' and action.execution_result['official_books_verified'] is False
        assert db.query(Note).filter_by(organization_id=org_id, entity_type='document_intake').count() == 1
        assert db.query(ReportRecord).filter_by(organization_id=org_id, kind='file').count() == 1
        assert db.query(SyncCheckpoint).count() == initial_checkpoints
    assert len(writes) == 12, writes
    assert len(provider_calls) == 1
    result = {'passed': True, 'synthetic_only': True, 'api_responses_mocked': False, 'external_network_blocked': True,
        'journey': 'three email attachments, cross-channel duplicate, source correction, classification, distinct signer approval, pre-execution withdrawal and replacement approval, fake SUMIT draft acknowledgement, PDF split and lineage, app lifespan restart, saved report and download, RTL mobile',
        'provider_calls': provider_calls, 'provider_is_fake': True,
        'api_requests': requests, 'writes': writes, 'javascript_errors': errors, 'official_books_verified': False,
        'payment_or_period_close_executed': False}
    (output / 'evidence.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    browser.close()
client.__exit__(None, None, None)
print(json.dumps({'passed': True, 'api_responses_mocked': False, 'writes': len(writes)}))
