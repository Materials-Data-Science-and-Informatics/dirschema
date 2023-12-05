![Project status](https://img.shields.io/badge/project%20status-alpha-%23ff8000)
[
![Docs](https://img.shields.io/badge/read-docs-success)
](https://materials-data-science-and-informatics.github.io/dirschema)
[
![CI](https://img.shields.io/github/actions/workflow/status/Materials-Data-Science-and-Informatics/dirschema/ci.yml?branch=main&label=ci)
](https://github.com/Materials-Data-Science-and-Informatics/dirschema/actions/workflows/ci.yml)
[
![Test Coverage](https://materials-data-science-and-informatics.github.io/dirschema/main/coverage_badge.svg)
](https://materials-data-science-and-informatics.github.io/dirschema/main/coverage)
[
![PyPIPkgVersion](https://img.shields.io/pypi/v/dirschema)
](https://pypi.org/project/dirschema/)

<!-- --8<-- [start:abstract] -->
# dirschema

<br />
<div>
<img style="center-align: middle;" alt="DirSchema Logo" src="https://raw.githubusercontent.com/Materials-Data-Science-and-Informatics/Logos/main/DirSchema/DirSchema_Logo_Text.png" width=70% height=70% />
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

<!-- --8<-- [end:abstract] -->
<!-- --8<-- [start:quickstart] -->

## Installation

```
pip install dirschema
```

## Getting Started

The `dirschema` tool needs as input:

* a DirSchema YAML file (containing a specification), and
* a path to a directory or file (e.g. zip file) that should be checked.

You can run it like this:

```
dirschema my_dirschema.yaml DIRECTORY_OR_ARCHIVE_PATH
```

If the validation was successful, there will be no output.
Otherwise, the tool will output a list of errors (e.g. invalid metadata, missing files, etc.).

You can also use `dirschema` from other Python code as a library:

```python
from dirschema.validate import DSValidator
DSValidator("/path/to/dirschema").validate("/dataset/path")
```

Similarly, the method will return an error dict, which will be empty if the validation succeeded.

<!-- --8<-- [end:quickstart] -->

**You can find more information on using and contributing to this repository in the
[documentation](https://materials-data-science-and-informatics.github.io/dirschema/main).**

<!-- --8<-- [start:citation] -->

## How to Cite

If you want to cite this project in your scientific work,
please use the [citation file](https://citation-file-format.github.io/)
in the [repository](https://github.com/Materials-Data-Science-and-Informatics/dirschema/blob/main/CITATION.cff).

<!-- --8<-- [end:citation] -->
<!-- --8<-- [start:acknowledgements] -->

## Acknowledgements

We kindly thank all
[authors and contributors](https://materials-data-science-and-informatics.github.io/dirschema/latest/credits).

<div>
<img style="vertical-align: middle;" alt="HMC Logo" src="https://github.com/Materials-Data-Science-and-Informatics/Logos/raw/main/HMC/HMC_Logo_M.png" width=50% height=50% />
&nbsp;&nbsp;
<img style="vertical-align: middle;" alt="FZJ Logo" src="https://github.com/Materials-Data-Science-and-Informatics/Logos/raw/main/FZJ/FZJ.png" width=30% height=30% />
</div>
<br />

This project was developed at the Institute for Materials Data Science and Informatics
(IAS-9) of the Jülich Research Center and funded by the Helmholtz Metadata Collaboration
(HMC), an incubator-platform of the Helmholtz Association within the framework of the
Information and Data Science strategic initiative.

<!-- --8<-- [end:acknowledgements] -->
