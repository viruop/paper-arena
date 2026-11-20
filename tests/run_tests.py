"""Runs the arena's code tests, each on a fresh throwaway copy of the repository, so no test can change a real
file or see what another left behind.

    python tests/run_tests.py              every test_*.py in this folder
    python tests/run_tests.py risk data    only those whose file name contains one of these words

Each test file also runs on its own: python tests/<file> <repo copy> <scratch folder>. The browser tests need
Playwright with Chromium (pip install playwright==1.63.0, then python -m playwright install chromium) and the
Zerodha test needs Node. .github/workflows/tests.yml runs them all whenever code is uploaded.
Exits with 1 if any test fails.
"""

import ast
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
LIMIT = 600                         # seconds one test file may take (the board test downloads the day's prices)


def tests():
    """Every test file here, with what it says it checks (its docstring up to the line on how to run it)."""
    out = []
    for name in sorted(os.listdir(HERE)):
        if name.startswith("test_") and name.endswith(".py"):
            with open(os.path.join(HERE, name), encoding="utf-8") as f:
                doc = (ast.get_docstring(ast.parse(f.read())) or "").splitlines()
            what = []
            for line in doc:
                if line.strip().startswith("python") or not line.strip():
                    break
                what.append(line.strip())
            out.append((name, " ".join(what)))
    return out


def main(words):
    picked = [(name, what) for name, what in tests() if not words or any(w in name for w in words)]
    if not picked:
        print("No test file matches: " + " ".join(words))
        return 1
    scratch = tempfile.mkdtemp(prefix="arena_tests_")
    failed = []
    try:
        for name, what in picked:
            start = time.time()
            copy, work = os.path.join(scratch, name[:-3], "repo"), os.path.join(scratch, name[:-3], "scratch")
            shutil.copytree(REPO, copy, ignore=shutil.ignore_patterns(".git", "site", "__pycache__", "tests"))
            os.makedirs(work)
            try:
                run = subprocess.run([sys.executable, os.path.join(HERE, name), copy, work], stdout=subprocess.PIPE,
                                     stderr=subprocess.STDOUT, text=True, env=dict(os.environ, PYTHONUNBUFFERED="1"),
                                     timeout=LIMIT)
                code, lines = run.returncode, run.stdout.strip().splitlines()   # in order: a traceback comes last
            except subprocess.TimeoutExpired as late:
                out = late.stdout.decode(errors="replace") if isinstance(late.stdout, bytes) else (late.stdout or "")
                code, lines = 1, out.strip().splitlines() + [f"stopped after {LIMIT // 60} minutes"]
            took = f"{time.time() - start:.0f}s"
            if code == 0:
                print(f"ok    {name} ({took}): {lines[-1] if lines else what}")
            else:
                failed.append(name)
                print(f"FAIL  {name} ({took}): {what}")
                print("\n".join("      " + line for line in lines[-40:]))
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    print(f"\n{len(picked) - len(failed)} of {len(picked)} test files passed."
          + (f" Failed: {', '.join(failed)}." if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
