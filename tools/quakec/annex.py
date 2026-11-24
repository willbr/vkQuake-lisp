"""Exercise a stock-engine sentry encounter with real client input."""
import json
import math

from pathlib import Path
import subprocess
import sys

from challenge import read_edicts, require

SAVES = ('patrol', 'exposed', 'covered', 'safe', 'respawn', 'disabled', 'supplies',
         'pulse', 'switched', 'checked', 'dooropen', 'guarded', 'reset',
         'rtmoved', 'rtload', 'rtresume',
         'bkdock', 'bkstart', 'bkbrake', 'bkback', 'bkaim', 'bkpush', 'bksteer', 'bkgrip',
         'bkfast', 'bkslide', 'bksettle', 'bkrelay', 'bkdepot', 'bkjump1', 'bkland1',
         'bkjump2', 'bkair', 'bktouch', 'bkgripup', 'bkland2', 'bkentry', 'bkbank',
         'bkviewa', 'bkcurve', 'bkpark', 'bkupbase', 'bkup', 'bkwall', 'bkwmid',
         'bkwout', 'bkreload', 'bkresp')


def verification_commands():
    commands = ['host_framerate 0.05', 'con_notifytime 0', 'scr_centertime 0', '+mlook'] + ['wait'] * 82
    commands += ['save patrol', 'echo annex-first-exposure', '+moveleft'] + ['wait'] * 24
    commands += ['-moveleft', 'wait', 'save exposed', 'screenshot', '+moveright'] + ['wait'] * 24
    commands += ['-moveright'] + ['wait'] * 8 + ['save covered']
    commands += ['wait'] * 20 + ['save safe', '+moveleft'] + ['wait'] * 24
    commands += ['-moveleft'] + ['wait'] * 100 + ['save defeated', '+attack', 'wait', '-attack']
    commands += ['wait'] * 12 + ['save respawn', '+moveleft'] + ['wait'] * 23
    commands += ['-moveleft', '+attack'] + ['wait'] * 15 + ['-attack', 'wait', 'save disabled', '+forward']
    commands += ['wait'] * 39 + ['-forward'] + ['wait'] * 9
    commands += ['save supplies', 'impulse 3', 'wait', 'save pulse', '+attack', 'wait', '-attack']
    commands += ['wait'] * 5 + ['impulse 1', 'wait', 'save switched', 'kill']
    commands += ['wait'] * 12 + ['+attack', 'wait', '-attack']
    commands += ['wait'] * 12 + ['save checked', 'impulse 10']
    commands += ['wait'] * 14 + ['save dooropen', '+moveright'] + ['wait'] * 5
    commands += ['-moveright'] + ['wait'] * 24 + ['save guarded', 'restart']
    commands += ['wait'] * 35 + ['save reset'] + ['wait'] * 27 + ['save rtmoved', 'load reset']
    commands += ['wait'] * 14 + ['save rtload'] + ['wait'] * 21
    commands += ['save rtresume', 'load guarded'] + ['wait'] * 20
    commands += ['+moveleft'] + ['wait'] * 5 + ['-moveleft'] + ['wait'] * 10
    commands += ['+attack'] + ['wait'] * 16 + ['-attack', '+forward'] + ['wait'] * 15
    commands += ['-forward'] + ['wait'] * 12 + ['save bkdock', 'impulse 10'] + ['wait'] * 2
    commands += ['save bkstart', 'screenshot', '+attack 128'] + ['wait'] * 9
    # NetQuake appends client commands behind this cfg. Send the same button
    # and impulse as the Down binding while the scripted ride owns the queue.
    commands += ['-attack 128', '+jump 129', 'impulse 8'] + ['wait'] * 5 + ['save bkbrake']
    commands += ['wait'] * 24 + ['save bkback', '-jump 129', 'impulse 9', 'wait', 'load bkstart'] + ['wait'] * 16
    commands += ['+left'] + ['wait'] * 7 + ['-left', 'save bkaim', '+attack 128', 'wait', 'save bkpush']
    commands += ['wait'] * 8 + ['save bksteer', '+right'] + ['wait'] * 4
    commands += ['save bkgrip', '-right', '-attack 128', 'load bkstart'] + ['wait'] * 16
    commands += ['+attack'] + ['wait'] * 17
    commands += ['-attack', 'save bkfast', 'echo bike-particle-window', 'cl_shownet 2',
                 'impulse 10', '+jump', '+left'] + ['wait'] * 7
    commands += ['save bkslide', 'screenshot', '-jump', '+attack', 'wait', 'wait', 'save bksettle']
    commands += ['cl_shownet 0', 'echo bike-particle-end'] + ['wait'] * 4 + ['-left'] + ['wait'] * 14
    commands += ['save bkrelay', '+right'] + ['wait'] * 13 + ['-right', 'save bkdepot', 'screenshot']
    commands += ['wait'] * 11 + ['save bkjump1'] + ['wait'] * 7 + ['save bkland1']
    commands += ['wait'] * 12 + ['save bkjump2', 'screenshot', '+left']
    commands += ['wait'] * 5 + ['save bkair', 'echo landing-particle-window', 'cl_shownet 2']
    commands += ['wait'] * 3 + ['save bktouch'] + ['wait'] * 2
    commands += ['save bkgripup', 'cl_shownet 0', 'echo landing-particle-end']
    commands += ['wait'] * 4 + ['-left', 'save bkland2']
    commands += ['wait'] * 25 + ['save bkentry'] + ['wait'] * 8
    commands += ['save bkbank', '+left']
    commands += ['wait'] * 5 + ['save bkviewa', 'wait', 'save bkcurve', 'screenshot'] + ['wait'] * 8
    commands += ['-left', '-attack', '+jump'] + ['wait'] * 35
    commands += ['-jump', 'impulse 10'] + ['wait'] * 2
    # Revisit the bank at the play session's faster update rate.
    commands += ['save bkpark', 'host_framerate 0.013888889', 'load bkentry'] + ['wait'] * 14
    commands += ['+jump'] + ['wait'] * 69 + ['-jump', 'save bkupbase', '+attack']
    commands += ['wait'] * 40 + ['save bkup'] + ['wait'] * 115 + ['save bkwall', '+left']
    commands += ['wait'] * 35 + ['save bkwmid'] + ['wait'] * 65
    commands += ['save bkwout', '-left', '-attack', 'host_framerate 0.05', 'load bkslide']
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
    wire_yaw = math.trunc(math.trunc(float(player.get('bike-view-command-yaw', '0'))) * 256 / 360) * 1.40625
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
        'steering_yaw': float(player.get('bike-steer-yaw', '0')),
        'view_yaw': float(player.get('v_angle', '0 0 0').split()[1]),
        'bike_camera': camera,
        'bike_view': int(player.get('bike-view', '0')),
        'camera_origin': tuple(float(x) for x in entities[camera]['origin'].split()) if camera else None,
        'camera_yaw': float(player.get('bike-camera-yaw', '0')),
        'camera_yaw_offset': float(player.get('punchangle', '0 0 0').split()[1]),
        'camera_wire_yaw': wire_yaw,
        'camera_floor': float(player.get('bike-camera-floor', '0')),
        'camera_reach': float(player.get('bike-camera-reach', '0')),
        'bike_skidding': int(float(player.get('bike-skidding', '0'))),
        'bike_slip': float(player.get('bike-slip', '0')),
        'bike_bank': float(player.get('bike-bank', '0')),
        'bike_bank_contact': bool(float(player.get('bike-bank-contact', '0'))),
        'bike_contact_grip': float(player.get('bike-contact-grip', '0')),
        'bike_front_angle': float(player.get('bike-front-angle', '0')),
        'bike_pitch': float(player.get('bike-pitch', '0')),
        'bike_air_time': float(player.get('bike-air-time', '0')),
        'landing_dust_until': float(player.get('bike-landing-dust-until', '0')),
        'bike_next_dust': float(player.get('bike-next-dust', '0')),
        'client_horizontal_speed': tuple(float(x) for x in player.get('velocity', '0 0 0').split()[:2]),
        'vertical_speed': float(player.get('velocity', '0 0 0').split()[2]),
        'grounded': bool(int(float(player.get('flags', '0'))) & 512),
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
    require(states['pulse']['weapon'] == 'progs/v_pulse.mdl' and states['pulse']['display_ammo'] == 6 and
            states['switched']['weapon'] == 'progs/v_lshot.mdl' and
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
    def yaw_delta(current, previous):
        return (current - previous + 180) % 360 - 180

    dock, start, fast, slide, relay, park, loaded, respawn = (
        states[name] for name in ('bkdock', 'bkstart', 'bkfast', 'bkslide', 'bkrelay', 'bkpark', 'bkreload', 'bkresp'))
    require(dock['bike_solid'] == 2 and dock['bike_model'] == 'progs/bike.mdl' and
            start['riding'] and start['bike_rider'] == 1 and start['bike_solid'] == 0 and
            start['player_model'] == 'progs/r_bike.mdl' and not start['weapon'] and
            start['bike_relay'] == 0,
            'the player did not mount the service bike at the dock')
    require(start['bike_camera'] > 1 and start['bike_view'] == start['bike_camera'] and
            start['camera_origin'][0] < start['player_origin'][0] - 140 and
            abs(start['camera_origin'][1] - start['player_origin'][1]) < 2 and
            start['camera_origin'][2] > start['player_origin'][2] + 44,
            'the mounted client did not get a raised chase view behind the bike')
    brake, reverse = states['bkbrake'], states['bkback']
    require(brake['bike_velocity'][0] > 40 and reverse['bike_velocity'][0] < -60 and
            reverse['player_origin'][0] < brake['player_origin'][0] - 30,
            'Down did not brake first and then back the bike up')
    aim, push = states['bkaim'], states['bkpush']
    require(aim['steering_yaw'] > 30 and aim['player_frame'] >= 4 and
            abs(aim['camera_yaw'] - start['camera_yaw']) < 1 and
            abs(aim['bike_heading'] - start['bike_heading']) < 1 and
            abs(push['bike_heading'] - aim['bike_heading']) < 3 and push['bike_velocity'][0] > 0,
            'turning the view at the dock snapped the bike heading')
    steered, gripped = states['bksteer'], states['bkgrip']
    require(steered['steering_yaw'] > 30 and steered['player_origin'][1] > start['player_origin'][1] + 12 and
            gripped['steering_yaw'] < steered['steering_yaw'] - 20,
            'the keyboard did not steer the stopped and rolling bike')
    for sample in (steered, gripped):
        vx, vy = sample['bike_velocity']
        bearing = math.degrees(math.atan2(vy, vx))
        require(sample['riding'] and not sample['bike_skidding'] and
                abs(sample['steering_yaw'] - bearing) < 19 and
                abs(sample['steering_yaw'] - sample['bike_heading']) < 14,
                'the bike did not come around toward the riding direction')
    require(1 <= gripped['player_frame'] <= 3,
            'the world model did not show the handlebars turn right')
    vx, vy = slide['bike_velocity']
    motion_bearing = math.degrees(math.atan2(vy, vx))
    require(math.hypot(*fast['bike_velocity']) > 300 and fast['player_origin'][0] > start['player_origin'][0] + 140,
            'pedaling did not accelerate the bike down the approach')
    require(fast['client_horizontal_speed'] == (0, 0),
            'the client received walking camera velocity while riding')
    require(slide['bike_skidding'] == 1 and slide['bike_heading'] > 25 and 4 <= slide['player_frame'] <= 6 and
            slide['bike_view'] == slide['bike_camera'] and
            abs(motion_bearing - slide['bike_heading']) > 22 and
            0.74 < math.hypot(vx, vy) / math.hypot(*fast['bike_velocity']) < 1,
            'braking into the corner did not produce controlled sideways momentum')
    settle = states['bksettle']
    settle_bearing = math.degrees(math.atan2(settle['bike_velocity'][1], settle['bike_velocity'][0]))
    require(0 < settle['bike_slip'] < slide['bike_slip'] and settle['bike_skidding'] == 1 and
            abs(settle_bearing - settle['bike_heading']) > 16 and relay['bike_slip'] == 0,
            'brake release did not ease the bike from a slide back to normal grip')
    start_particles = lines.index('bike-particle-window')
    end_particles = lines.index('bike-particle-end', start_particles)
    require(fast['bike_next_dust'] == 0 and slide['bike_next_dust'] > 0 and
            sum('svc_particle' in line for line in lines[start_particles:end_particles]) >= 2,
            'braking did not send rear-wheel dust and smoke to the stock client')
    require(8 < slide['bike_heading'] - slide['camera_yaw'] < 24 and
            8 < slide['steering_yaw'] - slide['bike_heading'] < 24,
            'the chase heading did not ease around the brake slide')
    require(any(s['camera_yaw_offset'] for s in (slide, settle, relay)) and
            all(abs(yaw_delta(s['camera_wire_yaw'] + s['camera_yaw_offset'], s['camera_yaw'])) < 0.12
                for s in (slide, settle, relay)),
            'the stock client yaw and its visual offset did not reconstruct the smooth camera heading')
    require(relay['bike_relay'] == 1 and relay['player_origin'][1] >= 332,
            'the rider did not reach and activate the relay around the corner')
    depot = states['bkdepot']
    require(depot['riding'] and depot['player_origin'][1] > 540 and math.hypot(*depot['bike_velocity']) > 220,
            'the bike could not continue at speed into the depot beyond the relay')
    for jump_name, land_name, lip in (('bkjump1', 'bkland1', 1152), ('bkjump2', 'bkland2', 1472)):
        jump, landing = states[jump_name], states[land_name]
        require(jump['riding'] and not jump['grounded'] and jump['player_origin'][2] > 52 and
                jump['player_origin'][0] > lip + 20 and landing['grounded'] and
                landing['player_origin'][2] < 30 and landing['player_origin'][0] > jump['player_origin'][0] + 95,
                f'the bike did not take off and land across the ramp at x={lip}')
    first_jump, second_jump = states['bkjump1'], states['bkjump2']
    require(abs(first_jump['steering_yaw'] - second_jump['steering_yaw']) < 2 and
            abs(second_jump['view_yaw'] - second_jump['camera_wire_yaw']) < 3,
            'the camera fed its own rotation back into the steering')
    air, touch, grip = (states[name] for name in ('bkair', 'bktouch', 'bkgripup'))
    require(not air['grounded'] and air['bike_contact_grip'] == 0 and air['bike_front_angle'] > 15 and
            abs(yaw_delta(air['bike_heading'], second_jump['bike_heading'])) < 1 and
            touch['grounded'] and touch['bike_contact_grip'] == 0 and
            0 < grip['bike_contact_grip'] < 1 and
            4 < yaw_delta(grip['bike_heading'], touch['bike_heading']) < 13 and
            0 < abs(grip['bike_pitch']) < abs(touch['bike_pitch']),
            'the wheel did not steer in the air and regain grip progressively on touchdown')
    landing_start = lines.index('landing-particle-window')
    landing_end = lines.index('landing-particle-end', landing_start)
    require(air['bike_air_time'] > 0.1 and touch['bike_air_time'] == 0 and
            air['landing_dust_until'] < touch['landing_dust_until'] == grip['landing_dust_until'] and
            any('svc_particle' in line for line in lines[landing_start:landing_end]),
            'touchdown did not send a dust puff to the stock client')
    entry, bank, curve = (states[name] for name in ('bkentry', 'bkbank', 'bkcurve'))
    require(entry['bike_bank_contact'] and entry['player_origin'][1] < 1220 and
            all(sample['bike_bank_contact'] and sample['grounded'] for sample in (bank, curve)) and
            bank['player_origin'][2] > entry['player_origin'][2] + 25 and
            math.hypot(*bank['bike_velocity']) > 300 and
            curve['riding'] and curve['player_origin'][2] > bank['player_origin'][2] and
            abs(curve['bike_bank']) > 8 and
            curve['bike_heading'] > bank['bike_heading'] + 20,
            'the bike did not climb and turn on the bank')
    before = states['bkviewa']
    require(all(sample['bike_view'] == sample['bike_camera'] == start['bike_camera']
                for sample in (bank, before, curve)) and
            math.dist(before['camera_origin'], curve['camera_origin']) < 48 and
            abs(before['camera_floor'] - curve['camera_floor']) < 14,
            'the chase view jumped on the bank')
    climb_start, climb = states['bkupbase'], states['bkup']
    require(climb_start['bike_bank_contact'] and climb['bike_bank_contact'] and
            math.hypot(*climb_start['bike_velocity']) < 25 and math.hypot(*climb['bike_velocity']) > 120 and
            climb['player_origin'][2] > climb_start['player_origin'][2] + 8,
            'the stopped bike could not pedal up the bank')
    wall, wall_mid, wall_out = (states[name] for name in ('bkwall', 'bkwmid', 'bkwout'))
    require(wall['bike_bank_contact'] and wall['player_origin'][1] > 1550 and
            math.hypot(*wall['bike_velocity']) < 20 and
            yaw_delta(wall_mid['bike_heading'], wall['bike_heading']) > 35 and
            yaw_delta(wall_out['bike_heading'], wall_mid['bike_heading']) > 15 and
            wall_out['player_origin'][0] < wall['player_origin'][0] - 50 and
            math.hypot(*wall_out['bike_velocity']) > 80,
            'holding Left with the bike against the bank wall did not steer it clear')
    require(not park['riding'] and not park['bike_rider'] and not park['bike_camera'] and park['bike_solid'] == 2 and
            park['player_model'] == 'progs/player.mdl' and park['weapon'] == 'progs/v_lshot.mdl' and
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
    require((output / 'quake03.pcx').is_file(), 'missing depot riding screenshot')
    require((output / 'quake04.pcx').is_file(), 'missing jump screenshot')
    require((output / 'quake05.pcx').is_file(), 'missing bank screenshot')


def verify_restarts(dosbox, output, env, base, mod):
    """A sentry route with five waypoints parks the sentry with restarts
    instead of ending the server. Check retry, skip, and abort."""
    from map_editor import MapDocument
    from uplink import Client, named, number, wait

    document = MapDocument((Path(__file__).resolve().parents[2] / 'examples/annex.map').read_text(encoding='ascii'))
    far = next(i for i in range(len(document.entities)) if document.value(i, 'targetname') == 'patrol_far')
    document.set(far, 'target', 'patrol_3')
    for index, (x, after) in enumerate(((100, 'patrol_4'), (130, 'patrol_5'), (150, 'patrol_near')), 3):
        document.add_entity({'classname': 'qslisp_waypoint', 'origin': f'{x} 150 16',
                             'targetname': f'patrol_{index}', 'target': after})
    source = output / 'restarts.map'
    source.write_text(document.text, encoding='ascii')
    with (output / 'restarts-build.log').open('w') as log:
        subprocess.run([sys.executable, Path(__file__).with_name('build-signal.py'), '--source', source,
                        mod / 'maps/restarts.bsp'], stdout=log, stderr=subprocess.STDOUT, check=True)
    client = Client(dosbox, output, env, base, mod, level='restarts')
    parked = client.run('restart-park', None, [*wait(70), 'save parked'])
    sentry = next(e for e in read_edicts(client.save('parked')) if e.get('classname') == 'qslisp_sentry')
    require('actor: condition signaled' in parked and 'more than four waypoints' in parked
            and sentry.get('actor-parked') == 'parked' and sentry.get('think') == 'actor-remind',
            'a five-waypoint route did not park the sentry with restarts')
    # Loading a save first spawns the map's own entities for a few frames, so
    # only the console after each restart counts.
    retry = client.run('restart-retry', 'parked', ['impulse 26', *wait(10)])
    require('actor: restart retry' in retry
            and 'actor: condition signaled' in retry.split('actor: restart retry', 1)[1],
            'retry did not run the failing step again')
    skip = client.run('restart-skip', 'parked', ['impulse 27', *wait(10), 'save skipped'])
    sentry = next(e for e in read_edicts(client.save('skipped')) if e.get('classname') == 'qslisp_sentry')
    require('actor: restart skip' in skip
            and 'actor: condition signaled' not in skip.split('actor: restart skip', 1)[1]
            and sentry.get('think') == 'sentry-think' and number(sentry, 'patrol-route-length') == 4,
            'skip did not resume the sentry on its first four waypoints')
    abort = client.run('restart-abort', 'parked', ['impulse 28', *wait(4), 'save aborted'])
    require('actor: restart abort' in abort and
            not any(e.get('classname') == 'qslisp_sentry' for e in read_edicts(client.save('aborted'))),
            'abort did not remove the parked sentry')
