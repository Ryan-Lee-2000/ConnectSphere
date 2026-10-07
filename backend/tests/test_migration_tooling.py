import shutil
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory


# SPL-128 AC-8 Test-08
def test_can_generate_a_revision_without_touching_project_migrations(tmp_path):
    source = Path(__file__).resolve().parents[1] / "migrations"
    target = tmp_path / "migrations"
    shutil.copytree(source, target, ignore=shutil.ignore_patterns("__pycache__"))
    config = Config()
    config.set_main_option("script_location", str(target))
    # Read the current head first, so later migrations do not have to edit this test.
    heads = ScriptDirectory.from_config(config).get_heads()
    revision = command.revision(config, message="tooling check", rev_id="probe")
    assert revision.down_revision == heads[0]
    compile(Path(revision.path).read_text(), revision.path, "exec")
