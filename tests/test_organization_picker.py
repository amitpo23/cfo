from cfo.database import SessionLocal
from cfo.models import User, UserRole
from cfo.services import membership_service


def test_picker_lists_only_active_memberships(client, fresh_org):
    a, b, unrelated = fresh_org(), fresh_org(), fresh_org()
    with SessionLocal() as db:
        user = db.query(User).filter_by(organization_id=a['org_id']).one()
        grantor = db.query(User).filter_by(organization_id=b['org_id']).one()
        user_id = user.id
        membership_service.grant(db, organization_id=b['org_id'], user_id=user.id,
                                 role=UserRole.VIEWER, granted_by_user_id=grantor.id)
        db.commit()
    response = client.get('/api/admin/auth/organizations', headers=a['headers'])
    assert response.status_code == 200
    assert {r['id'] for r in response.json()} == {a['org_id'], b['org_id']}
    assert unrelated['org_id'] not in {r['id'] for r in response.json()}
    with SessionLocal() as db:
        row = membership_service.memberships_for(db, user_id)
        next(m for m in row if m.organization_id == b['org_id']).status = 'revoked'
        db.commit()
    assert {r['id'] for r in client.get('/api/admin/auth/organizations', headers=a['headers']).json()} == {a['org_id']}
