"""Waitress lifecycle management for the local loopback web server."""

import json
import os
import threading
import time
import webbrowser
from http.client import HTTPConnection, HTTPException
from typing import Any

from waitress import create_server
from waitress.server import MultiSocketServer

from .app import create_app, shutdown_app_resources
from .errors import APP_ALREADY_RUNNING_ERROR, APP_START_ERROR, AppError
from .instance_lock import InstanceAlreadyRunning, InstanceLock

_HOST = "127.0.0.1"
_SMOKE_ENVIRONMENT_VALUE = "1"
_SMOKE_REQUEST_TIMEOUT_SECONDS = 0.5
_SMOKE_STARTUP_TIMEOUT_SECONDS = 5.0


def _health_url(port: int) -> str:
    return f"http://{_HOST}:{port}/health"


def _probe_health(port: int) -> None:
    deadline = time.monotonic() + _SMOKE_STARTUP_TIMEOUT_SECONDS
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            connection = HTTPConnection(_HOST, port, timeout=_SMOKE_REQUEST_TIMEOUT_SECONDS)
            try:
                connection.request("GET", "/health")
                response = connection.getresponse()
                payload = json.loads(response.read())
                if response.status == 200 and payload.get("status") == "ok":
                    return
                raise RuntimeError("Loopback health endpoint returned an unexpected response")
            finally:
                connection.close()
        except (HTTPException, OSError, RuntimeError, ValueError) as error:
            last_error = error
            time.sleep(0.05)
    raise RuntimeError("Loopback health endpoint did not become ready") from last_error


def _close_smoke_server(server: Any) -> None:
    server.close()
    if isinstance(server, MultiSocketServer):
        return
    dispatcher = getattr(server, "task_dispatcher", None)
    shutdown = getattr(dispatcher, "shutdown", None)
    if callable(shutdown):
        shutdown()


def _run_smoke_server(server: Any) -> int:
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        _probe_health(server.effective_port)
    finally:
        _close_smoke_server(server)
        thread.join(timeout=_SMOKE_STARTUP_TIMEOUT_SECONDS)
        if thread.is_alive():
            raise RuntimeError("Loopback server did not stop cleanly")
    return 0


def launch(app: Any | None = None) -> int:
    """Bind Waitress to a dynamic loopback port and open that exact URL."""
    owned_application = app is None
    lock: InstanceLock | None = None
    application = app
    if owned_application:
        local = os.environ.get("LOCALAPPDATA")
        if not local:
            raise AppError(APP_START_ERROR)
        lock_path = os.path.join(local, "PharmaProto", "runtime", "instance.lock")
        try:
            lock = InstanceLock.acquire(lock_path)
        except InstanceAlreadyRunning:
            state = InstanceLock.read_state(lock_path)
            if state is None:
                raise AppError(APP_ALREADY_RUNNING_ERROR) from None
            try:
                _probe_health(state["port"])
            except RuntimeError:
                raise AppError(APP_ALREADY_RUNNING_ERROR) from None
            webbrowser.open(f"http://{_HOST}:{state['port']}/")
            return 0

    try:
        if application is None:
            application = create_app()
        server = create_server(application, host=_HOST, port=0)
        if lock is not None:
            lock.write_state(pid=os.getpid(), port=server.effective_port)
        if os.environ.get("PHARMA_SMOKE_EXIT_AFTER_START") == _SMOKE_ENVIRONMENT_VALUE:
            return _run_smoke_server(server)

        webbrowser.open(f"http://{_HOST}:{server.effective_port}/")
        server.run()
        return 0
    finally:
        if owned_application and application is not None:
            shutdown_app_resources(application)
        if lock is not None:
            lock.release()


def main() -> int:
    try:
        return launch()
    except AppError as error:
        print(error.code, file=os.sys.stderr)   # DB-INTEGRITY-001 · DB-VERSION-001 · APP-ALREADY-RUNNING-001 그대로
        return 1
    except RuntimeError:
        print(APP_START_ERROR, file=os.sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
