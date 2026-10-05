"""Opening weather traits: shared timing, teaching coexistence and version isolation."""
import copy
import hashlib
import json
from pathlib import Path
import random
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'sim'), str(ROOT/'tools/acceptance'), str(ROOT)]
import abilities
import demo
import tactics
from combat import Battle
from roster import build_roster
from session_save import SessionCodec, LEGACY_TACTICS_FINGERPRINT, UnknownRulesError
from test_tactical_combat import effects, strike

PIECES = {p.species_id: p for rows in build_roster().values() for p in rows}


def fight(a=(38,), b=(9,), ruleset=tactics.CURRENT_TACTICS_RULESET, **options):
    options.setdefault('positions_a', [(2+i, 2) for i in range(len(a))])
    options.setdefault('positions_b', [(2+i, 1) for i in range(len(b))])
    return Battle([PIECES[s] for s in a], [PIECES[s] for s in b], random.Random(741),
                  ruleset=ruleset, layout='back', **options)


class OpeningWeatherContracts(unittest.TestCase):
    def test_catalog_is_fixed_species_current_version_and_returns_fresh_data(self):
        self.assertEqual([r['species'] for r in abilities.catalog('tactics_v2')], [38, 131])
        for version in ('base_v1', 'tactics_v1'):
            self.assertEqual(abilities.catalog(version), [])
            for sid in (38, 131):
                self.assertIsNone(abilities.for_species(sid, version))
        self.assertIsNone(abilities.for_species(37, 'tactics_v2'))
        self.assertIsNone(abilities.for_species(6, 'tactics_v2'))
        self.assertIsNone(abilities.for_species(True, 'tactics_v2'))
        first = abilities.for_species(38, 'tactics_v2')
        first['weather'] = 'rain'
        self.assertEqual(abilities.for_species(38, 'tactics_v2')['weather'], 'sun')
        with self.assertRaises(ValueError):
            abilities.catalog('bogus')

    def test_each_species_triggers_without_partner_learning_or_configuration(self):
        for sid, weather in ((38, 'sun'), (131, 'rain')):
            battle = fight((sid,))
            self.assertEqual(battle.weather_name, weather)
            request, = effects(battle, 'weather_request')
            start, = effects(battle, 'weather_start')
            self.assertEqual(request[0], 0.)
            self.assertEqual(start[0], 0.)
            self.assertEqual(request[5]['source_kind'], 'ability')
            self.assertIsNone(request[5]['cast_index'])
            self.assertEqual(start[5]['expires_at'], 8.)
            self.assertTrue(all(len(e) == 6 for e in battle.events if e[1] == 'tactical_effect'))
            self.assertIsNone(battle.units[0].technique)
            before = copy.deepcopy(battle.events)
            battle.flush_tactics(0.)
            battle.flush_tactics(0.)
            self.assertEqual(battle.events, before)

    def test_same_weather_duplicates_across_teams_never_stack_and_expire_to_base(self):
        battle = fight((38, 38), (38,), weather_name='hail')
        self.assertEqual(len(effects(battle, 'weather_request')), 3)
        start, = effects(battle, 'weather_start')
        self.assertEqual(len(start[5]['requests']), 3)
        self.assertEqual(start[5]['expires_at'], 8.)
        battle.flush_tactics(7.99)
        self.assertEqual(battle.weather_name, 'sun')
        battle.flush_tactics(8.)
        self.assertEqual(battle.weather_name, 'hail')
        self.assertEqual(len(effects(battle, 'weather_end')), 1)
        battle.flush_tactics(16.)
        self.assertEqual(len(effects(battle, 'weather_start')), 1)

    def test_opposite_weather_is_symmetric_and_same_team_can_conflict(self):
        for a, b in (((38,), (131,)), ((131,), (38,)), ((38, 131), (9,)), ((131, 38), (9,))):
            battle = fight(a, b, weather_name='sand')
            self.assertEqual(battle.weather_name, 'sand')
            conflict, = effects(battle, 'weather_conflict')
            self.assertEqual(conflict[0], 0.)
            self.assertEqual({r['weather'] for r in conflict[5]['requests']}, {'sun', 'rain'})
            self.assertIsNone(conflict[5]['expires_at'])
            self.assertFalse(effects(battle, 'weather_start'))
            battle.flush_tactics(8.)
            self.assertFalse(effects(battle, 'weather_end'))

    def test_weather_survives_source_death_and_cannot_retrigger(self):
        battle = fight()
        battle.units[0].hp = 0
        battle.flush_tactics(1.)
        self.assertEqual(battle.weather_name, 'sun')
        battle.flush_tactics(8.)
        self.assertIsNone(battle.weather_name)
        battle.run()
        self.assertEqual(len(effects(battle, 'weather_request')), 1)

    def test_native_teaching_cast_can_override_opening_weather_and_does_not_rewind_it(self):
        battle = fight((38,), (9,), weather_name='hail', learned_b=['rain_dance'],
                       tactics_b={'weather': {'source': 0}})
        a, b = battle.units
        for unit in battle.units:
            unit.max_hp = unit.hp = 10000
        strike(battle, b, a, 2.1)
        self.assertEqual(battle.weather_name, 'sun')
        self.assertEqual(b.technique, 'rain_dance')
        battle.flush_tactics(2.2)
        self.assertEqual(battle.weather_name, 'rain')
        self.assertEqual(effects(battle, 'weather_start')[-1][5]['reason'], 'overridden')
        battle.flush_tactics(10.2)
        self.assertEqual(battle.weather_name, 'hail')
        # Native casts remain ordinary after the one weather teaching opportunity.
        strike(battle, b, a, 11.)
        self.assertEqual(len(effects(battle, 'weather_request')), 2)

    def test_own_teaching_is_independent_and_can_extend_its_weather_window(self):
        battle = fight(learned_a=['sunny_day'], tactics_a={'weather': {'source': 0}})
        a, b = battle.units
        b.max_hp = b.hp = 10000
        strike(battle, a, b, .1)
        battle.flush_tactics(.2)
        start = effects(battle, 'weather_start')[-1]
        self.assertEqual(start[5]['reason'], 'extended')
        self.assertEqual(start[5]['expires_at'], 8.2)
        self.assertNotIn('source_kind', start[5]['requests'][0])
        self.assertEqual(a.technique, 'sunny_day')
        battle.flush_tactics(8.)
        self.assertEqual(battle.weather_name, 'sun')
        battle.flush_tactics(8.2)
        self.assertIsNone(battle.weather_name)

    def test_opening_conflict_consumes_traits_but_leaves_later_teaching_available(self):
        battle = fight((38,), (131,), learned_b=['rain_dance'],
                       tactics_b={'weather': {'source': 0}})
        a, b = battle.units
        a.hp = a.max_hp = 10000
        strike(battle, b, a, .1)
        battle.flush_tactics(.2)
        self.assertEqual(battle.weather_name, 'rain')
        self.assertEqual(len(effects(battle, 'weather_conflict')), 1)
        self.assertEqual(len(effects(battle, 'weather_start')), 1)

    def test_shared_sun_changes_both_sides_native_fire_damage_before_first_cast(self):
        def damages(version):
            battle = fight((38, 6), (6,), ruleset=version)
            for u in battle.units:
                u.hp = u.max_hp = 10000
            _, ally, enemy = battle.units
            strike(battle, ally, enemy, .1)
            ally_damage = 10000-enemy.hp
            ally.hp = 10000
            strike(battle, enemy, ally, .1)
            enemy_damage = 10000-ally.hp
            return ally_damage, enemy_damage, battle
        old = damages('tactics_v1')
        new = damages('tactics_v2')
        for baseline, boosted in zip(old[:2], new[:2]):
            self.assertGreater(boosted, baseline)
            self.assertAlmostEqual(boosted/baseline, 1.2, delta=.03)
        battle = new[2]
        battle.flush_tactics(8.)
        ally, enemy = battle.units[1:]
        enemy.hp = 10000
        strike(battle, ally, enemy, 8.1)
        self.assertEqual(10000-enemy.hp, old[0])

    def test_trait_dispatch_never_draws_rng_or_changes_unrelated_teams(self):
        old, new = fight(ruleset='tactics_v1'), fight(ruleset='tactics_v2')
        self.assertEqual(old.rng.getstate(), new.rng.getstate())
        old, new = fight((6,), ruleset='tactics_v1'), fight((6,), ruleset='tactics_v2')
        left, right = old.run(), new.run()
        self.assertEqual({k: v for k, v in left.items() if k != 'units'},
                         {k: v for k, v in right.items() if k != 'units'})
        self.assertEqual(old.events, new.events)
        self.assertEqual(old.rng.getstate(), new.rng.getstate())


