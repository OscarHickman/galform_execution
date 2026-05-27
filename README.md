# galform_execution

[![CI](https://github.com/OscarHickman/galform_execution/actions/workflows/ci.yml/badge.svg)](https://github.com/OscarHickman/galform_execution/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A Python-based utility to manage GALFORM N-body simulation submissions to SLURM on COSMA.

`galform_execution` replaces legacy `tcsh`/`csh` workflow scripts by dynamically generating self-contained SLURM batch scripts. It automates environment setup, parameter file modification, and conditional post-processing, providing a robust and reproducible way to run GALFORM at scale.

## Key Features

- **Dynamic Script Generation**: Automatically generates complete `tcsh` run scripts with all required simulation parameters and model configurations.
- **Config-Driven**: Simulations, models, and dust parameters are managed via JSON files, eliminating the need to modify source code for new runs.
- **SLURM Integration**: Native support for job arrays, remapping high subvolume indices to fit scheduler constraints.
- **Robust Submissions**: Automatic retries with exponential backoff for transient SLURM scheduler errors.
- **Pipeline Control**: Fine-grained control over GALFORM pipeline stages (NETA, LUM_FUN, stellar mass functions, etc.) via CLI flags.

## Prerequisites

- **Environment**: Must be run on the **COSMA** HPC cluster (primarily COSMA5).
- **Tooling**: Requires [uv](https://github.com/astral-sh/uv) for fast dependency management and installation.

## Installation

```bash
# Clone the repository
git clone https://github.com/OscarHickman/galform_execution.git
cd galform_execution

# Install dependencies and the package using uv
uv pip install -r requirements.txt
uv pip install -e .
```

## Quick Start

Once installed, the `submit-galform-job` command is available in your environment.

### 1. List Available Configurations
Check which simulations and models are already configured:
```bash
submit-galform-job --list-simulations
submit-galform-job --list-models
```

### 2. Perform a Dry Run
Preview the generated SLURM script without submitting it to the queue:
```bash
submit-galform-job --nbody-sim Mill2 --model lc16 --iz 40 --nvol 1-64 --dry-run
```

### 3. Submit a Real Job
Submit a job array for snapshot 40, subvolumes 1 through 64:
```bash
submit-galform-job --nbody-sim Mill2 --model lc16 --iz 40 --nvol 1-64 --output-folder-name My_Project
```

## Comprehensive Usage

### CLI Arguments

| Argument | Description | Default |
|:---|:---|:---|
| `galform_dir` | Path to the GALFORM source directory | `~/galform` |
| `--nbody-sim` | Name of the N-body simulation (e.g., `L800`, `MillGas`) | `L800` |
| `--model` | GALFORM model variant (e.g., `gp14`, `lc16`) | `gp14` |
| `--iz` | Single snapshot number to submit | - |
| `--nvol` | Subvolume range for SLURM array (e.g., `1-10`, `12`) | - |
| `--partition` | SLURM partition to use | `cosma5` |
| `--account` | SLURM account (project code) | `durham` |
| `--walltime` | Maximum job duration | `72:00:00` |

### Pipeline Stage Toggles
You can override default pipeline behavior (defined in `run_flags.json`) using these flags:
- `--no-neta`: Disable NETA_AVE dust calculation.
- `--no-lum-fun`: Disable luminosity function calculation.
- `--run-dust-props`: Enable dust properties output.
- `--build-galaxy-trees`: Set `build_galaxy_trees = .true.` in the GALFORM input file.

## Architecture

The utility works by:
1. **Resolving Configs**: Merging simulation-specific JSONs, model definitions, and runtime flags.
2. **Generating tcsh**: Creating a temporary `tcsh` script that handles:
    - Loading required COSMA modules.
    - Injecting parameters into a `.input.ref` base file using `replace_variable.csh`.
    - Executing `galform2` and post-processing binaries.
3. **Submitting via sbatch**: Piping the script directly to `sbatch` with appropriate array indices.

## Configuration

Configurations are located in `galform_execution/config/`:
- `simulations/`: One JSON per simulation family (Eagle, Millennium, etc.).
- `models.json`: Maps model names to base input files and dust profiles.
- `dust_params.json`: Defines named sets of dust parameters.
- `run_flags.json`: Default switches for pipeline stages.

## Development & Testing

### Running Tests
The project uses `pytest` for unit testing.
```bash
pytest tests
```

### Linting
We use `ruff` to maintain code quality.
```bash
ruff check galform_execution
```

## License

Distributed under the MIT License. See `LICENSE` for more information.
