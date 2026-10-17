"""Portal browsing keeps game state intact and old tools reachable."""

import json
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from collections import Counter
from html.parser import HTMLParser
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "acceptance"))
import server


class Navigation(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_portal = False
        self.links = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'nav' and attrs.get('aria-label') == '全站导航':
            self.in_portal = True
        if tag == 'a' and self.in_portal:
            self.links.append(attrs)

    def handle_endtag(self, tag):
        if tag == 'nav':
            self.in_portal = False


class PortalRoutes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f'http://127.0.0.1:{cls.httpd.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(timeout=5)

    def read(self, path):
        with urlopen(self.base + path, timeout=5) as response:
            self.assertEqual(response.status, 200)
            body = response.read()
            self.assertEqual(len(body), int(response.headers['Content-Length']))
            return body, response.headers

    def test_browsing_references_never_creates_or_saves_a_session(self):
        before = set(server.demo_mod.SESSIONS)
        with tempfile.TemporaryDirectory() as directory, patch.object(
                server.demo_mod, 'SAVE_ROOT', Path(directory)), patch.object(
                server.demo_mod, 'Session', side_effect=AssertionError('Reference page created a game')):
            for path in ('/', '/pokedex', '/pokedex?tab=bonds', '/pokedex?tab=bonds&category=tactic', '/pokedex?tab=items',
                         '/pokedex?tab=items&view=recipes',
                         '/pokedex?tab=items&view=recipes&component=bell',
                         '/pokedex?tab=items&view=recipes&a=shoes&b=shoes',
                         '/pokedex?tab=augments',
                         '/pokedex?tab=techniques', '/pokedex?tab=builds', '/guide', '/tools', '/api/portal/catalog'):
                with self.subTest(path=path):
                    self.read(path)
            self.assertEqual(list(Path(directory).iterdir()), [])
        self.assertEqual(set(server.demo_mod.SESSIONS), before)

    def test_global_navigation_is_complete_and_route_aware(self):
        paths = ('/', '/pokedex', '/pokedex/', '/guide', '/tools', '/play', '/play/',
                 '/demo', '/roster', '/match', '/experiments', '/synergy', '/scenarios',
                 '/items', '/anim?seed=7', '/animation-lab', '/animation-editor',
                 '/device', '/expedition', '/acceptance')
        primary = {'/', '/pokedex', '/guide', '/tools', '/play'}
        for path in paths:
            with self.subTest(path=path):
                body, headers = self.read(path)
                html = body.decode()
                self.assertIn('text/html', headers['Content-Type'])
                self.assertEqual(html.count('aria-label="全站导航"'), 1)
                nav = Navigation()
                nav.feed(html)
                self.assertEqual({a['href'] for a in nav.links}, primary)
                route = path.split('?')[0].rstrip('/') or '/'
                expected = route if route in primary else '/tools'
                self.assertEqual([a['href'] for a in nav.links if a.get('aria-current') == 'page'], [expected])

    def test_catalog_uses_actual_trial_skills_and_learning_compatibility(self):
        body, _ = self.read('/api/portal/catalog')
        data = json.loads(body)
        self.assertTrue(data['ok'])
        pokemon = data['pokemon']
        self.assertEqual(len({p['sid'] for p in pokemon}), 62)
        self.assertEqual(Counter(p['role_key'] for p in pokemon),
                         {'attack': 30, 'defense': 17, 'support': 15})
        arena = server.demo_mod.arena_mod
        self.assertEqual(data['techniques'], arena.technique_catalog())
        for p in pokemon:
            with self.subTest(pokemon=p['sid']):
                self.assertEqual(p['native_skill']['energy'], 80)
                self.assertFalse(p['native_skill']['replaceable'])
                self.assertEqual(p['pool_total'], arena.pool_cap(p['sid']))
                expected = [t['id'] for t in data['techniques']
                            if server.demo_mod.techniques_mod.compatible_species(p['sid'], t['id'], ruleset='arena_v1')]
                self.assertEqual(p['learnable'], expected)

    def test_generation_groups_preserve_original_roster_and_shared_pool(self):
        data = json.loads(self.read('/api/portal/catalog')[0])
        pokemon = data['pokemon']
        gen2 = {162, 211, 195, 237, 164, 171, 181, 196, 214,
                197, 208, 242, 157, 212, 230, 160, 248, 154,
                198, 200, 215, 227}
        self.assertEqual({p['sid'] for p in pokemon if p['generation'] == 2}, gen2)
        self.assertEqual(Counter(p['generation'] for p in pokemon), {1: 40, 2: 22})
        self.assertEqual(Counter((p['generation'], p['role_key']) for p in pokemon),
                         {(1, 'attack'): 19, (1, 'defense'): 10, (1, 'support'): 11,
                          (2, 'attack'): 11, (2, 'defense'): 7, (2, 'support'): 4})
        self.assertEqual(Counter(p['cost'] for p in pokemon), {1: 16, 2: 22, 3: 18, 4: 3, 5: 3})
        self.assertEqual(sum(p['pool_total'] for p in pokemon), 906)
        arena = server.demo_mod.arena_mod
        from data import pokedex
        dex = pokedex()
        for p in pokemon:
            with self.subTest(species=p['sid']):
                generation = 2 if p['sid'] in gen2 else 1
                self.assertEqual(p['generation_name'], '第二世代' if generation == 2 else '第一世代')
                group = ('第二世代精灵' if generation == 2 else
                         '传说精灵' if p['sid'] in arena.LEGENDARY else
                         '第一世代独立精灵' if p['sid'] in arena.EXPANSION_ROSTER
                         or len(dex.family_of(p['sid'])) == 1 else '进化形态')
                self.assertEqual(p['pool_group'], group)

    def test_item_and_augment_catalogs_use_current_effects_and_valid_recipes(self):
        data = json.loads(self.read('/api/portal/catalog')[0])
        demo = server.demo_mod
        items = demo.items_mod
        self.assertEqual({row['id'] for row in data['items']}, set(items.catalog('arena_v1')))
        self.assertNotIn('evo_stone', {row['id'] for row in data['items']})
        self.assertEqual({row['id'] for row in data['components']}, set(items.COMPONENT_ORDER))
        ids = {p['sid'] for p in data['pokemon']}
        for row in data['items']:
            with self.subTest(item=row['id']):
                self.assertEqual(row['description'], demo._item_effect(row['id'], 'budget_v1'))
                self.assertTrue(row['advice'])
                self.assertTrue(row['tradeoff'])
                self.assertTrue(set(row['recommended']) <= ids)
                for pair in row['recipes']:
                    self.assertEqual(len(pair), 2)
                    self.assertEqual(items.craft_result(pair[0]['id'], pair[1]['id'], 'arena_v1'), row['id'])
        lens = next(row for row in data['items'] if row['id'] == 'focus_lens')
        self.assertIn('40能量', lens['description'])
        self.assertNotEqual(lens['description'], demo._item_effect('focus_lens', 'legacy'))
        for row in data['augments']:
            with self.subTest(augment=row['id']):
                self.assertEqual(row['name'], demo.arena_mod.AUGMENTS[row['id']]['name'])
                self.assertEqual(row['description'], demo.arena_mod.AUGMENTS[row['id']]['description'])
                self.assertTrue(set(row['recommended']) <= ids)

    def test_build_examples_reference_available_and_compatible_choices(self):
        data = json.loads(self.read('/api/portal/catalog')[0])
        pokemon = {p['sid']: p for p in data['pokemon']}
        self.assertEqual({row['id'] for row in data['techniques']}, set(data['technique_advice']))
        generated = [key for key, row in data['technique_advice'].items() if row.get('generated')]
        self.assertEqual(generated, [], '技能机缺手写攻略文案，portal 只能出兜底卡')
        self.assertEqual(len(data['builds']), 33)
        self.assertEqual(len({row['id'] for row in data['builds']}), len(data['builds']))
        for build in data['builds']:
            with self.subTest(build=build['id']):
                self.assertIn(build['core'], pokemon)
                self.assertTrue(set(build['teammates']) <= set(pokemon))
                self.assertIn(build['item'], {row['id'] for row in data['items']})
                self.assertIn(build['augment'], {row['id'] for row in data['augments']})
                self.assertIn(build['technique'], pokemon[build['core']]['learnable'])
                self.assertTrue(build['steps'])
                self.assertTrue(build['counter'])
                self.assertTrue(build['alternative'])

    def test_gen2_build_partners_are_available_and_explain_their_role(self):
        data = json.loads(self.read('/api/portal/catalog')[0])
        pokemon = {p['sid']: p for p in data['pokemon']}
        covered = set()
        for build in data['builds']:
            partners = build['gen2_partners']
            with self.subTest(build=build['id']):
                self.assertTrue(partners)
                self.assertEqual(len(partners), len(set(partners)))
                for sid in partners:
                    self.assertEqual(pokemon[sid]['generation'], 2)
                    self.assertIn(pokemon[sid]['name'], build['gen2_advice'])
                covered.update(partners)
        self.assertEqual(covered, set(server.demo_mod.arena_mod.GEN2_ROSTER))

    @unittest.skipUnless(shutil.which('node'), 'Node.js is needed to execute the portal filters')
    def test_frontend_combines_generation_role_search_and_clear(self):
        data = json.loads(self.read('/api/portal/catalog')[0])
        # Execute the shipped script with a minimal DOM; filtering is exercised
        # through its real event handlers, without exposing app internals.
        program = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const data = JSON.parse(fs.readFileSync(0, 'utf8'));
const source = fs.readFileSync(process.argv[1], 'utf8');
async function page(search = '?pool=species_v1') {
  const elements = new Map();
  class Element {
    constructor(id) { this.id = id; this.listeners = {}; this.buttons = []; this.textContent = ''; this.value = ''; this._html = ''; }
    get innerHTML() { return this._html; }
    set innerHTML(value) {
      this._html = value;
      this.buttons = [...value.matchAll(/<button[^>]*data-filter="([^"]+)"[^>]*aria-pressed="([^"]+)"/g)].map(match => ({
        dataset: { filter: match[1] }, pressed: match[2],
        setAttribute(name, value) { if (name === 'aria-pressed') this.pressed = value; },
        closest() { return this; },
      }));
      if (this.id === 'hub-app') for (const id of ['dex-generations', 'dex-filters']) {
        const match = value.match(new RegExp('<div id="' + id + '"[^>]*>([\\s\\S]*?)</div>'));
        if (match) element(id).innerHTML = match[1];
      }
    }
    addEventListener(type, listener) { this.listeners[type] = listener; }
    focus() {}
    click(value) {
      const button = this.buttons.find(b => b.dataset.filter === value);
      assert.ok(button, `Missing filter ${value}`);
      this.listeners.click({ target: button });
    }
  }
  function element(id) {
    if (!elements.has(id)) elements.set(id, new Element(id));
    return elements.get(id);
  }
  const context = vm.createContext({
    location: { pathname: '/pokedex', search }, URLSearchParams, AbortController, setTimeout, clearTimeout,
    document: {
      getElementById: element, querySelector: () => element('head-mark'),
      querySelectorAll: selector => element(selector.split(' ')[0].slice(1)).buttons,
    },
    fetch: async url => { assert.equal(url, '/api/portal/catalog?pool=species_v1'); return { ok: true, json: async () => data }; },
  });
  vm.runInContext(source, context);
  await new Promise(resolve => setImmediate(resolve));
  return { element, root: element('hub-app') };
}
(async () => {
  const { element, root } = await page();
  const count = expected => assert.equal(element('dex-count').textContent, `${expected} / 62 位宝可梦`);
  count(62);
  assert.equal(element('head-mark').textContent, '062');
  element('dex-generations').click('2'); count(22);
  element('dex-filters').click('attack'); count(11);
  const search = element('dex-search');
  search.value = '电龙'; search.listeners.input({ target: search }); count(1);
  assert.match(element('dex-results').innerHTML, /<h2>电龙<\/h2>/);
  assert.match(element('dex-results').innerHTML, /第二世代/);
  assert.match(element('dex-results').innerHTML, /搭配参考/);
  search.value = '不存在的精灵'; search.listeners.input({ target: search }); count(0);
  root.listeners.click({ target: { closest: selector => selector === '[data-clear]' ? {} : null } });
  count(62);
  for (const id of ['dex-generations', 'dex-filters']) {
    assert.equal(element(id).buttons.find(b => b.dataset.filter === 'all').pressed, 'true');
  }
  element('dex-generations').click('1'); element('dex-filters').click('support'); count(11);
  assert.match(element('dex-results').innerHTML, /首代独立精灵/);
  const linked = await page('?pool=species_v1&generation=2&role=defense');
  assert.equal(linked.element('dex-count').textContent, '7 / 62 位宝可梦');
  assert.match(linked.element('dex-results').innerHTML, /<h2>大钢蛇<\/h2>/);
})().catch(error => { console.error(error); process.exitCode = 1; });
"""
        result = subprocess.run([shutil.which('node'), '-e', program,
                                 str(ROOT / 'tools/acceptance/hub.js')],
                                input=json.dumps(data), capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_assets_are_fixed_and_old_tool_scripts_remain_present(self):
        for name, mime in (('hub.css', 'text/css'), ('hub.js', 'text/javascript'),
                           ('portal.css', 'text/css')):
            with self.subTest(asset=name):
                body, headers = self.read('/hub/assets/' + name)
                self.assertEqual(body, (ROOT / 'tools/acceptance' / name).read_bytes())
                self.assertIn(mime, headers['Content-Type'])
                self.assertEqual(headers['X-Content-Type-Options'], 'nosniff')
        for path in ('/hub/assets/server.py', '/hub/assets/../server.py',
                     '/hub/assets/%2e%2e/server.py', '/hub/assets/missing.js'):
            with self.subTest(path=path), self.assertRaises(HTTPError) as error:
                self.read(path)
            self.assertEqual(error.exception.code, 404)
        for path, marker in (('/play', '/play/assets/play.js'),
                             ('/anim?seed=7', "fetch('/api/prepare?'"),
                             ('/roster', "fetch('/api/roster')"),
                             ('/animation-editor', "const ACTIONS"),
                             ('/acceptance', "fetch('/api/reports')")):
            with self.subTest(path=path):
                self.assertIn(marker, self.read(path)[0].decode())

    def test_documents_stay_in_navigation_and_cannot_read_other_files(self):
        path = '/reference?path=docs%2F09-save-system.md'
        body, headers = self.read(path)
        self.assertIn('text/html', headers['Content-Type'])
        self.assertIn('aria-label="全站导航"', body.decode())
        self.assertIn('下载 Markdown 原文', body.decode())
        self.assertIn('href="/docs/09-save-system.md"', body.decode())
        for relative in ('tools/acceptance/server.py', '../README.md',
                         '/etc/passwd', 'docs/missing.md'):
            with self.subTest(relative=relative), self.assertRaises(HTTPError) as error:
                self.read('/reference?path=' + relative)
            self.assertEqual(error.exception.code, 404)


if __name__ == '__main__':
    unittest.main()
