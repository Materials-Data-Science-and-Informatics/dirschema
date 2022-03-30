"""CLI interface of dirschema."""

import sys
from pathlib import Path
from typing import Tuple

import typer
from ruamel.yaml import YAML

from .validator import DSValidator, MetaConvention

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
        ("", "", "", ""),
        help=(
            "Used metadata file convention consisting of four strings "
            "(pathPrefix, pathSuffix, filePrefix, fileSuffix), at least one of which "
            "must be non-empty"
        ),
    ),
) -> None:
    """
    Run dirschema validation of a directory against a schema.

    Take a YAML or JSON DirSchema and a directory (or suitable archive),
    perform validation according to schema and print all unsatisfied constraints.
    """
    dsv = DSValidator(schema, MetaConvention.from_tuple(*conv))
    errors = dsv.validate(dir)
    if errors:
        dsv.format_errors(errors, sys.stdout)
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
