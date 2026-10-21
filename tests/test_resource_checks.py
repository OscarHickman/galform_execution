"""Checks on the resources a submitter asks for (0.4.0 review fixes).

1. A partition list sized by its smallest node warns when that leaves workers
   running several subvolumes; excluded nodes no longer count.
4. A walltime above a listed partition's MaxTime is an error; an explicit
   ``cpus_per_task`` above the smallest node warns.
6/7. ``exclude``, ``dependency`` and ``extra_sbatch_args`` cannot smuggle in
   directives or repeat options the submitter already sets.
9. A ``/cosma8`` ``stellar_pop_dir`` on a partition not known to mount
   ``/cosma8`` warns.
"""

import re
import warnings

import pytest

from galform_execution.submit_galform_job import (
    PARTITION_CONFIGS,
    GalformSubmitter,
    _expand_hostlist,
    _walltime_hours,
)

SIGMA8_LIST = "cosma8-shm,cosma8-shm2,cosma8-shm3,cosma7-shm,dine2"


def _submitter(galform_dir, log_dir, **kw):
    kw.setdefault("nbody_sim", "L800")
    kw.setdefault("model", "gp14")
    kw.setdefault("iz", 100)
    kw.setdefault("nvol", "1-64")
    return GalformSubmitter(galform_dir=galform_dir, log_path=str(log_dir), **kw)


def _no_warnings(galform_dir, log_dir, **kw):
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        return _submitter(galform_dir, log_dir, **kw)


def _cpus(s: GalformSubmitter) -> int:
    script = s.create_job_script(100, tcsh_path="/x.csh")
    return int(re.search(r"#SBATCH --cpus-per-task=(\d+)", script).group(1))


# --------------------------------------------------------------------------
# 1. Smallest-node sizing: warn, and honour exclusions
# --------------------------------------------------------------------------


def test_list_smaller_than_its_largest_node_warns(galform_dir, log_dir):
    """sigma8_bias: 64 ivols on this list silently got 56 workers (mad01)."""
    with pytest.warns(UserWarning, match=r"56 CPUs for 64 subvolumes.*cpus_per_task"):
        s = _submitter(galform_dir, log_dir, partition=SIGMA8_LIST)
    assert _cpus(s) == 56


def test_excluding_the_only_small_node_resizes_the_list(galform_dir, log_dir):
    s = _no_warnings(galform_dir, log_dir, partition=SIGMA8_LIST, exclude="mad01,mad05")
    assert _cpus(s) == 64  # dine2 / ga006 are now the smallest


@pytest.mark.parametrize(
    "exclude, cpus",
    [
        ("mad01", 112),  # mad02 left
        ("mad[01]", 112),
        ("mad[01-02]", None),  # nothing left
        ("gc001", 56),  # a node of another partition changes nothing
    ],
)
def test_exclusions_within_one_partition(galform_dir, log_dir, exclude, cpus):
    kw = dict(partition="cosma7-shm", nvol="1-112", exclude=exclude)
    if cpus is None:
        s = _submitter(galform_dir, log_dir, cpus_per_task=8, **kw)
        with pytest.raises(ValueError, match="excludes every node"):
            _submitter(galform_dir, log_dir, **kw)._effective_cpus()
        assert _cpus(s) == 8
        return
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        assert _cpus(_submitter(galform_dir, log_dir, **kw)) == cpus


def test_fully_excluded_partition_drops_out_of_a_list(galform_dir, log_dir):
    s = _no_warnings(
        galform_dir, log_dir, partition="cosma7-shm,dine2", exclude="mad[01-02]"
    )
    assert _cpus(s) == 64


def test_no_warning_when_every_worker_has_one_subvolume(galform_dir, log_dir):
    s = _no_warnings(galform_dir, log_dir, partition=SIGMA8_LIST, nvol="1-32")
    assert _cpus(s) == 32


def test_no_warning_for_a_uniform_partition(galform_dir, log_dir):
    s = _no_warnings(galform_dir, log_dir, partition="cosma8", nvol="1-1024")
    assert _cpus(s) == 128


def test_heterogeneous_single_partition_warns(galform_dir, log_dir):
    with pytest.warns(UserWarning, match="112 CPUs for 1024 subvolumes"):
        _submitter(
            galform_dir,
            log_dir,
            partition="hardwarelab-cpu",
            nvol="1-1024",
            walltime="06:00:00",
        )


