"""Report configuration and execution durability; synthetic local files only."""
import asyncio
from datetime import datetime, timedelta

import pytest

from cfo.database import SessionLocal
from cfo.services.report_builder_service import ReportBuilderService, ReportType, ReportFrequency, DeliveryMethod, ReportFormat


def template(service):
    return service.create_template('Synthetic P&L', ReportType.PROFIT_LOSS,
        [{'field_name': 'amount', 'display_name': 'Amount', 'data_type': 'currency'}])


def test_templates_and_schedules_survive_restart_without_cross_org_leak(fresh_org):
    org, foreign = fresh_org()['org_id'], fresh_org()['org_id']
    with SessionLocal() as db:
        svc = ReportBuilderService(db, org)
        t = template(svc)
        s = svc.create_schedule(t.template_id, 'Synthetic monthly', ReportFrequency.MONTHLY, [],
            delivery_method=DeliveryMethod.DOWNLOAD)
    with SessionLocal() as db:
        svc = ReportBuilderService(db, org)
        assert svc.get_template(t.template_id).name == 'Synthetic P&L'
        assert svc.get_schedules()[0].schedule_id == s.schedule_id
        assert svc.pause_schedule(s.schedule_id)
        other = ReportBuilderService(db, foreign)
        assert other.get_template(t.template_id) is None
        assert other.get_schedules() == []
        assert other.delete_template(t.template_id) is False
    with SessionLocal() as db:
        assert ReportBuilderService(db, org).get_schedules()[0].is_active is False


def test_schedule_validates_template_and_refuses_unknown_delivery(fresh_org):
    with SessionLocal() as db:
        svc = ReportBuilderService(db, fresh_org()['org_id'])
        with pytest.raises(ValueError): svc.create_schedule('missing', 'x', ReportFrequency.DAILY, [])
        with pytest.raises(ValueError): svc.create_schedule('DEFAULT-PL', 'x', ReportFrequency.DAILY, [], delivery_method=DeliveryMethod.EMAIL)


def test_execution_and_file_evidence_survive_restart_and_repeat(fresh_org, tmp_path):
    org = fresh_org()['org_id']
    with SessionLocal() as db:
        svc = ReportBuilderService(db, org); svc.reports_dir = tmp_path
        s = svc.create_schedule('DEFAULT-PL', 'Synthetic', ReportFrequency.DAILY, [],
            delivery_method=DeliveryMethod.DOWNLOAD, format=ReportFormat.JSON)
        svc.update_schedule(s.schedule_id, {'next_run': (datetime.now() - timedelta(days=2)).isoformat()})
        first = asyncio.run(svc.run_scheduled_reports())
        assert len(first) == 1 and first[0].status == 'completed'
    with SessionLocal() as db:
        svc = ReportBuilderService(db, org); svc.reports_dir = tmp_path
        history = svc.get_execution_history()
        assert len(history) == 1 and history[0].result.report_id == first[0].result.report_id
        assert asyncio.run(svc.run_scheduled_reports()) == []


def test_failed_generation_is_persisted_and_not_retried_implicitly(fresh_org, monkeypatch):
    org = fresh_org()['org_id']
    with SessionLocal() as db:
        svc = ReportBuilderService(db, org)
        s = svc.create_schedule('DEFAULT-PL', 'Synthetic', ReportFrequency.DAILY, [], delivery_method=DeliveryMethod.DOWNLOAD)
        svc.update_schedule(s.schedule_id, {'next_run': '2020-01-01T00:00:00'})
        def fail(**kwargs): raise ValueError('synthetic unavailable source')
        monkeypatch.setattr(svc, 'generate_report', fail)
        assert asyncio.run(svc.run_scheduled_reports())[0].status == 'failed'
    with SessionLocal() as db:
        svc = ReportBuilderService(db, org)
        assert svc.get_execution_history()[0].status == 'failed'
        assert asyncio.run(svc.run_scheduled_reports()) == []


def test_report_update_cannot_change_org_or_identity(fresh_org):
    with SessionLocal() as db:
        svc = ReportBuilderService(db, fresh_org()['org_id'])
        t = template(svc)
        with pytest.raises(ValueError): svc.update_template(t.template_id, {'organization_id': 999})
        with pytest.raises(ValueError): svc.update_template(t.template_id, {'template_id': 'DEFAULT-PL'})


def test_report_http_saved_download_and_tenant_access(client, fresh_org):
    a, b = fresh_org(), fresh_org()
    path = '/api/financial/reports'
    t = client.post(f'{path}/templates', headers=a['headers'], json={'name': 'Synthetic saved report',
        'report_type': 'profit_loss', 'columns': [{'field_name': 'amount', 'display_name': 'Amount', 'data_type': 'currency'}]})
    assert t.status_code == 200, t.text
    tid = t.json()['data']['template_id']
    assert any(t['template_id'] == tid for t in client.get(f'{path}/templates', headers=a['headers']).json()['data'])
    assert all(t['template_id'] != tid for t in client.get(f'{path}/templates', headers=b['headers']).json()['data'])
    response = client.post(f'{path}/generate', headers=a['headers'], json={'template_id': tid, 'format': 'json',
        'parameters': {'year': 2026, 'month': 9}})
    assert response.status_code == 200, response.text
    url = response.json()['data']['download_url']
    assert client.get(url, headers=a['headers']).status_code == 200
    assert client.get(url, headers=b['headers']).status_code == 404
    assert client.post(f'{path}/schedules', headers=a['headers'], json={'template_id': tid, 'name': 'No fake delivery',
        'frequency': 'monthly', 'recipients': [], 'delivery_method': 'email'}).status_code == 400


