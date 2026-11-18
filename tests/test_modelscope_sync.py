from pathlib import Path

import pytest

from scripts.sync_modelscope import MANIFEST, allowed, sync


def test_only_runtime_files_are_allowed():
    assert allowed("src/bom_pilot/ui.py") and allowed("examples/ai_box_demo.xlsx")
    for name in (".env", "outputs/log.json", "README.md", "tests/test_engine.py",
                 "src/bom_pilot/__pycache__/cached.py", "src/bom_pilot/private_key.py"):
        assert not allowed(name)


def test_deploy_preserves_existing_files_and_updates_only_managed_paths(tmp_path):
    readme = tmp_path / "README.md"
    readme.write_text("Studio metadata", encoding="utf-8")
    first = {"app.py": b"original", "src/bom_pilot/obsolete.py": b"old"}
    assert sync(tmp_path, first) == 2
    assert sync(tmp_path, first) == 0
    assert sync(tmp_path, {"app.py": b"new"}) == 2
    assert readme.read_text(encoding="utf-8") == "Studio metadata"
    assert not (tmp_path / "src/bom_pilot/obsolete.py").exists()


@pytest.mark.parametrize("initial", [True, False])
def test_fail_before_writing_if_destination_has_a_conflict(tmp_path, initial):
    app = tmp_path / "app.py"
    if not initial:
        sync(tmp_path, {"app.py": b"last deployment"})
    app.write_bytes(b"ModelScope edit")
    manifest = tmp_path / MANIFEST
    original_manifest = manifest.read_bytes() if manifest.exists() else None
    with pytest.raises(ValueError, match="app.py"):
        sync(tmp_path, {"app.py": b"new app", "requirements.txt": b"other file"})
    assert app.read_bytes() == b"ModelScope edit"
    assert not (tmp_path / "requirements.txt").exists()
    assert (manifest.read_bytes() if manifest.exists() else None) == original_manifest


def test_refuses_symlinked_destination_directory(tmp_path):
    (tmp_path / "src").symlink_to(Path("/tmp"), target_is_directory=True)
    with pytest.raises(ValueError, match="Target path conflict"):
        sync(tmp_path, {"src/bom_pilot/ui.py": b"ignore"})
