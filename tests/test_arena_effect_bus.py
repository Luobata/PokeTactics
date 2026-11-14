"""Effect bus contracts and arena_v1 behaviour freeze (golden event fingerprints)."""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for path in (ROOT / 'sim', ROOT / 'tools' / 'acceptance', ROOT / 'tools' / 'mockups'):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import arena_effects  # noqa: E402
import arena_golden  # noqa: E402

FIXTURE = ROOT / 'tests' / 'fixtures' / 'arena_golden.json'


class EffectBusTest(unittest.TestCase):
    def test_legacy_hooks_keep_historical_order(self):
        self.assertEqual([h.__name__ for h in arena_effects.LEGACY_HOOKS['native_energy']],
                         ['_energy_offense', '_energy_bonds', '_energy_equipment'])
        self.assertEqual([h.__name__ for h in arena_effects.LEGACY_HOOKS['direct_hit']],
                         ['_direct_traits', '_direct_bonds', '_direct_teaching'])

    def test_subscribe_rejects_unknown_trigger(self):
        bus = arena_effects.EffectBus(battle=None)
        with self.assertRaises(ValueError):
            bus.subscribe('after_lunch', lambda **_: None)

    def test_emit_runs_handlers_in_subscription_order(self):
        calls = []
        bus = arena_effects.EffectBus(battle='B')
        bus.handlers['death'] = []
        bus.subscribe('death', lambda battle, **ctx: calls.append(('a', battle, ctx['t'])))
        bus.subscribe('death', lambda battle, **ctx: calls.append(('b', battle, ctx['t'])))
        bus.emit('death', t=1.5)
        self.assertEqual(calls, [('a', 'B', 1.5), ('b', 'B', 1.5)])

    def test_ledger_accumulates_per_team_source(self):
        ledger = arena_effects.Ledger()
        ledger.add(0, 'item', 'life_orb', triggers=1, damage=10.4)
        ledger.add(0, 'item', 'life_orb', triggers=1, damage=5)
        ledger.add(1, 'augment', 'executioner', triggers=1)
        row = ledger.view(0)[0]
        self.assertEqual((row['triggers'], row['damage']), (2, 15))
        self.assertEqual(ledger.view(1)[0]['id'], 'executioner')


class ArenaV1FreezeTest(unittest.TestCase):
    """The refactor and every depth feature must leave arena_v1 battles identical."""

    def test_session_and_fuzz_fingerprints_unchanged(self):
        expected = json.loads(FIXTURE.read_text())
        self.assertEqual(arena_golden.run_seed(11), expected['11'])
        self.assertEqual(arena_golden.run_fuzz(11, 80), expected['fuzz11'])


if __name__ == '__main__':
    unittest.main()
