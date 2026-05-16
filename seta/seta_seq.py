# seta_seq.py

import bpy
import os
import random
import string
from bpy.types import Operator
from bpy.props import StringProperty
from PIL import Image

from . import image_processing


# ----------------------------------------------------------
# Utilities
# ----------------------------------------------------------

SETA_MIX_FRAME_INDEX = 0


def generate_random_suffix(length=8):
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=length))


def ensure_sequence_editor(scene):
    if not scene.sequence_editor:
        scene.sequence_editor_create()


def get_first_free_channel(scene, frame):
    seq = scene.sequence_editor
    if not seq:
        return 1

    occupied = set()

    for s in seq.strips:
        if s.frame_start <= frame < s.frame_final_end:
            occupied.add(s.channel)

    channel = 1
    while channel in occupied:
        channel += 1

    return channel


def create_black_image(filepath, width, height):
    img = Image.new("RGB", (width, height), (0, 0, 0))
    img.save(filepath, "PNG")


def build_sequence_filenames(base_name, start_index=1, end_index=250):
    return [
        f"{base_name}{i:04d}.png"
        for i in range(start_index, end_index + 1)
    ]


# ----------------------------------------------------------
# Operator
# ----------------------------------------------------------

class SETA_OT_create_strip(Operator):
    bl_idname = "seta.create_strip"
    bl_label = "Create Stop Motion Strip"
    bl_description = "Create a new stop-motion image sequence strip"

    directory: StringProperty(
        name="Directory",
        subtype='DIR_PATH'
    )

    def execute(self, context):

        scene = context.scene
        frame = scene.frame_current

        if not self.directory:
            self.report({'ERROR'}, "No directory selected")
            return {'CANCELLED'}

        os.makedirs(self.directory, exist_ok=True)

        ensure_sequence_editor(scene)

        rnd = generate_random_suffix()
        base_name = f"seta_img_{rnd}_"

        width, height = image_processing.get_effective_render_size(scene)
        sequence_length = int(scene.seta_image_count)

        # Create 0000 for mix
        mix_filename = f"{base_name}{SETA_MIX_FRAME_INDEX:04d}.png"
        mix_filepath = os.path.join(self.directory, mix_filename)
        create_black_image(mix_filepath, width, height)

        # Create sequence placeholders 0001..N
        sequence_filenames = build_sequence_filenames(
            base_name,
            start_index=1,
            end_index=sequence_length,
        )

        for filename in sequence_filenames:
            filepath = os.path.join(self.directory, filename)
            create_black_image(filepath, width, height)

        channel = get_first_free_channel(scene, frame)

        # Add full sequence 0001..N
        bpy.ops.sequencer.image_strip_add(
            directory=self.directory,
            files=[{"name": name} for name in sequence_filenames],
            frame_start=frame,
            channel=channel,
            move_strips=False,
        )

        strip = scene.sequence_editor.active_strip
        if strip:
            strip.frame_final_duration = sequence_length

        self.report(
            {'INFO'},
            f"Created stop-motion sequence strip with {sequence_length} source frames."
        )

        return {'FINISHED'}


# ----------------------------------------------------------
# Register
# ----------------------------------------------------------

classes = (
    SETA_OT_create_strip,
)


def register():
    for c in classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(classes):
        bpy.utils.unregister_class(c)