from importlib import import_module
from pathlib import Path
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

gfx = import_module('build-gfx')


def stand_in_pak(path):
    """A PAK whose gfx.wad has every generated lump at its stock size, a
    character sheet, and one lump the generator must pass through untouched."""
    lumps = [(name, 0x42, struct.pack('<ii', picture.width, picture.height) + bytes(picture.width * picture.height))
             for name, picture in gfx.replacements().items()]
    lumps.append((b'CONCHARS', 0x44, b'\x07' * (128 * 128)))
    lumps.append((b'BACKTILE', 0x42, struct.pack('<ii', 2, 2) + b'\x05' * 4))
    wad = gfx.write_wad(lumps)
    entry = b'gfx.wad'.ljust(56, b'\0') + struct.pack('<ii', 12, len(wad))
    path.write_bytes(struct.pack('<4sii', b'PACK', 12 + len(wad), 64) + wad + entry)


class StatusBarArtTests(unittest.TestCase):
    def test_generated_lumps_keep_stock_sizes_and_others_pass_through(self):
        with tempfile.TemporaryDirectory() as directory:
            pak = Path(directory) / 'pak0.pak'
            stand_in_pak(pak)
            mod = Path(directory) / 'mod'
            gfx.build(pak, mod)
            lumps = {name: (kind, payload) for name, kind, payload in gfx.read_wad((mod / 'gfx.wad').read_bytes())}
            self.assertEqual(lumps[b'BACKTILE'], (0x42, struct.pack('<ii', 2, 2) + b'\x05' * 4))
            sheet = lumps[b'CONCHARS'][1]
            def cell(code):
                return [sheet[(code // 16 * 8 + y) * 128 + code % 16 * 8:][:8] for y in range(8)]
            # Control characters keep the stock menu art; printable ones use the font.
            self.assertEqual(cell(1), [b'\x07' * 8] * 8)
            self.assertIn(gfx.FONT_INK, b''.join(cell(ord('A'))))
            self.assertIn(gfx.FONT_GOLD, b''.join(cell(ord('A') + 128)))
            self.assertEqual(cell(ord(' ')), [bytes(8)] * 8)
            for name, picture in gfx.replacements().items():
                with self.subTest(name=name):
                    self.assertEqual(lumps[name], (0x42, picture.qpic()))
            # Status bar pictures draw opaque in software, so nothing uses index 255.
            self.assertNotIn(255, lumps[b'FACE1'][1][8:])
            width, height = struct.unpack_from('<ii', (mod / 'gfx/conback.lmp').read_bytes())
            self.assertEqual((width, height), (320, 200))

    def test_a_resized_stock_lump_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            pak = Path(directory) / 'pak0.pak'
            lumps = [(b'SBAR', 0x42, struct.pack('<ii', 8, 8) + bytes(64))]
            wad = gfx.write_wad(lumps)
            entry = b'gfx.wad'.ljust(56, b'\0') + struct.pack('<ii', 12, len(wad))
            pak.write_bytes(struct.pack('<4sii', b'PACK', 12 + len(wad), 64) + wad + entry)
            with self.assertRaisesRegex(ValueError, 'lacks'):
                gfx.build(pak, Path(directory) / 'mod')


if __name__ == '__main__':
    unittest.main()
