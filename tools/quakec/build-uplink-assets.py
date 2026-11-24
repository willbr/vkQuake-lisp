#!/usr/bin/env python3
"""Author the mod's models with stock MDL recipes: the uplink buddy, tether,
anchor, beam, collector node, every weapon's view model and pickup, and the
beacon and ricochet projectiles."""
import argparse
import json
from pathlib import Path

from model_editor import build


RECIPES = Path(__file__).resolve().parents[2] / 'examples/models'
MODELS = ('upbuddy', 'tether', 'tethanch', 'beam', 'gcnode', 'beacon', 'bolt')
# View model recipe, pickup name. Each pickup reuses its view model's parts.
WEAPONS = (('v_lshot', 'g_lshot'), ('v_link', 'g_link'), ('v_pulse', 'g_pulse'),
           ('v_beacn', 'g_beacn'), ('v_rico', 'g_rico'), ('v_sweep', 'g_sweep'))


def pickup(recipe):
    """Center the view model's parts over the origin, resting on the floor,
    and set the stock flag that spins an item in the client."""
    boxes = [part for part in recipe['parts'].values() if 'low' in part]
    low = [min(part['low'][axis] for part in boxes) for axis in range(3)]
    high = [max(part['high'][axis] for part in boxes) for axis in range(3)]
    shift = [-(low[0] + high[0]) / 2, -(low[1] + high[1]) / 2, -low[2]]
    parts = {name: {**part, 'low': [a + b for a, b in zip(part['low'], shift)],
                    'high': [a + b for a, b in zip(part['high'], shift)]}
             for name, part in recipe['parts'].items()}
    return {'name': f"{recipe['name']} pickup", 'palette': recipe['palette'], 'flags': 8, 'parts': parts}


def assets(directory):
    for name in MODELS:
        recipe = json.loads((RECIPES / f'{name}.json').read_text(encoding='utf-8'))
        build(recipe, directory / 'progs' / f'{name}.mdl')
    for view, item in WEAPONS:
        recipe = json.loads((RECIPES / f'{view}.json').read_text(encoding='utf-8'))
        build(recipe, directory / 'progs' / f'{view}.mdl')
        build(pickup(recipe), directory / 'progs' / f'{item}.mdl')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    assets(parser.parse_args().directory)
