# galform_execution

A Python-based utility to manage GALFORM N-body simulation submissions to SLURM on COSMA.

This tool replaces legacy `tcsh`/`csh` scripts by dynamically generating self-contained SLURM batch scripts. It handles:
- Environment setup (modules)
- Parameter file modification (`.input.ref` injection)
- GALFORM execution
- Conditional post-processing (NETA, LUM_FUN, etc.)
- Retries on transient SLURM scheduler errors

## Installation

```bash
# Clone the repository
git clone https://github.com/OscarHickman/galform_execution.git
cd galform_execution

# Install dependencies and package
pip install -r requirements.txt
pip install -e .
```

## Usage

After installation, the `submit-galform-job` command is available.

### Basic submission
```bash
# Submit for Mill2 simulation, lc16 model, snapshot 40, subvolumes 1 to 64
submit-galform-job --nbody-sim Mill2 --model lc16 --iz 40 --nvol 1-64 --output-folder-name Galform_Test
```

### Dry run
Preview the generated SLURM script without submitting:
```bash
submit-galform-job --nbody-sim Mill2 --model lc16 --iz 40 --nvol 1-64 --dry-run
```

### Help
```bash
submit-galform-job --help
```

## Configuration

The tool uses JSON configuration files located in `galform_execution/config/`:
- `simulations/*.json`: N-body simulation paths and parameters.
- `models.json`: GALFORM model definitions.
- `dust_params.json`: Dust model parameters.
- `run_flags.json`: Pipeline execution switches.

## Development

### Tests
```bash
pytest tests
```

### Linting
```bash
ruff check galform_execution
```
