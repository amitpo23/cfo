from cfo.services import system_health


def test_unhealthy_database_is_http_failure(client, monkeypatch):
    monkeypatch.setattr(system_health, 'health_snapshot', lambda: {
        'status':'unhealthy','database':'error','alembic_revision':'unknown','errors_today':-1,
    })
    response = client.get('/api/health')
    assert response.status_code == 503
    assert response.json()['status'] == 'unhealthy'


def test_error_logging_records_stack_without_exception_values(caplog):
    from cfo.services.system_health import record_system_error_best_effort
    try:
        raise RuntimeError('sensitive-value-do-not-log')
    except RuntimeError as exc:
        record_system_error_best_effort(path='/api/failing-route', exception=exc)
    assert 'test_error_logging_records_stack_without_exception_values' in caplog.text
    assert 'RuntimeError' in caplog.text
    assert 'sensitive-value-do-not-log' not in caplog.text
