"""Palette loading and file output for the stock Quake asset editors."""
from pathlib import Path
import struct
import tempfile

MIPTEX = struct.Struct('<16s6I')
WAD_HEADER = struct.Struct('<4sii')
WAD_ENTRY = struct.Struct('<iiiBB2x16s')


def write_file(path, data, expected=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    stream = tempfile.NamedTemporaryFile(dir=path.parent, delete=False)
    staged = Path(stream.name)
    try:
        with stream:
            stream.write(data)
        if expected is not None and path.read_bytes() != expected:
            raise ValueError('recipe changed on disk. Reopen it before saving.')
        if path.exists():
            staged.chmod(path.stat().st_mode & 0o777)
        staged.replace(path)
    finally:
        staged.unlink(missing_ok=True)


def read_palette(path):
    if path.suffix.lower() == '.pak':
        with path.open('rb') as pak:
            header = pak.read(12)
            if len(header) != 12:
                raise ValueError('incomplete PAK header')
            magic, directory, length = struct.unpack('<4sII', header)
            file_size = pak.seek(0, 2)
            if magic != b'PACK' or length % 64 or directory + length > file_size:
                raise ValueError('invalid PAK directory')
            pak.seek(directory)
            records = pak.read(length)
            for name, offset, size in struct.iter_unpack('<56sII', records):
                if name.rstrip(b'\0') == b'gfx/palette.lmp' and size == 768 and 12 <= offset <= file_size - size:
                    pak.seek(offset)
                    palette = pak.read(size)
                    break
            else:
                raise ValueError('PAK does not contain gfx/palette.lmp')
    else:
        palette = path.read_bytes()
    if len(palette) != 768:
        raise ValueError('the palette must contain 256 RGB colors')
    return tuple(struct.iter_unpack('3B', palette))


def encode_miptex(name, width, height, levels):
    offset = MIPTEX.size
    offsets = []
    for level in levels:
        offsets.append(offset)
        offset += len(level)
    return MIPTEX.pack(name, width, height, *offsets) + b''.join(levels)


def encode_wad(textures):
    lumps = bytearray()
    directory = bytearray()
    for name, miptex in textures.items():
        size = len(miptex)
        directory += WAD_ENTRY.pack(WAD_HEADER.size + len(lumps), size, size, 68, 0, name)
        lumps += miptex
    return WAD_HEADER.pack(b'WAD2', len(textures), WAD_HEADER.size + len(lumps)) + lumps + directory


def read_wad_textures(path):
    data = path.read_bytes()
    if len(data) < WAD_HEADER.size:
        raise ValueError(f'{path} has an incomplete WAD header')
    magic, count, table = WAD_HEADER.unpack_from(data)
    if (magic != b'WAD2' or count < 0 or table < WAD_HEADER.size
            or table + count * WAD_ENTRY.size > len(data)):
        raise ValueError(f'{path} has an invalid WAD2 directory')
    textures = {}
    for i in range(count):
        offset, disk_size, size, kind, compression, name = WAD_ENTRY.unpack_from(
            data, table + i * WAD_ENTRY.size)
        if kind != 68:
            continue
        if (compression or size != disk_size or offset < WAD_HEADER.size
                or size < MIPTEX.size or offset + size > len(data)):
            raise ValueError(f'{path} contains an invalid miptex lump')
        _, width, height, *levels = MIPTEX.unpack_from(data, offset)
        if (not width or not height or width % 16 or height % 16
                or any(start < MIPTEX.size or start + (width >> mip) * (height >> mip) > size
                       for mip, start in enumerate(levels))):
            raise ValueError(f'{path} contains invalid miptex dimensions or offsets')
        textures[name.rstrip(b'\0').lower()] = data[offset:offset + size]
    return textures
