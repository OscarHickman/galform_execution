# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.0] - 2026-10-09

### Added
- Top-level public API: `from galform_execution import GalformSubmitter, RunFlags, SimulationConfig, ...` (see `galform_execution.__all__`). The package now ships type hints (`py.typed`).
- `GalformSubmitter(sim_config=..., model_config=...)` for simulations and models that are not bundled with the package.
- CLI options `--simulation-config` and `--model-config` load extra simulation/model definitions from JSON files in the same format as the bundled ones; `--list-simulations` and `--list-models` include them.
- CLI options mirroring the Python API: `--ivols`, `--mem-per-cpu`, `--input-override NAME=VALUE` (repeatable) and `--version`.
- The CLI prints the SLURM job id of every snapshot it submits.
- `--list-simulations` has a Status column flagging simulations that cannot be submitted yet (missing `volume` or `iz0`).
- Public `GalformSubmitter.create_tcsh_script()` (the private `_create_tcsh_script` remains as an alias), `SimulationConfig.missing_fields()`, `default_galform_dir()` and `default_output_root()`.

### Changed
- **Requires Python 3.9 or newer.** Python 3.8 reached end of life in 2024 and current setuptools cannot build on it. Tested on Python 3.9–3.14.
- The bundled `MillGas` simulation now defaults to all 64 of its subvolumes (`nvol_range` `1-64`, previously the subset `1-10`). This matches its per-subvolume `volume` and its 64 tree files, and stops valid `ivols` of 10 or more being rejected. Pass `--nvol 1-10` (or `nvol="1-10"`) for the old default.
- The bundled `Mill1` and `Mill2` redshift lists are now the full tables (Millennium snapshots 7–63, Millennium-II 0–67), copied from the tree directories. They previously held only 3 and 2 snapshots with rounded redshifts, so any other snapshot, for example in `output_iz_list`, could not be resolved. **The redshift passed to GALFORM changes slightly for runs at those snapshots:** Mill2 iz=40 is now z=1.503637 (was 1.5) and Mill1 iz=33 is now z=1.912633 (was 1.91).
- The job wrapper sets `OMP_NUM_THREADS`, `MKL_NUM_THREADS` and `OPENBLAS_NUM_THREADS` to 1, because it already runs one GALFORM process per allocated CPU.
- `load_run_flags_config()` raises `FileNotFoundError` for an explicit path that does not exist and `ValueError` for unknown flag names (keys starting with `_` are comments), instead of silently using defaults.
- Contradictory CLI options are rejected by the argument parser with exit code 2: `--run-galform`/`--no-galform`, each tree toggle and its `--no-` form, `--output-iz-list`/`--output-z-list`, and `--nvol`/`--nvol-range`/`--ivols`.
- The console script lives in `galform_execution.cli`; `galform_execution.submit_galform_job.main` still works.
- `__version__` is read from the installed package metadata, so it can no longer drift from the released version.
- Package metadata uses an SPDX license expression and lists project URLs, the DOI and supported Python versions.
- Releases are published to PyPI only after linting and the full test suite pass on Python 3.9–3.14 and the built wheel passes the tests. The GitHub Release (and so the Zenodo DOI) is created only after the PyPI upload succeeds, with the wheel and sdist attached.
- The example notebooks use the public top-level API (`from galform_execution import ...`).

### Fixed
- A SLURM job now fails when any of its subvolumes exits non-zero. The job wrapper used to ignore each subvolume's exit status, so `sacct` reported runs with dead subvolumes as `COMPLETED`. The failing task ids are written to the job's stderr.
- The default log directory follows `--output-base-dir` / `output_base_dir` (`<output_base_dir>/<output_folder_name>/logs`), as `--help` documented. It previously always used `/cosma5/data/durham/$USER`, so jobs writing outputs elsewhere died at start on nodes that do not mount `/cosma5`.
- Submitting where `sbatch` is not installed raises an error saying so and pointing at `--dry-run`, instead of a bare `No such file or directory`.
- `python -m galform_execution` exits with status 1 on errors; it previously always exited 0.
- `--run-flags-config` no longer drops flags that have no dedicated CLI switch (e.g. `cosmicsed`, `agn`, `sedfit`).
- Invalid subvolume ranges such as `0`, `0-5` or `10-1` are rejected instead of producing a job that does nothing or runs ivol -1.
- A snapshot that is missing from a readable redshift list is rejected when the job is generated, instead of failing on the compute node after queueing.
- Generating scripts no longer fails when the default log directory cannot be created for reasons other than permissions, e.g. a read-only root filesystem when previewing on macOS.
- An unknown field in a simulation JSON produces an error naming the simulation and the file.
- The test suite no longer creates directories under `/cosma5`.

## [0.2.4] - 2026-09-26

### Fixed
- `galform_execution.__version__` now matches the packaged version (it had drifted from `pyproject.toml`).

## [0.2.3] - 2026-09-26

### Added
- `GalformSubmitter` accepts an explicit `ivols=` list of 0-based subvolume indices (e.g. a random m-of-k draw); it is mutually exclusive with `nvol`/`nvol_range` and is validated as non-empty, unique and in range.
- Bundled `COLIBRE-L200m6` simulation entry and redshift list.

