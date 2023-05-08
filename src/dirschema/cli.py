"""CLI interface of dirschema (see `dirschema --help`)."""

import sys
from pathlib import Path
from typing import Tuple

import typer
from ruamel.yaml import YAML

from .json.handlers import loaded_handlers
from .log import log_level, logger
from .validate import DSValidator, MetaConvention

yaml = YAML()

app = typer.Typer()


def _check_rel_prefix(prefix: str):
    """Validate prefix argument."""
    valid_protocols = ["http://", "https://", "file://", "cwd://", "local://"]
    valid_protocols += [f"v#{name}://" for name in loaded_handlers.keys()]

    if not prefix.find("://") > 0 or prefix.startswith(tuple(valid_protocols)):
        return prefix

    msg = "Unsupported URI protocol. "
    msg += "Supported protocols are: " + ", ".join(valid_protocols)
    raise typer.BadParameter(msg)


_def_meta_conv = MetaConvention().to_tuple()
"""Default metadata convention tuple (used if user provides no override)."""

_schema_arg = typer.Argument(
    ...,
    exists=True,
    dir_okay=False,
    readable=True,
    help="Path of YAML file with the DirSchema to be used for validation.",
)

_dir_arg = typer.Argument(
    ..., exists=True, help="Directory path (or suitable archive file) to be checked."
)

_conv_opt = typer.Option(
    _def_meta_conv,
    help=(
        "Used metadata file convention consisting of four strings "
        "(pathPrefix, pathSuffix, filePrefix, fileSuffix), at least one of which "
        "must be non-empty"
    ),
)

_local_basedir_opt = typer.Option(
    None,
    exists=True,
    help=(
        "Base path to resolve local:// URIs  "
        "[default: location of the passed dirschema]"
    ),
)

_rel_prefix_opt = typer.Option(
    "",
    help=(
        "Prefix to add to all relative paths "
        "(i.e. to paths not starting with a slash or some access protocol)."
    ),
    callback=_check_rel_prefix,
)

_verbose_opt = typer.Option(0, "--verbose", "-v", min=0, max=3)


@app.command()
def run_dirschema(
    schema: Path = _schema_arg,
    dir: Path = _dir_arg,
    conv: Tuple[str, str, str, str] = _conv_opt,
    local_basedir: Path = _local_basedir_opt,
    relative_prefix: str = _rel_prefix_opt,
    verbose: int = _verbose_opt,
) -> None:
    """Run dirschema validation of a directory against a schema.

    Performs validation according to schema and prints all unsatisfied constraints.
    """
    logger.setLevel(log_level[verbose])
    local_basedir = local_basedir or schema.parent
    dsv = DSValidator(
        schema,
        MetaConvention.from_tuple(*conv),
        local_basedir=local_basedir,
        relative_prefix=relative_prefix,
    )
    if errors := dsv.validate(dir):
        logger.debug(f"Validation of '{dir}' failed")
        dsv.format_errors(errors, sys.stdout)
        raise typer.Exit(code=1)
    logger.debug(f"Validation of '{dir}' successful")
