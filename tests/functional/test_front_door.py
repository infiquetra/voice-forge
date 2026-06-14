"""Front-door routing: GET / redirects to the Forge; /lab stays and links to it.

U10 — /forge becomes the front door (bare root → studio) without disturbing /lab
(KTD7: /lab stays fully intact, gains only an additive cross-link to /forge).
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from voice_forge.server import app  # noqa: E402


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


def test_root_redirects_to_forge_temporary(client: TestClient) -> None:
    """GET / issues a 307 to /forge/ (temporary — the front door must stay reroutable).

    Locking 307 (not 308): a permanent redirect would get baked into browser caches
    and be painful to undo if the front door later moves (chooser page / SPA-at-root).
    """
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code == 307
    assert resp.headers["location"] == "/forge/"


def test_root_follows_through_to_forge_200(client: TestClient) -> None:
    """Following the redirect lands on the served Forge index (final 200 at /forge/)."""
    resp = client.get("/")  # TestClient follows redirects by default
    assert resp.status_code == 200
    assert resp.request.url.path == "/forge/"


def test_lab_still_200_and_links_to_forge(client: TestClient) -> None:
    """KTD7: /lab is untouched (200) and its body now points users at /forge."""
    resp = client.get("/lab")
    assert resp.status_code == 200
    body = resp.text
    assert 'href="/forge/"' in body
    # The legacy cross-link to /demo must survive the edit to line 121.
    assert 'href="/demo"' in body
