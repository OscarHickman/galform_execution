# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies
pip install -r requirements.txt
pip install -e .        # install as editable package

# Run all tests
pytest tests

# Run a single test
pytest tests/test_submit_galform_job.py::test_create_slurm_script -v

# Lint
ruff check galform_execution

# Preview a job submission without submitting (using console script)
submit-galform-job --nbody-sim Mill2 --model lc16 --iz 40 --nvol 1-64 --dry-run

# Preview using python module
python -m galform_execution --nbody-sim Mill2 --model lc16 --iz 40 --nvol 1-64 --dry-run

# List available simulations / models
submit-galform-job --list-simulations
submit-galform-job --list-models
```

## Architecture

The library is structured as a Python package `galform_execution`. The core logic resides in `galform_execution/submit_galform_job.py`. It replaces the legacy `qsub_galform_Nbody_example.csh` + `run_galform_Nbody_example.csh` workflow by generating complete tcsh SLURM batch scripts from Python-controlled configuration.

### Core class: `GalformSubmitter`

`GalformSubmitter.__init__` resolves three layers of configuration:

1. **Simulation config** (`SimulationConfig`) — N-body tree paths, cosmological parameters, snapshot list, subvolume range. Loaded from `galform_execution/config/simulations/*.json` (one JSON file per simulation family; merged at load time).
2. **Model config** (`ModelConfig`) — references a `.input.ref` base parameter file and a dust profile. Loaded from `galform_execution/config/models.json`; each model refers to a named dust profile in `galform_execution/config/dust_params.json`.
3. **Run flags** (`RunFlags`) — boolean switches controlling which pipeline stages execute (compile, galform, neta, lum_fun, etc.). Defaults come from `galform_execution/config/run_flags.json`; CLI flags override them.

`create_slurm_script(iz)` assembles a complete tcsh script for one snapshot (`iz`). The script:
- Sets up COSMA modules via `modulecmd.tcl` (not relying on interactive shell startup)
- Computes `ivol` from a compact SLURM array task ID remapped from the actual subvolume range (avoids sites that reject large array indices)
- Copies the `.input.ref` base file and calls `replace_variable.csh` / `replace_vector.csh` to inject all parameters
- Runs `galform2`, then post-processing executables (`neta_ave_disk`, `neta_ave_burst`, `sample_gals`) conditionally on run flags

`submit_job(iz)` pipes the script to `sbatch --array=<compact-range>` and retries on transient SLURM scheduler overload errors with exponential backoff.

`submit_all_jobs()` iterates over `iz_list` calling `submit_job` for each snapshot.

### Configuration files (`galform_execution/config/`)

| File | Purpose |
|------|---------|
| `simulations/*.json` | One file per simulation family (dove, eagle, millennium, nifty). Each key is a simulation label (e.g. `L800`, `MillGas`). |
| `models.json` | GALFORM model variants. Each entry specifies a `base_inputs_file` (.input.ref) and either a `dust_profile` name or inline `dust_params`. |
| `dust_params.json` | Named dust parameter profiles (e.g. `baugh05`, `lacey16`) reused across models. |
| `run_flags.json` | Default boolean flags for each pipeline stage. |

All configs are loaded at module import time into module-level dicts (`SIMULATION_CONFIGS`, `MODEL_CONFIGS`, `DUST_CONFIGS`). Custom JSON paths can be passed to each loader function.

### Special cases to be aware of

- **`nifty62.5` simulation**: uses `delete_variable.csh` to remove `aquarius_particle_file` instead of replacing it (the file doesn't exist for this sim).
- **Multi-output runs**: when `output_redshifts` or `output_iz_list` has more than one entry, `nout`/`zout` are set accordingly. If `build_galaxy_trees` is also enabled, `mgalmin_output_descendants` is automatically added to keep descendants across outputs (can be overridden by explicit `input_overrides`).
- **SLURM array index remapping**: `slurm_array_range` is always `1-N` regardless of the actual `nvol_start`; the tcsh script offsets with `@ ivol = $slurm_task_id + nvol_start - 2`.
- **Fortran endianness**: the generated script sets `GFORTRAN_CONVERT_UNIT=big_endian` and `F_UFMTENDIAN=big` as defaults (only if not already set) for reading stellar population data files.
