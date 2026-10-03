"""Tests for the ``submit-galform-job`` command-line interface."""

import json
import subprocess
import sys
from unittest.mock import patch

import pytest

from galform_execution import __version__
from galform_execution.submit_galform_job import main

SBATCH = "galform_execution.submit_galform_job.subprocess.run"


def _sbatch_ok(*job_ids):
    """Patch sbatch so each call reports the next job id."""
    results = [
        subprocess.CompletedProcess(
            ["sbatch"], 0, stdout=f"Submitted batch job {j}\n".encode(), stderr=b""
        )
        for j in job_ids
    ]
    return patch(SBATCH, side_effect=results)


def _run(capsys, *argv):
    rc = main([str(a) for a in argv])
    captured = capsys.readouterr()
    return rc, captured.out, captured.err


def _l800_dry_run(capsys, galform_dir, *extra):
    return _run(
        capsys,
        galform_dir,
        "--nbody-sim",
        "L800",
        "--iz",
        "100",
        "--nvol",
        "1-4",
        "--dry-run",
        *extra,
    )


def _write_sim_config(path, name, **overrides):
    """Write a single-simulation JSON file in the bundled config format."""
    cfg = {
        "nvol_range": "1-8",
        "nbody_trees_dir": "/trees",
        "snapshot_file": "L800.txt",
        "aquarius_tree_file": "/trees/tree_271",
        "aquarius_particle_file": "/trees/particle_list_271",
        "omega0": 0.3,
        "lambda0": 0.7,
        "omegab": 0.05,
        "h0": 0.7,
        "sigma8": 0.8,
        "pk_file": "Power_Spec/pk.dat",
        "iz_list": [271],
        "volume": 42.0,
        "iz0": 271,
    }
    cfg.update(overrides)
    cfg = {k: v for k, v in cfg.items() if v is not None}
    path.write_text(json.dumps({name: cfg}))
    return path


# --------------------------------------------------------------------------
# Informational commands
# --------------------------------------------------------------------------


def test_list_models(capsys):
    rc, out, _ = _run(capsys, "--list-models")
    assert rc == 0
    assert "Available model configurations" in out
    assert "gp14" in out and "lc16" in out


def test_list_simulations(capsys):
    rc, out, _ = _run(capsys, "--list-simulations")
    assert rc == 0
    assert "Available simulation configurations" in out
    assert "L800" in out and "MillGas" in out and "EagleDM" in out


