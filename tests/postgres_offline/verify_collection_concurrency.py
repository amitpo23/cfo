"""Synthetic PostgreSQL concurrency proof; loopback test database only."""
import json,sys,uuid
from pathlib import Path
from datetime import date
from decimal import Decimal
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
sys.path.insert(0,str(Path(__file__).resolve().parents[2] / 'src'))
from environment import test_engine, evidence_path
import sqlalchemy as sa
from sqlalchemy.orm import Session
from cfo.models import Organization,User,UserRole,OrganizationMembership,Contact,ContactType,Invoice,InvoiceStatus,Payment,BankTransaction,CollectionPaymentAllocation
from cfo.services.collection_settlement import CollectionSettlementService
engine=test_engine()
with Session(engine) as db:
 org=Organization(name='SYNTHETIC ALLOCATION CONCURRENCY',settings={'synthetic':True});db.add(org);db.flush()
 user=User(organization_id=org.id,email=f'synthetic-{uuid.uuid4()}@example.invalid',password_hash='not-a-login-hash',full_name='Synthetic reviewer',role=UserRole.ADMIN,is_active=True);db.add(user);db.flush()
 db.add(OrganizationMembership(organization_id=org.id,user_id=user.id,role=UserRole.ADMIN,status='active'))
 contact=Contact(organization_id=org.id,source='sumit',external_id='synthetic-customer',contact_type=ContactType.CUSTOMER,name='Synthetic');db.add(contact);db.flush()
 invoice=Invoice(organization_id=org.id,source='sumit',external_id='synthetic-invoice',contact_id=contact.id,total=1000,paid_amount=0,balance=1000,currency='ILS',status=InvoiceStatus.SENT,issue_date=date(2026,9,6),raw_data={'document_type':'invoice'});db.add(invoice);db.flush()
 payment=Payment(organization_id=org.id,source='sumit',external_id='receipt:synthetic',contact_id=contact.id,amount=1000,currency='ILS',method='receipt',payment_date=date(2026,9,6),raw_data={'document_id':'synthetic','document_type':'receipt','status':'open'})
 bank=BankTransaction(organization_id=org.id,source='open_finance',external_id='synthetic-bank',amount=1000,currency='ILS',transaction_date=date(2026,9,6),is_provisional=False,raw_data={'status':'BOOKED'})
 db.add_all([payment,bank]);db.commit();org_id,user_id,invoice_id,payment_id,bank_id=org.id,user.id,invoice.id,payment.id,bank.id
barrier=Barrier(2)
def allocate(key,amount):
 with Session(engine) as db:
  actor=db.get(User,user_id);barrier.wait(timeout=10)
  try:
   result=CollectionSettlementService(db,org_id).allocate_existing(invoice_id=invoice_id,payment_id=payment_id,bank_transaction_id=bank_id,amount=amount,idempotency_key=key,decided_by=actor,reason='Synthetic reviewed reference and receipt identity')
   return {'status':'allocated','allocation_id':result['allocation_id']}
  except ValueError as exc:
   db.rollback();return {'status':'blocked','reason':str(exc)}
with ThreadPoolExecutor(max_workers=2) as pool:
 futures=[pool.submit(allocate,key,'600') for key in ['capacity-a','capacity-b']];results=[f.result(timeout=20) for f in futures]
assert sorted(r['status'] for r in results)==['allocated','blocked'],results
with Session(engine) as db:
 invoice=db.get(Invoice,invoice_id);assert invoice.balance==Decimal('400')
 allocation_id=next(r['allocation_id'] for r in results if r['status']=='allocated')
 CollectionSettlementService(db,org_id).reverse_allocation(allocation_id,decided_by=db.get(User,user_id),reason='Synthetic reversal preserves original decision history')
 assert db.get(Invoice,invoice_id).balance==Decimal('1000')
barrier=Barrier(2)
with ThreadPoolExecutor(max_workers=2) as pool:
 futures=[pool.submit(allocate,'same-request','500') for _ in range(2)];replays=[f.result(timeout=20) for f in futures]
assert all(r['status']=='allocated' for r in replays) and replays[0]['allocation_id']==replays[1]['allocation_id'],replays
with Session(engine) as db:
 assert db.get(Invoice,invoice_id).balance==Decimal('500')
 assert db.query(CollectionPaymentAllocation).filter_by(organization_id=org_id,status='active').count()==1
 assert db.query(CollectionPaymentAllocation).filter_by(organization_id=org_id,status='reversed').count()==1
result={'status':'passed','synthetic_only':True,'provider_requests':0,'checks':['concurrent capacity: one 600 allocation accepted, second blocked against 1000 receipt/bank','reviewed reversal preserves history and restores balance','concurrent same-key replay creates one 500 allocation'], 'official_books_verified':False}
evidence_path('2026-09-06-provider-allocation-concurrency.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result));engine.dispose()
