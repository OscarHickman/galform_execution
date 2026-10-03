"""Tests for submit_galform_job.py script."""

import errno
import json
import os
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from galform_execution.submit_galform_job import (
    MODEL_CONFIGS,
    SIMULATION_CONFIGS,
    DustParams,
    GalformSubmitter,
    ModelConfig,
    RunFlags,
    SimulationConfig,
    _parse_nvol_range,
    _resolve_log_path,
    load_run_flags_config,
)


def _make_galform_dir(tmpdir):
    """Create a minimal fake galform directory with build/galform2."""
    gdir = Path(tmpdir) / "galform"
    build = gdir / "build"
    build.mkdir(parents=True)
    (build / "galform2").touch()
    (build / "neta_ave_disk").touch()
    (build / "neta_ave_burst").touch()
    (build / "sample_gals").touch()
    # Create a dummy .input.ref file for the default gp14 model
    (gdir / "Gonzalez13_Nbody_MillGas.input.ref").write_text(
        "# test ref\nomega0 = 0.272\n"
    )
    # Helper scripts
    (gdir / "replace_variable.csh").write_text("#!/bin/tcsh\n")
    (gdir / "replace_vector.csh").write_text("#!/bin/tcsh\n")
    (gdir / "delete_variable.csh").write_text("#!/bin/tcsh\n")
    return str(gdir)


def test_galform_submitter_initialization():
    """Test that GalformSubmitter can be initialized with valid inputs."""
    with tempfile.TemporaryDirectory() as tmpdir:
        gdir = _make_galform_dir(tmpdir)

        submitter = GalformSubmitter(
            galform_dir=gdir,
            nbody_sim="L800",
            model="gp14",
        )

        assert submitter.nbody_sim == "L800"
        assert submitter.model == "gp14"
        assert submitter.partition == "cosma5"
        assert submitter.account == "durham"
        assert submitter.walltime == "72:00:00"
        assert len(submitter.iz_list) > 0
        assert submitter.nvol_range == "1-1024"
        assert submitter.output_base_dir == Path(
            f"/cosma5/data/durham/{os.environ.get('USER', Path.home().name)}"
        )
        assert submitter.output_folder_name == "Galform_Out"


def test_galform_submitter_custom_config():
    """Test GalformSubmitter with custom configuration."""
    with tempfile.TemporaryDirectory() as tmpdir:
        gdir = _make_galform_dir(tmpdir)

        submitter = GalformSubmitter(
            galform_dir=gdir,
            nbody_sim="MillGas",
            model="gp14",
            iz=61,
            partition="cosma7",
            account="dp004",
            walltime="48:00:00",
            nvol_range="1-5",
            output_folder_name="Galform_Out_Test",
        )

        assert submitter.nbody_sim == "MillGas"
        assert submitter.partition == "cosma7"
        assert submitter.account == "dp004"
        assert submitter.walltime == "48:00:00"
        assert submitter.iz_list == [61]
        assert submitter.nvol_range == "1-5"
        assert submitter.output_folder_name == "Galform_Out_Test"


def test_galform_submitter_accepts_nvol_range():
    """Test that legacy-style nvol ranges can be passed directly."""
    with tempfile.TemporaryDirectory() as tmpdir:
        gdir = _make_galform_dir(tmpdir)

        submitter = GalformSubmitter(
            galform_dir=gdir,
            nbody_sim="L800",
            model="gp14",
            iz=271,
            nvol="1-10",
        )

        assert submitter.iz_list == [271]
        assert submitter.nvol_range == "1-10"


def test_create_tcsh_script():
    """Test tcsh inner script generation."""
    with tempfile.TemporaryDirectory() as tmpdir:
        gdir = _make_galform_dir(tmpdir)

        submitter = GalformSubmitter(
            galform_dir=gdir,
            nbody_sim="L800",
            model="gp14",
            output_folder_name="Galform_Out_Test",
        )

        script_content = submitter._create_tcsh_script(iz=100)

        # Check SLURM directives
        assert "#!/bin/tcsh -ef" in script_content
        assert "#SBATCH --ntasks 1" in script_content
        assert "#SBATCH -J L800.gp14" in script_content
        assert "#SBATCH -p cosma5" in script_content
        assert "#SBATCH -A durham" in script_content
        assert "#SBATCH -t 72:00:00" in script_content
        # Check parameter variables
        assert "set model     = gp14" in script_content
        assert "set Nbody_sim = L800" in script_content
        assert "set iz        = 100" in script_content
        assert "@ slurm_task_id = ${SLURM_ARRAY_TASK_ID}" in script_content
        assert "@ ivol        = $slurm_task_id + 1 - 2" in script_content
        # Check that galform dir is referenced
        assert f"cd {gdir}" in script_content
        # Check Fortran endianness conversion defaults are present
        assert "setenv GFORTRAN_CONVERT_UNIT big_endian" in script_content
        assert "setenv F_UFMTENDIAN big" in script_content
        # Check simulation parameters are injected
        assert "set omega0     = 0.307" in script_content
        assert "set h0         = 0.6777" in script_content
        assert "set sigma8     = 0.8288" in script_content
        # Check model setup
        assert "Gonzalez13_Nbody_MillGas.input.ref" in script_content
        # Check executables
        assert "galform2" in script_content
        assert "neta_ave_disk" in script_content
        assert "sample_gals" in script_content
        # Check bands
        assert "replace_vector.csh $galform_inputs_file idband" in script_content
        # Check run sections
        assert "running GALFORM" in script_content
        assert "running NETA_AVE" in script_content
        assert "running LUM_FUN" in script_content
        assert "Galform_Out_Test/L800" in script_content


