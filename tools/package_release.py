"""Explicit allowlists keep owner source out of the public introduction package."""
from pathlib import Path
import argparse
import hashlib
import json
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PUBLIC_FILES = ("README.md", "COMMERCIAL_USE.md", "INSTALL.md")
OWNER_ROOT_FILES = ("README.md", "LICENSE", "pyproject.toml", ".gitignore", "start.bat", "start.command", "launcher.py")
OWNER_DIRS = ("relay", "tests", "tools", "docs", "public", "packaging", ".github")
EXTENSIONS = {".py", ".html", ".md", ".cjs", ".json", ".txt", ".iss", ".desktop", ".yml"}


def public_package(destination, root=ROOT):
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in PUBLIC_FILES:
            file = root / "public" / name
            if file.is_symlink() or not file.resolve().is_relative_to((root / "public").resolve()):
                raise ValueError("Public files cannot be symbolic links")
            archive.write(file, "ai-run-relay/" + name)
    with zipfile.ZipFile(destination) as archive:
        assert set(archive.namelist()) == {"ai-run-relay/" + f for f in PUBLIC_FILES}


def owner_package(destination, root=ROOT):
    paths = [root / f for f in OWNER_ROOT_FILES]
    for directory in OWNER_DIRS:
        paths.extend(p for p in (root / directory).rglob("*")
                     if p.is_file() and p.suffix in EXTENSIONS and "__pycache__" not in p.parts)
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(paths):
            if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
                raise ValueError("Owner package cannot include external symbolic links")
            archive.write(path, str(Path("ai-run-relay") / path.relative_to(root)))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=ROOT / "release")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    version = (ROOT / "relay" / "__init__.py").read_text().split('__version__ = "')[1].split('"')[0]
    owner = args.out / f"AI-Run-Relay-v{version}-SOURCE.zip"
    public = args.out / f"AI-Run-Relay-v{version}-PUBLIC-INTRO.zip"
    owner_package(owner)
    public_package(public)
    manifest = {p.name: {"bytes": p.stat().st_size, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
                for p in (owner, public)}
    (args.out / "SHA256SUMS.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
