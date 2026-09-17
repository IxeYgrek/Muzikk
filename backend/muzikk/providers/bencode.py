"""Minimal bencode reader used to inspect .torrent files before downloading.

Reading the file list of a torrent is what prevents most false positives: the
release title alone lies about the format and the track count.
"""

from __future__ import annotations

import hashlib
from typing import Any


class BencodeError(ValueError):
    pass


def _decode(data: bytes, index: int) -> tuple[Any, int]:
    if index >= len(data):
        raise BencodeError("unexpected end of data")

    prefix = data[index : index + 1]

    if prefix == b"i":
        end = data.index(b"e", index)
        return int(data[index + 1 : end]), end + 1

    if prefix == b"l":
        index += 1
        items: list[Any] = []
        while data[index : index + 1] != b"e":
            value, index = _decode(data, index)
            items.append(value)
        return items, index + 1

    if prefix == b"d":
        index += 1
        mapping: dict[bytes, Any] = {}
        while data[index : index + 1] != b"e":
            key, index = _decode(data, index)
            if not isinstance(key, bytes):
                raise BencodeError("dictionary keys must be byte strings")
            value, index = _decode(data, index)
            mapping[key] = value
        return mapping, index + 1

    if prefix.isdigit():
        separator = data.index(b":", index)
        length = int(data[index:separator])
        start = separator + 1
        return data[start : start + length], start + length

    raise BencodeError(f"invalid bencode prefix {prefix!r} at offset {index}")


def decode(data: bytes) -> Any:
    value, _ = _decode(data, 0)
    return value


def encode(value: Any) -> bytes:
    if isinstance(value, bool):
        raise BencodeError("booleans cannot be bencoded")
    if isinstance(value, int):
        return b"i" + str(value).encode() + b"e"
    if isinstance(value, bytes):
        return str(len(value)).encode() + b":" + value
    if isinstance(value, str):
        raw = value.encode()
        return str(len(raw)).encode() + b":" + raw
    if isinstance(value, (list, tuple)):
        return b"l" + b"".join(encode(item) for item in value) + b"e"
    if isinstance(value, dict):
        parts = []
        for key in sorted(value, key=lambda item: item if isinstance(item, bytes) else str(item).encode()):
            raw_key = key if isinstance(key, bytes) else str(key).encode()
            parts.append(encode(raw_key))
            parts.append(encode(value[key]))
        return b"d" + b"".join(parts) + b"e"
    raise BencodeError(f"cannot bencode {type(value)!r}")


def _text(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value or "")


def info_hash(torrent: bytes) -> str | None:
    """SHA-1 of the info dictionary, as used by qBittorrent."""
    try:
        payload = decode(torrent)
    except (BencodeError, ValueError, IndexError):
        return None
    if not isinstance(payload, dict) or b"info" not in payload:
        return None
    try:
        return hashlib.sha1(encode(payload[b"info"])).hexdigest()
    except BencodeError:
        return None


def list_files(torrent: bytes) -> tuple[str, list[tuple[str, int]]]:
    """Return the torrent name and its ``(path, size)`` entries."""
    payload = decode(torrent)
    if not isinstance(payload, dict):
        raise BencodeError("torrent root is not a dictionary")
    info = payload.get(b"info")
    if not isinstance(info, dict):
        raise BencodeError("torrent has no info dictionary")

    name = _text(info.get(b"name"))
    files: list[tuple[str, int]] = []

    if b"files" in info and isinstance(info[b"files"], list):
        for entry in info[b"files"]:
            if not isinstance(entry, dict):
                continue
            components = [_text(part) for part in entry.get(b"path") or []]
            if not components:
                continue
            files.append(("/".join([name, *components]), int(entry.get(b"length") or 0)))
    else:
        files.append((name, int(info.get(b"length") or 0)))

    return name, files


def magnet_info_hash(magnet: str) -> str | None:
    """Extract the info hash from a magnet URI."""
    if not magnet or "xt=urn:btih:" not in magnet:
        return None
    fragment = magnet.split("xt=urn:btih:", 1)[1]
    value = fragment.split("&", 1)[0].strip().lower()
    if len(value) == 40 and all(char in "0123456789abcdef" for char in value):
        return value
    if len(value) == 32:
        # Base32 encoded hash, as used by some older trackers.
        import base64

        try:
            return base64.b32decode(value.upper()).hex()
        except Exception:  # noqa: BLE001
            return None
    return None
