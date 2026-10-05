import copy
import hashlib
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools/acceptance'))
sys.path.insert(0, str(ROOT / 'tests'))
import demo
import device_controls as controls
from test_evolution_device import EvolutionDeviceContracts

OUT = Path(__file__).resolve().parent
SNAPS = OUT / 'snapshots'
SNAPS.mkdir(exist_ok=True)
SOURCE_FILES = [
    ROOT / 'tools/acceptance/device_controls.py',
    ROOT / 'tools/acceptance/device_renderer.js',
    ROOT / 'tests/test_evolution_device.py',
]

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def raw_summary(device):
    state = device.state or {}
    bench = state.get('bench') or []
    board = state.get('board') or []
    return {
        'sid': device.sid,
        'ruleset': state.get('ruleset'),
        'save_sequence': (state.get('save') or {}).get('sequence'),
        'gold': (state.get('you') or {}).get('gold'),
        'round': state.get('round'),
        'bench_count': len([p for p in bench if p]),
        'bench': [
            {'name': p.get('name'), 'sid': p.get('sid'), 'uid': p.get('uid'),
             'item': p.get('item'), 'technique': (p.get('technique') or {}).get('id'),
             'evolution_locked': bool((p.get('evolution') or {}).get('locked')),
             'can_evolve': bool((p.get('evolution') or {}).get('can_evolve'))}
            for p in bench if p
        ],
        'board_count': sum(1 for row in board for cell in row if cell),
        'board_species': [p.get('name') for row in board for cell in row if cell for p in [cell]],
    }

def screen_summary(result):
    screen = result.get('screen') or {}
    active = screen.get('active') or {}
    preview = screen.get('evolution_preview') or {}
    return {
        'page': screen.get('page'), 'selected_index': screen.get('selected'),
        'selected_label': active.get('label'), 'message': screen.get('message'),
        'detail_page': screen.get('detail_page'), 'detail_total': screen.get('detail_total'),
        'merge_count': len(preview.get('merges') or []),
        'confirm_prompt': screen.get('prompt'),
    }

class Recorder:
    def __init__(self, case, name):
        self.case, self.name, self.events, self.snapshots = case, name, [], []
        self.event_no = 0
        self.snapshot_no = 0
        self.before = raw_summary(case.device)
        self.last_result = case.state

    def input(self, phase, key=None, **extra):
        case = self.case
        case.t += .15
        params = {'phase': phase, 'device_id': case.device_id, **extra}
        if key is not None:
            params['key'] = key
        result = controls.api_input(params, now=case.t)
        assert result['ok'], result
        case.device_id = result['device_id']
        case.state = result
        self.event_no += 1
        after = raw_summary(case.device)
        event = {
            'n': self.event_no,
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'test_clock': case.t,
            'phase': phase,
            'key': key,
            'intent': extra.get('intent'),
            'before': self.before,
            'after': after,
            'screen': screen_summary(result),
            'result_sequence': result.get('sequence'),
            'sleeping': result.get('sleeping'),
            'busy': result.get('busy'),
        }
        self.events.append(event)
        self.before = after
        self.last_result = result
        return result

    def click(self, key, intent=None):
        self.input('down', key, intent=intent or f'press {key}')
        return self.input('up', key, intent=intent or f'release {key}')

    def long(self, key, seconds=.7, intent=None):
        case = self.case
        self.input('down', key, intent=(intent or f'long press {key}') + ': down')
        case.t += seconds - .15
        result = self.input('tick', intent=(intent or f'long press {key}') + ': held past threshold')
        self.input('up', key, intent=(intent or f'long press {key}') + ': release')
        return result

    def choose(self, label, intent=None):
        device = self.case.device
        labels = [r['label'] for r in device.rows()]
        target = next((i for i, value in enumerate(labels) if label in value), None)
        assert target is not None, (label, device.page, labels)
        while device.selected != target:
            self.click('B' if device.selected < target else 'A',
                       intent=f'move selection toward {label}')
        return self.click('C', intent=intent or f'activate {label}')

    def note(self, text, **data):
        self.events.append({'n': self.event_no, 'timestamp': datetime.now(timezone.utc).isoformat(),
                            'test_clock': self.case.t, 'note': text, **data})

    def snapshot(self, reason):
        self.snapshot_no += 1
        name = f'{self.name}-{self.snapshot_no:02d}-{reason}.json'
        payload = {
            'reason': reason, 'captured_at': datetime.now(timezone.utc).isoformat(),
            'test_clock': self.case.t, 'screen': self.last_result,
            'session': raw_summary(self.case.device),
        }
        (SNAPS / name).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n')
        self.snapshots.append(name)
        self.note(f'saved snapshot {name}')
        return name

    def save(self):
        path = OUT / f'{self.name}.json'
        path.write_text(json.dumps({
            'scenario': self.name,
            'generated_at': datetime.now(timezone.utc).isoformat(),
            'events': self.events,
            'snapshots': self.snapshots,
        }, ensure_ascii=False, indent=2) + '\n')
        return path

