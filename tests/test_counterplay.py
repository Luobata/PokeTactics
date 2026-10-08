"""Paid, versioned healing denial: native hits, actual HP and durable ownership."""
import copy
import hashlib
import json
from pathlib import Path
import random
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'tools/acceptance'), str(ROOT/'sim'), str(ROOT)]
import demo
from bots import PERSONALITIES
import items
import tactics
from combat import Battle
from session_save import SessionCodec, LEGACY_ABILITIES_FINGERPRINT, UnknownRulesError
from test_tactical_combat import effects, strike


def fixture(source=6, target=143):
    battle = Battle([(demo.build_templates()[source], 'healing_needle')],
                    [demo.build_templates()[target]], random.Random(741),
                    positions_a=[(2, 2)], positions_b=[(2, 1)],
                    stat_mode='budget_v1', ruleset='tactics_v3')
    for unit in battle.units:
        unit.max_hp = unit.hp = 10000
    return battle, *battle.units


class HealingCounterContracts(unittest.TestCase):
    def test_recipe_is_versioned_and_stone_can_still_use_named_pair(self):
        for version in ('base_v1', 'tactics_v1', 'tactics_v2', 'tactics_v3'):
            inv = items.Inventory(version)
            inv.add_component('band'); inv.add_component('charcoal')
            active = version == 'tactics_v3'
            self.assertEqual(items.craft_result('band', 'charcoal', version),
                             'healing_needle' if active else 'evo_stone')
            self.assertEqual(inv.craftable('healing_needle') is not None, active)
            pair = inv.craftable('evo_stone')
            self.assertIsNotNone(pair)
            inv.craft('evo_stone', pair)
            self.assertEqual(inv.finished, ['evo_stone'])
            self.assertEqual(inv.total_components(), 0)
        for version in ('base_v1', 'tactics_v1', 'tactics_v2'):
            with self.assertRaises(ValueError):
                Battle([(demo.build_templates()[6], 'healing_needle')],
                       [demo.build_templates()[143]], random.Random(1), ruleset=version)

    def test_native_primary_once_reduces_actual_missing_hp_and_expires(self):
        battle, attacker, target = fixture()
        strike(battle, attacker, target, 1.)
        block, = effects(battle, 'healing_block')
        self.assertEqual(block[5]['expires_at'], 9.)
        self.assertTrue(attacker.needle_used)
        target.hp = 9000
        self.assertEqual(battle._heal(target, 2000, 2.), 400)
        prevented, = effects(battle, 'healing_prevented')
        self.assertEqual(prevented[5]['amount'], 600)  # Never count overheal.
        self.assertEqual(target.hp, 9400)
        target.hp = 10000
        before = len(battle.events)
        self.assertEqual(battle._heal(target, 2000, 2.), 0)
        self.assertEqual(len(battle.events), before)
        target.hp = 9000
        self.assertEqual(battle._heal(target, 1000, 9.), 1000)
        strike(battle, attacker, target, 10.)
        self.assertEqual(len(effects(battle, 'healing_block')), 1)

    def test_miss_immunity_death_basic_and_derived_packets_do_not_consume(self):
        battle, attacker, target = fixture()
        attacker.energy = 80
        with patch.dict(battle.dex.moves[attacker.piece.move_id], accuracy=1), \
                patch.object(battle.rng, 'randrange', return_value=99):
            battle._strike(attacker, target, .1)
        self.assertFalse(attacker.needle_used)
        attacker.energy = 0
        battle._strike(attacker, target, .2)
        self.assertFalse(attacker.needle_used)
        battle._land_hit(attacker, target, 1, .3, primary=False)
        self.assertFalse(attacker.needle_used)
        target.hp = 1
        strike(battle, attacker, target, 1.)
        self.assertFalse(attacker.needle_used)
        self.assertEqual(battle._heal(target, 100, 2.), 0)
        self.assertFalse(target.alive)
        battle, attacker, target = fixture(94, 143)
        strike(battle, attacker, target)
        self.assertFalse(attacker.needle_used)  # Normal absorbs the Ghost cast.
        self.assertFalse(effects(battle, 'healing_block'))

    def test_overlapping_sources_max_strength_and_independent_expiry(self):
        battle, attacker, target = fixture()
        target.hp = 9000
        target.healing_blocks = [{'source': attacker.idx, 'fraction': .6, 'expires_at': 3.},
                                {'source': attacker.idx, 'fraction': .2, 'expires_at': 7.}]
        self.assertEqual(battle._heal(target, 100, 2.), 40)
        self.assertEqual(battle._heal(target, 100, 3.), 80)
        attacker.hp = 0
        self.assertEqual(battle._heal(target, 100, 4.), 80)
        self.assertEqual(battle._heal(target, 100, 7.), 100)

    def test_periodic_rest_and_partner_heals_share_real_healing_path(self):
        battle, attacker, target = fixture()
        target.hp = 5000
        target.healing_blocks = [{'source': attacker.idx, 'fraction': .6, 'expires_at': 20.}]
        battle._partner_heal(target, target, .25, 1., 'rest')
        self.assertEqual(target.hp, 6000)
        event = next(e for e in battle.events if e[1] == 'partner_effect')
        self.assertEqual(event[6]['amount'], 1000)
        target.synergy_heal = .01; target.item_heal = .015
        attacker.next_act = target.next_act = 100.
        with patch('combat.MAX_BATTLE_SECONDS', 1.1):
            battle.run()
        self.assertEqual(target.hp, 6100)  # 250 requested, 100 actually healed.
        self.assertEqual(sum(e[5]['amount'] for e in effects(battle, 'healing_prevented')), 1650)

    def test_guard_receives_needle_on_final_target(self):
        from test_tactical_combat import guarded_battle
        battle, attacker, protected, guard, bait = guarded_battle()
        battle.ruleset = 'tactics_v3'
        attacker.item_key = 'healing_needle'
        strike(battle, attacker, bait)
        block, = effects(battle, 'healing_block')
        self.assertEqual(block[3], guard.idx)
        self.assertFalse(protected.healing_blocks)


