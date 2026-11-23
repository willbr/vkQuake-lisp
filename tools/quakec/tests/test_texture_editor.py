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
from texture_editor import MATERIALS, RAMPS, TextureDocument, TextureRecipe, generate_mips

PALETTE = tuple((i, i, i) for i in range(256))


class TextureEditorTests(unittest.TestCase):
    def test_seeded_materials_use_only_their_quake_indices(self):
        for material in MATERIALS:
            with self.subTest(material=material):
                recipe = TextureRecipe().updated({'material': material, 'width': 32, 'height': 64})
                mips = generate_mips(recipe, PALETTE)
                allowed = set(RAMPS[recipe.ramp][1])
                if material == 'hazard':
                    allowed.update(RAMPS['steel'][1])
                self.assertEqual(tuple(map(len, mips)), (2048, 512, 128, 32))
                self.assertTrue(all(set(level) <= allowed for level in mips))
                self.assertGreater(len(set(mips[0])), 3)
                self.assertEqual(mips, generate_mips(recipe, PALETTE))
                self.assertNotEqual(mips[0], generate_mips(recipe.updated({'seed': 8}), PALETTE)[0])

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
        with self.assertRaisesRegex(ValueError, 'width and height'):
            doc.apply({'material': 'stone', 'width': 48})
        self.assertEqual(doc.recipe, recipe)
        self.assertIs(doc.levels, previous)
