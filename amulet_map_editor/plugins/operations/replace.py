from typing import TYPE_CHECKING, Tuple, Dict
import wx
import numpy

from amulet.api.block import Block
from amulet.api.selection import SelectionGroup
from amulet.api.data_types import Dimension
from amulet_map_editor.amulet_wx.block_select import BlockDefine
from amulet_map_editor.amulet_wx.simple import SimpleDialog

if TYPE_CHECKING:
    from amulet.api.world import World


def replace(
    world: "World",
    dimension: Dimension,
    selection: SelectionGroup,
    options: dict
):
    original_block_options: Tuple[str, Tuple[int, int, int], bool, str, str, Dict[str, str]] = options.get("original_block_options")
    replacement_block: Block = options.get("replacement_block")
    if original_block_options is None or not isinstance(replacement_block, Block):
        # verify that the options are actually given
        raise Exception('Please specify the blocks before running the replace operation')

    original_platform, original_version, original_blockstate, original_namespace, original_base_name, original_properties = original_block_options
    replacement_block_id = world.palette.get_add_block(replacement_block)

    original_block_matches = []
    universal_block_count = 0

    iter_count = len(list(world.get_chunk_slices(selection, dimension)))
    count = 0

    for chunk, slices, _ in world.get_chunk_slices(selection, dimension):
        if universal_block_count < len(world.palette):
            for universal_block_id in range(universal_block_count, len(world.palette)):
                version_block = world.translation_manager.get_version(
                    original_platform,
                    original_version
                ).block.from_universal(
                    world.palette[universal_block_id],
                    force_blockstate=original_blockstate
                )[0]
                if version_block.namespace == original_namespace and \
                    version_block.base_name == original_base_name\
                    and all(original_properties.get(prop) in ['*', val.to_snbt()] for prop, val in version_block.properties.items()):
                    original_block_matches.append(universal_block_id)

            universal_block_count = len(world.palette)
        blocks = chunk.blocks[slices]
        blocks[numpy.isin(blocks, original_block_matches)] = replacement_block_id
        chunk.blocks[slices] = blocks
        chunk.changed = True

        count += 1
        yield 100 * count / iter_count


def show_ui(parent, world: "World", options: dict) -> dict:
    dialog = SimpleDialog(parent, 'Replace', wx.HORIZONTAL)

    original_block = BlockDefine(
        dialog,
        world.world_wrapper.translation_manager,
        *(options.get("original_block_options", []) or [world.world_wrapper.platform]),
        wildcard=True
    )
    replacement_block = BlockDefine(
        dialog,
        world.world_wrapper.translation_manager,
        *(options.get("replacement_block_options", []) or [world.world_wrapper.platform])
    )
    dialog.sizer.Add(original_block, 0)
    dialog.sizer.Add(replacement_block, 0)
    dialog.Fit()

    if dialog.ShowModal() == wx.ID_OK:
        options = {
            "original_block_options": original_block.options,
            "replacement_block": world.translation_manager.get_version(
                replacement_block.platform,
                replacement_block.version
            ).block.to_universal(
                replacement_block.block,
                force_blockstate=replacement_block.force_blockstate
            )[0],
            "replacement_block_options": replacement_block.options,
        }
    return options


export = {
    "v": 1,  # a version 1 plugin
    "name": "Replace",  # the name of the plugin
    "features": ["src_selection", "wxoptions"],
    "inputs": ["src_selection", "options"],  # the inputs to give to the plugin
    "operation": replace,  # the actual function to call when running the plugin
    "wxoptions": show_ui
}