def new_case():
    case = EvolutionDeviceContracts('test_renderer_evolution_text_and_native_canvas_bounds')
    case.setUp()
    case.input = lambda *args, **kwargs: None
    return case

# The bound test helper is replaced after setUp; all subsequent gestures go through Recorder.
case = new_case()
rec = Recorder(case, 'auto-inheritance-cancel-commit')
rec.input('state', intent='open isolated device session')
for label in ('战术远征', '主搭档', '喷火龙', '出发', '确认'):
    rec.choose(label)
assert case.device.state['ruleset'] == 'tactics_v5'
rec.snapshot('tactical-v5-prep')
session = demo.SESSIONS[case.device.sid]
for old in session.player.shop.slots:
    if old is not None:
        session.pool.put(old)
session.player.shop.slots = [7] * 4
for _ in range(4):
    session.pool.take(7)
session.player.gold = 50
assert demo.api_action({'cmd': 'save', 'sid': session.sid})['ok']
rec.input('state', intent='refresh after evidence shop pin')
rec.note('fixture pinned all four shop slots to Squirtle sid=7 in isolated save storage')
for _ in range(2):
    rec.choose('商店'); rec.choose('杰尼龟')
first = session.player.bench[0]
first.item = 'leftovers'
first.technique = 'surf'
assert demo.api_action({'cmd': 'save', 'sid': session.sid})['ok']
rec.input('state', intent='refresh after attaching inherited item and technique')
rec.snapshot('two-materials-before-preview')
seq, gold = case.device.sequence, case.device.state['you']['gold']
rec.choose('商店'); rec.choose('杰尼龟', intent='open buy evolution preview')
assert case.device.page == 'evolution_buy'
preview = case.state['screen']['evolution_preview']
merge = preview['merges'][0]
assert (merge['from_sid'], merge['to_sid']) == (7, 8)
assert merge['source_uids'][0] == first.uid
assert merge['inherit_item'] == 'leftovers' and merge['inherit_technique'] == 'surf'
rec.snapshot('buy-evolution-preview')
rec.long('C', intent='read full evolution preview')
assert case.device.page == 'detail'
rec.snapshot('buy-evolution-full-detail')
rec.click('C', intent='leave full detail back to preview')
rec.choose('购买并进化', intent='open automatic evolution confirmation')
assert case.device.page == 'confirm' and case.device.selected == 0
rec.snapshot('auto-confirm-default-cancel')
rec.click('C', intent='physically release default cancel')
assert case.device.sequence == seq and len(session.player.bench) == 2
rec.snapshot('auto-cancel-zero-resource-change')
rec.choose('购买并进化'); rec.choose('确认', intent='commit buy and automatic evolution')
assert case.device.sequence == seq + 1 and case.device.state['you']['gold'] == gold - 1
assert len(session.player.bench) == 1
evolved = session.player.bench[0]
assert (evolved.piece.species_id, evolved.item, evolved.technique, evolved.uid) == (
    8, 'leftovers', 'surf', merge['result_uid'])
rec.snapshot('auto-evolution-committed')
rec.input('down', 'C', intent='begin duplicate release attempt')
rec.input('up', 'C', intent='duplicate release must not commit')
rec.input('tick', intent='post-duplicate idle tick')
assert case.device.sequence == seq + 1 and len(session.player.bench) == 1
rec.snapshot('duplicate-release-safe')
auto_path = rec.save()
case.doCleanups()

