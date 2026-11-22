import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'tools/quakec'))
from map_editor import MapDocument, bank, edit_map, revision, switchback

WORLD = '{\n"classname" "worldspawn"\n"wad" "signal.wad"\n}\n'


class MapEditorTests(unittest.TestCase):
    def test_inspects_existing_annex_and_keeps_unedited_source(self):
        original = (ROOT / 'examples/annex.map').read_text()
        doc = MapDocument(original)
        self.assertEqual(doc.text, original)
        self.assertEqual(doc.validate()['brushes'], 60)
        self.assertIn('polygon', doc.preview('side'))

    def test_edits_and_generates_stock_brushes(self):
        doc = MapDocument(WORLD)
        doc.apply([
            {'op': 'box', 'low': [0, 0, -16], 'high': [128, 128, 0], 'texture': 'relay_floor'},
            {'op': 'place', 'fields': {'classname': 'info_player_start', 'origin': [16, 16, 24]}},
            {'op': 'place', 'fields': {'classname': 'qslisp_waypoint', 'origin': [64, 64, 24]}},
            {'op': 'link', 'entity': 1, 'to': 2, 'name': 'turn'},
            {'op': 'translate-brush', 'brush': 0, 'offset': [4, 0, 0]},
        ])
        self.assertEqual(doc.value(1, 'target'), 'turn')
        self.assertEqual(doc.value(2, 'targetname'), 'turn')
        self.assertEqual(doc.validate()['bounds'], [(4, 0, -16), (132, 128, 24)])
        self.assertEqual(len(bank((0, 0, 0), (96, 352), (0, 90), 48, 6, 'relay_trim')), 12)
        descent = switchback((-2400, -600, 0), 4576, 512, 704, 1280, 2, 'relay_floor')
        self.assertEqual(len(descent), 3)
        self.assertIn((-2400, 104, -1280), descent[-1].vertices())

    def test_preview_and_invalid_edit_leave_file_intact(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'level.map'
            path.write_text(WORLD)
            operations = [{'op': 'place', 'fields': {'classname': 'light', 'origin': [0, 0, 80]}}]
            self.assertIn('+"classname" "light"', edit_map(path, operations)['diff'])
            self.assertEqual(path.read_text(), WORLD)
            with self.assertRaisesRegex(ValueError, 'no classname'):
                edit_map(path, operations + [{'op': 'place', 'fields': {}}], write=True)
            self.assertEqual(path.read_text(), WORLD)
            edit_map(path, operations, expected=revision(WORLD), write=True)
            with self.assertRaisesRegex(ValueError, 'revision changed'):
                edit_map(path, operations, expected=revision(WORLD), write=True)

    def test_local_tcp_session_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'level.map'
            path.write_text(WORLD)
            server = subprocess.Popen([sys.executable, ROOT / 'tools/quakec/map_editor.py',
                                       path, 'serve', '--port', '0'],
                                      stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
            try:
                url = server.stdout.readline().split()[-1]
                with urlopen(url, timeout=3) as response:
                    first = json.load(response)
                edit = {'revision': first['revision'], 'write': True, 'operations': [
                    {'op': 'place', 'fields': {'classname': 'light', 'origin': [0, 0, 32]}}]}
                request = Request(url+'/edit', data=json.dumps(edit).encode(),
                                  headers={'Content-Type': 'application/json'})
                with urlopen(request, timeout=3) as response:
                    self.assertEqual(json.load(response)['entities'], 2)
                with self.assertRaises(HTTPError) as rejected:
                    urlopen(request, timeout=3)
                self.assertEqual(rejected.exception.code, 409)
                rejected.exception.close()
            finally:
                server.terminate()
                server.wait(timeout=3)
                server.stdout.close()


if __name__ == '__main__':
    unittest.main()
