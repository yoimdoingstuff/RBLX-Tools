"""Colour space helpers. Roblox colours (Color3, Color3uint8, BrickColor) are
sRGB; Blender colour properties and shaders work in linear colour, so values
are converted when they cross into Blender."""


def srgb_to_linear(c):
    c = min(max(float(c), 0.0), 1.0)
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def linear_to_srgb(c):
    c = min(max(float(c), 0.0), 1.0)
    return c * 12.92 if c <= 0.0031308 else 1.055 * (c ** (1.0 / 2.4)) - 0.055


def to_linear(rgb):
    return tuple(srgb_to_linear(c) for c in rgb[:3])


def to_srgb(rgb):
    return tuple(linear_to_srgb(c) for c in rgb[:3])