case = new_case()
rec = Recorder(case, 'defer-persist-manual-terminal')
rec.input('state', intent='open isolated device session')
for label in ('战术远征', '主搭档', '喷火龙', '出发', '确认'):
    rec.choose(label)
session = demo.SESSIONS[case.device.sid]
for old in session.player.shop.slots:
    if old is not None:
        session.pool.put(old)
session.player.shop.slots = [7] * 4
for _ in range(4):
    session.pool.take(7)
session.player.gold = 50
assert demo.api_action({'cmd': 'save', 'sid': session.sid})['ok']
rec.input('state', intent='refresh after evidence shop pin')
for _ in range(2):
    rec.choose('商店'); rec.choose('杰尼龟')
rec.choose('商店'); rec.choose('杰尼龟', intent='open buy evolution preview')
assert case.device.page == 'evolution_buy'
rec.snapshot('defer-preview-two-options')
rec.choose('购买并暂缓')
assert case.device.page == 'confirm' and case.device.selected == 0
rec.snapshot('defer-confirm-default-cancel')
rec.click('C', intent='physically release default cancel')
assert len(session.player.bench) == 2
rec.snapshot('defer-cancel-zero-resource-change')
rec.choose('购买并暂缓'); rec.choose('确认', intent='buy third copy and defer all merges')
assert len(session.player.bench) == 3
assert all(o.evolution_locked for o in session.player.bench)
rec.snapshot('defer-three-locked-copies')
assert demo.api_action({'cmd': 'save', 'sid': session.sid})['ok']
sid = session.sid
locks = [o.evolution_locked for o in session.player.bench]
demo.SESSIONS.clear()
rec.input('state', intent='simulate process restart; device must reload from isolated save')
rec.choose('继续存档')
session = demo.SESSIONS[sid]
assert [o.evolution_locked for o in session.player.bench] == locks
rec.snapshot('locks-restored-after-restart')
uid = session.player.bench[0].uid
for label in ('棋盘与备战', '备战席', '杰尼龟'):
    rec.choose(label)
assert '进化预览' in [r['label'] for r in case.device.rows()]
rec.snapshot('piece-menu-eight-rows')
rec.choose('进化预览', intent='open manual one-step evolution preview')
manual_preview = case.state['screen']['evolution_preview']
assert len(manual_preview['merges']) == 1 and '只进化一步' in manual_preview['detail']
rec.snapshot('manual-one-step-preview')
rec.long('C', intent='read full manual evolution detail')
assert case.device.page == 'detail'
rec.snapshot('manual-full-detail')
rec.click('C', intent='return from full detail')
rec.choose('确认进化')
assert case.device.page == 'confirm' and case.device.selected == 0
rec.snapshot('manual-confirm-default-cancel')
rec.click('C', intent='physically release default cancel')
assert len(session.player.bench) == 3
rec.choose('确认进化'); rec.choose('确认', intent='commit exactly one manual evolution step')
assert len(session.player.bench) == 1
evolved = session.player.bench[0]
assert (evolved.piece.species_id, evolved.uid, evolved.evolution_locked) == (8, uid, False)
rec.snapshot('manual-one-step-committed')
session.pool.take(131)
session.player.bench.append(demo.shop_mod.OwnedPiece(session.templates[131], 3))
assert demo.api_action({'cmd': 'save', 'sid': session.sid})['ok']
rec.input('state', intent='refresh after adding terminal species Lapras')
for label in ('棋盘与备战', '备战席', '拉普拉斯'):
    rec.choose(label)
assert '形态状态' in [r['label'] for r in case.device.rows()]
rec.snapshot('terminal-piece-menu-no-lock')
rec.choose('形态状态', intent='open terminal species status')
assert case.device.page == 'detail'
first_detail = case.state['screen']['detail']
all_detail = ''.join(first_detail)
pages = [first_detail]
for _ in range(case.state['screen']['detail_total'] - 1):
    rec.click('B', intent='advance terminal detail page')
    page_detail = case.state['screen']['detail']
    all_detail += ''.join(page_detail)
    pages.append(page_detail)
    rec.snapshot('terminal-detail-page')
