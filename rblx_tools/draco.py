"""Draco decoding for Roblox meshes (COREMESH v2), using the Draco bridge
library that ships with Blender's bundled glTF importer."""

import os
import sys
from array import array
from ctypes import c_bool, c_char_p, c_size_t, c_uint32, c_void_p, cdll

from .rbx import mesh as rbxmesh

_GL_FLOAT = 5126
_GL_UNSIGNED_INT = 5125
# Attribute unique ids written by Roblox's encoder
_ATTR_POSITION, _ATTR_NORMAL, _ATTR_UV = 0, 1, 2

_dll = None
_load_error = None


def _find_library():
    try:
        from io_scene_gltf2.io.com.library import dll_path
        p = dll_path("bf_intern_draco_bridge", "Draco")
        if p is not None and p.exists():
            return str(p.resolve())
    except Exception:
        pass
    names = {"win32": "bf_intern_draco_bridge.dll", "darwin": "libbf_intern_draco_bridge.dylib"}
    name = names.get(sys.platform, "libbf_intern_draco_bridge.so")
    for base in sys.path:
        p = os.path.join(base, "io_scene_gltf2", name)
        if os.path.isfile(p):
            return p
    return None


def _load():
    global _dll, _load_error
    if _dll is not None or _load_error is not None:
        return _dll
    path = _find_library()
    if path is None:
        _load_error = "Blender's Draco library (from the glTF importer) was not found"
        return None
    try:
        dll = cdll.LoadLibrary(path)
    except OSError as ex:
        _load_error = "Could not load Draco library: %s" % ex
        return None
    dll.decoderCreate.restype = c_void_p
    dll.decoderCreate.argtypes = []
    dll.decoderRelease.restype = None
    dll.decoderRelease.argtypes = [c_void_p]
    dll.decoderDecode.restype = c_bool
    dll.decoderDecode.argtypes = [c_void_p, c_void_p, c_size_t]
    dll.decoderReadAttribute.restype = c_bool
    dll.decoderReadAttribute.argtypes = [c_void_p, c_uint32, c_size_t, c_char_p]
    dll.decoderGetVertexCount.restype = c_uint32
    dll.decoderGetVertexCount.argtypes = [c_void_p]
    dll.decoderGetIndexCount.restype = c_uint32
    dll.decoderGetIndexCount.argtypes = [c_void_p]
    dll.decoderGetAttributeByteLength.restype = c_size_t
    dll.decoderGetAttributeByteLength.argtypes = [c_void_p, c_uint32]
    dll.decoderCopyAttribute.restype = None
    dll.decoderCopyAttribute.argtypes = [c_void_p, c_uint32, c_void_p]
    dll.decoderReadIndices.restype = c_bool
    dll.decoderReadIndices.argtypes = [c_void_p, c_size_t]
    dll.decoderGetIndicesByteLength.restype = c_size_t
    dll.decoderGetIndicesByteLength.argtypes = [c_void_p]
    dll.decoderCopyIndices.restype = None
    dll.decoderCopyIndices.argtypes = [c_void_p, c_void_p]
    _dll = dll
    return dll


def available():
    return _load() is not None


def load_error():
    _load()
    return _load_error


def _floats(dll, dec, attr_id, kind, width, count):
    if not dll.decoderReadAttribute(dec, attr_id, _GL_FLOAT, kind):
        return None
    n = dll.decoderGetAttributeByteLength(dec, attr_id)
    buf = bytes(n)
    dll.decoderCopyAttribute(dec, attr_id, buf)
    vals = array("f")
    vals.frombytes(buf)
    if len(vals) < width * count:
        return None
    return [tuple(vals[i * width:(i + 1) * width]) for i in range(count)]


def decode(data):
    dll = _load()
    if dll is None:
        raise rbxmesh.MeshFormatError(_load_error)
    dec = dll.decoderCreate()
    try:
        if not dll.decoderDecode(dec, data, len(data)):
            raise rbxmesh.MeshFormatError("Draco data could not be decoded")
        count = dll.decoderGetVertexCount(dec)
        positions = _floats(dll, dec, _ATTR_POSITION, b"VEC3", 3, count)
        if positions is None:
            raise rbxmesh.MeshFormatError("Draco mesh has no positions")
        normals = _floats(dll, dec, _ATTR_NORMAL, b"VEC3", 3, count) or []
        uvs = _floats(dll, dec, _ATTR_UV, b"VEC2", 2, count) or []
        if not dll.decoderReadIndices(dec, _GL_UNSIGNED_INT):
            raise rbxmesh.MeshFormatError("Draco mesh has no triangles")
        n = dll.decoderGetIndicesByteLength(dec)
        buf = bytes(n)
        dll.decoderCopyIndices(dec, buf)
        idx = array("I")
        idx.frombytes(buf)
        faces = [tuple(idx[i:i + 3]) for i in range(0, len(idx) - 2, 3)]
        return positions, normals, uvs, faces
    finally:
        dll.decoderRelease(dec)


def register():
    rbxmesh.set_draco_decoder(decode)


def unregister():
    rbxmesh.set_draco_decoder(None)