def test_run_flags():
    """Test that run flags are properly injected into the script."""
    with tempfile.TemporaryDirectory() as tmpdir:
        gdir = _make_galform_dir(tmpdir)

        flags = RunFlags(
            galform=True,
            neta=False,
            lum_fun=False,
            study_stellar_mass_function=False,
            dust_props=True,
        )

        submitter = GalformSubmitter(
            galform_dir=gdir,
            nbody_sim="L800",
            model="gp14",
            run_flags=flags,
        )

        script_content = submitter._create_tcsh_script(iz=271)

        assert "set galform     = true" in script_content
        assert "set neta        = false" in script_content
        assert "set lum_fun     = false" in script_content
        assert "set dust_props  = true" in script_content
        assert "set study_stellar_mass_function = false" in script_content


def test_simulation_configs():
    """Test that all predefined simulation configurations are accessible."""
    assert "L800" in SIMULATION_CONFIGS
    assert "MillGas" in SIMULATION_CONFIGS
    assert "EagleDM" in SIMULATION_CONFIGS

    l800 = SIMULATION_CONFIGS["L800"]
    assert l800.iz_list == [271, 207, 176, 155, 142, 121, 120, 105, 100, 82]
    assert l800.nvol_range == "1-1024"
    assert l800.omega0 == 0.307
    assert l800.h0 == 0.6777

    for name, cfg in SIMULATION_CONFIGS.items():
        assert isinstance(cfg, SimulationConfig)
        assert cfg.iz_list is None or isinstance(cfg.iz_list, list)
        assert isinstance(cfg.nvol_range, str)
        assert cfg.omega0 > 0
        assert cfg.h0 > 0


def test_model_configs():
    """Test that all predefined model configurations are accessible."""
    assert "gp14" in MODEL_CONFIGS
    assert "lc16" in MODEL_CONFIGS
    assert "lc16.newmg" in MODEL_CONFIGS

    gp14 = MODEL_CONFIGS["gp14"]
    assert gp14.base_inputs_file == "Gonzalez13_Nbody_MillGas.input.ref"
    assert gp14.dust_params.fcloud == 0.25

    lc16 = MODEL_CONFIGS["lc16"]
    assert lc16.dust_params.fcloud == 0.5

    for name, cfg in MODEL_CONFIGS.items():
        assert isinstance(cfg, ModelConfig)
        assert isinstance(cfg.dust_params, DustParams)


def test_invalid_galform_dir():
    """Test that appropriate errors are raised for invalid galform dir."""
    try:
        GalformSubmitter(
            galform_dir="/nonexistent/path/galform",
            nbody_sim="L800",
        )
        assert False, "Should have raised FileNotFoundError"
    except FileNotFoundError as e:
        assert "GALFORM directory not found" in str(e)


def test_missing_executable():
    """Test error when galform dir exists but has no executable."""
    with tempfile.TemporaryDirectory() as tmpdir:
        gdir = Path(tmpdir) / "galform"
        gdir.mkdir()
        (gdir / "build").mkdir()
        # No galform2 executable
        try:
            GalformSubmitter(galform_dir=str(gdir), nbody_sim="L800")
            assert False, "Should have raised FileNotFoundError"
        except FileNotFoundError as e:
            assert "GALFORM executable not found" in str(e)


