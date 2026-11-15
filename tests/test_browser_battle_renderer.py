"""Browser battle renderer (docs/58): script endpoint, schemas and JS contracts."""
import copy
import json
import random
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tools/acceptance'), str(ROOT / 'tools/mockups'), str(ROOT / 'sim')]
import arena  # noqa: E402
import battle_script  # noqa: E402
import demo  # noqa: E402
import motion_schema  # noqa: E402
from arena_scenarios import make_scene  # noqa: E402
from esp32_runtime.animation import sample_track  # noqa: E402

NODE = shutil.which('node')
_SCRIPT = {}


def showcase_script():
    if 'script' not in _SCRIPT:
        anim = make_scene(7, 'arena_showcase')
        _SCRIPT['anim'] = anim
        _SCRIPT['script'] = battle_script.build_script(
            anim, source={'kind': 'scenario'}, log_formatter=demo._fmt_event)
    return _SCRIPT['anim'], _SCRIPT['script']


class BattleScriptContract(unittest.TestCase):
    def test_script_is_valid_json_safe_and_deterministic(self):
        anim, script = showcase_script()
        self.assertEqual(battle_script.validate_script(script), [])
        text = json.dumps(script, ensure_ascii=False)
        again = battle_script.build_script(make_scene(7, 'arena_showcase'), source={'kind': 'scenario'},
                                           log_formatter=demo._fmt_event)
        self.assertEqual(json.dumps(again, ensure_ascii=False), text)
        self.assertEqual(script['arena']['rows'], 6)
        self.assertEqual(len(script['units']), 12)
        unit = script['units'][0]
        for key in ('idx', 'team', 'sid', 'name', 'star', 'shiny', 'role', 'types', 'range', 'melee',
                    'pos', 'max_hp', 'item', 'sprite', 'skill'):
            self.assertIn(key, unit)
        self.assertTrue(unit['sprite'].startswith('/demo/sprite/'))
        casts = [a for a in script['actions'] if a['kind'] == 'cast']
        self.assertTrue(casts)
        for key in ('id', 'name', 'type', 'category', 'arch', 'tags', 'power', 'targeting'):
            self.assertIn(key, casts[0]['skill'])

    def test_actions_mirror_the_animation_timeline(self):
        anim, script = showcase_script()
        rows = {row['i']: row for row in script['actions']}
        for timing in anim.timeline.actions:
            row = rows[timing.source_index]
            self.assertAlmostEqual(row['start'], timing.start, places=3)
            self.assertAlmostEqual(row['release'], timing.release, places=3)
            self.assertAlmostEqual(row['impact'], timing.impact, places=3)
            self.assertAlmostEqual(row['end'], timing.recover_end, places=3)
            self.assertEqual((row['actor'], row['target']), (timing.attacker, timing.target))
        self.assertEqual(len(script['events']), len(anim.timeline.events))
        self.assertEqual(script['clock']['duration'], round(anim.timeline.duration, 3))

    def test_state_snapshots_match_the_presentation_view(self):
        anim, script = showcase_script()
        for t in (0.0, 1.0, 4.85, 9.0, 15.0, script['clock']['duration']):
            states = anim.presentation_state(t)
            for unit in script['units']:
                rows = script['states'][str(unit['idx'])]
                current = [row for row in rows if row[0] <= t + 1e-9][-1]
                self.assertEqual(current[1], states[unit['idx']]['hp'], f'unit {unit["idx"]} at {t}')

    def test_shared_skill_ids_keep_each_species_name(self):
        for species, name in ((26, '电流链'), (135, '雷电接力')):
            script = battle_script.preview_script(species, 'cast')
            casts = [a for a in script['actions'] if a['kind'] == 'cast' and a['actor'] == 0]
            self.assertEqual(casts[0]['skill']['name'], name)
            self.assertEqual(script['units'][0]['skill']['name'], name)

    def test_unknown_payloads_stay_json_safe(self):
        self.assertEqual(battle_script.json_safe({'a': (1, 2.0), 'b': {3}, 'c': float('nan'), 'd': object}),
                         {'a': [1, 2], 'b': [3], 'c': None, 'd': str(object)})

    def test_depth_edition_effects_and_terrain_reach_the_script(self):
        import combat
        import arena_families as families
        from render_battle_gif import BattleAnimation

        def piece(fid, star=1):
            return families.make_piece(fid, star, families.FAMILIES[fid][1][0][-1])
        battle = combat.Battle([piece(66, 2), piece(66, 1)], [piece(1), piece(1)], random.Random(1),
                               layout='back', ruleset='arena_v2', stat_mode='budget_v1',
                               arena_teams=[['charge_horn'], []], arena_terrain='mana_spring',
                               positions_a=[(0, 4), (1, 4)], positions_b=[(0, 1), (1, 1)])
        battle.run()
        anim = BattleAnimation([], [], 0, *demo._assets(), battle=battle)
        script = battle_script.build_script(anim, source={'kind': 'fixture'},
                                            log_formatter=demo._fmt_event, battle=battle)
        self.assertEqual(battle_script.validate_script(script), [])
        self.assertEqual(script['arena']['ruleset'], 'arena_v2')
        terrain = script['arena']['terrain']
        self.assertEqual(terrain['id'], 'mana_spring')
        # localRow 0 (front) maps to row 3 for team 0 and row 2 / mirrored column for team 1.
        self.assertIn([2, 3, 0], terrain['cells'])
        self.assertIn([3, 2, 1], terrain['cells'])
        effects = [row for row in script['events'] if row[2] == 'effect']
        self.assertTrue(any(row[3] == -1 and row[6]['label'] == '冲锋号' for row in effects))
        json.dumps(script)


