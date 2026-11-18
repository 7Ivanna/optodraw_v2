"""The editor is local-only.

The package serves one editor to the machine it runs on. A hosted, shared
editor does not isolate users or their sessions, so it is outside the release
scope: ``create_app(hosted=True)`` refuses to start, the launcher has no
``--hosted`` flag, and a request that does not come from this machine gets 403
even when the server is bound to a public address.
"""

from __future__ import annotations

import pytest

fastapi_testclient = pytest.importorskip("fastapi.testclient")

from optodraw.app.server import create_app  # noqa: E402

TOKEN = "editor-secret-token"


class TestLocalOnlyEditor:
    def test_hosted_mode_is_refused(self):
        with pytest.raises(ValueError, match="local-only"):
            create_app(hosted=True)


    def test_a_foreign_host_name_is_refused(self):
        """Bound to 0.0.0.0 and reached by name, the editor must still say no."""

        client = fastapi_testclient.TestClient(create_app())
        response = client.get("/api/health", headers={"Host": "editor.example.org"})
        assert response.status_code == 403
        assert "local-only" in response.text

    def test_a_remote_client_is_refused(self):
        client = fastapi_testclient.TestClient(create_app(), client=("203.0.113.5", 50000))
        response = client.get("/api/health")
        assert response.status_code == 403
        assert "local-only" in response.text


class TestCreateAppGuards:
    def test_auth_token_and_auth_dependency_are_mutually_exclusive(self):
        def _dep() -> None: ...

        with pytest.raises(ValueError, match="not both"):
            create_app(auth_token=TOKEN, auth_dependency=_dep)
