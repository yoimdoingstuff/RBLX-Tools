"""Reader for Roblox's binary model/place format (.rbxm / .rbxl).

Format reference: the community spec maintained in the rbx-dom project
(docs/binary.md). Chunks: META, SSTR, INST, PROP, PRNT, END (+ ignored
extras such as SIGN)."""

import struct

from . import lz4
from .datatypes import CFrame, Document, Instance, Ref, resolve_refs

MAGIC = b"<roblox!"
ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"

# NormalId order used by the "special" CFrame rotation ids.
_NORMALS = (
    (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0),
    (-1.0, 0.0, 0.0), (0.0, -1.0, 0.0), (0.0, 0.0, -1.0),
)


class RobloxFormatError(Exception):
    pass


class _Reader:
    __slots__ = ("data", "pos")

    def __init__(self, data, pos=0):
        self.data = data
        self.pos = pos

    def read(self, n):
        end = self.pos + n
        if end > len(self.data):
            raise RobloxFormatError("unexpected end of data")
        b = self.data[self.pos:end]
        self.pos = end
        return b

    def u8(self):
        return self.read(1)[0]

    def u16(self):
        return struct.unpack("<H", self.read(2))[0]

    def u32(self):
        return struct.unpack("<I", self.read(4))[0]

    def i32(self):
        return struct.unpack("<i", self.read(4))[0]

    def string(self):
        return self.read(self.u32())

    def remaining(self):
        return len(self.data) - self.pos


# ---------------------------------------------------------------------------
# Interleaved array helpers

def _interleaved(r, count, width):
    """Return `width` byte-columns (most significant byte first)."""
    raw = r.read(count * width)
    return [raw[k * count:(k + 1) * count] for k in range(width)]


def _u32s(r, count):
    if count == 0:
        return []
    c0, c1, c2, c3 = _interleaved(r, count, 4)
    return [(a << 24) | (b << 16) | (c << 8) | d for a, b, c, d in zip(c0, c1, c2, c3)]


def _i32s(r, count):
    return [(v >> 1) ^ -(v & 1) for v in _u32s(r, count)]


def _f32s(r, count):
    if count == 0:
        return []
    bits = [((v >> 1) | ((v & 1) << 31)) & 0xFFFFFFFF for v in _u32s(r, count)]
    return list(struct.unpack(">%df" % count, struct.pack(">%dI" % count, *bits)))


def _u64s(r, count):
    if count == 0:
        return []
    cols = _interleaved(r, count, 8)
    out = []
    for i in range(count):
        v = 0
        for c in cols:
            v = (v << 8) | c[i]
        out.append(v)
    return out


def _i64s(r, count):
    return [(v >> 1) ^ -(v & 1) for v in _u64s(r, count)]


def _referents(r, count):
    out = []
    acc = 0
    for v in _i32s(r, count):
        acc += v
        out.append(acc)
    return out


def _text(b):
    try:
        return b.decode("utf-8")
    except UnicodeDecodeError:
        return b  # genuinely binary (e.g. AttributesSerialize, PhysicsData)


