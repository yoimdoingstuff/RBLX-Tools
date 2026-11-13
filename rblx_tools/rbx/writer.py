"""Writes Roblox XML model files (.rbxmx) that Roblox Studio can open or
insert. No bpy here: callers build Item trees of typed properties."""

from xml.sax.saxutils import escape


class Item:
    """One Roblox instance to write: class name, properties and children.
    Properties are (type, name, value) with types: string, bool, int, float,
    token, Vector3, CoordinateFrame, Color3, Color3uint8, Content, Ref,
    NumberRange, NumberSequence, ColorSequence."""

    _next = [0]

    def __init__(self, class_name, name=None):
        self.class_name = class_name
        self.props = []
        self.children = []
        Item._next[0] += 1
        self.referent = "RBX%08X" % Item._next[0]
        if name is not None:
            self.prop("string", "Name", name)

    def prop(self, kind, name, value):
        self.props.append((kind, name, value))
        return self

    def add(self, child):
        self.children.append(child)
        return child


def _num(v):
    v = float(v)
    if v != v or v in (float("inf"), float("-inf")):
        v = 0.0
    s = repr(round(v, 6))
    return s[:-2] if s.endswith(".0") else s


def _value(kind, name, value):
    n = escape(name, {'"': "&quot;"})
    if kind == "string":
        return '<string name="%s">%s</string>' % (n, escape(str(value)))
    if kind == "bool":
        return '<bool name="%s">%s</bool>' % (n, "true" if value else "false")
    if kind == "int":
        return '<int name="%s">%d</int>' % (n, int(value))
    if kind == "float":
        return '<float name="%s">%s</float>' % (n, _num(value))
    if kind == "token":
        return '<token name="%s">%d</token>' % (n, int(value))
    if kind == "Vector2":
        return '<Vector2 name="%s"><X>%s</X><Y>%s</Y></Vector2>' % (n, *map(_num, value))
    if kind == "Vector3":
        return '<Vector3 name="%s"><X>%s</X><Y>%s</Y><Z>%s</Z></Vector3>' % (n, *map(_num, value))
    if kind == "CoordinateFrame":
        pos, rot = value
        rv = list(rot)
        return ('<CoordinateFrame name="%s"><X>%s</X><Y>%s</Y><Z>%s</Z>' % (n, *map(_num, pos)) +
                "".join("<R%d%d>%s</R%d%d>" % (i // 3, i % 3, _num(rv[i]), i // 3, i % 3)
                        for i in range(9)) + "</CoordinateFrame>")
    if kind == "Color3":
        return '<Color3 name="%s"><R>%s</R><G>%s</G><B>%s</B></Color3>' % (n, *map(_num, value))
    if kind == "Color3uint8":
        r, g, b = (max(0, min(255, int(round(c * 255.0)))) for c in value)
        return '<Color3uint8 name="%s">%d</Color3uint8>' % (n, (0xFF << 24) | (r << 16) | (g << 8) | b)
    if kind == "Content":
        if not value:
            return '<Content name="%s"><null></null></Content>' % n
        return '<Content name="%s"><url>%s</url></Content>' % (n, escape(str(value)))
    if kind == "Ref":
        return '<Ref name="%s">%s</Ref>' % (n, value.referent if value is not None else "null")
    if kind == "NumberRange":
        return '<NumberRange name="%s">%s %s </NumberRange>' % (n, _num(value[0]), _num(value[1]))
    if kind == "NumberSequence":
        return '<NumberSequence name="%s">%s</NumberSequence>' % (
            n, "".join("%s %s %s " % (_num(t), _num(v), _num(e)) for t, v, e in value))
    if kind == "ColorSequence":
        return '<ColorSequence name="%s">%s</ColorSequence>' % (
            n, "".join("%s %s %s %s %s " % (_num(k[0]), _num(k[1]), _num(k[2]), _num(k[3]),
                                            _num(k[4] if len(k) > 4 else 0)) for k in value))
    raise ValueError("unknown property type " + kind)


def _write(item, out, depth):
    pad = " " * depth
    out.append('%s<Item class="%s" referent="%s">' % (pad, item.class_name, item.referent))
    out.append(pad + " <Properties>")
    for kind, name, value in item.props:
        out.append(pad + "  " + _value(kind, name, value))
    out.append(pad + " </Properties>")
    for c in item.children:
        _write(c, out, depth + 1)
    out.append(pad + "</Item>")


def to_xml(items):
    out = ['<roblox xmlns:xmime="http://www.w3.org/2005/05/xmlmime" '
           'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
           'xsi:noNamespaceSchemaLocation="http://www.roblox.com/roblox.xsd" version="4">',
           "<External>null</External>", "<External>nil</External>"]
    for it in items:
        _write(it, out, 0)
    out.append("</roblox>")
    return "\n".join(out) + "\n"


def write_file(path, items):
    with open(path, "w", encoding="utf-8") as f:
        f.write(to_xml(items))
