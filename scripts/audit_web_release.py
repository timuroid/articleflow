"""Read-only inventory of a private Web 017 tarball; never extracts its contents."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tarfile
from pathlib import Path, PurePosixPath


ROOT = "articleflow-web-017"
REQUIRED = {
    "pyproject.toml",
    "src/articleflow/web017.py",
    "src/articleflow/structure017.py",
    "src/articleflow/web_static017/index.html",
    "scripts/install-web017.sh",
    "scripts/enable-https017.sh",
}
PUBLIC_PREFIXES = ("src/", "tests/", "scripts/", "docs/")
PUBLIC_ROOT_FILES = {"README.md", "pyproject.toml", "agent.md", "AGENTS.md", ".gitignore"}
MAX_ARCHIVE_BYTES = 128 * 1024 * 1024
MAX_MEMBERS = 10_000
MAX_UNCOMPRESSED_BYTES = 1024 * 1024 * 1024


class ReleaseError(ValueError):
    """The archive is unavailable, malformed, or incomplete."""


def inspect(archive: Path, expected_sha256: str | None = None) -> dict:
    if not archive.is_file():
        raise ReleaseError("архив не найден")
    if archive.stat().st_size > MAX_ARCHIVE_BYTES:
        raise ReleaseError("архив превышает ограничение проверки")
    with archive.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    if expected_sha256 and digest.lower() != expected_sha256.lower():
        raise ReleaseError("SHA-256 архива не совпадает с ожидаемым")

    seen: set[str] = set()
    files: set[str] = set()
    public_count = 0
    private_count = 0
    total_bytes = 0
    with tarfile.open(archive, "r:gz") as bundle:
        for index, member in enumerate(bundle):
            if index >= MAX_MEMBERS:
                raise ReleaseError("слишком много элементов архива")
            name = member.name
            path = PurePosixPath(name)
            if (
                path.is_absolute()
                or ".." in path.parts
                or "\\" in name
                or not path.parts
                or path.parts[0] != ROOT
            ):
                raise ReleaseError("найден небезопасный путь в архиве")
            if not (member.isfile() or member.isdir()):
                raise ReleaseError("в архиве есть ссылка или специальный файл")
            if name in seen:
                raise ReleaseError("в архиве есть повторяющийся путь")
            seen.add(name)
            if member.isdir():
                continue
            total_bytes += member.size
            if total_bytes > MAX_UNCOMPRESSED_BYTES:
                raise ReleaseError("распакованный объём превышает ограничение проверки")
            relative = "/".join(path.parts[1:])
            files.add(relative)
            if relative.startswith(PUBLIC_PREFIXES) or relative in PUBLIC_ROOT_FILES:
                public_count += 1
            else:
                private_count += 1

    missing = sorted(REQUIRED - files)
    if missing:
        raise ReleaseError("не хватает обязательных файлов: " + ", ".join(missing))
    return {
        "sha256": digest,
        "members": len(seen),
        "uncompressed_bytes": total_bytes,
        "public_candidates": public_count,
        "private_or_unclassified_files": private_count,
        "ready_for_manual_review": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--sha256", help="ожидаемый хеш из отдельного доверенного канала")
    args = parser.parse_args()
    try:
        result = inspect(args.archive, args.sha256)
    except (ReleaseError, OSError, tarfile.TarError) as exc:
        print(f"Ошибка проверки релиза: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print("Кандидаты в публичные файлы всё ещё требуют проверки содержимого.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
