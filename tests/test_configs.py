"""Integrity of the bundled configuration data and the config loaders."""

import dataclasses
import json
import math
from pathlib import Path

import pytest

from galform_execution.submit_galform_job import (
    _REDSHIFT_LISTS_DIR,
    _RUN_FLAGS_CONFIG_PATH,
    DUST_CONFIGS,
    MODEL_CONFIGS,
    PARTITION_CONFIGS,
    SIMULATION_CONFIGS,
    RunFlags,
    _parse_nvol_range,
    load_dust_configs,
    load_model_configs,
    load_simulation_configs,
)

SIM_NAMES = sorted(SIMULATION_CONFIGS)


def _bundled_redshift_list(name):
    path = _REDSHIFT_LISTS_DIR / name
    snapshots = {}
    for line in path.read_text().splitlines():
        parts = line.split()
        if len(parts) >= 2 and not line.lstrip().startswith("#"):
            snapshots[int(parts[0])] = float(parts[1])
    return snapshots


BUNDLED_SIMS = sorted(
    n for n, c in SIMULATION_CONFIGS.items() if not Path(c.snapshot_file).is_absolute()
)


# --------------------------------------------------------------------------
# Simulations
# --------------------------------------------------------------------------


@pytest.mark.parametrize("name", SIM_NAMES)
def test_cosmology_is_physical(name):
    cfg = SIMULATION_CONFIGS[name]
    assert math.isclose(cfg.omega0 + cfg.lambda0, 1.0, abs_tol=2e-3), "not flat"
    assert 0 < cfg.omegab < cfg.omega0
    assert 0.5 < cfg.h0 < 1.0
    assert 0.5 < cfg.sigma8 < 1.1


@pytest.mark.parametrize("name", SIM_NAMES)
def test_nvol_range_is_valid(name):
    start, end = _parse_nvol_range(SIMULATION_CONFIGS[name].nvol_range)
    assert start == 1, "default range should cover the box from subvolume 1"
    assert end >= start


@pytest.mark.parametrize(
    "name",
    [
        n
        for n in SIM_NAMES
        if SIMULATION_CONFIGS[n].lbox and SIMULATION_CONFIGS[n].volume
    ],
)
def test_volume_is_box_volume_per_subvolume(name):
    """``volume`` is the per-subvolume volume: lbox**3 / (number of subvolumes)."""
    cfg = SIMULATION_CONFIGS[name]
    n_subvolumes = _parse_nvol_range(cfg.nvol_range)[1]
    assert math.isclose(cfg.volume, cfg.lbox**3 / n_subvolumes, rel_tol=1e-3)


@pytest.mark.parametrize("name", BUNDLED_SIMS)
def test_bundled_redshift_list_covers_iz_list_and_iz0(name):
    cfg = SIMULATION_CONFIGS[name]
    snapshots = _bundled_redshift_list(cfg.snapshot_file)
    assert set(cfg.iz_list or []) <= set(snapshots)
    assert cfg.iz0 in snapshots
    assert snapshots[cfg.iz0] == pytest.approx(0.0, abs=1e-2), "iz0 must be z=0"


@pytest.mark.parametrize(
    "filename", sorted(p.name for p in _REDSHIFT_LISTS_DIR.iterdir())
)
def test_bundled_redshift_lists_are_ordered(filename):
    """Redshift never increases with snapshot number and is never negative.

    Not strictly decreasing: P-Millennium (L800) genuinely has two pairs of
    snapshots at the same output time (100/101 and 138/139).
    """
    snapshots = _bundled_redshift_list(filename)
    assert snapshots, "empty redshift list"
    redshifts = [snapshots[iz] for iz in sorted(snapshots)]
    assert all(z >= 0 for z in redshifts)
    assert all(a >= b for a, b in zip(redshifts, redshifts[1:]))
    assert redshifts[0] > redshifts[-1]


