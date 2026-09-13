"""Concurrent source identity and report occurrence checks on guarded local PostgreSQL."""
import asyncio
import json
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier, Lock
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
from environment import test_engine, evidence_path
from sqlalchemy.orm import Session
from cfo.models import DocumentIntake, Organization, ReportRecord
from cfo.services.document_intake import DocumentIntakeService
from cfo.services.report_builder_service import ReportBuilderService, ReportFrequency, ReportFormat, DeliveryMethod

engine = test_engine()
with Session(engine) as db:
    org = Organization(name='SYNTHETIC DOCUMENT REPORT CONCURRENCY', settings={'synthetic': True})
    db.add(org); db.commit(); org_id = org.id

barrier = Barrier(2)
def receive(channel):
    with Session(engine) as db:
        barrier.wait(timeout=10)
        return DocumentIntakeService(db, org_id).receive(b'%PDF-1.4 concurrent source',
            media_type='application/pdf', source=channel, filename='synthetic.pdf')

with ThreadPoolExecutor(max_workers=2) as pool:
    futures = [pool.submit(receive, channel) for channel in ('email', 'upload')]
    received = [future.result(timeout=20) for future in futures]
assert sorted(row['status'] for row in received) == ['duplicate', 'queued'], received
assert len({row['document_id'] for row in received}) == 1
with Session(engine) as db:
    row = db.query(DocumentIntake).filter_by(organization_id=org_id).one()
    assert {source['channel'] for source in row.sources} == {'email', 'upload'}
    service = ReportBuilderService(db, org_id)
    schedule = service.create_schedule('DEFAULT-PL', 'Synthetic occurrence', ReportFrequency.DAILY, [],
        delivery_method=DeliveryMethod.DOWNLOAD, format=ReportFormat.JSON)
    service.update_schedule(schedule.schedule_id, {'next_run': '2020-01-01T00:00:00'})

barrier, lock, calls = Barrier(2), Lock(), []
def synthetic_data(*args, **kwargs):
    with lock: calls.append(1)
    return []

with tempfile.TemporaryDirectory(prefix='rezef-concurrent-report-') as directory:
    def run():
        with Session(engine) as db:
            service = ReportBuilderService(db, org_id); service.reports_dir = Path(directory)
            barrier.wait(timeout=10)
            return asyncio.run(service.run_scheduled_reports())
    with patch.object(ReportBuilderService, '_generate_pl_data', synthetic_data):
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(run) for _ in range(2)]
            results = [future.result(timeout=20) for future in futures]
assert len(calls) == 1 and sum(len(result) for result in results) == 1, results
with Session(engine) as db:
    service = ReportBuilderService(db, org_id)
    assert service.get_execution_history()[0].status == 'completed'
    assert db.query(ReportRecord).filter_by(organization_id=org_id, kind='execution').count() == 1
    assert db.query(ReportRecord).filter_by(organization_id=org_id, kind='file').count() == 1
    assert asyncio.run(service.run_scheduled_reports()) == []

result = {'status': 'passed', 'synthetic_only': True, 'provider_requests': 0,
    'checks': ['concurrent same-content intake creates one source and preserves both channel observations',
        'concurrent due report workers create one occurrence, one file and one execution',
        'repeated worker invocation does not rerun the occurrence'], 'official_books_verified': False}
evidence_path('2026-09-07-document-report-concurrency.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result))
engine.dispose()
