"""The ``prophetovol`` command line: a thin client of the service (ARC-1, INT-40).

Commands are added by later phases (data, registry, spec, stress, run, serve, demo).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import click

from prophetovol.core.home import HOME_ENV_VAR, resolve_home
from prophetovol.core.versions import software_versions


@dataclass(frozen=True)
class CliState:
    """Options shared by every command, stored on the click context.

    :param home: The resolved home directory (``--home``, ``PROPHETOVOL_HOME`` or the default).
    """

    home: Path


def _print_versions(ctx: click.Context, _param: click.Parameter, value: bool) -> None:
    """Print ProphetoVol's and its libraries' versions, then exit (the ``--version`` flag).

    :param ctx: The click context.
    :param _param: The option being processed (unused).
    :param value: Whether the flag was given.
    """
    if not value or ctx.resilient_parsing:
        return
    for name, version in software_versions().model_dump().items():
        click.echo(f"{name} {version}")
    ctx.exit()


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.option("--version", is_flag=True, expose_value=False, is_eager=True, callback=_print_versions,
              help="Show the versions of ProphetoVol and its libraries, then exit.")
@click.option("--home", type=click.Path(file_okay=False, path_type=Path), default=None,
              help=f"Home directory to use. Defaults to ${HOME_ENV_VAR}, then ~/.prophetovol.")
@click.pass_context
def main(ctx: click.Context, home: Path | None) -> None:
    """ProphetoVol: deterministic backtesting of index options.
    \f
    :param ctx: The click context.
    :param home: The ``--home`` option, if given.
    """
    ctx.obj = CliState(home=resolve_home(home))
