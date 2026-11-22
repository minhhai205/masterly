from masterly.multi_user import identity, paths
from masterly.multi_user.context import reset_current_user, set_current_user
from masterly.multi_user.models import CurrentUser, UserScope
from masterly.services.path_service import get_path_service


def test_saved_accounts_get_a_stable_id(tmp_path, monkeypatch):
    users_file = tmp_path / "data" / "system" / "auth" / "users.json"
    monkeypatch.setattr(identity, "USERS_FILE", users_file)

    identity.save_user("alice", "h1", role="admin")
    identity.save_user("bob", "h2")
    first = identity.load_users()
    identity.save_user("bob", "h3")
    second = identity.load_users()

    assert first["alice"]["id"].startswith("u_")
    assert first["alice"]["role"] == "admin"
    assert first["bob"]["role"] == "user"
    # Updating an account keeps its id: data directories are keyed by it.
    assert second["bob"]["id"] == first["bob"]["id"]
    assert second["bob"]["hash"] == "h3"


def test_path_service_uses_current_user_scope(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "ensure_user_workspace", lambda _uid: tmp_path)
    user_root = tmp_path / "data" / "users" / "u_alice"
    user = CurrentUser(
        id="u_alice",
        username="alice",
        role="user",
        scope=UserScope(kind="user", user_id="u_alice", root=user_root),
    )

    token = set_current_user(user)
    try:
        service = get_path_service()
        assert service.workspace_root == user_root.resolve()
        assert service.get_chat_history_db() == user_root.resolve() / "user" / "chat_history.db"
    finally:
        reset_current_user(token)
