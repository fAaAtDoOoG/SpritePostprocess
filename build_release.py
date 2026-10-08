"""Package only portable source files, never local config or user animation data."""
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from spritepost import __version__


def main():
    root = Path(__file__).resolve().parent
    destination = root / f"SpritePostprocess-{__version__}.zip"
    paths = [root / name for name in ("spritepost.py", "gui.py", "ui_strings.py", "ui_config.py",
                                      "Start.ps1", "Start.cmd", "README.md", "README.zh-CN.md",
                                      "requirements.txt", "build_release.py", ".gitignore")]
    for folder in ("spritepost", "examples", "tests"):
        paths.extend(p for p in (root / folder).rglob("*") if p.is_file()
                     and "__pycache__" not in p.parts and p.suffix != ".pyc")
    with ZipFile(destination, "w", ZIP_DEFLATED) as archive:
        for path in sorted(paths):
            archive.write(path, (Path("SpritePostprocess") / path.relative_to(root)).as_posix())
    print(destination)


if __name__ == "__main__":
    main()
