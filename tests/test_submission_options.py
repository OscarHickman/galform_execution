"""Regression tests for the 2026-10-21 submission fixes.

1. Each distinct tcsh script gets its own file, so a later submission cannot
   change what an earlier, still-queued job runs.
2. Partition lists and unknown partitions no longer request one CPU per subvolume.
3. ``stellar_pop_dir`` is settable from the CLI and the environment; the
   default stays jch's ``/cosma5`` copy.
4. Extra ``sbatch`` options (exclude, dependency, anything else) have a public API.
"""

import re
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from galform_execution.cli import main
from galform_execution.submit_galform_job import (
    COSMA5_STELLAR_POP_DIR,
    PARTITION_CONFIGS,
    GalformSubmitter,
    default_stellar_pop_dir,
)

SBATCH = "galform_execution.submit_galform_job.subprocess.run"


def _fake_sbatch(captured):
    """sbatch stand-in recording each wrapper it receives."""

    def _run(cmd, input, capture_output, check):
        captured.append(input.decode())
        return subprocess.CompletedProcess(
            cmd, 0, stdout=f"Submitted batch job {len(captured)}\n".encode(), stderr=b""
        )

    return _run


def _tcsh_path_in(wrapper: str) -> Path:
    return Path(re.search(r"tcsh -ef (\S+)", wrapper).group(1))


def _submitter(galform_dir, log_dir, **kw):
    kw.setdefault("nbody_sim", "L800")
    kw.setdefault("model", "gp14")
    kw.setdefault("iz", 100)
    kw.setdefault("nvol", "1-4")
    return GalformSubmitter(
        galform_dir=galform_dir, log_path=str(log_dir), submit_retry_delay_s=0.0, **kw
    )


# --------------------------------------------------------------------------
# 1. One script file per distinct submission
# --------------------------------------------------------------------------


def test_later_submission_does_not_change_an_earlier_jobs_script(galform_dir, log_dir):
    """Two submissions sharing (sim, model, iz) used to share <model>_iz<iz>.csh, so
    the second silently rewrote what the first job's remaining ivols ran."""
    wrappers = []
    with patch(SBATCH, side_effect=_fake_sbatch(wrappers)):
        _submitter(galform_dir, log_dir, input_overrides={"tau0": "1.0"}).submit_job(
            100
        )
        _submitter(galform_dir, log_dir, input_overrides={"tau0": "2.0"}).submit_job(
            100
        )

    first, second = (_tcsh_path_in(w) for w in wrappers)
    assert first != second
    assert "tau0 1.0" in first.read_text()
    assert "tau0 2.0" in second.read_text()
    assert first.parent == second.parent == log_dir / "L800"
    assert first.name.startswith("gp14_iz100_") and first.suffix == ".csh"


def test_identical_submissions_share_one_script_file(galform_dir, log_dir):
    """Content-addressed names keep the file count at one per distinct script."""
    wrappers = []
    with patch(SBATCH, side_effect=_fake_sbatch(wrappers)):
        _submitter(galform_dir, log_dir).submit_job(100)
        _submitter(galform_dir, log_dir).submit_job(100)
    assert _tcsh_path_in(wrappers[0]) == _tcsh_path_in(wrappers[1])
    assert len(list((log_dir / "L800").glob("*.csh"))) == 1


def test_legacy_script_path_is_left_untouched(galform_dir, log_dir):
    """Jobs queued by older releases still read <model>_iz<iz>.csh: never touch it."""
    legacy = log_dir / "L800" / "gp14_iz100.csh"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("legacy script of a queued job\n")
    with patch(SBATCH, side_effect=_fake_sbatch([])):
        _submitter(galform_dir, log_dir).submit_job(100)
    assert legacy.read_text() == "legacy script of a queued job\n"


def test_script_path_is_public_and_used_by_default(galform_dir, log_dir):
    s = _submitter(galform_dir, log_dir)
    path = s.tcsh_script_path(100)
    assert path == s.tcsh_script_path(100, s.create_tcsh_script(100))
    assert f"tcsh -ef {path}" in s.create_job_script(100)


def test_existing_script_with_the_same_content_is_not_rewritten(galform_dir, log_dir):
    """A running job may be reading it; identical content means no write at all."""
    s = _submitter(galform_dir, log_dir)
    path = s.tcsh_script_path(100)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(s.create_tcsh_script(100))
    with (
        patch(SBATCH, side_effect=_fake_sbatch([])),
        patch.object(
            Path, "write_text", side_effect=AssertionError("rewrote the script")
        ),
    ):
        s.submit_job(100)


