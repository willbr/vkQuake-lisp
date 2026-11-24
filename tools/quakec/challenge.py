"""Drive the original local client and check the Signal Room's observable state."""
import json
import math
import re
import struct

SAVES = ('spawned', 'walked', 'rise', 'landed', 'missed', 'locksave', 'cleared',
         'lockload', 'reopened', 'openload', 'finished', 'reset', 'replay')
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
    commands += ['save locksave']
    commands += profile('shot', ['+attack'])
    commands += ['-attack'] + ['wait'] * 12 + ['save cleared', 'screenshot', 'load locksave']
    commands += ['wait'] * 35 + ['save lockload', '+attack', 'wait', '-attack']
    commands += ['wait'] * 12 + ['save reopened', 'restart']
    commands += ['wait'] * 35 + ['load cleared']
    commands += ['wait'] * 35 + ['save openload', '+forward']
    commands += ['wait'] * 45 + ['-forward', 'wait', 'save finished', 'restart']
    commands += ['wait'] * 35 + ['save reset']
    commands += profile('combined', ['+jump', '+attack'])
    commands += ['-attack', '-jump'] + ['wait'] * 25
    commands += ['save replay', '+forward'] + ['wait'] * 55
    commands += ['-forward', 'wait', 'echo annex-transition-request', 'impulse 10', 'wait', 'wait']
    return '\n'.join(commands) + '\n'


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def read_edicts(path):
    text = path.read_text(encoding='cp437')
    blocks = re.findall(r'^\{\s*\n(.*?)^\}', text, flags=re.M | re.S)
    require(len(blocks) >= 3, f'missing player edict in {path.name}')
    return [dict(re.findall(r'^"([^"]*)"\s+"([^"]*)"', block, re.M)) for block in blocks[1:]]


def save_state(path):
    entities = read_edicts(path)
    player = entities[1]
    gate, = (ent for ent in entities if ent.get('classname') == 'qslisp_gate')
    exit_trigger, = (ent for ent in entities if ent.get('classname') == 'qslisp_exit')
    return {
        'origin': tuple(float(x) for x in player['origin'].split()),
        'rounds': int(float(player['ammo_shells'])),
        'weapon': player.get('weaponmodel'),
        'targets': sum(ent.get('classname') == 'qslisp_target' for ent in entities),
        'gate_open': int(float(gate.get('gate-open', '0'))),
        'gate_solid': int(float(gate.get('solid', '0'))),
        'complete': int(float(exit_trigger.get('room-complete', '0'))),
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
    require(spawn['rounds'] == 3 and spawn['weapon'] == 'progs/v_lshot.mdl' and spawn['targets'] == 1,
            'player did not start with a weapon, three shells, and a target')
    for name in ('spawned', 'missed', 'locksave', 'lockload', 'reset'):
        state = states[name]
        require((state['gate_open'], state['gate_solid'], state['complete']) == (0, 4, 0),
                f'{name} gate must block the exit')
    require(walked['origin'][0] - spawn['origin'][0] > 32, 'forward input did not move the player')
    require(states['rise']['origin'][2] - walked['origin'][2] > 16, 'the player did not jump')
    require(abs(states['landed']['origin'][2] - walked['origin'][2]) < 1, 'the player did not land')
    require(lines.count('qslisp: jump') == 2, 'expected one jump per press, including a held press through landing')
    require(states['missed']['targets'] == 1 and states['missed']['rounds'] == 2,
            'a missed shot must spend one shell and leave the target intact')
    for name, rounds in (('cleared', 1), ('reopened', 1), ('openload', 1), ('replay', 2)):
        require(states[name]['targets'] == 0 and states[name]['rounds'] == rounds,
                f'expected the hit to spend one shell and clear the target in {name}')
        state = states[name]
        require((state['gate_open'], state['gate_solid'], state['complete']) == (2, 0, 0),
                f'{name} gate should be open with the exit still ahead')
    require(states['finished']['origin'][0] > 224 and states['finished']['complete'] == 1,
            'walking through the gate did not complete the level')
    require(states['lockload'] == states['locksave'] and states['openload'] == states['cleared'],
            'stock load did not restore ammo, position, model, target, and gate state')
    require(lines.count('qslisp: gate open') == 3 and lines.count('qslisp: level complete') == 2,
            'expected three gate openings and two exit callbacks')
    transition = lines.index('SpawnServer: annex')
    require('CL_SignonReply: 4' in lines[transition:], 'the local client did not enter Relay Annex')
    require(states['reset'] == spawn, 'reset did not restore player position, ammo, and target')
    require(lines.count('qslisp: fired') == 4 and lines.count('qslisp: target hit') == 3,
            'expected one miss, the initial hit, and a hit after each restore or reset of the target')
    require(all((output / f'quake0{i}.pcx').is_file() for i in range(2)), 'missing stock client screenshots')

    report = measured_profiles(lines, (output / 'progs.dat').read_bytes())
    report['movement'] = {'walk_distance': math.dist(spawn['origin'], walked['origin']),
                          'jump_height_sample': states['rise']['origin'][2] - walked['origin'][2]}
    (output / 'measurements.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2))
