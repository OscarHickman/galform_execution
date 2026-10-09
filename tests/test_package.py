"""Packaging tests: what a user installing from PyPI actually receives."""

import importlib.metadata as md
import re
from importlib import resources
from pathlib import Path

import pytest

import galform_execution
from galform_execution import submit_galform_job

REPO_ROOT = Path(__file__).resolve().parents[1]
DIST = "galform_execution"


def test_public_api_is_importable_from_the_top_level():
    for name in galform_execution.__all__:
        assert hasattr(galform_execution, name), name
    assert galform_execution.GalformSubmitter is submit_galform_job.GalformSubmitter


def test_version_comes_from_installed_metadata():
    assert galform_execution.__version__ == md.version(DIST)
    assert re.fullmatch(r"\d+\.\d+\.\d+([ab]|rc)?\d*", galform_execution.__version__)


def test_console_script_points_at_cli():
    (script,) = [
        ep for ep in md.distribution(DIST).entry_points if ep.group == "console_scripts"
    ]
    assert script.name == "submit-galform-job"
    assert script.value == "galform_execution.cli:main"
    assert script.load() is galform_execution.cli.main


def test_legacy_main_still_works(capsys):
    assert submit_galform_job.main(["--list-models"]) == 0
    assert "gp14" in capsys.readouterr().out


def test_distribution_metadata():
    meta = md.metadata(DIST)
    assert meta["Requires-Python"] == ">=3.9"
    assert meta["License-Expression"] == "MIT"
    classifiers = meta.get_all("Classifier")
    assert "Typing :: Typed" in classifiers
    assert "Topic :: Scientific/Engineering :: Astronomy" in classifiers
    assert "Programming Language :: Python :: 3.9" in classifiers
    urls = {u.split(",")[0] for u in meta.get_all("Project-URL")}
    assert {"Homepage", "Repository", "Issues", "Changelog"} <= urls
    assert not md.requires(DIST), "runtime must stay dependency-free"


def test_bundled_data_files_are_installed():
    root = resources.files("galform_execution")
    assert root.joinpath("py.typed").is_file()
    config = root.joinpath("config")
    for name in (
        "models.json",
        "dust_params.json",
        "partition_configs.json",
        "run_flags.json",
    ):
        assert config.joinpath(name).is_file(), name
    sims = [p.name for p in config.joinpath("simulations").iterdir()]
    assert len([s for s in sims if s.endswith(".json")]) >= 6


def test_relative_snapshot_files_are_bundled():
    """A relative snapshot_file must ship with the package, or every job for
    that simulation fails on the compute node."""
    lists = resources.files("galform_execution").joinpath("config", "redshift_lists")
    for name, cfg in galform_execution.SIMULATION_CONFIGS.items():
        if not Path(cfg.snapshot_file).is_absolute():
            assert lists.joinpath(cfg.snapshot_file).is_file(), name


# --------------------------------------------------------------------------
# Release metadata kept in step with the package version (source tree only)
# --------------------------------------------------------------------------

in_repo = pytest.mark.skipif(
    not (REPO_ROOT / "pyproject.toml").is_file(),
    reason="release metadata files are only present in a source checkout",
)


def _pyproject_version():
    text = (REPO_ROOT / "pyproject.toml").read_text()
    return re.search(r'^version = "([^"]+)"', text, re.M).group(1)


@in_repo
def test_citation_cff_matches_version():
    text = (REPO_ROOT / "CITATION.cff").read_text()
    assert f'version: "{_pyproject_version()}"' in text


@pytest.mark.skipif(
    not (REPO_ROOT / "conda" / "meta.yaml").is_file(),
    reason="the conda recipe is not shipped in the sdist",
)
def test_conda_recipe_matches_version():
    text = (REPO_ROOT / "conda" / "meta.yaml").read_text()
    assert f'{{% set version = "{_pyproject_version()}" %}}' in text


@in_repo
def test_changelog_has_entry_for_version():
    text = (REPO_ROOT / "CHANGELOG.md").read_text()
    assert f"## [{_pyproject_version()}]" in text
