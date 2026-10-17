"""Make a reproducible source-only release from a clean, committed Git tree."""
from __future__ import annotations

import argparse
import gzip
import subprocess
from pathlib import Path

from audit_web_release import inspect


def git(*args: str) -> bytes:
    return subprocess.check_output(["git", *args], cwd=Path(__file__).resolve().parents[1])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    if git("status", "--porcelain"):
        raise SystemExit("Commit and review the tree before packaging.")
    names = git("ls-tree", "-r", "--name-only", "HEAD").decode().splitlines()
    forbidden = [name for name in names if name.startswith(("private-fixtures/", "artifacts/", "var/"))
                 or name.endswith((".docx", ".pdf", ".pem", ".key")) or name == ".env"]
    if forbidden:
        raise SystemExit("Tracked private or binary paths require review before packaging.")
    tar_bytes = git("archive", "--format=tar", "--prefix=articleflow-web-017/", "HEAD")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("wb") as stream, gzip.GzipFile(fileobj=stream, mode="wb", mtime=0, filename="") as zipped:
        zipped.write(tar_bytes)
    result = inspect(args.output)
    print(f"{args.output}: {result['sha256']} ({result['members']} members)")


if __name__ == "__main__":
    main()
