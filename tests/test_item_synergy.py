"""arena_v2 item synergy: resonance tags, awakened items, dual-wield combos, save and advisor."""
import random
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for path in (ROOT / 'sim', ROOT / 'tools' / 'acceptance', ROOT / 'tools' / 'mockups'):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import arena  # noqa: E402
import arena_depth  # noqa: E402
import arena_families as families  # noqa: E402
import arena_item_synergy as syn  # noqa: E402
import arena_session  # noqa: E402
import combat  # noqa: E402
import items  # noqa: E402


def piece(fid, star=2, **extra):
    p = families.make_piece(fid, star, families.FAMILIES[fid][1][0][-1])
    for key, value in extra.items():
        setattr(p, key, value)
    return p


ENEMY = lambda: [piece(147), piece(43), piece(10), piece(74), piece(1)]


def fight(a, b, seed=3, pa=None, pb=None, until=None):
    battle = combat.Battle(a, b, random.Random(seed), layout='back', ruleset='arena_v2',
                           stat_mode='budget_v1', arena_teams=[[], []],
                           positions_a=pa or [(c, 3) for c in range(len(a))],
                           positions_b=pb or [(c, 2) for c in range(len(b))])
    battle.run(until=until)
    return battle


def effects(battle, key):
    return [e for e in battle.events if e[1] == 'effect' and e[4] == key]


class TagTest(unittest.TestCase):
    def test_every_obtainable_item_has_a_tag_and_awakened_items_never_drop(self):
        for key in items.obtainable('arena_v2'):
            self.assertTrue(syn.item_tags(key), key)
        for key in syn.AWAKENED_ITEMS:
            self.assertIn(key, items.catalog('arena_v2'))
            self.assertNotIn(key, items.obtainable('arena_v2'))
            self.assertNotIn(key, items.catalog('arena_v1'))
            self.assertEqual(syn.item_tags(key), syn.item_tags(syn.base_key(key)))
            self.assertEqual(arena_depth.item_stats(key), arena_depth.item_stats(syn.base_key(key)))

    def test_thresholds(self):
        self.assertEqual(syn.active_resonances(['flame_orb']), {})
        self.assertEqual(syn.active_resonances(['flame_orb', 'toxic_orb_plus']), {'status': 1})
        self.assertEqual(syn.active_resonances(['flame_orb', 'toxic_orb', 'static_glove', 'contagion_orb'])['status'], 2)


class ResonanceBattleTest(unittest.TestCase):
    TEAMS = {
        'status': ['flame_orb', 'toxic_orb', 'static_glove', 'contagion_orb'],
        'impact': ['impact_gauntlet', 'red_card', 'storm_chime', 'trap_lens'],
        'arcane': ['echo_bell', 'mind_crystal', 'quick_claw', 'torrent_orb'],
        'guard': ['taunt_bell', 'revival_seed', 'sash', 'leftovers'],
        'strike': ['boomerang', 'metronome', 'drain_fang', 'life_orb'],
    }
    BODIES = (66, 74, 4, 92)

    def test_each_resonance_tier_acts_in_battle(self):
        for tag, keys in self.TEAMS.items():
            with self.subTest(tag=tag):
                seen = {2: 0, 4: 0}
                for seed in range(4):
                    team = [(piece(fid), key) for fid, key in zip(self.BODIES, keys)]
                    battle = fight(team, ENEMY(), seed=seed, pa=[(c, 3) for c in range(1, 5)])
                    self.assertEqual(battle.item_resonance[0]['active'], {tag: 2})
                    for n in seen:
                        seen[n] += len(effects(battle, f'res_{tag}_{n}'))
                self.assertTrue(all(seen.values()), seen)

    def test_resonance_needs_deployed_items_and_is_deterministic(self):
        battle = fight([(piece(66), 'flame_orb'), piece(4)], ENEMY(), until=3)
        self.assertEqual(battle.item_resonance[0]['active'], {})
        def run():
            team = [(piece(fid), key) for fid, key in zip(self.BODIES, self.TEAMS['impact'])]
            return repr(fight(team, ENEMY(), seed=5).events)
        self.assertEqual(run(), run())


