"""Exercise a stock-engine sentry encounter with real client input."""
import json
import math

from challenge import read_edicts, require

SAVES = ('patrol', 'exposed', 'covered', 'safe', 'respawn', 'disabled', 'supplies',
         'pulse', 'switched', 'checked', 'dooropen', 'guarded', 'reset',
         'rtmoved', 'rtload', 'rtresume',
         'bkdock', 'bkstart', 'bksteer', 'bkgrip', 'bkfast', 'bkslide', 'bkrelay', 'bkpark', 'bkreload', 'bkresp')


def verification_commands():
    commands = ['host_framerate 0.05', 'con_notifytime 0', 'scr_centertime 0'] + ['wait'] * 82
    commands += ['save patrol', 'echo annex-first-exposure', '+moveleft'] + ['wait'] * 24
    commands += ['-moveleft', 'wait', 'save exposed', 'screenshot', '+moveright'] + ['wait'] * 24
    commands += ['-moveright'] + ['wait'] * 8 + ['save covered']
    commands += ['wait'] * 20 + ['save safe', '+moveleft'] + ['wait'] * 24
    commands += ['-moveleft'] + ['wait'] * 100 + ['save defeated', '+attack', 'wait', '-attack']
    commands += ['wait'] * 12 + ['save respawn', '+moveleft'] + ['wait'] * 23
    commands += ['-moveleft', '+attack'] + ['wait'] * 15 + ['-attack', 'wait', 'save disabled', '+forward']
    commands += ['wait'] * 39 + ['-forward'] + ['wait'] * 9
    commands += ['save supplies', 'impulse 2', 'wait', 'save pulse', '+attack', 'wait', '-attack']
    commands += ['wait'] * 5 + ['impulse 1', 'wait', 'save switched', 'kill']
    commands += ['wait'] * 12 + ['+attack', 'wait', '-attack']
    commands += ['wait'] * 12 + ['save checked', 'impulse 3']
    commands += ['wait'] * 14 + ['save dooropen', '+moveright'] + ['wait'] * 5
    commands += ['-moveright'] + ['wait'] * 24 + ['save guarded', 'restart']
    commands += ['wait'] * 35 + ['save reset'] + ['wait'] * 27 + ['save rtmoved', 'load reset']
    commands += ['wait'] * 14 + ['save rtload'] + ['wait'] * 21
    commands += ['save rtresume', 'load guarded'] + ['wait'] * 20
    commands += ['+moveleft'] + ['wait'] * 5 + ['-moveleft'] + ['wait'] * 10
    commands += ['+attack'] + ['wait'] * 16 + ['-attack', '+forward'] + ['wait'] * 15
    commands += ['-forward'] + ['wait'] * 12 + ['save bkdock', 'impulse 3'] + ['wait'] * 2
    commands += ['save bkstart', 'screenshot', '+left'] + ['wait'] * 9
    commands += ['-left', '+attack'] + ['wait'] * 5 + ['save bksteer', '+right'] + ['wait'] * 5
    commands += ['save bkgrip', '-right', '-attack', 'load bkstart'] + ['wait'] * 16
    commands += ['+attack'] + ['wait'] * 17
    commands += ['-attack', 'save bkfast', 'impulse 3', '+jump', '+left'] + ['wait'] * 7
    commands += ['save bkslide', 'screenshot', '-jump', '+attack'] + ['wait'] * 6 + ['-left'] + ['wait'] * 14
    commands += ['-attack', 'save bkrelay', '+jump'] + ['wait'] * 24
    commands += ['-jump', 'impulse 3'] + ['wait'] * 2 + ['save bkpark', 'load bkslide']
    commands += ['wait'] * 16 + ['save bkreload', 'kill'] + ['wait'] * 12
    commands += ['+attack', 'wait', '-attack'] + ['wait'] * 10 + ['save bkresp', 'toggleconsole', 'quit']
    return '\n'.join(commands) + '\n'


