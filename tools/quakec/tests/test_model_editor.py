import json
import struct
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from model_editor import RecipeDocument, build, preview_palette


class ModelEditorTests(unittest.TestCase):
    def test_palette_and_named_poses_share_stock_topology(self):
        recipe = {
            'palette': [31, 215],
            'parts': {'box': {'low': [0, 0, 0], 'high': [6, 8, 10], 'material': 1}},
            'frames': {'idle': {}, 'lift': {'box': [0, 0, 4]}},
        }
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'model.mdl'
            build(recipe, output)
            data = output.read_bytes()
        header = struct.unpack_from('<4si3f3ff3f8if', data)
        self.assertEqual(header[:2], (b'IDPO', 6))
        width, height, vertices, triangles, frames = header[13:18]
        self.assertEqual((width, height, triangles, frames), (32, 32, 12, 2))
        self.assertEqual(data[88:96], bytes([31] * 4 + [215] * 4))
        first = 88 + width * height + 12 * vertices + 16 * triangles
        second = first + 28 + 4 * vertices
        self.assertEqual(data[first + 12:first + 16], b'idle')
        self.assertEqual(data[second + 12:second + 16], b'lift')
        self.assertEqual(data[second + 6] - data[first + 6], 16)

    def test_editor_applies_mesh_and_pose_edits_and_exports_the_draft(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'source.json'
            path.write_text('{"parts":{"body":{"low":[0,0,0],"high":[4,6,8],"material":0}},'
                            '"palette":[19,22]}')
            doc = RecipeDocument(path)
            doc.set_coordinates('body', None, [3, 1, 2])
            doc.set_coordinates('body', None, [5, 6, 8], size=True)
            doc.set_coordinates('body', 'idle', [0, 0, 4])
            doc.set_material('body', 1)
            self.assertTrue(doc.dirty)
            self.assertEqual(doc.recipe['parts']['body']['high'], [8, 7, 10])
            self.assertEqual(doc.frames['idle'][0][0], (3, 1, 6))
            output = Path(tmp) / 'draft.mdl'
            doc.export(output)
            self.assertEqual(output.read_bytes()[:8], b'IDPO\x06\0\0\0')
            self.assertEqual(output.read_bytes()[92], 22)
            self.assertNotIn('frames', json.loads(path.read_text()))
            doc.save()
            self.assertFalse(doc.dirty)
            self.assertEqual(json.loads(path.read_text())['frames']['idle']['body'], [0, 0, 4])
            doc.set_coordinates('body', 'idle', [0, 0, 8])
            path.write_text('{}')
            with self.assertRaisesRegex(ValueError, 'changed on disk'):
                doc.save()
            self.assertEqual(path.read_text(), '{}')

    def test_preview_reads_the_palette_from_a_pak(self):
        palette = bytes((i * 7) % 256 for i in range(768))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'pak0.pak'
            path.write_bytes(struct.pack('<4sII', b'PACK', 12+len(palette), 64) + palette
                             + struct.pack('<56sII', b'gfx/palette.lmp', 12, len(palette)))
            self.assertEqual(preview_palette(path)[14], tuple(palette[42:45]))
