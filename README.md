# galform_execution

[![PyPI](https://img.shields.io/pypi/v/galform_execution.svg)](https://pypi.org/project/galform_execution/)
[![Python versions](https://img.shields.io/pypi/pyversions/galform_execution.svg)](https://pypi.org/project/galform_execution/)
[![CI](https://github.com/OscarHickman/galform_execution/actions/workflows/ci.yml/badge.svg)](https://github.com/OscarHickman/galform_execution/actions/workflows/ci.yml)
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.20797781.svg)](https://doi.org/10.5281/zenodo.20797781)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Generate and submit [GALFORM](https://www.icc.dur.ac.uk/) semi-analytic galaxy
formation runs on N-body merger trees to SLURM on the COSMA HPC cluster.

`galform_execution` builds the job scripts for a GALFORM run, injects the
simulation (trees, cosmology, snapshots) and model parameters into GALFORM's
`.input.ref` files, and submits each snapshot as a single SLURM job that runs
every subvolume across the CPUs of one allocation. It is a Python library and
a command-line tool (`submit-galform-job`), with no runtime dependencies.

## Features

- **Bundled configurations** for the Millennium, P-Millennium (L800), EAGLE,
  COLIBRE, FLAMINGO, DOVE and nIFTy simulations and the standard GALFORM models
  (`gp14`, `lc16`, ...), plus your own simulations and models in the same JSON
  format.
- **Packed jobs:** all subvolumes of a snapshot run in one SLURM slot, one worker
  per CPU. Contiguous ranges (`1-1024`) and explicit subsets (`ivols=[5, 17, 900]`)
  are both supported.
- **Fails loudly:** if any subvolume exits non-zero, the whole job fails, so
  `sacct` never shows a run with dead subvolumes as `COMPLETED`. Bad ranges,
  unknown snapshots and incomplete configs are rejected before anything is queued.
- **Pipeline control:** switch GALFORM, NETA dust, luminosity functions, stellar
  mass functions and other stages on or off. Override any GALFORM input
  parameter, and output several redshifts from one run.
- **Robust submission:** transient scheduler errors are retried with
  exponential backoff.
- **Typed** (`py.typed`) and tested on Python 3.9–3.14.

## Installation

```bash
pip install galform_execution
# or
uv pip install galform_execution
```

You need a compiled GALFORM source tree (containing `build/galform2`,
`*.input.ref`, `replace_variable.csh`, ...) and, to submit, a SLURM login node.
Off-cluster you can still generate and inspect scripts with `--dry-run`.

## Quick start: command line

```bash
# Preview the generated scripts without submitting anything
submit-galform-job /path/to/galform --nbody-sim Mill2 --model lc16 --iz 40 --nvol 1-64 --dry-run

# Submit; prints the SLURM job id of each snapshot
submit-galform-job /path/to/galform --nbody-sim Mill2 --model lc16 --iz 40 --nvol 1-64 \
    --output-folder-name MyProject

# What is available?
submit-galform-job --list-simulations
submit-galform-job --list-models
```

Run `submit-galform-job --help` for all options (SLURM resources, output
locations, pipeline stages, `--input-override NAME=VALUE`, ...).

## Quick start: Python

```python
from galform_execution import GalformSubmitter, RunFlags

s = GalformSubmitter(
    "/path/to/galform",
    nbody_sim="Mill2",
    model="lc16",
    iz=40,
    nvol="1-64",
    output_folder_name="MyProject",
    # Skip post-processing you do not need (each stage writes extra files)
    run_flags=RunFlags(neta=False, lum_fun=False, study_stellar_mass_function=False),
    input_overrides={"vhotdisk": "290"},
)
s.submit_all_jobs(dry_run=True)   # print the scripts
job_ids = s.submit_all_jobs()     # submit with sbatch
```

The `examples/` notebooks cover simulations and models, pipeline stages,
parameter studies, multi-redshift outputs and galaxy trees.

## Your own simulations and models

Pass a JSON file (or a directory of them) in the same format as the bundled
`galform_execution/config/simulations/*.json` and `config/models.json`:

```bash
submit-galform-job /path/to/galform --simulation-config my_sims.json --nbody-sim MySim --iz 100
```

or, from Python, `GalformSubmitter(..., sim_config=SimulationConfig(...), model_config=ModelConfig(...))`.

## Defaults and paths

| What | Default | Override |
| --- | --- | --- |
| GALFORM source tree | `/cosma/apps/durham/$USER/galform` | positional `galform_dir` |
| Outputs | `/cosma5/data/durham/$USER/<output-folder-name>/<sim>/<model>/iz<iz>/ivol<n>` | `--output-base-dir`, `--output-folder-name` |
| SLURM logs and generated scripts | `<output-base-dir>/<output-folder-name>/logs` | `--log-path` or `$GALFORM_LOG_PATH` |
| Partition / account | `cosma5` / `durham` | `--partition`, `--account` |

## Development

```bash
git clone https://github.com/OscarHickman/galform_execution.git
cd galform_execution
uv sync                       # creates .venv with the package and dev tools

uv run pytest --cov           # tests (tcsh needed for the script-execution tests)
uv run ruff check galform_execution tests
uv run black --check galform_execution tests
uv run isort --check-only galform_execution tests
uv run mypy galform_execution
```

### Releasing

1. Update the version in `pyproject.toml`, `CITATION.cff` (`version`,
   `date-released`) and `conda/meta.yaml`, and add a `CHANGELOG.md` entry. The
   test suite checks that these agree.
2. Commit, then tag and push: `git tag v0.3.0 && git push origin main v0.3.0`.

The `Publish` workflow checks that the tag matches the package version, runs
the full CI, publishes the tested distributions to PyPI (trusted publishing),
and creates the GitHub Release, which Zenodo archives under a new version DOI.

For conda-forge, put the sha256 of the PyPI sdist into `conda/meta.yaml` and
submit it to [conda-forge/staged-recipes](https://github.com/conda-forge/staged-recipes).

## Citing

If you use `galform_execution` in your research, please cite it. The concept DOI
[10.5281/zenodo.20797781](https://doi.org/10.5281/zenodo.20797781) always
resolves to the latest version. GitHub's **"Cite this repository"** button
gives the metadata from `CITATION.cff`.

```bibtex
@software{hickman_galform_execution,
  author    = {Hickman, Oscar},
  title     = {galform\_execution},
  url       = {https://github.com/OscarHickman/galform_execution},
  doi       = {10.5281/zenodo.20797781},
  license   = {MIT}
}
```

## License

MIT; see [`LICENSE`](LICENSE).