def test_explicit_cpus_per_task_silences_the_sizing_warning(galform_dir, log_dir):
    s = _no_warnings(
        galform_dir,
        log_dir,
        partition=SIGMA8_LIST,
        exclude="mad05,mad01",
        cpus_per_task=64,
    )
    assert _cpus(s) == 64


@pytest.mark.parametrize(
    "spec, nodes",
    [
        ("mad01", {"mad01"}),
        ("mad01,mad05", {"mad01", "mad05"}),
        ("mad[01,05]", {"mad01", "mad05"}),
        ("mad[01-03],gc001", {"mad01", "mad02", "mad03", "gc001"}),
        ("gn[003-004],ga008", {"gn003", "gn004", "ga008"}),
        (" mad01 , ", {"mad01"}),
        (None, set()),
    ],
)
def test_expand_hostlist(spec, nodes):
    assert _expand_hostlist(spec) == nodes


def test_node_tables_agree_with_the_smallest_node():
    for name, cfg in PARTITION_CONFIGS.items():
        if cfg.nodes:
            assert min(cfg.nodes.values()) == cfg.cpus_per_node, name


# --------------------------------------------------------------------------
# 4. MaxTime and oversized cpus_per_task
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "walltime, hours",
    [
        ("72:00:00", 72.0),
        ("3-00:00:00", 72.0),
        ("1-12", 36.0),
        ("2-06:30", 54.5),
        ("06:00:00", 6.0),
        ("90", 1.5),
        ("30:00", 0.5),
        ("bogus", None),
        ("UNLIMITED", None),
    ],
)
def test_walltime_hours(walltime, hours):
    assert _walltime_hours(walltime) == hours


@pytest.mark.parametrize(
    "partition, max_h",
    [
        ("hardwarelab-cpu", 6),
        ("hardwarelab-gpu", 6),
        ("gracehopper", 6),
        ("mi300a", 2),
        ("bluefield1", 72),
        ("cosma5", 72),
        ("cosma8-pauper", 24),
        ("cosma8-serial", 72),
    ],
)
def test_partition_table_has_max_time(partition, max_h):
    assert PARTITION_CONFIGS[partition].max_time_h == max_h


def test_walltime_over_a_listed_partitions_max_is_an_error(galform_dir, log_dir):
    with pytest.raises(ValueError, match=r"hardwarelab-cpu.*6 h.*72:00:00"):
        _submitter(
            galform_dir,
            log_dir,
            partition="cosma5,hardwarelab-cpu",
            walltime="72:00:00",
            cpus_per_task=32,
        )


def test_walltime_at_the_max_is_accepted(galform_dir, log_dir):
    _no_warnings(
        galform_dir,
        log_dir,
        partition="hardwarelab-cpu",
        walltime="06:00:00",
        cpus_per_task=32,
    )
    _no_warnings(galform_dir, log_dir, partition="cosma5", walltime="3-00:00:00")


def test_unknown_partition_or_walltime_format_is_not_checked(galform_dir, log_dir):
    _no_warnings(
        galform_dir, log_dir, partition="newpart", walltime="999:00:00", cpus_per_task=8
    )
    _no_warnings(galform_dir, log_dir, partition="cosma5", walltime="bogus")


def test_cpus_per_task_above_the_smallest_node_warns(galform_dir, log_dir):
    with pytest.warns(UserWarning, match=r"cpus_per_task=64.*mad01.*56"):
        _submitter(galform_dir, log_dir, partition=SIGMA8_LIST, cpus_per_task=64)


def test_cpus_per_task_capped_by_subvolumes_does_not_warn(galform_dir, log_dir):
    _no_warnings(
        galform_dir, log_dir, partition="bluefield1", nvol="1-16", cpus_per_task=64
    )


# --------------------------------------------------------------------------
# 6/7. Directive validation
# --------------------------------------------------------------------------


@pytest.mark.parametrize("field", ["exclude", "dependency"])
@pytest.mark.parametrize("bad", ["mad01\n#SBATCH -A dp004", "mad01\r", "x\ny"])
def test_exclude_and_dependency_reject_newlines(galform_dir, log_dir, field, bad):
    with pytest.raises(ValueError, match=f"{field}.*newline"):
        _submitter(galform_dir, log_dir, **{field: bad})


