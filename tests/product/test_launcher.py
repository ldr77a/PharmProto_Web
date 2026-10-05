import threading

import pytest


def test_launcher_binds_loopback_and_opens_effective_port(monkeypatch):
    calls = {}

    class FakeServer:
        effective_port = 43123

        def run(self):
            calls["ran"] = True

    monkeypatch.delenv("PHARMA_SMOKE_EXIT_AFTER_START", raising=False)
    monkeypatch.setattr(
        "pharma_proto.launcher.create_server",
        lambda app, host, port: calls.update(host=host, port=port) or FakeServer(),
    )
    monkeypatch.setattr(
        "pharma_proto.launcher.webbrowser.open",
        lambda url: calls.update(url=url),
    )

    from pharma_proto.launcher import launch

    assert launch(app=object()) == 0
    assert calls == {
        "host": "127.0.0.1",
        "port": 0,
        "url": "http://127.0.0.1:43123/",
        "ran": True,
    }


def test_launcher_smoke_hook_probes_health_closes_server_and_returns_zero(monkeypatch):
    calls = {}

    class FakeServer:
        effective_port = 43124

        def run(self):
            calls["ran"] = True

        def close(self):
            calls["closed"] = True

    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def read(self):
            return b'{"status":"ok"}'

    monkeypatch.setenv("PHARMA_SMOKE_EXIT_AFTER_START", "1")
    monkeypatch.setattr(
        "pharma_proto.launcher.create_server",
        lambda app, host, port: calls.update(host=host, port=port) or FakeServer(),
    )
    class FakeConnection:
        def __init__(self, host, port, timeout):
            calls.update(probe_host=host, probe_port=port, timeout=timeout)

        def request(self, method, target):
            calls.update(method=method, target=target)

        def getresponse(self):
            return FakeResponse()

        def close(self):
            calls["probe_closed"] = True

    monkeypatch.setattr("pharma_proto.launcher.HTTPConnection", FakeConnection)
    monkeypatch.setattr(
        "pharma_proto.launcher.webbrowser.open",
        lambda url: calls.update(browser=url),
    )

    from pharma_proto.launcher import launch

    assert launch(app=object()) == 0
    assert calls == {
        "host": "127.0.0.1",
        "port": 0,
        "ran": True,
        "probe_host": "127.0.0.1",
        "probe_port": 43124,
        "timeout": 0.5,
        "method": "GET",
        "target": "/health",
        "probe_closed": True,
        "closed": True,
    }


def test_loopback_probe_uses_direct_connection_even_when_proxy_is_configured(monkeypatch):
    calls = {}

    class FakeResponse:
        status = 200

        def read(self):
            return b'{"status":"ok"}'

    class FakeConnection:
        def __init__(self, host, port, timeout):
            calls.update(host=host, port=port, timeout=timeout)

        def request(self, method, target):
            calls.update(method=method, target=target)

        def getresponse(self):
            return FakeResponse()

        def close(self):
            calls["closed"] = True

    monkeypatch.setenv("HTTP_PROXY", "http://proxy.invalid:8080")
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.invalid:8080")
    monkeypatch.setattr("pharma_proto.launcher.HTTPConnection", FakeConnection)

    from pharma_proto.launcher import _probe_health

    _probe_health(43126)

    assert calls == {
        "host": "127.0.0.1",
        "port": 43126,
        "timeout": 0.5,
        "method": "GET",
        "target": "/health",
        "closed": True,
    }


def test_smoke_shutdown_stops_single_socket_dispatcher_after_closing_listener(monkeypatch):
    calls = []

    class FakeDispatcher:
        def shutdown(self):
            calls.append("dispatcher.shutdown")

    class FakeServer:
        effective_port = 43127
        task_dispatcher = FakeDispatcher()

        def run(self):
            calls.append("run")

        def close(self):
            calls.append("close")

    monkeypatch.setattr("pharma_proto.launcher._probe_health", lambda port: calls.append("probe"))

    from pharma_proto.launcher import _run_smoke_server

    assert _run_smoke_server(FakeServer()) == 0
    assert calls == ["run", "probe", "close", "dispatcher.shutdown"]


def test_smoke_shutdown_does_not_double_stop_a_multi_socket_dispatcher(monkeypatch):
    calls = []

    class FakeDispatcher:
        def shutdown(self):
            calls.append("dispatcher.shutdown")

    class FakeMultiSocketServer:
        effective_port = 43128
        task_dispatcher = FakeDispatcher()

        def run(self):
            calls.append("run")

        def close(self):
            calls.extend(("close", "dispatcher.shutdown"))

    monkeypatch.setattr("pharma_proto.launcher.MultiSocketServer", FakeMultiSocketServer)
    monkeypatch.setattr("pharma_proto.launcher._probe_health", lambda port: calls.append("probe"))

    from pharma_proto.launcher import _run_smoke_server

    assert _run_smoke_server(FakeMultiSocketServer()) == 0
    assert calls == ["run", "probe", "close", "dispatcher.shutdown"]


