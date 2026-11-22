import struct
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from model_editor import build


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
