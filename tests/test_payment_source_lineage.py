from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace
import asyncio
from cfo.services.sumit_connector import SumitConnector


def test_sumit_payment_and_receipt_ids_do_not_collide_or_invent_invoice(monkeypatch):
    class Client:
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        async def list_payments(self,**kwargs):
            return [SimpleNamespace(id='42',customer_id='7',date=date(2026,9,6),amount=10,currency='ILS',status='completed'),
                    SimpleNamespace(id='43',customer_id='7',date=date(2026,9,6),amount=10,currency='ILS',status='failed')]
    async def get_client(self):return Client()
    async def docs(*args):return [SimpleNamespace(id='42',document_id='42',customer_id='7',date=date(2026,9,6),total=10,currency='ILS',status='open',document_type='receipt')]
    monkeypatch.setattr(SumitConnector,'_get_client',get_client)
    monkeypatch.setattr(SumitConnector,'_list_documents_all',docs)
    result=asyncio.run(SumitConnector('fake','1',1).fetch_payments())
    assert not result.error,result.error
    assert {p.external_id for p in result.items}=={'billing:42','receipt:42'}
    assert all(p.invoice_external_id is None for p in result.items)
    assert all(p.raw_data['invoice_link_status']=='unavailable_in_provider_list' for p in result.items)


def test_late_invoice_link_is_resolved_even_when_payload_hash_unchanged(client,fresh_org):
    from cfo.database import SessionLocal
    from cfo.models import Invoice,Payment
    from cfo.services.sync_engine import SyncEngine
    from cfo.services.connector_base import NormalizedPayment
    identity=fresh_org()
    db=SessionLocal();org=identity['org_id']
    engine=SyncEngine(db,SumitConnector('fake','1',org),org,source='sumit')
    item=NormalizedPayment(external_id='receipt:late',invoice_external_id='later',payment_date=date(2026,9,6),amount=Decimal('100'),raw_data={'id':'late'})
    engine._upsert_payment(item);db.commit()
    inv=Invoice(organization_id=org,source='sumit',external_id='later',total=100,balance=100)
    db.add(inv);db.commit()
    engine._upsert_payment(item);db.commit()
    payment=db.query(Payment).filter_by(organization_id=org,external_id=item.external_id).one()
    assert payment.invoice_id==inv.id
    db.close()
