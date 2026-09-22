"""Syntax and preflight checks for the RNAseq_Pipelines scripts."""

import os
import py_compile
import shutil
import subprocess
from pathlib import Path

import pytest

PIPELINE_DIR = Path(__file__).resolve().parent.parent / "RNAseq_Pipelines"

SH_FILES = sorted(PIPELINE_DIR.glob("*.sh"))
PY_FILES = sorted(PIPELINE_DIR.glob("*.py"))
R_FILES = sorted(PIPELINE_DIR.glob("*.R"))

bash = shutil.which("bash")


@pytest.mark.parametrize("script", SH_FILES, ids=[p.name for p in SH_FILES])
def test_shell_syntax(script):
    if bash is None:
        pytest.skip("bash not available")
    result = subprocess.run(
        [bash, "-n", str(script)], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("script", PY_FILES, ids=[p.name for p in PY_FILES])
def test_python_syntax(script, tmp_path):
    py_compile.compile(str(script), cfile=str(tmp_path / "out.pyc"), doraise=True)


@pytest.mark.parametrize("script", R_FILES, ids=[p.name for p in R_FILES])
def test_r_syntax(script):
    rscript = shutil.which("Rscript")
    if rscript is None:
        pytest.skip("Rscript not available")
    result = subprocess.run(
        [rscript, "-e", f'parse(file="{script.as_posix()}")'],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("script", SH_FILES, ids=[p.name for p in SH_FILES])
def test_shell_fails_cleanly_on_missing_data_dir(script, tmp_path):
    """Each script must exit non-zero with a clear message when the data
    directory does not exist, rather than running against garbage paths."""
    if bash is None:
        pytest.skip("bash not available")
    env = dict(os.environ)
    env["LABSTACK_DATA_DIR"] = str(tmp_path / "nonexistent")
    env["LABSTACK_INDEX_DIR"] = str(tmp_path / "index")
    env["LABSTACK_OUT_DIR"] = str(tmp_path / "results")
    result = subprocess.run(
        [bash, str(script)], capture_output=True, text=True, env=env
    )
    assert result.returncode != 0
    assert "does not exist" in result.stderr
