#!/usr/bin/env python3
"""Submit GALFORM N-body tree runs to SLURM batch queue on COSMA."""

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Dict, List, Optional, Tuple


@dataclass
class SimulationConfig:
    """N-body simulation configuration (tree paths, cosmology, snapshots)."""

    nvol_range: str
    nbody_trees_dir: str
    snapshot_file: str
    aquarius_tree_file: str
    aquarius_particle_file: str
    omega0: float
    lambda0: float
    omegab: float
    h0: float
    sigma8: float
    pk_file: str
    # Optional fields with defaults
    iz_list: Optional[List[int]] = None
    volume: Optional[float] = None
    iz0: Optional[int] = None
    lbox: Optional[float] = None
    mpart: Optional[float] = None


@dataclass
class DustParams:
    """Dust model parameters for post-processing."""

    dustfile: str = "Data/dust/dust_MW_hz1.0.dat"
    emdustfile: str = "0"
    rfacburst: float = 1.0
    fcloud: float = 0.25
    tesc_disk: float = 0.001
    tesc_burst: float = 0.001
    lambda_break_disk: float = 1e4
    beta2_disk: float = 2.0
    lambda_break_burst: float = 100.0
    beta2_burst: float = 1.6


@dataclass
class ModelConfig:
    """GALFORM model configuration."""

    base_inputs_file: str
    dust_params: DustParams
    extra_replacements: Dict[str, str] = field(default_factory=dict)


@dataclass
class RunFlags:
    """Flags controlling which parts of the GALFORM pipeline to run."""

    compile: bool = False
    galform: bool = True
    neta: bool = True
    dust_props: bool = False
    lum_fun: bool = True
    samp_z0: bool = False
    cosmicsed: bool = False
    lum_fun_burst: bool = False
    samp2_z0: bool = False
    sedfit: bool = False
    agn: bool = False
    sed_agn: bool = False
    samp_mah: bool = False
    study_stellar_mass_function: bool = True


_CONFIG_DIR = Path(__file__).parent / "config"
_SIMULATION_CONFIG_PATH = _CONFIG_DIR / "simulations.json"
_DUST_CONFIG_PATH = _CONFIG_DIR / "dust_params.json"
_MODEL_CONFIG_PATH = _CONFIG_DIR / "models.json"
_RUN_FLAGS_CONFIG_PATH = _CONFIG_DIR / "run_flags.json"
_LEGACY_RUN_FLAGS_CONFIG_PATH = Path(__file__).parent / "run_flags.json"
_REDSHIFT_LISTS_DIR = _CONFIG_DIR / "redshift_lists"

_SIMULATION_CONFIG_DIR = _CONFIG_DIR / "simulations"

_TRANSIENT_SUBMIT_ERROR_MARKERS = (
    "slurm temporarily unable to accept job",
    "resource temporarily unavailable",
)


def _load_json(path: Path) -> Dict[str, dict]:
    with open(path) as fh:
        return json.load(fh)


def load_simulation_configs(
    config_path: Optional[str] = None,
) -> Dict[str, SimulationConfig]:
    """Load simulation configs from JSON.

    Supports a single JSON file or a directory containing ``*.json`` files.
    """
    if config_path:
        path = Path(config_path)
    elif _SIMULATION_CONFIG_DIR.is_dir():
        path = _SIMULATION_CONFIG_DIR
    else:
        path = _SIMULATION_CONFIG_PATH

    if path.is_dir():
        merged: Dict[str, dict] = {}
        for file_path in sorted(path.glob("*.json")):
            merged.update(_load_json(file_path))
        raw = merged
    else:
        raw = _load_json(path)

    return {
        name: SimulationConfig(
            **{k: v for k, v in cfg.items() if not k.startswith("_")}
        )
        for name, cfg in raw.items()
    }


def load_dust_configs(config_path: Optional[str] = None) -> Dict[str, DustParams]:
    """Load named dust parameter profiles from JSON."""
    path = Path(config_path) if config_path else _DUST_CONFIG_PATH
    raw = _load_json(path)
    return {name: DustParams(**cfg) for name, cfg in raw.items()}


def load_model_configs(
    dust_configs: Optional[Dict[str, DustParams]] = None,
    config_path: Optional[str] = None,
) -> Dict[str, ModelConfig]:
    """Load model configs from JSON and resolve their dust profiles."""
    dust = dust_configs if dust_configs is not None else load_dust_configs()
    path = Path(config_path) if config_path else _MODEL_CONFIG_PATH
    raw = _load_json(path)
    models: Dict[str, ModelConfig] = {}
    for name, cfg in raw.items():
        dust_profile = cfg.get("dust_profile")
        dust_params_raw = cfg.get("dust_params")
        if dust_profile:
            if dust_profile not in dust:
                raise ValueError(
                    f"Model '{name}' refers to unknown dust_profile '{dust_profile}'"
                )
            dust_params = dust[dust_profile]
        elif dust_params_raw is not None:
            dust_params = DustParams(**dust_params_raw)
        else:
            raise ValueError(
                f"Model '{name}' must define either dust_profile or dust_params"
            )

        models[name] = ModelConfig(
            base_inputs_file=cfg["base_inputs_file"],
            dust_params=dust_params,
            extra_replacements=cfg.get("extra_replacements", {}),
        )
    return models


DUST_CONFIGS = load_dust_configs()
DUST_BAUGH05 = DUST_CONFIGS["baugh05"]
DUST_LACEY16 = DUST_CONFIGS["lacey16"]
SIMULATION_CONFIGS = load_simulation_configs()
MODEL_CONFIGS = load_model_configs(DUST_CONFIGS)


