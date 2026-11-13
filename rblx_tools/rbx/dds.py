"""Minimal DDS reader for Roblox's texture packages: DXT1/BC1 and DXT5/BC3,
plain or DX10 texture arrays. Decodes the top mip level of each slice to
RGBA (numpy). No bpy."""

import struct

import numpy as np

DXGI_BC1 = (70, 71, 72)
DXGI_BC3 = (76, 77, 78)


class DDSError(Exception):
    pass


def header(data):
    if data[:4] != b"DDS ":
        raise DDSError("not a DDS file")
    height, width = struct.unpack("<2I", data[12:20])
    mips = max(1, struct.unpack("<I", data[28:32])[0])
    fourcc = data[84:88]
    offset = 128
    fmt, layers = None, 1
    if fourcc == b"DX10":
        dxgi, _dim, _misc, layers = struct.unpack("<4I", data[128:144])
        offset = 148
        fmt = "BC1" if dxgi in DXGI_BC1 else "BC3" if dxgi in DXGI_BC3 else None
        if fmt is None:
            raise DDSError("unsupported DXGI format %d" % dxgi)
    elif fourcc == b"DXT1":
        fmt = "BC1"
    elif fourcc == b"DXT5":
        fmt = "BC3"
    else:
        raise DDSError("unsupported DDS format %r" % fourcc)
    return dict(width=width, height=height, mips=mips, format=fmt, layers=max(1, layers),
                offset=offset)


def _mip_size(w, h, fmt):
    bw, bh = max(1, (w + 3) // 4), max(1, (h + 3) // 4)
    return bw * bh * (8 if fmt == "BC1" else 16)


def _rgb565(c):
    r = ((c >> 11) & 31).astype(np.float32) * (255.0 / 31.0)
    g = ((c >> 5) & 63).astype(np.float32) * (255.0 / 63.0)
    b = (c & 31).astype(np.float32) * (255.0 / 31.0)
    return np.stack([r, g, b], axis=-1)


def _decode_color(block, four_color_only):
    """block: (n, 8) uint8 BC1 colour blocks -> (n, 16, 4) RGBA float."""
    c0 = block[:, 0].astype(np.uint16) | (block[:, 1].astype(np.uint16) << 8)
    c1 = block[:, 2].astype(np.uint16) | (block[:, 3].astype(np.uint16) << 8)
    idx = (block[:, 4].astype(np.uint32) | (block[:, 5].astype(np.uint32) << 8) |
           (block[:, 6].astype(np.uint32) << 16) | (block[:, 7].astype(np.uint32) << 24))
    p0, p1 = _rgb565(c0), _rgb565(c1)
    four = (c0 > c1) | four_color_only
    p2 = np.where(four[:, None], (2 * p0 + p1) / 3.0, (p0 + p1) / 2.0)
    p3 = np.where(four[:, None], (p0 + 2 * p1) / 3.0, 0.0)
    pal = np.stack([p0, p1, p2, p3], axis=1)                     # (n, 4, 3)
    alpha = np.ones((len(block), 4), np.float32) * 255.0
    alpha[:, 3] = np.where(four, 255.0, 0.0)
    sel = (idx[:, None] >> (2 * np.arange(16, dtype=np.uint32))) & 3   # (n, 16)
    rgb = np.take_along_axis(pal, sel[..., None].astype(np.int64).repeat(3, axis=2), axis=1)
    a = np.take_along_axis(alpha, sel.astype(np.int64), axis=1)
    return np.concatenate([rgb, a[..., None]], axis=2)


def _decode_alpha(block):
    """(n, 8) BC3 alpha blocks -> (n, 16) alpha."""
    a0 = block[:, 0].astype(np.float32)
    a1 = block[:, 1].astype(np.float32)
    bits = np.zeros(len(block), dtype=np.uint64)
    for i in range(6):
        bits |= block[:, 2 + i].astype(np.uint64) << np.uint64(8 * i)
    sel = ((bits[:, None] >> (np.uint64(3) * np.arange(16, dtype=np.uint64))) & np.uint64(7)).astype(np.int64)
    eight = a0 > a1
    pal = np.zeros((len(block), 8), np.float32)
    pal[:, 0], pal[:, 1] = a0, a1
    for i in range(2, 8):
        pal[:, i] = np.where(eight, ((8 - i) * a0 + (i - 1) * a1) / 7.0,
                             np.where(i < 6, ((6 - i) * a0 + (i - 1) * a1) / 5.0,
                                      0.0 if i == 6 else 255.0))
    return np.take_along_axis(pal, sel, axis=1)


def decode_level(raw, w, h, fmt):
    bw, bh = max(1, (w + 3) // 4), max(1, (h + 3) // 4)
    size = 8 if fmt == "BC1" else 16
    blocks = np.frombuffer(raw[:bw * bh * size], dtype=np.uint8).reshape(-1, size)
    if fmt == "BC1":
        px = _decode_color(blocks, False)
    else:
        px = _decode_color(blocks[:, 8:], True)
        px[:, :, 3] = _decode_alpha(blocks[:, :8])
    px = px.reshape(bh, bw, 4, 4, 4).transpose(0, 2, 1, 3, 4).reshape(bh * 4, bw * 4, 4)
    return np.clip(px[:h, :w], 0, 255).astype(np.uint8)


def decode(data, layer=None):
    """[(slice index, HxWx4 uint8 RGBA, top row first)] for each array slice."""
    hd = header(data)
    w, h, fmt = hd["width"], hd["height"], hd["format"]
    per_slice = 0
    mw, mh = w, h
    for _ in range(hd["mips"]):
        per_slice += _mip_size(mw, mh, fmt)
        mw, mh = max(1, mw // 2), max(1, mh // 2)
    out = []
    for s in range(hd["layers"]):
        if layer is not None and s != layer:
            continue
        start = hd["offset"] + s * per_slice
        out.append((s, decode_level(data[start:start + _mip_size(w, h, fmt)], w, h, fmt)))
    return out


def write_png(path, rgba):
    """Write an HxWx4 uint8 array as a PNG (no dependencies)."""
    import zlib
    h, w = rgba.shape[:2]
    raw = b"".join(b"\x00" + rgba[y].tobytes() for y in range(h))

    def chunk(tag, payload):
        c = struct.pack(">I", len(payload)) + tag + payload
        return c + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)

    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b"")
    with open(path, "wb") as f:
        f.write(png)
