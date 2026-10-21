import json,os
from pathlib import Path
from playwright.sync_api import sync_playwright, expect
BASE=os.environ.get('REZEF_BROWSER_BASE', 'http://127.0.0.1:5199')
output=Path(os.environ.get('REZEF_BROWSER_OUTPUT', '/private/tmp/rezef-workbench-browser')); output.mkdir(parents=True, exist_ok=True)
with sync_playwright() as p:
 browser=p.chromium.launch(headless=True);page=browser.new_page(viewport={'width':1440,'height':1100})
 page.add_init_script("localStorage.setItem('auth_token','synthetic');localStorage.setItem('active_org_id','1')")
 writes=[];errors=[]
 data={'invoices':[{'id':1,'external_id':'invoice:1','number':'INV-1','contact_id':10,'currency':'ILS','balance':'1000.00','total':'1000.00','status':'sent'}],
 'receipts':[{'id':2,'external_id':'receipt:2','contact_id':10,'currency':'ILS','amount':'1200.00','unallocated_amount':'1200.00','document_external_id':'2','date':'2026-09-06'}],
 'bank_movements':[{'id':3,'external_id':'bank:3','currency':'ILS','amount':'1200.00','unallocated_amount':'1200.00','date':'2026-09-06','provisional':False,'source_status':'BOOKED'}, {'id':4,'external_id':'bank:4','currency':'ILS','amount':'1000.00','unallocated_amount':'1000.00','date':'2026-09-06','provisional':True,'source_status':'PENDING'}],
 'allocations':[],'requests':[],'event_reviews':[],'pagination':{'has_more':False,'counts':{}}}
 def route(r):
  url=r.request.url
  if not url.startswith(BASE+'/'):r.abort();return
  if '/api/' not in url:r.continue_();return
  if r.request.method!='GET':writes.append({'url':url,'payload':r.request.post_data_json})
  if url.endswith('/admin/auth/me'):response={'id':1,'organization_id':1,'email':'synthetic@example.invalid','full_name':'Synthetic','role':'admin'}
  elif url.endswith('/admin/auth/organizations'):response=[{'id':1,'name':'Synthetic business'}]
  elif '/financial/collection/workbench' in url:response=data
  elif url.endswith('/financial/collection/allocations'):
   body=r.request.post_data_json
   assert body['invoice_id']==1 and body['payment_id']==2 and body['bank_transaction_id']==3
   assert body['amount']=='1000' and body['idempotency_key']
   data['invoices'][0]['balance']='0.00';data['invoices'][0]['status']='paid'
   data['receipts'][0]['unallocated_amount']='200.00';data['bank_movements'][0]['unallocated_amount']='200.00'
   data['allocations']=[{'allocation_id':5,'invoice_id':1,'payment_id':2,'bank_transaction_id':3,'amount':'1000.00','currency':'ILS','status':'active','remaining_balance':'0.00','evidence':{'reason':body['reason']}}];response=data['allocations'][0]
  elif url.endswith('/financial/collection/allocations/5/reverse'):
   data['allocations'][0]['status']='reversed';data['allocations'][0]['remaining_balance']='1000.00';data['invoices'][0]['balance']='1000.00';response=data['allocations'][0]
   data['receipts'][0]['unallocated_amount']='1200.00';data['bank_movements'][0]['unallocated_amount']='1200.00'
   data['invoices'][0]['status']='sent'
  else:r.fulfill(status=503,json={'detail':'Synthetic unavailable service'});return
  r.fulfill(status=200,json=response)
 page.route('**/*',route);page.on('pageerror',lambda e:errors.append(str(e)))
 page.goto(BASE+'/collections');page.wait_for_load_state('networkidle');assert not writes
 page.get_by_label('Invoice',exact=True).select_option('1')
 page.get_by_label('Allocation amount').fill('1000')
 page.get_by_label('SUMIT receipt').select_option('2')
 expect(page.get_by_label('Bank movement').locator('option[value="4"]')).to_have_attribute('disabled', '')
 page.get_by_label('Bank movement').select_option('3')
 page.get_by_label('Reviewed identity evidence').fill('Reviewed payer transfer reference and the SUMIT receipt identity')
 page.get_by_role('button',name='Record reviewed allocation',exact=True).click()
 expect(page.get_by_role('status')).to_contain_text('Allocation recorded locally')
 expect(page.get_by_text('Allocation 5',exact=False)).to_be_visible()
 assert '200.00' in page.get_by_label('SUMIT receipt').inner_text()
 page.get_by_role('button',name='Reverse local allocation',exact=True).click()
 expect(page.get_by_role('status')).to_contain_text('Local allocation reversed')
 assert '1200.00' in page.get_by_label('SUMIT receipt').inner_text()
 assert len(writes)==2
 page.screenshot(path=str(output/'2026-09-06-collection-workbench.png'),full_page=True)
 page.set_viewport_size({'width':390,'height':844});page.wait_for_timeout(100)
 assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'), 'Mobile horizontal overflow'
 assert not errors,errors
 result={'passed':True,'synthetic_only':True,'provider_requests':0,'checks':['no screen-open writes','explicit identity selection','provisional disabled','allocation and unallocated excess','reversal history','mobile width','no JavaScript errors']}
 (output/'2026-09-06-collection-workbench-browser.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result));browser.close()
