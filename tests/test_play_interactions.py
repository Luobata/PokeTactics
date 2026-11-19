"""Prep interaction data (docs/62): read-only, explained, and consistent with the bots."""
import copy
import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for path in (ROOT / 'sim', ROOT / 'tools' / 'acceptance', ROOT / 'tools' / 'mockups'):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import arena  # noqa: E402
import arena_depth  # noqa: E402
import demo  # noqa: E402
import interaction_view  # noqa: E402
import items  # noqa: E402


def new_session(edition='v2', seed='2027'):
    result = demo._apply_action({'cmd': 'new', 'mode': 'arena', 'seed': seed, 'edition': edition})
    assert result['ok'], result
    return demo.SESSIONS[result['sid']], result['state']


def act(sess, cmd, **params):
    result = demo._apply_action({'cmd': cmd, 'sid': sess.sid, **{k: str(v) for k, v in params.items()}})
    assert result['ok'], result
    return result['state']


def field_team(sess):
    """Buy the whole shop with plenty of gold and deploy it, front row first."""
    sess.player.gold = 99
    shop = act(sess, 'state')['shop']
    for i, card in enumerate(shop):
        if card is not None:
            act(sess, 'buy', i=i)
    cells = [f'g{r},{c}' for r in range(3) for c in range(6)]
    while sess.player.bench and len(sess.player.grid) < sess.player.pop():
        act(sess, 'move', **{'from': 'b0', 'to': cells.pop(0)})
    return act(sess, 'state')


class ReadOnlyTest(unittest.TestCase):
    def test_building_the_view_never_changes_the_session(self):
        sess, _ = new_session()
        field_team(sess)
        before = json.dumps(act(sess, 'state'), sort_keys=True, ensure_ascii=False)
        snapshot = copy.deepcopy((sess.player.gold, sess.player.inventory.components,
                                  sess.player.inventory.finished, sess.arena_augments_pending))
        for _ in range(3):
            interaction_view.build(sess)
        self.assertEqual(snapshot, (sess.player.gold, sess.player.inventory.components,
                                    sess.player.inventory.finished, sess.arena_augments_pending))
        self.assertEqual(before, json.dumps(act(sess, 'state'), sort_keys=True, ensure_ascii=False))

    def test_state_carries_interactions_for_both_editions(self):
        for edition in ('v1', 'v2'):
            with self.subTest(edition=edition):
                _sess, state = new_session(edition)
                ix = state['interactions']
                self.assertNotIn('error', ix)
                self.assertEqual(set(ix), {'version', 'augments', 'techniques', 'skills', 'recipes', 'equip',
                                           'item_advice', 'item_synergy'})


