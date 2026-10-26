"""Receiving an import's files (DATA-3, DATA-4, DATA-10, DATA-12).

An import takes one or more CSV files, folders of them (searched recursively), or zip archives
containing them. Every file is hashed while it is read, in chunks, never held whole in memory.
CSV files on the local disk are read where they are; zip members are extracted, as they are
hashed, into the import's working folder. Files uploaded through the API arrive in the same
folder and are handled the same way.
"""

from __future__ import annotations

import hashlib
import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path

from prophetovol.core.errors import ValidationFailed, ValidationIssue

CHUNK_BYTES = 8 * 1024 * 1024
"""Read and hash files in chunks of this size."""

DEFAULT_MAX_IMPORT_BYTES = 2 * 1024**3
"""The largest total uncompressed size of one import, by default (DATA-4)."""


@dataclass(frozen=True)
class ReceivedFile:
    """One CSV file of an import, ready to parse.

    :param name: The name to record: the file name, or ``archive.zip/member.csv`` for a zip member.
    :param path: Where the file is now on disk.
    :param size_bytes: Its uncompressed size.
    :param sha256: The SHA-256 of its contents.
    """

    name: str
    path: Path
    size_bytes: int
    sha256: str


def _hash_file(path: Path) -> str:
    """Hash a file in chunks.

    :param path: The file.
    :returns: Its SHA-256 as hexadecimal.
    """
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while chunk := handle.read(CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def plan_inputs(paths: list[Path], max_bytes: int = DEFAULT_MAX_IMPORT_BYTES) -> list[tuple[Path, str | None]]:
    """Expand an import's inputs into CSV files and zip members, checking existence and the size limit.

    Nothing is read or extracted yet, so a refused import costs nothing.

    :param paths: Files, folders and zip archives, in the order given.
    :param max_bytes: The largest total uncompressed size allowed.
    :returns: ``(path, member)`` pairs: ``member`` is ``None`` for a CSV file, or the member name inside a zip.
    :raises ValidationFailed: If an input is missing or of an unsupported type, nothing is found, or the
        total size exceeds the limit.
    """
    issues: list[ValidationIssue] = []
    items: list[tuple[Path, str | None]] = []
    total = 0
    for i, raw in enumerate(paths):
        path = Path(raw)
        where = f"paths.{i}"
        if not path.exists():
            issues.append(ValidationIssue(where, f"{path} does not exist"))
        elif path.is_dir():
            csvs = sorted(p for p in path.rglob("*") if p.is_file() and p.suffix.lower() == ".csv")
            if not csvs:
                issues.append(ValidationIssue(where, f"no .csv files in folder {path}"))
            for csv_path in csvs:
                items.append((csv_path, None))
                total += csv_path.stat().st_size
        elif path.suffix.lower() == ".csv":
            items.append((path, None))
            total += path.stat().st_size
        elif path.suffix.lower() == ".zip":
            with zipfile.ZipFile(path) as zf:
                members = sorted((m for m in zf.infolist() if not m.is_dir() and m.filename.lower().endswith(".csv")),
                                 key=lambda m: m.filename)
                if not members:
                    issues.append(ValidationIssue(where, f"no .csv files in archive {path}"))
                for m in members:
                    items.append((path, m.filename))
                    total += m.file_size
        else:
            issues.append(ValidationIssue(where, f"{path} is not a .csv file, a folder or a .zip archive"))
    if not issues and not items:
        issues.append(ValidationIssue("paths", "no files to import"))
    if total > max_bytes:
        issues.append(ValidationIssue("paths", f"the import is {total:,} bytes uncompressed, more than the limit of "
                                               f"{max_bytes:,} bytes; import fewer files at a time"))
    if issues:
        raise ValidationFailed(issues)
    return items


def receive(items: list[tuple[Path, str | None]], work_dir: Path) -> list[ReceivedFile]:
    """Hash every planned file, extracting zip members into the working folder as they are hashed.

    :param items: The output of :func:`plan_inputs`.
    :param work_dir: The import's working folder (created if needed).
    :returns: The received files, in input order.
    """
    work_dir.mkdir(parents=True, exist_ok=True)
    received: list[ReceivedFile] = []
    for n, (path, member) in enumerate(items):
        if member is None:
            received.append(ReceivedFile(path.name, path, path.stat().st_size, _hash_file(path)))
            continue
        target = work_dir / f"{n:03d}_{Path(member).name}"
        digest = hashlib.sha256()
        with zipfile.ZipFile(path) as zf, zf.open(member) as src, open(target, "wb") as dst:
            while chunk := src.read(CHUNK_BYTES):
                digest.update(chunk)
                dst.write(chunk)
        received.append(ReceivedFile(f"{path.name}/{member}", target, target.stat().st_size, digest.hexdigest()))
    return received


def clean_up(work_dir: Path) -> None:
    """Remove an import's working folder and everything in it.

    :param work_dir: The folder.
    """
    shutil.rmtree(work_dir, ignore_errors=True)
