"""Tests for submit_galform_job.py script."""

import subprocess
import tempfile
from pathlib import Path
import sys
import os
from unittest.mock import patch

from galform_execution.submit_galform_job import (
    GalformSubmitter,
    RunFlags,
    SIMULATION_CONFIGS,
    MODEL_CONFIGS,
    DustParams,
    SimulationConfig,
    ModelConfig,
    _parse_nvol_range,
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


def test_create_slurm_script():
    """Test SLURM script generation."""
    with tempfile.TemporaryDirectory() as tmpdir:
        gdir = _make_galform_dir(tmpdir)

        submitter = GalformSubmitter(
            galform_dir=gdir,
            nbody_sim="L800",
            model="gp14",
            output_folder_name="Galform_Out_Test",
        )

        script_content = submitter.create_slurm_script(iz=100)

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

        script_content = submitter.create_slurm_script(iz=271)

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


def test_script_help_option():
    """Test that the script's help option works."""
    script_path = (
        Path(__file__).parent.parent / "galform_execution" / "submit_galform_job.py"
    )

    result = subprocess.run(
        ["python", str(script_path), "--help"],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "Submit GALFORM N-body runs to SLURM" in result.stdout
    assert "galform_dir" in result.stdout
    assert "--nbody-sim" in result.stdout
    assert "--dry-run" in result.stdout
    assert "--run-galform" in result.stdout
    assert "--iz" in result.stdout
    assert "--nvol" in result.stdout
    assert "--output-folder-name" in result.stdout


def test_script_list_simulations():
    """Test that the script can list available simulations."""
    script_path = (
        Path(__file__).parent.parent / "galform_execution" / "submit_galform_job.py"
    )

    result = subprocess.run(
        ["python", str(script_path), "--list-simulations"],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "Available simulation configurations" in result.stdout
    assert "L800" in result.stdout
    assert "MillGas" in result.stdout
    assert "EagleDM" in result.stdout


def test_script_list_models():
    """Test that the script can list available models."""
    script_path = (
        Path(__file__).parent.parent / "galform_execution" / "submit_galform_job.py"
    )

    result = subprocess.run(
        ["python", str(script_path), "--list-models"],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "Available model configurations" in result.stdout
    assert "gp14" in result.stdout
    assert "lc16" in result.stdout


def test_parse_nvol_range_supports_single_and_range():
    """nvol parser should support a single value and an explicit range."""
    assert _parse_nvol_range("12") == (12, 12)
    assert _parse_nvol_range("1001-1024") == (1001, 1024)


def test_submit_job_remaps_large_nvol_array_indices():
    """Submitting high nvol IDs should use a compact SLURM array range."""
    with tempfile.TemporaryDirectory() as tmpdir:
        gdir = _make_galform_dir(tmpdir)

        submitter = GalformSubmitter(
            galform_dir=gdir,
            nbody_sim="L800",
            model="gp14",
            iz=207,
            nvol="1001-1024",
        )

        called = {}

        def _fake_run(cmd, input, capture_output, check):
            called["cmd"] = cmd
            called["input"] = input.decode()

            class _Result:
                stdout = b"Submitted batch job 12345\n"

            return _Result()

        with patch("subprocess.run", side_effect=_fake_run):
            job_id = submitter.submit_job(iz=207, dry_run=False)

        assert job_id == "12345"
        assert "--array=1-24" in called["cmd"]
        assert "@ ivol        = $slurm_task_id + 1001 - 2" in called["input"]


def test_script_dry_run():
    """Test that the script's dry-run mode works."""
    script_path = (
        Path(__file__).parent.parent / "galform_execution" / "submit_galform_job.py"
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        gdir = _make_galform_dir(tmpdir)

        result = subprocess.run(
            [
                "python",
                str(script_path),
                gdir,
                "--nbody-sim",
                "L800",
                "--iz",
                "100",
                "--nvol",
                "5",
                "--output-folder-name",
                "Galform_Out_Test",
                "--dry-run",
            ],
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        assert "DRY RUN" in result.stdout
        assert "iz=100" in result.stdout
        assert "nvol_range=5" in result.stdout
        assert "#SBATCH" in result.stdout
        assert "set model" in result.stdout
        assert "Galform_Out_Test/L800" in result.stdout


def test_script_dry_run_with_nvol_range():
    """Test dry-run output for legacy-style nvol array submission."""
    script_path = (
        Path(__file__).parent.parent / "galform_execution" / "submit_galform_job.py"
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        gdir = _make_galform_dir(tmpdir)

        result = subprocess.run(
            [
                "python",
                str(script_path),
                gdir,
                "--nbody-sim",
                "L800",
                "--iz",
                "100",
                "--nvol",
                "1-10",
                "--dry-run",
            ],
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        assert "DRY RUN" in result.stdout
        assert "iz=100" in result.stdout
        assert "nvol_range=1-10" in result.stdout
        assert "@ slurm_task_id = ${SLURM_ARRAY_TASK_ID}" in result.stdout
        assert "@ ivol        = $slurm_task_id + 1 - 2" in result.stdout


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

        submitter.create_slurm_script(iz=100)

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

        script = submitter.create_slurm_script(iz=271)
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
        )

        transient_err = subprocess.CalledProcessError(
            returncode=1,
            cmd=["sbatch", "--array=101-150"],
            output=b"",
            stderr=(
                b"sbatch: error: Slurm temporarily unable to accept job, sleeping and retrying\n"
                b"sbatch: error: Batch job submission failed: Resource temporarily unavailable\n"
            ),
        )
        success = subprocess.CompletedProcess(
            args=["sbatch", "--array=101-150"],
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
        )

        fatal_err = subprocess.CalledProcessError(
            returncode=1,
            cmd=["sbatch", "--array=101-150"],
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
        )

        transient_err = subprocess.CalledProcessError(
            returncode=1,
            cmd=["sbatch", "--array=101-150"],
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

        script = submitter.create_slurm_script(iz=271)
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

        script = submitter.create_slurm_script(iz=155)
        assert "./replace_variable.csh $galform_inputs_file nout 3" in script
        assert "./replace_vector.csh $galform_inputs_file zout 0 0.401 1" in script
        assert (
            "./replace_variable.csh $galform_inputs_file mgalmin_output_descendants .true."
            in script
        )


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

        script = submitter.create_slurm_script(iz=155)
        assert (
            "./replace_variable.csh $galform_inputs_file mgalmin_output_descendants .false."
            in script
        )
