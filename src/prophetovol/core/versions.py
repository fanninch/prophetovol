"""Software versions recorded on every run (RUN-30, AUD-3) and shown by ``prophetovol --version``."""

from __future__ import annotations

import platform
from importlib import metadata

from pydantic import BaseModel, ConfigDict, Field

import prophetovol


def _distribution_version(name: str) -> str:
    """Return the installed version of a distribution, or ``"not installed"``.

    :param name: The distribution name, as on PyPI.
    :returns: The version string.
    """
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return "not installed"


class SoftwareVersions(BaseModel):
    """The versions of ProphetoVol and of the libraries whose behaviour affects results."""

    model_config = ConfigDict(frozen=True)

    prophetovol: str = Field(description="The ProphetoVol package version.")
    python: str = Field(description="The Python version, for example 3.12.2.")
    duckdb: str = Field(description="The DuckDB version (storage and queries).")
    ibis: str = Field(description="The Ibis version (query expressions, DATA-81).")
    pyarrow: str = Field(description="The PyArrow version (columnar data and Parquet).")
    numpy: str = Field(description="The NumPy version (numerics).")
    scipy: str = Field(description="The SciPy version (the normal distribution and statistics).")
    pydantic: str = Field(description="The pydantic version (models and validation).")
    exchange_calendars: str = Field(
        description="The exchange_calendars version, which is also the trading calendar's version (REF-11).",
    )


def software_versions() -> SoftwareVersions:
    """Collect the versions of ProphetoVol, Python and the libraries that affect results.

    :returns: The versions, as installed in the running environment.
    """
    return SoftwareVersions(
        prophetovol=prophetovol.__version__,
        python=platform.python_version(),
        duckdb=_distribution_version("duckdb"),
        ibis=_distribution_version("ibis-framework"),
        pyarrow=_distribution_version("pyarrow"),
        numpy=_distribution_version("numpy"),
        scipy=_distribution_version("scipy"),
        pydantic=_distribution_version("pydantic"),
        exchange_calendars=_distribution_version("exchange_calendars"),
    )
