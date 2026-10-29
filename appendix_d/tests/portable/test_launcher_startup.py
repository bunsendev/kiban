"""Startup/control regressions without starting a listener or a native window."""

import http.client
import logging
import ssl
import subprocess
import sys
import urllib.error
import urllib.request
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from portable import APP_VERSION
from portable.launcher import main as launcher
from portable.runtime import feedback_admin, local_http, update_apply
from portable.runtime.installation import create_profile
from portable.runtime.paths import DataPaths


@pytest.fixture
def connections(monkeypatch):
    created = []

    class Connection:
        debuglevel = 0

        def __init__(self, host, port, timeout):
            self.host, self.port, self.timeout = host, port, timeout
            self.body, self.status, self.headers = b'{"active":0}', 200, {}
            self.requests, self.reads = [], []
            self.closed = False
            created.append(self)

        def set_debuglevel(self, level):
            self.debug = level

        def request(self, method, path, headers):
            self.requests.append((method, path, headers))

        def getresponse(self):
            def read(limit):
                self.reads.append(limit)
                return self.body[:limit]

            return SimpleNamespace(status=self.status, headers=self.headers, read=read)

        def close(self):
            self.closed = True

    monkeypatch.setattr(local_http.http.client, "HTTPConnection", Connection)
    return created


def test_loopback_ignores_proxy_and_global_opener_without_exposing_control_token(
    monkeypatch, connections
):
    monkeypatch.setenv("HTTP_PROXY", "http://user:secret@proxy.invalid:8000")
    monkeypatch.setenv("HTTPS_PROXY", "http://user:secret@proxy.invalid:8000")
    monkeypatch.setenv("ALL_PROXY", "http://proxy.invalid:8000")
    monkeypatch.setenv("NO_PROXY", "")
    monkeypatch.setattr(urllib.request, "proxy_bypass", lambda _: False)
    monkeypatch.setattr(urllib.request, "urlopen", lambda *_a, **_k: pytest.fail("global opener"))
    monkeypatch.setattr(urllib.request, "build_opener", lambda *_a, **_k: pytest.fail("opener"))
    assert local_http.request_json(48150, "/api/control/status", token="control-secret") == {
        "active": 0
    }
    connection = connections[0]
    assert connection.host == "127.0.0.1" and connection.port == 48150
    assert connection.requests == [
        ("GET", "/api/control/status", {"X-Portable-Control": "control-secret"})
    ]
    assert connection.closed and connection.debug == 0
    assert connection.reads == [local_http.MAX_RESPONSE_BYTES + 1]


def test_loopback_never_follows_redirect_or_forwards_token(monkeypatch, connections):
    original = local_http.http.client.HTTPConnection.getresponse

    def redirect(connection):
        connection.status = 302
        connection.headers = {"Location": "http://outside.invalid/collect"}
        return original(connection)

    monkeypatch.setattr(local_http.http.client.HTTPConnection, "getresponse", redirect)
    with pytest.raises(urllib.error.HTTPError, match="redirect refused"):
        local_http.request_json(48150, "/api/control/status", token="secret")
    assert len(connections) == 1 and connections[0].host == "127.0.0.1"
    assert len(connections[0].requests) == 1 and connections[0].closed


@pytest.mark.parametrize(
    "body", [b"[]", b"not json", b" " * 65537], ids=["array", "invalid-json", "oversized"]
)
def test_bad_local_responses_are_bounded_and_rejected(monkeypatch, connections, body):
    original = local_http.http.client.HTTPConnection.getresponse

    def result(connection):
        connection.body = body
        return original(connection)

    monkeypatch.setattr(local_http.http.client.HTTPConnection, "getresponse", result)
    with pytest.raises(ValueError):
        local_http.request_json(48150, "/ready")
    assert connections[0].closed


def test_missing_tls_initialization_reproduces_pilot54_failure_but_http_still_works(
    monkeypatch, connections
):
    def missing():
        raise FileNotFoundError(2, "synthetic missing certificate store")

    monkeypatch.setattr(ssl, "_create_default_https_context", missing)
    with pytest.raises(FileNotFoundError):
        # Exactly the old pilot.54 opener, before any HTTP connection is attempted.
        urllib.request.build_opener(urllib.request.ProxyHandler({}))
    assert local_http.request_json(48150, "/ready") == {"active": 0}
    assert len(connections) == 1 and connections[0].closed


