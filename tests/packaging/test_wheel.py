"""DIST-1: the built wheel is pure Python and installs and imports on its own."""

from __future__ import annotations

import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def wheel(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Build the wheel once for this module, without network access (no build isolation).

    :param tmp_path_factory: pytest's temporary directory factory.
    :returns: The path of the built wheel.
    """
    out = tmp_path_factory.mktemp("dist")
    subprocess.run([sys.executable, "-m", "build", "--wheel", "--no-isolation", "--outdir", str(out), str(ROOT)],
                   check=True, capture_output=True, text=True)
    wheels = list(out.glob("prophetovol-*.whl"))
    assert len(wheels) == 1
    return wheels[0]


@pytest.mark.slow
def test_wheel_is_pure_python(wheel):
    assert wheel.name == "prophetovol-0.1.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel) as zf:
        names = zf.namelist()
        assert not [n for n in names if n.endswith((".pyd", ".so", ".c", ".dll"))]
        assert "prophetovol/__init__.py" in names and "prophetovol/cli/__init__.py" in names
        assert "prophetovol/reference/defaults/underlyings/SPX.yaml" in names
        assert "prophetovol/reference/defaults/data_sources/ivolatility_eod.yaml" in names
        meta = zf.read("prophetovol-0.1.0.dist-info/METADATA").decode()
        entry_points = zf.read("prophetovol-0.1.0.dist-info/entry_points.txt").decode()
        wheel_info = zf.read("prophetovol-0.1.0.dist-info/WHEEL").decode()
    assert "Root-Is-Purelib: true" in wheel_info
    assert "Requires-Dist: duckdb" in meta and "Requires-Python: >=3.11" in meta
    assert "prophetovol = prophetovol.cli:main" in entry_points
    assert not [n for n in names if n.startswith(("tests/", "specs/"))]


@pytest.mark.slow
def test_wheel_installs_and_imports_from_a_clean_folder(wheel, tmp_path):
    target = tmp_path / "site"
    subprocess.run([sys.executable, "-m", "pip", "install", "--no-deps", "--no-index", "--quiet",
                    "--disable-pip-version-check", "--target", str(target), str(wheel)], check=True)
    # Dependencies come from the test environment; the package itself must come from the wheel.
    code = (f"import sys; sys.path.insert(0, {str(target)!r}); import prophetovol, prophetovol.cli; "
            "from prophetovol.reference.defaults import default_underlyings; "
            "print(prophetovol.__file__); print(prophetovol.__version__); print(len(default_underlyings()['SPX'].roots))")
    out = subprocess.run([sys.executable, "-c", code], check=True, capture_output=True, text=True).stdout.split()
    assert Path(out[0]).is_relative_to(target) and out[1] == "0.1.0"
    assert out[2] == "40"  # the shipped root table loads from the installed wheel
