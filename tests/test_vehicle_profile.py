"""CRUD מינימלי ל-VehicleProfile — עיקר-השימוש הוא עובדה פר-רכב (KB02 §1),
לא פר-עסק, ולכן זהו מודל נפרד מ-Organization."""
from cfo.database import SessionLocal
from cfo.models import VehicleProfile


def test_create_and_read_vehicle_profile(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        vp = VehicleProfile(
            organization_id=org_id, label="טנדר עבודה 12-345-67",
            vehicle_kind="commercial", primarily_business=True,
        )
        db.add(vp)
        db.commit()
        db.refresh(vp)
        assert vp.id is not None

        fetched = db.query(VehicleProfile).filter(VehicleProfile.id == vp.id).first()
        assert fetched.label == "טנדר עבודה 12-345-67"
        assert fetched.vehicle_kind == "commercial"
        assert fetched.primarily_business is True
        assert fetched.attached_to_employee_with_use_value is False
    finally:
        db.close()


def test_primarily_business_defaults_to_none_not_a_guess(fresh_org):
    """בלי קלט מפורש — None (הכרעה), לא ברירת מחדל מנוחשת."""
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        vp = VehicleProfile(organization_id=org_id, label="סדאן 11-111-11", vehicle_kind="private")
        db.add(vp)
        db.commit()
        db.refresh(vp)
        assert vp.primarily_business is None
    finally:
        db.close()


def test_update_and_delete_vehicle_profile(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        vp = VehicleProfile(organization_id=org_id, label="רכב שני", vehicle_kind="private")
        db.add(vp)
        db.commit()
        db.refresh(vp)
        vp_id = vp.id

        vp.primarily_business = False
        db.commit()
        assert db.query(VehicleProfile).filter(VehicleProfile.id == vp_id).first().primarily_business is False

        db.delete(vp)
        db.commit()
        assert db.query(VehicleProfile).filter(VehicleProfile.id == vp_id).first() is None
    finally:
        db.close()


def test_vehicle_profiles_are_org_scoped(fresh_org):
    org_a = fresh_org()["org_id"]
    org_b = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        db.add(VehicleProfile(organization_id=org_a, label="רכב א", vehicle_kind="private"))
        db.commit()
        assert db.query(VehicleProfile).filter(VehicleProfile.organization_id == org_b).count() == 0
        assert db.query(VehicleProfile).filter(VehicleProfile.organization_id == org_a).count() == 1
    finally:
        db.close()
