"""prod_smoke חייב לרוץ end-to-end מול האפליקציה ולדווח סטטוס לכל נתיב."""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "prod_smoke", Path(__file__).parent.parent / "scripts" / "prod_smoke.py"
)
prod_smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prod_smoke)


def test_smoke_runs_against_local_app(client, owner):
    """מריצים את הסקריפט עצמו מול ה-TestClient — login אמיתי + סריקה מלאה."""
    results = prod_smoke.run_smoke(
        base_url="", email="owner@example.com", password="secret123", client=client
    )
    paths = {r["path"] for r in results}
    assert "/api/health" in paths
    assert any(r["path"].startswith("/api/dashboard") for r in results)
    login = next(r for r in results if r["path"] == "/api/admin/auth/login")
    assert login["ok"], "login מקומי חייב להצליח — owner קיים מה-conftest"
    # אף תוצאה לא מתפוצצת בלי סטטוס; כשלים מדווחים, לא נזרקים
    assert all(isinstance(r["status"], int) for r in results)
    # נתיבים אמיתיים (לא 404) — תפס בעבר "financial/reports/profit-loss" ו-"ap/aging" שגויים
    by_path = {r["path"]: r for r in results}
    assert by_path["/api/reports/profit-loss"]["status"] != 404
    assert by_path["/api/daily-reports/ap-aging"]["status"] != 404