def test_unknown_simulation():
    """Test handling of unknown simulation without custom config."""
    with tempfile.TemporaryDirectory() as tmpdir:
        gdir = _make_galform_dir(tmpdir)

        try:
            GalformSubmitter(
                galform_dir=gdir,
                nbody_sim="UnknownSim",
            )
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "Unknown simulation" in str(e)

        # Should work with explicit iz_list and nvol_range
        submitter = GalformSubmitter(
            galform_dir=gdir,
            nbody_sim="CustomSim",
            iz_list=[100],
            nvol_range="1-10",
        )
        assert submitter.nbody_sim == "CustomSim"
        assert submitter.iz_list == [100]





def test_parse_nvol_range_supports_single_and_range():
    """nvol parser should support a single value and an explicit range."""
    assert _parse_nvol_range("12") == (12, 12)
    assert _parse_nvol_range("1001-1024") == (1001, 1024)


def test_high_nvol_offset_in_tcsh_script():
    """High nvol start offset should appear correctly in the inner tcsh script."""
    with tempfile.TemporaryDirectory() as tmpdir:
        gdir = _make_galform_dir(tmpdir)

        submitter = GalformSubmitter(
            galform_dir=gdir,
            nbody_sim="L800",
            model="gp14",
            iz=207,
            nvol="1001-1024",
        )

        script = submitter._create_tcsh_script(iz=207)
        assert "@ ivol        = $slurm_task_id + 1001 - 2" in script




def test_log_path_creation():
    """Test that log directory is created properly."""
    with tempfile.TemporaryDirectory() as tmpdir:
        gdir = _make_galform_dir(tmpdir)
        log_path = Path(tmpdir) / "test_logs"

        submitter = GalformSubmitter(
            galform_dir=gdir,
            nbody_sim="L800",
            log_path=str(log_path),
        )

        submitter._create_tcsh_script(iz=100)

        assert log_path.exists()
        assert (log_path / "L800").exists()


