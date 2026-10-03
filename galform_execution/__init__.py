"""Generate and submit GALFORM N-body runs to SLURM on COSMA.

Quick start::

    from galform_execution import GalformSubmitter

    s = GalformSubmitter("/path/to/galform", nbody_sim="Mill2", model="lc16",
                         iz=40, nvol="1-64")
    s.submit_all_jobs(dry_run=True)
"""

from importlib.metadata import PackageNotFoundError, version

from galform_execution.submit_galform_job import (
    DUST_CONFIGS,
    MODEL_CONFIGS,
    PARTITION_CONFIGS,
    SIMULATION_CONFIGS,
    DustParams,
    GalformSubmitter,
    ModelConfig,
    PartitionConfig,
    RunFlags,
    SimulationConfig,
    default_galform_dir,
    default_output_root,
    load_dust_configs,
    load_model_configs,
    load_partition_configs,
    load_run_flags_config,
    load_simulation_configs,
)

try:
    __version__ = version("galform_execution")
except PackageNotFoundError:  # running from a source tree that is not installed
    __version__ = "0+unknown"

__all__ = [
    "DUST_CONFIGS",
    "MODEL_CONFIGS",
    "PARTITION_CONFIGS",
    "SIMULATION_CONFIGS",
    "DustParams",
    "GalformSubmitter",
    "ModelConfig",
    "PartitionConfig",
    "RunFlags",
    "SimulationConfig",
    "__version__",
    "default_galform_dir",
    "default_output_root",
    "load_dust_configs",
    "load_model_configs",
    "load_partition_configs",
    "load_run_flags_config",
    "load_simulation_configs",
]