def test_report_never_silently_ignores_unsupported_format_type_or_filter(fresh_org, tmp_path):
    with SessionLocal() as db:
        svc = ReportBuilderService(db, fresh_org()['org_id']); svc.reports_dir = tmp_path
        with pytest.raises(ValueError): svc.generate_report('DEFAULT-PL', ReportFormat.PDF)
        t = svc.create_template('Unsupported balance', ReportType.BALANCE_SHEET, [])
        with pytest.raises(ValueError): svc.generate_report(t.template_id, ReportFormat.JSON)
        with pytest.raises(ValueError): svc.generate_report('DEFAULT-PL', ReportFormat.JSON,
            filters=[{'field_name': 'not_a_field', 'operator': 'eq', 'value': 1}])


def test_manual_runs_preserve_history_success_failure_and_result_evidence(fresh_org, tmp_path):
    org = fresh_org()['org_id']
    with SessionLocal() as db:
        svc = ReportBuilderService(db, org); svc.reports_dir = tmp_path
        report = svc.generate_report('DEFAULT-PL', ReportFormat.JSON)
        with pytest.raises(ValueError): svc.generate_report('DEFAULT-PL', ReportFormat.PDF)
    with SessionLocal() as db:
        history = ReportBuilderService(db, org).get_execution_history()
        assert len(history) == 2
        assert {r.status for r in history} == {'completed', 'failed'}
        assert next(r for r in history if r.status == 'completed').result.report_id == report.report_id


def test_source_failure_cannot_be_reported_as_successful_empty_report(fresh_org, monkeypatch, tmp_path):
    from cfo.services.financial_reports_service import FinancialReportsService
    def fail(*args, **kwargs): raise RuntimeError('synthetic source unavailable')
    monkeypatch.setattr(FinancialReportsService, 'generate_profit_loss', fail)
    with SessionLocal() as db:
        svc = ReportBuilderService(db, fresh_org()['org_id']); svc.reports_dir = tmp_path
        with pytest.raises(ValueError): svc.generate_report('DEFAULT-PL', ReportFormat.JSON)
        assert svc.get_execution_history()[0].status == 'failed'


def test_html_export_preserves_external_text_without_executable_markup(fresh_org, monkeypatch, tmp_path):
    with SessionLocal() as db:
        svc = ReportBuilderService(db, fresh_org()['org_id']); svc.reports_dir = tmp_path
        t = svc.create_template('<script>synthetic()</script>', ReportType.PROFIT_LOSS,
            [{'field_name': 'category', 'display_name': '<b>label</b>', 'data_type': 'string'}])
        monkeypatch.setattr(svc, '_execute_report_query', lambda *args: [{'category': '<img src=x onerror=synthetic()>'}])
        report = svc.generate_report(t.template_id, ReportFormat.HTML)
        from pathlib import Path
        content = Path(report.file_path).read_text()
        assert '<script>' not in content and '<img ' not in content
        assert '&lt;script&gt;' in content


def test_moshko_reports_use_saved_org_scoped_metadata_only(fresh_org):
    from cfo.services.ai_chat_tools import TOOLS
    org, foreign = fresh_org()['org_id'], fresh_org()['org_id']
    with SessionLocal() as db:
        t = template(ReportBuilderService(db, org))
        tool = TOOLS['get_saved_reports']
        assert tool.category == 'read'
        result = asyncio.run(tool.fn(db, org))
        assert any(row['template_id'] == t.template_id for row in result['templates'])
        assert result['sync_triggered'] is False
        other = asyncio.run(tool.fn(db, foreign))
        assert not any(row['template_id'] == t.template_id for row in other['templates'])
        assert 'content_base64' not in str(result)


def test_previous_period_is_not_a_budget(fresh_org, monkeypatch):
    from types import SimpleNamespace
    from cfo.services.financial_reports_service import FinancialReportsService
    monkeypatch.setattr(FinancialReportsService, 'generate_profit_loss', lambda *a, **k: SimpleNamespace(
        revenue=[SimpleNamespace(category_hebrew='Synthetic', amount=20, previous_amount=10, change_percentage=100)],
        cost_of_goods_sold=[], operating_expenses=[], other_income=[], other_expenses=[]))
    with SessionLocal() as db:
        row = ReportBuilderService(db, fresh_org()['org_id'])._generate_pl_data()[0]
        assert row['previous_period'] == 10
        assert row['budget'] is None


def test_stale_template_update_cannot_overwrite_another_worker(fresh_org):
    org = fresh_org()['org_id']
    with SessionLocal() as first, SessionLocal() as second:
        a, b = ReportBuilderService(first, org), ReportBuilderService(second, org)
        t = template(a)
        stale = a.get_template(t.template_id)
        b.update_template(t.template_id, {'name': 'Reviewed new name'})
        stale.name = 'Stale worker name'
        with pytest.raises(ValueError): a._templates[t.template_id] = stale
        assert a.get_template(t.template_id).name == 'Reviewed new name'
