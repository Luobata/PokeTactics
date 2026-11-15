"""Action feedback layer: node scenarios + served assets."""
import json
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class PlayFeedbackTest(unittest.TestCase):
    def test_every_action_leaves_a_visible_trace(self):
        result = subprocess.run(['node', str(ROOT / 'tests' / 'frontend' / 'play_feedback.js')],
                                capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('play_feedback: ok', result.stdout)

    def test_page_loads_feedback_assets_and_hooks(self):
        html = (ROOT / 'tools' / 'acceptance' / 'play.html').read_text()
        self.assertIn('/play/assets/play_feedback.js', html)
        self.assertIn('/play/assets/play_feedback.css', html)
        server = (ROOT / 'tools' / 'acceptance' / 'server.py').read_text()
        self.assertIn('"/play/assets/play_feedback.js"', server)
        play = (ROOT / 'tools' / 'acceptance' / 'play.js').read_text()
        self.assertIn('PlayFeedback?.before(cmd, params, state)', play)
        self.assertIn('PlayFeedback.after(feedback', play)
        self.assertIn('PlayFeedback?.selection(', play)


if __name__ == '__main__':
    unittest.main()


class LiteStateTest(unittest.TestCase):
    def test_prep_mutations_return_a_slim_state(self):
        import sys
        for path in (ROOT / 'sim', ROOT / 'tools' / 'acceptance', ROOT / 'tools' / 'mockups'):
            if str(path) not in sys.path:
                sys.path.insert(0, str(path))
        import json
        import demo
        session = demo._new_session(91, {'mode': 'arena'})
        full = demo.state_json(session)
        lite = demo.state_json(session, lite=True)
        self.assertTrue(lite['lite'])
        self.assertNotIn('catalog', lite['arena'])
        self.assertNotIn('trait_catalog', lite['arena'])
        self.assertEqual([row['seat'] for row in lite['scouting']], [0])
        self.assertEqual(set(lite['arena']['pool_remaining']), {str(row['sid']) for row in full['arena']['catalog']})
        self.assertLess(len(json.dumps(lite, ensure_ascii=False)), len(json.dumps(full, ensure_ascii=False)) / 4)
        session.phase = 'battle'
        self.assertNotIn('lite', demo.state_json(session, lite=True))


class MusicTest(unittest.TestCase):
    def test_tracks_follow_the_phase(self):
        script = r'''
const fs = require("fs"), vm = require("vm");
const dialogs = {"battle-dialog": {open: false}, "result-dialog": {open: false}};
const document = {readyState: "complete", hidden: false, getElementById: (id) => dialogs[id] || null,
  addEventListener() {}};
const window = {};
vm.createContext(Object.assign(window, {window, document, localStorage: {getItem: () => null, setItem() {}},
  setTimeout, setInterval, clearInterval, console}));
vm.runInContext(fs.readFileSync(process.argv[1], "utf8"), window);
const m = window.PlayMusic, out = [];
m.update({phase: "prep", round: 3, hp: 100}); out.push(m.desired());
m.update({round: 12}); out.push(m.desired());
m.update({round: 22}); out.push(m.desired());
dialogs["battle-dialog"].open = true; m.update({round: 10, pve: true}); out.push(m.desired());
m.update({pve: false, round: 21}); out.push(m.desired());
dialogs["battle-dialog"].open = false; m.update({phase: "over"}); out.push(m.desired());
console.log(JSON.stringify(out));
'''
        result = subprocess.run(['node', '-e', script, str(ROOT / 'tools' / 'acceptance' / 'play_music.js')],
                                capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), ['prep_calm', 'prep_mid', 'prep_tense', 'battle_wild',
                                                     'battle_final', 'results'])
