"""Command-line interface: the ``submit-galform-job`` console script."""

import argparse
import dataclasses
import sys
from typing import Dict, Mapping, Optional, Sequence, Tuple

from galform_execution import __version__
from galform_execution.submit_galform_job import (
    DUST_CONFIGS,
    MODEL_CONFIGS,
    SIMULATION_CONFIGS,
    GalformSubmitter,
    ModelConfig,
    RunFlags,
    SimulationConfig,
    default_galform_dir,
    load_model_configs,
    load_run_flags_config,
    load_simulation_configs,
)

_EPILOG = """
Examples:
  # Preview the generated scripts without submitting anything
  %(prog)s /path/to/galform --nbody-sim Mill2 --model lc16 --iz 40 --nvol 1-64 --dry-run

  # Submit the default snapshot list for L800 with the gp14 model
  %(prog)s /path/to/galform

  # Custom snapshot list and subvolume range
  %(prog)s /path/to/galform --iz-list 100 120 155 --nvol 1-50

  # A non-contiguous selection of 0-based subvolumes
  %(prog)s /path/to/galform --iz 271 --ivols 5 17 900

  # Your own simulation/model definitions (same JSON format as the bundled ones)
  %(prog)s /path/to/galform --simulation-config my_sims.json --nbody-sim MySim

  # Enable/disable pipeline stages
  %(prog)s /path/to/galform --no-neta --no-lum-fun --no-study-smf
"""

# (on flag, off flag, GALFORM input parameter)
_TREE_TOGGLES = (
    ("build_galaxy_trees", "no_build_galaxy_trees", "build_galaxy_trees"),
    ("output_halo_trees", "no_output_halo_trees", "output_halo_trees"),
)


def _name_equals_value(text: str) -> Tuple[str, str]:
    name, sep, value = text.partition("=")
    name, value = name.strip(), value.strip()
    if not sep or not name or not value:
        raise argparse.ArgumentTypeError(f"expected NAME=VALUE, got {text!r}")
    return name, value


def _add_selection_arguments(parser: argparse.ArgumentParser) -> None:
    group = parser.add_argument_group("what to run")
    group.add_argument(
        "--nbody-sim", default="L800", help="N-body simulation name (default: L800)"
    )
    group.add_argument(
        "--model", default="gp14", help="GALFORM model name (default: gp14)"
    )
    group.add_argument("--iz", type=int, help="Single snapshot number to submit")
    group.add_argument(
        "--iz-list",
        type=int,
        nargs="+",
        help="Snapshot numbers to submit (default: the simulation's iz_list)",
    )
    vols = group.add_mutually_exclusive_group()
    vols.add_argument(
        "--nvol",
        help='1-based subvolume range, e.g. "1-64" or "12" '
        "(default: the simulation's nvol_range)",
    )
    vols.add_argument("--nvol-range", help="Deprecated alias for --nvol")
    vols.add_argument(
        "--ivols",
        type=int,
        nargs="+",
        metavar="IVOL",
        help="Explicit 0-based subvolume indices (the ivol<N> output "
        "directories), e.g. a random subset",
    )
    outputs = group.add_mutually_exclusive_group()
    outputs.add_argument(
        "--output-iz-list",
        type=int,
        nargs="+",
        help="Output multiple snapshots in one run (sets nout/zout)",
    )
    outputs.add_argument(
        "--output-z-list",
        type=float,
        nargs="+",
        help="Output multiple redshifts in one run (sets nout/zout)",
    )
    group.add_argument(
        "--input-override",
        type=_name_equals_value,
        action="append",
        default=[],
        metavar="NAME=VALUE",
        help="Set a parameter in the GALFORM input file (repeatable)",
    )


def _add_config_arguments(parser: argparse.ArgumentParser) -> None:
    group = parser.add_argument_group("configuration files")
    group.add_argument(
        "--simulation-config",
        metavar="JSON",
        help="Extra simulation definitions: a JSON file, or a directory of *.json, "
        "in the format of the bundled config/simulations/*.json",
    )
    group.add_argument(
        "--model-config",
        metavar="JSON",
        help="Extra model definitions in the format of the bundled config/models.json",
    )
    group.add_argument(
        "--run-flags-config",
        metavar="JSON",
        help="JSON file of pipeline-stage flags replacing the bundled "
        "config/run_flags.json",
    )


