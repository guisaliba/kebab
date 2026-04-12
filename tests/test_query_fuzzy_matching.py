import subprocess
import sys

from scripts.lib.paths import ROOT


def test_fuzzy_query_typo_retrieves_target_when_enabled() -> None:
    build = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "index" / "main.py"), "--target", "wiki"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert build.returncode == 0, build.stderr + build.stdout

    no_fuzzy = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "query" / "main.py"),
            "--question",
            "brod targetng meta ads",
            "--top-k",
            "3",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert no_fuzzy.returncode == 0, no_fuzzy.stderr + no_fuzzy.stdout

    fuzzy = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "query" / "main.py"),
            "--question",
            "brod targetng meta ads",
            "--top-k",
            "3",
            "--fuzzy",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert fuzzy.returncode == 0, fuzzy.stderr + fuzzy.stdout
    assert "wiki/tactics/broad-targeting.md" in fuzzy.stdout or "wiki/platforms/meta-ads.md" in fuzzy.stdout


def test_fuzzy_mixed_intent_typo_prioritizes_tactic_page() -> None:
    build = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "index" / "main.py"), "--target", "wiki"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert build.returncode == 0, build.stderr + build.stdout

    fuzzy = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "query" / "main.py"),
            "--question",
            "brod targting criativo fraco",
            "--top-k",
            "3",
            "--fuzzy",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert fuzzy.returncode == 0, fuzzy.stderr + fuzzy.stdout
    lines = [line for line in fuzzy.stdout.splitlines() if line.startswith("- ")]
    assert lines, fuzzy.stdout
    assert "wiki/tactics/broad-targeting.md" in lines[0], fuzzy.stdout


def test_alias_layer_can_be_disabled_for_runtime_ablation() -> None:
    with_alias = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "query" / "main.py"),
            "--question",
            "brod targting criativo fraco",
            "--top-k",
            "3",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert with_alias.returncode == 0, with_alias.stderr + with_alias.stdout

    without_alias = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "query" / "main.py"),
            "--question",
            "brod targting criativo fraco",
            "--top-k",
            "3",
            "--disable-aliases",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert without_alias.returncode == 0, without_alias.stderr + without_alias.stdout
    assert "consulted_layers: wiki" in with_alias.stdout
    assert "consulted_layers: wiki" in without_alias.stdout