class ScriptPersistenceAndGating(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='poke-script-')
        self.root_patch = patch.object(demo, 'ROOT', Path(self.temp.name))
        self.root_patch.start()
        demo.DEFER_RENDER = True
        demo._RENDER_THREADS.clear()
        demo._RENDER_ACTIVE.clear()
        demo._RENDER_LAZY.clear()

    def tearDown(self):
        for worker in list(demo._RENDER_THREADS):
            worker.join()
        demo.DEFER_RENDER = False
        demo._RENDER_THREADS.clear()
        demo._RENDER_ACTIVE.clear()
        demo._RENDER_LAZY.clear()
        self.root_patch.stop()
        self.temp.cleanup()

    def session(self):
        session = demo.Session(20261115, 'arena_v1')
        session.begin_round(1)
        state = demo.state_json(session)
        for i, slot in enumerate(state.get('shop', [])):
            if slot:
                try:
                    demo.act_buy(session, i)
                except demo.DemoError:
                    pass
        state = demo.state_json(session)
        for j, _ in enumerate(state['bench'][:3]):
            try:
                demo.act_move(session, f'b{j}', f'g{j},0')
            except demo.DemoError:
                pass
        arena.claim_augment(session, 'augment-r1',
                            state['augments']['pending'][0]['options'][0]['id'])
        return session

    def test_script_rounds_skip_pillow_until_a_frame_is_requested(self):
        session = self.session()
        session.render_preference = 'script'
        session.end_prep()
        meta = session.last_battle
        directory = demo.ROOT / '.build' / 'demo' / session.sid / 'r1'
        self.assertTrue(meta['script'])
        self.assertTrue((directory / 'script.json').is_file())
        self.assertEqual(demo._RENDER_ACTIVE, {}, 'no Pillow job for browser-rendered rounds')
        self.assertFalse((directory / '0.png').exists())
        status, script = battle_script.session_script(demo, session.sid, 1)
        self.assertEqual(status, 200)
        self.assertEqual(script['source']['sid'], session.sid)
        self.assertEqual(script['playback_meta']['winner'], meta['winner'])
        self.assertEqual(battle_script.validate_script(script), [])
        # ?renderer=png: the first frame request starts the job (not a restart).
        self.assertEqual(demo.ensure_render_job(session.sid, 1), 'rendering')
        for worker in list(demo._RENDER_THREADS):
            worker.join()
        self.assertEqual(demo.ensure_render_job(session.sid, 1), 'ready')
        self.assertNotIn((session.sid, 1), demo._RENDER_RESTARTS)
        self.assertTrue((directory / 'script.json').is_file(), 'frame job keeps the script')

    def test_default_rounds_still_start_the_frame_job(self):
        session = self.session()
        session.end_prep()
        self.assertIn((session.sid, 1), demo._RENDER_ACTIVE)

    def test_missing_script_regenerates_identically_and_restore_reattaches(self):
        session = self.session()
        session.render_preference = 'script'
        session.end_prep()
        path = demo.ROOT / '.build' / 'demo' / session.sid / 'r1' / 'script.json'
        original = path.read_text()
        path.unlink()
        status, _ = battle_script.session_script(demo, session.sid, 1)
        self.assertEqual(status, 200)
        self.assertEqual(path.read_text(), original)
        # A resumed save (n=0 stub) reattaches the replay from the script alone.
        winner = session.last_battle['winner']
        session.last_battle = {'round': 1, 'winner': winner, 'restored': True, 'n': 0}
        demo._restore_battle_replay(session)
        self.assertTrue(session.last_battle['script'])
        self.assertGreater(session.last_battle['n'], 0)
        # Without the side file or parameters, the endpoint reports 404.
        demo._RENDER_PARAMS.pop((session.sid, 1), None)
        path.unlink()
        self.assertEqual(battle_script.session_script(demo, session.sid, 1)[0], 404)
        self.assertEqual(battle_script.session_script(demo, '../etc', 1)[0], 400)


