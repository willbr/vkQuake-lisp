#!/usr/bin/env python3
"""Rebuild a surface WAD (uplink, lambda, or winter) from the native editor's recipes."""
import argparse
import json
from pathlib import Path

from quake_assets import encode_miptex, encode_wad, write_file
from texture_editor import ROOT, TextureRecipe, generate_mips, stock_palette

TEXTURES = ROOT / 'examples/textures'


def build(recipes, output, palette):
    textures = {}
    for path in sorted(recipes.glob('*.json')):
        recipe = TextureRecipe().updated(json.loads(path.read_text(encoding='utf-8')))
        if path.stem != recipe.name:
            raise ValueError(f'{path} must match its texture name {recipe.name!r}')
        name = recipe.name.encode('ascii')
        textures[name] = encode_miptex(name, recipe.width, recipe.height, generate_mips(recipe, palette))
    if not textures:
        raise ValueError(f'no texture recipes in {recipes}')
    write_file(output, encode_wad(textures))
    print(f'Wrote {len(textures)} textures to {output}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--palette', type=Path, help='stock palette.lmp or pak0.pak')
    parser.add_argument('--set', default='uplink', help='recipe directory under examples/textures')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    recipes = TEXTURES / args.set
    try:
        build(recipes, args.output or recipes.with_suffix('.wad'), stock_palette(args.palette))
    except (ValueError, OSError) as error:
        parser.exit(1, f'{error}\n')


if __name__ == '__main__':
    main()