def test_output_base_dir():
    """Test custom output base directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        gdir = _make_galform_dir(tmpdir)
        out_dir = Path(tmpdir) / "my_outputs"

        submitter = GalformSubmitter(
            galform_dir=gdir,
            nbody_sim="L800",
            output_base_dir=str(out_dir),
            output_folder_name="CustomFolder",
        )

        script = submitter._create_tcsh_script(iz=271)
        assert str(out_dir / "CustomFolder" / "L800") in script


def test_submit_job_retries_transient_error_then_succeeds():
    """Transient Slurm overload errors should be retried."""
    with tempfile.TemporaryDirectory() as tmpdir:
        gdir = _make_galform_dir(tmpdir)

        submitter = GalformSubmitter(
            galform_dir=gdir,
            nbody_sim="L800",
            iz=271,
            nvol="101-150",
            submit_retries=3,
            submit_retry_delay_s=0.0,
            log_path=str(Path(tmpdir) / "logs"),
        )

        transient_err = subprocess.CalledProcessError(
            returncode=1,
            cmd=["sbatch"],
            output=b"",
            stderr=(
                b"sbatch: error: Slurm temporarily unable to accept job, sleeping and retrying\n"
                b"sbatch: error: Batch job submission failed: Resource temporarily unavailable\n"
            ),
        )
        success = subprocess.CompletedProcess(
            args=["sbatch"],
            returncode=0,
            stdout=b"Submitted batch job 12345\n",
            stderr=b"",
        )

        with patch("galform_execution.submit_galform_job.time.sleep") as mocked_sleep:
            with patch(
                "galform_execution.submit_galform_job.subprocess.run",
                side_effect=[transient_err, success],
            ) as mocked_run:
                job_id = submitter.submit_job(iz=271, dry_run=False)

        assert job_id == "12345"
        assert mocked_run.call_count == 2
        mocked_sleep.assert_called_once()


def test_submit_job_fails_immediately_for_non_transient_error():
    """Non-transient sbatch errors should not be retried."""
    with tempfile.TemporaryDirectory() as tmpdir:
        gdir = _make_galform_dir(tmpdir)

        submitter = GalformSubmitter(
            galform_dir=gdir,
            nbody_sim="L800",
            iz=271,
            nvol="101-150",
            submit_retries=3,
            submit_retry_delay_s=0.0,
            log_path=str(Path(tmpdir) / "logs"),
        )

        fatal_err = subprocess.CalledProcessError(
            returncode=1,
            cmd=["sbatch"],
            output=b"",
            stderr=b"sbatch: error: Invalid account or account/partition combination specified\n",
        )

        with patch("galform_execution.submit_galform_job.time.sleep") as mocked_sleep:
            with patch(
                "galform_execution.submit_galform_job.subprocess.run",
                side_effect=fatal_err,
            ) as mocked_run:
                try:
                    submitter.submit_job(iz=271, dry_run=False)
                    assert (
                        False
                    ), "Expected RuntimeError for non-transient submission failure"
                except RuntimeError as exc:
                    assert "Invalid account" in str(exc)

        assert mocked_run.call_count == 1
        mocked_sleep.assert_not_called()


def test_submit_job_fails_after_retries_exhausted_for_transient_error():
    """Transient errors should eventually fail once retries are exhausted."""
    with tempfile.TemporaryDirectory() as tmpdir:
        gdir = _make_galform_dir(tmpdir)

        submitter = GalformSubmitter(
            galform_dir=gdir,
            nbody_sim="L800",
            iz=271,
            nvol="101-150",
            submit_retries=3,
            submit_retry_delay_s=0.0,
            log_path=str(Path(tmpdir) / "logs"),
        )

        transient_err = subprocess.CalledProcessError(
            returncode=1,
            cmd=["sbatch"],
            output=b"",
            stderr=(
                b"sbatch: error: Slurm temporarily unable to accept job, sleeping and retrying\n"
                b"sbatch: error: Batch job submission failed: Resource temporarily unavailable\n"
            ),
        )

        with patch("galform_execution.submit_galform_job.time.sleep") as mocked_sleep:
            with patch(
                "galform_execution.submit_galform_job.subprocess.run",
                side_effect=[transient_err, transient_err, transient_err],
            ) as mocked_run:
                try:
                    submitter.submit_job(iz=271, dry_run=False)
                    assert False, "Expected RuntimeError after retry exhaustion"
                except RuntimeError as exc:
                    assert "Resource temporarily unavailable" in str(exc)

        assert mocked_run.call_count == 3
        assert mocked_sleep.call_count == 2


def test_custom_modules():
    """Test custom module loading."""
    with tempfile.TemporaryDirectory() as tmpdir:
        gdir = _make_galform_dir(tmpdir)

        submitter = GalformSubmitter(
            galform_dir=gdir,
            nbody_sim="L800",
            modules=["gcc/11.0", "openmpi/4.1"],
        )

        script = submitter._create_tcsh_script(iz=271)
        assert "modulecmd.tcl csh purge" in script
        assert "modulecmd.tcl csh load gcc/11.0" in script
        assert "modulecmd.tcl csh load openmpi/4.1" in script


def test_multi_output_redshifts_set_nout_and_zout():
    """Explicit output redshifts should set nout and zout vector."""
    with tempfile.TemporaryDirectory() as tmpdir:
        gdir = _make_galform_dir(tmpdir)
        submitter = GalformSubmitter(
            galform_dir=gdir,
            nbody_sim="L800",
            model="gp14",
            iz=155,
            nvol="1-1",
            output_redshifts=[0.0, 0.401, 1.0],
            input_overrides={
                "build_galaxy_trees": ".true.",
            },
        )

        script = submitter._create_tcsh_script(iz=155)
        assert "./replace_variable.csh $galform_inputs_file nout 3" in script
        assert "./replace_vector.csh $galform_inputs_file zout 0 0.401 1" in script
        assert (
            "./replace_variable.csh $galform_inputs_file mgalmin_output_descendants .true."
            in script
        )


def test_create_job_script():
    """Job bash wrapper should use cpus-per-task instead of --array."""
    with tempfile.TemporaryDirectory() as tmpdir:
        gdir = _make_galform_dir(tmpdir)
        log_path = Path(tmpdir) / "logs"

        submitter = GalformSubmitter(
            galform_dir=gdir,
            nbody_sim="L800",
            model="gp14",
            iz=100,
            nvol="1-64",
            log_path=str(log_path),
            partition="cosma8-shm",
            account="durham",
            walltime="72:00:00",
        )

        tcsh_path = f"{tmpdir}/logs/L800/gp14_iz100.csh"
        script = submitter.create_job_script(iz=100, tcsh_path=tcsh_path)

        assert "#!/bin/bash" in script
        assert "#SBATCH --ntasks=1" in script
        assert "#SBATCH --cpus-per-task=64" in script
        assert "#SBATCH --mem-per-cpu=4000" in script
        assert "#SBATCH -J L800.gp14" in script
        assert "#SBATCH -p cosma8-shm" in script
        assert "#SBATCH -A durham" in script
        assert "#SBATCH -t 72:00:00" in script
        assert "--array" not in script
        assert f"tcsh -ef {tcsh_path}" in script
        # cosma8-shm has 128 CPUs; 64 ivols fit without throttling
        assert "for cpu_id in $(seq 1 64)" in script
        assert "[ $task_id -le 64 ]" in script
        assert "task_id + 64" in script
        assert "wait" in script
        assert ".%j.log" in script
        assert ".%A.%a.log" not in script


def test_create_job_script_custom_mem():
    """mem_per_cpu kwarg should propagate into the wrapper."""
    with tempfile.TemporaryDirectory() as tmpdir:
        gdir = _make_galform_dir(tmpdir)
        submitter = GalformSubmitter(
            galform_dir=gdir,
            nbody_sim="L800",
            model="gp14",
            iz=100,
            nvol="1-16",
        )
        script = submitter.create_job_script(
            iz=100, tcsh_path="/tmp/g.csh", mem_per_cpu=8000
        )
        assert "#SBATCH --cpus-per-task=16" in script
        assert "#SBATCH --mem-per-cpu=8000" in script


def test_create_job_script_throttled():
    """Job script caps cpus-per-task at partition limit; workers stride over excess ivols."""
    with tempfile.TemporaryDirectory() as tmpdir:
        gdir = _make_galform_dir(tmpdir)
        submitter = GalformSubmitter(
            galform_dir=gdir,
            nbody_sim="L800",
            model="gp14",
            iz=100,
            nvol="1-1024",
            partition="cosma8",  # 128 CPUs per node
            account="durham",
            walltime="72:00:00",
        )
        script = submitter.create_job_script(iz=100, tcsh_path="/tmp/g.csh")

        # Should request only 128 CPUs, not 1024
        assert "#SBATCH --cpus-per-task=128" in script
        # Each worker strides through 1024 ivols 128 at a time
        assert "for cpu_id in $(seq 1 128)" in script
        assert "[ $task_id -le 1024 ]" in script
        assert "task_id + 128" in script
        assert "--array" not in script


def test_create_job_script_mail_notifications():
    """mail_user should add SBATCH mail directives; omitting it should not."""
    with tempfile.TemporaryDirectory() as tmpdir:
        gdir = _make_galform_dir(tmpdir)

        # With email — default mail_type
        submitter = GalformSubmitter(
            galform_dir=gdir,
            nbody_sim="L800",
            model="gp14",
            iz=100,
            nvol="1-8",
            mail_user="user@example.com",
        )
        script = submitter.create_job_script(iz=100, tcsh_path="/tmp/g.csh")
        assert "#SBATCH --mail-user=user@example.com" in script
        assert "#SBATCH --mail-type=END,FAIL" in script

        # Custom mail_type
        submitter_all = GalformSubmitter(
            galform_dir=gdir,
            nbody_sim="L800",
            model="gp14",
            iz=100,
            nvol="1-8",
            mail_user="user@example.com",
            mail_type="ALL",
        )
        script_all = submitter_all.create_job_script(iz=100, tcsh_path="/tmp/g.csh")
        assert "#SBATCH --mail-type=ALL" in script_all

        # Without email — directives must be absent
        submitter_no_mail = GalformSubmitter(
            galform_dir=gdir,
            nbody_sim="L800",
            model="gp14",
            iz=100,
            nvol="1-8",
        )
        script_no_mail = submitter_no_mail.create_job_script(
            iz=100, tcsh_path="/tmp/g.csh"
        )
        assert "--mail-user" not in script_no_mail
        assert "--mail-type" not in script_no_mail


def test_submit_job_dry_run(capsys):
    """Dry run should print both scripts and not call sbatch."""
    with tempfile.TemporaryDirectory() as tmpdir:
        gdir = _make_galform_dir(tmpdir)
        submitter = GalformSubmitter(
            galform_dir=gdir,
            nbody_sim="L800",
            model="gp14",
            iz=100,
            nvol="1-8",
        )
        result = submitter.submit_job(iz=100, dry_run=True)

        assert result is None
        captured = capsys.readouterr()
        assert "DRY RUN" in captured.out
        assert "#!/bin/tcsh -ef" in captured.out
        assert "#!/bin/bash" in captured.out


def test_submit_job_writes_tcsh_and_submits():
    """submit_job should write the tcsh script and submit the bash wrapper."""
    with tempfile.TemporaryDirectory() as tmpdir:
        gdir = _make_galform_dir(tmpdir)
        log_path = Path(tmpdir) / "logs"
        submitter = GalformSubmitter(
            galform_dir=gdir,
            nbody_sim="L800",
            model="gp14",
            iz=100,
            nvol="1-4",
            log_path=str(log_path),
            submit_retry_delay_s=0.0,
        )
        expected_tcsh = log_path / "L800" / "gp14_iz100.csh"

        calls = {}

        def _fake_run(cmd, input, capture_output, check):
            calls["cmd"] = cmd
            calls["input"] = input.decode()

            class _Result:
                stdout = b"Submitted batch job 99999\n"

            return _Result()

        with patch("subprocess.run", side_effect=_fake_run):
            job_id = submitter.submit_job(iz=100, dry_run=False)

        assert job_id == "99999"
        assert "--array" not in " ".join(calls["cmd"])
        assert "#!/bin/bash" in calls["input"]
        assert "#SBATCH --cpus-per-task=4" in calls["input"]
        assert str(expected_tcsh) in calls["input"]
        assert expected_tcsh.exists()
        assert "#!/bin/tcsh -ef" in expected_tcsh.read_text()


def test_submit_job_retries_transient_error():
    """Transient sbatch errors during submission should be retried."""
    with tempfile.TemporaryDirectory() as tmpdir:
        gdir = _make_galform_dir(tmpdir)
        log_path = Path(tmpdir) / "logs"
        submitter = GalformSubmitter(
            galform_dir=gdir,
            nbody_sim="L800",
            model="gp14",
            iz=100,
            nvol="1-4",
            log_path=str(log_path),
            submit_retries=3,
            submit_retry_delay_s=0.0,
        )

        transient_err = subprocess.CalledProcessError(
            returncode=1,
            cmd=["sbatch"],
            output=b"",
            stderr=b"sbatch: error: Slurm temporarily unable to accept job\n",
        )
        success = subprocess.CompletedProcess(
            args=["sbatch"],
            returncode=0,
            stdout=b"Submitted batch job 77777\n",
            stderr=b"",
        )

        with patch("galform_execution.submit_galform_job.time.sleep"):
            with patch(
                "galform_execution.submit_galform_job.subprocess.run",
                side_effect=[transient_err, success],
            ) as mocked_run:
                job_id = submitter.submit_job(iz=100, dry_run=False)

        assert job_id == "77777"
        assert mocked_run.call_count == 2


def test_multi_output_respects_explicit_mgalmin_descendant_override():
    """User-provided mgalmin_output_descendants should not be overwritten."""
    with tempfile.TemporaryDirectory() as tmpdir:
        gdir = _make_galform_dir(tmpdir)
        submitter = GalformSubmitter(
            galform_dir=gdir,
            nbody_sim="L800",
            model="gp14",
            iz=155,
            nvol="1-1",
            output_redshifts=[0.0, 0.401],
            input_overrides={
                "build_galaxy_trees": ".true.",
                "mgalmin_output_descendants": ".false.",
            },
        )

        script = submitter._create_tcsh_script(iz=155)
        assert (
            "./replace_variable.csh $galform_inputs_file mgalmin_output_descendants .false."
            in script
        )


def test_params_file_path_is_job_unique():
    """The generated parameter file must not be shared between concurrent jobs.

    Two jobs sharing (Nbody_sim, model, iz, ivol) each run
    ``cp $base_inputs_file $galform_inputs_file`` before substituting, so a
    shared path lets one job wipe the other's substitutions and lets GALFORM
    read a parameter set belonging to a different job. This silently mixed
    x_imf branches across the 2026 redshift-ladder campaigns.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        gdir = _make_galform_dir(tmpdir)

        submitter = GalformSubmitter(
            galform_dir=gdir,
            nbody_sim="L800",
            model="gp14",
            output_folder_name="Galform_Out_Test",
        )
        script_content = submitter._create_tcsh_script(iz=100)

        line = next(
            ln
            for ln in script_content.splitlines()
            if ln.strip().startswith("set galform_inputs_file")
        )
        assert "${SLURM_JOB_ID}" in line, (
            "parameter file path must be job-unique; got: " + line
        )