class BrowserRendererHTTP(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import server
        cls.server = server
        cls.httpd = ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        cls.worker = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.worker.start()
        cls.base = f'http://127.0.0.1:{cls.httpd.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def request(self, path, data=None, headers=None):
        request = Request(self.base + path, data=data, headers=headers or {}, method='POST' if data else 'GET')
        try:
            response = urlopen(request, timeout=60)
        except HTTPError as error:
            response = error
        with response:
            return response.status, response.headers, response.read()

    def test_routes_assets_and_scripts(self):
        status, headers, body = self.request('/animation-workbench')
        self.assertEqual(status, 200)
        html = body.decode()
        self.assertIn('aria-label="全站导航"', html)
        self.assertIn('/play/assets/battle_renderer.js', html)
        for asset in ('battle_renderer.js', 'animation_workbench.js', 'animation_workbench.css'):
            status, headers, _ = self.request('/play/assets/' + asset)
            self.assertEqual(status, 200, asset)
        status, _, body = self.request('/api/battle/script/scenario?key=arena_showcase&seed=7')
        self.assertEqual(status, 200)
        self.assertEqual(battle_script.validate_script(json.loads(body)), [])
        status, _, body = self.request('/api/battle/script/preview?species=6&kind=cast&scene=dummy')
        self.assertEqual(status, 200)
        self.assertTrue(any(a['kind'] == 'cast' for a in json.loads(body)['actions']))
        self.assertEqual(self.request('/api/battle/script/scenario?key=nope')[0], 400)
        self.assertEqual(self.request('/api/battle/script?sid=000000000000&round=1')[0], 404)
        self.assertEqual(self.request('/api/battle/script?sid=x&round=z')[0], 400)
        status, _, body = self.request('/api/animation/pack')
        data = json.loads(body)
        self.assertTrue(data['ok'])
        self.assertIn('roles', data['motion'])
        self.assertIn('core', data['vfx'])

    def test_pack_save_is_local_validated_and_atomic(self):
        temp = Path(tempfile.mkdtemp(prefix='poke-pack-'))
        try:
            shutil.copytree(ROOT / 'assets/motion', temp / 'assets/motion')
            shutil.copytree(ROOT / 'assets/vfx', temp / 'assets/vfx')
            pack = json.loads((temp / 'assets/motion/roles.json').read_text())
            pack['clips']['role.idle.breathe']['phases']['loop'][1][2] = -3
            body = json.dumps({'group': 'motion', 'name': 'roles', 'data': pack}).encode()
            headers = {'Content-Type': 'application/json', 'X-PokeTactics-Workbench': '1'}
            with patch.object(motion_schema, 'ROOT', temp):
                self.assertEqual(self.request('/api/animation/pack/save', body,
                                              {**headers, 'Origin': 'http://evil.invalid'})[0], 403)
                self.assertEqual(self.request('/api/animation/pack/save', body,
                                              {'Content-Type': 'application/json'})[0], 400)
                bad = copy.deepcopy(pack)
                bad['clips']['role.idle.breathe']['phases']['loop'][1][1] = 90
                status, _, reply = self.request('/api/animation/pack/save', json.dumps(
                    {'group': 'motion', 'name': 'roles', 'data': bad}).encode(), headers)
                self.assertEqual(status, 400)
                self.assertIn('limits', json.loads(reply)['error'])
                status, _, reply = self.request('/api/animation/pack/save', body, headers)
                self.assertEqual(status, 200, reply)
            saved = json.loads((temp / 'assets/motion/roles.json').read_text())
            self.assertEqual(saved['clips']['role.idle.breathe']['phases']['loop'][1][2], -3)
        finally:
            shutil.rmtree(temp)


class MotionSchema(unittest.TestCase):
    def test_checked_in_packs_validate_and_reference_each_other(self):
        self.assertEqual(motion_schema.validate_all(), [])

    def test_seed_generator_is_in_sync_with_checked_in_packs(self):
        import motion_seed
        for (group, name), data in motion_seed.packs().items():
            path = ROOT / 'assets' / group / f'{name}.json'
            self.assertEqual(json.loads(path.read_text()), json.loads(motion_schema.dump_pack(data)),
                             f'{path} differs from motion_seed.py; rerun the seed or update the generator')

    def test_every_native_skill_has_its_own_recipe(self):
        import arena_skills
        packs = motion_schema.load_packs()['vfx']
        recipes = {name: recipe for pack in packs.values() for name, recipe in pack.get('recipes', {}).items()}
        bindings = packs['skills']['bindings']['skill']
        catalog = arena_skills.catalog(include_families=True)
        self.assertEqual({row['id'] for row in catalog}, set(bindings))
        categories = {row['category'] for row in catalog}
        for category in categories:
            self.assertIn('cat.' + category, recipes, category)
            self.assertEqual(packs['core']['bindings']['category'][category], 'cat.' + category)
        for skill_id, recipe_id in bindings.items():
            self.assertEqual(recipe_id, 'skill.' + skill_id)
            self.assertIn(recipes[recipe_id]['extends'], recipes)

    def test_category_silhouettes_are_distinct_not_recolours(self):
        core = motion_schema.load_packs()['vfx']['core']['recipes']
        def silhouette(name):
            recipe = core[name]
            layers = list(recipe.get('layers', [])) + list(recipe.get('add', []))
            if recipe.get('extends'):
                layers += [layer for layer in silhouette_layers(recipe['extends'])
                           if layer['shape'] not in recipe.get('drop', [])]
            return frozenset((layer['layer'], layer['shape']) for layer in layers
                             if layer['layer'] not in ('projectile', 'screen'))
        def silhouette_layers(name):
            recipe = core[name]
            return list(recipe.get('layers', [])) + list(recipe.get('add', []))
        primary = ['cat.burst', 'cat.area', 'cat.chain', 'cat.combo', 'cat.drain', 'cat.energy', 'cat.heal',
                   'cat.shield', 'cat.cleanse', 'cat.displacement', 'cat.root', 'cat.pursuit', 'cat.taunt',
                   'cat.terrain', 'cat.poison', 'cat.vulnerability', 'cat.execute', 'cat.pierce',
                   'cat.retaliation', 'cat.control']
        shapes = {name: silhouette(name) for name in primary}
        self.assertEqual(len(set(shapes.values())), len(primary))
        signature = {'cat.chain': ('link', 'fork'), 'cat.drain': ('link', 'stream'), 'cat.shield': ('aura', 'hex_dome'),
                     'cat.heal': ('aura', 'cross_glyph'), 'cat.root': ('ground', 'vines_grow'),
                     'cat.taunt': ('aura', 'shout_rings'), 'cat.displacement': ('impact', 'shove'),
                     'cat.area': ('ground', 'ring_expand')}
        for name, shape in signature.items():
            self.assertIn(shape, shapes[name], name)

    def test_every_recipe_shape_has_a_drawing(self):
        source = (ROOT / 'tools/acceptance/battle_renderer.js').read_text()
        packs = motion_schema.load_packs()['vfx']
        used = {layer['shape'] for pack in packs.values() for recipe in pack.get('recipes', {}).values()
                for layer in recipe.get('layers', []) + recipe.get('add', [])
                if layer['layer'] not in ('projectile', 'screen', 'trail')}
        for shape in used:
            self.assertIn(f'"{shape}"', source, f'{shape} is used by a recipe but never drawn')

    def test_part_tracks_and_recipe_inheritance_are_validated(self):
        roles = json.loads((ROOT / 'assets/motion/roles.json').read_text())
        self.assertTrue(all('parts' in clip for clip in roles['clips'].values()))
        for mutate in (lambda k: k[1].__setitem__(1, 40), lambda k: k[0].__setitem__(0, .2),
                       lambda k: k[1].__setitem__(6, 'wobbly'), lambda k: k[1].pop()):
            pack = copy.deepcopy(roles)
            mutate(pack['clips']['role.melee.attack']['parts']['dash'])
            with self.assertRaises(motion_schema.SchemaError):
                motion_schema.validate_motion_pack(pack)
        pack = copy.deepcopy(roles)
        pack['clips']['role.idle.breathe']['parts']['dash'] = pack['clips']['role.idle.breathe']['parts']['loop']
        with self.assertRaises(motion_schema.SchemaError):
            motion_schema.validate_motion_pack(pack)
        cyc = {'schema_version': 1, 'kind': 'vfx_pack', 'name': 'cyc',
               'recipes': {'a': {'extends': 'b'}, 'b': {'extends': 'a'}}}
        motion_schema.validate_vfx_pack(cyc)
        self.assertTrue(any('cycle' in p for p in motion_schema.check_references([], [cyc])))
        bad = copy.deepcopy(cyc)
        bad['recipes']['a'] = {'extends': 'b', 'add': [{'layer': 'link', 'shape': 'fork', 'on': ['Heal!']}]}
        with self.assertRaises(motion_schema.SchemaError):
            motion_schema.validate_vfx_pack(bad)

    def test_invalid_motion_and_vfx_are_rejected(self):
        base = json.loads((ROOT / 'assets/motion/roles.json').read_text())
        def broken(mutate):
            pack = copy.deepcopy(base)
            mutate(pack)
            with self.assertRaises(motion_schema.SchemaError):
                motion_schema.validate_motion_pack(pack)
        broken(lambda p: p.update(schema_version=2))
        broken(lambda p: p['clips']['role.idle.breathe']['phases']['loop'][0].__setitem__(7, 'wobble'))
        broken(lambda p: p['clips']['role.idle.breathe']['phases']['loop'][0].__setitem__(0, 0.1))
        broken(lambda p: p['clips']['role.idle.breathe']['phases']['loop'][1].__setitem__(4, 160))
        broken(lambda p: p['clips']['role.idle.breathe']['phases'].update(dash=[]))
        broken(lambda p: p['archetypes']['melee']['timing'].update(anticipation=5))
        vfx = json.loads((ROOT / 'assets/vfx/core.json').read_text())
        bad = copy.deepcopy(vfx)
        bad['recipes']['melee_slash']['layers'][0]['shape'] = 'teleport'
        with self.assertRaises(motion_schema.SchemaError):
            motion_schema.validate_vfx_pack(bad)
        bad = copy.deepcopy(vfx)
        bad['palettes']['FIRE'] = ['red']
        with self.assertRaises(motion_schema.SchemaError):
            motion_schema.validate_vfx_pack(bad)
        self.assertTrue(motion_schema.check_references(
            [base], [{'name': 'x', 'recipes': {}, 'bindings': {'archetype': {'melee': 'missing'}}}]))


@unittest.skipUnless(NODE, 'Node.js runs the browser renderer contracts')
class BrowserRendererNode(unittest.TestCase):
    def test_outcomes_and_chains_follow_cast_and_action_indices(self):
        self.assertIn('OK renderer cause links', self.run_case('causeLinks'))

    def test_part_tracks_deform_the_body_on_actions_and_hits(self):
        self.assertIn('OK renderer parts', self.run_case('parts'))

    def test_every_vfx_shape_paints(self):
        shapes = sorted({shape for layer, names in motion_schema.SHAPES.items()
                         if layer not in ('projectile', 'trail', 'screen') for shape in names})
        self.assertIn('OK renderer paint', self.run_case('paintAll', json.dumps(shapes)))
    @classmethod
    def setUpClass(cls):
        _, script = showcase_script()
        cls.temp = tempfile.NamedTemporaryFile('w', suffix='.json', delete=False)
        json.dump(script, cls.temp)
        cls.temp.close()

    @classmethod
    def tearDownClass(cls):
        Path(cls.temp.name).unlink(missing_ok=True)

    def run_case(self, name, *extra):
        result = subprocess.run([NODE, str(ROOT / 'tests/frontend/battle_renderer.js'), self.temp.name, name, *extra],
                                capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout

    def test_same_script_and_time_give_the_same_draw_list(self):
        self.assertIn('OK renderer determinism', self.run_case('determinism'))

    def test_timing_variety_breaks_the_metronome(self):
        self.assertIn('OK renderer variety', self.run_case('variety'))

    def test_impacts_warp_and_telemetry_stay_authoritative(self):
        self.assertIn('OK renderer invariants', self.run_case('invariants'))

    def test_unknown_and_generic_effect_events_degrade_gracefully(self):
        self.assertIn('OK renderer unknown events', self.run_case('unknownEvents'))

    def test_portable_sampler_matches_the_device_reference(self):
        keys = [[0, 0, 0, 0, 100, 100, 1], [0.3, -7, 3, -9, 110, 92, 1], [0.65, 5, -2, 7, 93, 108, 0],
                [1, 0, 0, 0, 100, 100, 1]]
        samples = [[p, list(sample_track(keys, p))] for p in
                   (0, 0.05, 0.15, 0.2999, 0.3, 0.47, 0.5, 0.65, 0.8, 0.99, 1, 1.2)]
        self.assertIn('OK renderer sampler', self.run_case(
            'portableSampler', json.dumps({'keys': keys, 'samples': samples})))


if __name__ == '__main__':
    unittest.main()
