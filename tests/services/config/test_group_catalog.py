"""Each group's model catalog lives in its ``groups`` row, with keys encrypted."""

from __future__ import annotations

import pytest
from sqlalchemy import select, update

from masterly.db.models import Group
from masterly.multi_user.context import current_user_for, reset_current_user, set_current_user
from masterly.services.config import get_model_catalog_service
from masterly.services.config.group_catalog import refresh_group_catalog
from masterly.services.encryption import ENCRYPTED_PREFIX
from tests.conftest import new_learner, new_owner, run_in_db


@pytest.fixture
def signed_in(needs_db):
    """Run a block as an account, the way a request does."""

    class _As:
        def __init__(self, account):
            self.account = account

        def __enter__(self):
            self.token = set_current_user(current_user_for(self.account))
            return get_model_catalog_service()

        def __exit__(self, *exc):
            reset_current_user(self.token)

    return _As


def _add_connection(catalog, connection_id: str, key: str) -> None:
    catalog.setdefault("connections", []).append(
        {"id": connection_id, "name": "Gateway", "provider": "openai", "api_key": key}
    )


def _stored_row(group_id):
    async def read(session):
        return (
            await session.execute(
                select(Group.model_catalog, Group.catalog_revision).where(Group.id == group_id)
            )
        ).one()

    return run_in_db(read)


def test_a_save_lands_in_the_group_row_with_the_key_encrypted(signed_in):
    owner = new_owner()
    with signed_in(owner) as service:
        catalog = service.load()
        _add_connection(catalog, "conn-a", "sk-secret-a")
        service.save(catalog)

    stored, revision = _stored_row(owner.group_id)
    connection = next(c for c in stored["connections"] if c["id"] == "conn-a")
    assert connection["api_key"].startswith(ENCRYPTED_PREFIX)
    assert "sk-secret-a" not in str(stored)
    assert revision >= 1

    with signed_in(owner) as service:
        loaded = next(c for c in service.load()["connections"] if c["id"] == "conn-a")
    assert loaded["api_key"] == "sk-secret-a"


def test_groups_do_not_see_each_other_and_learners_share_their_owners(signed_in):
    first, second = new_owner(), new_owner()
    learner = new_learner(first.group_id)
    with signed_in(first) as service:
        catalog = service.load()
        _add_connection(catalog, "conn-first", "sk-first")
        service.save(catalog)

    with signed_in(second) as service:
        assert all(c["id"] != "conn-first" for c in service.load().get("connections", []))
    with signed_in(learner) as service:
        assert any(c["id"] == "conn-first" for c in service.load()["connections"])


def test_a_change_saved_elsewhere_is_picked_up_by_revision(signed_in):
    owner = new_owner()
    with signed_in(owner) as service:
        catalog = service.load()

    # Another backend process saves: the row and its revision move together.
    _add_connection(catalog, "conn-elsewhere", "plain-key")
    run_in_db(
        lambda session: session.execute(
            update(Group)
            .where(Group.id == owner.group_id)
            .values(model_catalog=catalog, catalog_revision=Group.catalog_revision + 1)
        )
    )
    with signed_in(owner) as service:
        assert all(c["id"] != "conn-elsewhere" for c in service.load()["connections"])

    run_in_db(lambda session: refresh_group_catalog(session, str(owner.group_id)))
    with signed_in(owner) as service:
        connection = next(c for c in service.load()["connections"] if c["id"] == "conn-elsewhere")
    assert connection["api_key"] == "plain-key"
