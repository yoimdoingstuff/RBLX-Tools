"""Operators: import Roblox animations, export animations and models."""

import os

import bpy
from bpy.props import BoolProperty, EnumProperty, StringProperty
from bpy_extras.io_utils import ExportHelper, ImportHelper

from . import animio, assets, exporter
from .rbx import RobloxFormatError, load_file


class RBLX_OT_import_animation(bpy.types.Operator, ImportHelper):
    """Import a Roblox animation (KeyframeSequence saved from Roblox Studio, Moon Animator 2 or
    Eclipse Animator, or an animation asset id) onto the selected character's rig"""
    bl_idname = "rblx.import_animation"
    bl_label = "Import Roblox Animation"
    bl_options = {"REGISTER", "UNDO"}

    filename_ext = ".rbxm"
    filter_glob: StringProperty(default="*.rbxm;*.rbxmx", options={"HIDDEN"})
    filepath: StringProperty(name="File Path", subtype="FILE_PATH", options={"HIDDEN", "SKIP_SAVE"})
    asset_id: StringProperty(name="Animation ID", default="", options={"SKIP_SAVE"},
                             description="Roblox animation asset id (instead of a file). Your own "
                                         "animations need an API key or cookie in the settings")
    start: EnumProperty(name="Start At", default="CURRENT",
                        items=[("CURRENT", "Current Frame", ""), ("START", "Scene Start", "")])

    @classmethod
    def poll(cls, context):
        return animio.rig_for(context) is not None

    def invoke(self, context, event):
        if self.asset_id:
            return self.execute(context)
        return ImportHelper.invoke(self, context, event)

    def execute(self, context):
        rig = animio.rig_for(context)
        if rig is None:
            self.report({"WARNING"}, "Select a character (its rig or a body part) first")
            return {"CANCELLED"}
        path = self.filepath
        if self.asset_id.strip():
            resolver = assets.default_resolver("", True)
            path = resolver.resolve(self.asset_id.strip())
            if not path:
                self.report({"ERROR"}, "Couldn't download the animation: %s"
                            % (resolver.error_for(self.asset_id.strip()) or "not found"))
                return {"CANCELLED"}
        try:
            doc = load_file(path)
        except (OSError, RobloxFormatError) as ex:
            self.report({"ERROR"}, "Couldn't read %s: %s" % (os.path.basename(path or "?"), ex))
            return {"CANCELLED"}
        seqs = animio.find_sequences(doc)
        if not seqs:
            self.report({"ERROR"}, "No KeyframeSequence or CurveAnimation in this file")
            return {"CANCELLED"}
        start = context.scene.frame_current if self.start == "CURRENT" else context.scene.frame_start
        missing_all = set()
        for seq in seqs:
            frames, missing = animio.apply_sequence(context, seq, rig, start)
            missing_all.update(missing)
            if len(seqs) > 1 and rig.animation_data and rig.animation_data.action:
                rig.animation_data.action.use_fake_user = True
        msg = "Imported %d animation(s) onto %s" % (len(seqs), rig.name)
        if missing_all:
            msg += "; no joint for: " + ", ".join(sorted(missing_all)[:6])
        self.report({"WARNING"} if missing_all else {"INFO"}, msg)
        return {"FINISHED"}


class RBLX_OT_export_animation(bpy.types.Operator, ExportHelper):
    """Save the selected character's animation as a Roblox KeyframeSequence (.rbxmx). In Studio,
    insert it and load it in the Animation Editor (or Moon Animator) to publish it"""
    bl_idname = "rblx.export_animation"
    bl_label = "Export Roblox Animation"

    filename_ext = ".rbxmx"
    filter_glob: StringProperty(default="*.rbxmx", options={"HIDDEN"})
    loop: BoolProperty(name="Looped", default=False)
    priority: EnumProperty(name="Priority", default="2", items=[
        ("0", "Idle", ""), ("1", "Movement", ""), ("2", "Action", ""), ("3", "Action2", ""),
        ("4", "Action3", ""), ("5", "Action4", ""), ("1000", "Core", "")])

    @classmethod
    def poll(cls, context):
        rig = animio.rig_for(context)
        return rig is not None and rig.animation_data is not None and rig.animation_data.action

    def invoke(self, context, event):
        rig = animio.rig_for(context)
        action = rig.animation_data.action
        self.loop = bool(action.get("rbx_loop", False))
        self.filepath = bpy.path.clean_name(action.name) + ".rbxmx"
        return ExportHelper.invoke(self, context, event)

    def execute(self, context):
        rig = animio.rig_for(context)
        ok = animio.export_sequence(context, rig, self.filepath, loop=self.loop,
                                    priority=int(self.priority))
        if not ok:
            self.report({"WARNING"}, "This rig has no keyframes to export")
            return {"CANCELLED"}
        self.report({"INFO"}, "Saved " + os.path.basename(self.filepath))
        return {"FINISHED"}


class RBLX_OT_export_model(bpy.types.Operator, ExportHelper):
    """Save the selected Roblox objects (or the whole scene) as a Roblox model file (.rbxmx) that
    Studio can insert"""
    bl_idname = "rblx.export_model"
    bl_label = "Export Roblox Model"

    filename_ext = ".rbxmx"
    filter_glob: StringProperty(default="*.rbxmx", options={"HIDDEN"})
    selected_only: BoolProperty(name="Selected Only", default=True)
    include_animation: BoolProperty(name="Include Animations", default=True,
                                    description="Add each rig's animation as a KeyframeSequence")

    def execute(self, context):
        objs = list(context.selected_objects) if self.selected_only else list(context.scene.objects)
        objs = [o for o in objs if o.rblx.kind != "NONE" or o.type in ("MESH", "EMPTY")]
        # take whole models: include everything under selected models
        full = set(objs)
        for o in objs:
            full.update(o.children_recursive)
        if not full:
            self.report({"WARNING"}, "Nothing to export")
            return {"CANCELLED"}
        count, notes = exporter.export_objects(context, list(full), self.filepath,
                                               self.include_animation)
        if notes:
            txt = bpy.data.texts.get("RBX Export Report") or bpy.data.texts.new("RBX Export Report")
            txt.clear()
            txt.write("Roblox export: %s\n\n" % self.filepath + "\n".join(notes))
            self.report({"WARNING"}, "Exported %d object(s); %d note(s) in Text Editor > "
                        "RBX Export Report" % (count, len(notes)))
        else:
            self.report({"INFO"}, "Exported %d object(s)" % count)
        return {"FINISHED"}


def _menu_export(self, context):
    self.layout.operator(RBLX_OT_export_model.bl_idname, text="Roblox Model (.rbxmx)")
    self.layout.operator(RBLX_OT_export_animation.bl_idname, text="Roblox Animation (.rbxmx)")


def _menu_import(self, context):
    self.layout.operator(RBLX_OT_import_animation.bl_idname, text="Roblox Animation (.rbxm/.rbxmx)")


CLASSES = (RBLX_OT_import_animation, RBLX_OT_export_animation, RBLX_OT_export_model)


def register():
    for c in CLASSES:
        bpy.utils.register_class(c)
    bpy.types.TOPBAR_MT_file_export.append(_menu_export)
    bpy.types.TOPBAR_MT_file_import.append(_menu_import)


def unregister():
    bpy.types.TOPBAR_MT_file_import.remove(_menu_import)
    bpy.types.TOPBAR_MT_file_export.remove(_menu_export)
    for c in reversed(CLASSES):
        bpy.utils.unregister_class(c)
