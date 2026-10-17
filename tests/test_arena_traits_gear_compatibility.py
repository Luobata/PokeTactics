"""Fixed passives are forward combat rules, without replay or save-ledger changes."""
import copy
from arena_save_expectations import with_synergy_defaults
from contextlib import ExitStack
from collections import Counter
import hashlib
import json
from pathlib import Path
import random
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'sim'), str(ROOT / 'tools/acceptance')]
import arena_rewards
import demo
import items
from esp32_runtime import SaveStore
from session_save import SessionCodec, PRE_TRAITS_GEAR_FINGERPRINT, UnknownRulesError

STAGES = ('prep', 'settled', 'r3-prep', 'r3-settled', 'r4-deferred-prep',
          'r4-claimed-prep', 'r6-prep', 'r6-settled', 'r7-claimed-prep')
NEW_ITEMS = ('drain_fang', 'tide_shell', 'dew_charm', 'torrent_orb',
             'pulse_band', 'relay_coil', 'grounding_cloak', 'storm_chime')


def fast_render(a, b, battle_rng, weather_name, out_dir, positions_a=None,
                hud_snapshot=None, **options):
    from combination_view import battle_summary, field_summary
    battle = demo.Battle(a, b, battle_rng, layout='back', weather_name=weather_name,
                        positions_a=positions_a, **options)
    result = battle.run()
    teams = {unit.idx: unit.team for unit in battle.units}
    return {**result, 'n': 0, 'events': [], 'statistics': battle.statistics(),
            'combinations': battle_summary(battle.events, teams),
            'fields': field_summary(battle.events, teams)}