def test_dry_run_writes_no_script(galform_dir, log_dir, capsys):
    s = _submitter(galform_dir, log_dir)
    assert s.submit_job(100, dry_run=True) is None
    assert f"tcsh_path={s.tcsh_script_path(100)}" in capsys.readouterr().out
    assert not list(log_dir.rglob("*.csh"))


def test_write_tcsh_script_names_the_file_by_the_final_text(galform_dir, log_dir):
    """Callers that edit the script (imf, desi) get a name unique to their edit."""
    s = _submitter(galform_dir, log_dir)
    base = s.create_tcsh_script(100)
    edited = base + "# edited by the caller\n"
    path = s.write_tcsh_script(100, edited)
    assert path.read_text() == edited
    assert path == s.tcsh_script_path(100, edited)
    assert path != s.tcsh_script_path(100)  # that one hashes the unmodified script
    assert path.parent == log_dir / "L800" and path.name.startswith("gp14_iz100_")
    assert s.write_tcsh_script(100, base) == s.tcsh_script_path(100)


def test_write_tcsh_script_never_rewrites_an_existing_file(galform_dir, log_dir):
    s = _submitter(galform_dir, log_dir)
    path = s.write_tcsh_script(100, "echo one\n")
    mtime = path.stat().st_mtime_ns
    with patch(
        "galform_execution.submit_galform_job.os.replace",
        side_effect=AssertionError("rewrote the script"),
    ):
        assert s.write_tcsh_script(100, "echo one\n") == path
    assert path.stat().st_mtime_ns == mtime


def test_write_tcsh_script_leaves_no_temporary_file(galform_dir, log_dir):
    s = _submitter(galform_dir, log_dir)
    s.write_tcsh_script(100, "echo one\n")
    with patch(
        "galform_execution.submit_galform_job.os.replace",
        side_effect=OSError("disk full"),
    ):
        with pytest.raises(OSError, match="disk full"):
            s.write_tcsh_script(100, "echo two\n")
    assert sorted(p.name.startswith(".") for p in (log_dir / "L800").iterdir()) == [
        False
    ]


def test_write_tcsh_script_is_safe_across_threads(galform_dir, log_dir):
    """Every writer must see a complete file; temp names must not collide."""
    from concurrent.futures import ThreadPoolExecutor

    s = _submitter(galform_dir, log_dir)
    text = "echo same\n" * 1000
    with ThreadPoolExecutor(8) as pool:
        paths = set(pool.map(lambda _: s.write_tcsh_script(100, text), range(32)))
    (path,) = paths
    assert path.read_text() == text
    assert [p.name for p in (log_dir / "L800").iterdir()] == [path.name]


# --------------------------------------------------------------------------
# 2. CPU request for partition lists and unknown partitions
# --------------------------------------------------------------------------


def _cpus(script: str) -> int:
    return int(re.search(r"#SBATCH --cpus-per-task=(\d+)", script).group(1))


def test_partition_list_is_sized_by_its_smallest_node(galform_dir, log_dir):
    """L800 on a list used to ask for --cpus-per-task=1024, which sbatch rejects."""
    with pytest.warns(UserWarning, match="smallest node"):
        s = _submitter(
            galform_dir,
            log_dir,
            nvol="1-1024",
            partition="cosma8-shm,cosma8-shm2,cosma8-shm3,cosma7-shm",
        )
    script = s.create_job_script(100, tcsh_path="/x.csh")
    assert _cpus(script) == 56  # mad01 in cosma7-shm
    assert "#SBATCH -p cosma8-shm,cosma8-shm2,cosma8-shm3,cosma7-shm" in script
    assert "task_id + 56" in script


def test_partition_list_tolerates_spaces_and_empty_entries(galform_dir, log_dir):
    with pytest.warns(UserWarning, match="smallest node"):
        s = _submitter(
            galform_dir, log_dir, nvol="1-1024", partition="cosma8-shm, dine2,"
        )
    script = s.create_job_script(100, tcsh_path="/x.csh")
    assert _cpus(script) == 64
    assert "#SBATCH -p cosma8-shm,dine2\n" in script


@pytest.mark.parametrize(
    "partition, cpus",
    [
        ("hardwarelab-cpu", 112),  # gi001
        ("hardwarelab-gpu", 64),  # gn004
        ("cosma8-highram", 128),  # mad05
        ("cosma8-ska2", 48),  # mad03
        ("cosma8-shm2", 64),  # ga006
        ("cosma7-shm", 56),  # mad01
        ("bluefield1", 32),
    ],
)
def test_partition_table_holds_the_smallest_node(partition, cpus):
    assert PARTITION_CONFIGS[partition].cpus_per_node == cpus


