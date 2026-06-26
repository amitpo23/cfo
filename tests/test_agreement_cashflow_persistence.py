"""Agreement cash-flow persistence — data must survive a new service instance.

This is the P0 fix: agreements + cash-flow entries were in-memory only and vanished
on restart. They now round-trip through the database.
"""
import asyncio
from datetime import date

from cfo.database import SessionLocal
from cfo.services.agreement_cashflow_service import (
    AgreementCashFlowService, AgreementType, BillingCycle, AgreementStatus, CashFlowType,
)


def test_agreement_persists_across_instances(fresh_org):
    org_id = fresh_org()["org_id"]

    async def scenario():
        # First instance creates an agreement.
        svc = AgreementCashFlowService(SessionLocal(), organization_id=org_id)
        ag = await svc.create_agreement(
            customer_id="C1", customer_name="לקוח בדיקה",
            agreement_type=AgreementType.RETAINER, title="ריטיינר חודשי",
            total_value=120000, billing_cycle=BillingCycle.MONTHLY,
            start_date=date(2026, 1, 1), end_date=date(2026, 12, 31),
        )
        # A brand-new instance (simulating a restart) must load it from the DB.
        svc2 = AgreementCashFlowService(SessionLocal(), organization_id=org_id)
        loaded = await svc2.list_agreements()
        assert any(a.agreement_id == ag.agreement_id for a in loaded)
        reloaded = svc2._agreements[ag.agreement_id]
        assert reloaded.status == AgreementStatus.ACTIVE
        assert reloaded.title == "ריטיינר חודשי"
        # Generated forecast cash-flow entries persisted too.
        assert any(e.source_id == ag.agreement_id for e in svc2._cash_flow_entries)

        # A recorded actual transaction also survives a reload.
        await svc2.record_actual_transaction(
            amount=5000, date=date(2026, 2, 1), flow_type=CashFlowType.INFLOW,
            category="invoice", description="תקבול")
        svc3 = AgreementCashFlowService(SessionLocal(), organization_id=org_id)
        assert any(e.is_actual and e.amount == 5000 for e in svc3._cash_flow_entries)

    asyncio.run(scenario())


def test_org_isolation(fresh_org):
    org_a = fresh_org()["org_id"]
    org_b = fresh_org()["org_id"]

    async def scenario():
        svc_a = AgreementCashFlowService(SessionLocal(), organization_id=org_a)
        await svc_a.create_agreement(
            customer_id="C1", customer_name="A", agreement_type=AgreementType.PROJECT,
            title="פרויקט A", total_value=50000, billing_cycle=BillingCycle.ONE_TIME,
            start_date=date(2026, 3, 1))
        # Org B sees nothing from org A.
        svc_b = AgreementCashFlowService(SessionLocal(), organization_id=org_b)
        assert await svc_b.list_agreements() == []

    asyncio.run(scenario())
