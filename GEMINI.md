# galform_execution

A Python-based utility to manage GALFORM N-body simulation submissions to SLURM on COSMA. This tool replaces legacy `tcsh`/`csh` scripts by dynamically generating self-contained SLURM batch scripts that handle environment setup, parameter file modification, GALFORM execution, and post-processing tasks.

## Key Components

- `src/submit_galform_job.py`: The core application that manages job submission. It reads configuration files, generates custom `tcsh` scripts, and interacts with the `sbatch` scheduler.
- `src/config/`: Directory containing JSON configurations for simulations (`simulations/`), GALFORM models (`models.json`), dust parameters (`dust_params.json`), and pipeline execution flags (`run_flags.json`).

## Building and Running

### Prerequisites
- Must be run on COSMA (COSMA5).
- Requires a Python environment with dependencies (managed via `requirements.txt`).

### Setup
```bash
# Install dependencies
pip install -r requirements.txt
# Optional: install in editable mode for local development
pip install -e .
```

### Submitting Jobs
Use the main script to submit GALFORM runs.

```bash
# Typical run
python src/submit_galform_job.py --nbody-sim Mill2 --model lc16 --iz 40 --nvol 1-64 --output-folder-name Galform_Test

# Dry run (preview the SLURM script)
python src/submit_galform_job.py --nbody-sim Mill2 --model lc16 --iz 40 --nvol 1-64 --dry-run
```

## Development Conventions
- **Testing**: Use `pytest`.
  ```bash
  pytest tests -q
  ```
- **Linting**: Use `ruff`.
  ```bash
  ruff check src/galform_execution
  ```
- **Configuration**: Changes to defaults (e.g., model parameters, simulation paths, runtime flags) should be performed by editing the JSON files in `src/config/` rather than modifying the Python source code.