def test_explicit_ivols_list_in_tcsh_script():
    """An explicit, non-contiguous ivol list is looked up by task id (tcsh arrays are 1-based)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        gdir = _make_galform_dir(tmpdir)

        submitter = GalformSubmitter(
            galform_dir=gdir, nbody_sim="L800", model="gp14", iz=271, ivols=[5, 900, 17]
        )

        assert submitter.ivols == [5, 900, 17]
        assert submitter.nvol_count == 3
        script = submitter._create_tcsh_script(iz=271)
        assert "set ivol_list = ( 5 900 17 )" in script
        assert "@ ivol        = $ivol_list[$slurm_task_id]" in script
        assert "$slurm_task_id + " not in script


def test_explicit_ivols_sizes_job_wrapper():
    """The bash wrapper covers exactly len(ivols) task ids."""
    with tempfile.TemporaryDirectory() as tmpdir:
        gdir = _make_galform_dir(tmpdir)
        ivols = list(range(0, 1024, 16))  # 64 ivols

        submitter = GalformSubmitter(
            galform_dir=gdir,
            nbody_sim="L800",
            model="gp14",
            iz=271,
            ivols=ivols,
            log_path=str(Path(tmpdir) / "logs"),
            partition="cosma8-shm",
        )

        script = submitter.create_job_script(iz=271, tcsh_path="/x.csh")
        assert "#SBATCH --cpus-per-task=64" in script
        assert "[ $task_id -le 64 ]" in script


def test_explicit_ivols_validation():
    """ivols must be unique, in range, non-empty and exclusive with nvol/nvol_range."""
    with tempfile.TemporaryDirectory() as tmpdir:
        gdir = _make_galform_dir(tmpdir)
        kw = dict(galform_dir=gdir, nbody_sim="L800", model="gp14", iz=271)
        for bad in ([], [3, 3], [-1], [1024]):
            with pytest.raises(ValueError):
                GalformSubmitter(**kw, ivols=bad)
        with pytest.raises(ValueError):
            GalformSubmitter(**kw, ivols=[1, 2], nvol="1-2")
        with pytest.raises(ValueError):
            GalformSubmitter(**kw, ivols=[1, 2], nvol_range="1-2")


def test_contiguous_nvol_unchanged_without_ivols():
    """Without ivols the legacy contiguous mapping is untouched."""
    with tempfile.TemporaryDirectory() as tmpdir:
        gdir = _make_galform_dir(tmpdir)
        submitter = GalformSubmitter(
            galform_dir=gdir, nbody_sim="L800", model="gp14", iz=271, nvol="1-64"
        )
        assert submitter.ivols is None
        script = submitter._create_tcsh_script(iz=271)
        assert "@ ivol        = $slurm_task_id + 1 - 2" in script
        assert "ivol_list" not in script


def test_explicit_ivols_with_unknown_sim():
    """ivols stands in for nvol when the simulation is not in SIMULATION_CONFIGS."""
    with tempfile.TemporaryDirectory() as tmpdir:
        gdir = _make_galform_dir(tmpdir)
        submitter = GalformSubmitter(
            galform_dir=gdir,
            nbody_sim="MyCustomSim",
            model="gp14",
            iz_list=[100],
            ivols=[7, 2],
        )
        assert submitter.nvol_count == 2
        assert submitter.nvol_range == "3-8"


# --------------------------------------------------------------------------
# Test isolation and default paths
# --------------------------------------------------------------------------


def test_default_log_path_is_isolated_from_cosma_during_tests(galform_dir, tmp_path):
    submitter = GalformSubmitter(galform_dir=galform_dir, nbody_sim="L800")
    assert tmp_path in submitter.log_path.parents


def test_default_log_path_lives_under_cosma_user_root(monkeypatch):
    monkeypatch.delenv("GALFORM_LOG_PATH", raising=False)
    monkeypatch.setenv("USER", "someone")
    assert _resolve_log_path(None, "Proj") == Path(
        "/cosma5/data/durham/someone/Proj/logs"
    )


def test_log_path_env_var_and_explicit_argument(monkeypatch, tmp_path):
    monkeypatch.setenv("GALFORM_LOG_PATH", str(tmp_path / "env"))
    assert _resolve_log_path(None, "Proj") == tmp_path / "env"
    assert _resolve_log_path(str(tmp_path / "explicit"), "Proj") == (
        tmp_path / "explicit"
    )


# --------------------------------------------------------------------------
# Input validation
# --------------------------------------------------------------------------


@pytest.mark.parametrize("bad", ["", "abc", "1-x", "0", "0-5", "10-1", "-3"])
def test_parse_nvol_range_rejects_invalid_ranges(bad):
    """Ranges are 1-based and ordered: ivol = task + start - 2 must be >= 0."""
    with pytest.raises(ValueError):
        _parse_nvol_range(bad)


def test_unknown_snapshot_is_rejected_before_submission(galform_dir):
    """An iz missing from the redshift list would only fail on the compute node."""
    submitter = GalformSubmitter(
        galform_dir=galform_dir, nbody_sim="L800", iz=99999, nvol="1-2"
    )
    with pytest.raises(ValueError, match="99999"):
        submitter.create_tcsh_script(99999)
    with pytest.raises(ValueError, match="99999"):
        submitter.submit_job(99999, dry_run=True)


def test_create_tcsh_script_is_public(galform_dir):
    submitter = GalformSubmitter(galform_dir=galform_dir, nbody_sim="L800")
    assert submitter.create_tcsh_script(100) == submitter._create_tcsh_script(100)


# --------------------------------------------------------------------------
# Job wrapper behaviour
# --------------------------------------------------------------------------


def test_job_wrapper_caps_thread_pools_to_one_per_worker(galform_dir):
    """Workers already fill every allocated CPU, so each must stay single-threaded."""
    submitter = GalformSubmitter(
        galform_dir=galform_dir, nbody_sim="L800", iz=100, nvol="1-8"
    )
    script = submitter.create_job_script(iz=100, tcsh_path="/x.csh")
    for var in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
        assert f"export {var}=1" in script
    assert script.index("export OMP_NUM_THREADS=1") < script.index("_run_worker $cpu_id &")


def test_unwritable_log_dir_does_not_break_script_generation(galform_dir, monkeypatch):
    """Previewing off-cluster must work even where /cosma5 cannot be created
    (e.g. a read-only root filesystem raises EROFS, not PermissionError)."""
    submitter = GalformSubmitter(
        galform_dir=galform_dir, nbody_sim="L800", iz=100, nvol="1-2"
    )

    def _read_only(self, *args, **kwargs):
        raise OSError(errno.EROFS, "Read-only file system", str(self))

    monkeypatch.setattr(Path, "mkdir", _read_only)
    assert "#!/bin/tcsh" in submitter.create_tcsh_script(100)
    assert "#!/bin/bash" in submitter.create_job_script(100)


# --------------------------------------------------------------------------
# Custom simulation and model configs
# --------------------------------------------------------------------------


def _custom_sim(**overrides):
    cfg = dict(
        nvol_range="1-8",
        nbody_trees_dir="/trees",
        snapshot_file="L800.txt",
        aquarius_tree_file="/trees/tree_271",
        aquarius_particle_file="/trees/particle_list_271",
        omega0=0.3,
        lambda0=0.7,
        omegab=0.05,
        h0=0.7,
        sigma8=0.8,
        pk_file="Power_Spec/pk.dat",
        iz_list=[271, 207],
        volume=42.0,
        iz0=271,
    )
    cfg.update(overrides)
    return SimulationConfig(**cfg)


def test_custom_sim_config_for_unregistered_simulation(galform_dir):
    submitter = GalformSubmitter(
        galform_dir=galform_dir, nbody_sim="MySim", sim_config=_custom_sim()
    )
    assert submitter.iz_list == [271, 207]
    assert submitter.nvol_range == "1-8"
    script = submitter.create_tcsh_script(271)
    assert "set Nbody_sim = MySim" in script
    assert "set volume     = 42.0" in script
    assert "/trees/tree_271" in script


def test_sim_config_argument_takes_precedence_over_registry(galform_dir):
    submitter = GalformSubmitter(
        galform_dir=galform_dir,
        nbody_sim="L800",
        sim_config=_custom_sim(omega0=0.123, lambda0=0.877),
    )
    assert "set omega0     = 0.123" in submitter.create_tcsh_script(271)


def test_custom_model_config(galform_dir):
    model = ModelConfig(
        base_inputs_file="Mine.input.ref",
        dust_params=DustParams(fcloud=0.9),
        extra_replacements={"nmf": "3"},
    )
    submitter = GalformSubmitter(
        galform_dir=galform_dir, nbody_sim="L800", model="mine", model_config=model
    )
    script = submitter.create_tcsh_script(100)
    assert "set model     = mine" in script
    assert "set base_inputs_file = Mine.input.ref" in script
    assert "set fcloud = 0.9" in script
    assert "./replace_variable.csh $galform_inputs_file nmf 3" in script


def test_unknown_model_fails_with_actionable_message(galform_dir):
    submitter = GalformSubmitter(
        galform_dir=galform_dir, nbody_sim="L800", model="no_such_model"
    )
    with pytest.raises(ValueError, match="model_config"):
        submitter.create_tcsh_script(100)


# --------------------------------------------------------------------------
# Run-flag config loading
# --------------------------------------------------------------------------


def test_load_run_flags_config_explicit_missing_path_raises(tmp_path):
    with pytest.raises(FileNotFoundError, match="typo.json"):
        load_run_flags_config(str(tmp_path / "typo.json"))


def test_load_run_flags_config_rejects_unknown_keys(tmp_path):
    cfg = tmp_path / "flags.json"
    cfg.write_text(json.dumps({"neta": False, "lumfun": False}))
    with pytest.raises(ValueError, match="lumfun"):
        load_run_flags_config(str(cfg))


def test_load_run_flags_config_ignores_comment_keys(tmp_path):
    cfg = tmp_path / "flags.json"
    cfg.write_text(json.dumps({"_comment": "for the imf runs", "neta": False}))
    flags = load_run_flags_config(str(cfg))
    assert flags == RunFlags(neta=False)


def test_load_run_flags_config_default_matches_bundled_json():
    assert load_run_flags_config() == RunFlags()