def test_every_bundled_redshift_list_is_used():
    used = {SIMULATION_CONFIGS[n].snapshot_file for n in BUNDLED_SIMS}
    assert used == {p.name for p in _REDSHIFT_LISTS_DIR.iterdir()}


def test_load_simulation_configs_from_single_file(tmp_path):
    l800 = {
        f.name: getattr(SIMULATION_CONFIGS["L800"], f.name)
        for f in dataclasses.fields(SIMULATION_CONFIGS["L800"])
    }
    path = tmp_path / "one.json"
    path.write_text(json.dumps({"Copy": {**l800, "_note": "comments are ignored"}}))
    assert load_simulation_configs(str(path)) == {"Copy": SIMULATION_CONFIGS["L800"]}


def test_load_simulation_configs_merges_a_directory(tmp_path):
    base = {
        f.name: getattr(SIMULATION_CONFIGS["L800"], f.name)
        for f in dataclasses.fields(SIMULATION_CONFIGS["L800"])
    }
    (tmp_path / "a.json").write_text(json.dumps({"A": base}))
    (tmp_path / "b.json").write_text(json.dumps({"B": base}))
    (tmp_path / "ignored.txt").write_text("not json")
    assert sorted(load_simulation_configs(str(tmp_path))) == ["A", "B"]


def test_invalid_simulation_field_names_the_simulation(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"Broken": {"nvol_range": "1-8", "omega_0": 0.3}}))
    with pytest.raises(ValueError, match="Broken"):
        load_simulation_configs(str(path))


# --------------------------------------------------------------------------
# Models and dust
# --------------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(MODEL_CONFIGS))
def test_models_reference_input_ref_files(name):
    assert MODEL_CONFIGS[name].base_inputs_file.endswith(".input.ref")


@pytest.mark.parametrize("name", sorted(DUST_CONFIGS))
def test_dust_profiles_are_positive(name):
    dust = DUST_CONFIGS[name]
    for field in dataclasses.fields(dust):
        value = getattr(dust, field.name)
        if isinstance(value, float):
            assert value > 0, field.name


def test_model_with_unknown_dust_profile_is_rejected(tmp_path):
    path = tmp_path / "models.json"
    path.write_text(
        json.dumps({"m": {"base_inputs_file": "x.input.ref", "dust_profile": "nope"}})
    )
    with pytest.raises(ValueError, match="nope"):
        load_model_configs(DUST_CONFIGS, str(path))


def test_model_without_dust_is_rejected(tmp_path):
    path = tmp_path / "models.json"
    path.write_text(json.dumps({"m": {"base_inputs_file": "x.input.ref"}}))
    with pytest.raises(ValueError, match="dust_profile or dust_params"):
        load_model_configs(DUST_CONFIGS, str(path))


def test_model_with_inline_dust_params(tmp_path):
    path = tmp_path / "models.json"
    path.write_text(
        json.dumps(
            {"m": {"base_inputs_file": "x.input.ref", "dust_params": {"fcloud": 0.7}}}
        )
    )
    assert load_model_configs(DUST_CONFIGS, str(path))["m"].dust_params.fcloud == 0.7


def test_load_dust_configs_from_custom_file(tmp_path):
    path = tmp_path / "dust.json"
    path.write_text(json.dumps({"mine": {"fcloud": 0.1}}))
    assert load_dust_configs(str(path))["mine"].fcloud == 0.1


# --------------------------------------------------------------------------
# Partitions and run flags
# --------------------------------------------------------------------------


def test_partitions_include_defaults_and_are_positive():
    assert "cosma5" in PARTITION_CONFIGS, "the default --partition must be known"
    for name, cfg in PARTITION_CONFIGS.items():
        assert isinstance(cfg.cpus_per_node, int) and cfg.cpus_per_node > 0, name


def test_bundled_run_flags_list_every_flag_exactly_once():
    data = json.loads(_RUN_FLAGS_CONFIG_PATH.read_text())
    assert set(data) == {f.name for f in dataclasses.fields(RunFlags)}
