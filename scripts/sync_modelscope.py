"""Synchronize runtime artifacts into a clean, existing ModelScope checkout."""
import argparse
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
import re
import subprocess

ROOT_FILES = {"app.py", "requirements.txt", "pyproject.toml"}
DEMO_FILES = {
    "examples/ai_box_demo.xlsx", "examples/ai_box_bom.csv",
    "examples/supplier_quotes.csv", "examples/supplier_quotes_invalid.csv",
}
MANIFEST = ".bom-pilot-deployment.json"
KEY = re.compile(rb"-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----|\b(?:sk-(?:proj-|ant-)?|gh[pousr]_|github_pat_)[A-Za-z0-9_-]{20,}\b")


def allowed(name):
    if name in ROOT_FILES or name in DEMO_FILES:
        return True
    path = PurePosixPath(name)
    return (str(path) == name and path.parts[:2] == ("src", "bom_pilot")
            and len(path.parts) >= 3 and path.suffix == ".py"
            and all(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", x) for x in (*path.parts[:-1], path.stem))
            and "__pycache__" not in path.parts
            and not re.search(r"secret|private_?key|credential", path.stem, re.I))


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args])


def source_files(root):
    desired = {}
    for entry in git(root, "ls-tree", "-rz", "HEAD").split(b"\0"):
        if not entry:
            continue
        info, raw_path = entry.split(b"\t", 1)
        name = raw_path.decode()
        if not allowed(name):
            continue
        mode, kind, oid = info.split()
        if kind != b"blob" or mode not in (b"100644", b"100755"):
            raise ValueError(f"Not a regular source file: {name}")
        data = git(root, "cat-file", "blob", oid.decode())
        if KEY.search(data):
            raise ValueError(f"Potential credential in deployment file: {name}")
        desired[name] = data
    required = ROOT_FILES | {"src/bom_pilot/__init__.py", "examples/ai_box_demo.xlsx"}
    if missing := required - desired.keys():
        raise ValueError(f"Missing deployment inputs: {', '.join(sorted(missing))}")
    return desired


def digest(data):
    return sha256(data).hexdigest() if data is not None else None


def regular_path(root, name):
    path = root
    for component in PurePosixPath(name).parts[:-1]:
        path /= component
        if path.is_symlink() or (path.exists() and not path.is_dir()):
            raise ValueError(f"Target path conflict: {name}")
    path = root / name
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise ValueError(f"Target path conflict: {name}")
    return path


def sync(target, desired):
    manifest = regular_path(target, MANIFEST)
    previous = {}
    if manifest.exists():
        saved = json.loads(manifest.read_text(encoding="utf-8"))
        if not isinstance(saved, dict) or saved.get("version") != 1 or not isinstance(saved.get("files"), dict):
            raise ValueError("Unrecognized ModelScope deployment manifest")
        previous = saved["files"]
        if any(not allowed(name) or not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value)
               for name, value in previous.items()):
            raise ValueError("Invalid ModelScope deployment manifest")
    hashes = {name: digest(content) for name, content in desired.items()}
    changes = {}
    conflicts = []
    for name in sorted(previous.keys() | desired.keys()):
        path = regular_path(target, name)
        current = digest(path.read_bytes()) if path.exists() else None
        new = hashes.get(name)
        if current == new:
            continue
        if current != previous.get(name):
            conflicts.append(name)
        else:
            changes[path] = desired.get(name)
    if conflicts:
        raise ValueError("Target files differ from the last managed version: " + ", ".join(conflicts))
    for path, content in changes.items():
        if content is None:
            path.unlink()
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
    manifest.write_text(json.dumps({"version": 1, "files": hashes}, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return len(changes)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("target", type=Path)
    args = parser.parse_args()
    try:
        if git(args.target, "status", "--porcelain", "--untracked-files=all"):
            raise ValueError("ModelScope checkout must be clean")
        count = sync(args.target, source_files(args.source))
        print(f"Prepared {count} managed file changes.")
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"ModelScope sync stopped: {exc}\n")


if __name__ == "__main__":
    main()
