"""Robustness battery: end-to-end fixture runs of the Salmon-vs-baseline
comparison script via its environment-variable interface."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

pd = pytest.importorskip("pandas", reason="comparison script needs pandas")
pytest.importorskip("scipy", reason="comparison script needs scipy.stats")

SCRIPT = (Path(__file__).resolve().parent.parent
          / "RNAseq_Pipelines" / "compare_ryan_salmon.py")


def _quant(dirpath, names, tpms, reads):
    dirpath.mkdir(parents=True, exist_ok=True)
    (dirpath / "quant.sf").write_text(
        "Name\tLength\tEffectiveLength\tTPM\tNumReads\n"
        + "".join(f"{n}\t100\t90\t{t}\t{r}\n"
                  for n, t, r in zip(names, tpms, reads)))


def _fixture(tmp_path, baseline_rows, our_rows, map_lines):
    base = tmp_path / "baseline_quants"
    ours = tmp_path / "ours"
    out = tmp_path / "out"
    base.mkdir(); ours.mkdir(); out.mkdir()
    (base / "sample_map.txt").write_text("\n".join(map_lines) + "\n")
    for name, names, tpms, reads in baseline_rows:
        _quant(base / f"{name}_quant", names, tpms, reads)
    for srr, names, tpms, reads in our_rows:
        _quant(ours / srr, names, tpms, reads)
    env = dict(os.environ, LABSTACK_BASELINE_DIR=str(base),
               LABSTACK_QUANTS_DIR=str(ours), LABSTACK_OUT_DIR=str(out))
    return env, out


def _run(env, tmp_path):
    return subprocess.run([sys.executable, str(SCRIPT)], env=env,
                          capture_output=True, text=True, cwd=tmp_path)


NAMES = ["tx1", "tx2", "tx3", "tx4"]


class TestComparisonFixture:
    def test_identical_quants_r1(self, tmp_path):
        env, out = _fixture(
            tmp_path,
            [("ctrl", NAMES, [1.0, 2.0, 3.0, 4.0], [10, 20, 30, 40])],
            [("SRR1", NAMES, [1.0, 2.0, 3.0, 4.0], [10, 20, 30, 40])],
            ["SRR1\tctrl"])
        r = _run(env, tmp_path)
        assert r.returncode == 0
        csv = out / "Ryan_vs_Salmon_Comparison.csv"
        df = pd.read_csv(csv)
        assert df["TPM Pearson r"].iloc[0] == pytest.approx(1.0)

    def test_pipe_headers_split_to_transcript_id(self, tmp_path):
        env, out = _fixture(
            tmp_path,
            [("ctrl", [f"{n}|extra|header" for n in NAMES],
              [1.0, 2.0, 3.0, 4.0], [10, 20, 30, 40])],
            [("SRR1", NAMES, [1.0, 2.0, 3.0, 4.0], [10, 20, 30, 40])],
            ["SRR1\tctrl"])
        r = _run(env, tmp_path)
        assert r.returncode == 0
        df = pd.read_csv(out / "Ryan_vs_Salmon_Comparison.csv")
        assert df["Genes Compared"].iloc[0] == 4

    def test_missing_map_file_exits_clean(self, tmp_path):
        env = dict(os.environ,
                   LABSTACK_BASELINE_DIR=str(tmp_path / "nope"),
                   LABSTACK_QUANTS_DIR=str(tmp_path),
                   LABSTACK_OUT_DIR=str(tmp_path / "o"))
        r = _run(env, tmp_path)
        assert r.returncode == 0 and "not found" in r.stdout

    def test_missing_quant_skipped_not_crash(self, tmp_path):
        env, out = _fixture(
            tmp_path,
            [("ctrl", NAMES, [1, 2, 3, 4], [1, 2, 3, 4])],
            [],  # our quant missing for SRR1
            ["SRR1\tctrl"])
        r = _run(env, tmp_path)
        assert r.returncode == 0
        assert "Missing our quant" in r.stdout
        assert not (out / "Ryan_vs_Salmon_Comparison.csv").exists()

    def test_malformed_map_lines_ignored(self, tmp_path):
        env, out = _fixture(
            tmp_path,
            [("ctrl", NAMES, [1, 2, 3, 4], [1, 2, 3, 4])],
            [("SRR1", NAMES, [1, 2, 3, 4], [1, 2, 3, 4])],
            ["# comment", "", "NO_TABS", "SRR1\tctrl"])
        r = _run(env, tmp_path)
        assert r.returncode == 0
        df = pd.read_csv(out / "Ryan_vs_Salmon_Comparison.csv")
        assert len(df) == 1
