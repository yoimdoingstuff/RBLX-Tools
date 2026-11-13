"""Roblox smooth terrain (Terrain.SmoothGrid) decoder / encoder.

Layout (unofficial spec from rbx-dom's smooth-grid.md, verified on Roblox's
template places):
    u8 version (1), u8 log2 chunk size (5 -> 32^3 voxels), then chunks:
      3 x i32 chunk offset from the previous chunk (byte-interleaved, big
      endian), in chunks
      voxels until the chunk is full, ordered Y (slowest), Z, X (fastest):
        u8 flag: bits 0-5 material index, bit 6 occupancy stored, bit 7 count stored
        [u8 solid occupancy / 255]            if bit 6
        [u8 count]                            if bit 7 (the voxel repeats `count` more times)
        [u8 water occupancy / 255]            if bit 7 and count == 0
A voxel is 4 studs; a 32-voxel chunk covers 128 studs."""

VOXEL_STUDS = 4.0
MATERIALS = ["Air", "Water", "Grass", "Slate", "Concrete", "Brick", "Sand", "WoodPlanks", "Rock",
             "Glacier", "Snow", "Sandstone", "Mud", "Basalt", "Ground", "CrackedLava", "Asphalt",
             "Cobblestone", "Ice", "LeafyGrass", "Salt", "Limestone", "Pavement"]
# Terrain.MaterialColors: 23 RGB triples, the first two unused, then Grass..Pavement
COLOR_ORDER = MATERIALS[2:]


class TerrainError(Exception):
    pass


# Chunk offsets are byte-interleaved *big-endian* i32s, like the rest of Roblox's
# binary format (checked against Roblox's template places: the first chunk of a
# map centred on the origin decodes to (-8, -1, -8)).
def _deinterleave_i32(raw, n):
    return [int.from_bytes(bytes(raw[b * n + i] for b in range(4)), "big", signed=True)
            for i in range(n)]


def _interleave_i32(vals):
    bs = [v.to_bytes(4, "big", signed=True) for v in vals]
    return bytes(bs[i][b] for b in range(4) for i in range(len(vals)))


def decode(data):
    """Returns (chunk_size, chunks) with chunks = [((cx, cy, cz), runs)], where
    runs = [(start_index, count, material, solid_occupancy, water_occupancy)]
    for non-air runs. Voxel index = y*cs*cs + z*cs + x."""
    data = bytes(data or b"")
    if len(data) < 2:
        return 32, []
    if data[0] != 1:
        raise TerrainError("unknown terrain version %d" % data[0])
    if data[1] > 8:
        raise TerrainError("bad chunk size %d" % data[1])
    cs = 1 << data[1]
    total = cs * cs * cs
    pos = 2
    n = len(data)
    cx = cy = cz = 0
    chunks = []
    while pos < n:
        if pos + 12 > n:
            raise TerrainError("truncated chunk header")
        dx, dy, dz = _deinterleave_i32(data[pos:pos + 12], 3)
        pos += 12
        cx, cy, cz = cx + dx, cy + dy, cz + dz
        runs = []
        i = 0
        while i < total:
            if pos >= n:
                raise TerrainError("truncated voxel data")
            flag = data[pos]
            pos += 1
            mat = flag & 0x3F
            occ = 1.0
            water = 0.0
            count = 1
            if flag & 0x40:
                occ = data[pos] / 255.0
                pos += 1
            if flag & 0x80:
                c = data[pos]
                pos += 1
                if c == 0:
                    water = data[pos] / 255.0
                    pos += 1
                else:
                    count = c + 1
            if mat != 0 or water > 0.0:
                runs.append((i, min(count, total - i), mat, occ if mat != 0 else 0.0, water))
            i += count
        chunks.append(((cx, cy, cz), runs))
    return cs, chunks


def encode(chunks, cs_log2=5):
    """Inverse of decode, for tests: chunks = [((cx,cy,cz), dense list of
    (material, occupancy) per voxel)]."""
    out = bytearray((1, cs_log2))
    px = py = pz = 0
    for (cx, cy, cz), voxels in sorted(chunks, key=lambda c: c[0]):
        out += _interleave_i32([cx - px, cy - py, cz - pz])
        px, py, pz = cx, cy, cz
        i = 0
        while i < len(voxels):
            mat, occ = voxels[i]
            run = 1
            while i + run < len(voxels) and voxels[i + run] == voxels[i] and run < 256:
                run += 1
            flag = mat & 0x3F
            extra = bytearray()
            if mat != 0 and occ < 1.0:
                flag |= 0x40
                extra.append(int(round(occ * 255)))
            if run > 1:
                flag |= 0x80
                extra.append(run - 1)
            out.append(flag)
            out += extra
            i += run
    return bytes(out)


def material_colors(blob):
    """{material name: (r, g, b) 0..1 sRGB} from Terrain.MaterialColors."""
    blob = bytes(blob or b"")
    out = {}
    for k, name in enumerate(COLOR_ORDER):
        o = 6 + k * 3
        if o + 3 <= len(blob):
            out[name] = tuple(b / 255.0 for b in blob[o:o + 3])
    return out


def voxel_points(cs, chunks, min_occupancy=0.05):
    """{material index: [((x, y, z) voxel centre in studs, Roblox axes, occupancy)]};
    water (index 1) includes shoreline water occupancy."""
    pts = {}
    cs2 = cs * cs
    for (cx, cy, cz), runs in chunks:
        bx, by, bz = cx * cs, cy * cs, cz * cs
        for start, count, mat, occ, water in runs:
            items = []
            if mat != 0 and occ >= min_occupancy:
                items.append((mat, occ))
            if mat != 1 and water >= min_occupancy:
                items.append((1, water))
            for key, amount in items:
                lst = pts.setdefault(key, [])
                for idx in range(start, start + count):
                    y, rem = divmod(idx, cs2)
                    z, x = divmod(rem, cs)
                    lst.append((((bx + x + 0.5) * VOXEL_STUDS, (by + y + 0.5) * VOXEL_STUDS,
                                 (bz + z + 0.5) * VOXEL_STUDS), amount))
    return pts
