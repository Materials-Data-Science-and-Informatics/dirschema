# dirschema

A directory structure and metadata linter based on JSON Schema.

## Development

This project uses [Poetry](https://python-poetry.org/) for dependency management.

Clone this repository and run `poetry install`.

Pre-commit hooks should be enabled. If they are not, run `pre-commit install`.

Before commiting, run `pytest` and make sure you did not break anything.
Also check that the pre-commit hooks are run successfully.

To generate documentation, run `pdoc -o docs python_app_template`.

To check coverage, use `pytest --cov`.

To run the tests with different Python versions, run `tox`.
You can use [pyenv](https://github.com/pyenv/pyenv) 
to manage and install other Python interpreter versions without touching the system.
You should install the versions in the `.python-version` file.