def _special_rotation(rot_id):
    v = rot_id - 1
    right = _NORMALS[v // 6]
    up = _NORMALS[v % 6]
    back = (
        right[1] * up[2] - right[2] * up[1],
        right[2] * up[0] - right[0] * up[2],
        right[0] * up[1] - right[1] * up[0],
    )
    # Columns are right, up, back.
    return (right[0], up[0], back[0],
            right[1], up[1], back[1],
            right[2], up[2], back[2])


def _cframes(r, count):
    rots = []
    for _ in range(count):
        rid = r.u8()
        if rid == 0:
            rots.append(struct.unpack("<9f", r.read(36)))
        else:
            rots.append(_special_rotation(rid))
    xs = _f32s(r, count)
    ys = _f32s(r, count)
    zs = _f32s(r, count)
    return [CFrame((x, y, z), rot) for x, y, z, rot in zip(xs, ys, zs, rots)]


# ---------------------------------------------------------------------------
# Property value decoders, by type id

def _read_values(r, type_id, n, sstr):
    if type_id in (0x01, 0x1D):  # String, Bytecode
        return [_text(r.string()) for _ in range(n)]
    if type_id == 0x02:  # Bool
        return [b != 0 for b in r.read(n)]
    if type_id == 0x03:  # Int32
        return _i32s(r, n)
    if type_id == 0x04:  # Float32
        return _f32s(r, n)
    if type_id == 0x05:  # Float64
        return list(struct.unpack("<%dd" % n, r.read(8 * n)))
    if type_id == 0x06:  # UDim
        scales = _f32s(r, n)
        offsets = _i32s(r, n)
        return list(zip(scales, offsets))
    if type_id == 0x07:  # UDim2
        sx, sy, ox, oy = _f32s(r, n), _f32s(r, n), _i32s(r, n), _i32s(r, n)
        return [((a, c), (b, d)) for a, b, c, d in zip(sx, sy, ox, oy)]
    if type_id == 0x08:  # Ray
        return [struct.unpack("<6f", r.read(24)) for _ in range(n)]
    if type_id in (0x09, 0x0A):  # Faces, Axes
        return list(r.read(n))
    if type_id == 0x0B:  # BrickColor
        return _u32s(r, n)
    if type_id == 0x0C:  # Color3
        return list(zip(_f32s(r, n), _f32s(r, n), _f32s(r, n)))
    if type_id == 0x0D:  # Vector2
        return list(zip(_f32s(r, n), _f32s(r, n)))
    if type_id == 0x0E:  # Vector3
        return list(zip(_f32s(r, n), _f32s(r, n), _f32s(r, n)))
    if type_id == 0x0F:  # Vector2int16
        return [struct.unpack("<hh", r.read(4)) for _ in range(n)]
    if type_id == 0x10:  # CFrame
        return _cframes(r, n)
    if type_id == 0x12:  # Enum
        return _u32s(r, n)
    if type_id == 0x13:  # Ref
        return [Ref(v) for v in _referents(r, n)]
    if type_id == 0x14:  # Vector3int16
        return [struct.unpack("<hhh", r.read(6)) for _ in range(n)]
    if type_id == 0x15:  # NumberSequence
        out = []
        for _ in range(n):
            k = r.u32()
            vals = struct.unpack("<%df" % (3 * k), r.read(12 * k))
            out.append([vals[i:i + 3] for i in range(0, len(vals), 3)])
        return out
    if type_id == 0x16:  # ColorSequence
        out = []
        for _ in range(n):
            k = r.u32()
            vals = struct.unpack("<%df" % (5 * k), r.read(20 * k))
            out.append([vals[i:i + 5] for i in range(0, len(vals), 5)])
        return out
    if type_id == 0x17:  # NumberRange
        return [struct.unpack("<2f", r.read(8)) for _ in range(n)]
    if type_id == 0x18:  # Rect
        a, b, c, d = _f32s(r, n), _f32s(r, n), _f32s(r, n), _f32s(r, n)
        return list(zip(a, b, c, d))
    if type_id == 0x19:  # PhysicalProperties
        out = []
        for _ in range(n):
            # bit 0: custom values follow; bit 1: newer layout that also
            # carries AcousticAbsorption (6 floats instead of 5).
            flag = r.u8()
            if not flag & 1:
                out.append(None)
            elif flag & 2:
                out.append(struct.unpack("<6f", r.read(24)))
            else:
                out.append(struct.unpack("<5f", r.read(20)))
        return out
    if type_id == 0x1A:  # Color3uint8
        rr, gg, bb = r.read(n), r.read(n), r.read(n)
        return [(a / 255.0, b / 255.0, c / 255.0) for a, b, c in zip(rr, gg, bb)]
    if type_id == 0x1B:  # Int64
        return _i64s(r, n)
    if type_id == 0x1C:  # SharedString
        return [sstr[i] if i < len(sstr) else b"" for i in _u32s(r, n)]
    if type_id == 0x1E:  # OptionalCFrame
        r.u8()  # inner type id (CFrame)
        cfs = _cframes(r, n)
        r.u8()  # inner type id (Bool)
        flags = [b != 0 for b in r.read(n)]
        return [cf if f else None for cf, f in zip(cfs, flags)]
    if type_id == 0x1F:  # UniqueId
        cols = _interleaved(r, n, 16)
        return [bytes(c[i] for c in cols) for i in range(n)]
    if type_id == 0x20:  # Font
        out = []
        for _ in range(n):
            family = _text(r.string())
            weight = r.u16()
            style = r.u8()
            cached = _text(r.string())
            out.append({"Family": family, "Weight": weight, "Style": style, "CachedFaceId": cached})
        return out
    if type_id == 0x21:  # SecurityCapabilities
        return _u64s(r, n)
    if type_id == 0x22:  # Content (2024+): best effort, URIs only
        kinds = _i32s(r, n)
        uris = [_text(r.string()) for _ in range(r.u32())]
        out = []
        ui = 0
        for k in kinds:
            if k == 1 and ui < len(uris):
                out.append(uris[ui])
                ui += 1
            else:
                out.append("")
        return out
    raise RobloxFormatError("unsupported property type 0x%02X" % type_id)


# ---------------------------------------------------------------------------
# Chunk decompression

def _zstd_decompress(payload, size):
    try:
        from compression import zstd  # Python 3.14+
        return zstd.decompress(payload)
    except ImportError:
        pass
    try:
        import zstandard
        return zstandard.ZstdDecompressor().decompress(payload, max_output_size=size)
    except ImportError:
        pass
    try:
        import pyzstd
        return pyzstd.decompress(payload)
    except ImportError:
        pass
    raise RobloxFormatError(
        "This file uses Zstandard compression, which this Python build can't "
        "decompress. Re-save it from Roblox Studio as .rbxmx/.rbxlx (XML) instead.")


def _chunk_data(payload, compressed, uncompressed):
    if compressed == 0:
        return payload
    if payload[:4] == ZSTD_MAGIC:
        return _zstd_decompress(payload, uncompressed)
    return lz4.decompress(payload, uncompressed)


# ---------------------------------------------------------------------------

def read_binary(data, warnings=None):
    if warnings is None:
        warnings = []
    if not data.startswith(MAGIC):
        raise RobloxFormatError("not a binary Roblox file")

    r = _Reader(data, len(MAGIC))
    r.read(6)  # signature 89 FF 0D 0A 1A 0A
    version = r.u16()
    if version != 0:
        warnings.append("Unknown binary format version %d; trying anyway" % version)
    r.i32()  # class count
    r.i32()  # instance count
    r.read(8)

    classes = {}        # class id -> (class name, [referents])
    instances = {}      # referent -> Instance
    sstr = []
    order = []          # creation order, used if PRNT is missing

    while r.remaining() >= 16:
        name = r.read(4)
        compressed = r.u32()
        uncompressed = r.u32()
        r.read(4)
        payload = r.read(compressed if compressed else uncompressed)

        if name == b"END\x00":
            break
        try:
            chunk = _chunk_data(payload, compressed, uncompressed)
        except RobloxFormatError:
            raise
        except Exception as ex:  # corrupt chunk
            warnings.append("Skipped unreadable %s chunk: %s" % (name.decode("latin-1"), ex))
            continue
        cr = _Reader(chunk)

        if name == b"INST":
            class_id = cr.u32()
            class_name = cr.string().decode("utf-8", "replace")
            cr.u8()  # object format (service markers follow if 1)
            count = cr.u32()
            refs = _referents(cr, count)
            classes[class_id] = (class_name, refs)
            for ref in refs:
                inst = Instance(class_name, ref)
                instances[ref] = inst
                order.append(inst)

        elif name == b"PROP":
            class_id = cr.u32()
            prop_name = cr.string().decode("utf-8", "replace")
            type_id = cr.u8()
            cls = classes.get(class_id)
            if cls is None:
                continue
            class_name, refs = cls
            try:
                values = _read_values(cr, type_id, len(refs), sstr)
            except Exception as ex:
                warnings.append("Skipped %s.%s: %s" % (class_name, prop_name, ex))
                continue
            for ref, v in zip(refs, values):
                instances[ref].props[prop_name] = v

        elif name == b"SSTR":
            cr.u32()  # version
            for _ in range(cr.u32()):
                cr.read(16)  # md5
                sstr.append(cr.string())

        elif name == b"PRNT":
            cr.u8()
            count = cr.u32()
            children = _referents(cr, count)
            parents = _referents(cr, count)
            for c, p in zip(children, parents):
                child = instances.get(c)
                parent = instances.get(p)
                if child is not None and parent is not None:
                    child.parent = parent
                    parent.children.append(child)

        # META and unknown chunks (SIGN, ...) are ignored.

    roots = [inst for inst in order if inst.parent is None]
    resolve_refs(instances, order)
    return Document(roots, "binary")
