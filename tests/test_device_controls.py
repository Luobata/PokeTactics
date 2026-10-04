"""Drive real saved sessions exclusively through the three physical keys."""
import copy
from pathlib import Path
import sys
import tempfile
import unittest
import shutil
import subprocess
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools/acceptance"))
import demo
import device_controls as controls
import device_page


def fast_render(a, b, rng, weather, path, positions_a=None, hud_snapshot=None, **kwargs):
    result = demo.Battle(a, b, rng, weather_name=weather, positions_a=positions_a, **kwargs).run()
    return {"n": 0, "winner": result["winner"], "survivors": result["survivors"],
            "duration": result["duration"], "events": []}


class DeviceControlsContracts(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        for p in (patch.object(demo, "SAVE_ROOT", Path(directory.name)),
                  patch.object(demo, "SESSIONS", {}), patch.object(controls, "DEVICES", {}),
                  patch.object(demo, "_render_battle_frames", side_effect=fast_render)):
            p.start(); self.addCleanup(p.stop)
        self.t, self.device_id = 1., ""
        self.state = self.input("state")

    def input(self, phase, key=None, **extra):
        self.t += .15
        params = {"phase": phase, "device_id": self.device_id, **extra}
        if key is not None:
            params["key"] = key
        result = controls.api_input(params, now=self.t)
        self.assertTrue(result["ok"], result)
        self.device_id = result["device_id"]
        self.state = result
        return result

    @property
    def device(self):
        return controls.DEVICES[self.device_id]

    def click(self, key):
        self.input("down", key)
        return self.input("up", key)

    def long(self, key, seconds=.7):
        self.input("down", key)
        self.t += seconds-.15
        result = self.input("tick")
        self.input("up", key)
        return result

    def choose(self, label):
        labels = [r["label"] for r in self.device.rows()]
        target = next((i for i, value in enumerate(labels) if label in value), None)
        self.assertIsNotNone(target, (label, self.device.page, labels))
        while self.device.selected != target:
            self.click("B" if self.device.selected < target else "A")
        return self.click("C")

    def classic(self):
        self.choose("经典对局")
        self.assertEqual(self.state["screen"]["page"], "confirm")
        self.assertEqual(self.device.selected, 0)
        self.choose("确认")
        self.assertEqual(self.device.page, "prep")
        return self.device.sid

    def test_initial_state_has_only_home_and_navigation_does_not_save(self):
        self.assertEqual(self.state["screen"]["page"], "home")
        self.assertFalse(demo.SESSIONS)
        self.click("B"); self.click("A")
        self.long("C")
        self.assertEqual(self.device.page, "detail")
        self.long("B")
        self.assertFalse(demo.SESSIONS)
        self.classic()
        sequence = self.device.sequence
        self.choose("商店"); self.click("B"); self.long("B")
        self.assertEqual(self.device.sequence, sequence)

    def test_only_three_keys_can_buy_deploy_fight_and_advance_without_duplicate_battle(self):
        self.classic()
        self.choose("商店")
        self.click("C")  # First real shop piece.
        self.assertEqual(len(self.device.state["bench"]), 1)
        self.choose("棋盘与备战")
        self.choose("备战席"); self.click("C")
        self.choose("移动 / 交换"); self.choose("战场第一行"); self.click("C")
        self.assertEqual(self.device.state["you"]["on_board"], 1)
        self.choose("开战")
        self.assertEqual(self.device.page, "confirm")
        self.choose("确认")
        self.assertEqual(self.device.page, "result")
        session = demo.SESSIONS[self.device.sid]
        count, seq = session.player_battles, self.device.sequence
        self.long("B")
        self.assertEqual(self.device.page, "home")
        self.choose("继续存档")
        self.assertEqual(self.device.page, "result")
        self.assertEqual(demo.SESSIONS[self.device.sid].player_battles, count)
        self.assertEqual(self.device.sequence, seq)
        self.choose("下一轮")
        self.assertEqual(self.device.state["round"], 2)
        self.assertEqual(self.device.page, "prep")

    def test_sleep_and_wake_consume_whole_gesture_without_confirming_or_advancing(self):
        self.classic()
        self.choose("开战")
        seq = self.device.sequence
        self.long("C", 1.6)
        self.assertTrue(self.device.input.sleeping)
        self.assertEqual(self.device.sequence, seq)
        self.input("down", "C")
        self.t += 2.
        self.input("tick"); self.input("up", "C")
        self.assertFalse(self.device.input.sleeping)
        self.assertEqual(self.device.page, "confirm")
        self.assertEqual(self.device.selected, 0)
        self.assertEqual(self.device.sequence, seq)

    def test_rendered_playback_starts_after_render_and_auto_result_advances_directly(self):
        self.classic()
        self.choose("商店"); self.click("C")
        self.choose("棋盘与备战"); self.choose("备战席"); self.click("C")
        self.choose("移动 / 交换"); self.choose("战场第一行"); self.click("C")
        self.choose("开战"); self.click("B")
        sequence = self.device.sequence

        def render(*args, **kwargs):
            meta = fast_render(*args, **kwargs)
            self.t += 3.  # Rendering takes longer than the playback itself.
            return meta | {"n": 20, "dt": .05}

        def send(phase, key=None, elapsed=.15):
            self.t += elapsed
            result = controls.api_input({"device_id": self.device_id, "phase": phase, "key": key})
            self.assertTrue(result["ok"], result)
            return result

        # Exercise the production clock path, whose time moves while rendering.
        self.device.input.clock = lambda: self.t
        with patch.object(controls.time, "monotonic", side_effect=lambda: self.t), \
                patch.object(demo, "_render_battle_frames", side_effect=render):
            send("down", "C")
            battle = send("up", "C")
            self.assertEqual(battle["screen"]["page"], "battle")
            self.assertEqual(battle["screen"]["battle"]["frame"], 0)
            self.assertEqual(self.device.play_started, self.t)
            self.assertEqual(self.device.sequence, sequence + 1)
            self.assertEqual(send("tick", elapsed=.3)["screen"]["page"], "battle")
            result = send("tick", elapsed=.8)
            self.assertEqual(result["screen"]["page"], "result")
            self.assertEqual(result["screen"]["selected"], 0)
            self.assertEqual(self.device.sequence, sequence + 1)
            count = demo.SESSIONS[self.device.sid].player_battles
            send("down", "C")
            advanced = send("up", "C")
            self.assertEqual(advanced["screen"]["page"], "prep")
            self.assertEqual(advanced["screen"]["round"], 2)
            self.assertEqual(self.device.sequence, sequence + 2)
            send("up", "C")  # Duplicate release cannot commit a second action.
            send("tick")
            self.assertEqual(self.device.sequence, sequence + 2)
            self.assertEqual(demo.SESSIONS[self.device.sid].player_battles, count)

    def test_playback_end_cancels_a_held_confirm_but_allows_the_next_press(self):
        self.classic()
        self.choose("商店"); self.click("C")
        self.choose("棋盘与备战"); self.choose("备战席"); self.click("C")
        self.choose("移动 / 交换"); self.choose("战场第一行"); self.click("C")

        def render(*args, **kwargs):
            return fast_render(*args, **kwargs) | {"n": 20, "dt": .05}

        with patch.object(demo, "_render_battle_frames", side_effect=render):
            self.choose("开战"); self.choose("确认")
        self.assertEqual(self.device.page, "battle")
        sequence = self.device.sequence
        self.t = self.device.play_started + .65
        self.input("down", "C")
        self.t += .1
        self.input("tick")  # The result arrives while C is held on the playback page.
        self.assertEqual(self.device.page, "result")
        self.input("up", "C")
        self.assertEqual(self.device.sequence, sequence)
        self.assertEqual(self.device.state["round"], 1)
        self.click("C")
        self.assertEqual(self.device.page, "prep")
        self.assertEqual(self.device.state["round"], 2)
        self.assertEqual(self.device.sequence, sequence + 1)

    def test_stale_shop_or_uid_target_is_cancelled_after_another_page_mutates(self):
        self.classic()
        self.choose("商店")
        self.input("down", "C")
        sid = self.device.sid
        other = demo.api_action({"sid": sid, "cmd": "refresh"})
        self.assertTrue(other["ok"], other)
        self.input("up", "C")
        self.assertEqual(self.device.page, "prep")
        self.assertFalse(self.device.state["bench"])
        self.assertIn("另一页面", self.state["screen"]["message"])
        self.assertEqual(self.device.sequence, other["state"]["save"]["sequence"])

    def test_cancel_and_long_on_no_detail_never_perform_selected_action(self):
        self.classic()
        seq = self.device.sequence
        self.input("down", "C"); self.input("cancel"); self.input("up", "C")
        self.assertEqual(self.device.page, "prep")
        self.long("C")  # Shop menu has no details; must not enter it on release.
        self.assertEqual(self.device.page, "prep")
        self.assertEqual(self.device.sequence, seq)

    def test_expedition_picker_starts_only_on_explicit_confirmation(self):
        self.choose("远征")
        self.choose("主搭档")
        self.click("C")
        self.assertEqual(self.device.page, "expedition")
        self.assertFalse(demo.SESSIONS)
        self.choose("出发")
        self.click("C")  # Default cancel.
        self.assertFalse(demo.SESSIONS)
        self.choose("出发"); self.choose("确认")
        self.assertEqual(self.device.page, "prep")
        self.assertIsNotNone(self.device.state["expedition"])
        self.assertEqual(self.device.state["you"]["on_board"], 1)

    def test_uid_target_learning_and_default_cancel_on_replacement(self):
        self.classic()
        session = demo.SESSIONS[self.device.sid]
        from shop import OwnedPiece
        session.pool.take(7)
        session.player.bench.append(OwnedPiece(session.templates[7], 1))
        # Root provides the persisted per-seat inventory and teaching transaction.
        inventory = session.player.inventory.techniques
        inventory["surf"] = 1
        inventory["rest"] = 1
        result = demo.api_action({"sid": self.device.sid, "cmd": "save"})
        self.assertTrue(result["ok"], result)
        self.input("state")
        uid = self.device.state["bench"][0]["uid"]
        self.choose("仓库与教学"); self.choose("招式机器")
        self.choose("冲浪"); self.click("C")
        self.assertEqual(self.device.page, "confirm")
        self.choose("确认")
        self.assertEqual(self.device.state["bench"][0]["technique"]["id"], "surf")
        self.assertEqual(self.device.state["bench"][0]["uid"], uid)
        self.choose("仓库与教学"); self.choose("招式机器")
        self.choose("睡觉"); self.click("C")
        self.assertIn("覆盖", self.state["screen"]["prompt"])
        seq = self.device.sequence
        self.click("C")
        self.assertEqual(self.device.sequence, seq)
        self.assertEqual(self.device.state["bench"][0]["technique"]["id"], "surf")

    def test_resume_link_and_device_cap_do_not_create_new_game(self):
        sid = self.classic()
        seq = self.device.sequence
        loaded = controls.api_input({"phase": "state", "sid": sid}, now=self.t+1)
        self.assertTrue(loaded["ok"], loaded)
        self.assertEqual(loaded["sid"], sid)
        self.assertEqual(loaded["sequence"], seq)
        for i in range(12):
            controls.api_input({"phase": "state"}, now=self.t+2+i)
        self.assertEqual(len(controls.DEVICES), 8)
        self.assertEqual(len(demo.SESSIONS), 1)

    def test_remembered_slot_survives_restart_without_loading_until_continue(self):
        sid = self.classic()
        seq = self.device.sequence
        demo.SESSIONS.clear()
        response = controls.api_input({"phase": "state", "remembered_sid": sid}, now=self.t+1)
        self.assertTrue(response["ok"], response)
        self.assertEqual(response["screen"]["page"], "home")
        self.assertEqual(response["sid"], sid)
        self.assertFalse(demo.SESSIONS)
        self.device_id = response["device_id"]
        self.t += 2
        self.choose("继续存档")
        self.assertEqual(self.device.page, "prep")
        self.assertEqual(self.device.sequence, seq)

    def test_warehouse_craft_equip_unequip_and_sell_cancel_use_saved_transactions(self):
        self.classic()
        self.choose("商店"); self.click("C")
        session = demo.SESSIONS[self.device.sid]
        session.player.inventory.components["hardstone"] = 1
        session.player.inventory.components["bell"] = 1
        saved = demo.api_action({"cmd": "save", "sid": self.device.sid})
        self.assertTrue(saved["ok"], saved)
        self.input("state")
        self.choose("仓库与教学"); self.choose("组件")
        self.choose("剩饭"); self.choose("确认")
        self.assertTrue(any(i["key"] == "leftovers" for i in self.device.state["items"]["finished"]))
        self.choose("仓库与教学"); self.choose("成品装备")
        self.choose("剩饭"); self.click("C"); self.choose("确认")
        self.assertEqual(self.device.state["bench"][0]["item"], "leftovers")
        self.choose("棋盘与备战"); self.choose("备战席"); self.click("C")
        self.choose("卸下装备")
        self.assertIsNone(self.device.state["bench"][0]["item"])
        self.choose("棋盘与备战"); self.choose("备战席"); self.click("C")
        seq = self.device.sequence
        self.choose("卖出"); self.click("C")
        self.assertEqual(self.device.sequence, seq)
        self.assertEqual(len(self.device.state["bench"]), 1)
        self.choose("卖出"); self.choose("确认")
        self.assertFalse(self.device.state["bench"])

    def test_incompatible_learning_explains_rejection_and_does_not_consume_inventory(self):
        self.classic()
        session = demo.SESSIONS[self.device.sid]
        from shop import OwnedPiece
        session.pool.take(4)
        session.player.bench.append(OwnedPiece(session.templates[4], 1))
        session.player.inventory.techniques["surf"] = 1
        self.assertTrue(demo.api_action({"cmd": "save", "sid": self.device.sid})["ok"])
        self.input("state")
        self.choose("仓库与教学"); self.choose("招式机器"); self.choose("冲浪")
        seq = self.device.sequence
        self.assertTrue(self.state["screen"]["rows"][0]["disabled"])
        self.click("C")
        self.assertEqual(self.device.page, "targets")
        self.assertIn("无法学习", self.state["screen"]["message"])
        self.assertEqual(self.device.sequence, seq)
        self.assertEqual(session.player.inventory.techniques["surf"], 1)

    def test_details_paginate_and_lists_scroll_with_only_three_keys(self):
        self.choose("挑战与图鉴"); self.choose("宝可梦图鉴")
        for _ in range(7):
            self.click("B")
        self.assertGreater(self.state["screen"]["offset"], 0)
        self.assertEqual(len(self.state["screen"]["rows"]), 5)
        self.long("B"); self.long("B")
        self.assertEqual(self.device.page, "home")
        self.classic(); self.choose("商店")
        self.long("C")
        self.assertEqual(self.device.page, "detail")
        self.assertGreaterEqual(self.state["screen"]["detail_total"], 1)
        total = self.state["screen"]["detail_total"]
        for _ in range(total+2):
            self.click("B")
        self.assertEqual(self.state["screen"]["detail_page"], total)
        self.click("C")
        self.assertEqual(self.device.page, "shop")

    def test_eliminated_prep_has_only_spectator_actions_and_no_shop(self):
        self.classic()
        session = demo.SESSIONS[self.device.sid]
        session.player.hp = 0
        session._eliminate(session.player)
        session.player.rank = 8
        session.phase = "battle"
        session.next_round()  # Rebuild valid surviving-seat pairings after elimination.
        saved = demo.api_action({"cmd": "save", "sid": self.device.sid})
        self.assertTrue(saved["ok"], saved)
        self.input("state")
        self.assertEqual(self.device.page, "spectate")
        self.assertFalse(any("商店" in r["label"] for r in self.device.rows()))
        seq = self.device.sequence
        self.long("B")
        self.assertEqual(self.device.page, "home")
        self.assertEqual(self.device.sequence, seq)

    def test_readonly_screen_and_shared_physical_input_transport(self):
        html = device_page.page_html()
        self.assertIn('width="240" height="320"', html)
        self.assertIn("pointer-events:none", html)
        self.assertNotIn("onclick=", html)
        self.assertIn("queue('down',key)", html)
        self.assertIn("queue('up',key)", html)
        self.assertIn("window.addEventListener('blur',cancel)", html)
        self.assertNotIn("ArrowLeft", html)
        self.assertEqual(html.count('class="key" data-key='), 3)
        self.assertIn('id="screen-text"', html)
        self.assertIn("if(actionPending||!device)", html)
        self.assertNotIn("if(pending){suppressed", html)
        self.assertIn("40", controls.piece_detail({"name": "测试", "item_effect": "开场获得40能量"}))

    @unittest.skipUnless(shutil.which("node"), "Node is required for browser transport fault injection")
    def test_client_tick_does_not_swallow_keys_and_network_recovery_never_replays_action(self):
        browser_script = device_page.HTML.split("<script>", 1)[1].split("</script>", 1)[0]
        setup = r'''
const assert=require('node:assert/strict');
const noop=()=>{};const fakeContext=new Proxy({}, {get:(t,k)=>t[k]||noop,set:(t,k,v)=>(t[k]=v,true)});
const classes={add:noop,remove:noop};const buttons=['A','B','C'].map(key=>({dataset:{key},classList:classes,addEventListener:noop}));
const elements={screen:{getContext:()=>fakeContext},status:{textContent:''},'screen-text':{textContent:''}};
global.document={getElementById:id=>elements[id],querySelector:()=>({classList:classes}),querySelectorAll:()=>buttons,addEventListener:noop,hidden:false};
global.window={addEventListener:noop};global.location={search:''};global.history={replaceState:noop};global.localStorage={getItem:()=>'',setItem:noop};
global.setInterval=noop;let calls=[],failPhase=null;
global.fetch=async url=>{const phase=new URL(url,'http://host').searchParams.get('phase');calls.push(phase);if(phase===failPhase){failPhase=null;throw Error('response lost after server receives request')}return {json:async()=>({ok:true,device_id:'testdevice',sid:'',sleeping:false,screen:{page:'home',title:'测试',rows:[],footer:[],message:'就绪'}})}};
'''
        verify = r'''
await chain;calls=[];
queue('tick');down('B');up('B');await chain;
assert.deepEqual(calls,['tick','down','up']);
calls=[];failPhase='down';down('C');up('C');await chain;
assert.equal(disconnected,true);queue('tick');await chain;
assert.deepEqual(calls,['down','cancel','state']);assert.equal(disconnected,false);
calls=[];down('C');await chain;failPhase='up';up('C');await chain;
queue('tick');await chain;
assert.deepEqual(calls,['down','up','cancel','state']);
assert.equal(calls.filter(p=>p==='up').length,1);assert.equal(pressed.size,0);
'''
        result = subprocess.run([shutil.which("node"), "-"], input="(async()=>{\n" + setup + browser_script + verify + "\n})().catch(e=>{console.error(e);process.exit(1)})",
                                text=True, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
