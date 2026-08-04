"""Discover validator classes by importing the modules that define them.

Builtins ship with the engine. A repo may also point `[validators] paths` in
`.validator.toml` at its own directories, and those merge with the builtins
under one namespace -- which is what lets a project add manifest-specific rules
without forking the engine.
"""

import importlib.util
import pathlib

from toolshed.validator.base import Validator

_BUILTIN_DIR = pathlib.Path(__file__).resolve().parent / "validators"


def _load_module(py_file: pathlib.Path, mod_name: str):
    spec = importlib.util.spec_from_file_location(mod_name, py_file)
    if spec is None or spec.loader is None:
        raise ValueError(f"could not load validator module {py_file}")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except ImportError as e:
        # Most often a third-party engine the validator wraps is absent. Name the
        # file so the fix is obvious rather than a bare traceback from an import.
        raise ValueError(f"{py_file}: {e}") from e
    return module


def _validators_in(module) -> list[type[Validator]]:
    return [
        attr
        for attr in vars(module).values()
        if isinstance(attr, type)
        and issubclass(attr, Validator)
        and attr is not Validator
    ]


def _collect(
    directory: pathlib.Path, prefix: str, into: dict[str, type[Validator]]
) -> None:
    for py_file in sorted(directory.glob("*.py")):
        if py_file.name.startswith("__"):
            continue
        module = _load_module(py_file, f"{prefix}._{py_file.stem}")
        for cls in _validators_in(module):
            existing = into.get(cls.name)
            if existing is not None and existing is not cls:
                raise ValueError(
                    f"duplicate validator name {cls.name!r}: {existing} and {cls}"
                )
            into[cls.name] = cls


def all_validators(
    extra_paths: list[pathlib.Path] | None = None,
) -> dict[str, type[Validator]]:
    """Every validator class, keyed by its registered name.

    Builtins load first, so a repo-local validator that reuses a builtin's name
    is a hard error rather than a silent shadow.
    """
    result: dict[str, type[Validator]] = {}
    _collect(_BUILTIN_DIR, "toolshed.validator.validators", result)

    for path in extra_paths or []:
        if not path.is_dir():
            raise ValueError(f"validator path is absent or not a directory: {path}")
        _collect(path, f"toolshed.validator.external.{path.name}", result)

    return result
