"""Plain-Python data model shared by the binary (.rbxm/.rbxl) and XML
(.rbxmx/.rbxlx) readers. Nothing in this package imports bpy, so it can be
tested outside Blender."""


class CFrame:
    """Roblox CFrame: position + 3x3 rotation matrix (row-major R00..R22)."""

    __slots__ = ("pos", "rot")

    def __init__(self, pos=(0.0, 0.0, 0.0), rot=(1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0)):
        self.pos = tuple(pos)
        self.rot = tuple(rot)

    def __repr__(self):
        return "CFrame(pos=%r, rot=%r)" % (self.pos, self.rot)

    def __mul__(self, other):
        a = self.rot
        b = other.rot
        rot = tuple(
            a[r * 3 + 0] * b[0 * 3 + c] + a[r * 3 + 1] * b[1 * 3 + c] + a[r * 3 + 2] * b[2 * 3 + c]
            for r in range(3) for c in range(3))
        p = other.pos
        pos = tuple(a[r * 3] * p[0] + a[r * 3 + 1] * p[1] + a[r * 3 + 2] * p[2] + self.pos[r]
                    for r in range(3))
        return CFrame(pos, rot)

    def inverse(self):
        a = self.rot
        rt = (a[0], a[3], a[6], a[1], a[4], a[7], a[2], a[5], a[8])
        p = self.pos
        pos = tuple(-(rt[r * 3] * p[0] + rt[r * 3 + 1] * p[1] + rt[r * 3 + 2] * p[2]) for r in range(3))
        return CFrame(pos, rt)

    @staticmethod
    def from_pos(x, y, z):
        return CFrame((x, y, z))

    @staticmethod
    def from_values(*v):
        """CFrame.new(x, y, z, R00, R01, R02, R10, R11, R12, R20, R21, R22)"""
        return CFrame(v[0:3], v[3:12])

    def scaled_pos(self, sx, sy, sz):
        return CFrame((self.pos[0] * sx, self.pos[1] * sy, self.pos[2] * sz), self.rot)


class Ref:
    """Unresolved reference to another instance (by referent)."""

    __slots__ = ("referent",)

    def __init__(self, referent):
        self.referent = referent

    def __repr__(self):
        return "Ref(%r)" % (self.referent,)


class Instance:
    __slots__ = ("class_name", "props", "children", "parent", "referent")

    def __init__(self, class_name, referent=None):
        self.class_name = class_name
        self.props = {}
        self.children = []
        self.parent = None
        self.referent = referent

    @property
    def name(self):
        name = self.props.get("Name")
        if isinstance(name, bytes):
            name = name.decode("utf-8", "replace")
        return name or self.class_name

    def get(self, *names, default=None):
        """Return the first property that exists out of several spellings
        (files mix e.g. "size"/"Size", "MeshId"/"MeshID")."""
        for n in names:
            if n in self.props:
                return self.props[n]
        return default

    def find_first_child(self, name):
        for c in self.children:
            if c.name == name:
                return c
        return None

    def find_first_child_of_class(self, *class_names):
        for c in self.children:
            if c.class_name in class_names:
                return c
        return None

    def descendants(self):
        stack = list(reversed(self.children))
        while stack:
            inst = stack.pop()
            yield inst
            stack.extend(reversed(inst.children))

    def __repr__(self):
        return "<%s %r>" % (self.class_name, self.name)

    def add_child(self, child):
        if child.parent is not None and child in child.parent.children:
            child.parent.children.remove(child)
        child.parent = self
        self.children.append(child)
        return child

    def remove(self):
        if self.parent is not None and self in self.parent.children:
            self.parent.children.remove(self)
        self.parent = None

    def find_first_descendant(self, name=None, class_names=None):
        for d in self.descendants():
            if (name is None or d.name == name) and (class_names is None or d.class_name in class_names):
                return d
        return None


class Document:
    """Result of loading a Roblox file."""

    def __init__(self, roots, fmt):
        self.roots = roots
        self.format = fmt  # "binary" or "xml"

    def all_instances(self):
        for r in self.roots:
            yield r
            yield from r.descendants()

    def find_service(self, class_name):
        for r in self.roots:
            if r.class_name == class_name:
                return r
        return None

    def class_counts(self):
        counts = {}
        for inst in self.all_instances():
            counts[inst.class_name] = counts.get(inst.class_name, 0) + 1
        return counts


def resolve_refs(instances_by_referent, all_instances):
    """Replace Ref placeholders with Instance objects (or None)."""
    for inst in all_instances:
        for k, v in inst.props.items():
            if isinstance(v, Ref):
                inst.props[k] = instances_by_referent.get(v.referent)
