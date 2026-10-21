"""Synthetic loopback supplier concurrency evidence. No provider client is used."""
import asyncio,json,sys,uuid
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
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
from cfo.services.sync_engine import SyncEngine
from cfo.services.connector_base import NormalizedBill
from decimal import Decimal
settlement_flushed, release_settlement, sync_started = Event(),Event(),Event()
sync_pid = []
def settle_while_paused():
 with Session(engine) as db:
  original_commit=db.commit
  def paused_commit():
   db.flush();settlement_flushed.set()
   assert release_settlement.wait(timeout=10)
   original_commit()
  db.commit=paused_commit
  PayableSettlementService(db,org_id).settle(request_id,bank_transaction_id=bank_ids[0],decided_by=db.get(User,user_id),reason='Synthetic reviewed supplier reference while synchronization overlaps')
def synchronize_old_source():
 assert settlement_flushed.wait(timeout=10)
 with Session(engine) as db:
  sync_pid.append(db.execute(sa.text('SELECT pg_backend_pid()')).scalar_one())
  sync_started.set()
  try:
   SyncEngine(db,None,org_id,'sumit')._upsert_bill(NormalizedBill(external_id='synthetic-bill',vendor_external_id='synthetic-vendor',total=Decimal('1000'),paid_amount=Decimal('100'),balance=Decimal('900'),currency='ILS',status='received',raw_data={'source_observation':'before_local_settlement'}))
   db.commit();return 'overwritten'
  except ValueError:
   db.rollback();return 'review_required'
with ThreadPoolExecutor(max_workers=2) as pool:
 first=pool.submit(settle_while_paused);assert settlement_flushed.wait(timeout=10)
 second=pool.submit(synchronize_old_source);assert sync_started.wait(timeout=10)
 # Require an actual PostgreSQL lock wait, rather than relying on thread timing.
 import time
 deadline=time.monotonic()+5
 with engine.connect() as observer:
  while time.monotonic()<deadline:
   blocked=observer.execute(sa.text('SELECT EXISTS (SELECT 1 FROM pg_locks WHERE pid=:pid AND NOT granted)'),{'pid':sync_pid[0]}).scalar_one()
   if blocked: break
   time.sleep(0.02)
  else: raise AssertionError('The sync did not reach the expected financial row lock')
 release_settlement.set()
 first.result(timeout=20);result=second.result(timeout=20)
with Session(engine) as db:
 balance=db.get(Bill,bill_id).balance
assert result=='review_required' and balance==Decimal('400'),(result,str(balance))
evidence={'status':'passed','synthetic_only':True,'provider_requests':0,'checks':['overlapping sync waits for reviewed bill row','stale source balance requires parity review','committed supplier balance retained']}
evidence_path('2026-09-06-payable-sync-concurrency.json').write_text(json.dumps(evidence,indent=2)+'\n');print(json.dumps(evidence));engine.dispose()
