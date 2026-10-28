"""The ``prophetovol`` command line: a thin client of the service (ARC-1, INT-40).

Data, spec, run, registry, jobs and documentation commands are available. Stress, serve and demo
commands arrive in later phases.
"""

from __future__ import annotations

import errno
import logging
import os
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import click
from pydantic import ValidationError

from prophetovol.core.errors import ProphetoVolError
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


@contextmanager
def _logging(home):
    """Log details to the home's file without exposing tracebacks in terminal messages."""
    log_file = home / "logs" / "server.log"
    try:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(log_file, encoding="utf-8")
    except OSError as exc:
        raise click.ClickException(f"Cannot open the home log {log_file}: {exc.strerror or type(exc).__name__}") from None
    logger = logging.getLogger("prophetovol")
    handlers, level, propagate = logger.handlers[:], logger.level, logger.propagate
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logger.handlers, logger.level, logger.propagate = [handler], logging.INFO, False
    try:
        yield log_file
    finally:
        logger.handlers, logger.level, logger.propagate = handlers, level, propagate
        handler.close()


def _stdout_closed(exc: OSError) -> bool:
    """Whether an error means the reader of standard output went away (``prophetovol data list | head``).

    Windows reports a closed pipe as ``EINVAL`` rather than ``EPIPE``, so that case is confirmed by
    trying to flush standard output again.

    :param exc: The error raised by the command.
    :returns: True when output can no longer be written.
    """
    if isinstance(exc, BrokenPipeError):
        return True
    if exc.errno != errno.EINVAL:
        return False
    try:
        sys.stdout.flush()
    except OSError:
        return True
    return False


def _silence_stdout() -> None:
    """Point standard output at the null device, so Python's exit-time flush stays quiet."""
    try:
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
    except (OSError, ValueError):
        pass


class _CliGroup(click.Group):
    """Translate service errors once at the CLI boundary (NFR-3)."""

    def invoke(self, ctx):
        """Invoke a command with file logging and readable errors.

        :param ctx: Click invocation context.
        :returns: The command's return value.
        """
        home = resolve_home(ctx.params.get("home"))
        with _logging(home) as log_file:
            try:
                return super().invoke(ctx)
            except (click.ClickException, click.Abort, click.exceptions.Exit):
                raise
            except ProphetoVolError as exc:
                raise click.ClickException(str(exc)) from None
            except ValidationError as exc:
                message = "; ".join(".".join(map(str, e["loc"])) + ": " + e["msg"] for e in exc.errors())
                raise click.ClickException(message) from None
            except OSError as exc:
                if not _stdout_closed(exc):
                    logging.getLogger("prophetovol.cli").exception("command failed")
                    raise click.ClickException(f"Unexpected error. Details were logged to {log_file}.") from None
                _silence_stdout()
                raise click.exceptions.Exit(1) from None
            except Exception:
                logging.getLogger("prophetovol.cli").exception("command failed")
                raise click.ClickException(f"Unexpected error. Details were logged to {log_file}.") from None


@click.group(cls=_CliGroup, context_settings={"help_option_names": ["-h", "--help"]})
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
    _tolerant_output()
    ctx.obj = CliState(home=resolve_home(home))


def _tolerant_output() -> None:
    """Replace characters the output cannot encode instead of failing.

    Windows pipes and redirects default to cp1252, which has no ``≤`` or ``→``; field descriptions and
    schemas contain such characters.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass


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


# Imported after the root command exists; these commands use only service operations.
from prophetovol.cli.commands import data, docs, jobs, registry, run, spec

main.add_command(data)
main.add_command(spec)
main.add_command(run)
main.add_command(registry)
main.add_command(jobs)
main.add_command(docs)