def test_unknown_partition_is_an_error_without_explicit_cpus(galform_dir, log_dir):
    s = _submitter(galform_dir, log_dir, nvol="1-1024", partition="cosma8-shm,newpart")
    with pytest.raises(ValueError, match="newpart.*cpus_per_task"):
        s.create_job_script(100, tcsh_path="/x.csh")


def test_explicit_cpus_per_task_sizes_any_partition(galform_dir, log_dir):
    s = _submitter(
        galform_dir, log_dir, nvol="1-1024", partition="newpart", cpus_per_task=32
    )
    script = s.create_job_script(100, tcsh_path="/x.csh")
    assert _cpus(script) == 32
    assert "task_id + 32" in script


def test_explicit_cpus_per_task_overrides_the_table(galform_dir, log_dir):
    """e.g. a 64-ivol job on cosma7-shm with mad01 excluded."""
    s = _submitter(
        galform_dir,
        log_dir,
        nvol="1-64",
        partition="cosma7-shm",
        cpus_per_task=64,
        exclude="mad01",
    )
    assert _cpus(s.create_job_script(100, tcsh_path="/x.csh")) == 64


def test_explicit_cpus_per_task_is_capped_at_the_subvolume_count(galform_dir, log_dir):
    s = _submitter(galform_dir, log_dir, nvol="1-8", cpus_per_task=64)
    assert _cpus(s.create_job_script(100, tcsh_path="/x.csh")) == 8


@pytest.mark.parametrize("bad", [0, -4])
def test_cpus_per_task_must_be_positive(galform_dir, log_dir, bad):
    with pytest.raises(ValueError, match="cpus_per_task"):
        _submitter(galform_dir, log_dir, cpus_per_task=bad)


def test_single_known_partition_unchanged(galform_dir, log_dir):
    s = _submitter(galform_dir, log_dir, nvol="1-1024", partition="cosma8")
    assert _cpus(s.create_job_script(100, tcsh_path="/x.csh")) == 128


# --------------------------------------------------------------------------
# 3. stellar_pop_dir
# --------------------------------------------------------------------------


def _stellar_pop_line(s: GalformSubmitter) -> str:
    (line,) = [
        ln for ln in s.create_tcsh_script(100).splitlines() if " stellar_pop_dir " in ln
    ]
    return line


@pytest.mark.parametrize(
    "partition",
    ["cosma5", "cosma8-serial", "cosma8-shm,cosma8-shm2,cosma8-shm3,cosma7-shm,dine2"],
)
def test_default_stellar_pop_dir_is_jchs_copy_everywhere(
    galform_dir, log_dir, partition
):
    """The package is public: its default must not name one user's /cosma8 copy."""
    s = _submitter(galform_dir, log_dir, partition=partition)
    assert s.stellar_pop_dir == COSMA5_STELLAR_POP_DIR
    assert COSMA5_STELLAR_POP_DIR == "/cosma5/data/jch/Galform/Data/stellar_pop/"
    assert _stellar_pop_line(s).endswith(COSMA5_STELLAR_POP_DIR)
    assert default_stellar_pop_dir() == COSMA5_STELLAR_POP_DIR


def test_stellar_pop_dir_environment_variable(galform_dir, log_dir, monkeypatch):
    monkeypatch.setenv("GALFORM_STELLAR_POP_DIR", "/env/stellar_pop/")
    assert default_stellar_pop_dir() == "/env/stellar_pop/"
    assert _submitter(galform_dir, log_dir).stellar_pop_dir == "/env/stellar_pop/"
    explicit = _submitter(galform_dir, log_dir, stellar_pop_dir="/mine/")
    assert explicit.stellar_pop_dir == "/mine/"


def test_explicit_cosma5_stellar_pop_dir_on_a_cosma8_partition(galform_dir, log_dir):
    s = _submitter(
        galform_dir,
        log_dir,
        partition="cosma8-shm",
        stellar_pop_dir=COSMA5_STELLAR_POP_DIR,
    )
    assert _stellar_pop_line(s).endswith(COSMA5_STELLAR_POP_DIR)


# --------------------------------------------------------------------------
# 4. Extra sbatch options
# --------------------------------------------------------------------------


def test_exclude_and_dependency_become_wrapper_directives(galform_dir, log_dir):
    s = _submitter(
        galform_dir,
        log_dir,
        exclude="mad01,mad05",
        dependency="afterok:12345",
        extra_sbatch_args=["--qos=short", "--nice=10"],
    )
    script = s.create_job_script(100, tcsh_path="/x.csh")
    header = [ln for ln in script.splitlines() if ln.startswith("#SBATCH")]
    for directive in (
        "#SBATCH --exclude=mad01,mad05",
        "#SBATCH --dependency=afterok:12345",
        "#SBATCH --kill-on-invalid-dep=yes",
        "#SBATCH --qos=short",
        "#SBATCH --nice=10",
    ):
        assert directive in header


