# AGENTS.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install for development
uv pip install -e .

# Run tests
uv run pytest tests

# Run a single test
uv run pytest tests/test_submit_galform_job.py::test_galform_submitter_initialization

# Lint
uv run ruff check galform_execution

# Format check
uv run black --check galform_execution tests

# Import order check
uv run isort --check-only galform_execution

# Auto-fix formatting
uv run black galform_execution tests
uv run isort galform_execution

# Build package
uv build

# CLI dry-run (requires GALFORM dir on COSMA)
submit-galform-job /path/to/galform --nbody-sim Mill2 --model lc16 --iz 40 --nvol 1-64 --dry-run

# List available simulations / models
submit-galform-job --list-simulations
submit-galform-job --list-models
```

## Architecture

The package is a single-module library (`galform_execution/submit_galform_job.py`) exposing a `GalformSubmitter` class and a `main()` CLI entry point registered as `submit-galform-job`.

**Data flow:**
1. JSON configs are loaded at module import time into `SIMULATION_CONFIGS`, `MODEL_CONFIGS`, and `DUST_CONFIGS` module-level dicts.
2. `GalformSubmitter.__init__` resolves simulation/model configs from those dicts, validates the GALFORM directory, and computes subvolume parameters.
3. `_create_tcsh_script(iz)` assembles the inner `tcsh` GALFORM script via several `_generate_*` helper methods. This script is written to disk by `submit_job` but is never submitted directly to `sbatch`.
4. `create_job_script(iz)` generates a bash wrapper that requests `--cpus-per-task=min(nvol_count, partition_cpus_per_node)` and forks one worker per CPU. Each worker iterates over a strided subset of subvolume IDs, covering all `nvol_count` subvolumes within a single SLURM slot. No `--array` flag is used.
5. `submit_job(iz)` writes the tcsh script to `<log_path>/<nbody_sim>/<model>_iz<iz>.csh`, then submits the bash wrapper via `sbatch` with exponential-backoff retry on transient scheduler errors.
6. `submit_all_jobs` calls `submit_job` for every snapshot in `iz_list`.

**Config layout (`galform_execution/config/`):**
- `simulations/*.json` — per-simulation-family JSON files; merged into one dict at load time. Fields map to `SimulationConfig` dataclass.
- `models.json` — maps model name to `base_inputs_file` and a dust profile reference or inline `dust_params`. Maps to `ModelConfig`.
- `dust_params.json` — named dust profiles (e.g. `baugh05`, `lacey16`) mapping to `DustParams`.
- `run_flags.json` — default `RunFlags` (booleans controlling which pipeline stages run).
- `redshift_lists/*.txt` — snapshot index → redshift mappings, one per simulation family.

**Key dataclasses:** `SimulationConfig`, `DustParams`, `ModelConfig`, `RunFlags` — all plain dataclasses, no inheritance.

**COSMA-specific assumptions:**
- Default GALFORM dir: `/cosma/apps/durham/$USER/galform`
- Default output root: `/cosma5/data/durham/$USER`
- Default log root: `$output_root/$output_folder_name/logs`
- Modules loaded: Intel 2024 toolchain (`intel_comp/2024.2.0`, `compiler-rt`, `tbb`, `compiler`, `mpi`)
- All parallelism is handled within a single SLURM slot; `$SLURM_ARRAY_TASK_ID` is set per-worker by the bash wrapper, and `ivol` is derived as `$SLURM_ARRAY_TASK_ID + nvol_start - 2` inside the tcsh script.

**Generated tcsh script structure** (`_create_tcsh_script`)**:** `#!/bin/tcsh -ef` → module loads → environment variables → run flags → simulation params → dust params → redshift extraction via `awk` → model param file setup (`replace_variable.csh` / `replace_vector.csh`) → photometric bands block → GALFORM execution → NETA dust → luminosity function → stellar mass function.

**Generated bash wrapper structure** (`create_job_script`)**:** `#!/bin/bash` → `#SBATCH` directives (`--ntasks=1`, `--cpus-per-task`, `--mem-per-cpu`) → `_run_worker` function that loops over strided task IDs invoking `tcsh -ef <tcsh_path>` → parallel `for` loop forking one worker per CPU → `wait`.

## ⚠️ Per-run parameter file MUST carry the job id

`GalformSubmitter`'s generated script writes its substituted parameter file to
`./params/${Nbody_sim}_${model}_iz${iz}_ivol${ivol}_job${SLURM_JOB_ID}.input.temp`.

**Do not remove `_job${SLURM_JOB_ID}`.** Without it, any two jobs sharing
`(Nbody_sim, model, iz, ivol)` that run concurrently write the same file: each begins with
`cp $base_inputs_file ...`, wiping the other's substitutions, so GALFORM reads a parameter set
belonging to a different job while `sacct` still reports `COMPLETED`. This is not hypothetical —
it silently mixed IMF-slope branches across most of the `imf` project's 2026 redshift-ladder and
counter-ladder campaigns (their three branches per rung collide on exactly this key by design), and
was only detectable after the fact from each `galaxies.hdf5`'s `/Parameters` group. Fixed
2026-09-03; `tests/test_submit_galform_job.py` has a regression test asserting the job id is present.