assert '已无后续关都进化' in all_detail
rec.note('terminal detail assertion collected every page', pages_collected=len(pages))
defer_path = rec.save()
case.doCleanups()

case = new_case()
rec = Recorder(case, 'unlock-relock-suppressed-buy')
rec.input('state', intent='open isolated device session')
for label in ('战术远征', '主搭档', '喷火龙', '出发', '确认'):
    rec.choose(label)
session = demo.SESSIONS[case.device.sid]
for old in session.player.shop.slots:
    if old is not None:
        session.pool.put(old)
session.player.shop.slots = [7] * 4
for _ in range(4):
    session.pool.take(7)
session.player.gold = 50
assert demo.api_action({'cmd': 'save', 'sid': session.sid})['ok']
rec.input('state', intent='refresh after evidence shop pin')
for _ in range(2):
    rec.choose('商店'); rec.choose('杰尼龟')
rec.choose('商店'); rec.choose('杰尼龟'); rec.choose('购买并暂缓'); rec.choose('确认')
assert [o.evolution_locked for o in session.player.bench] == [True, True, True]
rec.snapshot('all-three-locked')
for label in ('棋盘与备战', '备战席', '杰尼龟'):
    rec.choose(label)
seq = case.device.sequence
rec.choose('解除形态锁定')
assert case.device.page == 'confirm' and case.device.selected == 0
rec.snapshot('unlock-confirm-default-cancel')
rec.click('C', intent='physically release default cancel')
assert case.device.sequence == seq
assert [o.evolution_locked for o in session.player.bench] == [True, True, True]
rec.snapshot('unlock-cancel-zero-lock-change')
rec.choose('解除形态锁定'); rec.choose('确认', intent='unlock one selected instance')
assert [o.evolution_locked for o in session.player.bench] == [False, True, True]
rec.snapshot('one-instance-unlocked')
assert demo.api_action({'cmd': 'save', 'sid': session.sid})['ok']
sid = session.sid
demo.SESSIONS.clear()
rec.input('state', intent='simulate process restart before relock')
rec.choose('继续存档')
session = demo.SESSIONS[sid]
assert [o.evolution_locked for o in session.player.bench] == [False, True, True]
rec.snapshot('mixed-locks-restored')
for label in ('棋盘与备战', '备战席', '杰尼龟'):
    rec.choose(label)
rec.choose('锁定当前形态'); rec.choose('确认', intent='relock previously unlocked instance')
assert [o.evolution_locked for o in session.player.bench] == [True, True, True]
rec.snapshot('all-locks-restored-by-user')
for old in session.player.shop.slots:
    if old is not None:
        session.pool.put(old)
session.player.shop.slots = [7] * 4
for _ in range(4):
    session.pool.take(7)
session.player.gold = 50
assert demo.api_action({'cmd': 'save', 'sid': session.sid})['ok']
rec.input('state', intent='refresh before proving fewer than three unlocked copies do not preview')
seq, bench = case.device.sequence, len(session.player.bench)
rec.choose('商店'); rec.choose('杰尼龟')
assert case.device.page == 'prep' and case.device.sequence == seq + 1
assert len(session.player.bench) == bench + 1
assert [o.evolution_locked for o in session.player.bench[:3]] == [True, True, True]
rec.snapshot('locked-copies-suppress-automatic-combine')
unlock_path = rec.save()
case.doCleanups()

before_hashes = {str(p.relative_to(ROOT)): sha(p) for p in SOURCE_FILES}
report = {
    'generated_at': datetime.now(timezone.utc).isoformat(),
    'source_hashes': before_hashes,
    'trace_files': [str(auto_path), str(defer_path), str(unlock_path)],
    'assertions': [
        'tactics_v5 buy preview is side-effect free before confirmation',
        'automatic evolution inherits UID, item, and technique and is duplicate-release safe',
        'defer keeps three copies, locks all instances, persists, and restores after process restart',
        'manual evolution performs exactly one canonical step and unlocks the result',
        'unlock confirmation defaults to cancel, persists mixed lock state, and can relock',
        'fewer than three unlocked copies bypass evolution preview and do not auto-combine',
        'terminal species exposes status detail with no lock control across every detail page',
    ],
}
(OUT / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
print(json.dumps(report, ensure_ascii=False, indent=2))
