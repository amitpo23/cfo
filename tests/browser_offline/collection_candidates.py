"""Synthetic bank candidate UI check; external traffic and all real APIs blocked."""
import json
import os
import tempfile
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

BASE='http://127.0.0.1:5199'
output=Path(os.environ.get('REZEF_BROWSER_OUTPUT', str(Path(tempfile.gettempdir())/'rezef-collection-browser')))
output.mkdir(parents=True, exist_ok=True)
with sync_playwright() as p:
    browser=p.chromium.launch(headless=True)
    page=browser.new_page(viewport={'width':1440,'height':1000})
    page.add_init_script("localStorage.setItem('auth_token','synthetic');localStorage.setItem('active_org_id','1')")
    writes=[];errors=[]
    def route(r):
        url=r.request.url
        if not url.startswith(BASE+'/'):r.abort();return
        if '/api/' not in url:r.continue_();return
        if r.request.method!='GET':writes.append(url)
        if url.endswith('/admin/auth/me'):
            data={'id':1,'organization_id':1,'email':'synthetic@example.invalid','full_name':'Synthetic','role':'admin'}
        elif url.endswith('/admin/auth/organizations'):data=[{'id':1,'name':'Synthetic business'}]
        elif '/open-finance/insights' in url:data={'items':[]}
        elif url.endswith('/open-finance/reconcile'):
            data={'matched_count':0,'candidate_count':2,'txn_count':1,'matches':[],
                  'unmatched_txns':[1],'unmatched_txn_details':[{'id':1,'is_provisional':True}]}
        else:r.fulfill(status=503,json={'detail':'Synthetic unavailable service'});return
        r.fulfill(status=200,json=data)
    page.route('**/*',route)
    page.on('pageerror',lambda e:errors.append(str(e)))
    page.goto(BASE+'/bank-insights');page.wait_for_load_state('networkidle')
    assert not writes,'Opening screen triggered a mutation'
    page.get_by_role('button',name='התאמת בנקים',exact=True).click()
    expect(page.get_by_text('מועמדויות לבדיקה',exact=True)).to_be_visible()
    expect(page.get_by_text('הותאמו מקומית',exact=True)).to_be_visible()
    expect(page.get_by_text('סכום ותאריך לבדם אינם התאמה.',exact=False)).to_be_visible()
    assert len(writes)==1 and writes[0].endswith('/open-finance/reconcile')
    page.screenshot(path=str(output/'candidates.png'),full_page=True)
    assert not errors,errors
    result={'passed':True,'synthetic_only':True,'checks':['screen open does not sync','candidate/confirmed distinction','provisional disclosure','no JavaScript errors'],'provider_requests':0}
    (output/'results.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result))
    browser.close()
