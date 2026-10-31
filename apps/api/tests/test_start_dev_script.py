import os
import base64
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path


def test_start_script_dry_run_describes_both_services():
    root = Path(__file__).resolve().parents[3]
    script = root / "start.ps1"
    shell = shutil.which("pwsh") or shutil.which("powershell")
    assert shell, "PowerShell is required to test the Windows launcher"

    result = subprocess.run(
        [shell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", os.fspath(script), "-DryRun"],
        cwd=root,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    output = result.stdout
    assert "apps\\api" in output
    assert "apps\\web" in output
    assert "127.0.0.1:8000" in output
    assert "127.0.0.1:1239" in output
    assert "uvicorn app.main:app" in output
    assert "run dev" in output


def test_start_script_declares_process_logs_and_bounded_rollover():
    root = Path(__file__).resolve().parents[3]
    script_text = (root / "start.ps1").read_text(encoding="utf-8")

    assert "logs" in script_text
    assert "api-process.log" in script_text
    assert "web-process.log" in script_text
    assert "5 * 1024 * 1024" in script_text or "5MB" in script_text
    assert "backup" in script_text.lower()
    assert "3" in script_text
    assert "Append" in script_text or "append" in script_text
    assert "Get-Content" in script_text and "-Tail 40" in script_text
    assert "Write-ProcessLogBytes" in script_text
    assert "GetByteCount" in script_text
    assert "FileMode]::Append" in script_text


def test_start_script_only_treats_2xx_as_healthy():
    root = Path(__file__).resolve().parents[3]
    script_text = (root / "start.ps1").read_text(encoding="utf-8")

    assert "StatusCode -ge 200 -and $response.StatusCode -lt 300" in script_text
    assert "StatusCode -lt 500" not in script_text


def test_start_script_logs_lifecycle_events_without_secrets():
    root = Path(__file__).resolve().parents[3]
    script_text = (root / "start.ps1").read_text(encoding="utf-8")

    for event in (
        "log preparation",
        "API start",
        "web start",
        "health-check success",
        "startup failure",
        "launcher completion",
    ):
        assert event.lower() in script_text.lower()
    assert ".env" not in script_text
    assert "AGENT_OPENAI_API_KEY" not in script_text


def test_worker_logs_process_start_errors_and_exit_code():
    root = Path(__file__).resolve().parents[3]
    script_text = (root / "start.ps1").read_text(encoding="utf-8")

    assert "process_started" in script_text
    assert "process_error" in script_text
    assert "process_exited" in script_text
    assert "exit_code" in script_text
    assert "`$processExitCode = [int]`$LASTEXITCODE" in script_text


def test_dry_run_does_not_create_project_logs():
    root = Path(__file__).resolve().parents[3]
    script = root / "start.ps1"
    logs_dir = root / "logs"
    before = {
        path.name: (path.stat().st_size, path.stat().st_mtime_ns)
        for path in logs_dir.glob("*")
    } if logs_dir.exists() else {}
    shell = shutil.which("pwsh") or shutil.which("powershell")
    assert shell, "PowerShell is required to test the Windows launcher"

    result = subprocess.run(
        [shell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", os.fspath(script), "-DryRun"],
        cwd=root,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    after = {
        path.name: (path.stat().st_size, path.stat().st_mtime_ns)
        for path in logs_dir.glob("*")
    } if logs_dir.exists() else {}
    assert after == before


def test_worker_captures_and_rotates_oversized_output():
    root = Path(__file__).resolve().parents[3]
    script_text = (root / "start.ps1").read_text(encoding="utf-8")
    worker_match = re.search(r"\$worker = @\"\n(?P<body>.*?)\n\"@\n", script_text, re.DOTALL)
    assert worker_match, "launcher worker template is missing"
    shell = shutil.which("pwsh") or shutil.which("powershell")
    assert shell, "PowerShell is required to test the Windows launcher"

    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        child = temp / "emit.ps1"
        child.write_text(
            "[Console]::Out.Write(('o' * 6000000))\n"
            "[Console]::Out.WriteLine()\n"
            "[Console]::Error.WriteLine(('e' * 1000))\n",
            encoding="utf-8",
        )
        log_path = temp / "api-process.log"
        log_path.write_bytes(b"seed\n")
        config = {
            "Name": "test",
            "FilePath": shell,
            "Arguments": ["-NoProfile", "-File", os.fspath(child)],
            "WorkingDirectory": os.fspath(temp),
            "LogPath": os.fspath(log_path),
        }
        payload = base64.b64encode(json.dumps(config, separators=(",", ":")).encode()).decode()
        worker = worker_match.group("body").replace("`$", "$").replace("$configPayload", payload)
        worker_path = temp / "worker.ps1"
        worker_path.write_text(worker, encoding="utf-8")

        result = subprocess.run(
            [shell, "-NoProfile", "-File", os.fspath(worker_path)],
            cwd=temp,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )

        assert result.returncode == 0, result.stderr
        retained = sorted(temp.glob("api-process.log*"))
        assert retained
        assert len(retained) <= 4
        assert all(path.stat().st_size <= 5 * 1024 * 1024 for path in retained)
        ordered = [
            temp / f"api-process.log.{index}"
            for index in range(3, 0, -1)
            if (temp / f"api-process.log.{index}").exists()
        ] + [log_path]
        combined = b"".join(path.read_bytes() for path in ordered)
        assert b"seed\n" in combined
        assert b"o" * 6000000 in combined, result.stderr
        assert b"e" * 1000 in combined, result.stderr
