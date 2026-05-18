# galform_execution

[![CI](https://github.com/OscarHickman/galform_execution/actions/workflows/ci.yml/badge.svg)](https://github.com/OscarHickman/galform_execution/actions/workflows/ci.yml)

a SLURM submitter for running GALFORM on COSMA.

## Setup

```bash
cd galform_execution
pip install -r requirements.txt
```

Optional (for imports in notebooks/scripts):

```bash
pip install -e .
```

Examples live in `examples/`.

## GALFORM Submission (COSMA)

Main script:

```bash
python src/submit_galform_job.py --help
```

Typical run:

```bash
python src/submit_galform_job.py --nbody-sim Mill2 --model lc16 --iz 40 --nvol 1-64 --output-folder-name Galform_Test
```

Dry run:

```bash
python src/submit_galform_job.py --nbody-sim Mill2 --model lc16 --iz 40 --nvol 1-64 --dry-run
```

## Execution Config Files

GALFORM execution config is stored in JSON under:

- `src/config/simulations/*.json`
- `src/config/models.json`
- `src/config/dust_params.json`
- `src/config/run_flags.json`

Edit these files to change defaults without touching Python code.

## Development

Run tests:

```bash
pytest tests -q
```

Lint:

```bash
ruff check src/galform_execution
```

## Author

Oscar Hickman
