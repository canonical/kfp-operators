# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

import importlib.util
import json
import threading
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

import pytest

SYNC_PATH = Path(__file__).parents[2] / "files" / "upstream" / "sync.py"
_spec = importlib.util.spec_from_file_location("sync", SYNC_PATH)
sync = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sync)

NAMESPACE = "user-ns"
SERVER_SETTINGS = {
    "visualization_server_image": "viz-image",
    "visualization_server_tag": "viz-tag",
    "frontend_image": "frontend-image",
    "frontend_tag": "frontend-tag",
    "disable_istio_sidecar": True,
    "minio_access_key": "access",
    "minio_secret_key": "secret",
    "minio_host": "minio",
    "minio_namespace": "kubeflow",
    "minio_port": "9000",
    "minio_endpoint": "minio.kubeflow:9000",
    "metadata_grpc_service_host": "mlmd.kubeflow",
    "metadata_grpc_service_port": "8080",
    "kfp_api_principal": "cluster.local/ns/kubeflow/sa/kfp-api",
    "ambient_mesh_enabled": True,
    "url": "127.0.0.1",
    "controller_port": 0,
}
EMPTY_ATTACHMENTS = {
    "Secret.v1": [],
    "ConfigMap.v1": [],
    "Deployment.apps/v1": [],
    "Service.v1": [],
    "AuthorizationPolicy.security.istio.io/v1beta1": [],
}


@pytest.fixture
def start_server():
    servers = []

    def _start(**overrides):
        server = sync.server_factory(**{**SERVER_SETTINGS, **overrides})
        threading.Thread(target=server.serve_forever, daemon=True).start()
        servers.append(server)
        return server, f"http://127.0.0.1:{server.server_address[1]}"

    yield _start
    for server in servers:
        server.shutdown()
        server.server_close()


def post_sync(url, labels):
    body = {
        "object": {"metadata": {"name": NAMESPACE, "labels": labels}},
        "attachments": EMPTY_ATTACHMENTS,
    }
    request = urllib.request.Request(
        url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(request) as response:
        return json.loads(response.read())


def get_artifact_env(attachments):
    deployment = next(
        a
        for a in attachments
        if a["kind"] == "Deployment" and a["metadata"]["name"] == "ml-pipeline-ui-artifact"
    )
    env = deployment["spec"]["template"]["spec"]["containers"][0]["env"]
    return {e["name"]: e.get("value") for e in env}


@pytest.mark.parametrize("path", ["/healthz", "/healthz?probe=1"])
def test_healthz_returns_ok(start_server, path):
    _, url = start_server()

    with urllib.request.urlopen(url + path) as response:
        assert response.status == 200
        assert response.read() == b"ok"


def test_get_unknown_path_returns_404(start_server):
    _, url = start_server()

    with pytest.raises(urllib.error.HTTPError) as err:
        urllib.request.urlopen(url + "/other")
    assert err.value.code == 404


def test_healthz_requests_are_not_logged(start_server):
    server, url = start_server()

    with patch.object(server.RequestHandlerClass, "log_message") as log_message:
        urllib.request.urlopen(url + "/healthz").close()
        log_message.assert_not_called()

        with pytest.raises(urllib.error.HTTPError):
            urllib.request.urlopen(url + "/other")
        log_message.assert_called()


def test_sync_skips_namespace_without_pipelines_label(start_server):
    _, url = start_server()

    assert post_sync(url, labels={}) == {"status": {}, "attachments": []}


@pytest.mark.parametrize("minio_ssl, expected", [(True, "true"), (False, "false")])
def test_sync_artifact_server_env(start_server, minio_ssl, expected):
    _, url = start_server(
        minio_ssl=minio_ssl,
        http_base_url="https://kubeflow.example.com",
        allowed_artifact_endpoints="https://s3.example.com",
    )

    desired = post_sync(url, labels={"pipelines.kubeflow.org/enabled": "true"})

    env = get_artifact_env(desired["attachments"])
    assert env["MINIO_SSL"] == expected
    assert env["HTTP_BASE_URL"] == "https://kubeflow.example.com"
    assert env["ALLOWED_ARTIFACT_ENDPOINTS"] == "https://s3.example.com"
    assert env["ARTIFACTS_RATE_LIMIT_DISABLED"] == "true"


def test_settings_from_env(monkeypatch):
    monkeypatch.setenv("KFP_VERSION", "2.18.0")
    monkeypatch.setenv("MINIO_ACCESS_KEY", "access")
    monkeypatch.setenv("MINIO_SECRET_KEY", "secret")
    monkeypatch.setenv("MINIO_SSL", "true")
    monkeypatch.setenv("HTTP_BASE_URL", "https://kubeflow.example.com")
    monkeypatch.setenv("ALLOWED_ARTIFACT_ENDPOINTS", "https://s3.example.com")

    settings = sync.get_settings_from_env()

    assert settings["minio_ssl"] is True
    assert settings["http_base_url"] == "https://kubeflow.example.com"
    assert settings["allowed_artifact_endpoints"] == "https://s3.example.com"


def test_settings_from_env_defaults(monkeypatch):
    monkeypatch.setenv("KFP_VERSION", "2.18.0")
    monkeypatch.setenv("MINIO_ACCESS_KEY", "access")
    monkeypatch.setenv("MINIO_SECRET_KEY", "secret")
    for var in ("MINIO_SSL", "HTTP_BASE_URL", "ALLOWED_ARTIFACT_ENDPOINTS"):
        monkeypatch.delenv(var, raising=False)

    settings = sync.get_settings_from_env()

    assert settings["minio_ssl"] is False
    assert settings["http_base_url"] == ""
    assert settings["allowed_artifact_endpoints"] == ""
