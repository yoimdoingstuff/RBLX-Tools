"""Reader for Roblox's XML model/place format (.rbxmx / .rbxlx)."""

import base64
import math
import xml.etree.ElementTree as ET

from .datatypes import CFrame, Document, Instance, Ref, resolve_refs

_CF_KEYS = ("R00", "R01", "R02", "R10", "R11", "R12", "R20", "R21", "R22")


def _float(text):
    if text is None:
        return 0.0
    t = text.strip()
    tl = t.lower()
    if tl in ("inf", "+inf", "infinity"):
        return math.inf
    if tl in ("-inf", "-infinity"):
        return -math.inf
    if tl == "nan":
        return math.nan
    try:
        return float(t)
    except ValueError:
        return 0.0


def _int(text):
    try:
        return int((text or "0").strip())
    except ValueError:
        return int(_float(text))


def _child_float(el, tag):
    c = el.find(tag)
    return _float(c.text) if c is not None else 0.0


def _cframe(el):
    pos = tuple(_child_float(el, k) for k in ("X", "Y", "Z"))
    rot = tuple(_child_float(el, k) for k in _CF_KEYS)
    return CFrame(pos, rot)


def _packed_color(v):
    return (((v >> 16) & 255) / 255.0, ((v >> 8) & 255) / 255.0, (v & 255) / 255.0)


def _content(el):
    for tag in ("url", "uri", "Url", "Uri"):
        c = el.find(tag)
        if c is not None:
            return (c.text or "").strip()
    if el.find("null") is not None:
        return ""
    return (el.text or "").strip()


def _parse_property(el, shared):
    tag = el.tag
    text = el.text

    if tag in ("string", "ProtectedString"):
        return text or ""
    if tag == "bool":
        return (text or "").strip().lower() == "true"
    if tag in ("int", "int64", "token", "BrickColor", "SecurityCapabilities"):
        return _int(text)
    if tag in ("float", "double"):
        return _float(text)
    if tag == "Vector3":
        return tuple(_child_float(el, k) for k in ("X", "Y", "Z"))
    if tag == "Vector2":
        return tuple(_child_float(el, k) for k in ("X", "Y"))
    if tag in ("Vector3int16",):
        return tuple(int(_child_float(el, k)) for k in ("X", "Y", "Z"))
    if tag == "Color3":
        if el.find("R") is not None:
            return tuple(_child_float(el, k) for k in ("R", "G", "B"))
        return _packed_color(_int(text))
    if tag == "Color3uint8":
        return _packed_color(_int(text))
    if tag in ("CoordinateFrame", "CFrame"):
        return _cframe(el)
    if tag == "OptionalCoordinateFrame":
        c = el.find("CFrame")
        return _cframe(c) if c is not None else None
    if tag in ("Content", "ContentId"):
        return _content(el)
    if tag == "Ref":
        t = (text or "").strip()
        return None if t in ("", "null") else Ref(t)
    if tag == "BinaryString":
        try:
            return base64.b64decode((text or "").strip())
        except Exception:
            return b""
    if tag == "SharedString":
        return shared.get((text or "").strip(), b"")
    if tag == "NumberRange":
        parts = (text or "").split()
        return tuple(_float(p) for p in parts[:2])
    if tag == "NumberSequence":
        vals = [_float(p) for p in (text or "").split()]
        return [tuple(vals[i:i + 3]) for i in range(0, len(vals) - 2, 3)]
    if tag == "ColorSequence":
        vals = [_float(p) for p in (text or "").split()]
        return [tuple(vals[i:i + 5]) for i in range(0, len(vals) - 4, 5)]
    if tag == "UDim2":
        return ((_child_float(el, "XS"), int(_child_float(el, "XO"))),
                (_child_float(el, "YS"), int(_child_float(el, "YO"))))
    if tag == "UDim":
        return (_child_float(el, "S"), int(_child_float(el, "O")))
    if tag == "PhysicalProperties":
        c = el.find("CustomPhysics")
        if c is None or (c.text or "").strip().lower() != "true":
            return None
        return tuple(_child_float(el, k) for k in
                     ("Density", "Friction", "Elasticity", "FrictionWeight", "ElasticityWeight"))
    if tag == "Font":
        fam = el.find("Family")
        return {
            "Family": _content(fam) if fam is not None else "",
            "Weight": int(_child_float(el, "Weight")),
            "Style": (el.findtext("Style") or "").strip(),
        }
    if tag in ("Faces", "Axes"):
        c = el.find(tag.lower())
        return _int(c.text) if c is not None else 0
    return text


def read_xml(data, warnings=None):
    if warnings is None:
        warnings = []
    try:
        root = ET.fromstring(data)
    except ET.ParseError as ex:
        from .binary import RobloxFormatError
        raise RobloxFormatError("invalid XML: %s" % ex)

    shared = {}
    ss = root.find("SharedStrings")
    if ss is not None:
        for s in ss.findall("SharedString"):
            key = s.get("md5") or ""
            try:
                shared[key] = base64.b64decode((s.text or "").strip())
            except Exception:
                shared[key] = b""

    by_ref = {}
    all_insts = []

    def build(item, parent):
        inst = Instance(item.get("class") or "Instance", item.get("referent"))
        all_insts.append(inst)
        if inst.referent:
            by_ref[inst.referent] = inst
        props = item.find("Properties")
        if props is not None:
            for p in props:
                name = p.get("name")
                if not name:
                    continue
                try:
                    inst.props[name] = _parse_property(p, shared)
                except Exception as ex:
                    warnings.append("Skipped %s.%s: %s" % (inst.class_name, name, ex))
        if parent is not None:
            inst.parent = parent
            parent.children.append(inst)
        for child in item.findall("Item"):
            build(child, inst)
        return inst

    roots = [build(item, None) for item in root.findall("Item")]
    resolve_refs(by_ref, all_insts)
    return Document(roots, "xml")
