import shutil
from pathlib import Path

from alembic import command
from alembic.config import Config


def test_can_generate_a_revision_without_touching_project_migrations(tmp_path):
    source = Path(__file__).resolve().parents[1] / "migrations"
    target = tmp_path / "migrations"
    shutil.copytree(source, target, ignore=shutil.ignore_patterns("__pycache__"))
    config = Config()
    config.set_main_option("script_location", str(target))
    revision = command.revision(config, message="tooling check", rev_id="probe")
    assert revision.down_revision == "s2_venue_occupancy"
    compile(Path(revision.path).read_text(), revision.path, "exec")
