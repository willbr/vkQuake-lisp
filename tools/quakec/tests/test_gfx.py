from importlib import import_module
from pathlib import Path
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

gfx = import_module('build-gfx')


def stand_in_pak(path, extra=b''):
    """A PAK whose gfx.wad has every generated lump at its stock size, plus one
    lump the generator must pass through untouched."""
    lumps = [(name, 0x42, struct.pack('<ii', picture.width, picture.height) + bytes(picture.width * picture.height))
             for name, picture in gfx.replacements().items()]
    lumps.append((b'CONCHARS', 0x44, b'\x07' * 64 + extra))
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
            self.assertEqual(lumps[b'CONCHARS'], (0x44, b'\x07' * 64))
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
