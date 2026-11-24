"""Drive the Lambda Lab with the stock DOS client and inspect its saves."""
import math
import re

from challenge import read_edicts, require
import hud
from uplink import Client, edit, named, number, origin, player, serverflags, wait

EYE = 22


def aim(eye, target):
    """Yaw and downward pitch in degrees from an eye position to a target."""
    dx, dy, dz = (t - e for t, e in zip(target, eye))
    return math.degrees(math.atan2(dy, dx)), -math.degrees(math.atan2(dz, math.hypot(dx, dy)))


def write_angle(degrees):
    """Stock MSG_WriteAngle: ((int)degrees * 256 / 360) & 255. The cast truncates;
    measured in DOS Quake 1.08, the division then rounds negative values down."""
    return int(degrees) * 256 // 360 & 255


def read_angle(byte):
    return (byte - 256 if byte > 127 else byte) * 360 / 256


def sent(degrees):
    """The angle the server sees for a client view angle."""
    return read_angle(write_angle(degrees))


def spread(a, b):
    return abs((a - b + 180) % 360 - 180)


def view_for(target):
    """A client view angle whose transmitted value is closest to the target and
    stays the same for small timing errors in a scripted turn."""
    best = None
    for tenth in range(-60, 61):
        view = target + tenth / 10
        value = sent(view)
        if all(sent(view + jitter) == value for jitter in (-0.4, 0.4)):
            if best is None or spread(value, target) < spread(sent(best), target):
                best = view
    return best


def turn(yaw, pitch):
    """Rotate the stock client's view. A key held for one frame applies half its speed."""
    commands = []
    if abs(yaw) > 0.01:
        commands += [f'cl_yawspeed {abs(yaw) * 40}', '+left' if yaw > 0 else '+right', 'wait',
                     '-left' if yaw > 0 else '-right']
    if abs(pitch) > 0.01:
        commands += [f'cl_pitchspeed {abs(pitch) * 40}', '+lookdown' if pitch > 0 else '+lookup', 'wait',
                     '-lookdown' if pitch > 0 else '-lookup']
    return commands


def shot():
    return ['+attack', 'wait', '-attack', *wait(7)]


def placed_view(yaw, pitch):
    """The client view after a save load: the server sends svc_setangle."""
    return read_angle(write_angle(yaw)), read_angle(write_angle(pitch))


def aimed_shots(eye, targets, *, first):
    """Turn from the placed view to each target and fire once at it. The
    client's view is tracked exactly; only transmitted angles are quantized."""
    yaw, pitch = placed_view(*first)
    commands = []
    for target in targets:
        goal_yaw, goal_pitch = aim(eye, target) if target else (yaw, pitch - 40)
        next_yaw, next_pitch = view_for(goal_yaw), view_for(goal_pitch)
        delta = (next_yaw - yaw + 180) % 360 - 180
        commands += [*turn(delta, next_pitch - pitch), 'wait', *shot()]
        yaw, pitch = next_yaw, next_pitch
    return commands


def pad(x, y):
    return (x, y + 56, 28)


def entries(path, classname):
    return [entry for entry in read_edicts(path) if entry.get('classname') == classname]