def _add_output_arguments(parser: argparse.ArgumentParser) -> None:
    group = parser.add_argument_group("output locations")
    group.add_argument(
        "--output-base-dir",
        help="Root directory for GALFORM outputs (default: /cosma5/data/durham/$USER)",
    )
    group.add_argument(
        "--output-folder-name",
        default="Galform_Out",
        help="Folder name under the base output directory (default: Galform_Out)",
    )
    group.add_argument(
        "--log-path",
        help="Directory for SLURM logs and generated scripts (default: "
        "$GALFORM_LOG_PATH, else <output-base-dir>/<output-folder-name>/logs)",
    )
    group.add_argument(
        "--galform-exe",
        help="Path to a custom GALFORM executable (overrides build/galform2)",
    )


def _add_slurm_arguments(parser: argparse.ArgumentParser) -> None:
    group = parser.add_argument_group("SLURM resources")
    group.add_argument(
        "--partition", default="cosma5", help="SLURM partition (default: cosma5)"
    )
    group.add_argument(
        "--account", default="durham", help="SLURM account (default: durham)"
    )
    group.add_argument(
        "--walltime", default="72:00:00", help="Job wall-time (default: 72:00:00)"
    )
    group.add_argument(
        "--mem-per-cpu",
        type=int,
        default=4000,
        metavar="MB",
        help="Memory per CPU in MB (default: 4000)",
    )
    group.add_argument("--mail-user", help="Email address for SLURM job notifications")
    group.add_argument(
        "--mail-type",
        default="END,FAIL",
        help="SLURM mail event types (default: END,FAIL)",
    )


def _add_stage_arguments(parser: argparse.ArgumentParser) -> None:
    group = parser.add_argument_group(
        "pipeline stages", "Override individual flags from the run-flags config."
    )
    galform = group.add_mutually_exclusive_group()
    galform.add_argument(
        "--run-galform", action="store_true", help="Force the galform2 run on"
    )
    galform.add_argument(
        "--no-galform", action="store_true", help="Force the galform2 run off"
    )
    group.add_argument(
        "--no-neta", action="store_true", help="Disable neta_ave dust calculation"
    )
    group.add_argument(
        "--no-lum-fun",
        action="store_true",
        help="Disable luminosity function calculation",
    )
    group.add_argument(
        "--no-study-smf",
        action="store_true",
        help="Disable stellar mass function output",
    )
    group.add_argument(
        "--run-dust-props", action="store_true", help="Enable dust properties output"
    )
    group.add_argument(
        "--run-samp-z0", action="store_true", help="Enable z=0 galaxy sample output"
    )

    trees = parser.add_argument_group("tree-output toggles")
    for on_dest, off_dest, param in _TREE_TOGGLES:
        pair = trees.add_mutually_exclusive_group()
        pair.add_argument(
            "--" + on_dest.replace("_", "-"),
            action="store_true",
            help=f"Set {param} = .true. in GALFORM input",
        )
        pair.add_argument(
            "--" + off_dest.replace("_", "-"),
            action="store_true",
            help=f"Set {param} = .false. in GALFORM input",
        )


