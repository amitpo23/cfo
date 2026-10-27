"""Moshko lists the business's dashboards and proposes a new one.

Owner request 27/10/2026: "a tool for Moshko to create dashboards". The chat
creates only for its own organization (never a model-supplied one), never a
public dashboard, and always as a draft that is activated in the app. Adding
related organizations and binding accounts stays in the app, because both reach
beyond the chat's organization. No provider calls.
"""
import asyncio

import pytest

from cfo.database import SessionLocal
from cfo.models import ClientDashboard, User, UserRole
from cfo.services import policy_engine
from cfo.services.ai_chat_tools import TOOLS


def _user_id(org_id):
    with SessionLocal() as db:
        return db.query(User).filter(User.organization_id == org_id).first().id


def _run(name, org_id, user_id, **kwargs):
    with SessionLocal() as db:
        return asyncio.run(TOOLS[name].fn(db, org_id, _user_id=user_id, **kwargs))


def test_the_read_tool_and_the_write_tool_are_registered_as_such():
    listing, creating = TOOLS["list_dashboards"], TOOLS["create_dashboard"]
    assert listing.category == "read" and listing.needs_user and listing.office is False
    assert creating.category == "write" and creating.needs_user and creating.office is False
    assert creating.policy_action == "dashboards.manage"


def test_the_write_tool_takes_no_organization_and_no_public_mode():
    schema = TOOLS["create_dashboard"].input_schema
    assert not {"organization_id", "primary_organization_id", "office_organization_id"} & set(schema["properties"])
    assert schema["properties"]["access_mode"]["enum"] == ["members", "link"]


def test_dashboards_manage_is_an_admin_write():
    assert "dashboards.manage" in policy_engine.WRITE_ACTIONS
    assert "dashboards.manage" in policy_engine.ROLE_PRESETS[UserRole.ADMIN]
    for role in (UserRole.ACCOUNTANT, UserRole.MANAGER, UserRole.USER, UserRole.VIEWER):
        assert "dashboards.manage" not in policy_engine.ROLE_PRESETS[role]


def test_it_creates_a_draft_for_the_chat_organization(fresh_org):
    org = fresh_org()

    result = _run("create_dashboard", org["org_id"], _user_id(org["org_id"]),
                  slug="moshko-made", title="תזרים העסק")

    assert result["status"] == "created" and result["path"] == "/d/moshko-made"
    with SessionLocal() as db:
        row = db.query(ClientDashboard).filter_by(slug="moshko-made").one()
        assert row.primary_organization_id == org["org_id"]
        assert row.status == "draft" and row.access_mode == "members"
    assert result["provider_calls"] == 0


def test_a_public_mode_is_refused_even_if_the_model_sends_it(fresh_org):
    org = fresh_org()

    with pytest.raises(ValueError):
        _run("create_dashboard", org["org_id"], _user_id(org["org_id"]),
             slug="moshko-public", title="x", access_mode="public")


def test_a_taken_slug_raises_so_no_fake_success_is_recorded(fresh_org):
    org = fresh_org()
    user_id = _user_id(org["org_id"])
    _run("create_dashboard", org["org_id"], user_id, slug="moshko-twice", title="x")

    with pytest.raises(ValueError):
        _run("create_dashboard", org["org_id"], user_id, slug="moshko-twice", title="y")


def test_it_lists_only_the_chat_organizations_dashboards(fresh_org):
    mine, other = fresh_org(), fresh_org()
    _run("create_dashboard", mine["org_id"], _user_id(mine["org_id"]), slug="moshko-mine", title="שלי")
    _run("create_dashboard", other["org_id"], _user_id(other["org_id"]), slug="moshko-theirs", title="אחר")

    result = _run("list_dashboards", mine["org_id"], _user_id(mine["org_id"]))

    slugs = {row["slug"] for row in result["dashboards"]}
    assert "moshko-mine" in slugs and "moshko-theirs" not in slugs
    mine_row = next(row for row in result["dashboards"] if row["slug"] == "moshko-mine")
    assert mine_row["path"] == "/d/moshko-mine" and mine_row["status"] == "draft"
    assert result["provider_calls"] == 0


def test_a_user_without_access_lists_nothing(fresh_org):
    mine, stranger = fresh_org(), fresh_org()
    _run("create_dashboard", mine["org_id"], _user_id(mine["org_id"]), slug="moshko-hidden", title="x")

    result = _run("list_dashboards", mine["org_id"], _user_id(stranger["org_id"]))

    assert result["dashboards"] == []