@pytest.mark.skipif(sys.platform != "win32", reason="Windows certificate stores")
def test_missing_windows_certificate_store_does_not_affect_local_http(monkeypatch, connections):
    def missing_store(name):
        raise FileNotFoundError(2, "synthetic missing Windows certificate store")

    monkeypatch.setattr(ssl, "enum_certificates", missing_store)
    with pytest.raises(FileNotFoundError):
        urllib.request.build_opener(urllib.request.ProxyHandler({}))
    assert local_http.request_json(48150, "/ready") == {"active": 0}
    assert connections[0].closed


@pytest.mark.parametrize("status", [401, 403, 500])
def test_http_status_and_closure_are_preserved(monkeypatch, connections, status):
    original = local_http.http.client.HTTPConnection.getresponse

    def result(connection):
        connection.status = status
        return original(connection)

    monkeypatch.setattr(local_http.http.client.HTTPConnection, "getresponse", result)
    with pytest.raises(urllib.error.HTTPError) as error:
        local_http.request_json(48150, "/api/control/status", token="secret")
    assert error.value.code == status and connections[0].closed


def test_http_protocol_errors_are_normalized_and_closed(monkeypatch, connections):
    def broken(connection):
        raise http.client.BadStatusLine("synthetic-private-response")

    monkeypatch.setattr(local_http.http.client.HTTPConnection, "getresponse", broken)
    with pytest.raises(ValueError) as error:
        local_http.request_json(48150, "/ready")
    assert error.value.portable_local_phase == "HTTP_RESPONSE"
    assert connections[0].closed


