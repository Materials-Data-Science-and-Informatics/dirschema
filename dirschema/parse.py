"""Helper functions to allow using JSON and YAML interchangably and taking care of $refs."""

import io
import json
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from urllib.request import urlopen

from jsonref import JsonLoader, JsonRef
from ruamel.yaml import YAML

yaml = YAML(typ="safe")


class JsonYamlLoader(JsonLoader):
    """Extends JsonLoader with capability of loading YAML as well."""

    def __call__(self, uri, **kwargs):
        """Try loading passed uri as YAML if loading as JSON fails."""
        try:
            return super().__call__(uri, **kwargs)
        except json.JSONDecodeError:
            res = yaml.load(io.StringIO(urlopen(uri).read().decode("utf-8"), **kwargs))
            if self.cache_results:
                self.store[uri] = res
            return res


def to_uri(path: str) -> str:
    """
    Given a path or URI, normalize it.

    This especially means adding file:// and making paths absolute.
    """
    prs = list(urlsplit(path))
    if prs[0] == "":  # URL scheme missing -> normal path -> make it a file:// abs_path
        prs[0] = "file"
        prs[2] = str(Path(prs[2]).absolute())
        return urlunsplit(prs)
    return path


def loads_json(dat: str, **kwargs):
    """Load YAML/JSON from a string, resolving all refs, both local and remote."""
    res = None
    try:
        res = json.loads(dat)
    except json.JSONDecodeError:
        res = yaml.load(io.StringIO(dat))
    return JsonRef.replace_refs(res, loader=JsonYamlLoader(), **kwargs)


def load_json(uri: str, **kwargs):
    """Load YAML/JSON from file/network +resolve all refs, both local and remote."""
    ldr = JsonYamlLoader()
    return JsonRef.replace_refs(ldr(uri), loader=ldr, **kwargs)