def test_help_exits_zero(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    for option in ("--nbody-sim", "--dry-run", "--iz", "--nvol", "--ivols"):
        assert option in out


def test_version_flag(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert __version__ in capsys.readouterr().out


# --------------------------------------------------------------------------
# Entry points and exit codes
# --------------------------------------------------------------------------


def test_python_dash_m_propagates_failure_exit_code(tmp_path):
    result = subprocess.run(
        [sys.executable, "-m", "galform_execution", str(tmp_path / "missing")],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "GALFORM directory not found" in result.stderr


def test_python_dash_m_help():
    result = subprocess.run(
        [sys.executable, "-m", "galform_execution", "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "Submit GALFORM N-body runs to SLURM" in result.stdout


def test_dry_run_prints_both_scripts(capsys, galform_dir):
    rc, out, _ = _l800_dry_run(capsys, galform_dir, "--output-folder-name", "Proj")
    assert rc == 0
    assert "DRY RUN: iz=100, nvol_range=1-4" in out
    assert "#!/bin/tcsh -ef" in out
    assert "#!/bin/bash" in out
    assert "Proj/L800" in out


def test_submission_prints_each_job_id(capsys, galform_dir, log_dir):
    with _sbatch_ok("111", "222"):
        rc, out, _ = _run(
            capsys,
            galform_dir,
            "--nbody-sim",
            "L800",
            "--iz-list",
            "271",
            "207",
            "--nvol",
            "1-4",
            "--log-path",
            log_dir,
        )
    assert rc == 0
    assert "iz=271" in out and "111" in out
    assert "iz=207" in out and "222" in out


def test_submission_failure_returns_1(capsys, galform_dir, log_dir):
    fatal = subprocess.CalledProcessError(
        1, ["sbatch"], output=b"", stderr=b"sbatch: error: Invalid account\n"
    )
    with patch(SBATCH, side_effect=fatal):
        rc, _, err = _run(
            capsys,
            galform_dir,
            "--iz",
            "271",
            "--nvol",
            "1-4",
            "--log-path",
            log_dir,
        )
    assert rc == 1
    assert "Error:" in err and "Invalid account" in err


# --------------------------------------------------------------------------
# Run flags
# --------------------------------------------------------------------------


def test_run_flags_config_keeps_flags_without_cli_switches(
    capsys, galform_dir, tmp_path
):
    """Every flag in --run-flags-config must reach the script, not just the
    handful that also have a CLI switch."""
    cfg = tmp_path / "flags.json"
    cfg.write_text(json.dumps({"cosmicsed": True, "agn": True, "neta": False}))
    rc, out, _ = _l800_dry_run(capsys, galform_dir, "--run-flags-config", cfg)
    assert rc == 0
    assert "set cosmicsed   = true" in out
    assert "set agn           = true" in out
    assert "set neta        = false" in out


def test_cli_switch_overrides_run_flags_config(capsys, galform_dir, tmp_path):
    cfg = tmp_path / "flags.json"
    cfg.write_text(json.dumps({"neta": True, "dust_props": False}))
    rc, out, _ = _l800_dry_run(
        capsys,
        galform_dir,
        "--run-flags-config",
        cfg,
        "--no-neta",
        "--run-dust-props",
    )
    assert rc == 0
    assert "set neta        = false" in out
    assert "set dust_props  = true" in out


def test_missing_run_flags_config_is_an_error(capsys, galform_dir, tmp_path):
    rc, _, err = _l800_dry_run(
        capsys, galform_dir, "--run-flags-config", tmp_path / "typo.json"
    )
    assert rc == 1
    assert "typo.json" in err


@pytest.mark.parametrize(
    "conflict",
    [
        ["--run-galform", "--no-galform"],
        ["--build-galaxy-trees", "--no-build-galaxy-trees"],
        ["--output-halo-trees", "--no-output-halo-trees"],
        ["--output-iz-list", "100", "--output-z-list", "0.5"],
        ["--nvol-range", "1-2"],
        ["--ivols", "1", "2"],
    ],
)
def test_conflicting_options_are_rejected_by_the_parser(
    capsys, galform_dir, conflict
):
    with pytest.raises(SystemExit) as exc:
        _l800_dry_run(capsys, galform_dir, *conflict)
    assert exc.value.code == 2
    assert "not allowed with" in capsys.readouterr().err


# --------------------------------------------------------------------------
# Options mirroring the Python API
# --------------------------------------------------------------------------


def test_ivols_option(capsys, galform_dir):
    rc, out, _ = _run(
        capsys,
        galform_dir,
        "--iz",
        "271",
        "--ivols",
        "5",
        "900",
        "17",
        "--dry-run",
    )
    assert rc == 0
    assert "set ivol_list = ( 5 900 17 )" in out
    assert "[ $task_id -le 3 ]" in out


def test_mem_per_cpu_option(capsys, galform_dir):
    rc, out, _ = _l800_dry_run(capsys, galform_dir, "--mem-per-cpu", "8000")
    assert rc == 0
    assert "#SBATCH --mem-per-cpu=8000" in out


def test_input_override_option(capsys, galform_dir):
    rc, out, _ = _l800_dry_run(
        capsys,
        galform_dir,
        "--input-override",
        "nmf=1",
        "--input-override",
        "vhotdisk=290",
    )
    assert rc == 0
    assert "./replace_variable.csh $galform_inputs_file nmf 1" in out
    assert "./replace_variable.csh $galform_inputs_file vhotdisk 290" in out


@pytest.mark.parametrize("bad", ["nmf", "=1", "nmf="])
def test_input_override_must_be_name_equals_value(capsys, galform_dir, bad):
    with pytest.raises(SystemExit) as exc:
        _l800_dry_run(capsys, galform_dir, "--input-override", bad)
    assert exc.value.code == 2
    assert "NAME=VALUE" in capsys.readouterr().err


def test_simulation_config_option(capsys, galform_dir, tmp_path):
    cfg = _write_sim_config(tmp_path / "sims.json", "MySim")
    rc, out, _ = _run(
        capsys,
        galform_dir,
        "--simulation-config",
        cfg,
        "--nbody-sim",
        "MySim",
        "--nvol",
        "1-2",
        "--dry-run",
    )
    assert rc == 0
    assert "set Nbody_sim = MySim" in out
    assert "set volume     = 42.0" in out
    assert "DRY RUN: iz=271" in out


def test_list_simulations_includes_custom_config(capsys, tmp_path):
    cfg = _write_sim_config(tmp_path / "sims.json", "MySim")
    rc, out, _ = _run(capsys, "--simulation-config", cfg, "--list-simulations")
    assert rc == 0
    assert "MySim" in out
    assert "L800" in out


def test_model_config_option(capsys, galform_dir, tmp_path):
    cfg = tmp_path / "models.json"
    cfg.write_text(
        json.dumps(
            {
                "mymodel": {
                    "base_inputs_file": "Custom.input.ref",
                    "dust_profile": "lacey16",
                    "extra_replacements": {"nmf": "2"},
                }
            }
        )
    )
    rc, out, _ = _l800_dry_run(
        capsys, galform_dir, "--model-config", cfg, "--model", "mymodel"
    )
    assert rc == 0
    assert "set base_inputs_file = Custom.input.ref" in out
    assert "set fcloud = 0.5" in out
    assert "./replace_variable.csh $galform_inputs_file nmf 2" in out


def test_no_snapshots_to_submit_is_an_error(capsys, galform_dir, tmp_path):
    cfg = _write_sim_config(tmp_path / "sims.json", "NoIz", iz_list=None)
    rc, _, err = _run(
        capsys,
        galform_dir,
        "--simulation-config",
        cfg,
        "--nbody-sim",
        "NoIz",
        "--nvol",
        "1-2",
        "--dry-run",
    )
    assert rc == 1
    assert "No snapshots" in err
