"""Roblox enum values used when reading/writing part properties."""

# Enum.Material token values -> name
MATERIALS = {
    256: "Plastic",
    272: "SmoothPlastic",
    288: "Neon",
    512: "Wood",
    528: "WoodPlanks",
    784: "Marble",
    788: "Basalt",
    800: "Slate",
    804: "CrackedLava",
    816: "Concrete",
    820: "Limestone",
    832: "Granite",
    836: "Pavement",
    848: "Brick",
    864: "Pebble",
    880: "Cobblestone",
    896: "Rock",
    912: "Sandstone",
    1040: "CorrodedMetal",
    1056: "DiamondPlate",
    1072: "Foil",
    1088: "Metal",
    1280: "Grass",
    1284: "LeafyGrass",
    1296: "Sand",
    1312: "Fabric",
    1328: "Snow",
    1344: "Mud",
    1360: "Ground",
    1376: "Asphalt",
    1392: "Salt",
    1536: "Ice",
    1552: "Glacier",
    1568: "Glass",
    1584: "ForceField",
    1792: "Air",
    2048: "Water",
}

# Part.Shape (serialized as "shape")
PART_SHAPES = {0: "BALL", 1: "BLOCK", 2: "CYLINDER", 3: "WEDGE", 4: "CORNER_WEDGE"}

# Enum.NormalId
NORMAL_IDS = {0: "RIGHT", 1: "TOP", 2: "BACK", 3: "LEFT", 4: "BOTTOM", 5: "FRONT"}

# Enum.MeshType (SpecialMesh)
MESH_TYPES = {
    0: "Head", 1: "Torso", 2: "Wedge", 3: "Sphere", 4: "Cylinder", 5: "FileMesh",
    6: "Brick", 7: "Prism", 8: "Pyramid", 9: "ParallelRamp", 10: "RightAngleRamp",
    11: "CornerWedge",
}

# A subset of the BrickColor palette, for very old files that only store
# BrickColor and not Color3uint8.
BRICK_COLORS = {
    1: (242, 243, 243), 5: (215, 197, 154), 9: (232, 186, 200), 18: (204, 142, 105),
    21: (196, 40, 28), 23: (13, 105, 172), 24: (245, 205, 48), 26: (27, 42, 53),
    28: (40, 127, 71), 37: (75, 151, 75), 38: (160, 95, 53), 45: (180, 210, 228),
    101: (218, 134, 122), 102: (110, 153, 202), 104: (107, 50, 124), 105: (226, 155, 64),
    106: (218, 133, 65), 107: (0, 143, 156), 119: (164, 189, 71), 125: (234, 184, 146),
    135: (116, 134, 157), 141: (39, 70, 45), 151: (120, 144, 130), 153: (149, 121, 119),
    192: (105, 64, 40), 194: (163, 162, 165), 199: (99, 95, 98), 208: (229, 228, 223),
    217: (124, 92, 70), 226: (253, 234, 141), 1001: (248, 248, 248), 1002: (205, 205, 205),
    1003: (17, 17, 17), 1004: (255, 0, 0), 1005: (255, 176, 0), 1006: (180, 128, 255),
    1007: (163, 75, 75), 1009: (255, 255, 0), 1010: (0, 0, 255), 1011: (0, 32, 96),
    1012: (33, 84, 185), 1013: (4, 175, 236), 1014: (170, 85, 0), 1015: (170, 0, 170),
    1016: (255, 102, 204), 1017: (255, 175, 0), 1018: (18, 238, 212), 1019: (0, 255, 255),
    1020: (0, 255, 0), 1021: (58, 125, 21), 1022: (127, 142, 100), 1023: (140, 91, 159),
    1024: (175, 221, 255), 1025: (255, 201, 201), 1026: (177, 167, 255), 1027: (159, 243, 233),
    1028: (204, 255, 204), 1029: (255, 255, 204), 1030: (255, 204, 153), 1031: (98, 37, 209),
    1032: (255, 0, 191),
}


def brick_color(number):
    rgb = BRICK_COLORS.get(number, (163, 162, 165))  # Medium stone grey
    return tuple(c / 255.0 for c in rgb)
