import numpy
from typing import TYPE_CHECKING, Tuple, Generator, Union, Optional, Dict, Any, List, Set
import math
from concurrent.futures import ThreadPoolExecutor, Future
import time
import weakref

import minecraft_model_reader
import PyMCTranslate
from amulet.api.block import BlockManager

from amulet_map_editor import log
from .chunk import RenderChunk
from .region import ChunkManager
from amulet_map_editor.opengl.resource_pack import ResourcePackManager
from amulet_map_editor.opengl.mesh.base.tri_mesh import Drawable

if TYPE_CHECKING:
    from amulet.api.world import World


def sin(theta: Union[int, float]) -> float:
    return math.sin(math.radians(theta))


def cos(theta: Union[int, float]) -> float:
    return math.cos(math.radians(theta))


def tan(theta: Union[int, float]) -> float:
    return math.tan(math.radians(theta))


def asin(x: Union[int, float]) -> float:
    return math.degrees(math.asin(x))


def acos(x: Union[int, float]) -> float:
    return math.degrees(math.acos(x))


def atan(x: Union[int, float]) -> float:
    return math.degrees(math.atan(x))


class ChunkGenerator(ThreadPoolExecutor):
    def __init__(self, render_world: 'RenderWorld'):
        super().__init__(max_workers=1)
        self._render_world = weakref.ref(render_world)
        self._region_size = render_world.chunk_manager.region_size
        self._enabled = False
        self._generator: Optional[Future] = None
        self._chunk_rebuilds: Set[Tuple[int, int]] = set()

    @property
    def render_world(self) -> "RenderWorld":
        return self._render_world()

    def start(self):
        if not self._enabled:
            self._enabled = True
            self._generator = self.submit(self._generate_chunks)

    def stop(self):
        if self._enabled:
            self._enabled = False
            self._generator.result()

    def _generate_chunks(self):
        while self._enabled:
            start_time = time.time()
            # first check if there is a chunk that exists and needs rebuilding
            chunk_coords = next(
                (
                    c for c in self.render_world.chunk_coords() if
                    self.render_world.chunk_manager.render_chunk_needs_rebuild(c)
                ),
                None
            )
            if chunk_coords is not None:
                # if there was a chunk found that needs rebuilding then add the surrounding chunks for rebuilding
                # (this deals with if the chunk was deleted or the blocks up to the chunk boundary were deleted)
                for offset in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                    chunk_coords_ = (chunk_coords[0] + offset[0], chunk_coords[1] + offset[1])
                    if chunk_coords_ in self.render_world.chunk_manager:
                        self._chunk_rebuilds.add(chunk_coords_)
            elif self._chunk_rebuilds:
                # if a chunk was not found that needs rebuilding due to it changing but a previously
                # identified neighbour chunk needs rebuilding do that.
                chunk_coords = self._chunk_rebuilds.pop()
            else:
                # if no chunks need rebuilding then find a new chunk to load.
                chunk_coords = next(
                    (
                        c for c in self.render_world.chunk_coords() if
                        c not in self.render_world.chunk_manager
                    ),
                    None
                )
            if chunk_coords is not None:
                # if chunk coords is in here then remove it so it doesn't get generated twice.
                if chunk_coords in self._chunk_rebuilds:
                    self._chunk_rebuilds.remove(chunk_coords)

                # generate the chunk
                chunk = RenderChunk(
                    self.render_world,
                    self._region_size,
                    chunk_coords,
                    self.render_world.dimension,
                    self._render_world().texture
                )

                try:
                    chunk.create_geometry()
                except:
                    log.error(f'Failed generating chunk geometry for chunk {chunk_coords}', exc_info=True)

                self.render_world.chunk_manager.add_render_chunk(
                    chunk
                )
            delta_time = time.time() - start_time
            if delta_time < 1/60:
                # go to sleep so this thread doesn't lock up the main thread.
                time.sleep(1/60-delta_time)


class RenderWorld(ResourcePackManager, Drawable):
    def __init__(
        self,
        context_identifier: Any,
        world: 'World',
        resource_pack: minecraft_model_reader.JavaRPHandler,
        texture: Any,
        texture_bounds: Dict[Any, Tuple[float, float, float, float]],
        translator: PyMCTranslate.Version
    ):
        super().__init__(context_identifier, resource_pack, texture, texture_bounds, translator)
        self._world = world
        self._camera = [0, 150, 0, 90, 0]
        self._dimension = "overworld"
        self._render_distance = 10
        self._garbage_distance = 20
        self._chunk_manager = ChunkManager(self.context_identifier, self.texture)
        self._chunk_generator = ChunkGenerator(self)

    @property
    def world(self) -> 'World':
        return self._world

    @property
    def chunk_manager(self) -> ChunkManager:
        return self._chunk_manager

    @property
    def chunk_generator(self) -> ChunkGenerator:
        return self._chunk_generator

    @property
    def _palette(self) -> BlockManager:
        return self._world.palette

    @property
    def translator(self) -> PyMCTranslate.Version:
        return self._resource_pack_translator

    def is_closeable(self):
        return True

    def enable(self):
        self._chunk_generator.start()

    def disable(self):
        self._chunk_generator.stop()
        self.run_garbage_collector(True)

    def close(self):
        self.disable()

    @property
    def camera(self):
        return self._camera

    @camera.setter
    def camera(self, value: List[Union[int, float]]):
        self._camera = value

    @property
    def dimension(self) -> str:
        return self._dimension

    @dimension.setter
    def dimension(self, dimension: int):
        self._chunk_generator.stop()
        self._dimension = dimension
        self.run_garbage_collector(True)
        self._chunk_generator.start()

    @property
    def render_distance(self) -> int:
        """The distance to render chunks around the camera"""
        return self._render_distance

    @render_distance.setter
    def render_distance(self, val: int):
        assert isinstance(val, int), 'Render distance must be an int'
        self._render_distance = val

    @property
    def garbage_distance(self) -> int:
        """The distance outside which chunks should be unloaded"""
        return self._garbage_distance

    @garbage_distance.setter
    def garbage_distance(self, val: int):
        assert isinstance(val, int), 'garbage distance must be an int'
        self._garbage_distance = val

    def chunk_coords(self) -> Generator[Tuple[int, int], None, None]:
        """Get all of the chunks to draw/load"""
        cx, cz = int(self._camera[0]) >> 4, int(self._camera[2]) >> 4

        sign = 1
        length = 1
        for _ in range(self.render_distance*2+1):
            for _ in range(length):
                yield cx, cz
                cx += sign
            for _ in range(length):
                yield cx, cz
                cz += sign
            sign *= -1
            length += 1

    def draw(self, transformation_matrix: numpy.ndarray):
        self._chunk_manager.draw(transformation_matrix, self._camera[:3])

    def run_garbage_collector(self, remove_all=False):
        if remove_all:
            self._chunk_manager.unload()
            self._world.unload()
        else:
            safe_area = (
                self._dimension,
                self._camera[0]//16 - self.garbage_distance,
                self._camera[2]//16 - self.garbage_distance,
                self._camera[0]//16 + self.garbage_distance,
                self._camera[2]//16 + self.garbage_distance
            )
            self._chunk_manager.unload(safe_area[1:])
            self._world.unload(safe_area)
