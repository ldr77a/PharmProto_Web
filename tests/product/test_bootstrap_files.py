import os
import shutil
import subprocess
from pathlib import Path

import pytest
import tomllib


ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.skipif(os.name != "nt", reason="Windows batch behavior")
def test_start_bat_passes_a_valid_project_root_to_powershell(tmp_path: Path):
    shutil.copy2(ROOT / "start.bat", tmp_path / "start.bat")
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir()
    (tools_dir / "bootstrap-runtime.ps1").write_text(
        "param([string]$ProjectRoot)\n"
        "$outputPath = Join-Path (Split-Path -Parent $PSScriptRoot) 'received-root.txt'\n"
        "[System.IO.File]::WriteAllText($outputPath, $ProjectRoot)\n"
        "exit 23\n",
        encoding="utf-8",
    )

    environment = os.environ.copy()
    environment["LOCALAPPDATA"] = str(tmp_path / "local-app-data")
    environment["PHARMA_NONINTERACTIVE"] = "1"
    result = subprocess.run(
        ["cmd.exe", "/d", "/c", str(tmp_path / "start.bat")],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )

    assert result.returncode == 23
    received_root = (tmp_path / "received-root.txt").read_text(encoding="utf-8")
    assert Path(received_root).resolve() == tmp_path.resolve()


def test_start_bat_never_calls_system_python_or_pip():
    text = (ROOT / "start.bat").read_text(encoding="utf-8").lower()
    assert "bootstrap-runtime.ps1" in text
    assert "uv.exe" in text
    assert 'cd /d "%project_root%"' in text
    assert "uv_project_environment" in text
    assert text.index("uv_project_environment") < text.index("bootstrap-runtime.ps1")
    assert "python -m pharma_proto.launcher" in text
    assert "app-start-001" in text
    assert "bootstrap.log" in text
    assert "pause" in text
    assert "pip install" not in text
    assert "py -" not in text


def _batch_label_body(text: str, label: str) -> str:
    start = text.index(f"\n:{label}\n")
    end = text.find("\n:", start + 1)
    return text[start:] if end < 0 else text[start:end]


def test_start_bat_points_each_failure_at_the_log_that_explains_it():
    text = (ROOT / "start.bat").read_text(encoding="utf-8").lower()
    launcher = text.index("python -m pharma_proto.launcher")
    launcher_failure = text[launcher:].split("goto :", 1)[1].split()[0]
    bootstrap_failure = text[:launcher].rsplit("goto :", 1)[1].split()[0]

    assert launcher_failure != bootstrap_failure
    launcher_body = _batch_label_body(text, launcher_failure)
    bootstrap_body = _batch_label_body(text, bootstrap_failure)
    assert "app-start-001" in launcher_body and "logs\\app.log" in launcher_body
    assert "bootstrap.log" not in launcher_body and "network" not in launcher_body
    assert "app-start-001" in bootstrap_body and "logs\\bootstrap.log" in bootstrap_body


def test_bootstrap_pins_tool_and_python_and_verifies_sha256():
    text = (ROOT / "tools" / "bootstrap-runtime.ps1").read_text(encoding="utf-8")
    assert 'UvVersion = "0.12.0"' in text
    assert 'PythonVersion = "3.12.13"' in text
    assert "Get-FileHash" in text
    assert "uv-windows-x64.sha256" in text
    assert "--frozen" in (ROOT / "start.bat").read_text(encoding="utf-8")
    assert "--no-dev" in (ROOT / "start.bat").read_text(encoding="utf-8")
    assert "sync --frozen --no-dev" in text


def test_bootstrap_never_requests_administrator_privileges():
    batch = (ROOT / "start.bat").read_text(encoding="utf-8").lower()
    bootstrap = (ROOT / "tools" / "bootstrap-runtime.ps1").read_text(encoding="utf-8").lower()
    forbidden = ("runas", "verb runas", "start-process -verb", "net session")
    assert not any(token in batch for token in forbidden)
    assert not any(token in bootstrap for token in forbidden)


def test_researcher_runtime_excludes_build_only_neo4j_driver():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    runtime = {dependency.split("[")[0].split("=")[0].lower() for dependency in project["project"]["dependencies"]}
    admin = {dependency.split("[")[0].split("=")[0].lower() for dependency in project["project"]["optional-dependencies"]["admin"]}
    assert "neo4j" not in runtime
    assert "neo4j" in admin


def test_runtime_environment_is_pinned_under_localappdata_before_uv_runs():
    batch = (ROOT / "start.bat").read_text(encoding="utf-8").lower()
    bootstrap = (ROOT / "tools" / "bootstrap-runtime.ps1").read_text(encoding="utf-8").lower()
    for name in ("uv_project_environment", "uv_python_install_dir", "uv_cache_dir"):
        assert f'set "{name}=%localappdata%\\pharmaproto\\runtime' in batch
        assert f'$env:{name} = join-path $approot "runtime' in bootstrap
        assert bootstrap.index(f'$env:{name}') < bootstrap.index("& $uvexe --version")
        assert bootstrap.index(f'$env:{name}') < bootstrap.index("& $uvexe python install")


def test_bootstrap_records_bounded_redacted_failure_messages():
    text = (ROOT / "tools" / "bootstrap-runtime.ps1").read_text(encoding="utf-8")
    assert "bootstrap.log" in text
    assert "APP-START-001" in text
    assert "Substring(0, [Math]::Min" in text
    assert "redact" in text.lower()


def test_pytest_registers_existing_hpe6_marker():
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert '"hpe6: requires the curated HPE6 reference dataset"' in pyproject
