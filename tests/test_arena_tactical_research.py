"""Tactical research is settled from real facts and starts only next battle."""
import copy
import json
import random
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'sim'), str(ROOT / 'tools/acceptance')]
import arena
import arena_families as families
import arena_research
import arena_skills
import status
from combat import Battle
from data import ENERGY_MAX
import demo
from session_save import SessionCodec


class ArenaTacticalResearch(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.templates = arena.build_templates()
        cls.codec = SessionCodec()

    def battle(self, source_sid, allies=(128,), enemy=128, *, research=None):
        source = families.make_piece(133, 2, source_sid) if source_sid in (134, 135, 136, 196, 197) \
            else families.make_piece(source_sid, 2)
        friends = [source] + [copy.copy(self.templates[sid]) for sid in allies]
        enemies = [copy.copy(self.templates[enemy])]
        battle = Battle(friends, enemies, random.Random(2501), ruleset='arena_v1',
                        stat_mode='budget_v1', arena_teams=[[], []],
                        positions_a=[(2, 3), (1, 3), (3, 3)][:len(friends)],
                        positions_b=[(2, 2)], arena_research=research)
        if research is None:
            for unit in battle.units:
                unit.max_hp = unit.hp = 1000
                unit.energy = 0
        return battle

    def cast(self, battle, source, raw=50):
        battle.duration = 1.
        source.energy = ENERGY_MAX
        target = next(unit for unit in battle.units
                      if unit.team != source.team and unit.alive)
        with patch.object(status, 'on_hit'), patch.object(battle, '_move_damage', return_value=raw):
            self.assertTrue(arena_skills.cast(battle, source, target, 1.))

    @staticmethod
    def effects(battle, key, effect):
        return [row for row in battle.events if row[1] == 'combo_effect'
                and row[4:6] == (key, effect)]

    def test_catalog_and_view_use_stable_public_fields(self):
        catalog = arena_research.catalog()
        self.assertEqual([row['id'] for row in catalog], ['sustain', 'assault', 'tempo'])
        self.assertEqual([(row['name'], row['limit'], row['species']) for row in catalog],
                         [('生存研习', 5, [134]),
                          ('强攻研习', 5, [136, 196]),
                          ('节奏研习', 5, [135, 197, 198])])
        state = arena_research.initial_state()
        arena_research.settle(state, 3, 1, {'tempo': {'species': [135], 'evidence_count': 2}})
        view = arena_research.view(state, 3)
        self.assertEqual(view['version'], 1)
        self.assertEqual([(row['id'], row['stacks']) for row in view['tracks']],
                         [('sustain', 0), ('assault', 0), ('tempo', 1)])
        self.assertEqual((view['last_round'], view['earned']), (1, ['tempo']))
        self.assertIn('下一场生效', view['description'])

    def test_battle_rejects_non_arena_and_forged_research_maps(self):
        piece = families.make_piece(133, 2, 134)
        valid = ({'sustain': 1}, {'tempo': 2})
        self.assertEqual(Battle([piece], [copy.copy(self.templates[128])], random.Random(4),
                                ruleset='arena_v1', stat_mode='budget_v1',
                                arena_teams=[[], []], arena_research=valid).arena_research,
                         ({'sustain': 1}, {'tempo': 2}))
        cases = [
            [{'sustain': 1}],
            ({'sustain': 1},),
            ({'unknown': 1}, {}),
            ({'sustain': True}, {}),
            ({'sustain': -1}, {}),
            ({'sustain': 6}, {}),
        ]
        for research in cases:
            with self.subTest(research=research), self.assertRaises(ValueError):
                Battle([piece], [copy.copy(self.templates[128])], random.Random(4),
                       ruleset='arena_v1' if research != cases[0] else 'base_v1',
                       stat_mode='budget_v1',
                       arena_teams=None if research == cases[0] else [[], []],
                       arena_research=research)

    def test_reward_stacks_apply_to_next_battle_team_stats(self):
        base = self.battle(134, research=({}, {}))
        boosted = self.battle(134, research=({'sustain': 3, 'assault': 2, 'tempo': 4}, {}))
        for plain, unit in zip(base.units[:2], boosted.units[:2]):
            self.assertEqual(unit.max_hp, int(plain.max_hp * 1.03))
            self.assertAlmostEqual(unit.attack / plain.attack, 1.02, delta=.03)
            self.assertAlmostEqual(unit.sp_attack / plain.sp_attack, 1.02, delta=.03)
            self.assertEqual(unit.energy, 4)

    def test_real_eevee_support_traits_prove_sustain_and_tempo_routes(self):
        b = self.battle(134)
        source, patient, enemy = b.units
        patient.hp = 100
        self.cast(b, source)
        self.assertTrue(self.effects(b, 'trait_tidal_renewal', 'heal'))
        self.assertEqual(arena_research.review(b, 0),
                         {'sustain': {'species': [134], 'evidence_count': 1}})

        b = self.battle(135)
        source, patient, enemy = b.units
        patient.energy = 0
        self.cast(b, source)
        self.assertTrue(self.effects(b, 'trait_charge_relay', 'energy'))
        self.assertEqual(arena_research.review(b, 0),
                         {'tempo': {'species': [135], 'evidence_count': 1}})

    def test_real_condition_attack_traits_prove_assault_route(self):
        for sid, key in ((136, 'trait_ignite_pursuit'), (196, 'trait_weakness_read')):
            with self.subTest(sid=sid):
                b = self.battle(sid)
                source, ally, target = b.units
                target.max_hp = target.hp = 5000
                self.cast(b, source)
                self.assertTrue(target.alive)
                with patch.object(status, 'on_hit'):
                    b._land_hit(source, target, 100, 2., primary=True, direct=True)
                rows = self.effects(b, key, 'empowered_hit')
                self.assertEqual(len(rows), 1)
                self.assertGreater(rows[0][6]['extra_damage'], 0)
                self.assertEqual(arena_research.review(b, 0),
                                 {'assault': {'species': [sid], 'evidence_count': 1}})

    def test_moonlight_requires_actual_absorb_and_umbreon_uses_gained_energy(self):
        b = self.battle(197)
        source, patient, enemy = b.units
        patient.hp = 100
        self.cast(b, source)
        self.assertTrue(self.effects(b, 'trait_moonlight', 'shield'))
        self.assertEqual(arena_research.review(b, 0), {})
        with patch.object(status, 'on_hit'):
            b._land_hit(enemy, patient, 80, 2., primary=True, direct=True)
        self.assertTrue(self.effects(b, 'trait_moonlight', 'absorb'))
        self.assertEqual(arena_research.review(b, 0),
                         {'tempo': {'species': [197], 'evidence_count': 1}})

        b = self.battle(198)
        source, ally, target = b.units
        target.energy = 40
        source.energy = 0
        with patch.object(status, 'on_hit'):
            b._land_hit(source, target, 100, 1., primary=True, direct=True)
        row = self.effects(b, 'trait_night_feed', 'energy_drain')[0]
        self.assertGreater(row[6]['gained'], 0)
        self.assertEqual(arena_research.review(b, 0),
                         {'tempo': {'species': [198], 'evidence_count': 1}})

    def test_review_requires_selected_trait_and_event_key_to_match(self):
        b = self.battle(134)
        source, patient, enemy = b.units
        patient.hp = 100
        self.cast(b, source)
        row = self.effects(b, 'trait_tidal_renewal', 'heal')[0]
        forged = list(row)
        forged[4] = 'trait_charge_relay'
        b.events[b.events.index(row)] = tuple(forged)
        self.assertEqual(arena_research.review(b, 0), {})

    def test_settlement_is_in_place_once_per_round_and_capped(self):
        state = arena_research.initial_state()
        evidence = {'tempo': {'species': [135], 'evidence_count': 3}}
        self.assertEqual(arena_research.settle(state, 2, 1, evidence), ['tempo'])
        self.assertIs(state['seats'][2]['stacks']['tempo'], 1)
        self.assertEqual(arena_research.settle(state, 2, 1, evidence), [])
        for round_no in range(2, 6):
            self.assertEqual(arena_research.settle(state, 2, round_no, evidence), ['tempo'])
        self.assertEqual(state['seats'][2]['stacks']['tempo'], 5)
        self.assertEqual(arena_research.settle(state, 2, 7, evidence), [])
        self.assertEqual(arena_research.normalize_state(state)['seats'][2]['settlements'][0]['evidence_count'], 3)
        high = {'tempo': {'species': [135], 'evidence_count': 101}}
        state = arena_research.initial_state()
        arena_research.settle(state, 0, 1, high)
        self.assertEqual(state['seats'][0]['settlements'][0]['evidence_count'], 100)

    def test_same_round_stack_is_hidden_until_next_battle_and_forgings_rejected(self):
        state = arena_research.initial_state()
        arena_research.settle(state, 1, 2, {'assault': {'species': [136], 'evidence_count': 1}})
        self.assertEqual(arena_research.stacks_for(state, 1, before_round=2)['assault'], 0)
        self.assertEqual(arena_research.stacks_for(state, 1, before_round=3)['assault'], 1)
        forged = arena_research.initial_state()
        forged['version'] = True
        with self.assertRaises(ValueError):
            arena_research.normalize_state(forged)
        forged = arena_research.initial_state()
        arena_research.settle(forged, 1, 1, {'sustain': {'species': [134], 'evidence_count': 1}})
        forged['seats'][1]['settlements'][0]['sources'] = [True]
        with self.assertRaises(ValueError):
            arena_research.normalize_state(forged)

    def session(self):
        session = demo.Session(3501, 'arena_v1', arena_pool=families.VERSION)
        session.begin_round(1)
        for reward in list(session.arena_augments_pending):
            arena.claim_augment(session, reward['id'], reward['options'][0]['id'])
        session.pool.take(133)
        session.player.grid[(2, 2)] = demo.shop_mod.OwnedPiece(
            copy.copy(session.templates[133]), 2)
        return session

    @staticmethod
    def result(seats, winner=0):
        return {'winner': winner, 'survivors': {0: 1, 1: 1}, 'duration': 1., 'n': 0,
                'events': [], '_research_by_seat': {
                    seat: {'tempo': {'species': [135], 'evidence_count': 1}} for seat in seats}}

    def test_bot_pvp_rendered_pvp_pve_and_ghost_settle_real_seats_once(self):
        evidence = {'tempo': {'species': [135], 'evidence_count': 1}}
        s = self.session()
        with patch.object(s, '_fight', side_effect=lambda *args, **kwargs:
                          self.result([args[2].seat, args[3].seat])), \
             patch.object(s, '_fight_rendered', side_effect=lambda *args, **kwargs:
                          self.result([args[2].seat, args[3].seat], winner=0)):
            s.end_prep()
        self.assertTrue(any(row['stacks']['tempo'] == 1 for row in s.arena_research['seats']))
        self.assertTrue(all(row['stacks']['tempo'] <= 1 for row in s.arena_research['seats']))
        loot_ids = [row['id'] for row in s.arena_loot]
        self.assertEqual(len(loot_ids), len(set(loot_ids)))

        s = self.session()
        meta = {'winner': 0, 'survivors': {0: 1, 1: 1}, 'n': 0, 'events': [],
                'research_teams': [evidence, evidence]}
        opponent = next(seat for seat in s.seats if seat is not s.player)
        with patch.object(demo, '_render_battle_frames', return_value=meta):
            rendered = s._fight_rendered(1, 0, s.player, opponent, None)
        self.assertEqual(rendered['_research_by_seat'],
                         {s.player.seat: evidence, opponent.seat: evidence})
        for label, flags in (('ghost', {'ghost': True}), ('pve', {'pve': True})):
            with self.subTest(route=label), patch.object(
                    demo, '_render_battle_frames', return_value=dict(meta)):
                mapped = s._fight_rendered(1, 1, s.player, opponent, None, **flags)
            self.assertEqual(set(mapped['_research_by_seat']), {s.player.seat})

        s = self.session()
        s.round_no, s.phase = 5, 'battle'
        with patch.object(s, '_fight_rendered', return_value=self.result([s.player.seat])):
            s._resolve_pve(5, None)
        self.assertEqual(s.arena_research['seats'][s.player.seat]['stacks']['tempo'], 1)

        s = self.session()
        s.pairs = [(s.seats[1], s.seats[2]), (s.seats[3], s.seats[4]),
                   (s.seats[5], s.seats[6])]
        s.ghost_seat, s.ghost_src = s.player, s.seats[1]
        ghost_result = self.result([s.player.seat])
        with patch.object(s, '_fight', return_value=ghost_result), \
             patch.object(s, '_fight_rendered', return_value=ghost_result):
            s.end_prep()
        self.assertEqual(s.arena_research['seats'][s.player.seat]['stacks']['tempo'], 1)
        self.assertEqual(s.arena_research['seats'][s.ghost_src.seat]['stacks']['tempo'], 0)

    def test_current_saves_roundtrip_and_predecessor_starts_empty_without_replay(self):
        s = self.session()
        s.phase = 'battle'
        arena_research.settle(s.arena_research, 0, 1,
                              {'sustain': {'species': [134], 'evidence_count': 2}})
        payload = self.codec.encode(s)
        restored = self.codec.decode(payload, 5)
        self.assertEqual(restored.arena_research, s.arena_research)
        self.assertEqual(self.codec.encode(restored), payload)
        state = demo.state_json(restored)
        self.assertEqual(state['arena']['research']['tracks'][0]['stacks'], 1)
        self.assertEqual(state['scouting'][0]['research']['tracks'][0]['stacks'], 1)
        missing = copy.deepcopy(payload)
        del missing['arena']['research']
        with self.assertRaises(ValueError):
            self.codec.decode(missing, 5)
        with_new = copy.deepcopy(payload)
        with_new['rules'] = 'not-a-current-fingerprint'
        with self.assertRaises(ValueError):
            self.codec.decode(with_new, 5)

        old = json.loads((ROOT / 'tests/fixtures/families-v2-pre-tactical-traits.json').read_text())
        restored = self.codec.decode(old, 5)
        self.assertEqual(restored.arena_research, arena_research.initial_state())
        self.assertIn('历史回合不追溯', restored.save_warning)
        upgraded = self.codec.encode(restored)
        self.assertEqual(upgraded['arena']['research'], arena_research.initial_state())


if __name__ == '__main__':
    unittest.main()
