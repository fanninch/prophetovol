"""The reference data shipped with the package, loaded from YAML.

These defaults seed the catalog as version 1 of each definition (REF-2). Files are read with
:mod:`importlib.resources`, so they load the same from a wheel, an editable install or a zip.
"""

from __future__ import annotations

from importlib import resources

import yaml

from prophetovol.reference.models import DataSource, Underlying


def _load_all(folder: str) -> list[dict]:
    """Read every YAML file in a subfolder of the defaults, in file-name order.

    :param folder: The subfolder, ``underlyings`` or ``data_sources``.
    :returns: The parsed documents.
    """
    base = resources.files(__name__) / folder
    files = sorted((f for f in base.iterdir() if f.name.endswith(".yaml")), key=lambda f: f.name)
    return [yaml.safe_load(f.read_text(encoding="utf-8")) for f in files]


def default_underlyings() -> dict[str, Underlying]:
    """The shipped underlying configurations, keyed by symbol.

    :returns: The underlyings (Phase 1 ships SPX).
    """
    items = [Underlying.model_validate(doc) for doc in _load_all("underlyings")]
    return {u.symbol: u for u in items}


def default_data_sources() -> dict[str, DataSource]:
    """The shipped data-source configurations, keyed by id.

    :returns: The data sources (Phase 1 ships ivolatility_eod).
    """
    items = [DataSource.model_validate(doc) for doc in _load_all("data_sources")]
    return {d.source_id: d for d in items}