def test_real_readiness_and_control_contract_work_with_tls_unavailable(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from portable.api.app import create_app

    paths = DataPaths(tmp_path / "Data")
    client = TestClient(
        create_app(paths.root, control_token="synthetic-control"), base_url="http://127.0.0.1"
    )
    calls = []

    def missing():
        raise FileNotFoundError(2, "synthetic unavailable TLS initialization")

    monkeypatch.setattr(ssl, "_create_default_https_context", missing)
    with pytest.raises(FileNotFoundError):
        urllib.request.build_opener(urllib.request.ProxyHandler({}))

    class Connection:
        def __init__(self, host, port, timeout):
            assert host == "127.0.0.1" and port == 48150

        def set_debuglevel(self, level):
            assert level == 0

        def request(self, method, path, headers):
            calls.append(path)
            self.response = client.request(method, path, headers=headers)

        def getresponse(self):
            return SimpleNamespace(
                status=self.response.status_code,
                headers=self.response.headers,
                read=lambda n: self.response.content[:n],
            )

        def close(self):
            pass

    monkeypatch.setattr(local_http.http.client, "HTTPConnection", Connection)
    monkeypatch.setattr(launcher, "available_ports", lambda: iter([48150]))
    child = Child(1)
    monkeypatch.setattr(launcher.subprocess, "Popen", lambda *a, **k: child)
    ready_child, port = launcher.start_server(
        paths, SimpleNamespace(add=lambda _: None), "synthetic-control"
    )
    assert ready_child is child and not child.terminated
    assert calls == ["/ready", "/api/control/status"]
    launcher.stop_server(child, port, "synthetic-control")
    assert child.terminated and calls[-2:] == ["/api/control/drain", "/api/control/status"]


@pytest.mark.parametrize(
    "port,path",
    [(True, "/ready"), (0, "/ready"), (48150, "//outside.invalid"), (48150, "/ready\r\nX: secret")],
)
def test_loopback_destination_is_fixed(port, path):
    with pytest.raises(ValueError):
        local_http.request_json(port, path)


class Child:
    def __init__(self, pid, code=None):
        self.pid, self.returncode = pid, code
        self.terminated = self.killed = False

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = -1

    def kill(self):
        self.killed = True
        self.returncode = -9

    def wait(self, timeout):
        return self.returncode


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    paths = DataPaths(tmp_path / "Data")
    paths.ensure()
    clock = SimpleNamespace(now=0.0)
    monkeypatch.setattr(launcher.time, "monotonic", lambda: clock.now)
    monkeypatch.setattr(
        launcher.time, "sleep", lambda seconds: setattr(clock, "now", clock.now + seconds)
    )
    monkeypatch.setattr(launcher, "available_ports", lambda: iter([48150, 48151, 48152]))
    children = []

    def spawn(*args, **kwargs):
        child = Child(100 + len(children))
        children.append(child)
        return child

    monkeypatch.setattr(launcher.subprocess, "Popen", spawn)
    job = SimpleNamespace(add=lambda _: None)
    return paths, clock, children, job


def test_failed_readiness_is_bounded_logs_stage_and_kills_child(runtime, monkeypatch, caplog):
    paths, clock, children, job = runtime
    caplog.set_level(logging.INFO, logger="portable.launcher")
    progress = []

    def denied(port, path, **kwargs):
        raise urllib.error.HTTPError(
            "http://proxy.invalid/control-secret", 403, "proxy-password", None, None
        )

    monkeypatch.setattr(launcher, "request_json", denied)
    with pytest.raises(RuntimeError, match="READY_HTTP_403"):
        launcher.start_server(paths, job, "control-secret", progress=progress.append)
    assert launcher.STARTUP_TIMEOUT <= clock.now < launcher.STARTUP_TIMEOUT + 1
    assert len(children) == 1 and children[0].terminated
    assert progress and "api_startup_timeout" in caplog.text
    for secret in ["control-secret", "proxy-password", "proxy.invalid"]:
        assert secret not in caplog.text


def test_missing_file_diagnostic_contains_phase_and_code_locations_but_no_secrets(
    runtime, monkeypatch, caplog
):
    paths, _, children, job = runtime
    caplog.set_level(logging.INFO, logger="portable.launcher")

    def failed_connection(*args, **kwargs):
        raise FileNotFoundError(2, "private-error-message", "private-secret-file")

    monkeypatch.setattr(local_http.http.client, "HTTPConnection", failed_connection)
    with pytest.raises(RuntimeError, match="READY_FileNotFoundError"):
        launcher.start_server(paths, job, "control-secret")
    assert "phase=HTTP_INIT" in caplog.text and "errno=2" in caplog.text
    assert "local_http.py:request_json" in caplog.text
    assert len(children) == 1 and children[0].terminated
    for secret in ["control-secret", "private-error-message", "private-secret-file"]:
        assert secret not in caplog.text


def test_control_auth_failure_is_distinguished(runtime, monkeypatch):
    paths, _, children, job = runtime

    def request(port, path, **kwargs):
        if path == "/ready":
            return {"ready": True, "version": APP_VERSION}
        raise urllib.error.HTTPError("synthetic", 403, "secret", None, None)

    monkeypatch.setattr(launcher, "request_json", request)
    with pytest.raises(RuntimeError, match="CONTROL_HTTP_403"):
        launcher.start_server(paths, job, "secret")
    assert len(children) == 1 and children[0].terminated


@pytest.mark.parametrize(
    "ready", [{"ready": False, "version": APP_VERSION}, {"ready": True, "version": "old-version"}]
)
def test_wrong_version_or_not_ready_never_accepted(runtime, monkeypatch, ready):
    paths, _, children, job = runtime
    calls = []

    def request(port, path, **kwargs):
        calls.append(path)
        return ready

    monkeypatch.setattr(launcher, "request_json", request)
    with pytest.raises(RuntimeError, match="READY_NOT_CURRENT"):
        launcher.start_server(paths, job, "secret")
    assert set(calls) == {"/ready"} and len(children) == 1 and children[0].terminated


def test_no_available_port_creates_no_child(runtime, monkeypatch):
    paths, _, children, job = runtime
    monkeypatch.setattr(launcher, "available_ports", lambda: iter([]))
    with pytest.raises(RuntimeError, match="NO_AVAILABLE_PORT"):
        launcher.start_server(paths, job, "secret")
    assert not children


def test_early_child_exit_can_retry_port_but_success_requires_current_authenticated_api(
    runtime, monkeypatch
):
    paths, _, children, job = runtime
    old_add = job.add

    def add(pid):
        if len(children) == 1:
            children[0].returncode = 1
        old_add(pid)

    job.add = add
    monkeypatch.setattr(
        launcher,
        "request_json",
        lambda port, path, **kwargs: (
            {"ready": True, "version": APP_VERSION} if path == "/ready" else {"active": 0}
        ),
    )
    child, port = launcher.start_server(paths, job, "secret")
    assert child == children[1] and port == 48151 and not child.terminated


def test_cancel_and_job_assignment_failure_always_cleanup(runtime, monkeypatch):
    paths, _, children, job = runtime
    messages = []
    with pytest.raises(launcher.StartupCancelled):
        launcher.start_server(
            paths, job, "secret", progress=messages.append, cancelled=lambda: len(messages) > 1
        )
    assert len(children) == 1 and children[0].terminated
    job.add = lambda _: (_ for _ in ()).throw(OSError("synthetic assignment failure"))
    with pytest.raises(OSError, match="assignment"):
        launcher.start_server(paths, job, "secret")
    assert children[-1].terminated


def test_unresponsive_child_is_killed(runtime, monkeypatch):
    child = Child(1)
    waits = []

    def wait(timeout):
        waits.append(timeout)
        if len(waits) == 1:
            raise subprocess.TimeoutExpired("fake", timeout)
        return child.returncode

    child.wait = wait
    launcher._terminate(child)
    assert child.terminated and child.killed and waits == [5, 5]


def test_duplicate_start_only_reopens_matching_data_root(runtime, monkeypatch):
    paths, _, _, _ = runtime
    create_profile(paths.root, "FIELD", "人工端末")
    expected = feedback_admin.instance_id(paths)
    monkeypatch.setattr(launcher, "PORTS", [48150, 48151])
    monkeypatch.setattr(
        launcher,
        "request_json",
        lambda port, path, **kwargs: (
            {"ready": True}
            if path == "/ready"
            else {"instance_id": expected if port == 48151 else "other-installation"}
        ),
    )
    seen = []
    monkeypatch.setattr(launcher.webbrowser, "open", lambda url: seen.append(url) or True)
    assert launcher.reopen_existing(paths)
    assert seen == ["http://127.0.0.1:48151/field"]


def test_admin_discovery_and_update_smoke_use_same_direct_transport(runtime, monkeypatch):
    paths, _, children, _ = runtime
    monkeypatch.setattr(feedback_admin, "is_admin", lambda: True)
    monkeypatch.setattr(
        feedback_admin,
        "request_json",
        lambda *a, **k: {"instance_id": feedback_admin.instance_id(paths)},
    )
    monkeypatch.setattr(feedback_admin, "issue", lambda _: "admin-secret")
    opened = []
    monkeypatch.setattr(feedback_admin.webbrowser, "open", lambda url: opened.append(url))
    assert feedback_admin.open_settings(paths.root.parent) == 0
    assert opened[0].endswith("/feedback-admin#admin-secret")
    monkeypatch.setattr(
        update_apply, "request_json", lambda *a, **k: {"ready": True, "version": APP_VERSION}
    )
    update_apply.smoke(paths.root / "fake.exe", paths.root, APP_VERSION)
    assert children[-1].terminated


def test_launcher_shows_starting_window_before_probe_and_cancel_is_clean(runtime, monkeypatch):
    paths, _, children, job = runtime
    events = []

    class Window:
        def __init__(self):
            events.append("window")

        def title(self, *_):
            pass

        def geometry(self, *_):
            pass

        def protocol(self, *_):
            pass

        def update(self):
            events.append("paint")

        def destroy(self):
            events.append("destroy")

    class Widget:
        def __init__(self, *a, **kw):
            pass

        def pack(self, **kw):
            pass

        def config(self, **kw):
            pass

    monkeypatch.setattr(launcher, "bundle_root", lambda: paths.root.parent)
    monkeypatch.setattr(launcher, "SingleInstance", lambda _: nullcontext())
    monkeypatch.setattr(launcher, "initialize_runtime", lambda *_: None)
    monkeypatch.setattr(
        launcher,
        "setup_profile",
        lambda _: {"mode": "FIELD", "terminal_name": "人工端末", "installation_id": "synthetic"},
    )
    monkeypatch.setattr(launcher.tk, "Tk", Window)
    monkeypatch.setattr(launcher.tk, "Label", Widget)
    monkeypatch.setattr(launcher.tk, "Button", Widget)
    job.close = lambda: events.append("job-closed")
    monkeypatch.setattr(launcher, "ChildJob", lambda: job)

    def start(*a, **kw):
        assert events[:2] == ["window", "paint"]
        assert kw["cancelled"]() is False
        raise launcher.StartupCancelled()

    monkeypatch.setattr(launcher, "start_server", start)
    assert launcher.launch() == 0
    assert "destroy" in events and "job-closed" in events and not children
