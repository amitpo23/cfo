"""יצוא 'מבנה אחיד' (openfrmt.py) — INI.TXT + BKMVDATA.TXT.

בודק חוזי-מבנה (ZIP חוקי, ספירות INI מול BKMVDATA, C100 לכל מסמך בטווח, ובידוד
ארגונים) — לא נאמנות בית-לבית מלאה למפרט הרשמי (מתועד כטיוטה, ראה openfrmt.DISCLAIMER).
"""
import io
import zipfile
from datetime import date

from cfo.database import SessionLocal
from cfo.models import Invoice, Bill, InvoiceStatus, BillStatus
from cfo.services import openfrmt


def _seed(org_id, tag="ofrmt-test"):
    db = SessionLocal()
    try:
        for model in (Bill, Invoice):
            db.query(model).filter(model.organization_id == org_id, model.source == tag).delete()
        db.commit()
        db.add(Invoice(organization_id=org_id, external_id=f"{tag}-INV-1", source=tag,
                       invoice_number="200", issue_date=date(2026, 6, 5),
                       status=InvoiceStatus.SENT, subtotal=1000, tax=180, total=1180))
        db.add(Bill(organization_id=org_id, external_id=f"{tag}-BILL-1", source=tag,
                    bill_number="B200", issue_date=date(2026, 6, 10),
                    status=BillStatus.RECEIVED, subtotal=500, tax=90, total=590))
        db.commit()
    finally:
        db.close()


def test_build_openfrmt_ini_counts_match_bkmvdata(fresh_org):
    org_id = fresh_org()["org_id"]
    _seed(org_id)
    db = SessionLocal()
    try:
        out = openfrmt.build_openfrmt(db, org_id, date(2026, 6, 1), date(2026, 6, 30))
        counts = out["summary"]["record_counts"]

        # ל-C100 יש בדיוק רשומה אחת לכל מסמך בטווח (1 חשבונית + 1 חשבון ספק).
        assert counts["C100"] == 2

        body_lines = out["bkmvdata"].split("\r\n")
        c100_actual = sum(1 for l in body_lines if l.startswith("C100"))
        d110_actual = sum(1 for l in body_lines if l.startswith("D110"))
        a100_actual = sum(1 for l in body_lines if l.startswith("A100"))
        z900_actual = sum(1 for l in body_lines if l.startswith("Z900"))

        assert c100_actual == counts["C100"]
        assert d110_actual == counts["D110"]
        assert a100_actual == counts["A100"] == 1
        assert z900_actual == counts["Z900"] == 1
        assert body_lines[0].startswith("A100")
        assert body_lines[-1].startswith("Z900")
        assert out["disclaimer"]
        assert out["draft"] is True
    finally:
        db.close()


def test_build_openfrmt_org_isolation(fresh_org):
    org_a = fresh_org()["org_id"]
    org_b = fresh_org()["org_id"]
    _seed(org_a, tag="ofrmt-a")
    _seed(org_b, tag="ofrmt-b")
    db = SessionLocal()
    try:
        out_a = openfrmt.build_openfrmt(db, org_a, date(2026, 6, 1), date(2026, 6, 30))
        # רק המסמכים של org_a — לא נזלג מסמך של org_b.
        assert out_a["summary"]["record_counts"]["C100"] == 2
        assert "ofrmt-b" not in out_a["bkmvdata"]
    finally:
        db.close()


def test_openfrmt_route_returns_valid_zip(client, owner):
    resp = client.get(
        "/api/daily-reports/openfrmt?date_from=2026-06-01&date_to=2026-06-30",
        headers=owner["headers"],
    )
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"] == "application/zip"
    cd = resp.headers.get("content-disposition", "")
    assert "attachment" in cd and "OPENFRMT" in cd

    zf = zipfile.ZipFile(io.BytesIO(resp.content))
    names = set(zf.namelist())
    assert names == {"INI.TXT", "BKMVDATA.TXT"}
    ini_text = zf.read("INI.TXT").decode("iso-8859-8")
    bkm_text = zf.read("BKMVDATA.TXT").decode("iso-8859-8")
    assert "[General]" in ini_text
    assert bkm_text.startswith("A100")


def test_openfrmt_route_requires_auth(client):
    resp = client.get("/api/daily-reports/openfrmt?date_from=2026-06-01&date_to=2026-06-30")
    assert resp.status_code == 403
