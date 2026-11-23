from importlib import import_module
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from quake_assets import read_wad_textures
from texture_editor import TextureDocument, TextureRecipe, generate_mips
from texture_pipeline import SOURCES, Stage, blur, render

PALETTE = tuple((i, i, i) for i in range(256))


class TextureEditorTests(unittest.TestCase):
    def test_sources_use_only_selected_quake_indices(self):
        allowed = [0, 33, 77, 142, 200, 254]
        for source in SOURCES:
            with self.subTest(source=source):
                recipe = TextureRecipe().updated({'stages': [{'kind': source}], 'width': 32,
                                                  'height': 64, 'colors': allowed})
                mips = generate_mips(recipe, PALETTE)
                self.assertEqual(tuple(map(len, mips)), (2048, 512, 128, 32))
                self.assertTrue(all(set(level) <= set(allowed) for level in mips))
                self.assertEqual(mips, generate_mips(recipe, PALETTE))
                if source in ('value', 'fractal', 'cellular', 'white'):
                    self.assertNotEqual(mips[0], generate_mips(recipe.updated({'seed': 8}), PALETTE)[0])

    def test_pipeline_respects_filter_order_amount_and_source_blend(self):
        base = Stage('solid', params={'value': 20})
        overlay = Stage('solid', amount=50, blend='add', params={'value': 90})
        self.assertAlmostEqual(render([base, overlay], 32, 32, 1)[0], .4)
        texture = Stage('bands', params={'across': 3, 'down': 1})
        threshold, smooth = Stage('threshold'), Stage('blur', params={'radius': 2})
        after = render([texture, smooth, threshold], 32, 32, 1)
        before = render([texture, threshold, smooth], 32, 32, 1)
        self.assertEqual(set(after), {0., 1.})
        self.assertTrue(any(0 < value < 1 for value in before))
        self.assertEqual(before, render([texture, threshold, smooth, Stage('invert', amount=0)], 32, 32, 1))

    def test_blur_samples_across_both_tile_edges(self):
        result = blur([1.] + [0.] * 15, 4, 4, 1)
        for index in (0, 1, 3, 4, 5, 7, 12, 13, 15):
            self.assertAlmostEqual(result[index], 1 / 9)
        self.assertEqual(result[10], 0.)

    def test_exported_png_and_wad_contain_the_same_indices(self):
        recipe = TextureRecipe().updated({'name': 'relay_wall', 'width': 32, 'height': 64})
        doc = TextureDocument(recipe, PALETTE)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            doc.export(output)
            draft = output / 'relay_wall'
            png = draft.with_suffix('.png').read_bytes()
            self.assertEqual(png[:8], b'\x89PNG\r\n\x1a\n')
            chunks = {}
            offset = 8
            while offset < len(png):
                size, kind = struct.unpack_from('>I4s', png, offset)
                start = offset + 8
                chunks[kind] = png[start:start + size]
                offset = start + size + 4
            self.assertEqual(struct.unpack_from('>IIBB', chunks[b'IHDR']), (32, 64, 8, 3))
            self.assertEqual(chunks[b'PLTE'], bytes(channel for rgb in PALETTE for channel in rgb))
            scanlines = zlib.decompress(chunks[b'IDAT'])
            self.assertEqual(scanlines[::33], bytes(64))
            self.assertEqual(b''.join(scanlines[i + 1:i + 33] for i in range(0, len(scanlines), 33)),
                             doc.levels[0])
            self.assertEqual(TextureRecipe().updated(json.loads(draft.with_suffix('.json').read_text())), recipe)
            wad = draft.with_suffix('.wad')
            miptex = read_wad_textures(wad)[b'relay_wall']
            name, width, height, *offsets = struct.unpack_from('<16s6I', miptex)
            self.assertEqual((name.rstrip(b'\0'), width, height), (b'relay_wall', 32, 64))
            self.assertEqual(offsets, [40, 2088, 2600, 2728])
            self.assertEqual(miptex[40:], b''.join(doc.levels))

            from_signal = output / 'signal.wad'
            import_module('build-signal').write_wad(from_signal, [wad])
            merged = read_wad_textures(from_signal)
            self.assertEqual(merged[b'relay_wall'], miptex)
            self.assertIn(b'relay_floor', merged)

    def test_invalid_recipe_edit_preserves_the_draft(self):
        recipe = TextureRecipe()
        doc = TextureDocument(recipe, PALETTE)
        previous = doc.levels
        with self.assertRaisesRegex(ValueError, 'Radius'):
            doc.apply({'width': 128, 'stages': [{'kind': 'blur', 'params': {'radius': 0}}]})
        self.assertEqual(doc.recipe, recipe)
        self.assertIs(doc.levels, previous)