def build_parser() -> argparse.ArgumentParser:
    """Build the ``submit-galform-job`` argument parser."""
    parser = argparse.ArgumentParser(
        prog="submit-galform-job",
        description="Submit GALFORM N-body runs to SLURM batch queue on COSMA",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=_EPILOG,
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    parser.add_argument(
        "galform_dir",
        nargs="?",
        default=str(default_galform_dir()),
        help="Path to the GALFORM source directory "
        f"(default: {default_galform_dir()}; contains build/, *.input.ref, etc.)",
    )
    _add_selection_arguments(parser)
    _add_config_arguments(parser)
    _add_output_arguments(parser)
    _add_slurm_arguments(parser)
    _add_stage_arguments(parser)
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
    return parser


def _run_flags(args: argparse.Namespace) -> RunFlags:
    """Flags from the config file, with explicit CLI switches applied on top."""
    switches = {
        "galform": True if args.run_galform else False if args.no_galform else None,
        "neta": False if args.no_neta else None,
        "lum_fun": False if args.no_lum_fun else None,
        "study_stellar_mass_function": False if args.no_study_smf else None,
        "dust_props": True if args.run_dust_props else None,
        "samp_z0": True if args.run_samp_z0 else None,
    }
    flags = load_run_flags_config(args.run_flags_config)
    return dataclasses.replace(
        flags, **{k: v for k, v in switches.items() if v is not None}
    )


def _input_overrides(args: argparse.Namespace) -> Dict[str, str]:
    overrides = dict(args.input_override)
    for on_dest, off_dest, param in _TREE_TOGGLES:
        if getattr(args, on_dest):
            overrides[param] = ".true."
        elif getattr(args, off_dest):
            overrides[param] = ".false."
    return overrides


def _print_simulations(simulations: Mapping[str, SimulationConfig]) -> None:
    print("Available simulation configurations:")
    print(f"{'Simulation':<20} {'Snapshots (iz)':<40} {'Subvolumes':<11} Status")
    print("-" * 90)
    for name, cfg in sorted(simulations.items()):
        iz_str = str(cfg.iz_list) if cfg.iz_list else "(not set)"
        if len(iz_str) > 37:
            iz_str = iz_str[:34] + "..."
        missing = cfg.missing_fields()
        status = f"incomplete: {', '.join(missing)}" if missing else "ready"
        print(f"{name:<20} {iz_str:<40} {cfg.nvol_range:<11} {status}")


def _print_models(models: Mapping[str, ModelConfig]) -> None:
    print("Available model configurations:")
    print(f"{'Model':<25} {'Base Input File':<45} {'Dust'}")
    print("-" * 80)
    for name, cfg in sorted(models.items()):
        dust_label = f"fcloud={cfg.dust_params.fcloud}"
        print(f"{name:<25} {cfg.base_inputs_file:<45} {dust_label}")


def _submit(submitter: GalformSubmitter, args: argparse.Namespace) -> None:
    if not submitter.iz_list:
        raise ValueError(
            f"No snapshots to submit for '{submitter.nbody_sim}': "
            "pass --iz or --iz-list"
        )
    for iz in submitter.iz_list:
        job_id = submitter.submit_job(
            iz, mem_per_cpu=args.mem_per_cpu, dry_run=args.dry_run
        )
        if job_id:
            print(f"Submitted iz={iz} as SLURM job {job_id}")
        elif not args.dry_run:
            print(f"Warning: sbatch reported no job id for iz={iz}", file=sys.stderr)


def _run(args: argparse.Namespace) -> int:
    simulations = dict(SIMULATION_CONFIGS)
    if args.simulation_config:
        simulations.update(load_simulation_configs(args.simulation_config))
    models = dict(MODEL_CONFIGS)
    if args.model_config:
        models.update(load_model_configs(DUST_CONFIGS, args.model_config))

    if args.list_simulations:
        _print_simulations(simulations)
        return 0
    if args.list_models:
        _print_models(models)
        return 0

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
        mail_user=args.mail_user,
        mail_type=args.mail_type,
        iz_list=args.iz_list,
        nvol_range=args.nvol_range,
        run_flags=_run_flags(args),
        input_overrides=_input_overrides(args),
        output_redshifts=args.output_z_list,
        output_iz_list=args.output_iz_list,
        galform_exe=args.galform_exe,
        ivols=args.ivols,
        sim_config=simulations.get(args.nbody_sim),
        model_config=models.get(args.model),
    )
    _submit(submitter, args)
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Run the CLI; returns the process exit code (0 success, 1 error)."""
    args = build_parser().parse_args(argv)
    try:
        return _run(args)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
