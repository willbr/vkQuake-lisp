"""Drive the AI Winter with the stock DOS client and inspect its saves."""
import math
import re

from challenge import read_edicts, require
from uplink import Client, edit, named, number, origin, player, wait

ALL_RUNES = 2032
# quote cons cond car cdr atom eq, as base-8 rune indices, oldest first.
RUNE_ORDER = 1 * 8**6 + 6 * 8**5 + 7 * 8**4 + 4 * 8**3 + 5 * 8**2 + 2 * 8 + 3


def serverflags(path):
    """The globals block precedes the edicts; stock saves flag serverflags there."""
    block = re.search(r'^\{\s*\n(.*?)^\}', path.read_text(encoding='cp437'), re.M | re.S)[1]
    return int(float(dict(re.findall(r'^"([^"]*)"\s+"([^"]*)"', block, re.M)).get('serverflags', 0)))


def slide(client, label, source, x, y):
    """Release the player at 300 units per second with no input; return the distance covered."""
    client.place(source, f'at{label}', x, y, 25, 0, velocity='300 0 0', **{'ice-vx': 300, 'ice-vy': 0})
    client.run(label, f'at{label}', [*wait(20), f'save {label}'])
    end_x, end_y, _ = origin(client.save(label))
    return math.hypot(end_x - x, end_y - y)


def verify(dosbox, output, env, base, mod):
    client = Client(dosbox, output, env, base, mod, level='winter')
    boot = client.run('boot', None, [*wait(40), 'save start', *wait(20), 'save later'])
    require('CL_SignonReply: 4' in boot, 'the AI Winter did not load')
    first, later = (float(named(client.save(name), 'fan-west')['angles'].split()[1]) for name in ('start', 'later'))
    require(abs(later - first) > 30, f'the fan did not spin: {first} -> {later}')
    require(number(named(client.save('start'), 'rune-gate'), 'solid') == 4, 'the rune gate opened without the runes')
    warm = player(client.save('later'))
    require(number(warm, 'armorvalue') > 60 and int(number(warm, 'items')) & 8192,
            'the warm hall did not fill the warmth gauge')

    snow = slide(client, 'snow', 'start', -950, -150)
    ice = slide(client, 'ice', 'start', -300, 0)
    require(ice > 2 * snow and ice > 150, f'ice did not keep the slide going: snow {snow:.0f}, ice {ice:.0f}')

    client.place('later', 'atcold', 500, 0, 25, 0, armorvalue=100)
    client.run('cold', 'atcold', [*wait(60), 'save cooled'])
    cooled = player(client.save('cooled'))
    require(number(cooled, 'armorvalue') < 80 and number(cooled, 'health') == 100,
            'the cold did not drain warmth before health')
    client.place('later', 'atfreeze', 500, 0, 25, 0, armorvalue=2)
    freeze = client.run('freeze', 'atfreeze', [*wait(60), 'save frozen'])
    frozen = player(client.save('frozen'))
    require('winter: player freezing' in freeze and number(frozen, 'health') < 100
            and int(number(frozen, 'items')) & 32768,
            'an empty warmth gauge did not freeze the player')

    client.place('start', 'atatom', 256, 570, 25, 90)
    client.run('atom', 'atatom', ['+forward', *wait(6), '-forward', 'save atom'])
    client.place('atom', 'ateq', 2048, -290, 9, 270)
    client.run('eq', 'ateq', ['+forward', *wait(6), '-forward', 'save eq'])
    flags = serverflags(client.save('eq'))
    require(flags & (32 | 64) == 32 | 64, f'the atom and eq runes were not collected: {flags}')

    edit(client.save('start'), client.save('allrunes'), [('serverflags', '0.000000', {'serverflags': ALL_RUNES})])
    client.place('allrunes', 'atgate', 2400, 0, 25, 0, **{'rune-order': RUNE_ORDER})
    finale = client.run('finale', 'atgate', [*wait(12), '+forward', *wait(50), '-forward', *wait(4), 'save finale'])
    require('winter: rune gate open' in finale and 'winter: episode complete' in finale,
            'all seven primitives did not open the gate to the exit')
    require('(define eval (lambda quote cons cond car cdr atom eq))' in finale,
            'the ending did not print the order the primitives were collected in')
    require(serverflags(client.save('finale')) & 4,
            'finishing the episode did not set its sigil')
    return output / 'boot.log'