def load_run_flags_config(config_path: Optional[str] = None) -> RunFlags:
    """Load RunFlags from a JSON config file.

    Looks for *config_path* if given, otherwise falls back to
    ``config/run_flags.json`` next to this module.  Returns
    ``RunFlags()`` defaults if the file is missing or malformed.
    """
    if config_path:
        path = Path(config_path)
    elif _RUN_FLAGS_CONFIG_PATH.is_file():
        path = _RUN_FLAGS_CONFIG_PATH
    else:
        path = _LEGACY_RUN_FLAGS_CONFIG_PATH
    if not path.is_file():
        return RunFlags()
    with open(path) as fh:
        data = json.load(fh)
    valid = {f.name for f in fields(RunFlags)}
    return RunFlags(**{k: v for k, v in data.items() if k in valid})


def _default_cosma_user_root() -> Path:
    """Return the default COSMA user root path."""
    user = os.environ.get("USER", Path.home().name)
    return Path(f"/cosma5/data/durham/{user}")


def _default_galform_dir() -> Path:
    """Return the default GALFORM source directory on COSMA."""
    user = os.environ.get("USER", Path.home().name)
    return Path(f"/cosma/apps/durham/{user}/galform")


def _resolve_log_path(explicit: Optional[str], output_folder_name: str) -> Path:
    """Determine the log directory.

    By default this always lives under the COSMA user root.
    """
    if explicit is not None:
        return Path(explicit)

    env_log = os.environ.get("GALFORM_LOG_PATH")
    if env_log:
        return Path(env_log)

    return _default_cosma_user_root() / output_folder_name / "logs"


def _parse_nvol_range(nvol_range: str) -> Tuple[int, int]:
    """Parse a legacy nvol range string (e.g. ``'12'`` or ``'1001-1024'``)."""
    raw = str(nvol_range).strip()
    if not raw:
        raise ValueError("nvol range must not be empty")

    if "-" in raw:
        parts = raw.split("-", maxsplit=1)
        if len(parts) != 2:
            raise ValueError(f"Invalid nvol range: {raw}")
        try:
            return int(parts[0]), int(parts[1])
        except ValueError as e:
            raise ValueError(f"Invalid nvol range (must be integers): {raw}") from e

    try:
        val = int(raw)
        return val, val
    except ValueError as e:
        raise ValueError(f"Invalid nvol range (must be integer or range): {raw}") from e


