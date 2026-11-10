"""Roblox file format support (no bpy dependency)."""

from .binary import RobloxFormatError, read_binary
from .datatypes import CFrame, Document, Instance
from .rbxmx import read_xml

__all__ = ["load_file", "load_bytes", "Document", "Instance", "CFrame", "RobloxFormatError"]


def load_bytes(data, warnings=None):
    """Load .rbxm/.rbxl (binary) or .rbxmx/.rbxlx (XML) data, detected by content."""
    if data.startswith(b"<roblox!"):
        return read_binary(data, warnings)
    head = data[:200].lstrip()
    if head.startswith(b"<roblox") or head.startswith(b"<?xml") or head.startswith(b"\xef\xbb\xbf"):
        return read_xml(data, warnings)
    raise RobloxFormatError("Not a Roblox model or place file")


def load_file(path, warnings=None):
    with open(path, "rb") as f:
        return load_bytes(f.read(), warnings)
