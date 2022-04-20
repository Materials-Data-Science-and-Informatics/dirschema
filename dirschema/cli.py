"""CLI interface of dirschema."""

import sys
from pathlib import Path
from typing import Tuple

import typer
from ruamel.yaml import YAML

from .log import log_level, logger
from .validate import DSValidator, MetaConvention

yaml = YAML()


def typer_patch_cmd_ctx(app, ctx):
    """Workaround to patch context in commands."""
    if not hasattr(app, "_command"):
        app._command = app.command

    def no_linewrap_command(*dargs, **dkwargs):
        def decorator(function):
            res_ctx = {**ctx, **dkwargs.get("context_settings", {})}
            if "context_settings" in dkwargs:
                del dkwargs["context_settings"]
            return app._command(context_settings=res_ctx, *dargs, **dkwargs)(function)

        return decorator

    app.command = no_linewrap_command


ctx = dict(max_content_width=800)
app = typer.Typer(context_settings=ctx)  # does not work
typer_patch_cmd_ctx(app, ctx)

def_meta_conv = MetaConvention().to_tuple()
"""Default metadata convention, as tuple (used if user provides no override)."""


@app.command()
def check(
    schema: Path = typer.Argument(
        ...,
        exists=True,
        dir_okay=False,
        readable=True,
        help="DirSchema YAML file to validate against.",
    ),
    dir: Path = typer.Argument(..., exists=True, help="Path or file to be validated."),
    conv: Tuple[str, str, str, str] = typer.Option(
        def_meta_conv,
        help=(
            "Used metadata file convention consisting of four strings "
            "(pathPrefix, pathSuffix, filePrefix, fileSuffix), at least one of which "
            "must be non-empty"
        ),
    ),
    local_basedir: Path = typer.Option(
        None,
        exists=True,
        help=(
            "Base path to resolve local:// URIs "
            "(Default: location of the passed dirschema)."
        ),
    ),
    verbose: int = typer.Option(0, "--verbose", "-v", min=0, max=3),
) -> None:
    """
    Run dirschema validation of a directory against a schema.

    Input:
        schema: YAML or JSON DirSchema path
        dir: Directory path (or suitable archive file) to be checked,

    Performs validation according to schema and prints all unsatisfied constraints.
    """
    logger.setLevel(log_level[verbose])
    local_basedir = local_basedir or schema.parent
    dsv = DSValidator(
        schema, MetaConvention.from_tuple(*conv), local_basedir=local_basedir
    )
    if errors := dsv.validate(dir):
        dsv.format_errors(errors, sys.stdout)
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
