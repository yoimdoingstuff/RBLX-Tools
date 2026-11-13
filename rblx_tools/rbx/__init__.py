"""Roblox file format support (no bpy dependency)."""

from .binary import RobloxFormatError, read_binary
from .datatypes import CFrame, Document, Instance
from .rbxmx import read_xml

__all__ = ["load_file", "load_bytes", "Document", "Instance", "CFrame", "RobloxFormatError"]

# Files saved by newer Studio builds store asset links in the Content type,
# under new property names (Shirt.ShirtTemplateContent instead of
# Shirt.ShirtTemplate, Decal.TextureContent instead of Decal.Texture...).
# These map them back to the classic names the rest of the add-on reads.
_SKYBOX = {"SkyboxBackContent": "SkyboxBk", "SkyboxDownContent": "SkyboxDn",
           "SkyboxFrontContent": "SkyboxFt", "SkyboxLeftContent": "SkyboxLf",
           "SkyboxRightContent": "SkyboxRt", "SkyboxUpContent": "SkyboxUp"}
_MESH_CLASSES = {"MeshPart": "TextureID", "SpecialMesh": "TextureId", "FileMesh": "TextureId",
                 "CharacterMesh": None}


def classic_name(class_name, prop):
    """The pre-Content name of a '...Content' property, or None."""
    if not prop.endswith("Content") or len(prop) <= 7:
        return None
    if prop in _SKYBOX:
        return _SKYBOX[prop]
    base = prop[:-7]
    if base == "Texture" and class_name in _MESH_CLASSES:
        return _MESH_CLASSES[class_name]
    if base.endswith("Mesh") or base.endswith("Texture") and base != "Texture":
        return base + "Id"       # MeshContent -> MeshId, SunTextureContent -> SunTextureId
    return base                  # ShirtTemplateContent -> ShirtTemplate, ImageContent -> Image


def add_classic_names(doc):
    """Give every '...Content' asset property its classic name too, unless the
    file already has a value under that name."""
    for inst in doc.all_instances():
        props = inst.props
        for key in [k for k in props if k.endswith("Content")]:
            value = props[key]
            if not isinstance(value, str) or not value.strip():
                continue
            old = classic_name(inst.class_name, key)
            if old and not (isinstance(props.get(old), str) and props[old].strip()):
                props[old] = value
    return doc


def load_bytes(data, warnings=None):
    """Load .rbxm/.rbxl (binary) or .rbxmx/.rbxlx (XML) data, detected by content."""
    if data.startswith(b"<roblox!"):
        return add_classic_names(read_binary(data, warnings))
    head = data[:200].lstrip()
    if head.startswith(b"<roblox") or head.startswith(b"<?xml") or head.startswith(b"\xef\xbb\xbf"):
        return add_classic_names(read_xml(data, warnings))
    raise RobloxFormatError("Not a Roblox model or place file")


def load_file(path, warnings=None):
    with open(path, "rb") as f:
        return load_bytes(f.read(), warnings)
