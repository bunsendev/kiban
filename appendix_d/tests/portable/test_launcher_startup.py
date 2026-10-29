"""Startup/control regressions without starting a listener or a native window."""

import io
import logging
import subprocess
import urllib.error
import urllib.request
from contextlib import nullcontext
from email.message import Message
from types import SimpleNamespace
from urllib.response import addinfourl

import pytest

from portable import APP_VERSION
from portable.launcher import main as launcher
from portable.runtime import feedback_admin, local_http, update_apply
from portable.runtime.installation import create_profile
from portable.runtime.paths import DataPaths


def response(req, body, code=200, headers=None):
    value = addinfourl(io.BytesIO(body), headers or Message(), req.full_url, code)
    value.msg = "synthetic"
    return value


def test_loopback_ignores_proxy_and_global_opener_without_exposing_control_token(monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://user:secret@proxy.invalid:8000")
    monkeypatch.setenv("HTTPS_PROXY", "http://user:secret@proxy.invalid:8000")
    monkeypatch.setenv("ALL_PROXY", "http://proxy.invalid:8000")
    monkeypatch.setenv("NO_PROXY", "")
    monkeypatch.setattr(urllib.request, "proxy_bypass", lambda _: False)
    monkeypatch.setattr(urllib.request, "urlopen", lambda *_a, **_k: pytest.fail("global opener"))
    requests = []

    def http_open(_, req):
        requests.append(req)
        return response(req, b'{"active":0}')

    monkeypatch.setattr(urllib.request.HTTPHandler, "http_open", http_open)
    # Demonstrate the old default opener consults the proxy for 127.0.0.1.
    urllib.request.build_opener().open("http://127.0.0.1:48150/ready").close()
    assert requests[-1].host == "proxy.invalid:8000"
    assert local_http.request_json(48150, "/api/control/status", token="control-secret") == {
        "active": 0
    }
    assert requests[-1].host == "127.0.0.1:48150"
    assert not requests[-1].has_proxy()
    assert requests[-1].get_header("X-portable-control") == "control-secret"
    assert requests[-1].get_header("Proxy-authorization") is None


def test_loopback_never_follows_redirect_or_forwards_token(monkeypatch):
    seen = []

    def http_open(_, req):
        seen.append(req.full_url)
        headers = Message()
        headers["Location"] = "http://outside.invalid/collect"
        return response(req, b"", 302, headers)

    monkeypatch.setattr(urllib.request.HTTPHandler, "http_open", http_open)
    with pytest.raises(urllib.error.HTTPError, match="redirect refused"):
        local_http.request_json(48150, "/api/control/status", token="secret")
    assert seen == ["http://127.0.0.1:48150/api/control/status"]


@pytest.mark.parametrize(
    "body", [b"[]", b"not json", b" " * 65537], ids=["array", "invalid-json", "oversized"]
)
def test_bad_local_responses_are_bounded_and_rejected(monkeypatch, body):
    monkeypatch.setattr(urllib.request.HTTPHandler, "http_open", lambda _, req: response(req, body))
    with pytest.raises(ValueError):
        local_http.request_json(48150, "/ready")


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
