"""Exercise a stock-engine sentry encounter with real client input."""
import json

from challenge import read_edicts, require

SAVES = ('patrol', 'exposed', 'covered', 'safe', 'respawn', 'disabled', 'reset')


def verification_commands():
    commands = ['host_framerate 0.05', 'con_notifytime 0'] + ['wait'] * 82
    commands += ['save patrol', 'echo annex-first-exposure', '+moveleft'] + ['wait'] * 24
    commands += ['-moveleft', 'wait', 'save exposed', 'screenshot', '+moveright'] + ['wait'] * 24
    commands += ['-moveright'] + ['wait'] * 8 + ['save covered']
    commands += ['wait'] * 20 + ['save safe', '+moveleft'] + ['wait'] * 24
    commands += ['-moveleft'] + ['wait'] * 100 + ['save defeated', '+attack', 'wait', '-attack']
    commands += ['wait'] * 12 + ['save respawn', '+moveleft'] + ['wait'] * 23
    commands += ['-moveleft', '+attack'] + ['wait'] * 15 + ['-attack', 'wait', 'save disabled', 'map annex']
    commands += ['wait'] * 35 + ['save reset', 'toggleconsole', 'quit']
    return '\n'.join(commands) + '\n'


def state(path):
    entities = read_edicts(path)
    player = entities[1]
    sentry = next((entry for entry in entities if entry.get('classname') == 'qslisp_sentry'), None)
    return {
        'player_origin': tuple(float(x) for x in player['origin'].split()),
        'player_health': int(float(player.get('health', '0'))),
        'rounds': int(float(player.get('ammo_shells', '0'))),
        'sentry_origin': tuple(float(x) for x in sentry['origin'].split()) if sentry else None,
        'sentry_health': int(float(sentry.get('health', '0'))) if sentry else None,
        'sentry_state': int(float(sentry.get('sentry-state', '0'))) if sentry else None,
        'patrol_count': int(float(sentry.get('patrol-count', '0'))) if sentry else None,
    }


def verify_annex(output, lines):
    states = {name: state(output / f'{name}.sav') for name in SAVES}
    exposure = lines.index('annex-first-exposure')
    require('qslisp: sentry spotted player' not in lines[:exposure], 'sentry detected player through cover')
    require(states['patrol']['patrol_count'] >= 1 and states['patrol']['sentry_state'] == 0,
            'sentry did not patrol while the player was behind cover')
    require(states['exposed']['sentry_state'] in (1, 2), 'sentry did not react to an exposed player')
    require('qslisp: sentry chasing' in lines,
            'sentry did not transition from alert to chase')
    require(states['covered']['sentry_state'] == states['safe']['sentry_state'] == 0 and
            states['covered']['player_health'] == states['safe']['player_health'] > 0,
            'sentry continued attacking through cover')
    defeat = lines.index('qslisp: player defeated')
    refusal = lines.index("Can't savegame with a dead player", defeat)
    lines.index('qslisp: player respawned', refusal)
    require(states['respawn']['player_health'] == 100 and states['respawn']['rounds'] == 3 and
            states['respawn']['player_origin'] == states['patrol']['player_origin'] and
            'qslisp: player respawned' in lines, 'respawn did not restore health, ammo, and position')
    require(states['disabled']['sentry_health'] is None and 'qslisp: sentry defeated' in lines,
            'player fire did not defeat the sentry')
    require(states['reset']['player_health'] == 100 and states['reset']['rounds'] == 3 and
            states['reset']['sentry_health'] == 45 and states['reset']['sentry_state'] == 0,
            'reset did not restore the sentry encounter')
    require((output / 'quake00.pcx').is_file(), 'missing sentry screenshot')
    (output / 'encounter.json').write_text(json.dumps(states, indent=2) + '\n', encoding='utf-8')
