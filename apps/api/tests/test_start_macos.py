"""Exercise the macOS launcher without touching the developer's services."""

import importlib.util
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[3]
pytestmark = pytest.mark.skipif(os.name != "posix", reason="macOS launcher requires POSIX process groups and Bash")


def test_dry_run_from_another_directory_has_no_side_effects(tmp_path):
    project = tmp_path / "project with spaces"
    project.mkdir()
    if (ROOT / "start.sh").exists():
        shutil.copy(ROOT / "start.sh", project)
        shutil.copytree(ROOT / "scripts", project / "scripts")
    result = subprocess.run(
        ["bash", str(project / "start.sh"), "--dry-run"],
        cwd=tmp_path, capture_output=True, text=True,
        env={**os.environ, "PYTHON": sys.executable},
    )
    assert result.returncode == 0, result.stderr
    assert "--workers 1" in result.stdout
    assert "--strictPort" in result.stdout
    assert "127.0.0.1:1239" in result.stdout
    assert not (project / "logs").exists()
    assert not (project / "apps").exists()


@pytest.fixture
def launcher():
    spec = importlib.util.spec_from_file_location("start_macos", ROOT / "scripts/start_macos.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def service(launcher, tmp_path):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    worker = tmp_path / "server.py"
    worker.write_text(
        "from http.server import HTTPServer, BaseHTTPRequestHandler\n"
        "import sys\n"
        "class Handler(BaseHTTPRequestHandler):\n"
        " def do_GET(self):\n"
        "  self.send_response(200); self.end_headers(); self.wfile.write(b'ok')\n"
        "HTTPServer(('127.0.0.1', int(sys.argv[1])), Handler).serve_forever()\n"
    )
    item = launcher.Service("test", [sys.executable, str(worker), str(port)], tmp_path, port, "/")
    yield item
    launcher.stop_service(item, tmp_path)


def test_start_reuses_owned_service_and_stop_releases_port(launcher, service, tmp_path):
    assert launcher.start_service(service, tmp_path, timeout=5)
    first = json.loads((tmp_path / "test-macos.json").read_text())
    assert launcher.healthy(service)
    assert not launcher.start_service(service, tmp_path, timeout=5)
    assert json.loads((tmp_path / "test-macos.json").read_text()) == first
    launcher.stop_service(service, tmp_path)
    assert not launcher.port_in_use(service.port)
    assert not (tmp_path / "test-macos.json").exists()


def test_start_refuses_occupied_port_without_killing_owner(launcher, service, tmp_path):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", service.port))
        sock.listen()
        with pytest.raises(RuntimeError, match="occupied"):
            launcher.start_service(service, tmp_path, timeout=1)
        assert sock.getsockname()[1] == service.port
    assert not (tmp_path / "test-macos.json").exists()


def test_failed_start_cleans_process_and_state(launcher, service, tmp_path):
    service.command = [sys.executable, "-c", "import sys; print('startup failed', flush=True); sys.exit(7)"]
    with pytest.raises(RuntimeError, match="startup failed"):
        launcher.start_service(service, tmp_path, timeout=2)
    assert not (tmp_path / "test-macos.json").exists()
    assert not launcher.port_in_use(service.port)


def test_stop_ignores_stale_pid_record(launcher, service, tmp_path):
    sleeper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"], start_new_session=True)
    try:
        (tmp_path / "test-macos.json").write_text(json.dumps({"pid": sleeper.pid, "started": "stale"}))
        launcher.stop_service(service, tmp_path)
        assert sleeper.poll() is None
    finally:
        sleeper.terminate()
        sleeper.wait(timeout=5)


def test_unhealthy_service_times_out_and_is_cleaned(launcher, service, tmp_path):
    service.command = [sys.executable, "-c", "import time; time.sleep(30)"]
    with pytest.raises(RuntimeError, match="not ready"):
        launcher.start_service(service, tmp_path, timeout=.2)
    assert not (tmp_path / "test-macos.json").exists()


def test_stop_terminates_descendant_that_ignores_sigterm(launcher, service, tmp_path):
    child = tmp_path / "child.py"
    child.write_text(
        "import signal\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "exec(open('server.py').read())\n"
    )
    parent = tmp_path / "parent.py"
    parent.write_text(
        "import subprocess, sys, time\n"
        "subprocess.Popen([sys.executable, 'child.py', sys.argv[1]])\n"
        "time.sleep(30)\n"
    )
    service.command = [sys.executable, str(parent), str(service.port)]
    launcher.start_service(service, tmp_path, timeout=5)
    launcher.stop_service(service, tmp_path, timeout=.2)
    assert not launcher.port_in_use(service.port)
    assert not (tmp_path / "test-macos.json").exists()


def test_stop_reports_orphaned_group_and_keeps_record(launcher, service, tmp_path):
    parent = tmp_path / "parent.py"
    parent.write_text(
        "import subprocess, sys, time\n"
        "subprocess.Popen([sys.executable, 'server.py', sys.argv[1]])\n"
        "time.sleep(30)\n"
    )
    service.command = [sys.executable, str(parent), str(service.port)]
    launcher.start_service(service, tmp_path, timeout=5)
    state = tmp_path / "test-macos.json"
    pid = json.loads(state.read_text())["pid"]
    try:
        os.kill(pid, signal.SIGTERM)
        os.waitpid(pid, 0)
        with pytest.raises(RuntimeError, match="leader exited"):
            launcher.stop_service(service, tmp_path)
        assert state.exists()
        assert launcher.port_in_use(service.port)
    finally:
        # These processes were created by this test, so their group is known.
        launcher.terminate_group(pid, timeout=.2)
        state.unlink(missing_ok=True)