def verify(dosbox, output, env, base, mod):
    client = Client(dosbox, output, env, base, mod, level='lambda')
    boot = client.run('boot', None, [*wait(80), 'save start', 'screenshot'])
    hud.verify_status_bar(mod / 'quake00.pcx')
    require('lambda: floyd found a cycle' in boot and 'lambda: tail door open' not in boot,
            'the drones did not detect the initial cycle or the tail door opened early')
    require(number(named(client.save('start'), 'c5'), 'lambda-head') == 1, 'the head cell was not spawned')

    client.place('start', 'atarmory', -830, -240, 25, 0)
    armory = client.run('armory', 'atarmory', ['+forward', *wait(60), '-forward', 'save armory'])
    items = int(number(player(client.save('armory')), 'items'))
    require(items & (2 | 16 | 32 | 64) == 2 | 16 | 32 | 64 and armory.count('collected') == 4,
            f'the hall pickups did not give all four Lisp weapons: items {items}')

    # Rewire the list from the balcony: c5 -> c2 -> c1 -> nil.
    eye = (-120, 0, 25 + EYE)
    yaw, pitch = aim(eye, pad(192, 0))
    client.place('armory', 'atbalc', -120, 0, 25, yaw, pitch)
    targets = [pad(192, 0), pad(832, -416), pad(832, -416), pad(1104, 0), pad(1104, 0), None]
    relink = client.run('relink', 'atbalc', ['impulse 2', *wait(3), *aimed_shots(eye, targets, first=(yaw, pitch)),
                                                *wait(10), 'save relinked'])
    require(relink.count('lambda: cdr rewired') == 3 and 'list: c5 c2 c1)' in relink
            and 'lambda: tail door open' in relink,
            'the linker did not splice, reverse, and terminate the list')
    require(number(named(client.save('relinked'), 'tail-door'), 'door-open') == 1, 'the tail door did not stay open')

    # Walk north into each pad, then east from the tail cell through its door.
    client.place('relinked', 'athead', 192, -40, 25, 90)
    walk = client.run('walk-list', 'athead', ['+forward', *wait(34), '-forward', *turn(-90, 0),
                                              '+forward', *wait(40), '-forward', 'save walked'])
    require(walk.count('lambda: followed cdr') == 2 and origin(client.save('walked'))[0] > 1300
            and int(number(player(client.save('walked')), 'items')) >= 0,
            'walking the rewired list did not reach the tail door corridor')
    require('lambda: rune collected' in walk and 'Primitive collected: cons' in walk, 'the cons rune was not collected')

    client.place('start', 'atbroken', 832, -456, 25, 90)
    client.run('broken-cell', 'atbroken', ['+forward', *wait(8), '-forward', *wait(30), 'save fell'])
    fell = player(client.save('fell'))
    x, y, _ = origin(client.save('fell'))
    require(abs(x + 120) < 40 and abs(y) < 40 and number(fell, 'health') == 90,
            'the broken cell did not drop the player into the pit and return them')

    client.place('start', 'atamb', 1792, 0, 25, 0)
    amb = client.run('amb-wrong', 'atamb', ['+forward', *wait(35), '-forward', *wait(4), 'save pruned'])
    barrier = named(client.save('pruned'), 'amb-0-0')
    x, _, _ = origin(client.save('pruned'))
    require('lambda: amb backtracked' in amb and number(barrier, 'solid') == 4 and x < 2000,
            'a wrong amb door did not backtrack and prune its branch')
    client.place('start', 'atambok', 2060, 160, 25, 0)
    client.run('amb-right', 'atambok', ['+forward', *wait(40), '-forward', 'save ambpass'])
    require(origin(client.save('ambpass'))[0] > 2304, 'the correct amb door did not lead on')

    client.place('start', 'atstack', 3264, 0, 25, 90)
    stack = client.run('stack-lift', 'atstack', ['impulse 10', *wait(200), 'save stackend'])
    lift = named(client.save('stackend'), 'stack-lift')
    require('lambda: stack lift overflowed' in stack and number(lift, 'lift-running') == 0
            and origin(client.save('stackend'))[2] < 100,
            'the stack lift did not overflow at depth eight and unwind')
    client.place('start', 'attail', 3456, 0, 25, 90)
    tail = client.run('tail-lift', 'attail', ['impulse 10', *wait(140), 'save taildone'])
    require('lambda: tail lift arrived' in tail and origin(client.save('taildone'))[2] > 760,
            'the tail-call lift did not carry the player to the arena')
    crates = [e for e in entries(client.save('taildone'), 'lambda_crate')]
    require(len(crates) == 1, f'the tail lift kept {len(crates)} crates instead of reusing one')

    # Mark-and-sweep a dog placed in front of the player.
    edit(client.save('armory'), client.save('dogfront'), [
        ('targetname', 'dog-east', {'origin': '3450 -250 24', 'oldorigin': '3450 -250 24'})])
    client.place('dogfront', 'atsweep', 3300, -250, 25, 0)
    sweep = client.run('sweep', 'atsweep', ['impulse 7', *wait(2), '+attack', *wait(4), '-attack',
                                            *wait(6), 'save swept'])
    require('weapon: marked' in sweep and 'weapon: swept' in sweep and 'lambda: dog defeated' in sweep
            and not named(client.save('swept'), 'dog-east'),
            'mark-and-sweep did not mark and sweep the dog')
    require(number(entries(client.save('swept'), 'lambda_stats')[0], 'lambda-killed') == 1, 'the kill was not counted')

    client.place('armory', 'atrico', 3200, -100, 25, 0)
    ricochet = client.run('ricochet', 'atrico', ['impulse 6', *wait(2), *shot(), *wait(20)])
    require('weapon: ricochet fired' in ricochet and 'weapon: ricochet bounced' in ricochet,
            'the ricochet bolt did not reflect off the lift hall wall')

    edit(client.save('armory'), client.save('dogcoil'), [
        ('targetname', 'dog-west', {'origin': '3400 150 24', 'oldorigin': '3400 150 24'})])
    eye = (3300, 250, 25 + EYE)
    yaw, pitch = aim(eye, (3400, 150, 30))
    client.place('dogcoil', 'atcoil', 3300, 250, 25, yaw, pitch)
    coil = client.run('coil', 'atcoil', ['god', 'impulse 2', *wait(3),
                                         *aimed_shots(eye, [(3400, 150, 30), (3500, 300, 48)], first=(yaw, pitch)),
                                         *wait(50), 'save coiled'])
    require('weapon: link source' in coil and 'weapon: hostile linked to coil' in coil
            and 'lambda: dog defeated' in coil, 'the coil did not destroy the linked dog')

    client.place('armory', 'atbeacon', -900, 0, 25, 0)
    client.run('beacon-throw', 'atbeacon', ['impulse 5', *wait(2), *shot(), *wait(20), 'save thrown'])
    thrown = player(client.save('thrown'))
    beacon = entries(client.save('thrown'), 'lambda_beacon')
    require(len(beacon) == 1 and int(number(thrown, 'items')) & 4194304, 'the beacon was not captured with the quad tint')
    bx, by, bz = map(float, beacon[0]['origin'].split())
    resume = client.run('beacon-resume', 'thrown', ['+back', *wait(10), '-back', *shot(), *wait(3), 'save resumed'])
    rx, ry, rz = origin(client.save('resumed'))
    require('weapon: continuation resumed' in resume and math.dist((rx, ry, rz), (bx, by, bz)) < 2
            and not int(number(player(client.save('resumed')), 'items')) & 4194304,
            'firing again did not return the player to the beacon')

    # eval is vulnerable while it calls apply; apply is inside the call.
    edit(client.save('armory'), client.save('bosses'), [
        ('targetname', 'eval', {'health': 30, 'boss-called': 0, 'boss-swap': 9999}),
        ('targetname', 'apply', {'health': 30, 'boss-called': 1, 'boss-swap': 9999})])
    eye = (3456, 200, 793 + EYE)
    yaw, pitch = aim(eye, (3612, 360, 800))
    client.place('bosses', 'atarena', 3456, 200, 793, yaw, pitch, ammo_shells=20, currentammo=20)
    boss = client.run('bosses', 'atarena', ['god', 'impulse 1', *wait(3), *shot(), 'save called',
                                            *aimed_shots(eye, [(3300, 360, 800), (3300, 360, 800),
                                                               (3612, 360, 800), (3612, 360, 800)],
                                                         first=(yaw, pitch)),
                                            *wait(4), 'save cleared'])
    require(number(named(client.save('called'), 'apply'), 'health') == 30, 'the called boss took damage')
    require(boss.count('lambda: boss defeated') == 2 and
            not any(e.get('classname') == 'lambda_boss_door' and e.get('solid') == '4.000000'
                    for e in read_edicts(client.save('cleared'))),
            'eval and apply did not fall in turn and open the arena door')

    eye = (3456, 560, 793 + EYE)
    yaw, pitch = aim(eye, (3800, 960, 832))
    client.place('armory', 'atgc', 3456, 560, 793, yaw, pitch)
    gc = client.run('collector', 'atgc', ['god', *wait(140), 'save gcfirst', 'impulse 2', *wait(3),
                                          *aimed_shots(eye, [(3800, 960, 832), (3800, 1120, 832),
                                                             (3800, 1120, 832), (3800, 1280, 832)],
                                                       first=(yaw, pitch)),
                                          *wait(200), 'save gcsecond'])
    first, second = client.save('gcfirst'), client.save('gcsecond')
    require(number(named(first, 'gc-3-deck'), 'solid') == 0 and number(named(first, 'gc-1-deck'), 'solid') == 4,
            'the collector did not sweep the unreachable platforms')
    require(gc.count('weapon: conduit linked') == 2 and number(named(second, 'gc-4-deck'), 'solid') == 4,
            'linking the conduits did not keep their platforms through the next sweep')

    client.place('start', 'atsecret', -672, -300, 25, 270)
    shrine = client.run('secret', 'atsecret', ['+forward', *wait(50), '-forward', 'save shrine'])
    require('lambda: secret found' in shrine and 'Primitive collected: quote' in shrine
            and number(entries(client.save('shrine'), 'lambda_stats')[0], 'lambda-found') == 1,
            'the illusory wall did not hide the shrine secret and its rune')
    client.place('shrine', 'atcons', -522, -900, 25, 270, 25)
    power = client.run('power-cycle', 'atcons', ['impulse 10', 'wait', 'save cycled'])
    # Saves hold a version, comment, 16 spawn parms, skill, map, and time before the 64 styles.
    styles = client.save('cycled').read_text(encoding='cp437').splitlines()[21:85]
    require('lambda: shrine power cycled' in power and styles[32] == 'a', 'the shrine console did not cycle its lights')

    client.place('start', 'atquine', -960, 200, 25, 180, 10)
    quine = client.run('quine', 'atquine', ['impulse 10', *wait(4)])
    require('(define-source-printer print-quine "quine.scm")' in quine and 'lambda: quine printed' in quine,
            'the quine sign did not print its own source')
    # Leave for the AI Winter. The loadout crosses the level change in spawn parms.
    # Stock changelevel appends to the command buffer, behind this script, so the
    # script issues the same command once the exit has requested it.
    client.place('armory', 'atexit', 3456, 1600, 793, 90)
    leave = client.run('exit', 'atexit', ['+forward', *wait(20), '-forward', 'changelevel winter',
                                          *wait(40), 'save winter'])
    arrived = player(client.save('winter'))
    require('lambda: exit' in leave and 'SpawnServer: winter' in leave
            and int(number(arrived, 'items')) & (2 | 16 | 32 | 64) == 2 | 16 | 32 | 64
            and number(arrived, 'ammo_cells') == 8 and serverflags(client.save('winter')) & 2,
            'the exit did not carry the loadout into the AI Winter')
    return output / 'boot.log'
