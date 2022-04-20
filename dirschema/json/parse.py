"""Helper functions to allow using JSON and YAML interchangably and taking care of $refs."""

import io
import json
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.request import urlopen

from jsonref import JsonLoader, JsonRef
from ruamel.yaml import YAML

yaml = YAML(typ="safe")


def to_uri(path: str, local_basedir: Optional[Path] = None) -> str:
    """
    Given a path or URI, normalize it to an absolute path.

    If path is already http(s):// or file://... path, do nothing to it.
    If the path is absolute (starts with a slash), just prepend file://
    If the path is local://, resolve based on prefix (if not given, CWD is used)
    If the path is relative and without protocol, make absolute wrt. CWD

    Result is either http(s):// or a file:// path that can be read with urlopen.
    """
    local_basedir = local_basedir or Path("")

    prot, rest = "", ""
    prs = str(path).split("://")
    if len(prs) == 1:
        rest = prs[0]
    else:
        prot, rest = prs

    if prot.startswith(("http", "file")):
        return path  # nothing to do
    elif prot == "local":
        # relative, but not to CWD
        rest = str((local_basedir / rest.lstrip("/")).absolute())
    elif prot == "":
        # URL scheme missing -> normal path
        if not Path(rest).is_absolute():
            rest = str((Path("") / rest).absolute())
    else:
        raise ValueError(f"Unknown protocol: {prot}")

    return f"file://{rest}"


class ExtJsonLoader(JsonLoader):
    """Extends JsonLoader with capabilities.

    Adds support for:

    * loading YAML
    * resolving relative paths
    """

    def __init__(self, local_basedir: Optional[Path] = None):
        super().__init__()
        self.local_basedir = local_basedir

    def __call__(self, uri: str, **kwargs):
        """Try loading passed uri as YAML if loading as JSON fails."""
        uri = to_uri(uri, self.local_basedir)  # normalize path/uri
        try:
            return super().__call__(uri, **kwargs)
        except json.JSONDecodeError:
            strval = urlopen(uri).read().decode("utf-8")
            res = yaml.load(io.StringIO(strval, **kwargs))
            if self.cache_results:
                self.store[uri] = res
            return res


def loads_json(dat: str, **kwargs) -> Dict[str, Any]:
    """Load YAML/JSON from a string, resolving all refs, both local and remote."""
    unknown_kwargs = set(kwargs.keys()) - set(["local_basedir"])
    if len(unknown_kwargs) > 0:
        raise ValueError(f"Unknown keyword arguments: '{unknown_kwargs}'")
    local_basedir = kwargs.pop("local_basedir", None)

    res = None
    try:
        res = json.loads(dat)
    except json.JSONDecodeError:
        res = yaml.load(io.StringIO(dat))

    ldr = ExtJsonLoader(local_basedir)
    return JsonRef.replace_refs(res, loader=ldr, **kwargs)  # type: ignore


def load_json(uri: str, **kwargs) -> Dict[str, Any]:
    """Load YAML/JSON from file/network + resolve all refs, both local and remote."""
    unknown_kwargs = set(kwargs.keys()) - set(["local_basedir"])
    if len(unknown_kwargs) > 0:
        raise ValueError(f"Unknown keyword arguments: '{unknown_kwargs}'")
    local_basedir = kwargs.pop("local_basedir", None)

    ldr = ExtJsonLoader(local_basedir)
    return JsonRef.replace_refs(ldr(str(uri)), loader=ldr, **kwargs)  # type: ignore
