"""The ``prophetovol`` command group: version, help and the home option."""

import click
from click.testing import CliRunner

from prophetovol.cli import CliState, main
from prophetovol.core.versions import software_versions


def test_version_lists_prophetovol_and_libraries():
    result = CliRunner().invoke(main, ["--version"])
    assert result.exit_code == 0
    lines = result.output.splitlines()
    assert lines[0] == "prophetovol 0.1.0"
    assert lines == [f"{k} {v}" for k, v in software_versions().model_dump().items()]


def test_help_mentions_home_option():
    result = CliRunner().invoke(main, ["--help"])
    assert result.exit_code == 0
    assert "--home" in result.output and "PROPHETOVOL_HOME" in result.output
    assert ":param" not in result.output  # reST fields stay out of the help text


@main.command("_show-home", hidden=True)
@click.pass_obj
def _show_home(state: CliState) -> None:
    """Print the resolved home (test helper)."""
    click.echo(str(state.home))


def test_home_option_beats_environment(tmp_path, tmp_home):
    runner = CliRunner()
    assert runner.invoke(main, ["_show-home"]).output.strip() == str(tmp_home.resolve())
    explicit = tmp_path / "explicit"
    out = runner.invoke(main, ["--home", str(explicit), "_show-home"]).output.strip()
    assert out == str(explicit.resolve())
