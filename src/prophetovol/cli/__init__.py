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


@main.group("testdata")
def testdata() -> None:
    """Synthetic vendor-format data for tests, the demo and trying things out."""


@testdata.command("generate")
@click.option("--out", "out_dir", type=click.Path(file_okay=False, path_type=Path), required=True,
              help="Folder to write data_download*.csv files into (existing ones there are replaced).")
@click.option("--start", "start_date", type=click.DateTime(["%Y-%m-%d"]), required=True, help="First date, YYYY-MM-DD.")
@click.option("--end", "end_date", type=click.DateTime(["%Y-%m-%d"]), required=True, help="Last date, YYYY-MM-DD.")
@click.option("--seed", type=int, default=7, show_default=True, help="Random seed.")
@click.option("--conventions", type=click.Choice(["current", "older"]), default="current", show_default=True,
              help="current: the vendor from Jun 2018; older: five-character codes, historical roots, "
                   "Saturday expirations, one price per date, discounted deltas.")
@click.option("--rows-per-file", type=int, default=None, help="Split into several files, as the vendor does.")
def testdata_generate(out_dir: Path, start_date, end_date, seed: int, conventions: str,
                      rows_per_file: int | None) -> None:
    """Write synthetic option files in the exact ivolatility format.
    \f
    :param out_dir: The output folder.
    :param start_date: First date.
    :param end_date: Last date.
    :param seed: Random seed.
    :param conventions: ``current`` or ``older``.
    :param rows_per_file: Rows per file before starting a new one, if any.
    """
    from prophetovol.testdata.generator import GeneratorConfig, generate

    summary = generate(GeneratorConfig(start_date=start_date.date(), end_date=end_date.date(), seed=seed,
                                       conventions=conventions, rows_per_file=rows_per_file), out_dir)
    click.echo(f"wrote {summary.rows:,} rows for {summary.dates} dates and {summary.expirations} expirations "
               f"to {len(summary.files)} file(s) in {out_dir}")
    click.echo(f"quirks: {summary.crossed_quotes} crossed quotes, {summary.zero_asks} zero asks, "
               f"{summary.flagged} flagged rows")