def test_smoke_shutdown_fails_when_the_server_thread_remains_alive(monkeypatch):
    release_thread = threading.Event()
    thread_finished = threading.Event()

    class FakeServer:
        effective_port = 43129

        def run(self):
            release_thread.wait()
            thread_finished.set()

        def close(self):
            pass

    monkeypatch.setattr("pharma_proto.launcher._probe_health", lambda port: None)
    monkeypatch.setattr("pharma_proto.launcher._SMOKE_STARTUP_TIMEOUT_SECONDS", 0.01)

    from pharma_proto.launcher import _run_smoke_server

    try:
        with pytest.raises(RuntimeError, match="did not stop cleanly"):
            _run_smoke_server(FakeServer())
    finally:
        release_thread.set()
    assert thread_finished.wait(timeout=1)


def test_launcher_main_redacts_runtime_shutdown_failure(monkeypatch, capsys):
    monkeypatch.setattr(
        "pharma_proto.launcher.launch",
        lambda: (_ for _ in ()).throw(RuntimeError("private failure detail")),
    )

    from pharma_proto.launcher import main

    assert main() == 1
    captured = capsys.readouterr()
    assert "APP-START-001" in captured.err
    assert "private failure detail" not in captured.err


def test_launcher_main_prints_the_specific_app_error_code(monkeypatch, capsys):
    from pharma_proto.errors import DB_INTEGRITY_ERROR, AppError

    monkeypatch.setattr(
        "pharma_proto.launcher.launch",
        lambda: (_ for _ in ()).throw(AppError(DB_INTEGRITY_ERROR)),
    )

    from pharma_proto.launcher import main

    assert main() == 1
    assert capsys.readouterr().err.strip() == DB_INTEGRITY_ERROR   # APP-START-001 로 뭉개지 않는다


def test_only_the_exact_smoke_value_changes_normal_launcher_behavior(monkeypatch):
    calls = {}

    class FakeServer:
        effective_port = 43125

        def run(self):
            calls["ran"] = True

    monkeypatch.setenv("PHARMA_SMOKE_EXIT_AFTER_START", "true")
    monkeypatch.setattr(
        "pharma_proto.launcher.create_server",
        lambda app, host, port: calls.update(host=host, port=port) or FakeServer(),
    )
    monkeypatch.setattr(
        "pharma_proto.launcher.webbrowser.open",
        lambda url: calls.update(url=url),
    )

    from pharma_proto.launcher import launch

    assert launch(app=object()) == 0
    assert calls["ran"] is True
    assert calls["url"] == "http://127.0.0.1:43125/"


def test_launcher_reuses_healthy_existing_instance_without_creating_server(
    monkeypatch, tmp_path
):
    calls = {}
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(
        "pharma_proto.launcher.InstanceLock.acquire",
        lambda path: (_ for _ in ()).throw(
            __import__("pharma_proto.instance_lock", fromlist=["InstanceAlreadyRunning"])
            .InstanceAlreadyRunning()
        ),
    )
    monkeypatch.setattr(
        "pharma_proto.launcher.InstanceLock.read_state",
        lambda path: {"pid": 123, "port": 43130},
    )
    monkeypatch.setattr(
        "pharma_proto.launcher._probe_health",
        lambda port: calls.update(probed=port),
    )
    monkeypatch.setattr(
        "pharma_proto.launcher.webbrowser.open",
        lambda url: calls.update(url=url),
    )
    monkeypatch.setattr(
        "pharma_proto.launcher.create_server",
        lambda *args, **kwargs: calls.update(created=True),
    )

    from pharma_proto.launcher import launch

    assert launch() == 0
    assert calls == {"probed": 43130, "url": "http://127.0.0.1:43130/"}


def test_launcher_releases_resources_and_instance_lock(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    class FakeLock:
        def write_state(self, *, pid, port):
            calls.append(("state", pid, port))

        def release(self):
            calls.append("release")

    class FakeServer:
        effective_port = 43131

        def run(self):
            calls.append("run")

    monkeypatch.delenv("PHARMA_SMOKE_EXIT_AFTER_START", raising=False)
    monkeypatch.setattr(
        "pharma_proto.launcher.InstanceLock.acquire", lambda path: FakeLock()
    )
    monkeypatch.setattr(
        "pharma_proto.launcher.create_server",
        lambda app, host, port: FakeServer(),
    )
    monkeypatch.setattr(
        "pharma_proto.launcher.webbrowser.open", lambda url: calls.append(("url", url))
    )
    monkeypatch.setattr(
        "pharma_proto.launcher.shutdown_app_resources",
        lambda app: calls.append("shutdown"),
    )
    monkeypatch.setattr("pharma_proto.launcher.create_app", lambda: object())

    from pharma_proto.launcher import launch

    assert launch() == 0
    assert "run" in calls
    assert "shutdown" in calls
    assert "release" in calls
    assert calls.index("shutdown") < calls.index("release")