class GalformSubmitter:
    """Orchestrates GALFORM N-body runs submitted to SLURM as tcsh array jobs."""

    def __init__(
        self,
        galform_dir: str,
        nbody_sim: str = "L800",
        model: str = "gp14",
        iz: Optional[int] = None,
        nvol: Optional[str] = None,
        output_base_dir: Optional[str] = None,
        output_folder_name: str = "Galform_Out",
        log_path: Optional[str] = None,
        partition: str = "cosma5",
        account: str = "durham",
        walltime: str = "72:00:00",
        iz_list: Optional[List[int]] = None,
        nvol_range: Optional[str] = None,
        run_flags: Optional[RunFlags] = None,
        stellar_pop_dir: str = "/cosma5/data/jch/Galform/Data/stellar_pop/",
        modules: Optional[List[str]] = None,
        input_overrides: Optional[Dict[str, str]] = None,
        output_redshifts: Optional[List[float]] = None,
        output_iz_list: Optional[List[int]] = None,
        galform_exe: Optional[str] = None,
        submit_retries: int = 4,
        submit_retry_delay_s: float = 15.0,
        submit_retry_backoff: float = 2.0,
    ):
        self.galform_dir = Path(galform_dir)
        self.nbody_sim = nbody_sim
        self.model = model
        self.iz = iz
        self.nvol = nvol
        self.partition = partition
        self.account = account
        self.walltime = walltime
        self.stellar_pop_dir = stellar_pop_dir
        self.galform_exe_override = Path(galform_exe) if galform_exe else None
        self.run_flags = run_flags if run_flags is not None else load_run_flags_config()
        self.output_folder_name = output_folder_name
        self.input_overrides = dict(input_overrides) if input_overrides else {}
        self.output_redshifts = (
            list(output_redshifts) if output_redshifts is not None else None
        )
        self.output_iz_list = (
            list(output_iz_list) if output_iz_list is not None else None
        )
        self.submit_retries = max(1, int(submit_retries))
        self.submit_retry_delay_s = max(0.0, float(submit_retry_delay_s))
        self.submit_retry_backoff = max(1.0, float(submit_retry_backoff))
        self._snapshot_redshift_cache: Optional[Dict[int, float]] = None

        if self.output_redshifts is not None and self.output_iz_list is not None:
            raise ValueError("Specify only one of output_redshifts and output_iz_list")

        # Multi-output tree building requires keeping descendants across outputs.
        if self._builds_galaxy_trees() and self._uses_multi_output():
            self.input_overrides.setdefault("mgalmin_output_descendants", ".true.")

        # Modules
        if modules is not None:
            self.modules = modules
        else:
            self.modules = [
                "intel_comp/2024.2.0",
                "compiler-rt",
                "tbb",
                "compiler",
                "mpi",
            ]

        # Log path
        self.log_path = _resolve_log_path(log_path, output_folder_name)

        # Output base directory
        if output_base_dir is not None:
            self.output_base_dir = Path(output_base_dir)
        else:
            self.output_base_dir = _default_cosma_user_root()
        self.models_dir = self.output_base_dir / output_folder_name / nbody_sim

        # Resolve simulation config
        if nbody_sim in SIMULATION_CONFIGS:
            self.sim_config = SIMULATION_CONFIGS[nbody_sim]
            default_iz_list = (
                list(self.sim_config.iz_list) if self.sim_config.iz_list else []
            )
            self.iz_list = iz_list if iz_list is not None else default_iz_list
            if nvol is not None and nvol_range is not None:
                raise ValueError("Specify only one of nvol and nvol_range")
            resolved_nvol_range = nvol if nvol is not None else nvol_range
            self.nvol_range = (
                resolved_nvol_range
                if resolved_nvol_range is not None
                else self.sim_config.nvol_range
            )
        else:
            if nvol is not None and nvol_range is not None:
                raise ValueError("Specify only one of nvol and nvol_range")
            resolved_nvol_range = nvol if nvol is not None else nvol_range
            if iz_list is None or resolved_nvol_range is None:
                raise ValueError(
                    f"Unknown simulation '{nbody_sim}'. "
                    "Provide iz_list and nvol explicitly."
                )
            self.sim_config = None
            self.iz_list = iz_list
            self.nvol_range = resolved_nvol_range

        # Resolve model config
        if model in MODEL_CONFIGS:
            self.model_config = MODEL_CONFIGS[model]
        else:
            self.model_config = None

        if self.iz is not None:
            self.iz_list = [self.iz]

        self.nvol_start, self.nvol_end = _parse_nvol_range(self.nvol_range)
        self.nvol_count = self.nvol_end - self.nvol_start + 1
        # Use compact task IDs to avoid SLURM sites that reject large array indices.
        self.slurm_array_range = f"1-{self.nvol_count}"

        # Validate
        if not self.galform_dir.is_dir():
            raise FileNotFoundError(f"GALFORM directory not found: {self.galform_dir}")
        if self.galform_exe_override:
            galform_exe = self.galform_exe_override
        else:
            galform_exe = self.galform_dir / "build" / "galform2"
        if not galform_exe.exists():
            raise FileNotFoundError(f"GALFORM executable not found: {galform_exe}")

    @staticmethod
    def _bool_to_csh(value: bool) -> str:
        return "true" if value else "false"

    def _generate_run_flags_block(self) -> str:
        rf = self.run_flags
        lines = [
            "# ---- run flags (set by GalformSubmitter) ----",
            f"set compile     = {self._bool_to_csh(rf.compile)}",
            f"set galform     = {self._bool_to_csh(rf.galform)}",
            f"set neta        = {self._bool_to_csh(rf.neta)}",
            f"set dust_props  = {self._bool_to_csh(rf.dust_props)}",
            f"set lum_fun     = {self._bool_to_csh(rf.lum_fun)}",
            f"set samp_z0     = {self._bool_to_csh(rf.samp_z0)}",
            f"set cosmicsed   = {self._bool_to_csh(rf.cosmicsed)}",
            f"set lum_fun_burst = {self._bool_to_csh(rf.lum_fun_burst)}",
            f"set samp2_z0      = {self._bool_to_csh(rf.samp2_z0)}",
            f"set sedfit        = {self._bool_to_csh(rf.sedfit)}",
            f"set agn           = {self._bool_to_csh(rf.agn)}",
            f"set sed_agn       = {self._bool_to_csh(rf.sed_agn)}",
            f"set samp_mah      = {self._bool_to_csh(rf.samp_mah)}",
            f"set study_stellar_mass_function = {self._bool_to_csh(rf.study_stellar_mass_function)}",
        ]
        return "\n".join(lines)

    def _generate_dust_params_block(self, dust: DustParams) -> str:
        lines = [
            "# ---- dust parameters ----",
            f"set dustfile = {dust.dustfile}",
            f"set emdustfile = {dust.emdustfile}",
            f"set rfacburst  = {dust.rfacburst}",
            f"set fcloud = {dust.fcloud}",
            f"set tesc_disk  = {dust.tesc_disk}",
            f"set tesc_burst = {dust.tesc_burst}",
            f"set lambda_break_disk = {dust.lambda_break_disk}",
            f"set beta2_disk = {dust.beta2_disk}",
            f"set lambda_break_burst = {dust.lambda_break_burst}",
            f"set beta2_burst = {dust.beta2_burst}",
        ]
        return "\n".join(lines)

    def _generate_simulation_block(self, sim: SimulationConfig) -> str:
        if sim.volume is None:
            raise ValueError(
                f"SimulationConfig for '{self.nbody_sim}' has no 'volume' — "
                "set it in the simulation JSON before submitting."
            )
        if sim.iz0 is None:
            raise ValueError(
                f"SimulationConfig for '{self.nbody_sim}' has no 'iz0' — "
                "set it in the simulation JSON before submitting."
            )

        snapshot_file = Path(sim.snapshot_file)
        if not snapshot_file.is_absolute():
            snapshot_file = _REDSHIFT_LISTS_DIR / snapshot_file

        lines = [
            "# ---- N-body simulation parameters ----",
            f"set snapshot_file          = {snapshot_file}",
            f"set aquarius_tree_file     = {sim.aquarius_tree_file}",
            f"set aquarius_particle_file = {sim.aquarius_particle_file}",
            f"set volume     = {sim.volume}",
            f"set omega0     = {sim.omega0}",
            f"set lambda0    = {sim.lambda0}",
            f"set omegab     = {sim.omegab}",
            f"set h0         = {sim.h0}",
            f"set sigma8     = {sim.sigma8}",
            f"set PKfile     = {sim.pk_file}",
            f"set iz0        = {sim.iz0}",
        ]
        if sim.lbox is not None:
            lines.append(f"set lbox  = {sim.lbox}")
        if sim.mpart is not None:
            lines.append(f"set mpart = {sim.mpart}")
        return "\n".join(lines)

    def _generate_model_setup_block(self) -> str:
        """Generate the block that copies the base .input.ref file and applies modifications."""
        if self.model_config is None:
            raise ValueError(
                f"Unknown model '{self.model}'. "
                "Add it to MODEL_CONFIGS or provide a custom model config."
            )
        mc = self.model_config
        lines = [
            "# ---- model parameter file setup ----",
            f"set base_inputs_file = {mc.base_inputs_file}",
            "set galform_inputs_file = ./params/${Nbody_sim}_${model}_iz${iz}_ivol${ivol}.input.temp",
            "\\mkdir -p ./params",
            "cp $base_inputs_file $galform_inputs_file",
        ]
        for name, value in mc.extra_replacements.items():
            lines.append(f"./replace_variable.csh $galform_inputs_file {name} {value}")
        return "\n".join(lines)

    def _generate_parameter_overrides_block(self) -> str:
        """Generate the block that injects simulation/cosmology params into the input file."""
        output_redshifts = self._resolve_output_redshifts()
        if output_redshifts is None:
            nout_value = "1"
            zout_value = "$z"
        else:
            nout_value = str(len(output_redshifts))
            zout_value = " ".join(
                self._format_float_for_input(zout) for zout in output_redshifts
            )

        lines = [
            "# ---- override parameters for N-body run ----",
            f"./replace_variable.csh $galform_inputs_file stellar_pop_dir {self.stellar_pop_dir}",
            "./replace_variable.csh $galform_inputs_file append_ivolume .true.",
            "./replace_variable.csh $galform_inputs_file aquarius_tree_file $aquarius_tree_file",
        ]
        if self.nbody_sim != "nifty62.5":
            lines.append(
                "./replace_variable.csh $galform_inputs_file aquarius_particle_file $aquarius_particle_file"
            )
        else:
            lines.append(
                "./delete_variable.csh $galform_inputs_file aquarius_particle_file"
            )
        lines += [
            "./replace_variable.csh $galform_inputs_file volume $volume",
            "./replace_variable.csh $galform_inputs_file omega0 $omega0",
            "./replace_variable.csh $galform_inputs_file lambda0 $lambda0",
            "./replace_variable.csh $galform_inputs_file omegab $omegab",
            "./replace_variable.csh $galform_inputs_file h0 $h0",
            "./replace_variable.csh $galform_inputs_file sigma8 $sigma8",
            "./replace_variable.csh $galform_inputs_file itrans -1",
            "./replace_variable.csh $galform_inputs_file PKfile $PKfile",
            f"./replace_variable.csh $galform_inputs_file nout {nout_value}",
            f"./replace_vector.csh $galform_inputs_file zout {zout_value}",
        ]

        # Inject optional user-provided parameter overrides.
        for name, value in self.input_overrides.items():
            lines.append(f"./replace_variable.csh $galform_inputs_file {name} {value}")

        return "\n".join(lines)

    @staticmethod
    def _format_float_for_input(value: float) -> str:
        """Format numeric input values compactly for GALFORM parameter files."""
        return f"{float(value):.12g}"

    @staticmethod
    def _is_truthy_fortran(value: str) -> bool:
        v = value.strip().lower()
        return v in {".true.", "true", "t"}

    def _builds_galaxy_trees(self) -> bool:
        raw = self.input_overrides.get("build_galaxy_trees")
        return bool(raw is not None and self._is_truthy_fortran(raw))

    def _uses_multi_output(self) -> bool:
        if self.output_redshifts is not None:
            return len(self.output_redshifts) > 1
        if self.output_iz_list is not None:
            return len(self.output_iz_list) > 1
        return False

    def _load_snapshot_redshifts(self) -> Dict[int, float]:
        if self._snapshot_redshift_cache is not None:
            return self._snapshot_redshift_cache
        if self.sim_config is None:
            raise ValueError("Simulation config is required to resolve output_iz_list")

        snapshot_map: Dict[int, float] = {}
        snapshot_file = Path(self.sim_config.snapshot_file)
        if not snapshot_file.is_absolute():
            snapshot_file = _REDSHIFT_LISTS_DIR / snapshot_file

        if not snapshot_file.exists():
            raise FileNotFoundError(f"Snapshot file not found: {snapshot_file}")

        with open(snapshot_file) as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split()
                if len(parts) < 2:
                    continue
                try:
                    snapshot_map[int(parts[0])] = float(parts[1])
                except ValueError:
                    continue

        self._snapshot_redshift_cache = snapshot_map
        return snapshot_map

    def _resolve_output_redshifts(self) -> Optional[List[float]]:
        if self.output_redshifts is not None:
            return [float(z) for z in self.output_redshifts]
        if self.output_iz_list is None:
            return None

        snapshot_map = self._load_snapshot_redshifts()
        resolved: List[float] = []
        missing: List[int] = []
        for iz in self.output_iz_list:
            if iz not in snapshot_map:
                missing.append(iz)
            else:
                resolved.append(snapshot_map[iz])
        if missing:
            raise ValueError(
                f"Could not resolve redshift(s) for output_iz_list entries: {missing}"
            )
        return resolved

    def _generate_bands_block(self) -> str:
        """Generate the photometric bands and emission lines configuration."""
        return r"""# ---- photometric bands ----
# Rest frame bands
set idband      = (200 201 127 51 52 53 54 47 48 49 6 202 203 204 205 206 212 213 214 215 216)
set iselect     = (0   0   0   0  0  0  0  0  0  0  0 0   0   0   0   0   0   0   0   0   0  )
# Special bands
set idband_add  = (52 52 1001 1002 1005 1005)
set iselect_add = (2  3  0    0    0    2)
set idband  = ( $idband  $idband_add )
set iselect = ( $iselect $iselect_add )
# Observer frame bands
set idband_add  = (200 201 127 51 52 53 54 47 48 49 6 202 203 204 205 206 212 213 214 215 216)
set iselect_add = (1   1   1   1  1  1  1  1  1  1  1 1   1   1   1   1   1   1   1   1   1  )
set idband  = ( $idband  $idband_add )
set iselect = ( $iselect $iselect_add )
# Top hat bands for dust emission (TH0-TH14)
set idband_add  = (185 186 187 188 189 190 191 192 193 194 195 196 197 198 199)
set iselect_add = (0   0   0   0   0   0   0   0   0   0   0   0   0   0   0)
set idband  = ( $idband  $idband_add )
set iselect = ( $iselect $iselect_add )
# Observer frame NIRCAM bands N1-N8
set idband_add  = (440 441 442 443 444 445 446 447)
set iselect_add = (1   1   1   1   1   1   1   1  )
set idband  = ( $idband  $idband_add )
set iselect = ( $iselect $iselect_add )
# Rest frame NIRCAM bands N1-N8
set idband_add  = (440 441 442 443 444 445 446 447)
set iselect_add = (0   0   0   0   0   0   0   0  )
set idband  = ( $idband  $idband_add )
set iselect = ( $iselect $iselect_add )
# Additional bands for sedfit / cosmicsed
set idband_add  = (232 233 164 165 166 167 294 295 297 294 295 297 200 201 164 165 166 167)
set iselect_add = (1   1   1   1   1   1   0   0   0   1   1   1   1   1   0   0   0   0  )
set idband  = ( $idband  $idband_add )
set iselect = ( $iselect $iselect_add )
# DESI Legacy Survey bands (DECam: DES-g=350, DES-r=351, DES-z=353) - rest frame
set idband_add  = (350 351 353)
set iselect_add = (0   0   0  )
set idband  = ( $idband  $idband_add )
set iselect = ( $iselect $iselect_add )
# DESI Legacy Survey bands - observer frame
set idband_add  = (350 351 353)
set iselect_add = (1   1   1  )
set idband  = ( $idband  $idband_add )
set iselect = ( $iselect $iselect_add )

set nband = `echo $idband | wc -w`
./replace_vector.csh $galform_inputs_file idband $idband
./replace_vector.csh $galform_inputs_file iselect $iselect

# ---- emission lines ----
./replace_variable.csh $galform_inputs_file emlines .true.
set lines = (Lyalpha Halpha Hbeta OII3727)
set nline = `echo $lines | wc -w`
./replace_variable.csh $galform_inputs_file nline $nline
./replace_vector.csh $galform_inputs_file lines $lines
"""

    def _generate_run_galform_block(self) -> str:
        """Generate the GALFORM execution and post-processing sections."""
        return r"""
############################################################################
# RUN GALFORM

if( $galform == true ) then
    echo '******************************************************************'
    echo running GALFORM
    $GALFORM2_EXE $output_dir $galform_inputs_file  -ivolume=$ivol
    if (( $status != 0 ) || ! ( -e ${output_dir}/global )) then
        echo Galform run failed, aborting script
        exit
    endif
endif

############################################################################
# CREATE ETA FILES  for extinction by dust clouds

if( $neta == true ) then
    echo '******************************************************************'
    echo running NETA_AVE
    set dustparfile = $output_dir/dustpars
    echo dustfile = $dustfile      >! $dustparfile
    echo emdustfile = $emdustfile  >> $dustparfile
    echo rfacburst = $rfacburst    >> $dustparfile
    echo fcloud = $fcloud          >> $dustparfile
    echo tesc_disk = $tesc_disk    >> $dustparfile
    echo tesc_burst = $tesc_burst  >> $dustparfile
    echo upsilon2 = $upsilon2      >> $dustparfile
    echo lambda_break_disk = $lambda_break_disk    >> $dustparfile
    echo beta2_disk = $beta2_disk      >> $dustparfile
    echo lambda_break_burst = $lambda_break_burst  >> $dustparfile
    echo beta2_burst = $beta2_burst    >> $dustparfile

    $NETA_AVE_DISK_EXE <<EOF
    $output_dir
    $tesc_disk
    1
EOF
    $NETA_AVE_BURST_EXE <<EOF
    $output_dir
    $tesc_burst
    1
EOF
endif

############################################################################
# CALCULATE LUMINOSITY FUNCTIONS

if ( $lum_fun == 'true' ) then
    echo '******************************************************************'
    echo running LUM_FUN
    set lffile = $output_dir/gal
    $SAMPLE_GALS_EXE  odir $output_dir  iseed $ISEED2  file $lffile redshift $z \
    mag_sys AB  volume 0  upsilon $upsilon2 \
    dust $dustfile $emdustfile $rfacburst $fcloud $tesc_disk $tesc_burst \
    dust_SED $lambda_break_disk $beta2_disk $lambda_break_burst $beta2_burst \
    dustem 24r 24o 60r 60o 100r 100o 160r 160o 250r 250o 350r 350o 500r 500o 850r 850o 870r 870o \
    lum_fun
    set lffile = $output_dir/gal.Vega
    $SAMPLE_GALS_EXE  odir $output_dir  iseed $ISEED2  file $lffile  redshift $z \
    mag_sys vega  volume 0  upsilon $upsilon2 \
    dust $dustfile $emdustfile $rfacburst $fcloud $tesc_disk $tesc_burst \
    lum_fun
endif

############################################################################
# STELLAR MASS FUNCTION

if ( $study_stellar_mass_function == true ) then
    echo creating smass.cat
    set file = $output_dir/smass.cat
    set vol = 0
    $SAMPLE_GALS_EXE  odir $output_dir  iseed $ISEED2  file $file  redshift $z \
    mag_sys AB  volume 0  upsilon $upsilon2 \
    dust $dustfile $emdustfile $rfacburst $fcloud $tesc_disk $tesc_burst \
    props weight mstars_tot mstars_allburst
endif

echo 'The end'
rm -f $galform_inputs_file
exit
"""

    def create_slurm_script(self, iz: int) -> str:
        """Generate the complete SLURM/tcsh batch script for snapshot iz."""
        if self.sim_config is None:
            raise ValueError(
                f"No simulation config for '{self.nbody_sim}'. "
                "Provide a SimulationConfig explicitly."
            )
        if self.model_config is None:
            raise ValueError(
                f"No model config for '{self.model}'. "
                "Add it to MODEL_CONFIGS or provide one explicitly."
            )

        jobname = f"{self.nbody_sim}.{self.model}"
        logname = self.log_path / self.nbody_sim / f"{self.model}.%A.%a.log"

        # Ensure log directory exists (best-effort)
        try:
            logname.parent.mkdir(parents=True, exist_ok=True)
        except PermissionError:
            pass

        # Load COSMA modules without relying on interactive tcsh startup files.
        modulecmd = "/cosma/local/Modules/default/libexec/modulecmd.tcl"
        module_lines = f"eval `/usr/bin/tclsh {modulecmd} csh purge`\n" + "\n".join(
            f"eval `/usr/bin/tclsh {modulecmd} csh load {m}`" for m in self.modules
        )

        custom_exe_env = ""
        if self.galform_exe_override:
            custom_exe_env = f"setenv GALFORM2_EXE_OVERRIDE {self.galform_exe_override}"

        script = f"""#!/bin/tcsh -ef
#
#SBATCH --ntasks 1
#SBATCH -J {jobname}
#SBATCH -o {logname}
#SBATCH -p {self.partition}
#SBATCH -A {self.account}
#SBATCH -t {self.walltime}
#

# ---- environment ----
{module_lines}

# ---- custom executable ----
{custom_exe_env}

# Ensure unformatted big-endian stellar population files are readable.
# Only set defaults if not already defined by the user environment.
if ( ! $?GFORTRAN_CONVERT_UNIT ) then
    setenv GFORTRAN_CONVERT_UNIT big_endian
endif
if ( ! $?F_UFMTENDIAN ) then
    setenv F_UFMTENDIAN big
endif

unlimit stacksize
unlimit datasize

# ---- parameters from GalformSubmitter ----
set model     = {self.model}
set Nbody_sim = {self.nbody_sim}
set iz        = {iz}
@ slurm_task_id = ${{SLURM_ARRAY_TASK_ID}}
@ ivol        = $slurm_task_id + {self.nvol_start} - 2

# Change to GALFORM source directory (scripts use relative paths)
cd {self.galform_dir}
set src_dir = `pwd`
set path = ( $src_dir $path )
set build_dir = ./build/

{self._generate_run_flags_block()}

set models_dir = {self.models_dir}
mkdir -p $models_dir
set upsilon2 = 1
set ISEED2 = -81027

{self._generate_simulation_block(self.sim_config)}
{self._generate_dust_params_block(self.model_config.dust_params)}

# ---- extract redshift from snapshot file ----
set z = `awk -v iz=$iz '$1==iz {{print $2}}' $snapshot_file`
set z0 = `awk -v iz=${{iz0}} '$1==iz {{print $2}}' $snapshot_file`
if ($z == '') then
    echo no redshift for snapshot $iz in file $snapshot_file
    exit
endif
echo running snapshot iz= $iz,   redshift z= $z

set zname = `echo $z | awk '{{printf( "%6.3f",$1)}}'`

set model_dir = $models_dir/$model
mkdir -p $model_dir
set output_dir = $model_dir/iz${{iz}}/ivol${{ivol}}
mkdir -p $output_dir
echo iz= $iz  z= $zname >! $model_dir/iz${{iz}}/zsnap.dat

# ---- executables ----
set build_dir = ./build/
set GALFORM2_EXE       = ${{build_dir}}/galform2
if ( $?GALFORM2_EXE_OVERRIDE ) then
    set GALFORM2_EXE = $GALFORM2_EXE_OVERRIDE
endif
set NETA_AVE_DISK_EXE  = ${{build_dir}}/neta_ave_disk
set NETA_AVE_BURST_EXE = ${{build_dir}}/neta_ave_burst
set SAMPLE_GALS_EXE    = ${{build_dir}}/sample_gals

# ---- construct GALFORM input parameters file ----
{self._generate_model_setup_block()}
{self._generate_parameter_overrides_block()}

# ---- photometric bands & emission lines ----
{self._generate_bands_block()}

# ---- execute GALFORM & post-processing ----
{self._generate_run_galform_block()}
"""
        return script

    def create_packed_job_script(
        self, iz: int, tcsh_path: str, mem_per_cpu: int = 4000
    ) -> str:
        """Generate a bash wrapper that runs all subvolumes in a single SLURM slot.

        Instead of a SLURM array (one task per subvolume), this script requests
        --cpus-per-task=<nvol_count> and forks each subvolume as a background
        process with SLURM_ARRAY_TASK_ID set via ``env``.  The tcsh script at
        *tcsh_path* is referenced by path and must be written to disk before
        the bash job starts (e.g. via ``create_slurm_script``).

        Args:
            iz: Snapshot index (informational; used by the referenced tcsh script).
            tcsh_path: Absolute path to the tcsh GALFORM script on disk.
            mem_per_cpu: Memory per CPU in MB passed to ``--mem-per-cpu``.
        """
        jobname = f"{self.nbody_sim}.{self.model}"
        logname = self.log_path / self.nbody_sim / f"{self.model}.%j.log"

        try:
            logname.parent.mkdir(parents=True, exist_ok=True)
        except PermissionError:
            pass

        script = f"""#!/bin/bash
#SBATCH --ntasks=1
#SBATCH --cpus-per-task={self.nvol_count}
#SBATCH --mem-per-cpu={mem_per_cpu}
#SBATCH -J {jobname}
#SBATCH -o {logname}
#SBATCH -p {self.partition}
#SBATCH -A {self.account}
#SBATCH -t {self.walltime}

for task_id in $(seq 1 {self.nvol_count}); do
    env SLURM_ARRAY_TASK_ID=$task_id tcsh -ef {tcsh_path} &
done
wait
"""
        return script

    def _sbatch_with_retry(
        self, script_content: str, iz: int, extra_args: Optional[List[str]] = None
    ) -> Optional[str]:
        """Submit *script_content* via sbatch, retrying on transient scheduler errors."""
        cmd = ["sbatch"] + (extra_args or [])
        for attempt in range(1, self.submit_retries + 1):
            try:
                result = subprocess.run(
                    cmd,
                    input=script_content.encode(),
                    capture_output=True,
                    check=True,
                )
                output = result.stdout.decode().strip()
                if "Submitted batch job" in output:
                    return output.split()[-1]
                return None
            except subprocess.CalledProcessError as e:
                stdout = e.stdout.decode() if e.stdout else ""
                stderr = e.stderr.decode() if e.stderr else ""
                combined = f"{stdout}\n{stderr}".lower()
                is_transient = any(
                    marker in combined for marker in _TRANSIENT_SUBMIT_ERROR_MARKERS
                )
                is_last_attempt = attempt >= self.submit_retries
                if not is_transient or is_last_attempt:
                    raise RuntimeError(
                        f"Failed to submit job for iz={iz}: {e}\n"
                        f"STDOUT: {stdout}\nSTDERR: {stderr}"
                    ) from e
                delay_s = self.submit_retry_delay_s * (
                    self.submit_retry_backoff ** (attempt - 1)
                )
                print(
                    f"Transient SLURM submission error for iz={iz}. "
                    f"Retrying in {delay_s:.1f}s "
                    f"(attempt {attempt + 1}/{self.submit_retries})."
                )
                time.sleep(delay_s)

    def submit_job(self, iz: int, dry_run: bool = False) -> Optional[str]:
        """Submit a SLURM array job for snapshot iz; returns job ID or None if dry_run."""
        script_content = self.create_slurm_script(iz)

        if dry_run:
            print(f"DRY RUN: iz={iz}, nvol_range={self.nvol_range}")
            print(script_content)
            return None

        return self._sbatch_with_retry(
            script_content, iz, extra_args=[f"--array={self.slurm_array_range}"]
        )

    def submit_packed_job(
        self,
        iz: int,
        tcsh_path: str,
        mem_per_cpu: int = 4000,
        dry_run: bool = False,
    ) -> Optional[str]:
        """Submit a packed (single-slot) SLURM job for snapshot iz.

        Writes the tcsh script to *tcsh_path* on disk, then submits the bash
        wrapper generated by ``create_packed_job_script``.  Returns the SLURM
        job ID, or None if *dry_run* is True.

        Args:
            iz: Snapshot index.
            tcsh_path: Path where the inner tcsh script will be written.
            mem_per_cpu: Memory per CPU in MB (forwarded to the bash wrapper).
            dry_run: If True, print scripts and return None without submitting.
        """
        tcsh_script = self.create_slurm_script(iz)
        bash_script = self.create_packed_job_script(iz, tcsh_path, mem_per_cpu)

        if dry_run:
            print(
                f"DRY RUN (packed): iz={iz}, nvol_range={self.nvol_range}, "
                f"tcsh_path={tcsh_path}"
            )
            print("=== tcsh script ===")
            print(tcsh_script)
            print("=== bash wrapper ===")
            print(bash_script)
            return None

        tcsh_file = Path(tcsh_path)
        tcsh_file.parent.mkdir(parents=True, exist_ok=True)
        tcsh_file.write_text(tcsh_script)

        return self._sbatch_with_retry(bash_script, iz)

    def submit_all_jobs(self, dry_run: bool = False) -> List[str]:
        """Submit SLURM jobs for all snapshots in iz_list; returns list of job IDs."""
        job_ids = []
        for iz in self.iz_list:
            job_id = self.submit_job(iz, dry_run=dry_run)
            if job_id:
                job_ids.append(job_id)
        return job_ids