class ArenaTraitsGearCompatibility(unittest.TestCase):
    def setUp(self):
        self.codec = SessionCodec()

    @staticmethod
    def fixture(stage):
        return json.loads((ROOT / f'tests/fixtures/arena-v5-pre-traits-gear-{stage}.json').read_text())

    def no_gameplay_decode(self, payload):
        with ExitStack() as stack:
            for owner, name in ((demo.Session, 'begin_round'), (demo.Session, 'end_prep'),
                                (demo.Session, 'next_round'), (demo.Session, '_grant_arena_loot'),
                                (demo.Session, '_grant_arena_component_choice'),
                                (demo.Bot, 'decide'), (demo.shop_mod.Shop, 'roll'),
                                (demo, '_render_battle_frames'), (arena_rewards, 'roll_rewards'),
                                (arena_rewards, 'grant_rewards'), (arena_rewards, 'component_choice'),
                                (arena_rewards, 'claim_component'), (arena_rewards, 'bot_component_choice')):
                stack.enter_context(patch.object(owner, name,
                    side_effect=AssertionError(f'loading must not invoke {name}')))
            return self.codec.decode(payload, 5)

    def test_exact_real_predecessors_preserve_all_committed_fields(self):
        for stage in STAGES:
            with self.subTest(stage=stage):
                old = self.fixture(stage)
                self.assertEqual(old['rules'], PRE_TRAITS_GEAR_FINGERPRINT)
                untouched = copy.deepcopy(old)
                restored = self.no_gameplay_decode(old)
                current = self.codec.encode(restored)
                expected = with_synergy_defaults(old)
                expected['rules'] = current['rules']
                self.assertEqual(current, expected)
                self.assertEqual(old, untouched)
                self.assertIn('历史战斗结果不会重算', restored.save_warning)
                self.assertNotIn('竞技池已扩', restored.save_warning)
                self.assertEqual(self.codec.encode(self.no_gameplay_decode(current)), current)
                self.assertNotIn('traits', current['arena'])
                self.assertNotIn('passive_selections', current['arena'])

    def test_predecessor_with_existing_supplies_cannot_use_any_missing_field_fallback(self):
        for kind in ('pool', 'machine', 'history', 'choices', 'choice_start', 'both_choices'):
            with self.subTest(kind=kind):
                payload = self.fixture('r6-settled')
                if kind == 'pool':
                    del payload['pool']['162']
                elif kind == 'machine':
                    del payload['seats'][0]['techniques']['roar']
                elif kind == 'history':
                    del payload['battle_history']
                elif kind == 'choices':
                    del payload['arena']['component_choices']
                elif kind == 'choice_start':
                    del payload['arena']['component_choice_start']
                else:
                    del payload['arena']['component_choices']
                    del payload['arena']['component_choice_start']
                with self.assertRaises(ValueError):
                    self.no_gameplay_decode(payload)

    def test_predecessor_corrupt_ledgers_remain_strict(self):
        for kind in ('duplicate_loot', 'duplicate_supply', 'unknown_component',
                     'foreign_run', 'claimed_without_choice', 'history_winner',
                     'trait_selection'):
            with self.subTest(kind=kind):
                payload = self.fixture('r6-settled')
                if kind == 'duplicate_loot':
                    payload['arena']['loot'].append(copy.deepcopy(payload['arena']['loot'][0]))
                elif kind == 'duplicate_supply':
                    payload['arena']['component_choices'].append(copy.deepcopy(payload['arena']['component_choices'][0]))
                elif kind == 'unknown_component':
                    payload['arena']['component_choices'][0]['options'][0] = 'unknown-component'
                elif kind == 'foreign_run':
                    payload['arena']['component_choices'][0]['id'] = 'foreign-run:r3:s0:component'
                elif kind == 'claimed_without_choice':
                    payload['arena']['component_choices'][0]['choice'] = None
                    payload['arena']['component_choices'][0]['status'] = 'claimed'
                elif kind == 'trait_selection':
                    payload['arena']['passive_selections'] = []
                else:
                    winner = payload['battle_history'][-1]['winner']
                    payload['battle_history'][-1]['winner'] = 1 if winner == 0 else 0
                with self.assertRaises(ValueError):
                    self.no_gameplay_decode(payload)

    def test_settled_milestones_do_not_issue_new_loot_or_component_choices(self):
        for stage in ('r3-settled', 'r6-settled'):
            with self.subTest(stage=stage):
                session = self.no_gameplay_decode(self.fixture(stage))
                before = self.codec.encode(session)
                participants = [row for row in session.arena_loot if row['round'] == session.round_no]
                for row in participants:
                    seat = session.seats[row['seat']]
                    session._grant_arena_loot(seat, row['result'])
                    session._grant_arena_component_choice(seat)
                self.assertEqual(self.codec.encode(session), before)

    def test_deferred_supply_claim_grants_one_component_and_duplicate_is_idempotent(self):
        session = self.no_gameplay_decode(self.fixture('r4-deferred-prep'))
        supply = next(row for row in session.arena_component_choices if row['seat'] == 0)
        before = session.player.inventory.components['mysticwater']
        history = copy.deepcopy(session.battle_history)
        demo.act_claim_component(session, supply['id'], 'mysticwater')
        self.assertEqual(session.player.inventory.components['mysticwater'], before + 1)
        self.assertEqual(session.battle_history, history)
        snapshot = self.codec.encode(session)
        restored = self.no_gameplay_decode(snapshot)
        demo.act_claim_component(restored, supply['id'], 'mysticwater')
        self.assertEqual(self.codec.encode(restored), snapshot)
        with self.assertRaises(demo.DemoError):
            demo.act_claim_component(restored, supply['id'], 'spark')
        self.assertEqual(self.codec.encode(restored), snapshot)

    def test_both_predecessor_claimed_supplies_keep_their_original_choices(self):
        session = self.no_gameplay_decode(self.fixture('r7-claimed-prep'))
        before = self.codec.encode(session)
        choices = {row['round']: row for row in session.arena_component_choices if row['seat'] == 0}
        self.assertEqual({round_no: row['choice'] for round_no, row in choices.items()},
                         {3: 'mysticwater', 6: 'spark'})
        for row in choices.values():
            demo.act_claim_component(session, row['id'], row['choice'])
        self.assertEqual(self.codec.encode(session), before)

    def test_new_recipes_craft_equip_and_roundtrip_using_existing_inventory_schema(self):
        for key in NEW_ITEMS:
            with self.subTest(item=key):
                session = self.no_gameplay_decode(self.fixture('prep'))
                demo.act_unequip(session, 'g0,1')
                for component, count in Counter(items.catalog('arena_v1')[key]['pairs'][0]).items():
                    session.player.inventory.components[component] += count
                components = copy.deepcopy(session.player.inventory.components)
                demo.act_craft(session, key)
                for component, count in Counter(items.catalog('arena_v1')[key]['pairs'][0]).items():
                    self.assertEqual(session.player.inventory.components[component], components[component] - count)
                demo.act_equip(session, key, 'g0,1')
                snapshot = self.codec.encode(session)
                restored = self.no_gameplay_decode(snapshot)
                self.assertEqual(self.codec.encode(restored), snapshot)
                self.assertEqual(restored.player.grid[(0, 1)].item, key)
                self.assertEqual(set(snapshot['arena']) - {'meta', 'research'},
                                 set(self.fixture('prep')['arena']))
                self.assertEqual(snapshot['battle_history'], [])

    def test_new_arena_equipment_is_not_accepted_by_classic_saves(self):
        old = json.loads((ROOT / 'tests/fixtures/classic-v5-pre-traits-gear-prep.json').read_text())
        for key in NEW_ITEMS:
            with self.subTest(item=key):
                forged = copy.deepcopy(old)
                forged['seats'][0]['finished'].append(key)
                with self.assertRaises(ValueError):
                    self.no_gameplay_decode(forged)

    def test_future_current_battle_preserves_every_old_history_entry(self):
        old = self.fixture('r3-settled')
        session = self.no_gameplay_decode(old)
        history = copy.deepcopy(old['battle_history'])
        session.next_round()
        with patch.object(demo, '_render_battle_frames', side_effect=fast_render):
            session.end_prep()
        self.assertEqual(session.round_no, 4)
        self.assertEqual(session.battle_history[:-1], history)
        self.assertEqual(session.battle_history[-1]['round'], 4)
        snapshot = self.codec.encode(session)
        self.assertEqual(self.codec.encode(self.no_gameplay_decode(snapshot)), snapshot)

    def test_classic_exact_predecessor_and_four_battle_oracles_are_preserved(self):
        old = json.loads((ROOT / 'tests/fixtures/classic-v5-pre-traits-gear-prep.json').read_text())
        self.assertEqual(old['rules'], PRE_TRAITS_GEAR_FINGERPRINT)
        untouched = copy.deepcopy(old)
        current = self.codec.encode(self.no_gameplay_decode(old))
        expected = with_synergy_defaults(old)
        expected['rules'] = current['rules']
        self.assertEqual(current, expected)
        self.assertEqual(old, untouched)
        self.assertNotIn('arena', current)
        oracle = json.loads((ROOT / 'tests/fixtures/classic-pre-traits-gear-battles.json').read_text())
        self.assertEqual(oracle['rules'], PRE_TRAITS_GEAR_FINGERPRINT)
        templates = demo.build_templates()
        for case in oracle['cases']:
            with self.subTest(seed=case['seed']):
                battle = demo.Battle([copy.copy(demo.make_piece(sid, templates)) for sid in case['a']],
                                    [copy.copy(demo.make_piece(sid, templates)) for sid in case['b']],
                                    random.Random(case['seed']))
                result = {key: value for key, value in battle.run().items()
                          if key in ('winner', 'survivors', 'duration')}
                self.assertEqual(json.loads(json.dumps(result)), case['result'])
                self.assertEqual([unit.hp for unit in battle.units], case['hp'])
                self.assertEqual(battle.statistics(), case['statistics'])

    def test_all_three_old_combination_summary_shapes_roundtrip_verbatim(self):
        totals = {'triggers', 'total_energy', 'total_shield', 'absorbed', 'by_key'}
        extra_totals = {'total_charges', 'total_damage', 'damage_absorbed', 'total_vulnerable'}
        attack_totals = {'total_spreads', 'total_tempo_stacks', 'total_offense_buffs'}
        base_row = {'id', 'name', 'triggers', 'energy', 'shield', 'absorbed'}
        extra_row = {'charges', 'damage', 'damage_absorbed', 'vulnerable'}
        attack_row = {'spreads', 'tempo_stacks', 'offense_buffs'}
        for top_fields, row_fields in ((totals, base_row),
                                      (totals | extra_totals, base_row | extra_row),
                                      (totals | extra_totals | attack_totals,
                                       base_row | extra_row | attack_row)):
            with self.subTest(fields=sorted(top_fields)):
                old = self.fixture('r3-settled')
                old['last_battle']['combinations'] = {
                    key: value for key, value in old['last_battle']['combinations'].items()
                    if key in top_fields}
                old['last_battle']['combinations']['by_key'] = [
                    {key: value for key, value in row.items() if key in row_fields}
                    for row in old['last_battle']['combinations']['by_key']]
                untouched = copy.deepcopy(old)
                current = self.codec.encode(self.no_gameplay_decode(old))
                expected = with_synergy_defaults(old)
                expected['rules'] = current['rules']
                self.assertEqual(current, expected)
                self.assertEqual(old, untouched)

    def test_new_combination_shape_rejects_forged_totals_negative_bool_unknown_and_partial_rows(self):
        import arena_traits
        from combination_view import battle_summary
        summary = battle_summary([], {})
        totals_to_rows = {
            'triggers': 'triggers', 'total_energy': 'energy', 'total_shield': 'shield',
            'absorbed': 'absorbed', 'total_charges': 'charges', 'total_damage': 'damage',
            'damage_absorbed': 'damage_absorbed', 'total_vulnerable': 'vulnerable',
            'total_spreads': 'spreads', 'total_tempo_stacks': 'tempo_stacks',
            'total_offense_buffs': 'offense_buffs', 'total_healing': 'healing',
            'total_cleanses': 'cleanses', 'total_statuses': 'statuses',
            'total_mitigated': 'mitigated', 'total_accuracy_saves': 'accuracy_saves',
            'total_weakens': 'weakens',
        }
        self.assertEqual(set(summary), set(totals_to_rows) | {'by_key'})
        trait = next(spec for spec in arena_traits.catalog() if spec['id'] == 'trait_healer')
        row = {'id': trait['id'], 'name': trait['name'],
               **{key: 0 for key in totals_to_rows.values()}}
        row.update(triggers=1, healing=5)
        summary.update(triggers=1, total_healing=5, by_key=[row])
        self.codec._validate_combination_summary(summary)
        for kind in ('forged_total', 'negative', 'bool', 'unknown', 'duplicate',
                     'partial_total', 'partial_row', 'wrong_name'):
            with self.subTest(kind=kind):
                malformed = copy.deepcopy(summary)
                if kind == 'forged_total':
                    malformed['total_healing'] = 6
                elif kind == 'negative':
                    malformed['by_key'][0]['healing'] = -1
                elif kind == 'bool':
                    malformed['by_key'][0]['cleanses'] = True
                elif kind == 'unknown':
                    malformed['by_key'][0]['id'] = 'trait_unknown'
                elif kind == 'duplicate':
                    malformed['by_key'].append(copy.deepcopy(row))
                elif kind == 'partial_total':
                    del malformed['total_mitigated']
                elif kind == 'partial_row':
                    del malformed['by_key'][0]['mitigated']
                else:
                    malformed['by_key'][0]['name'] = 'wrong name'
                with self.assertRaises(ValueError):
                    self.codec._validate_combination_summary(malformed)

    def test_unknown_newer_bank_never_recovers_an_older_known_rules_snapshot(self):
        def raw(payload, sequence):
            def canonical(value):
                return json.dumps(value, ensure_ascii=False, sort_keys=True,
                                  separators=(',', ':'), allow_nan=False).encode()
            body = {'game_id': 'poketactics', 'storage_version': 1,
                    'schema_version': 5, 'sequence': sequence, 'payload': payload}
            body['checksum'] = hashlib.sha256(canonical(body)).hexdigest()
            return canonical(body)
        known = self.fixture('r6-settled')
        unknown = copy.deepcopy(known)
        unknown['rules'] = 'unknown-future-traits-gear-version'

        class ReadOnlyBanks:
            def read(self, namespace, key):
                return {'autosave.0': raw(known, 3), 'autosave.1': raw(unknown, 4)}.get(key)
            def write_atomic(self, *args):
                raise AssertionError('loading cannot write banks')
            def delete(self, *args):
                raise AssertionError('loading cannot remove banks')

        with self.assertRaises(UnknownRulesError):
            SaveStore(ReadOnlyBanks(), self.codec).load()


if __name__ == '__main__':
    unittest.main()
