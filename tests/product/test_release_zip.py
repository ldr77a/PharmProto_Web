from __future__ import annotations

import hashlib
import json
import os
import subprocess
import zipfile
from pathlib import Path

import pytest

from tests.product.snapshot_fixtures import write_test_snapshot


ROOT = Path(__file__).resolve().parents[2]
BUILDER = ROOT / "tools" / "build-release.ps1"


def _run_builder(
    database: Path,
    manifest: Path,
    output: Path,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(BUILDER),
            "-DatabasePath",
            str(database),
            "-ManifestPath",
            str(manifest),
            "-OutputDirectory",
            str(output),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _built_zip(output: Path) -> Path:
    archives = sorted(output.glob("PharmaProto-*.zip"))
    assert len(archives) == 1
    return archives[0]


def test_release_zip_contains_only_runtime_allowlist(tmp_path):
    database, manifest = write_test_snapshot(tmp_path / "snapshot")
    output = tmp_path / "dist"

    result = _run_builder(database, manifest, output)

    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    archive = _built_zip(output)
    assert archive.name == "PharmaProto-0.2.0-fixture-snapshot.zip"
    with zipfile.ZipFile(archive) as bundle:
        names = {name.replace("\\", "/") for name in bundle.namelist()}
        required = {
            "start.bat",
            "pyproject.toml",
            "uv.lock",
            "function_seed.json",
            "README-RESEARCHER.md",
            "tools/bootstrap-runtime.ps1",
            "tools/uv-windows-x64.sha256",
            "release-data/knowledge.sqlite",
            "release-data/manifest.json",
            "generation/standard_doses.json",
        }
        assert required <= names
        for directory in ("pharma_proto/", "generation/", "gates/", "cleaning/"):
            assert any(name.startswith(directory) for name in names)
        runtime_forbidden = {
            "ingest/aliases.json",
            "schema.json",
            "ingest/unit_converter.py",
            "config/default-settings.json",
            "config/pharma.yaml",
            "tools/check-release-tree.ps1",
            "pharma_proto/cli.py",
            "pharma_proto/jsonl.py",
            "pharma_proto/legacy_interfaces.py",
            "pharma_proto/paths.py",
            "pharma_proto/settings.py",
            "pharma_proto/knowledge/exporter.py",
            "pharma_proto/knowledge/neo4j_export_source.py",
            "pharma_proto/knowledge/neo4j_repository.py",
            "generation/table_formatter.py",
            "cleaning/api_noise.py",
            "cleaning/dosage_normalizer.py",
            "cleaning/noise_filter.py",
            "cleaning/verify_base.py",
        }
        assert names.isdisjoint(runtime_forbidden)
        assert not any(name.startswith("normalization/") for name in names)
        assert not any(name.startswith("ingest/") for name in names)
        assert not any(name.startswith("legacy/") for name in names)
        forbidden = (
            ".git/",
            ".env",
            "tests/",
            "dist/",
            "__pycache__/",
            "logs/",
            "outputs/",
            ".sqlite-",
        )
        assert not any(token in name.lower() for name in names for token in forbidden)


@pytest.mark.parametrize("failure", ["hash", "integrity", "manifest"])
def test_release_builder_rejects_invalid_snapshot_without_partial_zip(tmp_path, failure):
    database, manifest = write_test_snapshot(tmp_path / "snapshot")
    if failure == "hash":
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        payload["sha256"] = "0" * 64
        manifest.write_text(json.dumps(payload), encoding="utf-8")
    elif failure == "integrity":
        database.write_bytes(b"not-a-sqlite-database")
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        payload["sha256"] = hashlib.sha256(database.read_bytes()).hexdigest()
        manifest.write_text(json.dumps(payload), encoding="utf-8")
    else:
        manifest.write_text("{}", encoding="utf-8")
    output = tmp_path / "dist"

    result = _run_builder(database, manifest, output)

    assert result.returncode != 0
    assert "RELEASE-BUILD-001" in f"{result.stdout}\n{result.stderr}"
    assert not list(output.glob("*.zip")) if output.exists() else True


def test_release_builder_preserves_previous_versioned_zip(tmp_path):
    output = tmp_path / "dist"
    first_db, first_manifest = write_test_snapshot(
        tmp_path / "first", snapshot_id="snapshot-a"
    )
    second_db, second_manifest = write_test_snapshot(
        tmp_path / "second", snapshot_id="snapshot-b"
    )

    first = _run_builder(first_db, first_manifest, output)
    second = _run_builder(second_db, second_manifest, output)

    assert first.returncode == 0, f"{first.stdout}\n{first.stderr}"
    assert second.returncode == 0, f"{second.stdout}\n{second.stderr}"
    assert {path.name for path in output.glob("*.zip")} == {
        "PharmaProto-0.2.0-snapshot-a.zip",
        "PharmaProto-0.2.0-snapshot-b.zip",
    }


def test_release_builder_supports_spaces_and_korean_paths(tmp_path):
    database, manifest = write_test_snapshot(
        tmp_path / "한글 데이터 폴더", snapshot_id="unicode-path"
    )
    output = tmp_path / "배포 파일 폴더"

    result = _run_builder(database, manifest, output)

    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    archive = _built_zip(output)
    extract_root = tmp_path / "압축 해제 폴더"
    with zipfile.ZipFile(archive) as bundle:
        bundle.extractall(extract_root)
    verify = subprocess.run(
        [
            str(ROOT / ".venv" / "Scripts" / "python.exe"),
            "-c",
            (
                "import sys; "
                "from pharma_proto.knowledge.snapshot import open_verified_snapshot; "
                "snapshot = open_verified_snapshot(sys.argv[1], sys.argv[2]); "
                "snapshot.close()"
            ),
            str(extract_root / "release-data" / "knowledge.sqlite"),
            str(extract_root / "release-data" / "manifest.json"),
        ],
        cwd=extract_root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert verify.returncode == 0, f"{verify.stdout}\n{verify.stderr}"


def test_extracted_release_starts_loopback_health_and_exits(tmp_path):
    database, manifest = write_test_snapshot(
        tmp_path / "snapshot", snapshot_id="launcher-smoke"
    )
    output = tmp_path / "dist"
    built = _run_builder(database, manifest, output)
    assert built.returncode == 0, f"{built.stdout}\n{built.stderr}"
    archive = _built_zip(output)
    extract_root = tmp_path / "Release ZIP with spaces"
    with zipfile.ZipFile(archive) as bundle:
        bundle.extractall(extract_root)

    environment = os.environ.copy()
    environment.update(
        {
            "LOCALAPPDATA": str(tmp_path / "Local App Data"),
            "PHARMA_SMOKE_EXIT_AFTER_START": "1",
            "PHARMA_NONINTERACTIVE": "1",
            "NO_PROXY": "127.0.0.1,localhost",
            "no_proxy": "127.0.0.1,localhost",
        }
    )
    result = subprocess.run(
        [
            str(ROOT / ".venv" / "Scripts" / "python.exe"),
            "-m",
            "pharma_proto.launcher",
        ],
        cwd=extract_root,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=15,
    )
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