class AugmentTest(unittest.TestCase):
    def test_pending_options_have_category_rarity_fit_and_reasons(self):
        sess, state = new_session()
        row = state['interactions']['augments']['pending'][0]
        self.assertEqual((row['rarity'], row['rarity_name'], row['rerolls_left']), ('silver', '银', 1))
        self.assertEqual([o['id'] for o in row['options']],
                         [o['id'] for o in state['augments']['pending'][0]['options']])
        for option in row['options']:
            self.assertIn(option['category_name'], interaction_view.CATEGORY_ZH.values())
            self.assertIn(option['fit'], ('high', 'mid', 'low'))
            self.assertTrue(option['reasons'])
            for reason in option['reasons']:
                self.assertEqual(set(reason), {'text', 'good'})
        self.assertEqual(sum(o['best'] for o in row['options']) >= 1, True)
        rerolled = act(sess, 'reroll_augment', id=row['id'])
        self.assertEqual(rerolled['interactions']['augments']['pending'][0]['rerolls_left'], 0)

    def test_rarity_follows_the_milestone(self):
        self.assertEqual(interaction_view.RARITY[7][0], 'gold')
        self.assertEqual(interaction_view.RARITY[13][0], 'prismatic')

    def test_bot_choice_is_the_best_augment_fit(self):
        sess, _ = new_session()
        field_team(sess)
        keys = sorted(arena.augment_pool(sess, sess.player))
        signals = arena.augment_signals(sess.player)
        for start in range(0, len(keys) - 2, 3):
            options = [arena.augment_view(k) for k in keys[start:start + 3]]
            best = max(options, key=lambda o: (arena.augment_fit(sess.player, o['id'], signals)[0], o['id']))
            self.assertEqual(arena.bot_augment_choice(sess.player, options)['id'], best['id'])

    def test_reasons_quote_the_visible_team(self):
        sess, _ = new_session()
        field_team(sess)
        signals = arena.augment_signals(sess.player)
        insight = interaction_view.augment_insight(sess, sess.player, 'charge_horn')
        texts = ' '.join(r['text'] for r in insight['reasons'])
        n = signals['melee']
        self.assertRegex(texts, rf'你有 {n} 只近战|近战只有 {n} 只')
        squad = interaction_view.augment_insight(sess, sess.player, 'elite_squad')
        pop = sess.player.pop()
        self.assertIn(f'人口上限 {pop} → {pop - 1}', squad['changes'])
        wield = interaction_view.augment_insight(sess, sess.player, 'dual_wield')
        self.assertIn('每只装备位 1 → 2', wield['changes'])

    def test_v1_conditional_augments_report_whether_the_condition_is_met(self):
        sess, _ = new_session('v1')
        field_team(sess)
        for key in ('poison_catalyst', 'watch_echo', 'barrier_feedback', 'native_inspiration', 'breach_momentum'):
            insight = interaction_view.augment_insight(sess, sess.player, key)
            self.assertEqual(insight['category'], 'condition')
            self.assertIn(insight['condition']['met'], (True, False))
            self.assertTrue(insight['reasons'][0]['text'].startswith('条件'))

    def test_selected_augments_carry_last_battle_ledger_rows(self):
        sess, _ = new_session()
        sess.player.arena_augments_selected.append(arena.augment_view('mana_siphon'))
        sess.last_battle = {'round': 3, 'ledger': [
            {'team': 0, 'source': 'augment', 'id': 'mana_siphon', 'triggers': 4, 'energy': 48},
            {'team': 1, 'source': 'augment', 'id': 'mana_siphon', 'triggers': 9, 'energy': 99}]}
        selected = interaction_view.augment_block(sess)['selected']
        row = next(r for r in selected if r['id'] == 'mana_siphon')
        self.assertEqual(row['last']['round'], 3)
        self.assertEqual([(r['triggers'], r['energy']) for r in row['last']['rows']], [(4, 48)])

    def test_last_rule_ledger_survives_into_the_next_prep_in_v2_only(self):
        for edition in ('v2', 'v1'):
            with self.subTest(edition=edition):
                sess, state = new_session(edition)
                pending = state['augments']['pending'][0]
                act(sess, 'claim_augment', id=pending['id'], choice=pending['options'][0]['id'])
                field_team(sess)
                act(sess, 'end_prep')
                state = act(sess, 'next')
                self.assertEqual(state['phase'], 'prep')
                selected = state['interactions']['augments']['selected'][0]
                if edition == 'v2':
                    self.assertEqual(sess.last_rule_ledger['round'], 1)
                    self.assertEqual(selected['last']['round'], 1)
                else:
                    self.assertIsNone(getattr(sess, 'last_rule_ledger', None))
                    self.assertIsNone(selected['last'])