@pytest.mark.parametrize("field", ["exclude", "dependency"])
def test_exclude_and_dependency_must_be_strings(galform_dir, log_dir, field):
    with pytest.raises(TypeError, match=field):
        _submitter(galform_dir, log_dir, **{field: ["mad01"]})


@pytest.mark.parametrize(
    "bad, match",
    [
        ("-pcosma8", "partition"),
        ("-Adp004", "account"),
        ("-A dp004", "account"),
        ("-c4", "cpus_per_task"),
        ("-t1:00:00", "walltime"),
        ("-Jname", "job name"),
        ("-oout.log", "log_path"),
        ("-N1", "single-node"),
        ("--nodes=1", "single-node"),
        ("--mem=8G", "mem_per_cpu"),
        ("--mem 8G", "mem_per_cpu"),
        ("--exclusive", "exclusive"),
        ("--part=cosma8", "partition"),
        ("--cpus=4", "cpus_per_task"),
    ],
)
def test_managed_options_in_any_form_are_rejected(galform_dir, log_dir, bad, match):
    with pytest.raises(ValueError, match=match):
        _submitter(galform_dir, log_dir, extra_sbatch_args=[bad])


@pytest.mark.parametrize(
    "kw, extra",
    [
        ({"exclude": "mad01"}, "--exclude=mad05"),
        ({"exclude": "mad01"}, "-xmad05"),
        ({"exclude": "mad01"}, "-x mad05"),
        ({"dependency": "afterok:1"}, "--kill-on-invalid-dep=no"),
        ({"dependency": "afterok:1"}, "--dependency=afterany:2"),
        ({"dependency": "afterok:1"}, "-dafterany:2"),
        ({"mail_user": "a@b.c"}, "--mail-type=ALL"),
    ],
)
def test_options_duplicating_a_keyword_argument_are_rejected(
    galform_dir, log_dir, kw, extra
):
    with pytest.raises(ValueError, match="already"):
        _submitter(galform_dir, log_dir, extra_sbatch_args=[extra], **kw)


@pytest.mark.parametrize(
    "extras",
    [
        ["--exclude=mad01", "-x mad05"],
        ["--kill-on-invalid-dep=yes", "--kill-on-invalid-dep=no"],
        ["--qos=short", "--qos=long"],
    ],
)
def test_repeated_extra_options_are_rejected(galform_dir, log_dir, extras):
    with pytest.raises(ValueError, match="more than once"):
        _submitter(galform_dir, log_dir, extra_sbatch_args=extras)


def test_unmanaged_options_still_pass(galform_dir, log_dir):
    s = _submitter(
        galform_dir,
        log_dir,
        extra_sbatch_args=["--exclude=mad01", "-q short", "--kill-on-invalid-dep=yes"],
    )
    script = s.create_job_script(100, tcsh_path="/x.csh")
    assert "#SBATCH --exclude=mad01" in script
    assert "#SBATCH -q short" in script


# --------------------------------------------------------------------------
# 9. /cosma8 stellar_pop_dir on partitions without /cosma8
# --------------------------------------------------------------------------


def test_cosma8_stellar_pop_from_env_on_cosma5_warns(galform_dir, log_dir, monkeypatch):
    monkeypatch.setenv("GALFORM_STELLAR_POP_DIR", "/cosma8/data/x/stellar_pop/")
    with pytest.warns(UserWarning, match=r"GALFORM_STELLAR_POP_DIR.*/cosma8.*cosma5"):
        _submitter(galform_dir, log_dir)  # default partition cosma5


def test_explicit_cosma8_stellar_pop_on_a_mixed_list_warns(galform_dir, log_dir):
    with pytest.warns(UserWarning, match=r"/cosma8.*cosma7"):
        _submitter(
            galform_dir,
            log_dir,
            partition="dine2,cosma7",
            cpus_per_task=28,
            stellar_pop_dir="/cosma8/data/x/",
        )


def test_cosma8_stellar_pop_where_every_partition_mounts_it(galform_dir, log_dir):
    _no_warnings(
        galform_dir,
        log_dir,
        partition=SIGMA8_LIST,
        exclude="mad01,mad05",
        cpus_per_task=64,
        stellar_pop_dir="/cosma8/data/x/",
    )
