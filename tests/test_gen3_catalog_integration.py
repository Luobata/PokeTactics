"""Gen3 family expansion must stay explicit in catalogs and portable saves."""
import random
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'sim'), str(ROOT / 'tools/acceptance')]

import arena_gen3
import arena
import arena_skills
import arena_traits
import arena_families as families
from combat import Battle
import demo
import status
from combination_view import NAMES, battle_summary, field_summary
from session_save import SessionCodec


GEN3_SPECIES = set(arena_gen3.ROLES)


class Gen3CatalogIntegration(unittest.TestCase):
    def test_skill_catalog_default_is_frozen_and_full_scope_is_explicit(self):
        default = arena_skills.catalog()
        full = arena_skills.catalog(include_families=True)
        self.assertEqual(len(default), 62)
        self.assertEqual({row['sid'] for row in default}, set(arena_skills.SKILLS))
        self.assertEqual(len(full), 151)
        self.assertEqual({row['sid'] for row in full}, set(arena_skills.SKILLS) | set(families.SPECIES_FAMILY))
        self.assertEqual({row['sid'] for row in full if row['sid'] in GEN3_SPECIES}, GEN3_SPECIES)
        self.assertEqual({row['id'] for row in full if row['sid'] in GEN3_SPECIES},
                         {row['id'] for row in arena_gen3.SKILLS.values()})

    def test_trait_catalog_default_is_frozen_and_full_scope_is_explicit(self):
        default = arena_traits.catalog()
        full = arena_traits.catalog(include_families=True)
        self.assertEqual(len(default), 65)
        self.assertEqual({row['species'] for row in default}, set(arena_traits.TRAITS))
        self.assertEqual(len(full), 153)
        self.assertLessEqual(set(arena_traits.TRAITS), {row['species'] for row in full})
        self.assertEqual({row['species'] for row in full if row['species'] in GEN3_SPECIES},
                         GEN3_SPECIES)
        self.assertIn('trait_overgrow', {row['id'] for row in full})

    def test_demo_move_translation_and_session_trait_catalog_follow_pool_version(self):
        previous_cache = demo._MOVES_ZH
        demo._MOVES_ZH = None
        try:
            self.assertEqual(demo._move_zh('arena_spark_chain'), '电流链')
            self.assertEqual(demo._move_zh('arena_hoenn_cross_bullet_252'), '新芽连射')
        finally:
            demo._MOVES_ZH = previous_cache

        for version, expected_templates in (('families_v1', families.build_templates(families.FIRST_VERSION)),
                                            ('families_v2', families.build_templates(families.VERSION))):
            with self.subTest(version=version):
                session = demo.Session(1003, 'arena_v1', arena_pool=version)
                session.begin_round(1)
                catalog = demo.state_json(session)['arena']['trait_catalog']
                covered = {row['species'] for row in catalog}
                self.assertLessEqual(covered, set(expected_templates))
                self.assertGreater(covered, set())
                if version == 'families_v1':
                    self.assertFalse(any(sid >= 252 for sid in covered))
                else:
                    self.assertEqual(GEN3_SPECIES & covered, GEN3_SPECIES)

    def test_telemetry_accepts_gen3_traits_without_renaming_legacy_hooks(self):
        self.assertEqual(NAMES['trait_overgrow'], '茂盛')
        self.assertEqual(NAMES['trait_sturdy'], '结实')

    def test_real_overgrow_summary_survives_save_roundtrip(self):
        caster = families.make_piece(252)
        target = families.make_piece(4)
        battle = Battle([caster], [target], random.Random(1003),
                        ruleset='arena_v1', stat_mode='budget_v1',
                        positions_a=[(2, 3)], positions_b=[(2, 2)],
                        arena_teams=[[], []])
        source, patient = battle.units
        source.hp, source.max_hp = 3000, 9000
        source.energy = arena_skills.ENERGY_MAX
        patient.hp = patient.max_hp = 10000
        with patch.object(battle, '_move_damage', return_value=100),                 patch.object(status, 'on_hit'):
            actual = battle._land_hit(
                source, patient, 100, 2., primary=True, cast=True,
                move=arena_skills.resolve_cast(source.piece), direct=True)
        self.assertEqual(actual, 125)
        self.assertEqual(patient.hp, 9875)

        teams = {unit.idx: unit.team for unit in battle.units}
        summary = battle_summary(battle.events, teams, team=0)
        row = next(item for item in summary['by_key'] if item['id'] == 'trait_overgrow')
        self.assertGreater(row['triggers'], 0)
        self.assertGreater(row['damage'], 0)
        SessionCodec._validate_combination_summary(summary)

        session = demo.Session(1003, 'arena_v1', arena_pool=families.VERSION)
        session.begin_round(1)
        session.phase = 'battle'
        # Consume this round's real preparation reward before hand-building a
        # settled battle report, keeping the augment lifecycle internally valid.
        for reward in list(session.arena_augments_pending):
            arena.claim_augment(session, reward['id'], reward['options'][0]['id'])
        session.last_battle = {
            'round': 1, 'winner': 0, 'survivors': {0: 1, 1: 1}, 'duration': 2.,
            'pve': False, 'ghost': False, 'opp_name': '验收对手',
            'statistics': battle.statistics(), 'effect_version': 1,
            'combinations': summary,
            'enemy_combinations': battle_summary(battle.events, teams, team=1),
            'fields': field_summary(battle.events, teams, team=0),
            'enemy_fields': field_summary(battle.events, teams, team=1),
        }
        codec = SessionCodec()
        encoded = codec.encode(session)
        restored = codec.decode(encoded, 5)
        restored_row = next(item for item in restored.last_battle['combinations']['by_key']
                            if item['id'] == 'trait_overgrow')
        self.assertEqual(restored_row, row)
        self.assertGreater(restored_row['triggers'], 0)
        self.assertGreater(restored_row['damage'], 0)


if __name__ == '__main__':
    unittest.main()
