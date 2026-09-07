"""Package the foundation source without local configuration or generated artifacts."""

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
PATTERNS = (
    "*.md",
    "*.json",
    "*.toml",
    "*.yaml",
    "*.lock",
    "*.ini",
    "Makefile",
    "Dockerfile",
    ".gitignore",
    ".dockerignore",
    ".env.example",
    ".nvmrc",
    ".python-version",
    ".github/**/*.yml",
    ".github/**/*.md",
    ".github/CODEOWNERS*",
    "backend/**/*.py",
    "backend/**/*.mako",
    "scripts/**/*.py",
    "scripts/*.mjs",
    "frontend/package.json",
    "frontend/tsconfig.json",
    "frontend/vite.config.ts",
    "frontend/index.html",
    "frontend/src/**/*.ts",
    "frontend/src/**/*.tsx",
    "frontend/src/**/*.css",
    "e2e/*.ts",
    "playwright.config.ts",
    "docs/**/*.md",
    "docs/infrastructure/ci-budget.json",
    "supabase/config.toml",
)


def package_source(root, destination):
    paths = sorted({path for pattern in PATTERNS for path in root.glob(pattern) if path.is_file()})
    with ZipFile(destination, "w", ZIP_DEFLATED) as archive:
        for path in paths:
            if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
                raise RuntimeError(f"Refusing source link outside workspace: {path.name}")
            archive.write(path, path.relative_to(root).as_posix())
    return len(paths)


if __name__ == "__main__":
    destination = ROOT / "artifacts/connectsphere-foundation.zip"
    destination.parent.mkdir(exist_ok=True)
    count = package_source(ROOT, destination)
    print(f"Packaged {count} source files: {destination}")
