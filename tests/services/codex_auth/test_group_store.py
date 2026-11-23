"""A group's Codex login lives encrypted in its ``groups`` row."""

from __future__ import annotations

import pytest
from sqlalchemy import select, update

from masterly.db.models import Group
from masterly.multi_user.context import current_user_for, reset_current_user, set_current_user
from masterly.services.codex_auth import service as service_module
from masterly.services.codex_auth.contracts import CodexAuthError, CodexCredentials
from masterly.services.codex_auth.group_store import GroupCodexStore
from masterly.services.config.group_catalog import GroupCatalogService
from tests.conftest import new_owner, run_in_db


def _credentials(token: str) -> CodexCredentials:
    return CodexCredentials(
        schema_version=1,
        access_token=f"access-{token}",
        refresh_token=f"refresh-{token}",
        id_token=f"id-{token}",
        account_id="account-123",
        expires_at=2_000_000_000,
        generation=0,
    )


def _stored(group_id) -> bytes | None:
    return run_in_db(
        lambda session: session.scalar(select(Group.codex_session).where(Group.id == group_id))
    )


@pytest.fixture
def store(needs_db) -> GroupCodexStore:
    return GroupCodexStore(str(new_owner().group_id))


def test_login_is_stored_encrypted_in_the_group_row(store):
    committed = store.commit_credentials(_credentials("one"), expected_generation=0)

    raw = _stored(store.group_id)
    assert raw is not None
    assert b"access-one" not in raw and b"refresh-one" not in raw
    assert committed.generation == 1
    assert store.load_credentials().access_token == "access-one"


def test_generations_guard_against_late_writes_and_logout(store):
    first = store.commit_credentials(_credentials("old"), expected_generation=0)
    store.save_catalog_cache({"models": [{"slug": "m"}]})
    with pytest.raises(CodexAuthError, match="changed"):
        store.commit_credentials(_credentials("late"), expected_generation=0)

    assert store.clear_credentials(expected_generation=first.generation) == 2
    assert store.load_credentials() is None
    assert store.load_catalog_cache() is None
    assert store.current_generation() == 2


def test_a_write_from_another_process_in_between_is_refused(store, monkeypatch):
    store.commit_credentials(_credentials("one"), expected_generation=0)
    other = GroupCodexStore(str(store.group_id))
    read = store._read

    def read_then_lose_the_race():
        previous = read()
        other.commit_credentials(_credentials("two"), expected_generation=1)
        return previous

    monkeypatch.setattr(store, "_read", read_then_lose_the_race)
    with pytest.raises(CodexAuthError, match="changed"):
        store.commit_credentials(_credentials("three"), expected_generation=1)
    monkeypatch.undo()
    assert store.load_credentials().access_token == "access-two"


def test_groups_keep_separate_logins(needs_db):
    first, second = GroupCodexStore(str(new_owner().group_id)), GroupCodexStore(
        str(new_owner().group_id)
    )
    first.commit_credentials(_credentials("first"), expected_generation=0)

    assert second.load_credentials() is None
    assert second.current_generation() == 0


def test_each_group_gets_its_own_sign_in_service(needs_db, monkeypatch):
    monkeypatch.setattr(service_module, "_SERVICE_INSTANCES", {})
    owners = [new_owner(), new_owner()]
    services = []
    for owner in owners:
        token = set_current_user(current_user_for(owner))
        try:
            services.append(service_module.get_codex_oauth_service())
            assert service_module.get_codex_oauth_service() is services[-1]
        finally:
            reset_current_user(token)

    assert services[0] is not services[1]
    for owner, service in zip(owners, services):
        assert isinstance(service._store, GroupCodexStore)
        assert service._store.group_id == owner.group_id
        assert isinstance(service._model_catalog, GroupCatalogService)
        assert service._model_catalog.group_id == str(owner.group_id)


def test_a_cleared_row_reads_as_signed_out(store):
    store.commit_credentials(_credentials("one"), expected_generation=0)
    run_in_db(
        lambda session: session.execute(
            update(Group).where(Group.id == store.group_id).values(codex_session=None)
        )
    )
    assert store.load_credentials() is None