def test_default_wrapper_has_no_extra_directives(galform_dir, log_dir):
    script = _submitter(galform_dir, log_dir).create_job_script(100, "/x.csh")
    assert "--exclude" not in script
    assert "--dependency" not in script
    # Byte-for-byte the pre-0.3.1 header: nothing after -t but a blank line.
    assert "#SBATCH -t 72:00:00\n\n\n# One worker per allocated CPU" in script


@pytest.mark.parametrize(
    "bad, match",
    [
        ("--partition=cosma8", "partition"),
        ("-p cosma8", "partition"),
        ("--cpus-per-task=4", "cpus_per_task"),
        ("-t 1:00:00", "walltime"),
        ("--array=1-4", "array"),
        ("qos=short", "start with '-'"),
        ("--qos=short\n#SBATCH -A other", "newline"),
    ],
)
def test_extra_sbatch_args_are_validated(galform_dir, log_dir, bad, match):
    with pytest.raises(ValueError, match=match):
        _submitter(galform_dir, log_dir, extra_sbatch_args=[bad])


def test_extra_sbatch_args_must_be_a_sequence_of_strings(galform_dir, log_dir):
    with pytest.raises(TypeError, match="extra_sbatch_args"):
        _submitter(galform_dir, log_dir, extra_sbatch_args="--qos=short")


def test_submitted_wrapper_carries_the_directives(galform_dir, log_dir):
    wrappers = []
    with patch(SBATCH, side_effect=_fake_sbatch(wrappers)):
        _submitter(galform_dir, log_dir, exclude="mad01").submit_job(100)
    assert "#SBATCH --exclude=mad01" in wrappers[0]


def test_public_sbatch_with_retry(galform_dir, log_dir):
    s = _submitter(galform_dir, log_dir)
    with patch(SBATCH, side_effect=_fake_sbatch([])) as run:
        assert s.sbatch_with_retry("#!/bin/bash\n", 100, ["-x", "mad01"]) == "1"
    assert run.call_args.args[0] == ["sbatch", "-x", "mad01"]


def test_subclass_overriding_private_sbatch_still_intercepts(galform_dir, log_dir):
    """sigma8_bias and HOD hook _sbatch_with_retry; keep that working."""
    seen = []

    class Excluding(GalformSubmitter):
        def _sbatch_with_retry(self, script_content, iz, extra_args=None):
            seen.append(extra_args)
            return super()._sbatch_with_retry(script_content, iz, ["-x", "mad05"])

    s = Excluding(galform_dir=galform_dir, nvol="1-2", iz=100, log_path=str(log_dir))
    with patch(SBATCH, side_effect=_fake_sbatch([])) as run:
        assert s.submit_job(100) == "1"
    assert seen == [None]
    assert run.call_args.args[0] == ["sbatch", "-x", "mad05"]


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def _dry_run(capsys, galform_dir, *extra):
    rc = main(
        [galform_dir, "--nbody-sim", "L800", "--iz", "100", "--nvol", "1-1024"]
        + ["--dry-run", *extra]
    )
    out = capsys.readouterr()
    return rc, out.out, out.err


def test_cli_new_options(capsys, galform_dir):
    rc, out, err = _dry_run(
        capsys,
        galform_dir,
        "--partition",
        "cosma7-shm,newpart",
        "--cpus-per-task",
        "40",
        "--stellar-pop-dir",
        "/my/stellar_pop/",
        "--exclude",
        "mad01",
        "--dependency",
        "afterany:7",
        "--sbatch-arg=--qos=short",
        "--sbatch-arg=--nice=5",
    )
    assert rc == 0, err
    assert "#SBATCH --cpus-per-task=40" in out
    assert "stellar_pop_dir /my/stellar_pop/" in out
    assert "#SBATCH --exclude=mad01" in out
    assert "#SBATCH --dependency=afterany:7" in out
    assert "#SBATCH --kill-on-invalid-dep=yes" in out
    assert "#SBATCH --qos=short" in out and "#SBATCH --nice=5" in out


def test_cli_unknown_partition_without_cpus_is_a_clear_error(capsys, galform_dir):
    rc, _, err = _dry_run(capsys, galform_dir, "--partition", "newpart")
    assert rc == 1
    assert "newpart" in err and "--cpus-per-task" in err
