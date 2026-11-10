"""Pure-Python LZ4 *block* decompressor (Roblox binary chunks use raw LZ4
blocks, not the framed format)."""


def decompress(src, uncompressed_size=None):
    src = memoryview(src)
    dst = bytearray()
    i = 0
    n = len(src)
    while i < n:
        token = src[i]
        i += 1

        lit_len = token >> 4
        if lit_len == 15:
            while True:
                b = src[i]
                i += 1
                lit_len += b
                if b != 255:
                    break
        dst += src[i:i + lit_len]
        i += lit_len
        if i >= n:
            break  # last sequence has literals only

        offset = src[i] | (src[i + 1] << 8)
        i += 2
        if offset == 0:
            raise ValueError("LZ4: invalid zero offset")

        match_len = token & 15
        if match_len == 15:
            while True:
                b = src[i]
                i += 1
                match_len += b
                if b != 255:
                    break
        match_len += 4

        start = len(dst) - offset
        if start < 0:
            raise ValueError("LZ4: offset out of range")
        if offset >= match_len:
            dst += dst[start:start + match_len]
        else:
            # Overlapping copy: repeat the pattern.
            pattern = bytes(dst[start:])
            reps, rem = divmod(match_len, offset)
            dst += pattern * reps + pattern[:rem]

    if uncompressed_size is not None and len(dst) != uncompressed_size:
        raise ValueError("LZ4: expected %d bytes, got %d" % (uncompressed_size, len(dst)))
    return bytes(dst)
