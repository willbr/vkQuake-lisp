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
from map_editor import MapDocument, bank, cross, dot, edit_map, ramp, revision, subtract, switchback

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

    def test_ramp_polygons_follow_outward_winding(self):
        brush = ramp((0, 0, 128, 64), (12, 36), 'x', -16, 'relay_trim')
        polygons = list(brush.polygons())
        self.assertEqual([len(vertices) for _, _, vertices in polygons], [4] * 6)
        self.assertTrue(any(0 < normal[2] < 1 for normal, _, _ in polygons))
        for normal, _, (a, b, c, _) in polygons:
            self.assertGreater(dot(normal, cross(subtract(b, a), subtract(c, a))), 0)

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
                for headers, status in (({'Content-Type': 'text/plain'}, 400),
                                        ({'Content-Type': 'application/json', 'Host': 'attacker.example'}, 403)):
                    with self.assertRaises(HTTPError) as rejected:
                        urlopen(Request(url+'/edit', data=request.data, headers=headers), timeout=3)
                    self.assertEqual(rejected.exception.code, status)
                    rejected.exception.close()
                with self.assertRaises(HTTPError) as rejected:
                    urlopen(Request(url, headers={'Host': 'attacker.example'}), timeout=3)
                self.assertEqual(rejected.exception.code, 403)
                rejected.exception.close()
            finally:
                server.terminate()
                server.wait(timeout=3)
                server.stdout.close()


if __name__ == '__main__':
    unittest.main()