class TechniqueTest(unittest.TestCase):
    def test_best_learner_is_compatible_and_the_top_teaching_fit(self):
        sess, _ = new_session()
        field_team(sess)
        block = interaction_view.technique_block(sess)
        ctx = arena.teaching_context(sess.player.board)
        owned = {o.uid: o for o in sess.player.all_pieces()}
        checked = 0
        for key, row in block.items():
            if row['best'] is None:
                continue
            checked += 1
            self.assertIn(row['best']['uid'], row['compatible'])
            self.assertTrue(row['best']['reasons'])
            top = max(arena.teaching_fit(ctx, owned[uid], key)[0] for uid in row['compatible']
                      if uid not in row['known_by'])
            self.assertEqual(row['best']['score'], top)
        self.assertGreater(checked, 3)

    def test_weather_pair_reason_matches_the_bot_bonus(self):
        sess, _ = new_session()
        field_team(sess)
        ctx = arena.teaching_context(sess.player.board)
        ctx = {**ctx, 'wants_rain': True}
        owned = sess.player.board[0]
        value, reasons = arena.teaching_fit(ctx, owned, 'rain_dance')
        self.assertGreaterEqual(value, 4)
        self.assertTrue(any('雨天' in text for text in reasons))


class SkillTest(unittest.TestCase):
    def test_skill_cards_and_pending_mods_with_deltas(self):
        sess, _ = new_session()
        field_team(sess)
        owned = sess.player.board[0]
        owned.piece.star = 2
        rows = interaction_view.skill_block(sess)
        card = rows[owned.uid]
        self.assertTrue(card['glyph'])
        self.assertIn('category_name', card)
        self.assertEqual(len(card['mods']), 2)
        for mod in card['mods']:
            self.assertIn(mod['id'], arena_depth.MODS)
            self.assertTrue(mod['delta'])

    def test_v1_has_no_star_up_mods(self):
        sess, _ = new_session('v1')
        field_team(sess)
        sess.player.board[0].piece.star = 2
        self.assertEqual(interaction_view.skill_block(sess)[sess.player.board[0].uid]['mods'], [])


class RecipeTest(unittest.TestCase):
    def test_matrix_covers_every_pair_and_marks_dead_and_depth_cells(self):
        v2, _ = new_session('v2')
        v1, _ = new_session('v1')
        cells2 = interaction_view.recipe_block(v2)['cells']
        cells1 = interaction_view.recipe_block(v1)['cells']
        self.assertEqual(len(cells2), 36)
        self.assertEqual(len(cells1), 36)
        self.assertEqual(sum(c['dead'] for c in cells2), 0)
        craftable_depth = sorted({c['item'] for c in cells2 if c['depth']})
        self.assertEqual(craftable_depth, sorted(k for k, spec in arena_depth.DEPTH_ITEMS.items() if spec['pairs']))
        import arena_mech_items
        original = [spec for key, spec in arena_depth.DEPTH_ITEMS.items()
                    if key not in arena_mech_items.MECH_ITEMS and spec['pairs']]
        self.assertEqual(sorted(tuple(sorted((c['a'], c['b']))) for c in cells1 if c['dead']),
                         sorted(tuple(sorted(spec['pairs'][0])) for spec in original))

    def test_craftable_cells_agree_with_the_inventory(self):
        sess, _ = new_session('v2')
        inv = sess.player.inventory
        inv.components.update({'band': 2, 'magnet': 1, 'shoes': 0})
        cells = interaction_view.recipe_block(sess)['cells']
        by_pair = {(c['a'], c['b']): c for c in cells}
        self.assertTrue(by_pair[('band', 'band')]['craftable'])        # metronome: band ×2
        self.assertTrue(by_pair[('band', 'magnet')]['craftable'])      # boomerang (v2 replaces 专爱头巾)
        self.assertFalse(by_pair[('magnet', 'shoes')]['craftable'])    # quick_claw needs shoes
        self.assertEqual(by_pair[('magnet', 'shoes')]['missing'], ['加速鞋'])
        for cell in cells:
            if cell['craftable']:
                self.assertIsNotNone(inv.craftable(cell['item']))
        state = act(sess, 'craft', item='boomerang')
        after = {(c['a'], c['b']): c for c in state['interactions']['recipes']['cells']}
        self.assertFalse(after[('band', 'magnet')]['craftable'])
        self.assertEqual(after[('band', 'magnet')]['missing'], ['磁铁线圈'])
        self.assertIn('boomerang', state['interactions']['equip']['items'])


