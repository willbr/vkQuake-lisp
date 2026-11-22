"""Drive the original local client and check the Signal Room's observable state."""
import json
import math
import re
import struct

SAVES = ('spawned', 'walked', 'rise', 'landed', 'missed', 'cleared', 'reset', 'replay')
PROFILES = {
    'jump': ('qslisp: jump',),
    'shot': ('qslisp: fired', 'qslisp: target hit'),
    'combined': ('qslisp: jump', 'qslisp: fired', 'qslisp: target hit'),
}


def profile(name, commands):
    return ['profile', f'echo qslisp-profile-{name}-begin', *commands, 'wait',
            'profile', f'echo qslisp-profile-{name}-end']


def verification_commands():
    commands = ['host_framerate 0.05', 'con_notifytime 0'] + ['wait'] * 35
    commands += ['save spawned', 'screenshot', '+forward'] + ['wait'] * 9
    commands += ['-forward'] + ['wait'] * 9 + ['save walked']
    commands += profile('jump', ['+jump'])
    commands += ['wait'] * 5 + ['save rise'] + ['wait'] * 26
    commands += ['save landed', '-jump', 'wait', 'wait']
    commands += ['+left'] + ['wait'] * 12 + ['-left', '+attack', 'wait', '-attack']
    commands += ['wait'] * 8 + ['save missed', '+right'] + ['wait'] * 12 + ['-right', 'wait']
    commands += profile('shot', ['+attack'])
    commands += ['-attack', 'wait', 'wait', 'save cleared', 'screenshot', 'map signal']
    commands += ['wait'] * 35 + ['save reset']
    commands += profile('combined', ['+jump', '+attack'])
    commands += ['-attack', '-jump'] + ['wait'] * 25
    commands += ['save replay', 'toggleconsole', 'quit']
    return '\n'.join(commands) + '\n'


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def save_state(path):
    text = path.read_text(encoding='cp437')
    blocks = re.findall(r'^\{\s*\n(.*?)^\}', text, flags=re.M | re.S)
    require(len(blocks) >= 3, f'missing player edict in {path.name}')
    entities = [dict(re.findall(r'^"([^"]*)"\s+"([^"]*)"', block, re.M)) for block in blocks[1:]]
    player = entities[1]
    return {
        'origin': tuple(float(x) for x in player['origin'].split()),
        'rounds': int(float(player['ammo_shells'])),
        'weapon': player.get('weaponmodel'),
        'targets': sum(ent.get('classname') == 'qslisp_target' for ent in entities),
    }


def measured_profiles(lines, program):
    header = struct.unpack_from('<15i', program)
    table = program[header[8]:header[8] + header[9] * 36]
    frames = [frame for frame in struct.iter_unpack('<7i8B', table) if frame[0] > 0]
    measured = {}
    for name, events in PROFILES.items():
        start = lines.index(f'qslisp-profile-{name}-begin')
        end = lines.index(f'qslisp-profile-{name}-end', start)
        sample = lines[start + 1:end]
        require(all(event in sample for event in events), f'{name} did not run in the profiled frame')
        counts = {}
        for line in sample:
            match = re.fullmatch(r'(\d+) (\S+)', line)
            if match:
                counts[match[2]] = int(match[1])
        body = counts.get('__qslisp_fn_PlayerPreThink')
        require(body is not None, f'no PlayerPreThink count in the {name} profile')
        # Stock profile only prints the top ten counts. Every omitted
        # bytecode function can have consumed at most the tenth count.
        limit = sum(counts.values())
        if len(counts) == 10:
            limit += (len(frames) - 10) * min(counts.values())
        require(limit < 100_000, f'{name} frame exceeds the stock instruction budget bound')
        measured[name] = {'player_prethink_body': body, 'frame_instruction_upper_bound': limit}
    return {'global_slots': header[13], 'entity_field_slots': header[14],
            'largest_local_frame': max(frame[2] for frame in frames), 'profiles': measured}


def verify_challenge(output, lines):
    states = {name: save_state(output / f'{name}.sav') for name in SAVES}
    spawn = states['spawned']
    walked = states['walked']
    require(spawn['rounds'] == 3 and spawn['weapon'] == 'progs/v_shot.mdl' and spawn['targets'] == 1,
            'player did not start with a weapon, three shells, and a target')
    require(walked['origin'][0] - spawn['origin'][0] > 32, 'forward input did not move the player')
    require(states['rise']['origin'][2] - walked['origin'][2] > 16, 'the player did not jump')
    require(abs(states['landed']['origin'][2] - walked['origin'][2]) < 1, 'the player did not land')
    require(lines.count('qslisp: jump') == 2, 'expected one jump per press, including a held press through landing')
    require(states['missed']['targets'] == 1 and states['missed']['rounds'] == 2,
            'a missed shot must spend one shell and leave the target intact')
    for name, rounds in (('cleared', 1), ('replay', 2)):
        require(states[name]['targets'] == 0 and states[name]['rounds'] == rounds,
                f'expected the hit to spend one shell and clear the target in {name}')
    require(states['reset'] == spawn, 'reset did not restore player position, ammo, and target')
    require(lines.count('qslisp: fired') == 3 and lines.count('qslisp: target hit') == 2,
            'expected one miss and one hit in the first round, then one hit after reset')
    require(all((output / f'quake0{i}.pcx').is_file() for i in range(2)), 'missing stock client screenshots')

    report = measured_profiles(lines, (output / 'progs.dat').read_bytes())
    report['movement'] = {'walk_distance': math.dist(spawn['origin'], walked['origin']),
                          'jump_height_sample': states['rise']['origin'][2] - walked['origin'][2]}
    (output / 'measurements.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2))
