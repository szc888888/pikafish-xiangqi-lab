"""Manage local API/Vite process groups using only the Python standard library."""

import argparse
from dataclasses import dataclass
import fcntl
import json
import os
from pathlib import Path
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
HTTP = urllib.request.build_opener(urllib.request.ProxyHandler({}))


@dataclass
class Service:
    name: str
    command: list[str]
    cwd: Path
    port: int
    path: str

    @property
    def url(self):
        return f"http://127.0.0.1:{self.port}{self.path}"


def port_in_use(port):
    with socket.socket() as sock:
        sock.settimeout(.2)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def healthy(service):
    try:
        with HTTP.open(service.url, timeout=1) as response:
            if not 200 <= response.status < 300:
                return False
            return service.name != "api" or json.load(response).get("api_ready") is True
    except (OSError, ValueError, urllib.error.URLError):
        return False


def process_started(pid):
    result = subprocess.run(["ps", "-p", str(pid), "-o", "lstart="], capture_output=True, text=True)
    return result.stdout.strip()


def state_path(service, logs):
    return logs / f"{service.name}-macos.json"


def owned_pid(service, logs):
    path = state_path(service, logs)
    if not path.exists():
        return None
    try:
        state = json.loads(path.read_text())
        pid = state["pid"]
        if isinstance(pid, int) and pid > 1 and state["started"] and process_started(pid) == state["started"] and os.getpgid(pid) == pid:
            return pid
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


def group_running(pgid):
    # A leader can exit before Vite or Pikafish. Ignore zombies, which cannot
    # hold ports; they will be reaped by their parent or the OS.
    result = subprocess.run(["ps", "-axo", "pgid=,stat="], capture_output=True, text=True, check=True)
    return any(int(parts[0]) == pgid and not parts[1].startswith("Z")
               for line in result.stdout.splitlines() if len(parts := line.split()) == 2)


