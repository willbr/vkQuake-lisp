#!/usr/bin/env python3
"""Author the uplink buddy, launcher, anchor, and beam with stock MDL recipes."""
import argparse
from pathlib import Path

from model_editor import build


def part(low, high, material):
    return {'low': low, 'high': high, 'material': material}


def assets(directory):
    recipes = {
        'upbuddy.mdl': {
            'palette': [18, 112, 215, 224],
            'parts': {
                'legs': part([-10,-11,0], [10,11,15], 0),
                'torso': part([-11,-13,14], [11,13,35], 1),
                'head': part([-9,-10,35], [9,10,47], 2),
                'visor': part([8,-10,37], [11,10,42], 3),
                'arm': part([7,-17,22], [19,-12,27], 0),
            },
            'frames': {'follow': {}, 'assist': {'arm': [1,0,4], 'visor': [1,0,0]}},
        },
        'tether.mdl': {
            'palette': [175, 181, 238],
            'parts': {
                'grip': part([2,-8,-12], [12,1,0], 0),
                'receiver': part([4,-8,-1], [20,1,6], 1),
                'hook': part([19,-7,0], [27,0,5], 2),
            },
            'frames': {'ready': {}, 'fire': {'hook': [6,0,0]}},
        },
        'tethanch.mdl': {
            'palette': [11, 224, 233],
            'parts': {
                'base': part([-9,-9,-7], [9,9,7], 0),
                'socket': part([-5,-5,-12], [5,5,12], 2),
            },
        },
        'beam.mdl': {
            'palette': [43, 62],
            'parts': {'strand': part([0,-.55,-.55], [30,.55,.55], 1)},
        },
    }
    for name, recipe in recipes.items():
        build(recipe, directory / 'progs' / name)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    assets(parser.parse_args().directory)