def main():
    parser = argparse.ArgumentParser(
        description="Submit GALFORM N-body runs to SLURM batch queue on COSMA",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Submit jobs for L800 simulation with gp14 model
  %(prog)s /path/to/galform

  # Submit jobs with custom simulation & model
  %(prog)s /path/to/galform --nbody-sim MillGas --model b06

  # Dry run to preview what would be submitted
    %(prog)s /path/to/galform --iz 271 --nvol 12 --dry-run

    # Custom snapshot list and subvolume range
    %(prog)s /path/to/galform --iz-list 100 120 155 --nvol 1-50

  # Enable/disable pipeline stages
  %(prog)s /path/to/galform --run-galform --no-neta --no-lum-fun
        """,
    )

    parser.add_argument(
        "galform_dir",
        nargs="?",
        default=str(_default_galform_dir()),
        help="Path to the GALFORM source directory "
        f"(default: {_default_galform_dir()}; contains build/, *.input.ref, etc.)",
    )

    parser.add_argument(
        "--nbody-sim", default="L800", help="N-body simulation name (default: L800)"
    )
    parser.add_argument(
        "--model", default="gp14", help="GALFORM model name (default: gp14)"
    )
    parser.add_argument("--iz", type=int, help="Single snapshot number to submit")
    parser.add_argument(
        "--nvol",
        help='Subvolume range for SLURM array submission (e.g. "1-10" or "12")',
    )
    parser.add_argument(
        "--output-base-dir",
        help="Root directory for GALFORM outputs (default: /cosma5/data/durham/$USER)",
    )
    parser.add_argument(
        "--output-folder-name",
        default="Galform_Out",
        help="Folder name under the base output directory (default: Galform_Out)",
    )
    parser.add_argument("--log-path", help="Directory for SLURM log files")
    parser.add_argument(
        "--galform-exe",
        help="Path to a custom GALFORM executable (overrides build/galform2)",
    )
    parser.add_argument(
        "--partition", default="cosma5", help="SLURM partition (default: cosma5)"
    )
    parser.add_argument(
        "--account", default="durham", help="SLURM account (default: durham)"
    )
    parser.add_argument(
        "--walltime", default="72:00:00", help="Job wall-time (default: 72:00:00)"
    )
    parser.add_argument(
        "--iz-list", type=int, nargs="+", help="Override default snapshot list"
    )
    parser.add_argument(
        "--output-iz-list",
        type=int,
        nargs="+",
        help="Output multiple snapshots in one run (sets nout/zout)",
    )
    parser.add_argument(
        "--output-z-list",
        type=float,
        nargs="+",
        help="Output multiple redshifts in one run (sets nout/zout)",
    )
    parser.add_argument("--nvol-range", help="Deprecated alias for --nvol")
    parser.add_argument(
        "--run-flags-config",
        help="Path to a JSON file overriding default run flags "
        "(defaults to config/run_flags.json next to this script)",
    )

    # Run-flag toggles — these override the defaults from run_flags.json
    flag_group = parser.add_argument_group("pipeline stages")
    flag_group.add_argument(
        "--run-galform",
        action="store_true",
        default=False,
        help="Force galform2 executable on (overrides JSON default)",
    )
    flag_group.add_argument(
        "--no-galform",
        action="store_true",
        default=False,
        help="Force galform2 executable off (overrides JSON default)",
    )
    flag_group.add_argument(
        "--no-neta", action="store_true", help="Disable neta_ave dust calculation"
    )
    flag_group.add_argument(
        "--no-lum-fun",
        action="store_true",
        help="Disable luminosity function calculation",
    )
    flag_group.add_argument(
        "--no-study-smf",
        action="store_true",
        help="Disable stellar mass function output",
    )
    flag_group.add_argument(
        "--run-dust-props", action="store_true", help="Enable dust properties output"
    )
    flag_group.add_argument(
        "--run-samp-z0", action="store_true", help="Enable z=0 galaxy sample output"
    )

    tree_group = parser.add_argument_group("tree-output toggles")
    tree_group.add_argument(
        "--build-galaxy-trees",
        action="store_true",
        help="Set build_galaxy_trees = .true. in GALFORM input",
    )
    tree_group.add_argument(
        "--no-build-galaxy-trees",
        action="store_true",
        help="Set build_galaxy_trees = .false. in GALFORM input",
    )
    tree_group.add_argument(
        "--output-halo-trees",
        action="store_true",
        help="Set output_halo_trees = .true. in GALFORM input",
    )
    tree_group.add_argument(
        "--no-output-halo-trees",
        action="store_true",
        help="Set output_halo_trees = .false. in GALFORM input",
    )

    parser.add_argument(
        "--dry-run", action="store_true", help="Print job scripts without submitting"
    )
    parser.add_argument(
        "--list-simulations",
        action="store_true",
        help="List available simulation configurations and exit",
    )
    parser.add_argument(
        "--list-models",
        action="store_true",
        help="List available model configurations and exit",
    )

    args = parser.parse_args()

    if args.list_simulations:
        print("Available simulation configurations:")
        fmt = f"{'Simulation':<20} {'Snapshots (iz)':<40} {'Subvolumes':<15}"
        print(fmt)
        print("-" * 75)
        for name, cfg in sorted(SIMULATION_CONFIGS.items()):
            iz_str = str(cfg.iz_list) if cfg.iz_list else "(not set)"
            if len(iz_str) > 37:
                iz_str = iz_str[:34] + "..."
            print(f"{name:<20} {iz_str:<40} {cfg.nvol_range:<15}")
        return 0

    if args.list_models:
        print("Available model configurations:")
        fmt = f"{'Model':<25} {'Base Input File':<45} {'Dust'}"
        print(fmt)
        print("-" * 80)
        for name, cfg in sorted(MODEL_CONFIGS.items()):
            dust_label = f"fcloud={cfg.dust_params.fcloud}"
            print(f"{name:<25} {cfg.base_inputs_file:<45} {dust_label}")
        return 0

    # Load defaults from JSON, then apply any explicit CLI overrides on top.
    _json_defaults = load_run_flags_config(args.run_flags_config)
    run_flags = RunFlags(
        galform=(
            True
            if args.run_galform
            else (False if args.no_galform else _json_defaults.galform)
        ),
        neta=False if args.no_neta else _json_defaults.neta,
        lum_fun=False if args.no_lum_fun else _json_defaults.lum_fun,
        study_stellar_mass_function=(
            False if args.no_study_smf else _json_defaults.study_stellar_mass_function
        ),
        dust_props=True if args.run_dust_props else _json_defaults.dust_props,
        samp_z0=True if args.run_samp_z0 else _json_defaults.samp_z0,
    )

    input_overrides: Dict[str, str] = {}
    if args.build_galaxy_trees and args.no_build_galaxy_trees:
        raise ValueError(
            "Use only one of --build-galaxy-trees or --no-build-galaxy-trees"
        )
    if args.output_halo_trees and args.no_output_halo_trees:
        raise ValueError(
            "Use only one of --output-halo-trees or --no-output-halo-trees"
        )
    if args.output_iz_list and args.output_z_list:
        raise ValueError("Use only one of --output-iz-list or --output-z-list")

    if args.build_galaxy_trees:
        input_overrides["build_galaxy_trees"] = ".true."
    if args.no_build_galaxy_trees:
        input_overrides["build_galaxy_trees"] = ".false."

    if args.output_halo_trees:
        input_overrides["output_halo_trees"] = ".true."
    if args.no_output_halo_trees:
        input_overrides["output_halo_trees"] = ".false."

    try:
        submitter = GalformSubmitter(
            galform_dir=args.galform_dir,
            nbody_sim=args.nbody_sim,
            model=args.model,
            iz=args.iz,
            nvol=args.nvol,
            output_base_dir=args.output_base_dir,
            output_folder_name=args.output_folder_name,
            log_path=args.log_path,
            partition=args.partition,
            account=args.account,
            walltime=args.walltime,
            iz_list=args.iz_list,
            nvol_range=args.nvol_range,
            run_flags=run_flags,
            input_overrides=input_overrides,
            output_redshifts=args.output_z_list,
            output_iz_list=args.output_iz_list,
            galform_exe=args.galform_exe,
        )
        submitter.submit_all_jobs(dry_run=args.dry_run)
        return 0

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
