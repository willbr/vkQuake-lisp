#!/usr/bin/env python3
"""Author the uplink buddy, launcher, anchor, beam, and collector node with stock MDL recipes."""
import argparse
import json
from pathlib import Path

from model_editor import build


RECIPES = Path(__file__).resolve().parents[2] / 'examples/models'


def assets(directory):
    for name in ('upbuddy', 'tether', 'tethanch', 'beam', 'gcnode'):
        recipe = json.loads((RECIPES / f'{name}.json').read_text(encoding='utf-8'))
        build(recipe, directory / 'progs' / f'{name}.mdl')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    assets(parser.parse_args().directory)
