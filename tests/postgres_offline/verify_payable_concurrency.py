"""Synthetic loopback supplier concurrency evidence. No provider client is used."""
import asyncio,json,sys,uuid
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from datetime import date
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[2] / 'src'))
from environment import test_engine, evidence_path
import sqlalchemy as sa
from sqlalchemy.orm import Session
from cfo.models import Organization,User,UserRole,OrganizationMembership,OrganizationSigningAuthority,Contact,ContactType,Bill,BillStatus,BankTransaction,Payment
from cfo.services.payable_settlement import PayableSettlementService
engine=test_engine()
class Fake:
 async def create_payment(self,body): return {'id':'synthetic-supplier-request','payUrl':'https://synthetic.invalid/pay'}
 async def get_payment(self,reference): return {'id':reference,'paymentStatus':'PENDING'}
 async def close(self): pass
with Session(engine) as db:
 org=Organization(name='SYNTHETIC SUPPLIER CONCURRENCY',settings={'synthetic':True});db.add(org);db.flush()
 user=User(organization_id=org.id,email=f'synthetic-{uuid.uuid4()}@example.invalid',password_hash='not-a-login',full_name='Synthetic reviewer',role=UserRole.ADMIN,is_active=True);db.add(user);db.flush()
 db.add(OrganizationMembership(organization_id=org.id,user_id=user.id,role=UserRole.ADMIN,status='active'))
 db.add(OrganizationSigningAuthority(organization_id=org.id,user_id=user.id,authority_type='owner',action_types=['*'],is_active=True,granted_by_user_id=user.id))
 vendor=Contact(organization_id=org.id,source='sumit',external_id='synthetic-vendor',name='Synthetic vendor',contact_type=ContactType.VENDOR,bank_code='12',bank_branch='345',bank_account_number='67890');db.add(vendor);db.flush()
 bill=Bill(organization_id=org.id,source='sumit',external_id='synthetic-bill',vendor_id=vendor.id,total=1000,paid_amount=0,balance=1000,currency='ILS',status=BillStatus.RECEIVED,issue_date=date(2026,9,6));db.add(bill);db.flush()
 banks=[BankTransaction(organization_id=org.id,source='open_finance',external_id=f'synthetic-outflow-{i}',amount=-600,currency='ILS',transaction_date=date(2026,9,6),is_provisional=False,raw_data={'status':'BOOKED'}) for i in (1,2)]
 db.add_all(banks);db.commit()
 service=PayableSettlementService(db,org.id)
 request=service.propose(bill_id=bill.id,amount='1000',proposed_by=user,idempotency_key='synthetic-concurrency',creditor={'name':vendor.name,'account_number':'12-345-67890','account_type':'bban'},beneficiary_evidence='Synthetic reviewed bank confirmation and beneficiary identity',withholding_decision='not_required',withholding_evidence='Synthetic payer obligation review for local test only')
 service.actions.approve(request.id,approved_by=user)
 with patch('cfo.api.routes.open_finance.get_open_finance_client',lambda *args:Fake()): asyncio.run(service.execute(request.id))
 org_id,user_id,bill_id,request_id,bank_ids=org.id,user.id,bill.id,request.id,[b.id for b in banks]
barrier=Barrier(2)
def settle(bank_id):
 with Session(engine) as db:
  actor=db.get(User,user_id);barrier.wait(timeout=10)
  try:
   r=PayableSettlementService(db,org_id).settle(request_id,bank_transaction_id=bank_id,decided_by=actor,reason='Synthetic reviewed supplier reference and booked bank identity')
   return {'status':'settled','payment_id':r['payment_id'],'bank_id':bank_id}
  except ValueError as exc:
   db.rollback();return {'status':'blocked','reason':str(exc)}
with ThreadPoolExecutor(max_workers=2) as pool:
 futures=[pool.submit(settle,i) for i in bank_ids];results=[f.result(timeout=20) for f in futures]
assert sorted(r['status'] for r in results)==['blocked','settled'],results
accepted=next(r for r in results if r['status']=='settled')
barrier=Barrier(2)
with ThreadPoolExecutor(max_workers=2) as pool:
 futures=[pool.submit(settle,accepted['bank_id']) for _ in range(2)];replays=[f.result(timeout=20) for f in futures]
assert all(r['payment_id']==accepted['payment_id'] for r in replays),replays
with Session(engine) as db:
 assert db.get(Bill,bill_id).balance==400
 payment=db.query(Payment).filter_by(organization_id=org_id).one()
 assert payment.amount==600 and len(payment.raw_data['settlements'])==1
 PayableSettlementService(db,org_id).reverse(request_id,bank_transaction_id=accepted['bank_id'],decided_by=db.get(User,user_id),reason='Synthetic relationship reversal preserving evidence history')
 assert db.get(Bill,bill_id).balance==1000
 assert len(payment.raw_data['settlements'])==1 and len(payment.raw_data['reversals'])==1
result={'status':'passed','synthetic_only':True,'provider_requests':0,'checks':['concurrent bank capacity enforced','same-bank replay returns one payment','reversal preserves original settlement history'],'official_books_verified':False}
evidence_path('2026-09-06-payable-postgres-concurrency.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result));engine.dispose()
