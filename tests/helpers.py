"""Shared helpers for the unit tests. Standard library only.

Run every test from the repository root:

  python3 -m unittest discover -s tests -t . -v
"""
import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_module(name, relpath):
    """Import a script that is not in a package (sdk-matrix/matrix.py, guide/check_guide.py, ...)."""
    spec = importlib.util.spec_from_file_location(name, ROOT / relpath)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def write_tree(base, files):
    """Write {relative path: str, dict or list} under base; dicts and lists become JSON."""
    for rel, content in files.items():
        p = Path(base) / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if not isinstance(content, str):
            content = json.dumps(content, indent=1)
        p.write_text(content)


def write_jsonl(base, rel, rows):
    write_tree(base, {rel: "".join(json.dumps(r) + "\n" for r in rows)})


def run_script(relpath, *args, cwd=None):
    """Run a repository script with this Python; returns (exit status, stdout + stderr)."""
    p = subprocess.run([sys.executable, str(ROOT / relpath), *args], cwd=cwd or ROOT,
                       capture_output=True, text=True, timeout=300)
    return p.returncode, p.stdout + p.stderr


def call_main(fn, *argv):
    """Call a script's main() with sys.argv set; returns (return value or exit code, stdout)."""
    out = io.StringIO()
    old = sys.argv
    sys.argv = ["script", *argv]
    try:
        with contextlib.redirect_stdout(out):
            try:
                rc = fn()
            except SystemExit as e:
                rc = e.code
    finally:
        sys.argv = old
    return rc, out.getvalue()


@contextlib.contextmanager
def chdir(path):
    old = os.getcwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(old)
