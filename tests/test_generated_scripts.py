"""Execute the generated job scripts: shell syntax, worker striding, ivol mapping.

The tcsh tests are skipped where tcsh is not installed (CI installs it).
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from galform_execution.submit_galform_job import (
    PARTITION_CONFIGS,
    GalformSubmitter,
    PartitionConfig,
    RunFlags,
)

needs_tcsh = pytest.mark.skipif(
    shutil.which("tcsh") is None, reason="tcsh is not installed"
)


def test_job_wrapper_is_valid_bash(galform_dir, tmp_path):
    submitter = GalformSubmitter(
        galform_dir, nbody_sim="L800", iz=100, nvol="1-8", mail_user="a@b.org"
    )
    wrapper = tmp_path / "wrapper.sh"
    wrapper.write_text(submitter.create_job_script(100, tcsh_path="/x.csh"))
    result = subprocess.run(
        ["bash", "-n", str(wrapper)], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr


@needs_tcsh
@pytest.mark.parametrize(
    "kwargs",
    [
        {"nvol": "1-4"},
        {"ivols": [5, 900, 17]},
        {
            "output_redshifts": [0.0, 1.0],
            "input_overrides": {"build_galaxy_trees": ".true."},
        },
        {"galform_exe": None, "modules": []},
    ],
    ids=["contiguous", "ivols", "multi-output", "no-modules"],
)
def test_tcsh_script_parses(galform_dir, tmp_path, kwargs):
    submitter = GalformSubmitter(galform_dir, nbody_sim="L800", iz=100, **kwargs)
    script = tmp_path / "job.csh"
    script.write_text(submitter.create_tcsh_script(100))
    result = subprocess.run(["tcsh", "-n", str(script)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


@needs_tcsh
def test_wrapper_runs_every_task_exactly_once_when_workers_stride(
    galform_dir, tmp_path, monkeypatch
):
    """10 subvolumes on a 3-CPU partition: 3 workers must cover tasks 1..10
    between them, each exactly once, every one single-threaded."""
    monkeypatch.setitem(PARTITION_CONFIGS, "tiny", PartitionConfig(cpus_per_node=3))
    submitter = GalformSubmitter(
        galform_dir, nbody_sim="L800", iz=100, nvol="1-10", partition="tiny"
    )
    # One file per task: concurrent tcsh ">>" appends to a shared file are not
    # atomic and drop lines, which made this test fail ~1 run in 8.
    record = tmp_path / "ran"
    record.mkdir()
    task = tmp_path / "task.csh"
    task.write_text(
        "#!/bin/tcsh -ef\n" f'echo "$OMP_NUM_THREADS" > {record}/$SLURM_ARRAY_TASK_ID\n'
    )
    wrapper = tmp_path / "wrapper.sh"
    script = submitter.create_job_script(100, tcsh_path=str(task))
    assert "#SBATCH --cpus-per-task=3" in script
    wrapper.write_text(script)

    subprocess.run(["bash", str(wrapper)], check=True, timeout=60)

    ran = sorted(record.iterdir(), key=lambda p: int(p.name))
    assert [int(p.name) for p in ran] == list(range(1, 11))
    assert {p.read_text().strip() for p in ran} == {"1"}


@needs_tcsh
@pytest.mark.parametrize(
    "kwargs, expected",
    [
        ({"nvol": "1-3"}, [0, 1, 2]),
        ({"nvol": "1001-1003"}, [1000, 1001, 1002]),
        ({"ivols": [5, 900, 17]}, [5, 900, 17]),
    ],
    ids=["from-1", "high-offset", "explicit-list"],
)
def test_task_id_maps_to_expected_ivol(galform_dir, tmp_path, kwargs, expected):
    """Evaluate the generated task-id -> ivol lines in a real tcsh (1-based arrays)."""
    submitter = GalformSubmitter(galform_dir, nbody_sim="L800", iz=100, **kwargs)
    full = submitter.create_tcsh_script(100)
    start = full.index("@ slurm_task_id")
    end = full.index("\n", full.index("@ ivol"))
    snippet = tmp_path / "ivol.csh"
    snippet.write_text(full[start:end] + "\necho $ivol\n")

    def ivol_for(task_id):
        result = subprocess.run(
            ["tcsh", "-ef", str(snippet)],
            env={**os.environ, "SLURM_ARRAY_TASK_ID": str(task_id)},
            capture_output=True,
            text=True,
            check=True,
        )
        return int(result.stdout.strip())

    assert [ivol_for(t) for t in (1, 2, 3)] == expected


_MODULECMD = "/usr/bin/tclsh /cosma/local/Modules/default/libexec/modulecmd.tcl"


def _stub(path, body):
    path.write_text("#!/bin/bash\n" + body + "\n")
    path.chmod(0o755)


@needs_tcsh
@pytest.mark.parametrize("neta", [True, False], ids=["neta-on", "neta-off"])
def test_tcsh_script_runs_end_to_end_with_stub_executables(galform_dir, tmp_path, neta):
    """Run the complete generated script with stand-ins for GALFORM and its
    helper scripts, checking what GALFORM is called with and that the
    per-job parameter file is cleaned up. Only module loading is replaced."""
    calls = tmp_path / "calls.log"
    gdir = Path(galform_dir)
    for helper in ("replace_variable.csh", "replace_vector.csh", "delete_variable.csh"):
        _stub(gdir / helper, f'echo "{helper} ${{@:2}}" >> {calls}')
    _stub(
        gdir / "build" / "galform2",
        f'echo "galform2 $@" >> {calls}; mkdir -p "$1"; touch "$1/global"',
    )
    for exe in ("neta_ave_disk", "neta_ave_burst"):
        _stub(gdir / "build" / exe, f"cat > /dev/null; echo {exe} >> {calls}")
    _stub(gdir / "build" / "sample_gals", f'echo "sample_gals $@" >> {calls}')

    out = tmp_path / "out"
    submitter = GalformSubmitter(
        galform_dir,
        nbody_sim="L800",
        model="gp14",
        iz=100,
        nvol="1-4",
        output_base_dir=str(out),
        output_folder_name="Proj",
        run_flags=RunFlags(neta=neta, lum_fun=False, study_stellar_mass_function=True),
        input_overrides={"nmf": "2"},
    )
    script = tmp_path / "job.csh"
    script.write_text(submitter.create_tcsh_script(100).replace(_MODULECMD, "true"))

    result = subprocess.run(
        ["tcsh", "-ef", str(script)],
        env={**os.environ, "SLURM_ARRAY_TASK_ID": "2", "SLURM_JOB_ID": "4242"},
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "The end" in result.stdout

    log = calls.read_text()
    output_dir = out / "Proj" / "L800" / "gp14" / "iz100" / "ivol1"
    params = "./params/L800_gp14_iz100_ivol1_job4242.input.temp"
    assert f"galform2 {output_dir} {params} -ivolume=1" in log
    assert "replace_variable.csh volume 155626.1" in log
    assert "replace_variable.csh nout 1" in log
    assert "replace_vector.csh zout 4.30093" in log
    assert "replace_variable.csh nmf 2" in log
    assert ("neta_ave_disk" in log) is neta
    assert "props weight mstars_tot mstars_allburst" in log
    assert (output_dir / "global").exists()
    assert (out / "Proj" / "L800" / "gp14" / "iz100" / "zsnap.dat").exists()
    assert not (gdir / params).exists(), "per-job parameter file not cleaned up"
