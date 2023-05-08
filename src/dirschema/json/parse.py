"""Helper functions to allow using JSON and YAML interchangably + take care of $refs."""

import io
import json
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.request import urlopen

from jsonref import JsonLoader, JsonRef
from ruamel.yaml import YAML

yaml = YAML(typ="safe")


def to_uri(
    path: str, local_basedir: Optional[Path] = None, relative_prefix: str = ""
) -> str:
    """Given a path or URI, normalize it to an absolute path.

    If the path is relative and without protocol, it is prefixed with `relative_prefix`
    before attempting to resolve it (by default equal to prepending `cwd://`)

    If path is already http(s):// or file://... path, do nothing to it.
    If the path is absolute (starts with a slash), just prepend file://
    If the path is cwd://, resolve based on CWD (even if starting with a slash)
    If the path is local://, resolve based on `local_basedir` (if missing, CWD is used)

    Result is either http(s):// or a file:// path that can be read with urlopen.
    """
    local_basedir = local_basedir or Path("")
    if str(path)[0] != "/" and str(path).find("://") < 0:
        path = relative_prefix + path

    prot, rest = "", ""
    prs = str(path).split("://")
    if len(prs) == 1:
        rest = prs[0]
    else:
        prot, rest = prs

    if prot.startswith(("http", "file")):
        return path  # nothing to do
    elif prot == "local":
        # relative, but not to CWD, but a custom path
        rest = str((local_basedir / rest.lstrip("/")).absolute())
    elif prot == "cwd":
        # like normal resolution of relative,
        # but absolute paths are still interpreted relative,
        # so cwd:// and cwd:/// are lead to the same results
        rest = str((Path(rest.lstrip("/"))).absolute())
    elif prot == "":
        # relative paths are made absolute
        if not Path(rest).is_absolute():
            rest = str((Path(rest)).absolute())
    else:
        raise ValueError(f"Unknown protocol: {prot}")

    return f"file://{rest}"


class ExtJsonLoader(JsonLoader):
    """Extends JsonLoader with capabilities.

    Adds support for:

    * loading YAML
    * resolving relative paths
    """

    def __init__(
        self, *, local_basedir: Optional[Path] = None, relative_prefix: str = ""
    ):
        """Initialize loader with URI resolution arguments."""
        super().__init__()
        self.local_basedir = local_basedir
        self.rel_prefix = relative_prefix

    def __call__(self, uri: str, **kwargs):
        """Try loading passed uri as YAML if loading as JSON fails."""
        uri = to_uri(uri, self.local_basedir, self.rel_prefix)  # normalize path/uri
        try:
            return super().__call__(uri, **kwargs)
        except json.JSONDecodeError:
            strval = urlopen(uri).read().decode("utf-8")  # nosec
            res = yaml.load(io.StringIO(strval, **kwargs))
            if self.cache_results:
                self.store[uri] = res
            return res


def loads_json_or_yaml(dat: str):
    """Parse a JSON or YAML object from a string."""
    try:
        return json.loads(dat)
    except json.JSONDecodeError:
        return yaml.load(io.StringIO(dat))


def init_loader(kwargs):
    """Initialize JSON/YAML loader from passed kwargs dict, removing its arguments."""
    return ExtJsonLoader(
        local_basedir=kwargs.pop("local_basedir", None),
        relative_prefix=kwargs.pop("relative_prefix", ""),
    )


def loads_json(dat: str, **kwargs) -> Dict[str, Any]:
    """Load YAML/JSON from a string, resolving all refs, both local and remote."""
    ldr = init_loader(kwargs)
    return JsonRef.replace_refs(loads_json_or_yaml(dat), loader=ldr, **kwargs)


def load_json(uri: str, **kwargs) -> Dict[str, Any]:
    """Load YAML/JSON from file/network + resolve all refs, both local and remote."""
    ldr = init_loader(kwargs)
    return JsonRef.replace_refs(ldr(str(uri)), loader=ldr, **kwargs)
