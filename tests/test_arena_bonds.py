"""Member-only panels and tactical bonds consume authoritative combat facts."""
import copy
import random
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'sim'))
import arena
import arena_bonds as bonds
import arena_families as families
import arena_fields
import arena_combinations as combos
import arena_fields as fields
import arena_offense as offense
import arena_skills
import combo
import status
import synergy
from combat import Battle
from data import ENERGY_MAX, MOVE_TICK, melee_move_mult
from shop import OwnedPiece


class ArenaBondRules(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.templates = arena.build_templates()

    def battle(self, friends=(34, 73), enemies=(68, 40, 40), *, items=(),
               augments=(), ruleset='arena_v1', normalize=True):
        item_map = dict(items)
        def comp(ids):
            return [(copy.copy(self.templates[sid]), item_map[i]) if i in item_map
                    else copy.copy(self.templates[sid]) for i, sid in enumerate(ids)]
        a, b = comp(friends), [copy.copy(self.templates[sid]) for sid in enemies]
        own_rows = 3 if ruleset == 'arena_v1' else 2
        pos_a = [(x, y) for y in range(own_rows, own_rows * 2) for x in (2, 1, 3, 0, 4, 5)]
        pos_b = [(x, y) for y in range(own_rows - 1, -1, -1) for x in (2, 1, 3, 0, 4, 5)]
        battle = Battle(a, b, random.Random(733), ruleset=ruleset, stat_mode='budget_v1',
                        positions_a=pos_a[:len(a)], positions_b=pos_b[:len(b)],
                        arena_teams=[list(augments), []] if ruleset == 'arena_v1' else None)
        if normalize:
            for u in battle.units:
                u.max_hp = u.hp = 1000
                u.energy = 0
                if hasattr(u, '_st'):
                    u._st.ctrl_until = 1000.
        return battle

    @staticmethod
    def effects(battle, key, effect=None):
        return [e for e in battle.events if e[1] == 'combo_effect' and e[4] == key
                and (effect is None or e[5] == effect)]

    def tick(self, battle, t):
        battle.duration = t
        status.tick(battle, t)

    def cast(self, battle, source, t):
        battle.duration, source.energy = t, ENERGY_MAX
        target = next(u for u in battle.units if u.team != source.team and u.alive)
        with patch('combat._damage', return_value=50), patch.object(status, 'on_hit'):
            return arena_skills.cast(battle, source, target, t)

    def basic(self, battle, source, target, t, damage=10):
        battle.duration, source.energy = t, 0
        with patch('combat._damage', return_value=damage), patch.object(status, 'on_hit'), \
                patch.object(battle, '_final_damage', side_effect=lambda a, b, move, raw: raw):
            battle._strike(source, target, t)

    def test_count_unique_species_not_copies_stars_items_or_owned_wrappers(self):
        a, duplicate, b = [copy.copy(self.templates[sid]) for sid in (34, 34, 73)]
        duplicate.star, duplicate.shiny = 3, True
        owned = OwnedPiece(duplicate, 18)
        self.assertEqual(bonds.count([a, (duplicate, 'metronome'), owned, b]),
                         bonds.count([a, b]))
        self.assertEqual(bonds.count([a, duplicate])['POISON'], 1)
        self.assertEqual(bonds.count([a, b])['bond_erosion'], 2)
        self.assertEqual(bonds.count([a, b])['POISON'], 2)

    def test_catalogue_matches_current_pool_types_and_reachable_tiers(self):
        catalog = bonds.catalog()
        self.assertEqual(len(catalog), 25)
        self.assertEqual({row['id'] for row in catalog}, set(bonds.ELEMENT_TIERS) | set(bonds.TACTICS))
        for row in catalog:
            self.assertLessEqual(max(step['count'] for step in row['thresholds']), row['pool_size'])
            self.assertEqual(len(set(row['members'])), row['pool_size'])
            self.assertTrue(set(row['members']) <= arena.ROSTER.keys())
            if row['category'] == 'element':
                expected = {sid for sid, p in self.templates.items() if row['element'] in p.types}
                self.assertEqual(set(row['members']), expected)
        for sid in self.templates:
            self.assertLessEqual(sum(key.startswith('bond_') for key in bonds.memberships(sid)), 2)
        for key in ('ICE', 'GHOST', 'DRAGON'):
            self.assertEqual(list(bonds.ELEMENT_TIERS[key]), [1])
        self.assertEqual(list(bonds.ELEMENT_TIERS['FIRE']), [2, 3])
        self.assertEqual(list(bonds.ELEMENT_TIERS['STEEL']), [2])
        self.assertEqual(list(bonds.ELEMENT_TIERS['DARK']), [2])

    def test_catalogue_views_do_not_mutate_rule_tables(self):
        row = bonds.catalog()[0]
        row['members'].clear()
        row['thresholds'][0]['effects'].clear()
        self.assertTrue(bonds.catalog()[0]['members'])
        self.assertEqual(bonds.ELEMENT_TIERS['POISON'][2], {'dmg': .04})

    def test_preparation_keeps_missing_tier_and_candidate_identity_explicit(self):
        comp = [self.templates[34]] * 3
        preview = bonds.preparation(comp)
        row = next(r for r in preview['entries'] if r['id'] == 'bond_erosion')
        self.assertEqual((row['n'], row['tier'], row['next'], row['need']), (1, 0, 2, 1))
        self.assertEqual(row['members'], [34])
        self.assertEqual(row['candidates'], [6, 31, 73, 157, 211])
        self.assertEqual(row['effect'], '')
        filtered = bonds.preparation(comp, available=[OwnedPiece(self.templates[31], 1), 26, 999])
        row = next(r for r in filtered['entries'] if r['id'] == 'bond_erosion')
        self.assertEqual(row['candidates'], [31])
        self.assertNotIn('WATER', {r['id'] for r in preview['entries']})
        self.assertEqual(bonds.preparation([])['entries'], [])

    def test_element_panels_only_touch_corresponding_members_and_dual_types_add(self):
        ids = (3, 45, 26)
        live = self.battle(ids, (68,), normalize=False)
        with patch.object(synergy, 'SYNERGIES_ON', False):
            control = self.battle(ids, (68,), normalize=False)
        grass, second, outsider = live.units[:3]
        self.assertEqual((grass.synergy_dmg, grass.synergy_heal), (.04, .003))
        self.assertEqual((second.synergy_dmg, second.synergy_heal), (.04, .003))
        panel = ('max_hp', 'attack', 'sp_attack', 'defense', 'sp_defense', 'attack_interval',
                 'synergy_dmg', 'synergy_dr', 'synergy_heal', 'synergy_energy')
        self.assertEqual([getattr(outsider, key) for key in panel],
                         [getattr(control.units[2], key) for key in panel])
        self.assertEqual(grass.max_hp, control.units[0].max_hp)
        # The 3-cost grass member has the same defined regeneration fraction.
        self.assertEqual(grass.synergy_heal, second.synergy_heal)

    def test_repeated_species_cannot_unlock_member_panels_or_tactics(self):
        live = self.battle((34,) * 6, (68,), normalize=False)
        self.assertTrue(all(u.synergy_dmg == 0 and not u.bond_tiers['bond_erosion']
                            and not u.bond_tiers['bond_combo'] for u in live.units[:6]))
        self.assertEqual(bonds.count(live._plain_comps[0])['POISON'], 1)

    def test_all_four_tactical_groups_need_fixed_members_not_role_counts(self):
        for key, spec in bonds.TACTICS.items():
            threshold = max(bonds.TACTICS[key]['tiers'])
            comp = [self.templates[sid] for sid in bonds._tactic_members(spec)[:threshold]]
            self.assertEqual(bonds.tier_of(bonds.count(comp)[key], key), threshold)
            if threshold > 1:
                self.assertEqual(bonds.tier_of(bonds.count(comp[:threshold - 1])[key], key),
                                 max((tier for tier in bonds.TACTICS[key]['tiers']
                                      if tier < threshold), default=0))
            if min(bonds.TACTICS[key]['tiers']) > 1:
                self.assertEqual(bonds.tier_of(bonds.count(comp[:1])[key], key), 0)
            else:
                self.assertEqual(bonds.tier_of(bonds.count([]).get(key, 0), key), 0)
        self.assertEqual(bonds.count([self.templates[sid] for sid in (9, 80, 128, 195)]).get('bond_guard', 0), 0)
        self.assertNotIn('bond_inspiration', bonds.memberships(113))

    def test_synergy_switch_disables_arena_panels_and_tactics_together(self):
        with patch.object(synergy, 'SYNERGIES_ON', False):
            b = self.battle((34, 73, 31, 6), (68,))
        source, _, _, _, patient = b.units
        self.assertEqual(source.bond_tiers, {'bond_erosion': 0, 'bond_combo': 0})
        self.assertEqual(source.synergy_dmg, 0)
        status.apply_debuff(b, patient, 'poison', 0., source=source)
        for t in (1., 2., 3.):
            self.tick(b, t)
        self.assertFalse(self.effects(b, 'bond_erosion'))

    def test_classic_repeated_attribute_keeps_old_whole_team_panels(self):
        b = self.battle((36, 36, 68), (40,), ruleset='base_v1', normalize=False)
        self.assertEqual(synergy.compute(b._plain_comps[0])['NORMAL'], 2)
        self.assertTrue(all(not u.bond_tiers for u in b.units))
        with patch.object(synergy, 'SYNERGIES_ON', False):
            control = self.battle((36, 36, 68), (40,), ruleset='base_v1', normalize=False)
        self.assertGreater(b.units[2].max_hp, control.units[2].max_hp)
        self.assertEqual(b.units[2].max_hp,
                         control.units[2].max_hp + int(control.units[2].max_hp * .06))

    def test_arena_six_duplicates_never_launch_old_volley_classic_still_does(self):
        for ruleset in ('arena_v1', 'base_v1'):
            b = self.battle((76,) * 6, (68,), ruleset=ruleset)
            with patch.object(combo, 'COMBOS_ON', True), patch('combat.MAX_BATTLE_SECONDS', 0):
                b.run()
            self.assertEqual(any(e[1] == 'combo' for e in b.events), ruleset == 'base_v1')

    def test_erosion_burn_and_poison_need_three_real_hp_ticks_and_exact_anchor(self):
        for kind in ('burn', 'poison'):
            for friends, expected in (((34, 73), 4), ((34, 73, 31, 6), 8)):
                with self.subTest(kind=kind, count=len(friends)):
                    b = self.battle(friends, (68,))
                    source, patient = b.units[0], b.units[-1]
                    rng_state = b.rng.getstate()
                    status.apply_debuff(b, patient, kind, 0., source=source)
                    self.tick(b, 1.); self.tick(b, 2.)
                    self.assertFalse(self.effects(b, 'bond_erosion'))
                    self.tick(b, 3.)
                    e, = self.effects(b, 'bond_erosion', 'energy')
                    self.assertEqual((e[2], e[3], e[6]['amount'], source.energy),
                                     (source.idx, source.idx, expected, expected))
                    self.assertEqual((e[6]['bond_tier'], e[6]['origin_idx']),
                                     (len(friends), patient.idx))
                    self.assertEqual(b.events[e[6]['action_index']][1:5],
                                     ('status', patient.idx, kind, 'tick'))
                    self.assertEqual(e[6]['event_count'], 1)
                    self.assertEqual(source.damage_dealt, patient.damage_taken)
                    self.assertEqual(b.rng.getstate(), rng_state)
                    self.tick(b, 4.); self.tick(b, 5.)
                    self.assertEqual(len(self.effects(b, 'bond_erosion')), 1)

    def test_erosion_three_fully_absorbed_ticks_do_not_count_or_shield_statistics(self):
        b = self.battle(enemies=(68,))
        source, _, patient = b.units
        combos.grant_shield(b, patient, patient, 200, 0., None)
        status.apply_debuff(b, patient, 'poison', 0., source=source)
        self.tick(b, 1.); self.tick(b, 2.)
        self.assertFalse(source.erosion_counts)
        self.assertEqual(patient.damage_taken, 0)
        self.assertEqual(patient.shield_absorbed, 12)
        for t in (3., 4., 5.):
            self.tick(b, t)
        self.assertEqual(len(self.effects(b, 'bond_erosion')), 1)

    def test_erosion_full_energy_does_not_spend_and_partial_gain_is_capped(self):
        b = self.battle(enemies=(68,))
        source, _, patient = b.units
        status.apply_debuff(b, patient, 'poison', 0., source=source)
        source.energy = ENERGY_MAX
        for t in (1., 2., 3.):
            self.tick(b, t)
        self.assertNotIn('bond_erosion', source.combo_uses)
        self.assertFalse(source.erosion_used_targets)
        source.energy -= 1
        self.tick(b, 4.)
        e, = self.effects(b, 'bond_erosion')
        self.assertEqual((e[6]['amount'], e[6]['requested'], source.energy), (1, 4, 80))
        self.assertEqual(source.combo_uses['bond_erosion'], 1)

    def test_erosion_owner_change_or_cleanse_resets_but_same_owner_refresh_retains_progress(self):
        for changed in ('refresh', 'owner', 'cleanse'):
            with self.subTest(changed=changed):
                b = self.battle(enemies=(68,))
                source, second, patient = b.units
                status.apply_debuff(b, patient, 'poison', 0., source=source)
                self.tick(b, 1.); self.tick(b, 2.)
                epoch = patient._st.debuff_source_epoch
                if changed == 'owner':
                    status.apply_debuff(b, patient, 'poison', 2.1, source=second)
                elif changed == 'cleanse':
                    status.cleanse(b, patient, 2.1)
                status.apply_debuff(b, patient, 'poison', 2.2, source=source)
                self.assertEqual(patient._st.debuff_source_epoch == epoch, changed == 'refresh')
                if changed == 'cleanse':
                    times = (3.2, 4.2, 5.2)
                else:
                    times = (3., 4., 5.)
                self.tick(b, times[0])
                self.assertEqual(bool(self.effects(b, 'bond_erosion')), changed == 'refresh')
                for t in times[1:]:
                    self.tick(b, t)
                self.assertEqual(len(self.effects(b, 'bond_erosion')), 1)

    def test_erosion_dead_source_dead_patient_nonmember_and_spread_product_cannot_earn(self):
        for reason in ('source', 'patient', 'nonmember', 'spread'):
            with self.subTest(reason=reason):
                friends = (34, 73) if reason != 'nonmember' else (94, 34, 73)
                b = self.battle(friends, (68,))
                source, patient = b.units[0], b.units[-1]
                status.apply_debuff(b, patient, 'poison', 0., source=source,
                                    non_spreading=reason == 'spread')
                self.tick(b, 1.); self.tick(b, 2.)
                if reason == 'source':
                    source.hp = 0
                elif reason == 'patient':
                    patient.hp = 1
                self.tick(b, 3.)
                self.assertFalse(self.effects(b, 'bond_erosion'))
                if reason == 'patient':
                    self.assertEqual(sum(e[1:3] == ('die', patient.idx) for e in b.events), 1)

    def test_erosion_source_shared_cooldown_three_successes_and_no_recursion(self):
        b = self.battle(enemies=(68,) * 4)
        source, *rest = b.units
        patients = rest[1:]
        for patient in patients:
            status.apply_debuff(b, patient, 'poison', 0., source=source)
        for t in range(1, 17):
            if t in (6, 11):
                for patient in patients:
                    status.apply_debuff(b, patient, 'poison', t - .5, source=source)
            self.tick(b, float(t))
        effects = self.effects(b, 'bond_erosion')
        self.assertEqual([e[0] for e in effects], [3., 7., 11.])
        self.assertEqual([e[6]['origin_idx'] for e in effects], [p.idx for p in patients[:3]])
        self.assertEqual(source.combo_uses['bond_erosion'], 3)
        self.assertEqual(source.energy, 12)

    def test_erosion_native_poison_and_orb_strengthen_existing_bond_independently(self):
        b = self.battle(enemies=(68, 40), items=((0, 'contagion_orb'),))
        source, _, patient, neighbor = b.units
        neighbor.pos = (5, 0)
        self.assertTrue(self.cast(b, source, 0.))
        self.assertEqual(patient._st.debuff_source_idx, source.idx)
        neighbor.pos = (1, 2)
        for t in (1., 2., 3.):
            self.tick(b, t)
        self.assertEqual(len(self.effects(b, 'contagion_orb', 'spread')), 1)
        self.assertEqual(len(self.effects(b, 'bond_erosion', 'energy')), 1)
        self.assertFalse(neighbor._st.debuff_spreadable)
        self.assertEqual(source.energy, 4)

    def test_combo_base_and_metronome_share_three_real_layers_and_total_speed(self):
        for friends, tier, base in (((68, 26), 2, .05), ((68, 26, 34, 162), 4, .08)):
            for item, item_fraction in ((None, 0.), ('metronome', .15)):
                with self.subTest(tier=tier, item=item):
                    b = self.battle(friends, (40,), items=((0, item),) if item else ())
                    source, patient = b.units[0], b.units[-1]
                    interval = source.attack_interval
                    for t in (0., .5, 1., 2.):
                        self.basic(b, source, patient, t)
                    key = 'metronome' if item else 'bond_combo'
                    effects = self.effects(b, key, 'tempo')
                    self.assertEqual([e[6]['stacks'] for e in effects], [1, 2, 3, 3])
                    self.assertEqual([e[6]['gained'] for e in effects], [1, 1, 1, 0])
                    self.assertAlmostEqual(effects[-1][6]['fraction'], (base + item_fraction) * 3)
                    self.assertAlmostEqual(effects[-1][6]['base_fraction'], base * 3)
                    self.assertAlmostEqual(effects[-1][6]['item_fraction'], item_fraction * 3)
                    self.assertEqual(effects[-1][6]['bond_tier'], tier)
                    self.assertAlmostEqual(b._action_interval(source, 2.), interval / (1 + (base + item_fraction) * 3))
                    self.assertEqual((source.attack_interval, source.move_mult), (interval, 1.))
                    for e in effects:
                        self.assertEqual(b.events[e[6]['action_index']][1:5],
                                         ('attack', source.idx, patient.idx, 10))
                        self.assertEqual(e[6]['event_count'], 1)
                    self.assertFalse(self.effects(b, 'bond_combo') if item else self.effects(b, 'metronome'))

    def test_combo_retarget_clears_even_if_new_target_dodges_or_absorbs(self):
        for obstacle in ('dodge', 'shield', 'success'):
            with self.subTest(obstacle=obstacle):
                b = self.battle((68, 26), (40, 40))
                source, _, first, second = b.units
                source.range = 2
                self.basic(b, source, first, 0.)
                if obstacle == 'dodge':
                    second.item_dodge = 1.
                elif obstacle == 'shield':
                    combos.grant_shield(b, second, second, 100, .5, None)
                self.basic(b, source, second, 1.)
                e, = self.effects(b, 'bond_combo', 'expire')
                self.assertEqual(e[6]['reason'], 'retarget')
                self.assertEqual(source.tempo_stacks, 1 if obstacle == 'success' else 0)

    def test_combo_same_target_shield_zero_dodge_do_not_extend_expiry(self):
        for obstacle in ('shield', 'zero', 'dodge'):
            with self.subTest(obstacle=obstacle):
                b = self.battle((68, 26), (40,))
                source, _, patient = b.units
                self.basic(b, source, patient, 0.)
                if obstacle == 'shield':
                    combos.grant_shield(b, patient, patient, 100, .5, None)
                elif obstacle == 'dodge':
                    patient.item_dodge = 1.
                self.basic(b, source, patient, 1., 0 if obstacle == 'zero' else 10)
                self.assertEqual((source.tempo_stacks, source.tempo_until), (1, 4.))
                self.assertAlmostEqual(offense.tempo_multiplier(b, source, 3.999), 1.05)
                self.assertEqual(offense.tempo_multiplier(b, source, 4.), 1.)
                offense.expire(b, source, 4.)
                self.assertEqual(source.tempo_stacks, 0)
                self.assertEqual(self.effects(b, 'bond_combo', 'expire')[0][6]['reason'], 'idle')

    def test_combo_native_tm_side_dot_and_counterattack_do_not_stack(self):
        b = self.battle((68, 26), (31,))
        source, _, patient = b.units
        source.technique = 'earthquake'
        self.assertTrue(self.cast(b, source, 0.))
        arena_skills._side_hit(b, source, patient, arena_skills.resolve_cast(source.piece), .4, .1, 0)
        b._land_hit(source, patient, 10, .2, primary=True)
        status.apply_debuff(b, patient, 'poison', .3, source=source)
        self.tick(b, 1.3)
        self.assertFalse(self.effects(b, 'bond_combo'))
        patient.pos = (2, 2)  # The native uppercut moved it out of basic range.
        self.basic(b, source, patient, 2.)
        self.assertTrue(source.technique_used)
        self.assertEqual(len(self.effects(b, 'bond_combo', 'tempo')), 1)

    def test_combo_accelerates_attack_and_cast_action_but_not_movement(self):
        b = self.battle((68, 26), (40,))
        source, _, patient = b.units
        interval = source.attack_interval
        with patch('combat._damage', return_value=10), patch.object(status, 'on_hit'):
            b._act(source, 0.)
            self.assertAlmostEqual(source.next_act, interval / 1.05)
            source.energy = ENERGY_MAX
            b.duration = 1.
            b._act(source, 1.)
            self.assertAlmostEqual(source.next_act, 1. + interval / 1.05)
            self.assertEqual(source.tempo_stacks, 1)
        patient.pos = (5, 0)
        source.energy, b.duration = 0, 2.
        b._act(source, 2.)
        self.assertAlmostEqual(source.next_act, 2. + MOVE_TICK * melee_move_mult() * source.move_mult)
        self.assertEqual(source.attack_interval, interval)

    # Keep the original bond boundary oracle independent of new species passives.
    @patch('arena_traits.TRAITS_ON', False)
    def test_guard_real_cross_half_uses_single_shield_ledger_once(self):
        for friends, expected, tier in (((76, 59), 80, 2), ((76, 59, 31, 36), 120, 4)):
            with self.subTest(tier=tier):
                b = self.battle(friends, (68,))
                patient, attacker = b.units[0], b.units[-1]
                b._land_hit(attacker, patient, 400, 0.)
                self.assertFalse(self.effects(b, 'bond_guard'))
                b._land_hit(attacker, patient, 100, 1.)
                e, = self.effects(b, 'bond_guard', 'shield')
                self.assertEqual((patient.hp, patient.shield), (500, expected))
                self.assertEqual((e[6]['hp_before'], e[6]['hp_after'], e[6]['bond_tier']), (600, 500, tier))
                self.assertEqual(b.events[e[6]['action_index']][1:5],
                                 ('attack', attacker.idx, patient.idx, 100))
                b._land_hit(attacker, patient, 20, 1.5)
                self.assertEqual((patient.hp, patient.shield, patient.shield_absorbed), (500, expected - 20, 20))
                patient.hp = 700
                b._land_hit(attacker, patient, 300, 2.)
                self.assertEqual(len(self.effects(b, 'bond_guard', 'shield')), 1)
                self.assertEqual(patient.combo_uses['bond_guard'], 1)
                self.assertEqual(attacker.damage_dealt, patient.damage_taken)

    # Keep the original bond boundary oracle independent of new species passives.
    @patch('arena_traits.TRAITS_ON', False)
    def test_guard_exact_half_start_dot_no_hp_loss_and_nonmember_do_not_trigger(self):
        for reason in ('half_start', 'dot', 'absorbed', 'nonmember'):
            with self.subTest(reason=reason):
                friends = (76, 59) if reason != 'nonmember' else (9, 76, 59)
                b = self.battle(friends, (68,))
                patient, attacker = b.units[0], b.units[-1]
                patient.hp = 500 if reason == 'half_start' else 505
                if reason == 'dot':
                    status.apply_debuff(b, patient, 'burn', 0., source=attacker)
                    self.tick(b, 1.)
                else:
                    if reason == 'absorbed':
                        combos.grant_shield(b, patient, patient, 100, 0., None)
                    b._land_hit(attacker, patient, 20, 1.)
                self.assertFalse(self.effects(b, 'bond_guard'))
                self.assertNotIn('bond_guard', patient.combo_uses)

    # Keep the original bond boundary oracle independent of new species passives.
    @patch('arena_traits.TRAITS_ON', False)
    def test_guard_rock_entry_crosses_half_without_consuming_direct_hit_shield(self):
        b = self.battle((76, 59), (95,))
        patient, _, setter = b.units
        field = fields.place_rocks(b, setter, patient, 0.)
        destination = next(cell for cell in field['cells']
                           if cell != patient.pos and not any(u.pos == cell for u in b.units))
        patient.hp = 520
        self.assertTrue(fields.move_unit(b, patient, destination, 1.))
        self.assertEqual((patient.hp, patient.damage_taken, setter.damage_dealt), (490, 30, 30))
        self.assertFalse(self.effects(b, 'bond_guard'))
        self.assertNotIn('bond_guard', patient.combo_uses)
        patient.hp = 520
        b._land_hit(setter, patient, 30, 2.)
        self.assertEqual((patient.hp, patient.shield), (490, 80))
        self.assertEqual(len(self.effects(b, 'bond_guard', 'shield')), 1)

    # Keep the original bond boundary oracle independent of new species passives.
    @patch('arena_traits.TRAITS_ON', False)
    def test_guard_stronger_shield_prevents_spend_and_later_cross_can_succeed(self):
        b = self.battle((76, 59), (68,))
        patient, _, attacker = b.units
        patient.hp = 550
        combos.grant_shield(b, patient, patient, 200, 0., None)
        b._land_hit(attacker, patient, 100, .5)
        self.assertEqual(patient.shield, 100)
        # To test a true cross without draining the stronger shield, establish
        # the settled HP-loss fact and call the same post-hit hook explicitly.
        patient.hp = 490
        self.assertFalse(bonds.after_direct_damage(b, patient, 550, 1., None))
        self.assertEqual(patient.shield, 100)
        self.assertNotIn('bond_guard', patient.combo_uses)
        combos.expire(b, patient, 3.)
        patient.hp = 550
        b._land_hit(attacker, patient, 60, 4.)
        self.assertEqual((patient.hp, patient.shield, patient.combo_uses['bond_guard']), (490, 80, 1))

    # Keep the original bond boundary oracle independent of new species passives.
    @patch('arena_traits.TRAITS_ON', False)
    def test_guard_death_does_not_shield_but_sash_survivor_can_cross(self):
        for sash in (False, True):
            with self.subTest(sash=sash):
                b = self.battle((76, 59), (68,), items=((0, 'sash'),) if sash else ())
                patient, _, attacker = b.units
                b._land_hit(attacker, patient, 2000, 1.)
                self.assertEqual(patient.hp, 1 if sash else 0)
                self.assertEqual(bool(self.effects(b, 'bond_guard', 'shield')), sash)
                self.assertEqual(patient.shield, 80 if sash else 0)

    def test_inspiration_real_native_heal_cleanse_and_energy_empower_other_ally(self):
        for sid, kind in ((40, 'heal'), (12, 'cleanse'), (121, 'energy'), (164, 'cleanse')):
            with self.subTest(source=sid):
                friends = (sid, 171 if sid != 171 else 40, 68)
                b = self.battle(friends, (40,))
                donor, other, patient, enemy = b.units
                other.energy = ENERGY_MAX
                if kind == 'heal':
                    patient.hp = 500
                elif kind == 'cleanse':
                    status.apply_debuff(b, patient, 'sleep' if sid == 164 else 'poison', 0., source=enemy)
                else:
                    patient.energy = 79
                self.assertTrue(self.cast(b, donor, 1.))
                e, = self.effects(b, 'bond_inspiration', 'offense_buff')
                self.assertEqual((e[2], e[3], e[6]['fraction']), (donor.idx, patient.idx, .10))
                self.assertIn(e[6]['native_kind'], ('heal', 'cleanse', 'energy'))
                self.assertGreater(e[6]['native_actual'], 0)
                self.assertEqual(b.events[e[6]['cast_index']][4], 'arena_' + donor.ult_arch)
                self.assertEqual((e[6]['duration'], e[6]['expires_at']), (3., 4.))
                self.assertEqual(patient.combo_uses['bond_inspiration'], 1)
                self.assertEqual(donor.casts, 1)
                self.assertEqual(patient.casts, 0)

    def test_inspiration_four_member_tier_fifteen_percent_and_hybrid_healing(self):
        b = self.battle((3, 12, 40, 121, 68), (40,))
        donor, _, _, _, patient, _ = b.units
        patient.hp = 300
        self.assertTrue(self.cast(b, donor, 1.))
        effects = self.effects(b, 'bond_inspiration', 'offense_buff')
        e = next(e for e in effects if e[3] == patient.idx)
        self.assertEqual((e[6]['fraction'], e[6]['bond_tier'], e[6]['native_kind']), (.15, 4, 'heal'))
        self.assertEqual(patient.bond_inspiration_fraction, .15)
        self.assertGreater(donor.healing_done, 0)

    def test_inspiration_empty_self_tm_passive_nonmember_and_enemy_receipts_do_not_trigger(self):
        for reason in ('empty', 'self', 'tm', 'passive', 'nonmember', 'enemy'):
            with self.subTest(reason=reason):
                friends = (40, 121, 68) if reason != 'nonmember' else (113, 40, 121, 68)
                b = self.battle(friends, (40,))
                donor, patient, enemy = b.units[0], b.units[-2], b.units[-1]
                if reason == 'empty':
                    self.assertFalse(self.cast(b, donor, 1.))
                elif reason == 'self':
                    donor.hp = 500
                    self.assertTrue(self.cast(b, donor, 1.))
                elif reason == 'tm':
                    patient.hp = 500
                    b._partner_heal(donor, patient, .25, 1., 'rest')
                elif reason == 'passive':
                    patient.hp = 500
                    b._heal(patient, 100, 1., source=donor)
                elif reason == 'nonmember':
                    patient.hp = 500
                    self.assertTrue(self.cast(b, donor, 1.))
                else:
                    self.assertTrue(self.cast(b, b.units[1], 1.))
                    cast_index = next(i for i, e in enumerate(b.events) if e[1] == 'cast')
                    self.assertFalse(bonds.after_native_support(b, b.units[1], enemy, 1, 'energy', 2., cast_index))
                    # Only the valid allied receipt from the preceding real cast.
                    self.assertTrue(all(e[3] != enemy.idx for e in self.effects(b, 'bond_inspiration')))
                    continue
                self.assertFalse(self.effects(b, 'bond_inspiration'))

    def test_inspiration_effective_patient_cooldown_and_three_limit_shared_across_donors(self):
        b = self.battle((121, 171, 68), (40,))
        first, second, patient, _ = b.units
        for t, donor in ((0., first), (1., second), (5., second), (6., first), (10., first), (15., second)):
            patient.energy = 20
            (second if donor is first else first).energy = 80
            self.cast(b, donor, t)
        effects = self.effects(b, 'bond_inspiration', 'offense_buff')
        self.assertEqual([e[0] for e in effects], [0., 5., 10.])
        self.assertEqual([e[2] for e in effects], [first.idx, second.idx, first.idx])
        self.assertEqual(patient.combo_uses['bond_inspiration'], 3)

    def test_inspiration_and_augment_take_stronger_with_independent_expiry(self):
        b = self.battle((40, 121, 68), (40,), augments=('native_inspiration',))
        healer, relay, patient, _ = b.units
        relay.energy = 80
        patient.hp = 500
        self.cast(b, healer, 0.)
        self.assertEqual(offense.damage_multiplier(b, patient, 0.), 1.10)
        # The base cooldown blocks a second base grant, without blocking the
        # independently earned stronger energy augment.
        healer.energy = 80
        patient.energy = 20
        self.cast(b, relay, 4.)
        self.assertEqual(patient.bond_inspiration_until, 3.)
        self.assertEqual(patient.offense_buff_until, 7.)
        patient.hp = 500
        self.cast(b, healer, 6.)
        self.assertEqual(patient.bond_inspiration_until, 9.)
        self.assertEqual(offense.damage_multiplier(b, patient, 6.), 1.25)
        offense.expire(b, patient, 7.)
        self.assertEqual((patient.offense_buff_fraction, patient.bond_inspiration_fraction), (0., .10))
        self.assertEqual(offense.damage_multiplier(b, patient, 7.), 1.10)
        offense.expire(b, patient, 9.)
        self.assertEqual(offense.damage_multiplier(b, patient, 9.), 1.)
        self.assertEqual(len(self.effects(b, 'native_inspiration', 'expire')), 1)
        self.assertEqual(len(self.effects(b, 'bond_inspiration', 'expire')), 1)

    def test_inspiration_base_expiry_does_not_clear_stronger_augment(self):
        b = self.battle((40, 121, 68), (40,), augments=('native_inspiration',))
        healer, relay, patient, _ = b.units
        patient.hp = 500
        self.cast(b, healer, 0.)
        healer.energy, patient.energy = 80, 20
        self.cast(b, relay, 1.)
        offense.expire(b, patient, 3.)
        self.assertEqual(offense.damage_multiplier(b, patient, 3.), 1.25)
        self.assertEqual(patient.offense_buff_until, 4.)
        self.assertEqual(patient.bond_inspiration_fraction, 0.)
        self.assertEqual([e[4] for e in b.events if e[1] == 'combo_effect' and e[5] == 'expire'], ['bond_inspiration'])

    def test_inspiration_direct_multiplier_leaves_dot_and_healing_unchanged(self):
        b = self.battle((121, 171, 34), (68,))
        donor, second, carrier, patient = b.units
        second.energy = 80
        self.cast(b, donor, 0.)
        self.assertEqual(offense.damage_multiplier(b, carrier, 1.), 1.10)
        status.apply_debuff(b, patient, 'poison', 0., source=carrier)
        self.tick(b, 1.)
        self.assertEqual(patient.damage_taken, 5)
        carrier.hp = 500
        b._heal(carrier, 100, 1., source=donor)
        self.assertEqual((carrier.hp, donor.healing_done), (600, 100))
        patient.range, patient.arena_dr = 2, 0.
        b.duration = 1.
        self.assertEqual(b._final_damage(carrier, patient, None, 100), 110)

    def test_type_tactics_use_actual_forms_and_family_identity_once(self):
        self.assertEqual(bonds.memberships(196), ['PSYCHIC', 'bond_mindsong'])
        self.assertEqual(bonds.count([families.make_piece(133, 2, 196),
                                      families.make_piece(63, 2, 65)])['bond_mindsong'], 2)
        self.assertEqual(bonds.count([families.make_piece(133, 1),
                                      families.make_piece(63, 1)])['bond_mindsong'], 1)
        self.assertEqual(bonds.count([families.make_piece(147, 1),
                                      families.make_piece(371, 1)])['bond_dragon_pressure'], 2)

    def test_frostline_three_real_direct_hits_slow_then_expire(self):
        b = self.battle((131, 144), (68, 40))
        source, ally, target, other = b.units
        for t in (0., 1., 2.):
            self.basic(b, source, target, t, 10)
        effects = self.effects(b, 'bond_frostline', 'chill')
        self.assertEqual(len(effects), 1)
        self.assertEqual(effects[0][6]['hits'], 3)
        self.assertEqual(effects[0][6]['fraction'], .15)
        self.assertEqual((target.bond_chill_fraction, target.bond_chill_until), (.15, 5.))
        self.assertEqual(source.combo_uses['bond_frostline'], 1)
        self.assertAlmostEqual(b._action_interval(target, 2.5), target.attack_interval * 1.15)
        offense.expire(b, target, 5.)
        self.assertEqual((target.bond_chill_fraction, target.bond_chill_until), (0., 0.))
        self.assertEqual(b._action_interval(target, 5.), target.attack_interval)
        self.assertEqual(len(self.effects(b, 'bond_frostline', 'expire')), 1)

    def test_frostline_window_actual_hit_and_stronger_chill_edges(self):
        b = self.battle((131, 144, 91), (68,))
        source, second, third, target = b.units
        self.basic(b, source, target, 0., 0)
        for t in (0., 4., 8.):
            self.basic(b, source, target, t, 10)
        self.assertFalse(self.effects(b, 'bond_frostline', 'chill'))
        self.basic(b, source, target, 8.5, 10)
        self.assertEqual([e[0] for e in self.effects(b, 'bond_frostline', 'chill')], [8.5])

        target.bond_chill_fraction, target.bond_chill_until = .20, 20.
        second.combo_uses['bond_frostline'] = 0
        for t in (10., 11., 12.):
            self.basic(b, second, target, t, 10)
        self.assertNotEqual(second.combo_uses.get('bond_frostline'), 1)
        self.assertEqual(len(self.effects(b, 'bond_frostline', 'chill')), 1)

    def test_spirit_binds_attacker_once_and_respects_range_and_stronger_root(self):
        b = self.battle((94, 93), (68, 40))
        ghost, mate, attacker, other = b.units
        ghost.pos, attacker.pos = (2, 3), (2, 2)
        self.basic(b, attacker, ghost, 0., 600)
        effects = self.effects(b, 'bond_spirit', 'root')
        self.assertEqual(len(effects), 1)
        self.assertEqual(effects[0][6]['attacker_idx'], attacker.idx)
        self.assertEqual((attacker.root_until, attacker.root_source), (1.5, ghost.idx))
        self.assertEqual(ghost.combo_uses['bond_spirit'], 1)
        self.basic(b, attacker, ghost, 1., 100)
        self.assertEqual(len(self.effects(b, 'bond_spirit', 'root')), 1)

        far = self.battle((94, 93), (68,))
        patient, partner, distant = far.units
        patient.pos, distant.pos = (0, 3), (5, 0)
        self.basic(far, distant, patient, 0., 600)
        self.assertFalse(self.effects(far, 'bond_spirit'))
        self.assertNotIn('bond_spirit', patient.combo_uses)

        blocked = self.battle((94, 93), (68,))
        wounded, partner, striker = blocked.units
        wounded.pos, striker.pos = (2, 3), (2, 2)
        striker.root_until = 3.
        self.basic(blocked, striker, wounded, 0., 600)
        self.assertFalse(self.effects(blocked, 'bond_spirit'))
        self.assertNotIn('bond_spirit', wounded.combo_uses)
        self.assertEqual(striker.root_until, 3.)

    def test_mindsong_relays_actual_energy_with_cooldown_and_native_guard(self):
        b = self.battle((80, 65, 121, 122), (68, 40))
        source, relay, third, fourth, target, other = b.units
        third.energy = fourth.energy = 100
        relay.energy = 10
        self.cast(b, source, 0.)
        effects = self.effects(b, 'bond_mindsong', 'energy')
        self.assertEqual(len(effects), 1)
        self.assertEqual((effects[0][6]['amount'], effects[0][6]['gained']), (5, 5))
        self.assertEqual((relay.energy, relay.combo_uses['bond_mindsong']), (15, 1))

        source.energy = 100
        self.cast(b, source, 1.)
        self.assertEqual(len(self.effects(b, 'bond_mindsong', 'energy')), 1)
        source.energy = 100
        self.cast(b, source, 4.)
        self.assertEqual(len(self.effects(b, 'bond_mindsong', 'energy')), 2)
        self.assertEqual(relay.combo_uses['bond_mindsong'], 2)

        full = self.battle((65, 80, 121, 122), (68,))
        caster, patient = full.units[:2]
        patient.energy = 100
        self.cast(full, caster, 0.)
        self.assertFalse(self.effects(full, 'bond_mindsong'))
        self.assertFalse(bonds.after_native_cast(full, caster, 1., len(full.events)))

    def test_dragon_pressure_marks_primary_and_adjacent_with_limits(self):
        b = self.battle((230, 148), (68, 40))
        source, mate, target, adjacent = b.units
        target.pos, adjacent.pos = (2, 2), (1, 2)
        self.cast(b, source, 0.)
        effects = self.effects(b, 'bond_dragon_pressure', 'vulnerability')
        self.assertEqual({e[3] for e in effects}, {target.idx, adjacent.idx})
        self.assertTrue(all(e[6]['fraction'] == .12 and e[6]['splash_count'] == 2
                            for e in effects))
        self.assertEqual((target.vulnerable_until, adjacent.vulnerable_until), (4., 4.))
        self.assertEqual((target.vulnerable_fraction, adjacent.vulnerable_fraction), (.12, .12))
        self.assertEqual(source.combo_uses['bond_dragon_pressure'], 1)

        source.energy = 100
        self.cast(b, source, 1.)
        source.energy = 100
        self.cast(b, source, 4.1)
        source.energy = 100
        self.cast(b, source, 8.2)
        self.assertEqual(len(self.effects(b, 'bond_dragon_pressure', 'vulnerability')), 4)
        self.assertEqual(source.combo_uses['bond_dragon_pressure'], 2)

        blocked = self.battle((230, 148), (68,))
        dragon, mate, patient = blocked.units
        patient.vulnerable_until, patient.vulnerable_fraction = 5., .12
        self.cast(blocked, dragon, 0.)
        self.assertFalse(self.effects(blocked, 'bond_dragon_pressure'))
        self.assertNotIn('bond_dragon_pressure', dragon.combo_uses)
        self.assertFalse(bonds.after_native_hit(blocked, dragon, patient, 1., None, 0))

    def test_dragon_pressure_fraction_changes_actual_damage_and_expires(self):
        low = self.battle((230, 40), (68,))
        source, outsider, patient = low.units
        self.cast(low, source, 0.)
        self.assertEqual(patient.vulnerable_fraction, .10)
        patient.range = 2
        low.duration = 0.
        source.synergy_dmg = 0.
        self.assertEqual(low._final_damage(source, patient, None, 100), 110)
        arena_fields.expire(low, 3.)
        self.assertEqual((patient.vulnerable_until, patient.vulnerable_fraction), (0., 0.))

        high = self.battle((230, 148), (68,))
        source, mate, patient = high.units
        self.cast(high, source, 0.)
        self.assertEqual(patient.vulnerable_fraction, .12)
        patient.range = 2
        high.duration = 0.
        source.synergy_dmg = 0.
        self.assertEqual(high._final_damage(source, patient, None, 100), 112)

    def test_classic_hooks_never_emit_arena_bond_events_or_modifiers(self):
        b = self.battle((34, 73), (68,), ruleset='base_v1')
        source, _, patient = b.units
        status.apply_debuff(b, patient, 'poison', 0., source=source)
        for t in (1., 2., 3.):
            self.tick(b, t)
        b._land_hit(source, patient, 600, 4.)
        self.assertFalse(any(e[1] == 'combo_effect' for e in b.events))
        self.assertEqual(offense.damage_multiplier(b, source, 4.), 1.)
        self.assertEqual(offense.tempo_multiplier(b, source, 4.), 1.)


if __name__ == '__main__':
    unittest.main()
