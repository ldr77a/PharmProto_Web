import json
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]


def _secret_assignment() -> str:
    return "API" + "_KEY=" + "abcdefghijklmnopqrstuvwxyz\n"


def _run_release_audit(path: Path, *, staged: bool = False) -> subprocess.CompletedProcess[str]:
    command = [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(ROOT / "tools" / "check-release-tree.ps1"),
        "-Path",
        str(path),
    ]
    if staged:
        command.append("-Staged")
    return subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")


def _initialize_git_repository(path: Path) -> None:
    for command in (
        ["git", "init", "-q"],
        ["git", "config", "user.email", "test@example.invalid"],
        ["git", "config", "user.name", "Release audit test"],
    ):
        subprocess.run(command, cwd=path, check=True)


def _tracked_files() -> set[str]:
    result = subprocess.run(
        ["git", "-c", "core.excludesFile=.git/info/exclude", "ls-files"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return set(result.stdout.splitlines())


def test_checked_in_baseline_contains_runtime_and_reference_assets():
    tracked = _tracked_files()
    # 앱 저장소 기준: ingest/normalization/schema.json 은 DB 저장소(Pharma_Proto) 소유라 여기엔 없다.
    required = {
        "pharma_proto/app.py",
        "generation/generation_loop.py",
        "generation/standard_doses.json",
        "function_seed.json",
        "release-data/manifest.json",
        "tools/build-release.ps1",
    }
    required.update(path.relative_to(ROOT).as_posix() for path in (ROOT / "gates").glob("*.py"))
    assert required <= tracked


@pytest.mark.parametrize(
    "forbidden",
    [
        "/__pycache__/",
        ".codex/",
        ".pytest_tmp_",
        "outputs/",
        ".env",
        ".sqlite-",
        ".db",
    ],
)
# 앱 저장소 정책: release-data/knowledge.sqlite 는 git LFS 로 추적한다.
# 그래서 DB 저장소에서 금지하던 ".sqlite" 는 여기서는 검사하지 않는다(사용자 매뉴얼은 README.md 로 옮겼다).
def test_checked_in_baseline_excludes_generated_sensitive_and_database_files(forbidden):
    assert not any(forbidden in f"/{path.lower()}" for path in _tracked_files())


def test_release_tree_audit_rejects_a_real_secret_shaped_file(tmp_path):
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    (fixture / "settings.txt").write_text(_secret_assignment(), encoding="utf-8")
    result = _run_release_audit(fixture)
    assert result.returncode != 0
    assert "settings.txt" in f"{result.stdout}\n{result.stderr}"


def test_staged_audit_reads_the_index_not_the_cleaned_working_tree(tmp_path):
    repository = tmp_path / "repository"
    repository.mkdir()
    _initialize_git_repository(repository)
    release_file = repository / "settings.txt"
    release_file.write_text(_secret_assignment(), encoding="utf-8")
    subprocess.run(["git", "add", "settings.txt"], cwd=repository, check=True)
    release_file.write_text("setting=clean\n", encoding="utf-8")

    result = _run_release_audit(repository, staged=True)

    assert result.returncode != 0
    assert "settings.txt" in f"{result.stdout}\n{result.stderr}"


def test_staged_audit_rejects_secret_in_a_unicode_path(tmp_path):
    repository = tmp_path / "repository"
    repository.mkdir()
    _initialize_git_repository(repository)
    filename = "자료/비밀 설정.txt"
    release_file = repository / filename
    release_file.parent.mkdir()
    release_file.write_text(_secret_assignment(), encoding="utf-8")
    subprocess.run(["git", "add", filename], cwd=repository, check=True)

    result = _run_release_audit(repository, staged=True)

    assert result.returncode != 0
    assert "Secret-shaped content:" in f"{result.stdout}\n{result.stderr}"


def test_release_tree_audit_scans_large_approved_text_files(tmp_path):
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    (fixture / "large.txt").write_text(
        "x" * (10 * 1024 * 1024 + 1) + "\n" + _secret_assignment(),
        encoding="utf-8",
    )

    result = _run_release_audit(fixture)

    assert result.returncode != 0
    assert "large.txt" in f"{result.stdout}\n{result.stderr}"


def test_release_tree_audit_rejects_json_secret_shape(tmp_path):
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    (fixture / "settings.json").write_text(
        json.dumps({"api" + "_key": "abcdefghijklmnopqrstuvwxyz"}) + "\n", encoding="utf-8"
    )

    result = _run_release_audit(fixture)

    assert result.returncode != 0
    assert "settings.json" in f"{result.stdout}\n{result.stderr}"


def test_release_tree_audit_allows_source_attribute_references(tmp_path):
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    (fixture / "settings.py").write_text(
        "def configure(self, api_key: str | None = None):\n    params = {\"api_key\": self.api_key}\n",
        encoding="utf-8",
    )

    result = _run_release_audit(fixture)

    assert result.returncode == 0
