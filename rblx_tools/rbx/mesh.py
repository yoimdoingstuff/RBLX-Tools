"""Reader for Roblox .mesh files (the asset behind MeshPart.MeshId and
SpecialMesh.MeshId).

Supported: versions 1.00/1.01 (text), 2.00, 3.00/3.01, 4.00/4.01, 5.00, and
6.00/7.00 (plain or Draco-compressed; Draco needs a decoder, see
set_draco_decoder).

Returns positions/normals/uvs in Roblox studs (Y-up) and triangle indices.
UVs are returned in Blender's convention: v2+ binary meshes store V top-down
and are flipped (v = 1 - v); v1 text meshes already match."""

import re
import struct


class MeshFormatError(Exception):
    pass


# Draco-compressed meshes (COREMESH v2, used by almost all current Roblox
# meshes) need a Draco decoder. Inside Blender, rblx_tools.draco installs one
# that uses the library Blender ships for its glTF importer.
# Signature: decoder(draco_bytes) -> (positions, normals, uvs, triangles)
_draco_decoder = None


def set_draco_decoder(func):
    global _draco_decoder
    _draco_decoder = func


class MeshData:
    __slots__ = ("positions", "normals", "uvs", "faces", "version")

    def __init__(self, positions, normals, uvs, faces, version):
        self.positions = positions
        self.normals = normals
        self.uvs = uvs
        self.faces = faces
        self.version = version

    def bounds(self):
        if not self.positions:
            return (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)
        xs, ys, zs = zip(*self.positions)
        return (min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs))


def _read_vertices(data, off, count, stride):
    pos, nrm, uvs = [], [], []
    for i in range(count):
        base = off + i * stride
        px, py, pz, nx, ny, nz, u, v = struct.unpack_from("<8f", data, base)
        pos.append((px, py, pz))
        nrm.append((nx, ny, nz))
        uvs.append((u, 1.0 - v))
    return pos, nrm, uvs, off + count * stride


def _read_faces(data, off, count):
    vals = struct.unpack_from("<%dI" % (count * 3), data, off)
    faces = [vals[i:i + 3] for i in range(0, len(vals), 3)]
    return faces, off + count * 12


def _first_lod(faces, lods):
    if len(lods) >= 2 and lods[1] > lods[0]:
        return faces[lods[0]:lods[1]]
    return faces


def _read_v1(text, version):
    lines = text.split("\n")
    if len(lines) < 3:
        raise MeshFormatError("truncated v1 mesh")
    num_faces = int(lines[1].strip())
    nums = [float(x) for x in re.findall(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", lines[2])]
    vecs = [nums[i:i + 3] for i in range(0, len(nums) - 2, 3)]
    scale = 0.5 if version == "1.00" else 1.0
    pos, nrm, uvs, faces = [], [], [], []
    for f in range(num_faces):
        tri = []
        for k in range(3):
            base = (f * 3 + k) * 3
            if base + 2 >= len(vecs):
                raise MeshFormatError("truncated v1 mesh data")
            p, n, t = vecs[base], vecs[base + 1], vecs[base + 2]
            tri.append(len(pos))
            pos.append((p[0] * scale, p[1] * scale, p[2] * scale))
            nrm.append(tuple(n))
            # v1 text meshes already store V bottom-up (unlike v2+); checked
            # against Roblox's own renders of old hats.
            uvs.append((t[0], t[1]))
        faces.append(tuple(tri))
    return MeshData(pos, nrm, uvs, faces, version)


def _read_v2_v5(data, off, version):
    major = int(version.split(".")[0])
    header_size = struct.unpack_from("<H", data, off)[0]
    hdr_start = off
    if major == 2:
        _, vsize, fsize, nverts, nfaces = struct.unpack_from("<HBBII", data, off)
        lods = []
        nbones = 0
    elif major == 3:
        _, vsize, fsize, _lodsize, nlods, nverts, nfaces = struct.unpack_from("<HBBHHII", data, off)
        nbones = 0
    else:  # 4.x / 5.x
        (_, _lodtype, nverts, nfaces, nlods, nbones, _bnsize, _nsubsets,
         _hq, _unused) = struct.unpack_from("<HHIIHHIHBB", data, off)
        vsize = 40
    off = hdr_start + header_size

    pos, nrm, uvs, off = _read_vertices(data, off, nverts, vsize)
    if major >= 4 and nbones > 0:
        off += nverts * 8  # skinning envelopes
    faces, off = _read_faces(data, off, nfaces)
    if major >= 3:
        lods = list(struct.unpack_from("<%dI" % nlods, data, off)) if nlods else []
    return MeshData(pos, nrm, uvs, _first_lod(faces, lods), version)


def _read_chunked(data, off, version):
    pos = nrm = uvs = None
    faces = []
    lods = []
    while off + 16 <= len(data):
        ctype = data[off:off + 8]
        cver, csize = struct.unpack_from("<II", data, off + 8)
        body = off + 16
        if ctype == b"COREMESH" and cver == 2:
            if _draco_decoder is None:
                raise MeshFormatError("mesh %s is Draco-compressed and no Draco decoder is available"
                                      % version)
            dlen = struct.unpack_from("<I", data, body)[0]
            pos, nrm, uvs, faces = _draco_decoder(bytes(data[body + 4:body + 4 + dlen]))
            uvs = [(u, 1.0 - v) for u, v in uvs] if uvs else []
        elif ctype == b"COREMESH":
            if cver != 1:
                raise MeshFormatError("mesh %s: unknown COREMESH version %d" % (version, cver))
            nverts = struct.unpack_from("<I", data, body)[0]
            pos, nrm, uvs, p = _read_vertices(data, body + 4, nverts, 40)
            nfaces = struct.unpack_from("<I", data, p)[0]
            faces, _ = _read_faces(data, p + 4, nfaces)
        elif ctype == b"LODS\x00\x00\x00\x00" and cver == 1:
            _lodtype, _hq, n = struct.unpack_from("<HBI", data, body)
            lods = list(struct.unpack_from("<%dI" % n, data, body + 7))
        off = body + csize
    if pos is None:
        raise MeshFormatError("mesh %s has no COREMESH chunk" % version)
    return MeshData(pos, nrm, uvs, _first_lod(faces, lods), version)


def read_mesh(data):
    if not data.startswith(b"version "):
        raise MeshFormatError("not a Roblox .mesh file")
    nl = data.find(b"\n")
    if nl < 0:
        raise MeshFormatError("truncated mesh header")
    version = data[8:nl].decode("ascii", "replace").strip()
    major = version.split(".")[0]
    try:
        if major == "1":
            return _read_v1(data.decode("ascii", "replace"), version)
        if major in ("2", "3", "4", "5"):
            return _read_v2_v5(data, nl + 1, version)
        if major in ("6", "7"):
            return _read_chunked(data, nl + 1, version)
    except struct.error as ex:
        raise MeshFormatError("corrupt mesh %s: %s" % (version, ex))
    raise MeshFormatError("unsupported mesh version %s" % version)


def is_mesh_data(head):
    return head.startswith(b"version ")