class CounterSessionContracts(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(); self.addCleanup(directory.cleanup)
        for p in (patch.object(demo, 'SAVE_ROOT', Path(directory.name)), patch.object(demo, 'SESSIONS', {})):
            p.start(); self.addCleanup(p.stop)
        result = demo.api_action({'cmd': 'new', 'mode': 'tactics', 'seed': '7'})
        self.assertTrue(result['ok'], result)
        self.sid = result['sid']; self.session = demo.SESSIONS[self.sid]; self.codec = SessionCodec()
        self.session.player.inventory.add_component('band')
        self.session.player.inventory.add_component('charcoal')
        demo.api_action({'cmd': 'save', 'sid': self.sid})

    def act(self, cmd, **params):
        return demo.api_action({'cmd': cmd, 'sid': self.sid, **params})

    def test_paid_craft_equip_return_sell_and_resume_conserve_item(self):
        self.assertTrue(self.act('craft', item='healing_needle')['ok'])
        self.assertEqual(self.session.player.inventory.total_components(), 0)
        before = self.codec.encode(self.session)
        self.assertFalse(self.act('craft', item='healing_needle')['ok'])
        self.assertEqual(self.codec.encode(self.session), before)
        self.assertTrue(self.act('equip', item='healing_needle', loc='g0,2')['ok'])
        encoded = self.codec.encode(self.session)
        restored = self.codec.decode(encoded, 4)
        self.assertEqual(self.codec.encode(restored), encoded)
        self.assertEqual(restored.player.inventory.ruleset, self.session.ruleset)
        self.assertTrue(self.act('unequip', loc='g0,2')['ok'])
        self.assertEqual(self.session.player.inventory.finished, ['healing_needle'])
        self.assertTrue(self.act('equip', item='healing_needle', loc='g0,2')['ok'])
        self.assertTrue(self.act('sell', loc='g0,2')['ok'])
        self.assertEqual(self.session.player.inventory.finished, ['healing_needle'])

    def test_old_version_and_fingerprint_cannot_acquire_counter(self):
        data = self.codec.encode(self.session)
        data['rules'] = LEGACY_ABILITIES_FINGERPRINT
        with self.assertRaises(UnknownRulesError):
            self.codec.decode(data, 4)
        for version in ('base_v1', 'tactics_v1', 'tactics_v2'):
            altered = self.codec.encode(self.session); altered['ruleset'] = version
            altered['seats'][0]['finished'] = ['healing_needle']
            with self.assertRaises(ValueError):
                self.codec.decode(altered, 4)

    def test_v2_frozen_fixture_replays_complete_state_and_events(self):
        saved = json.loads((ROOT/'tests/fixtures/tactics-v2-schema4-session.json').read_text())
        session = self.codec.decode(saved['initial'], 4); session.sid = 'v2-golden'
        battles = []
        def render(a, b, rng, weather, path, positions_a=None, hud_snapshot=None, **options):
            battle = demo.Battle(a, b, rng, layout='back', weather_name=weather, positions_a=positions_a, **options)
            result = battle.run()
            battles.append({'events_sha256': hashlib.sha256(json.dumps(battle.events, ensure_ascii=False,
                           separators=(',', ':')).encode()).hexdigest(), 'event_count': len(battle.events),
                           'winner': result['winner'], 'survivors': {str(k): v for k, v in result['survivors'].items()},
                           'duration': result['duration']})
            return {'n': 0, 'winner': result['winner'], 'survivors': result['survivors'],
                    'duration': result['duration'], 'events': []}
        with patch.object(demo, 'SESSIONS', {session.sid: session}), patch.object(demo, '_render_battle_frames', side_effect=render):
            for command in saved['commands']:
                result = demo._apply_action({'sid': session.sid, **command}); self.assertTrue(result['ok'], result)
        actual = self.codec.encode(session); actual['rules'] = LEGACY_ABILITIES_FINGERPRINT
        expected = copy.deepcopy(saved['expected_after'])
        initial = saved['initial']
        opponent_seat = next(b if a == 0 else a for a, b in initial['pairs'] if 0 in (a, b))
        opponent = next(seat for seat in initial['seats'] if seat['seat'] == opponent_seat)
        opponent_name = f"{opponent_seat}·{PERSONALITIES[opponent['personality']]['label'][:3]}L{opponent['ability']}"
        # Extend only the new report ledger, independently of the live session.
        # Frozen outcomes and the original opponent record remain the oracle.
        expected['battle_history'] = [{
            'round': initial['round'] + index, 'winner': result['winner'],
            'duration': result['duration'], 'pve': False, 'ghost': False,
            'opp_name': opponent_name, 'statistics': None,
        } for index, result in enumerate(saved['expected_battles'])]
        self.assertEqual(actual, expected)
        self.assertEqual(battles, saved['expected_battles'])


if __name__ == '__main__':
    unittest.main()
