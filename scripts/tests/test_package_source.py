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
        "LOCAL_DEVELOPER_CHEATSHEET.md",
        "scripts/local_refresh_demo.py",
    ]
    for name in files:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture")
    archive = tmp_path / "handoff.zip"
    assert package_source(tmp_path, archive) == 6
    with ZipFile(archive) as contents:
        assert set(contents.namelist()) == set(files[:6])


def test_archive_preserves_frontend_asset_and_evidence_config(tmp_path):
    files = {
        "frontend/src/style.css": "body { background: url('./assets/background.png'); }",
        "frontend/src/assets/background.png": "image fixture",
        "playwright.config.ts": "export default {};",
        "playwright.evidence.config.ts": "import config from './playwright.config';",
        ".agents/skills/qa/SKILL.md": "QA instructions",
        "docs/design/moodboard/operations-atlas.png": "design fixture",
    }
    for name, text in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    archive = tmp_path / "submission.zip"
    package_source(tmp_path, archive)
    with ZipFile(archive) as contents:
        contents.extractall(tmp_path / "extracted")
    extracted = tmp_path / "extracted"
    for name, text in files.items():
        assert (extracted / name).read_text() == text
