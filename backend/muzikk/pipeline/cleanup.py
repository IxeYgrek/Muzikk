"""Removal of junk files and leftover directories."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from ..matching.normalize import IMAGE_EXTENSIONS, JUNK_EXTENSIONS, extension_of, is_audio_file

logger = logging.getLogger(__name__)

KEEP_IMAGE_NAMES = {"cover", "folder", "front", "album", "artwork"}


def is_junk(path: Path) -> bool:
    extension = extension_of(path.name)
    if extension in JUNK_EXTENSIONS:
        return True
    if extension in IMAGE_EXTENSIONS:
        return path.stem.lower() not in KEEP_IMAGE_NAMES
    return False


def collect_audio_files(root: Path) -> list[Path]:
    """Every audio file under ``root``, sorted for stable ordering."""
    if root.is_file():
        return [root] if is_audio_file(root.name) else []
    files = [item for item in root.rglob("*") if item.is_file() and is_audio_file(item.name)]
    return sorted(files, key=lambda item: (str(item.parent).lower(), item.name.lower()))


def clean_directory(directory: Path) -> list[str]:
    """Delete parasite files in place and report what was removed."""
    removed: list[str] = []
    if not directory.exists() or not directory.is_dir():
        return removed
    for item in sorted(directory.rglob("*"), key=lambda path: len(path.parts), reverse=True):
        try:
            if item.is_file() and is_junk(item):
                item.unlink()
                removed.append(item.name)
        except OSError as exc:
            logger.debug("Unable to remove %s: %s", item, exc)
    remove_empty_dirs(directory)
    return removed


def remove_empty_dirs(root: Path) -> int:
    """Remove empty subdirectories, deepest first. ``root`` itself is kept."""
    if not root.exists() or not root.is_dir():
        return 0
    removed = 0
    for item in sorted(root.rglob("*"), key=lambda path: len(path.parts), reverse=True):
        if not item.is_dir():
            continue
        try:
            next(item.iterdir())
        except StopIteration:
            try:
                item.rmdir()
                removed += 1
            except OSError:
                continue
        except OSError:
            continue
    return removed


def remove_tree(path: Path, *, guard: Path | None = None) -> bool:
    """Delete a directory tree, refusing anything outside ``guard``."""
    if not path.exists():
        return False
    if guard is not None:
        try:
            path.resolve().relative_to(guard.resolve())
        except ValueError:
            logger.warning("Refusing to delete %s: outside of %s", path, guard)
            return False
    try:
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
        return True
    except OSError as exc:
        logger.warning("Unable to delete %s: %s", path, exc)
        return False


def prune_empty_parents(start: Path, stop_at: Path) -> int:
    """Walk up from ``start`` removing empty directories until ``stop_at``."""
    removed = 0
    try:
        current = start.resolve()
        boundary = stop_at.resolve()
    except OSError:
        return 0
    while current != boundary and boundary in current.parents:
        if not current.is_dir():
            break
        try:
            next(current.iterdir())
            break
        except StopIteration:
            parent = current.parent
            try:
                current.rmdir()
                removed += 1
            except OSError:
                break
            current = parent
        except OSError:
            break
    return removed
