"""Build an AstrBot upload archive from the plugin source tree.

The generated archive contains plugin files at its root (rather than adding a
second repository directory), which is the layout expected by the AstrBot
WebUI upload flow.
"""

from __future__ import annotations

import argparse
import re
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DEFAULT_OUTPUT = ROOT / "dist" / "astrbot_plugin_math_render.zip"
EXCLUDED_NAMES = {
    ".git",
    ".codex_backups",
    ".pytest_cache",
    ".ruff_cache",
    ".tmp",
    "__pycache__",
    "data",
    "dist",
    "tests",
}
REQUIRED_FILES = {
    "_conf_schema.json",
    "CHANGELOG.md",
    "README.md",
    "metadata.yaml",
    "requirements.txt",
    "logo.png",
    "logo.svg",
}


def iter_files() -> list[Path]:
    files: set[Path] = set()
    for path in ROOT.iterdir():
        if path.name in EXCLUDED_NAMES or path.name.startswith("."):
            continue
        if path.is_file() and (path.suffix == ".py" or path.name in REQUIRED_FILES):
            files.add(path)
    missing = REQUIRED_FILES - {path.name for path in files}
    if missing:
        raise FileNotFoundError(f"Missing required plugin files: {', '.join(sorted(missing))}")
    return sorted(files, key=lambda path: path.name.lower())


def _safe_version() -> str:
    metadata = (ROOT / "metadata.yaml").read_text(encoding="utf-8")
    match = re.search(r"^version:\s*([^\s]+)", metadata, re.MULTILINE)
    return match.group(1) if match else "dev"


def build(output: Path) -> Path:
    files = iter_files()
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in files:
            archive.write(path, arcname=path.name)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="output zip path (default: dist/astrbot_plugin_math_render.zip)",
    )
    args = parser.parse_args()
    output = args.output if args.output.is_absolute() else ROOT / args.output
    if output == DEFAULT_OUTPUT:
        output = output.with_name(f"astrbot_plugin_math_render_{_safe_version()}.zip")
    print(build(output))


if __name__ == "__main__":
    main()
