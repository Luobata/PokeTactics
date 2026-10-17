"""Hoenn family native kits stay external to the frozen legacy registries."""
import copy
import sys
import unittest
from types import SimpleNamespace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'sim'))
import arena_gen3
import arena_skills
import arena_traits
from combat import Battle
import status
import arena
import arena_families as families
import random
from unittest.mock import patch


SPECIES = {
    252, 253, 254, 255, 256, 257, 258, 259, 260, 270, 271, 272,
    280, 281, 282, 285, 286, 304, 305, 306, 333, 334, 349, 350,
    359, 371, 372, 373, 374, 375, 376,
}
TERMINALS = {254, 257, 260, 272, 282, 286, 306, 334, 350, 359, 373, 376}
ALLOWED_TYPES = {
    'NORMAL', 'FIRE', 'WATER', 'GRASS', 'ELECTRIC', 'FIGHTING', 'GROUND',
    'PSYCHIC', 'ROCK', 'GHOST', 'DRAGON', 'DARK', 'STEEL', 'BUG', 'POISON',
    'ICE', 'FLYING',
}


class Gen3CombatKits(unittest.TestCase):
    def test_first_hoenn_batch_has_one_distinct_move_and_role_per_stage(self):
        self.assertEqual(set(arena_gen3.ROLES), SPECIES)
        self.assertEqual(set(arena_gen3.SKILLS), SPECIES)
        self.assertEqual(set(arena_gen3.GEN3_TRAITS), SPECIES)
        self.assertEqual(len({row['id'] for row in arena_gen3.SKILLS.values()}), len(SPECIES))
        self.assertEqual(len({row['name'] for row in arena_gen3.SKILLS.values()}), len(SPECIES))
        self.assertLess({25, 35, 40, 55, 65, 70, 85},
                        {row['power'] for row in arena_gen3.SKILLS.values()})
        for sid, skill in arena_gen3.SKILLS.items():
            with self.subTest(sid=sid):
                self.assertEqual(skill['role'], arena_gen3.ROLES[sid])
                self.assertIn(skill['type'], ALLOWED_TYPES)
                self.assertIn(skill['effect'], arena_gen3._EFFECT_IDENTITIES)
                self.assertIn(skill['power'], range(0, 91))
                self.assertRegex(skill['description'], r'。$')
                resolved = arena_skills.skill_of(sid)
                self.assertEqual(resolved['arch'], skill['effect'])
                self.assertEqual(resolved['id'], skill['id'])
                cast = arena_skills.resolve_cast(SimpleNamespace(species_id=sid))
                self.assertEqual(cast['name'], 'arena_' + skill['id'])
                self.assertEqual(cast['targeting'], skill['targeting'])

    def test_external_moves_do_not_mutate_frozen_legacy_skill_registry(self):
        baseline = {sid: dict(row) for sid, row in arena_skills.SKILLS.items()}
        for sid in SPECIES:
            arena_skills.skill_of(sid)
        self.assertEqual(set(arena_skills.SKILLS), set(baseline))
        self.assertEqual(len(arena_skills.SKILLS), 62)
        self.assertEqual(arena_skills.SKILLS, baseline)

    def test_terminal_power_budgets_are_explicit(self):
        # These values are the reviewable balance contract; a regression should
        # fail here rather than merely echo the current dictionary value.
        expected = {254: 70, 257: 75, 260: 65, 272: 0, 282: 0, 286: 60,
                    306: 65, 334: 0, 350: 0, 359: 70, 373: 85, 376: 70}
        self.assertEqual(set(expected), TERMINALS)
        for sid, power in expected.items():
            with self.subTest(sid=sid):
                self.assertEqual(arena_skills.skill_of(sid)['power'], power)
        self.assertEqual((arena_skills.skill_of(349)['role'],
                          arena_skills.skill_of(350)['role']), ('attack', 'support'))
        self.assertEqual(arena_skills.skill_of(349)['power'], 25)
        self.assertNotIn(349, arena_gen3.BONDS)
        self.assertNotIn(359, arena_gen3.BONDS)
        self.assertFalse(any(skill['targeting'] == 'self'
                            for skill in arena_gen3.GEN3_SKILLS.values()))

    def test_hoenn_traits_are_species_owned_and_reuse_known_hooks(self):
        hook_tables = {
            'trait_overgrow': arena_traits._LOW_HP_BOOST,
            'trait_blaze': arena_traits._LOW_HP_BOOST,
            'trait_torrent': arena_traits._LOW_HP_BOOST,
            'trait_rain_dish': arena_traits._CADENCE_HEAL,
            'trait_swift_swim': {key: 'weather' for key in ('trait_chlorophyll', 'trait_swift_swim')},
            'trait_synchronize': {'trait_synchronize': 'mirror'},
            'trait_effect_spore': arena_traits._CONTACT_STATUS,
            'trait_sturdy': arena_traits._LETHAL_GUARD,
            'trait_natural_cure': {'trait_natural_cure': 'after_cast'},
            'trait_spin_guard': {'trait_spin_guard': 'shield'},
            'trait_pressure': {'trait_pressure': 'opening'},
            'trait_intimidate': arena_traits._OPENING_WEAKEN,
            'trait_clear_body': {'trait_clear_body': 'opening_guard'},
        }
        for sid, expected in arena_gen3.GEN3_TRAITS.items():
            with self.subTest(sid=sid):
                view = arena_traits.for_species(sid)
                self.assertEqual(view['sid'], sid)
                self.assertEqual(view['id'], expected['id'])
                self.assertTrue(view['fixed'])
                self.assertFalse(view['selectable'])
                self.assertEqual(view['source_label'], '原作特性改编')
                self.assertIn(expected['id'], hook_tables)
                # Options are defensive copies; callers cannot mutate the Hoenn table.
                view['tags'].clear()
                self.assertTrue(arena_traits.for_species(sid)['tags'])
        self.assertIsNone(arena_traits.for_species(16))

    def test_tactical_bonds_only_go_to_kits_that_can_trigger_them(self):
        self.assertEqual(set(arena_gen3.BONDS), SPECIES - {349, 359, 371, 372, 373})
        for sid, keys in arena_gen3.BONDS.items():
            with self.subTest(sid=sid):
                self.assertEqual(len(set(keys)), 1)
                self.assertIn(next(iter(keys)), {'bond_combo', 'bond_guard', 'bond_inspiration'})


    def _battle(self, sid, support=False):
        fid = families.SPECIES_FAMILY[sid]
        path = next(route for route in families.FAMILIES[fid][1] if sid in route)
        caster = families.make_piece(fid, path.index(sid) + 1, path[-1])
        ally = families.make_piece(333 if sid != 333 else 270)
        target, enemy = families.make_piece(4), families.make_piece(4)
        battle = Battle([caster, ally], [target, enemy], random.Random(1003),
                        ruleset='arena_v1', stat_mode='budget_v1',
                        positions_a=[(2, 3), (1, 3)], positions_b=[(2, 2), (3, 2)],
                        arena_teams=[[], []])
        for unit in battle.units:
            unit.hp = unit.max_hp = 10000
            unit.energy = 80
            unit._st.ctrl_until = 1000.
        if support:
            battle.units[1].hp = 4000
            battle.units[1].energy = 0
        battle.duration = 2.
        return battle

    def _cast_fixed(self, battle, t=2.):
        caster, target = battle.units[0], battle.units[2]
        caster.energy = arena_skills.ENERGY_MAX
        with patch.object(battle, '_move_damage',
                          side_effect=lambda unit, victim, move, fraction=1.: int(100 * fraction)):
            self.assertTrue(arena_skills.cast(battle, caster, target, t))
        return next(event for event in battle.events if event[1] == 'cast')

    def test_every_hoenn_form_completes_a_real_native_cast(self):
        for sid in SPECIES:
            support = arena_gen3.ROLES[sid] == 'support'
            with self.subTest(sid=sid):
                battle = self._battle(sid, support=support)
                event = self._cast_fixed(battle)
                caster, target = battle.units[0], battle.units[2]
                self.assertEqual(event[3], target.idx if not support else event[3])
                self.assertEqual(event[4], 'arena_' + arena_gen3.SKILLS[sid]['id'])
                self.assertEqual(caster.casts, 1)
                self.assertEqual(caster.energy, 0)
                if support:
                    self.assertEqual(event[6], 0)
                    self.assertEqual(battle.units[1].team, caster.team)
                    effect = arena_gen3.SKILLS[sid]['effect']
                    if effect in ('dragon_vein', 'bliss_chorus'):
                        self.assertGreater(battle.units[1].hp, 4000)
                    elif effect in ('moon_blessing', 'barrier_relay'):
                        self.assertGreater(battle.units[1].shield, 0)
                    elif effect in ('star_resonance', 'watchful_lullaby'):
                        self.assertGreater(battle.units[1].energy, 0)
                else:
                    self.assertGreater(event[6], 0)
                    self.assertLess(target.hp, 10000)

    def test_terminal_mechanics_resolve_native_followups_and_support_effects(self):
        battle = self._battle(254)
        caster, target = battle.units[0], battle.units[2]
        target.vulnerable_until = 10.
        self._cast_fixed(battle)
        self.assertEqual(len([event for event in battle.events
                              if event[1] == 'skill_effect' and event[5] == 'side_hit']), 2)

        battle = self._battle(257)
        before = battle.units[2].pos
        self._cast_fixed(battle)
        self.assertNotEqual(battle.units[2].pos, before)

        battle = self._battle(272, support=True)
        self._cast_fixed(battle)
        self.assertGreater(battle.units[1].hp, 4000)
        self.assertGreater(battle.units[0].healing_done, 0)

        battle = self._battle(282, support=True)
        self._cast_fixed(battle)
        self.assertGreater(battle.units[1].shield, 0)

    def test_overgrow_trait_changes_settled_direct_grass_damage(self):
        battle = self._battle(252)
        caster, target = battle.units[0], battle.units[2]
        caster.hp = 3000
        target.hp = 10000
        with patch.object(battle, '_move_damage', return_value=100), patch.object(status, 'on_hit'):
            actual = battle._land_hit(caster, target, 100, 2., primary=True, cast=True,
                                      move=arena_skills.resolve_cast(caster.piece), direct=True)
        self.assertEqual(target.hp, 10000 - 125)
        self.assertEqual(actual, 125)
        self.assertTrue(any(event[1] == 'combo_effect' and event[4] == 'trait_overgrow'
                            and event[5] == 'empowered_hit' for event in battle.events))


if __name__ == '__main__':
    unittest.main()