### Fixed
- The per-run GALFORM parameter file path now includes the SLURM job id, so concurrent jobs sharing the same sim/model/iz/ivol can no longer overwrite each other's parameters.
- `COLIBRE-L100m6` redshift list extended from 4 to 128 snapshots (including the missing iz=18, z=10.0 entry).
- Added missing iz=36 (z=1.503637) entry to the `Mill1` redshift list.

## [0.2.2] - 2026-07-17

### Added
- Bundled `COLIBRE-L400m7` simulation entry with verified cosmology and particle mass.
- Fill in `lbox` and `mpart` for `EagleDM/101/67`.

### Fixed
- Corrected bundled simulation config values after a full data audit: `mpart` and per-subvolume `volume` for `COLIBRE-L100m6` and `FLAMINGO-L1000N1800`.
- `nifty62.5` and `MillGas62.5` volume (a copy-paste from the 500 Mpc/h box) set to null with explanatory notes.

## [0.2.1] - 2026-06-23

### Added
- Optional SLURM email notifications via `mail_user` and `mail_type` (default `END,FAIL`) on `GalformSubmitter` and the CLI.

### Changed
- Example notebooks updated for the single-slot submission API.

## [0.2.0] - 2026-06-23

### Added
- `partition_configs.json` mapping each COSMA partition to its `cpus_per_node`.

### Changed
- Single-slot packed submission is now the only job mode: each submission uses one SLURM slot with `--cpus-per-task` capped at the partition's CPUs per node, and subvolumes run in a strided worker loop.
- `create_packed_job_script` is now `create_job_script`, and `submit_packed_job` is now `submit_job`.
- `submit_all_jobs` now forwards `mem_per_cpu`.

### Removed
- SLURM job-array submission (the old array-based `submit_job`, `create_slurm_script` as a public method, and the `slurm_array_range` attribute).

## [0.1.7] - 2026-06-22

### Added
- Packed single-slot SLURM jobs (`create_packed_job_script()` / `submit_packed_job()`): all subvolumes run in one slot instead of an N-task array, so many more samples fit under per-user slot limits.

### Changed
- Shared sbatch retry logic is reused by both submission paths.

## [0.1.6] - 2026-06-13

### Added
- Three example notebooks (quickstart, simulations/models/pipeline, parameter studies and trees) replacing the single original notebook.
- Note in `DoveWDM.clean` config that its paths are on a personal `/gpfs/` mount.

### Changed
- Tree-option CLI flags (`--build-galaxy-trees`, `--output-halo-trees` and their `--no-` forms) no longer set an explicit `None` default.

### Removed
- Unused `dust_params: null` entries from `models.json` and the `data_filesystem` field from simulation configs and `SimulationConfig`.
- Placeholder `COLIBRE-L400m7` entry (tree paths were not yet built; re-added with real values in 0.2.2).

## [0.1.5] - 2026-05-27

Maintenance release (packaging/CI only).

## [0.1.4] - 2026-05-27

### Fixed
- Python 3.8 compatibility: `Tuple` is now imported from `typing`.

## [0.1.3] - 2026-05-27

Maintenance release (packaging/CI only).

## [0.1.2] - 2026-05-27

### Fixed
- Python 3.8 compatibility: use `typing.Tuple` in annotations.

## [0.1.1] - 2026-05-27

### Changed
- Installation instructions now use PyPI.

## [0.1.0] - 2026-05-27

### Added
- Initial release: `GalformSubmitter` and the `submit-galform-job` CLI generate and submit GALFORM SLURM jobs on COSMA, with dry-run preview, retries with exponential backoff for transient scheduler errors, and remapping of high subvolume indices.
- Config-driven simulations, models, dust parameters, run flags and redshift lists, bundled for Millennium, Nifty, EAGLE, DOVE, FLAMINGO and COLIBRE families (including `COLIBRE-L100m6`).
- Package layout moved to `galform_execution/` with `python -m galform_execution` support; MIT license.

### Fixed
- tcsh job script no longer crashes when `GALFORM2_EXE_OVERRIDE` is unset (if/then/endif form).

[0.3.0]: https://github.com/OscarHickman/galform_execution/compare/v0.2.4...v0.3.0
[0.2.4]: https://github.com/OscarHickman/galform_execution/compare/v0.2.3...v0.2.4
[0.2.3]: https://github.com/OscarHickman/galform_execution/compare/v0.2.2...v0.2.3
[0.2.2]: https://github.com/OscarHickman/galform_execution/compare/v0.2.1...v0.2.2
[0.2.1]: https://github.com/OscarHickman/galform_execution/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/OscarHickman/galform_execution/compare/v0.1.7...v0.2.0
[0.1.7]: https://github.com/OscarHickman/galform_execution/compare/v0.1.6...v0.1.7
[0.1.6]: https://github.com/OscarHickman/galform_execution/compare/v0.1.5...v0.1.6
[0.1.5]: https://github.com/OscarHickman/galform_execution/compare/v0.1.4...v0.1.5
[0.1.4]: https://github.com/OscarHickman/galform_execution/compare/v0.1.3...v0.1.4
[0.1.3]: https://github.com/OscarHickman/galform_execution/compare/v0.1.2...v0.1.3
[0.1.2]: https://github.com/OscarHickman/galform_execution/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/OscarHickman/galform_execution/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/OscarHickman/galform_execution/releases/tag/v0.1.0
