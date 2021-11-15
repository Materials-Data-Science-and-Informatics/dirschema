# dirschema

A directory structure and metadata linter based on JSON Schema.

JSON Schema is great for validating (files containing) JSON objects that e.g. contain
metadata, but these are only the smallest pieces in the organization of a whole directory
structure, e.g. of some dataset of project.
When working on datasets of a certain kind, they might contain various types of data,
each different file requiring different accompanying metadata, based on its file type
and/or location.
DirSchema combines JSON Schema and regexes into a solution to enforce structural
dependencies and metadata requirements in directories and directory-like archives.
With it you can for example check that:

* only files of a certain type are in a location (e.g. only `jpg` files in directory `img`)
* for each data file there exists a metadata file (e.g. `test.jpg` has `test.jpg_meta.json`)
* each metadata file is valid according to some JSON Schema

If validating these kinds of constraints looks appealing to you, this tool is for you!

## Installation and Usage

Install the tool using `pip install` just as any other Python package.

Read the [manual](./MANUAL.md) to learn how to write a dirschema.

Given a DirSchema file and a directory that needs to be checked, just run:
```
dirschema my_dirschema.yaml some/directory
```
If there is no output, everything is fine. Otherwise, the tool will return for each
checked file the violated rules.

You can call the validation from Python using the class `DSValidator` in
`dirschema.validator`, e.g. `DSValidator("/path/to/dirschema").validate("/dataset/path")`

## Development

This project uses [Poetry](https://python-poetry.org/) for dependency management.

Clone this repository and run `poetry install`.

Run `pre-commit install` after cloning to enable pre-commit to enforce the required linting hooks.

Run `pytest` before merging your changes to make sure you did not break anything.

To generate documentation, run `pdoc -o docs python_app_template`.

To check coverage, use `pytest --cov`.

To run the tests with different Python versions, run `tox`.
You can use [pyenv](https://github.com/pyenv/pyenv)
to manage and install other Python interpreter versions without touching the system.
You should install the versions in the `.python-version` file.