def terminate_group(pid, timeout=10):
    try:
        os.killpg(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    deadline = time.monotonic() + timeout
    while group_running(pid) and time.monotonic() < deadline:
        time.sleep(.1)
    if group_running(pid):
        print(f"[launcher] process group {pid} still running; sending SIGKILL")
        os.killpg(pid, signal.SIGKILL)
        deadline = time.monotonic() + 2
        while group_running(pid) and time.monotonic() < deadline:
            time.sleep(.1)
        if group_running(pid):
            raise RuntimeError(f"Process group {pid} did not stop; ownership record retained")
    try:
        os.waitpid(pid, os.WNOHANG)
    except ChildProcessError:
        pass


def stop_service(service, logs, timeout=10):
    pid = owned_pid(service, logs)
    if pid:
        print(f"[launcher] stopping {service.name} (PID {pid})")
        terminate_group(pid, timeout)
    elif state_path(service, logs).exists():
        try:
            previous_pid = json.loads(state_path(service, logs).read_text())["pid"]
        except (OSError, ValueError, KeyError, TypeError):
            previous_pid = None
        if isinstance(previous_pid, int) and previous_pid > 1 and not process_started(previous_pid) and group_running(previous_pid):
            # Without the leader's identity we cannot safely claim this group.
            raise RuntimeError(f"{service.name} leader exited but process group {previous_pid} remains; inspect it manually. Ownership record retained: {state_path(service, logs)}")
    state_path(service, logs).unlink(missing_ok=True)


def start_service(service, logs, timeout=30):
    pid = owned_pid(service, logs)
    if pid:
        if healthy(service):
            print(f"[launcher] reusing {service.name} (PID {pid})")
            return False
        raise RuntimeError(f"Managed {service.name} is not healthy; use --restart")
    if port_in_use(service.port):
        raise RuntimeError(f"Port {service.port} is occupied by an unmanaged service; stop it before retrying")
    logs.mkdir(parents=True, exist_ok=True)
    log_path = logs / f"{service.name}-macos.log"
    # Bound retained history at each launch, without truncating an active log.
    if log_path.exists() and log_path.stat().st_size > 5 * 1024 * 1024:
        log_path.replace(log_path.with_suffix(".log.1"))
    print(f"[launcher] starting {service.name}; log: {log_path}")
    with log_path.open("ab") as log:
        child = subprocess.Popen(service.command, cwd=service.cwd, stdin=subprocess.DEVNULL,
                                 stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    try:
        state_path(service, logs).write_text(json.dumps({"pid": child.pid, "started": process_started(child.pid)}))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if child.poll() is not None:
                raise RuntimeError(f"{service.name} exited with code {child.returncode}")
            if healthy(service):
                print(f"[launcher] ready: {service.url}")
                return True
            time.sleep(.1)
        raise RuntimeError(f"{service.name} not ready after {timeout}s")
    except BaseException as exc:
        terminate_group(child.pid)
        child.wait(timeout=2)
        state_path(service, logs).unlink(missing_ok=True)
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
        tail = "\n".join(log_path.read_text(errors="replace").splitlines()[-40:])
        raise RuntimeError(f"{exc}\nRecent output ({log_path}):\n{tail}") from exc


def main():
    parser = argparse.ArgumentParser(description="macOS 本机开发服务：默认启动，复用已管理的健康进程。")
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--dry-run", action="store_true", help="显示命令，不创建文件或启动服务")
    actions.add_argument("--stop", action="store_true", help="仅停止此脚本管理的服务和子进程")
    actions.add_argument("--restart", action="store_true", help="停止此脚本管理的服务后重新启动")
    args = parser.parse_args()
    python = ROOT / "apps/api/.venv/bin/python"
    npm = shutil.which("npm") or "npm"
    services = [
        Service("api", [str(python), "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000", "--workers", "1"], ROOT / "apps/api", 8000, "/api/health"),
        Service("web", [npm, "run", "dev", "--", "--strictPort"], ROOT / "apps/web", 1239, "/"),
    ]
    if args.dry_run:
        for service in services:
            print(f"{service.name}: {service.url}\n  cwd: {service.cwd}\n  {shlex.join(service.command)}")
        return
    logs = ROOT / "logs"
    if args.stop and not logs.exists():
        print("没有此脚本管理的服务。")
        return
    if not args.stop:
        if not python.exists():
            raise RuntimeError("请先创建后端环境：python3.11 -m venv apps/api/.venv\n然后执行：apps/api/.venv/bin/python -m pip install -r apps/api/requirements.txt")
        check = subprocess.run([str(python), "-c", "import sys; assert sys.version_info >= (3, 11); import uvicorn, fastapi, sqlalchemy, alembic, dotenv"], capture_output=True)
        if check.returncode:
            raise RuntimeError("后端依赖或 Python 版本不满足要求；请使用 Python 3.11+ 创建虚拟环境并安装 apps/api/requirements.txt")
        if not shutil.which("npm") or not (ROOT / "apps/web/node_modules/.bin/vite").exists():
            raise RuntimeError("请安装 Node.js/npm，然后执行：cd apps/web && npm install")
    logs.mkdir(exist_ok=True)
    # Serialize invocations so a double click cannot start two engine owners.
    with (logs / "macos-launcher.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("另一个启动/停止操作正在进行，请稍后重试") from None
        if args.stop or args.restart:
            for service in reversed(services):
                stop_service(service, logs)
        if args.stop:
            print("已停止此脚本管理的服务。")
            return
        started = []
        try:
            for service in services:
                if start_service(service, logs):
                    started.append(service)
        except BaseException:
            for service in reversed(started):
                stop_service(service, logs)
            raise
    print("服务已启动：http://127.0.0.1:1239/\n停止：./start.sh --stop；重启：./start.sh --restart")
    with HTTP.open(services[0].url, timeout=2) as response:
        health = json.load(response)
    if not health.get("engine_ready"):
        print("Pikafish 未就绪；请检查 .env 中的 PIKAFISH_PATH、PIKAFISH_EVAL_FILE 和 API 日志。")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError) as error:
        print(f"[launcher] {error}", file=sys.stderr)
        sys.exit(1)
