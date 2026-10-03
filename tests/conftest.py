"""Shared fixtures for the galform_execution test suite."""

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolate_log_path(tmp_path, monkeypatch):
    """Keep every test away from the real COSMA filesystem.

    A submitter created without ``log_path`` otherwise resolves its logs to
    ``/cosma5/data/durham/$USER/<output_folder_name>/logs`` and creates that
    directory as a side effect of generating a script.
    """
    monkeypatch.setenv("GALFORM_LOG_PATH", str(tmp_path / "isolated_logs"))


@pytest.fixture
def galform_dir(tmp_path) -> str:
    """A minimal fake GALFORM source tree with the executables it expects."""
    gdir = tmp_path / "galform"
    build = gdir / "build"
    build.mkdir(parents=True)
    for exe in ("galform2", "neta_ave_disk", "neta_ave_burst", "sample_gals"):
        (build / exe).touch()
    (gdir / "Gonzalez13_Nbody_MillGas.input.ref").write_text(
        "# test ref\nomega0 = 0.272\n"
    )
    for helper in ("replace_variable.csh", "replace_vector.csh", "delete_variable.csh"):
        (gdir / helper).write_text("#!/bin/tcsh\n")
    return str(gdir)


@pytest.fixture
def log_dir(tmp_path) -> Path:
    return tmp_path / "logs"
