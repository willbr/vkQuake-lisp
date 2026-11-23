#!/usr/bin/env python3
"""Rebuild the Relay Annex surface WAD from the native editor's recipes."""
import argparse
import json
from pathlib import Path

from quake_assets import encode_miptex, encode_wad, write_file
from texture_editor import ROOT, TextureRecipe, generate_mips, stock_palette

RECIPES = ROOT / 'examples/textures/uplink'


def build(output, palette):
    textures = {}
    for path in sorted(RECIPES.glob('*.json')):
        recipe = TextureRecipe().updated(json.loads(path.read_text(encoding='utf-8')))
        if path.stem != recipe.name:
            raise ValueError(f'{path} must match its texture name {recipe.name!r}')
        name = recipe.name.encode('ascii')
        textures[name] = encode_miptex(name, recipe.width, recipe.height, generate_mips(recipe, palette))
    if not textures:
        raise ValueError(f'no texture recipes in {RECIPES}')
    write_file(output, encode_wad(textures))
    print(f'Wrote {len(textures)} textures to {output}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--palette', type=Path, help='stock palette.lmp or pak0.pak')
    parser.add_argument('--output', type=Path, default=RECIPES.with_suffix('.wad'))
    args = parser.parse_args()
    try:
        build(args.output, stock_palette(args.palette))
    except (ValueError, OSError) as error:
        parser.exit(1, f'{error}\n')


if __name__ == '__main__':
    main()
