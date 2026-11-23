from masterly.multi_user import paths
from masterly.multi_user.context import reset_current_user, set_current_user
from masterly.multi_user.models import CurrentUser, UserScope
from masterly.services.path_service import get_path_service


def test_every_account_is_scoped_under_users():
    scope = paths.scope_for_user("u_owner")
    assert scope.kind == "user"
    assert scope.root.parts[-2:] == ("users", "u_owner")


def test_outside_a_request_nobody_is_an_owner():
    assert paths.local_admin_user().is_owner is False


def test_path_service_uses_current_user_scope(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "_path_services", {})
    user_root = tmp_path / "data" / "users" / "u_alice"
    user = CurrentUser(
        id="u_alice",
        email="alice@example.com",
        display_name="alice",
        role="learner",
        group_id="g_1",
        scope=UserScope(kind="user", user_id="u_alice", root=user_root),
    )

    token = set_current_user(user)
    try:
        service = get_path_service()
        assert service.workspace_root == user_root.resolve()
        assert service.get_chat_history_db() == user_root.resolve() / "user" / "chat_history.db"
    finally:
        reset_current_user(token)