class OpeningSessionContracts(unittest.TestCase):
    def session(self):
        session = demo.Session(42, ruleset='tactics_v2')
        session.run_id = 'b0030000000000000000000000000000'
        session.expedition = {'partner': 6, 'technique': None, 'item': None}
        session.begin_round(6)
        session.player.level = 7
        return session

    def add(self, session, sid, pos=None, technique=None):
        session.pool.take(sid)
        owned = demo.shop_mod.OwnedPiece(session.templates[sid], session.templates[sid].tier)
        owned.technique = technique
        if pos is None:
            session.player.bench.append(owned)
        else:
            session.player.grid[pos] = owned
        session.ensure_unit_ids()
        return owned

    def test_forecast_tracks_deployed_sources_and_teaching_is_separate(self):
        session = self.session()
        self.add(session, 131)
        ninetales = self.add(session, 38, (0, 2), 'sunny_day')
        state = demo.state_json(session)
        self.assertEqual(state['entry_weather']['weather'], 'sun')
        self.assertEqual([s['species'] for s in state['entry_weather']['you']], [38])
        self.assertEqual(state['board'][0][2]['ability']['name'], '日照')
        self.assertEqual(state['board'][0][2]['technique']['id'], 'sunny_day')
        self.assertEqual(session.player.inventory.techniques['sunny_day'], 0)
        lapras = session.player.bench.pop()
        session.player.grid[(0, 3)] = lapras
        self.assertTrue(demo.state_json(session)['entry_weather']['conflict'])
        del session.player.grid[(0, 2)]
        session.player.bench.append(ninetales)
        self.assertEqual(demo.state_json(session)['entry_weather']['weather'], 'rain')

    def test_evolution_unlocks_trait_only_on_deployment_and_keeps_learning(self):
        session = self.session()
        first = self.add(session, 37, technique='sunny_day')
        self.add(session, 37)
        self.add(session, 37)
        self.assertIsNone(abilities.for_species(first.piece.species_id, session.ruleset))
        logs = demo.try_combine([], session.player.bench, session.pool, session.templates,
                                session.player.inventory)
        self.assertTrue(logs)
        evolved, = session.player.bench
        self.assertEqual((evolved.piece.species_id, evolved.uid, evolved.technique),
                         (38, first.uid, 'sunny_day'))
        self.assertFalse(demo.state_json(session)['entry_weather']['you'])
        session.player.bench.clear()
        session.player.grid[(0, 2)] = evolved
        self.assertEqual(demo.state_json(session)['entry_weather']['weather'], 'sun')

    def test_resume_rebuilds_traits_for_frozen_opponent_and_preserves_battle_events(self):
        session = self.session()
        self.add(session, 38, (0, 2))
        foe = next(b if a is session.player else a for a, b in session.pairs if session.player in (a, b))
        session.pool.take(131)
        foe.board.append(demo.shop_mod.OwnedPiece(session.templates[131], 3))
        foe.level = 7
        session.opp_view = session._opponent_view()
        codec = SessionCodec()
        payload = codec.encode(session)
        saved = codec.decode(copy.deepcopy(payload), 4)
        self.assertEqual(codec.encode(saved), payload)
        self.assertEqual(demo.state_json(saved)['entry_weather'], demo.state_json(session)['entry_weather'])
        self.assertTrue(demo.state_json(saved)['entry_weather']['conflict'])
        opponent = [p for cells in saved.opp_view['rows'] for p in cells if p and p['sid'] == 131]
        self.assertEqual(opponent[0]['ability']['name'], '降雨')
        def events(s):
            options = s.battle_options(s.player)
            options['learned_b'] = s.opponent_learned
            options['tactics_b'] = s.opponent_tactics
            battle = demo.Battle(s.player.battle_comp(), s.opponent_comp, random.Random(42), layout='back',
                                positions_a=s.player.battle_positions(), **options)
            battle.run()
            return battle.events
        self.assertEqual(events(saved), events(session))

    def test_real_tactics_v1_schema4_save_replays_identically_without_traits(self):
        fixture = json.loads((ROOT/'tests/fixtures/tactics-v1-schema4-session.json').read_text())
        self.assertEqual(fixture['initial']['rules'], LEGACY_TACTICS_FINGERPRINT)
        codec = SessionCodec()
        session = codec.decode(fixture['initial'], 4)
        self.assertEqual(session.ruleset, 'tactics_v1')
        self.assertIsNone(demo.state_json(session)['entry_weather'])
        self.assertTrue(all(not p.get('ability') for cells in demo.state_json(session)['board'] for p in cells if p))
        battles = []
        def render(a, b, rng, weather, path, positions_a=None, hud_snapshot=None, **options):
            battle = demo.Battle(a, b, rng, layout='back', weather_name=weather, positions_a=positions_a, **options)
            result = battle.run()
            battles.append({'events_sha256': hashlib.sha256(json.dumps(battle.events, ensure_ascii=False,
                           separators=(',', ':')).encode()).hexdigest(), 'event_count': len(battle.events),
                           'winner': result['winner'], 'survivors': {str(k): v for k, v in result['survivors'].items()},
                           'duration': result['duration']})
            self.assertFalse(any(e[1] == 'tactical_effect' and e[5].get('source_kind') == 'ability' for e in battle.events))
            return {'n': 0, 'winner': result['winner'], 'survivors': result['survivors'], 'duration': result['duration'], 'events': []}
        with patch.object(demo, 'SESSIONS', {session.sid: session}), patch.object(demo, '_render_battle_frames', side_effect=render):
            for command in fixture['commands']:
                result = demo._apply_action({'sid': session.sid, **command})
                self.assertTrue(result['ok'], result)
        actual = codec.encode(session)
        actual['rules'] = LEGACY_TACTICS_FINGERPRINT
        self.assertEqual(actual, fixture['expected_after'])
        self.assertEqual(battles, fixture['expected_battles'])

    def test_old_fingerprint_cannot_enable_new_traits(self):
        fixture = json.loads((ROOT/'tests/fixtures/tactics-v1-schema4-session.json').read_text())
        forged = copy.deepcopy(fixture['initial'])
        forged['ruleset'] = 'tactics_v2'
        with self.assertRaises(UnknownRulesError):
            SessionCodec().decode(forged, 4)


if __name__ == '__main__':
    unittest.main()
