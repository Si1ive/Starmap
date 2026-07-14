from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


def test_revision_ids_fit_default_alembic_version_column():
    backend_dir = Path(__file__).resolve().parents[1]
    config = Config(str(backend_dir / "alembic.ini"))
    config.set_main_option("script_location", str(backend_dir / "alembic"))
    scripts = ScriptDirectory.from_config(config)

    oversized = [
        revision.revision
        for revision in scripts.walk_revisions()
        if len(revision.revision) > 32
    ]

    assert oversized == []


def test_migration_graph_has_single_head():
    backend_dir = Path(__file__).resolve().parents[1]
    config = Config(str(backend_dir / "alembic.ini"))
    config.set_main_option("script_location", str(backend_dir / "alembic"))
    scripts = ScriptDirectory.from_config(config)

    assert scripts.get_heads() == ["20260714_entity_reextract"]