class EquipTest(unittest.TestCase):
    def test_carriers_are_ranked_with_reasons_and_slots_reported(self):
        for edition, cost in (('v2', 1), ('v1', 0)):
            with self.subTest(edition=edition):
                sess, _ = new_session(edition)
                field_team(sess)
                sess.player.inventory.finished.extend(['metronome', 'leftovers', 'choice_band'])
                block = interaction_view.equip_block(sess)
                self.assertEqual(block['unequip_cost'], cost)
                for key in ('metronome', 'leftovers', 'choice_band'):
                    row = block['items'][key]
                    self.assertLessEqual(len(row['carriers']), 3)
                    scores = [c['score'] for c in row['carriers'] if c['free']]
                    self.assertEqual(scores, sorted(scores, reverse=True))
                    for carrier in row['carriers']:
                        self.assertIn(' · ', carrier['reason'])
                self.assertTrue(block['items']['choice_band']['lines'])
                for uid, slot in block['slots'].items():
                    self.assertGreaterEqual(slot['total'], 1)
                    self.assertLessEqual(slot['used'], slot['total'])

    def test_component_stat_lines_only_in_the_depth_edition(self):
        v2, _ = new_session('v2')
        v1, _ = new_session('v1')
        for sess in (v2, v1):
            sess.player.inventory.finished.append('sash')
        self.assertEqual(interaction_view.equip_block(v2)['items']['sash']['stats'],
                         arena_depth.item_stats_text('sash').split('、'))
        self.assertEqual(interaction_view.equip_block(v1)['items']['sash']['stats'], [])
        self.assertIn('致命伤保留 1 生命（每场一次）', interaction_view.spec_lines('sash'))
        self.assertIn('攻击 / 特攻 +35%', interaction_view.spec_lines('choice_band'))
        self.assertEqual(items.FINISHED['sash']['name'], interaction_view.equip_block(v2)['items']['sash']['name'])


NODE = shutil.which('node')
ACCEPTANCE = ROOT / 'tools' / 'acceptance'


@unittest.skipUnless(NODE, 'Node.js is needed to execute the play-page handlers')
class FrontendMomentsTest(unittest.TestCase):
    def run_scenario(self, scenario):
        result = subprocess.run(
            [NODE, str(ROOT / 'tests/frontend/play_interactions_presentation.js'),
             str(ACCEPTANCE / 'play_layout.js'), str(ACCEPTANCE / 'play_interactions.js'),
             str(ACCEPTANCE / 'play.js'), str(ACCEPTANCE / 'play.html'), scenario],
            capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_augment_moment_renders_fit_defers_reopens_and_claims(self):
        self.run_scenario('augmentMoment')

    def test_machine_targeting_lights_compatible_units_and_confirms_learning(self):
        self.run_scenario('tmTargeting')

    def test_recipe_board_marks_craftable_near_and_dead_cells_and_crafts(self):
        self.run_scenario('recipeBoard')

    def test_equip_ranks_carriers_previews_slots_and_equips(self):
        self.run_scenario('equipPreview')

    def test_item_advice_strip_filters_combos_equip_and_chase(self):
        self.run_scenario('itemAdvice')

    def test_craft_advice_crafts_then_offers_the_carrier(self):
        self.run_scenario('itemAdviceCraft')

    def test_star_up_mod_choice_opens_and_can_be_deferred(self):
        self.run_scenario('skillMod')

    def test_star_up_mod_choice_sends_the_unit_location(self):
        self.run_scenario('skillModPick')

    def test_unit_detail_shows_native_skill_card_and_learn_socket(self):
        self.run_scenario('skillCard')


if __name__ == '__main__':
    unittest.main()
