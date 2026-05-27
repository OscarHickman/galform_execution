# galform_execution

[![CI](https://github.com/OscarHickman/galform_execution/actions/workflows/ci.yml/badge.svg)](https://github.com/OscarHickman/galform_execution/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A Python-based utility to manage GALFORM N-body simulation submissions to SLURM on COSMA.

`galform_execution` automates the generation and submission of SLURM batch scripts for GALFORM runs. It handles environment setup, parameter injection into `.input.ref` files, and conditional post-processing (NETA, LUM_FUN, etc.), providing a robust and reproducible workflow for large-scale galaxy formation simulations.

## Key Features

- **Dynamic Script Generation**: Generates self-contained `tcsh` scripts with resolved simulation and model parameters.
- **Config-Driven**: Manage simulations, models, and dust parameters via JSON configurations.
- **SLURM Optimized**: Automatic job array support and remapping of high subvolume indices.
- **Robustness**: Built-in retries with exponential backoff for transient scheduler errors.

## Prerequisites

- **Environment**: Access to the **COSMA** HPC cluster (Durham University).
- **Tooling**: [uv](https://github.com/astral-sh/uv) is recommended for fast installation and dependency management.

## Installation

```bash
# Install the package and its dependencies directly from PyPI using uv
uv pip install galform_execution
```

For development installation from source:
```bash
git clone https://github.com/OscarHickman/galform_execution.git
cd galform_execution
uv pip install -e .
```

## Quick Start

### 1. Identify your GALFORM directory
You need a compiled version of GALFORM with the standard directory structure (containing `build/galform2`, `*.input.ref`, etc.).

### 2. Preview a submission (Dry Run)
Check the generated SLURM script without submitting to the queue:
```bash
submit-galform-job /path/to/your/galform --nbody-sim Mill2 --model lc16 --iz 40 --nvol 1-64 --dry-run
```

### 3. Submit a job array
```bash
submit-galform-job /path/to/your/galform --nbody-sim Mill2 --model lc16 --iz 40 --nvol 1-64 --output-folder-name MyProject
```

## Configuration

Configurations are stored in `galform_execution/config/`:
- `simulations/`: JSON files defining N-body simulation parameters (tree paths, cosmology).
- `models.json`: Maps model names to base input files and dust profiles.
- `redshift_lists/`: Redshift mappings for various simulations.

## Development

### Running Tests
```bash
uv run pytest tests
```

### Linting
```bash
uv run ruff check galform_execution
```

## Citing this software

If you use `galform_execution` in your research, please cite it. GitHub will
show a **"Cite this repository"** button (top-right of the repo page) once
`CITATION.cff` is committed.

After connecting Zenodo (see below), each release gets a permanent DOI.
Replace `YOUR_ZENODO_DOI` with the DOI minted on first release:

```bibtex
@software{hickman_galform_execution,
  author    = {Hickman, Oscar},
  title     = {galform\_execution},
  url       = {https://github.com/OscarHickman/galform_execution},
  doi       = {YOUR_ZENODO_DOI},
  license   = {MIT}
}
```

### Setting up citation infrastructure

**Zenodo** (DOIs for every release) — already connected:
Push a new version tag and the release workflow will create a GitHub Release,
which Zenodo archives automatically and mints a DOI.
Update `CITATION.cff` and this README with the DOI badge Zenodo provides.

**Conda-forge**:
1. Get the sha256 of the PyPI source tarball:
   ```bash
   curl -s https://pypi.org/pypi/galform_execution/json \
     | python -c "import sys,json; d=json.load(sys.stdin); \
       [print(f['digests']['sha256']) for v in d['releases'].values() \
        for f in v if f['filename'].endswith('.tar.gz')]" | tail -1
   ```
2. Paste it into `recipe/meta.yaml`.
3. Fork [conda-forge/staged-recipes](https://github.com/conda-forge/staged-recipes), copy `recipe/meta.yaml` to `recipes/galform_execution/meta.yaml`, and open a PR.

## License

Distributed under the MIT License. See `LICENSE` for more information.
