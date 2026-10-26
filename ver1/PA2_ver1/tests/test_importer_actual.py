import os
from pathlib import Path

import pytest

from pa2.cad.importer import StepImporter
from pa2.storage.assets import sha256_file


@pytest.mark.integration
def test_optional_real_step_import_preserves_source():
    raw = os.environ.get("PA2_TEST_STEP")
    if not raw:
        pytest.skip("PA2_TEST_STEP not set")
    path = Path(raw); before = sha256_file(path)
    scene = StepImporter().read(path, before, "assets/test/source.step")
    assert scene.bodies and all(body.unit == "mm" for body in scene.bodies)
    assert sha256_file(path) == before

