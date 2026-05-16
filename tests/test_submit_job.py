import subprocess
import pytest

import submit_galform_job as sj


def test_submit_job_success(tmp_path, monkeypatch):
    # pick an available simulation key from configs
    sim_key = next(iter(sj.SIMULATION_CONFIGS))

    # create minimal galform dir expected by GalformSubmitter
    gdir = tmp_path / 'galform'
    build = gdir / 'build'
    build.mkdir(parents=True)
    (build / 'galform2').write_text('')
    (build / 'neta_ave_disk').write_text('')
    (build / 'neta_ave_burst').write_text('')
    (build / 'sample_gals').write_text('')
    # base inputs
    gdir.mkdir(exist_ok=True)
    (gdir / 'Gonzalez13_Nbody_MillGas.input.ref').write_text('# test ref\nomega0 = 0.272\n')

    runner = sj.GalformSubmitter(galform_dir=str(gdir), nbody_sim=sim_key)

    # fake subprocess.run to return a CompletedProcess with sbatch output
    def fake_run(cmd, input=None, capture_output=False, check=False):
        return subprocess.CompletedProcess(cmd, 0, stdout=b"Submitted batch job 12345\n", stderr=b"")

    monkeypatch.setattr(subprocess, "run", fake_run)

    job_id = runner.submit_job(runner.iz_list[0], dry_run=False)
    assert job_id == "12345"


def test_submit_job_non_transient_failure_raises(tmp_path, monkeypatch):
    sim_key = next(iter(sj.SIMULATION_CONFIGS))
    # create minimal galform dir
    gdir = tmp_path / 'galform'
    build = gdir / 'build'
    build.mkdir(parents=True)
    (build / 'galform2').write_text('')
    (build / 'neta_ave_disk').write_text('')
    (build / 'neta_ave_burst').write_text('')
    (build / 'sample_gals').write_text('')
    gdir.mkdir(exist_ok=True)
    (gdir / 'Gonzalez13_Nbody_MillGas.input.ref').write_text('# test ref\nomega0 = 0.272\n')

    runner = sj.GalformSubmitter(galform_dir=str(gdir), nbody_sim=sim_key)

    # Simulate sbatch failing with a non-transient error
    err = subprocess.CalledProcessError(returncode=1, cmd=["sbatch"], output=b"", stderr=b"fatal error")

    def fake_run(cmd, input=None, capture_output=False, check=False):
        raise err

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(RuntimeError):
        runner.submit_job(runner.iz_list[0], dry_run=False)
