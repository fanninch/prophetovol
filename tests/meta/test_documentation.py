"""Documentation rules that apply to the whole package.

* DOC-1: every field of every pydantic model has a description.
* DOC-4: every public module, class, function and method has a reStructuredText docstring,
  and every parameter of a public function or method is documented with ``:param name:``.
"""

from __future__ import annotations

import enum
import importlib
import inspect
import pkgutil
from types import ModuleType

import pydantic

import prophetovol


def _modules() -> list[ModuleType]:
    mods = [prophetovol]
    for info in pkgutil.walk_packages(prophetovol.__path__, "prophetovol."):
        mods.append(importlib.import_module(info.name))
    return mods


def _own_public(module: ModuleType):
    for name, obj in vars(module).items():
        if name.startswith("_"):
            continue
        if (inspect.isclass(obj) or inspect.isfunction(obj)) and getattr(obj, "__module__", None) == module.__name__:
            yield name, obj


def _documented_params(doc: str) -> set[str]:
    params = set()
    for line in doc.splitlines():
        line = line.strip()
        if line.startswith(":param "):
            params.add(line[len(":param "):].split(":", 1)[0].split()[-1])
    return params


def _missing_params(func, doc: str, skip_first: bool) -> list[str]:
    try:
        sig = inspect.signature(func)
    except (TypeError, ValueError):
        return []
    names = [p.name for p in sig.parameters.values()
             if p.kind not in (p.VAR_POSITIONAL, p.VAR_KEYWORD)]
    if skip_first and names:
        names = names[1:]
    return sorted(set(names) - _documented_params(doc))


def test_every_pydantic_field_has_a_description():
    models, problems = [], []
    for module in _modules():
        for name, obj in _own_public(module):
            if inspect.isclass(obj) and issubclass(obj, pydantic.BaseModel):
                models.append(obj)
                for field_name, field in obj.model_fields.items():
                    if not (field.description or "").strip():
                        problems.append(f"{module.__name__}.{name}.{field_name}")
    assert models, "expected at least one pydantic model to check"
    assert not problems, f"fields without a description: {problems}"


def test_public_code_has_rest_docstrings():
    problems = []
    for module in _modules():
        if not (module.__doc__ or "").strip():
            problems.append(f"{module.__name__}: module docstring")
        for name, obj in _own_public(module):
            where = f"{module.__name__}.{name}"
            doc = inspect.getdoc(obj) or ""
            if not doc.strip():
                problems.append(f"{where}: docstring")
                continue
            if inspect.isfunction(obj):
                problems += [f"{where}: :param {p}:" for p in _missing_params(obj, doc, skip_first=False)]
                continue
            # classes: an __init__ defined on the class documents its parameters in the class docstring
            is_model = issubclass(obj, pydantic.BaseModel)
            if "__init__" in vars(obj) and not is_model and not issubclass(obj, enum.Enum):
                problems += [f"{where}: :param {p}:" for p in _missing_params(obj.__init__, doc, skip_first=True)]
            for attr, member in vars(obj).items():
                if attr.startswith("_") and attr != "__str__":
                    continue
                func = member.__func__ if isinstance(member, (classmethod, staticmethod)) else member
                if isinstance(member, property):
                    func = member.fget
                if not inspect.isfunction(func):
                    continue
                mdoc = inspect.getdoc(func) or ""
                if not mdoc.strip():
                    problems.append(f"{where}.{attr}: docstring")
                elif not isinstance(member, property):
                    problems += [f"{where}.{attr}: :param {p}:"
                                 for p in _missing_params(func, mdoc, skip_first=not isinstance(member, staticmethod))]
    assert not problems, "documentation problems:\n" + "\n".join(problems)
