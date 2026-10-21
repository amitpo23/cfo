"""Offline browser journeys. Every API response is synthetic; external traffic is refused."""
import json
import os
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

BASE = 'http://127.0.0.1:5199'
OUTPUT = Path(os.environ.get('REZEF_BROWSER_OUTPUT', '/private/tmp/rezef-stabilization-browser'))
OUTPUT.mkdir(parents=True, exist_ok=True)

with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    summary = []
    for role in ('super_admin', 'admin'):
        context = browser.new_context(viewport={'width':1440,'height':1000})
        context.add_init_script("""if (!sessionStorage.getItem('initialized')) {
            localStorage.setItem('auth_token','synthetic-browser-test');
            localStorage.setItem('active_org_id','5');
            sessionStorage.setItem('initialized','1');
        }""")
        requests, errors = [], []
        def route(handler):
            url = handler.request.url
            if not url.startswith(BASE + '/'):
                handler.abort(); return
            if '/api/' not in url:
                handler.continue_(); return
            requests.append({'url':url, 'organization':handler.request.headers.get('x-active-org-id')})
            if url.endswith('/admin/auth/me'):
                body={'id':1,'email':'synthetic@example.com','full_name':'Synthetic Reviewer','role':role,'organization_id':1}
            elif url.endswith('/admin/auth/organizations'):
                body=[{'id':1,'name':'Synthetic Home'},{'id':5,'name':'Synthetic Client'}]
            else:
                handler.fulfill(status=503, json={'detail':'Synthetic service failure'}); return
            handler.fulfill(status=200, json=body)
        context.route('**/*', route)
        page = context.new_page()
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(BASE+'/settings')
        page.wait_for_load_state('networkidle')
        expect(page.get_by_title('Switch organization')).to_be_visible()
        page.get_by_title('Switch organization').click()
        page.get_by_role('button', name='Synthetic Home', exact=False).click()
        page.wait_for_load_state('networkidle')
        assert page.evaluate("localStorage.getItem('active_org_id')") == '1'
        assert [r for r in requests if r['url'].endswith('/admin/auth/me')][-1]['organization'] == '1'
        page.get_by_title('Switch organization').click()
        page.get_by_role('button', name='Synthetic Client', exact=False).click()
        page.wait_for_load_state('networkidle')
        assert page.evaluate("localStorage.getItem('active_org_id')") == '5'
        page.set_viewport_size({'width':390,'height':844})
        nav = page.get_by_role('button', name='Toggle navigation')
        expect(nav).to_be_visible()
        assert page.locator('main').bounding_box()['width'] >= 380
        nav.click()
        expect(nav).to_have_attribute('aria-expanded','true')
        page.locator('#main-navigation').get_by_role('link',name='Settings',exact=False).click()
        expect(nav).to_have_attribute('aria-expanded','false')
        page.wait_for_function("document.getElementById('main-navigation').getBoundingClientRect().right <= 1")
        page.screenshot(path=str(OUTPUT/f'{role}-mobile.png'), full_page=True)
        assert page.evaluate('document.body.scrollWidth <= innerWidth')
        page.set_viewport_size({'width':1440,'height':1000})
        page.get_by_role('button',name='Synthetic Reviewer',exact=False).click()
        page.get_by_role('button',name='Logout',exact=True).click()
        page.wait_for_load_state('networkidle')
        assert page.evaluate("localStorage.getItem('auth_token')") is None
        assert page.evaluate("localStorage.getItem('active_org_id')") is None
        assert not errors, errors
        summary.append({'role':role,'checks':['home selection header','second organization','mobile content width','mobile navigation','logout clears scope','no JavaScript errors'], 'passed':True})
        context.close()
    browser.close()
    (OUTPUT/'results.json').write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))