class AwakenAndDuoTest(unittest.TestCase):
    def test_awakened_items_keep_the_base_effect_and_add_a_clause(self):
        for key, label in (('boomerang', '回旋镖·再弹'), ('echo_bell', '回响·扩散'), ('flame_orb', '余烬'),
                           ('toxic_orb', '毒性外溢'), ('static_glove', '静电·电弧'), ('taunt_bell', '再挑衅')):
            with self.subTest(item=key):
                labels = set()
                for seed in range(4):
                    holder = piece(74 if key == 'taunt_bell' else 66, 3)
                    battle = fight([(holder, key + '_plus'), piece(4)], ENEMY(), seed=seed,
                                   pa=[(2, 3), (3, 3)])
                    labels |= {e[5]['label'] for e in battle.events if e[1] == 'effect'
                               and e[4] in (key, key + '_plus')}
                self.assertIn(label, labels)
                self.assertGreater(len(labels), 1)

    def test_dual_wield_pairs_trigger_only_on_one_holder(self):
        for duo, (pair, _name, _text) in syn.DUOS.items():
            if duo == 'duo_conductor':
                continue  # needs a landed paralysis; covered by the probe
            with self.subTest(duo=duo):
                n = 0
                for seed in range(4):
                    holder = piece(92 if duo == 'duo_circuit' else 66, 3, extra_item=pair[1])
                    n += len(effects(fight([(holder, pair[0]), piece(4)], ENEMY(), seed=seed,
                                           pa=[(2, 3), (3, 3)]), duo))
                self.assertGreater(n, 0)
                split = fight([(piece(66, 3), pair[0]), (piece(4), pair[1])], ENEMY(), pa=[(2, 3), (3, 3)])
                self.assertFalse(effects(split, duo))


class SessionTest(unittest.TestCase):
    def setUp(self):
        import demo
        self.demo = demo
        self.s = demo._new_session(91, {'mode': 'arena'})
        for reward in list(self.s.arena_augments_pending):
            arena.claim_augment(self.s, reward['id'], reward['options'][0]['id'])

    def test_awaken_rules_limit_and_save_roundtrip(self):
        s, p = self.s, self.s.player
        for component in p.inventory.components:
            p.inventory.components[component] = 0
        p.inventory.finished.append('flame_orb')
        p.inventory.add_component('charcoal')
        with self.assertRaises(self.demo.DemoError):
            self.demo.act_awaken(s, 'flame_orb')  # before AWAKEN_ROUND
        real_round, s.round_no = s.round_no, syn.AWAKEN_ROUND
        self.demo.act_awaken(s, 'flame_orb')
        self.assertIn('flame_orb_plus', p.inventory.finished)
        self.assertEqual(p.inventory.components['charcoal'], 0)
        with self.assertRaises(self.demo.DemoError):
            self.demo.act_awaken(s, 'boomerang')  # not held
        p.inventory.finished.append('toxic_orb')
        with self.assertRaises(self.demo.DemoError):
            self.demo.act_awaken(s, 'toxic_orb')  # no component
        p.inventory.add_component('mysticwater')
        self.demo.act_awaken(s, 'toxic_orb')
        p.inventory.finished.append('boomerang')
        p.inventory.add_component('band')
        with self.assertRaises(self.demo.DemoError):
            self.demo.act_awaken(s, 'boomerang')  # limit reached
        self.assertEqual(arena_session.seat_state(p)['awakened'], syn.AWAKEN_LIMIT)
        s.round_no = real_round  # keep the snapshot's milestone ledger consistent
        from session_save import SessionCodec
        codec = SessionCodec()
        restored = codec.decode(codec.encode(s), codec.schema_version)
        self.assertIn('flame_orb_plus', restored.player.inventory.finished)
        self.assertEqual(arena_session.seat_state(restored.player)['awakened'], syn.AWAKEN_LIMIT)
        # Dismantling returns the base recipe (the awakening component is spent).
        msg = arena_session.dismantle(p, 'flame_orb_plus')
        self.assertIn('木炭', msg)

    def test_state_exposes_synergy_and_advisor_mentions_resonance(self):
        s, p = self.s, self.s.player
        for i in range(5):
            if p.shop.slots[i] is not None and p.gold >= p.shop.price(i):
                self.demo.act_buy(s, i)
        self.demo.act_move(s, 'b0', 'g0,0')
        p.grid[(0, 0)].item = 'flame_orb'
        p.inventory.finished.append('toxic_orb')
        ix = self.demo.state_json(s, lite=True)['interactions']
        syn_view = ix['item_synergy']
        self.assertEqual([r['tag'] for r in syn_view['resonance']], list(syn.TAG_ORDER))
        status = next(r for r in syn_view['resonance'] if r['tag'] == 'status')
        self.assertEqual(status['count'], 1)
        self.assertIn('toxic_orb', [h['key'] for h in status['helpers']])
        self.assertEqual(len(syn_view['duos']), len(syn.DUOS))
        rows = [r for r in ix['item_advice']['suggestions'] if r['item'] == 'toxic_orb']
        self.assertTrue(any('异常共鸣' in why for r in rows for why in r['why']))
        self.assertTrue(ix['item_advice']['guides']['flame_orb']['duos'])


if __name__ == '__main__':
    unittest.main()