def state(path):
    entities = read_edicts(path)
    player = entities[1]
    sentry = next((entry for entry in entities if entry.get('classname') == 'qslisp_sentry'), None)
    guard = next((entry for entry in entities if entry.get('classname') == 'qslisp_guard'), None)
    gate = next(entry for entry in entities if entry.get('classname') == 'qslisp_gate')
    bike = next(entry for entry in entities if entry.get('classname') == 'qslisp_bike')
    relay = next(entry for entry in entities if entry.get('classname') == 'qslisp_bike_relay')
    camera = int(player.get('bike-camera', '0'))
    return {
        'player_origin': tuple(float(x) for x in player['origin'].split()),
        'player_health': int(float(player.get('health', '0'))),
        'rounds': int(float(player.get('ammo_shells', '0'))),
        'pulse_ammo': int(float(player.get('ammo_nails', '0'))),
        'display_ammo': int(float(player.get('currentammo', '0'))),
        'weapon': player.get('weaponmodel'),
        'player_model': player.get('model'),
        'player_frame': int(float(player.get('frame', '0'))),
        'checkpoint': int(player.get('checkpoint', '0')),
        'gate_open': int(float(gate.get('gate-open', '0'))),
        'guard_origin': tuple(float(x) for x in guard['origin'].split()) if guard else None,
        'guard_state': int(float(guard.get('sentry-state', '0'))) if guard else None,
        'sentry_origin': tuple(float(x) for x in sentry['origin'].split()) if sentry else None,
        'sentry_health': int(float(sentry.get('health', '0'))) if sentry else None,
        'sentry_state': int(float(sentry.get('sentry-state', '0'))) if sentry else None,
        'patrol_count': int(float(sentry.get('patrol-count', '0'))) if sentry else None,
        'patrol_route': [entities[int(sentry[f'patrol-route-{i}'])]['targetname']
                         for i in range(int(float(sentry.get('patrol-route-length', '0'))))] if sentry else None,
        'riding': int(player.get('riding', '0')),
        'bike_rider': int(bike.get('bike-rider', '0')),
        'bike_model': bike.get('model'),
        'bike_solid': int(float(bike.get('solid', '0'))),
        'bike_velocity': tuple(float(player.get(f'bike-v{axis}', '0')) for axis in 'xy'),
        'bike_heading': float(player.get('bike-heading', '0')),
        'view_yaw': float(player.get('v_angle', '0 0 0').split()[1]),
        'bike_camera': camera,
        'bike_view': int(player.get('bike-view', '0')),
        'camera_origin': tuple(float(x) for x in entities[camera]['origin'].split()) if camera else None,
        'bike_skidding': int(float(player.get('bike-skidding', '0'))),
        'bike_origin': tuple(float(x) for x in bike['origin'].split()),
        'bike_relay': int(float(relay.get('bike-relay-active', '0'))),
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
    supplies = states['supplies']
    require(supplies['player_health'] == 100 and supplies['rounds'] == 4 and
            supplies['pulse_ammo'] == 6 and supplies['checkpoint'] > 0,
            'health, ammo, weapon, or checkpoint pickup did not take effect')
    require(states['pulse']['weapon'] == 'progs/v_nail.mdl' and states['pulse']['display_ammo'] == 6 and
            states['switched']['weapon'] == 'progs/v_shot.mdl' and
            states['switched']['pulse_ammo'] == 5 and states['switched']['display_ammo'] == 4,
            'switching or firing the pulse weapon did not update separate ammo pools and HUD')
    require(states['checked']['player_health'] == 100 and states['checked']['player_origin'][0] == 158 and
            states['checked']['checkpoint'] == supplies['checkpoint'], 'respawn missed the active checkpoint')
    require(states['checked']['gate_open'] == 0 and states['dooropen']['gate_open'] == 2 and
            lines.count('qslisp: switch used') == 1, 'the authored switch did not open the service gate')
    require(states['guarded']['guard_state'] == 1 and 'qslisp: guard fired' in lines and
            states['guarded']['guard_origin'] == states['patrol']['guard_origin'],
            'the second actor did not defend its position after the service gate opened')
    require(states['reset']['player_health'] == 100 and states['reset']['rounds'] == 3 and
            states['reset']['sentry_health'] == 45 and states['reset']['sentry_state'] == 0 and
            states['reset']['checkpoint'] == states['reset']['gate_open'] == 0,
            'reset did not restore the sentry encounter')
    saved, moved, loaded, resumed = (states[name] for name in ('reset', 'rtmoved', 'rtload', 'rtresume'))
    require(saved['patrol_route'] == ['patrol_near', 'patrol_far'] and
            moved['patrol_route'] == ['patrol_far', 'patrol_near'] and
            moved['patrol_count'] == saved['patrol_count'] + 1,
            'patrol did not rotate away from the saved list')
    require(loaded['patrol_route'] == saved['patrol_route'] and loaded['patrol_count'] == saved['patrol_count'],
            'loading did not restore the Lisp route before reaching the saved waypoint')
    require(resumed['patrol_route'] == moved['patrol_route'] and resumed['patrol_count'] == moved['patrol_count'],
            'the saved Lisp route did not point the sentry to the next waypoint')
    require((output / 'quake00.pcx').is_file(), 'missing sentry screenshot')
    verify_bike(states, lines, output)
    (output / 'encounter.json').write_text(json.dumps(states, indent=2) + '\n', encoding='utf-8')


def verify_bike(states, lines, output):
    dock, start, fast, slide, relay, park, loaded, respawn = (
        states[name] for name in ('bkdock', 'bkstart', 'bkfast', 'bkslide', 'bkrelay', 'bkpark', 'bkreload', 'bkresp'))
    require(dock['bike_solid'] == 2 and dock['bike_model'] == 'progs/bike.mdl' and
            start['riding'] and start['bike_rider'] == 1 and start['bike_solid'] == 0 and
            start['player_model'] == 'progs/r_bike.mdl' and not start['weapon'] and
            start['bike_relay'] == 0,
            'the player did not mount the service bike at the dock')
    require(start['bike_camera'] > 1 and start['bike_view'] == start['bike_camera'] and
            start['camera_origin'][0] < start['player_origin'][0] - 65,
            'the mounted client did not get a separate world-space view behind the bike')
    steered, gripped = states['bksteer'], states['bkgrip']
    require(steered['view_yaw'] > 45 and steered['player_origin'][1] > start['player_origin'][1] + 10 and
            gripped['view_yaw'] < steered['view_yaw'] - 20,
            'the keyboard did not steer the stopped and rolling bike')
    for sample in (steered, gripped):
        vx, vy = sample['bike_velocity']
        bearing = math.degrees(math.atan2(vy, vx))
        require(sample['riding'] and not sample['bike_skidding'] and
                abs(sample['view_yaw'] - bearing) < 8 and abs(sample['view_yaw'] - sample['bike_heading']) < 6,
                'normal pedaling did not travel in the aim direction')
    require(steered['player_frame'] == 0 and 1 <= gripped['player_frame'] <= 3,
            'the world model did not show the handlebars turn right')
    vx, vy = slide['bike_velocity']
    motion_bearing = math.degrees(math.atan2(vy, vx))
    require(math.hypot(*fast['bike_velocity']) > 300 and fast['player_origin'][0] > start['player_origin'][0] + 140,
            'pedaling did not accelerate the bike down the approach')
    require(slide['bike_skidding'] == 1 and slide['bike_heading'] > 25 and 4 <= slide['player_frame'] <= 6 and
            slide['bike_view'] == slide['bike_camera'] and
            abs(motion_bearing - slide['bike_heading']) > 22 and
            100 < math.hypot(vx, vy) < math.hypot(*fast['bike_velocity']),
            'braking into the corner did not produce controlled sideways momentum')
    require(relay['bike_relay'] == 1 and relay['player_origin'][1] >= 332,
            'the rider did not reach and activate the relay around the corner')
    require(not park['riding'] and not park['bike_rider'] and not park['bike_camera'] and park['bike_solid'] == 2 and
            park['player_model'] == 'progs/player.mdl' and park['weapon'] == 'progs/v_shot.mdl' and
            math.dist(park['player_origin'], park['bike_origin']) >= 48,
            'dismount did not restore a parked bike and the player weapon')
    require(loaded['riding'] == slide['riding'] and loaded['bike_rider'] == 1 and loaded['bike_camera'] > 1 and
            loaded['bike_view'] == loaded['bike_camera'] and
            loaded['bike_solid'] == 0 and loaded['weapon'] == start['weapon'] and loaded['bike_relay'] == 0,
            'reloading a ride did not restore the mounted bike and previous relay state')
    require(respawn['player_health'] == 100 and not respawn['riding'] and not respawn['bike_rider'] and
            not respawn['bike_camera'] and
            respawn['bike_solid'] == 2 and respawn['bike_origin'] == dock['bike_origin'],
            'defeat and respawn did not release the bike at its parking spot')
    event = 0
    for message in ('qslisp: bike mounted', 'qslisp: bike rear-wheel slide',
                    'qslisp: bike relay online', 'qslisp: bike dismounted'):
        event = lines.index(message, event) + 1
    require((output / 'quake01.pcx').is_file(), 'missing mounted chase view screenshot')
    require((output / 'quake02.pcx').is_file(), 'missing brake slide chase view screenshot')
