"""Test-suite wide guards.

Keep the field log out of the way. `CODE_STEWARD_FIELD_LOG` is an
environment variable, and once it is exported from a shell profile
every `pytest` run inherits it -- so the CLI tests, which invoke real
commands against fixture projects, append to whatever real log the
developer is keeping. That happened: 119 of 130 rows in a live field
log turned out to be test fixtures, and the giveaway was that a
1-millisecond `trace` is impossible against a 14,848-unit index.

The measurement this project depends on is the one it must not
contaminate with its own test runs.
"""

from __future__ import annotations

import pytest

from code_steward.fieldlog import ENV_VAR


@pytest.fixture(autouse=True)
def _no_field_log(monkeypatch: pytest.MonkeyPatch) -> None:
    """Never write a developer's field log from the test suite."""
    monkeypatch.delenv(ENV_VAR, raising=False)
