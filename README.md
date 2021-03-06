# dirschema

[
![Test](https://img.shields.io/github/workflow/status/Materials-Data-Science-and-Informatics/dirschema/test?label=test)
](https://github.com/Materials-Data-Science-and-Informatics/dirschema/actions?query=workflow:test)
[
![Coverage](https://img.shields.io/codecov/c/gh/Materials-Data-Science-and-Informatics/dirschema?token=4JU2SZFZDZ)
](https://app.codecov.io/gh/Materials-Data-Science-and-Informatics/dirschema)
[
![Docs](https://img.shields.io/badge/read-docs-success)
](https://materials-data-science-and-informatics.github.io/dirschema/dirschema.html)
[
![PyPIPkgVersion](https://img.shields.io/pypi/v/dirschema)
](https://pypi.org/project/dirschema/)

<br />
<div>
<img style="center-align: middle;" alt="DirSchema Logo" src="https://user-images.githubusercontent.com/89833997/152970983-267fa89e-9928-4393-a1fa-2a8fe3c6b9ba.png" width=70% height=70% />
&nbsp;&nbsp;
</div>
<br />

A directory structure and metadata linter based on JSON Schema.

[JSON Schema](https://json-schema.org/) is great for validating (files containing) JSON
objects that e.g. contain metadata, but these are only the smallest pieces in the
organization of a whole directory structure, e.g. of some dataset of project.
When working on datasets of a certain kind, they might contain various types of data,
each different file requiring different accompanying metadata, based on its file type
and/or location.

**DirSchema** combines JSON Schemas and regexes into a solution to enforce structural
dependencies and metadata requirements in directories and directory-like archives.
With it you can for example check that:

* only files of a certain type are in a location (e.g. only `jpg` files in directory `img`)
* for each data file there exists a metadata file (e.g. `test.jpg` has `test.jpg_meta.json`)
* each metadata file is valid according to some JSON Schema

If validating these kinds of constraints looks appealing to you, this tool is for you!

**Dirschema features:**
* Built-in support for schemas and metadata stored as JSON or YAML
* Built-in support for checking contents of ZIP and HDF5 archives
* Extensible validation interface for advanced needs beyond JSON Schema
* Both a Python library and a CLI tool to perform the validation

## Installation and Usage

Install the tool using `pip install` just as any other Python package.

Read the [manual](./MANUAL.md) to learn how to write a dirschema.

Given a DirSchema file and a directory that needs to be checked, just run:
```
dirschema my_dirschema.yaml some/directory
```
If there is no output, everything is fine. Otherwise, the tool will output
a detailed error report for each file or directory that failed validation.

You can call the validation from Python using the class `DSValidator` in
`dirschema.validate`, e.g. `DSValidator("/path/to/dirschema").validate("/dataset/path")`

## Development

This project uses [Poetry](https://python-poetry.org/) for dependency management.

Clone this repository and run `poetry install`.

Run `pre-commit install` after cloning to enable pre-commit to enforce the required linting hooks.

Run `pytest` before merging your changes to make sure you did not break anything.

To generate documentation, run `pdoc -o docs dirschema`.

To check coverage, use `pytest --cov`.

To run the tests with different Python versions, run `tox`.
You can use [pyenv](https://github.com/pyenv/pyenv)
to manage and install other Python interpreter versions without touching the system.
You should install the versions in the `.python-version` file.

## Acknowledgements

<div>
<img style="vertical-align: middle;" alt="HMC Logo" src="https://github.com/Materials-Data-Science-and-Informatics/Logos/raw/main/HMC/HMC_Logo_M.png" width=50% height=50% />
&nbsp;&nbsp;
<img style="vertical-align: middle;" alt="FZJ Logo" src="https://github.com/Materials-Data-Science-and-Informatics/Logos/raw/main/FZJ/FZJ.png" width=30% height=30% />
</div>
<br />

This project was developed at the Institute for Materials Data Science and Informatics
(IAS-9) of the J??lich Research Center and funded by the Helmholtz Metadata Collaboration
(HMC), an incubator-platform of the Helmholtz Association within the framework of the
Information and Data Science strategic initiative.
