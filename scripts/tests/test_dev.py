"""Onboarding failures should explain recovery and never leave servers behind."""

import socket
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest

from scripts import dev


def test_pnpm_bootstrap_handles_paths_with_spaces(monkeypatch, tmp_path):
    cli = tmp_path / "npm cli.cjs"
    cli.write_text("console.log(JSON.stringify(process.argv.slice(2)))")
    monkeypatch.setenv("CONNECTSPHERE_NODE", dev.shutil.which("node"))
    monkeypatch.setenv("CONNECTSPHERE_NPM", str(cli))
    result = dev.run("pnpm", "--version", capture=True)
    assert dev.json.loads(result.stdout) == [
        "exec",
        "--yes",
        "--package=pnpm@10.15.1",
        "--",
        "pnpm",
        "--version",
    ]


def test_doctor_rejects_wrong_node_before_starting_docker(monkeypatch):
    monkeypatch.setattr(dev.shutil, "which", lambda tool: tool)
    calls = []

    def run(*args, **kwargs):
        calls.append(args)
        return SimpleNamespace(stdout="v22.19.0\n")

    monkeypatch.setattr(dev, "run", run)
    with pytest.raises(RuntimeError, match="Node 24 required"):
        dev.doctor()
    assert calls == [("node", "--version")]


def test_doctor_explains_unavailable_docker(monkeypatch):
    monkeypatch.setattr(dev.shutil, "which", lambda tool: tool)

    def run(*args, **kwargs):
        if args[0] == "docker":
            raise subprocess.CalledProcessError(1, args)
        return SimpleNamespace(stdout="v24.20.0" if args[0] == "node" else "10.15.1")

    monkeypatch.setattr(dev, "run", run)
    with pytest.raises(RuntimeError, match="Start Docker Desktop"):
        dev.doctor()


def test_dev_requires_setup_before_launch(monkeypatch, tmp_path):
    monkeypatch.setattr(dev, "ROOT", tmp_path)
    monkeypatch.setattr(sys, "argv", ["dev.py", "dev"])
    monkeypatch.chdir(tmp_path)
    with pytest.raises(RuntimeError, match="npm run setup"):
        dev.main()


def test_partial_server_start_is_cleaned_up(monkeypatch, tmp_path):
    (tmp_path / "frontend").mkdir()
    (tmp_path / ".env").touch()
    (tmp_path / "frontend/.env.local").touch()
    monkeypatch.setattr(dev, "ROOT", tmp_path)
    monkeypatch.setattr(sys, "argv", ["dev.py", "dev"])
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(dev, "command_args", lambda args: args)
    server = object()
    stopped = []

    def start(args, **kwargs):
        if args[0] == "pnpm":
            raise RuntimeError("frontend failed to launch")
        return server

    monkeypatch.setattr(dev.subprocess, "Popen", start)
    monkeypatch.setattr(dev, "stop_process", stopped.append)
    with pytest.raises(RuntimeError, match="frontend failed"):
        dev.main()
    assert stopped == [server]


def test_stop_releases_descendant_server_port(tmp_path):
    ready = tmp_path / "port.txt"
    child_code = (
        "import socket, pathlib, sys, time; "
        "sock=socket.socket(); sock.bind(('127.0.0.1', 0)); sock.listen(); "
        "pathlib.Path(sys.argv[1]).write_text(str(sock.getsockname()[1])); time.sleep(60)"
    )
    parent_code = "import subprocess, sys; subprocess.run([sys.executable, '-c', *sys.argv[1:]])"
    parent = subprocess.Popen(
        [sys.executable, "-c", parent_code, child_code, str(ready)],
        start_new_session=dev.os.name != "nt",
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if dev.os.name == "nt" else 0,
    )
    try:
        deadline = time.monotonic() + 10
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert ready.exists(), "Fixture server failed to start"
        port = int(ready.read_text())
    finally:
        dev.stop_process(parent)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", port))
