"""The API reports the package version, so a release and its API cannot disagree."""

from importlib.metadata import version

from fastapi.testclient import TestClient

from approps.api.app import app


def test_api_version_is_the_package_version():
    assert app.version == version("approps")
    assert TestClient(app).get("/api").json()["version"] == version("approps")
