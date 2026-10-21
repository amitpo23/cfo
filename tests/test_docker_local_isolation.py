"""Keep the passwordless local development stack off the LAN."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_local_compose_ports_bind_only_to_loopback():
    compose = (ROOT / "docker-compose.yml").read_text()

    assert 'AUTH_BYPASS_ENABLED: "true"' in compose
    for mapping in ("5433:5432", "8001:8000", "8080:80"):
        assert f'"127.0.0.1:{mapping}"' in compose
