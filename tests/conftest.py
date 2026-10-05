"""Keep test artifacts out of another Windows account's shared pytest temp root."""
from pathlib import Path
from uuid import uuid4


def pytest_configure(config):
    # A caller's explicit --basetemp always takes precedence. Fresh UUIDs avoid
    # reuse/deletion of directories created under the Codex sandbox account.
    if config.option.basetemp is None:
        project=Path(__file__).resolve().parents[1]
        parent=project/".test-tmp"
        # pytest creates the session directory, but expects its parent to exist.
        parent.mkdir(exist_ok=True)
        config.option.basetemp=str(parent/("session-"+uuid4().hex))
