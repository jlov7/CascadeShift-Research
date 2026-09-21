"""Descriptor-safe parsers and writers for caller-controlled CLI data."""

from __future__ import annotations

import json
import os
import stat
import uuid
from collections.abc import Iterable, Mapping
from contextlib import suppress
from pathlib import Path

import yaml

WORLD_MAX_BYTES = 1_048_576
JSON_MAX_BYTES = 2 * 1_048_576
MAX_PARSE_TOKENS = 100_000
MAX_PARSE_NODES = 100_000
MAX_PARSE_DEPTH = 64
MAX_YAML_ALIASES = 128
MAX_TASK_FILES = 128
MAX_TASK_ENTRIES_PER_DIRECTORY = 256
MAX_TASK_ENTRIES_TOTAL = 1_024


class BoundaryError(RuntimeError):
    """A stable, value-free boundary failure suitable for CLI output."""


def _path_parent_fd(path: Path, *, create_missing: bool, failure: str) -> tuple[int, str]:
    """Open a path's parent one component at a time without following links."""
    if not path.name or path.name in {".", ".."}:
        raise BoundaryError(failure)
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor: int | None = None
    try:
        if path.is_absolute():
            descriptor = os.open("/", flags)
            parts = path.parent.parts[1:]
        else:
            descriptor = os.open(".", flags)
            parts = path.parent.parts
        for part in parts:
            if part in {"", "."}:
                continue
            if part == "..":
                raise BoundaryError(failure)
            try:
                next_descriptor = os.open(part, flags, dir_fd=descriptor)
            except FileNotFoundError:
                if not create_missing:
                    raise
                os.mkdir(part, mode=0o700, dir_fd=descriptor)
                next_descriptor = os.open(part, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_descriptor
        return descriptor, path.name
    except BoundaryError:
        if descriptor is not None:
            with suppress(OSError):
                os.close(descriptor)
        raise
    except OSError as exc:
        if descriptor is not None:
            with suppress(OSError):
                os.close(descriptor)
        raise BoundaryError(failure) from exc


def _regular_fd(path: Path) -> int:
    parent_fd: int | None = None
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        parent_fd, name = _path_parent_fd(path, create_missing=False, failure="INPUT_UNAVAILABLE")
        fd = os.open(name, flags, dir_fd=parent_fd)
    except OSError as exc:
        raise BoundaryError("INPUT_UNAVAILABLE") from exc
    finally:
        if parent_fd is not None:
            os.close(parent_fd)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise BoundaryError("INPUT_NOT_REGULAR")
    except BaseException:
        os.close(fd)
        raise
    return fd


def read_regular_file(path: Path, *, max_bytes: int) -> bytes:
    """Read exactly one non-symlink regular file through a bounded descriptor."""
    fd = _regular_fd(path)
    try:
        chunks: list[bytes] = []
        remaining = max_bytes + 1
        while remaining:
            chunk = os.read(fd, min(65_536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        data = b"".join(chunks)
        if len(data) > max_bytes:
            raise BoundaryError("INPUT_TOO_LARGE")
        return data
    finally:
        os.close(fd)


def _read_regular_at(parent_fd: int, name: str, *, max_bytes: int) -> bytes:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(name, flags, dir_fd=parent_fd)
    except FileNotFoundError:
        raise
    except OSError as exc:
        raise BoundaryError("INPUT_UNAVAILABLE") from exc
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise BoundaryError("INPUT_NOT_REGULAR")
        chunks: list[bytes] = []
        remaining = max_bytes + 1
        while remaining:
            chunk = os.read(fd, min(65_536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        data = b"".join(chunks)
        if len(data) > max_bytes:
            raise BoundaryError("INPUT_TOO_LARGE")
        return data
    finally:
        os.close(fd)


def _walk_json(
    value: object,
    *,
    max_nodes: int,
    depth: int = 0,
    seen: list[int] | None = None,
) -> None:
    if depth > MAX_PARSE_DEPTH:
        raise BoundaryError("INPUT_DEPTH_EXCEEDED")
    count = seen or [0]
    count[0] += 1
    if count[0] > max_nodes:
        raise BoundaryError("INPUT_NODE_LIMIT_EXCEEDED")
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise BoundaryError("INPUT_JSON_INVALID")
            _walk_json(item, max_nodes=max_nodes, depth=depth + 1, seen=count)
    elif isinstance(value, list):
        for item in value:
            _walk_json(item, max_nodes=max_nodes, depth=depth + 1, seen=count)


def load_bounded_json(
    path: Path, *, max_bytes: int = JSON_MAX_BYTES, max_nodes: int = MAX_PARSE_NODES
) -> object:
    _raw, value = load_bounded_json_snapshot(path, max_bytes=max_bytes, max_nodes=max_nodes)
    return value


def load_bounded_json_snapshot(
    path: Path, *, max_bytes: int = JSON_MAX_BYTES, max_nodes: int = MAX_PARSE_NODES
) -> tuple[bytes, object]:
    """Return one no-follow JSON byte snapshot and its validated parsed value."""
    raw = read_regular_file(path, max_bytes=max_bytes)
    try:

        def reject_constant(_value: str) -> None:
            raise ValueError

        value = json.loads(raw.decode("utf-8"), parse_constant=reject_constant)
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError, RecursionError) as exc:
        raise BoundaryError("INPUT_JSON_INVALID") from exc
    _walk_json(value, max_nodes=max_nodes)
    return raw, value


def _yaml_shape(raw: bytes) -> None:
    try:
        aliases = 0
        for tokens, token in enumerate(yaml.scan(raw), start=1):
            if tokens > MAX_PARSE_TOKENS:
                raise BoundaryError("INPUT_TOKEN_LIMIT_EXCEEDED")
            if isinstance(token, yaml.tokens.AliasToken):
                aliases += 1
                if aliases > MAX_YAML_ALIASES:
                    raise BoundaryError("INPUT_ALIAS_LIMIT_EXCEEDED")
        document = yaml.compose(raw)
    except BoundaryError:
        raise
    except yaml.YAMLError as exc:
        raise BoundaryError("INPUT_YAML_INVALID") from exc

    nodes = [0]

    def visit(node: yaml.Node | None, depth: int) -> None:
        if node is None:
            return
        if depth > MAX_PARSE_DEPTH:
            raise BoundaryError("INPUT_DEPTH_EXCEEDED")
        nodes[0] += 1
        if nodes[0] > MAX_PARSE_NODES:
            raise BoundaryError("INPUT_NODE_LIMIT_EXCEEDED")
        if isinstance(node, yaml.SequenceNode):
            for item in node.value:
                visit(item, depth + 1)
        elif isinstance(node, yaml.MappingNode):
            for key, item in node.value:
                visit(key, depth + 1)
                visit(item, depth + 1)

    visit(document, 0)


def load_bounded_yaml(path: Path, *, max_bytes: int = WORLD_MAX_BYTES) -> object:
    raw = read_regular_file(path, max_bytes=max_bytes)
    _yaml_shape(raw)
    try:
        return yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise BoundaryError("INPUT_YAML_INVALID") from exc


def bounded_json_files(root: Path) -> list[Path]:
    """Walk an untrusted task directory without descending through symlinks."""
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    root_fd, _root_probe = _path_parent_fd(
        root / ".cascadeshift-root-probe",
        create_missing=False,
        failure="TASK_DIRECTORY_UNAVAILABLE",
    )
    files: list[Path] = []
    entries_seen = 0

    def visit(directory_fd: int, directory: Path, depth: int) -> None:
        nonlocal entries_seen
        if depth > MAX_PARSE_DEPTH:
            raise BoundaryError("TASK_DIRECTORY_DEPTH_EXCEEDED")
        try:
            entries: list[os.DirEntry[str]] = []
            duplicate_fd = os.dup(directory_fd)
            try:
                with os.scandir(duplicate_fd) as scanner:
                    for entry in scanner:
                        entries_seen += 1
                        if len(entries) >= MAX_TASK_ENTRIES_PER_DIRECTORY:
                            raise BoundaryError("TASK_DIRECTORY_ENTRY_LIMIT_EXCEEDED")
                        if entries_seen > MAX_TASK_ENTRIES_TOTAL:
                            raise BoundaryError("TASK_DIRECTORY_TOTAL_ENTRY_LIMIT_EXCEEDED")
                        entries.append(entry)
            finally:
                with suppress(OSError):
                    os.close(duplicate_fd)
        except OSError as exc:
            raise BoundaryError("TASK_DIRECTORY_UNAVAILABLE") from exc
        for entry in sorted(entries, key=lambda entry: entry.name):
            try:
                if entry.is_symlink():
                    raise BoundaryError("TASK_DIRECTORY_SYMLINK")
                if entry.is_dir(follow_symlinks=False):
                    child_fd = os.open(entry.name, flags, dir_fd=directory_fd)
                    try:
                        visit(child_fd, directory / entry.name, depth + 1)
                    finally:
                        os.close(child_fd)
                elif entry.is_file(follow_symlinks=False) and entry.name.endswith(".json"):
                    files.append(directory / entry.name)
                    if len(files) > MAX_TASK_FILES:
                        raise BoundaryError("TASK_FILE_LIMIT_EXCEEDED")
            except OSError as exc:
                raise BoundaryError("TASK_DIRECTORY_UNAVAILABLE") from exc

    try:
        visit(root_fd, root, 0)
        return files
    finally:
        os.close(root_fd)


def bounded_directory_entries(path: Path) -> list[os.DirEntry[str]]:
    """Read one caller-controlled directory within a deterministic entry budget."""
    try:
        status = path.lstat()
        if stat.S_ISLNK(status.st_mode) or not stat.S_ISDIR(status.st_mode):
            raise BoundaryError("TASK_DIRECTORY_INVALID")
        entries: list[os.DirEntry[str]] = []
        with os.scandir(path) as scanner:
            for entry in scanner:
                if len(entries) >= MAX_TASK_ENTRIES_PER_DIRECTORY:
                    raise BoundaryError("TASK_DIRECTORY_ENTRY_LIMIT_EXCEEDED")
                entries.append(entry)
    except OSError as exc:
        raise BoundaryError("TASK_DIRECTORY_UNAVAILABLE") from exc
    return sorted(entries, key=lambda entry: entry.name)


def _parent_directory_fd(path: Path) -> tuple[int, str]:
    """Create a no-follow output parent descriptor.

    Absolute output paths must already be canonical: macOS's ``/var`` alias is
    intentionally rejected, while its canonical ``/private/var`` path is supported.
    """
    return _path_parent_fd(path, create_missing=True, failure="OUTPUT_WRITE_FAILED")


def _safe_output_target(parent_fd: int, name: str) -> None:
    try:
        status = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return
    except OSError as exc:
        raise BoundaryError("OUTPUT_UNAVAILABLE") from exc
    if stat.S_ISLNK(status.st_mode):
        raise BoundaryError("OUTPUT_SYMLINK")


def _atomic_write_at(parent_fd: int, name: str, data: bytes) -> None:
    """Atomically replace a member of an already-open output directory."""
    temporary = f".{name}.{uuid.uuid4().hex}.tmp"
    fd: int | None = None
    try:
        _safe_output_target(parent_fd, name)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(temporary, flags, 0o600, dir_fd=parent_fd)
        view = memoryview(data)
        while view:
            written = os.write(fd, view)
            view = view[written:]
        os.fsync(fd)
        os.close(fd)
        fd = None
        _safe_output_target(parent_fd, name)
        os.replace(temporary, name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
        os.fsync(parent_fd)
    except OSError as exc:
        raise BoundaryError("OUTPUT_WRITE_FAILED") from exc
    finally:
        if fd is not None:
            os.close(fd)
        with suppress(OSError):
            os.unlink(temporary, dir_fd=parent_fd)


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """Atomically replace a regular output and fsync both file and directory."""
    parent_fd: int | None = None
    try:
        parent_fd, name = _parent_directory_fd(path)
        _atomic_write_at(parent_fd, name, data)
    finally:
        if parent_fd is not None:
            os.close(parent_fd)


def atomic_write_set(entries: Iterable[tuple[Path, bytes]]) -> None:
    """Use per-file atomic writes with best-effort rollback, not a crash-atomic set commit."""
    prepared = list(entries)
    originals: dict[Path, bytes | None] = {}
    rollback_fds: dict[Path, tuple[int, str]] = {}
    try:
        for path, _data in prepared:
            if path not in rollback_fds:
                rollback_fds[path] = _parent_directory_fd(path)
            parent_fd, name = rollback_fds[path]
            try:
                originals[path] = _read_regular_at(parent_fd, name, max_bytes=16 * 1_048_576)
            except FileNotFoundError:
                originals[path] = None
        try:
            completed: list[Path] = []
            for path, data in prepared:
                atomic_write_bytes(path, data)
                completed.append(path)
        except BoundaryError:
            for path in reversed(completed):
                previous = originals[path]
                try:
                    if previous is None:
                        parent_fd, name = rollback_fds[path]
                        os.unlink(name, dir_fd=parent_fd)
                    else:
                        parent_fd, name = rollback_fds[path]
                        _atomic_write_at(parent_fd, name, previous)
                except (BoundaryError, OSError):
                    pass
            raise
    finally:
        for parent_fd, _name in rollback_fds.values():
            os.close(parent_fd)
