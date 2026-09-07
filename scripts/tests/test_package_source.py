from zipfile import ZipFile

from scripts.package_source import package_source


def test_source_archive_excludes_local_secrets_and_generated_files(tmp_path):
    files = [
        "README.md",
        ".env.example",
        "frontend/src/App.tsx",
        "backend/app/__init__.py",
        "docs/infrastructure/ci-budget.json",
        "docs/infrastructure/tasks/INF-01.md",
        ".env",
        "frontend/.env.local",
        "frontend/dist/assets/old-demo.js",
        "backend/app/__pycache__/old.pyc",
        "playwright-report/index.html",
        "node_modules/dependency/package.json",
        ".venv/Lib/site-packages/library.py",
    ]
    for name in files:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture")
    archive = tmp_path / "handoff.zip"
    assert package_source(tmp_path, archive) == 6
    with ZipFile(archive) as contents:
        assert set(contents.namelist()) == set(files[:6])
