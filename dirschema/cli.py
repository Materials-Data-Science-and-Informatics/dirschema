"""CLI interface of dirschema."""

import sys
from pathlib import Path

import typer
from ruamel.yaml import YAML

from .validator import DSValidator

yaml = YAML()

app = typer.Typer()


@app.command()
def check(
    schema: Path = typer.Argument(..., exists=True, dir_okay=False, readable=True),
    dir: Path = typer.Argument(..., exists=True),
) -> None:
    """
    Run dirschema validation of a directory against a schema.

    Take a YAML or JSON DirSchema and a directory (or suitable archive),
    perform validation according to schema and print all unsatisfied constraints.
    """
    dsv = DSValidator(schema)
    errors = dsv.validate(dir)
    if errors:
        dsv.format_errors(errors, sys.stdout)
        sys.exit(1)


if __name__ == "__main__":
    typer.run(app)
