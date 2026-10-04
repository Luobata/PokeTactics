"""Saved tactical actions exercised through down/up/long physical gestures."""
import copy
import json
from pathlib import Path
import shutil
import subprocess
import unittest
from unittest.mock import patch

import test_device_controls as base

demo, controls = base.demo, base.controls


def tactical_render(*args, **kwargs):
    # Production rendering deploys both teams with layout="back". Random
    # deployment would invalidate otherwise adjacent saved bot selections.
    kwargs["layout"] = "back"
    return base.fast_render(*args, **kwargs)


class TacticalDeviceContracts(unittest.TestCase):
    def setUp(self):
        base.DeviceControlsContracts.setUp(self)
        seed = patch.object(demo.secrets, "randbits", return_value=1337)
        seed.start()
        self.addCleanup(seed.stop)
        renderer = patch.object(demo, "_render_battle_frames", side_effect=tactical_render)
        renderer.start()
        self.addCleanup(renderer.stop)
    input = base.DeviceControlsContracts.input
    click = base.DeviceControlsContracts.click
    long = base.DeviceControlsContracts.long
    choose = base.DeviceControlsContracts.choose
    classic = base.DeviceControlsContracts.classic
    device = base.DeviceControlsContracts.device

    def tactical(self):
        self.choose("战术远征")
        self.assertEqual(self.state["screen"]["scene"]["loadout_mode"], "tactics")
        self.choose("主搭档")
        self.choose("喷火龙")
        self.choose("出发")
        self.choose("确认")
        self.assertEqual(self.device.state["ruleset"], "tactics_v1")
        self.assertEqual(self.device.page, "prep")
        return demo.SESSIONS[self.device.sid]

    def save_fixture(self, session):
        result = demo.api_action({"sid": session.sid, "cmd": "save"})
        self.assertTrue(result["ok"], result)
        self.input("state")

    def add_piece(self, session, species, pos=None, technique=None):
        session.pool.take(species)
        piece = demo.shop_mod.OwnedPiece(session.templates[species], session.templates[species].tier)
        piece.technique = technique
        if pos is None:
            session.player.bench.append(piece)
        else:
            session.player.grid[pos] = piece
        session.player.level = 7
        return piece

    def open_piece(self, name, row="战场第一行"):
        self.choose("棋盘与备战")
        self.choose(row)
        self.choose(name)

    def learn(self, name, target):
        self.choose("仓库与教学")
        self.choose("招式机器")
        self.choose(name)
        self.choose(target)
        self.choose("确认")

    def test_tactical_entry_cancel_preserves_classic_and_expedition(self):
        self.choose("战术远征")
        self.choose("主搭档"); self.choose("喷火龙")
        self.choose("出发")
        self.click("C")  # Default cancellation, no run created.
        self.assertFalse(demo.SESSIONS)
        self.long("B")
        self.choose("启程 · 远征")
        self.choose("出发"); self.choose("确认")
        self.assertEqual(self.device.state["ruleset"], "base_v1")
        self.open_piece("小火龙")
        self.assertFalse(any(row["action"] == "piece_tactics" for row in self.device.rows()))
        self.long("B"); self.long("B"); self.long("B"); self.long("B")
        self.assertEqual(self.device.page, "home")
        self.classic()
        self.assertEqual(self.device.state["ruleset"], "base_v1")
        self.assertIsNone(self.device.state["expedition"])

    def test_real_pve_reward_cancel_claim_learn_guard_and_fight(self):
        session = self.tactical()
        water = self.add_piece(session, 7, (0, 3))
        session.begin_round(5)
        self.save_fixture(session)
        self.choose("开战"); self.choose("确认")
        self.assertEqual(self.device.page, "result", (session.seed, self.state["screen"].get("message")))
        self.choose("下一轮")
        rewards = self.device._pending_rewards()
        self.assertEqual(len(rewards), 1)
        frozen = copy.deepcopy(rewards[0])
        self.assertIn("guard", [option["id"] for option in frozen["options"]])
        self.assertEqual(sum(session.player.inventory.techniques.values()), 0)
        self.choose("开战")
        self.assertEqual(self.device.page, "rewards")
        self.click("C"); self.choose("护卫")
        seq = self.device.sequence
        self.click("C")  # Default cancel.
        self.assertEqual(self.device.sequence, seq)
        self.assertEqual(self.device._pending_rewards()[0], frozen)
        self.choose("护卫"); self.choose("确认")
        self.assertEqual(session.player.inventory.techniques["guard"], 1)
        self.assertFalse(self.device._pending_rewards())
        seq = self.device.sequence
        self.input("up", "C"); self.input("tick")
        self.assertEqual(session.player.inventory.techniques["guard"], 1)
        self.assertEqual(self.device.sequence, seq)
        self.learn("护卫", "杰尼龟")
        self.assertEqual(water.technique, "guard")
        self.assertEqual(session.player.inventory.techniques["guard"], 0)
        self.open_piece("杰尼龟"); self.choose("战术配置")
        self.choose("选择护卫对象"); self.choose("小火龙")
        preview = self.state["screen"]["tactical_preview"]["guard"]
        self.assertEqual(preview["uid"], water.uid)
        self.assertIsNone(session.tactical[0]["guard"])
        self.choose("确认")
        self.assertEqual(session.tactical[0]["guard"], preview)
        self.assertEqual(self.state["screen"]["scene"]["tactical"]["guard"], preview)
        self.choose("开战"); self.choose("确认")
        self.assertEqual(self.device.page, "result", (session.seed, self.state["screen"].get("message")))

    def test_guard_adjacent_preview_cancel_clear_and_move_invalidates(self):
        session = self.tactical()
        water = self.add_piece(session, 7, (0, 3), "guard")
        self.add_piece(session, 1, (1, 5))
        self.save_fixture(session)
        self.open_piece("杰尼龟"); self.choose("战术配置"); self.choose("选择护卫对象")
        sequence = self.device.sequence
        self.choose("妙蛙种子")
        self.assertEqual(self.device.page, "guard_targets")
        self.assertFalse(self.state["screen"]["tactical_preview"]["valid"])
        self.assertIn("相邻", self.state["screen"]["message"])
        self.assertEqual(self.device.sequence, sequence)
        self.choose("小火龙"); self.long("B")
        self.assertIsNone(session.tactical[0]["guard"])
        self.choose("小火龙"); self.choose("确认")
        first = copy.deepcopy(session.tactical[0]["guard"])
        self.open_piece("小火龙"); self.choose("战术配置"); self.choose("关闭本队护卫")
        self.click("C")
        self.assertEqual(session.tactical[0]["guard"], first)
        self.choose("关闭本队护卫"); self.choose("确认")
        self.assertIsNone(session.tactical[0]["guard"])
        self.open_piece("杰尼龟"); self.choose("战术配置"); self.choose("选择护卫对象")
        self.choose("小火龙"); self.choose("确认")
        self.open_piece("杰尼龟"); self.choose("移动 / 交换")
        self.choose("战场第一行"); self.choose("1 · 空位")
        self.assertIsNone(session.tactical[0]["guard"])
        self.assertEqual(session.player.grid[(0, 0)].uid, water.uid)
        self.assertIsNone(self.state["screen"]["scene"]["tactical"]["guard"])

    def test_weather_learning_compatibility_deployment_choice_and_clear(self):
        session = self.tactical()
        water = self.add_piece(session, 7)
        session.player.inventory.techniques["rain_dance"] = 1
        session.player.inventory.techniques["sunny_day"] = 1
        self.save_fixture(session)
        self.choose("仓库与教学"); self.choose("招式机器"); self.choose("求雨")
        sequence = self.device.sequence
        self.choose("小火龙")
        self.assertEqual(self.device.page, "targets")
        self.assertIn("无法学习", self.state["screen"]["message"])
        self.assertEqual(self.device.sequence, sequence)
        self.choose("杰尼龟"); self.choose("确认")
        self.open_piece("杰尼龟", "备战席"); self.choose("战术配置")
        self.choose("设为本队天气手")
        self.assertEqual(self.device.page, "piece_tactics")
        self.assertIn("需上场", self.state["screen"]["message"])
        self.long("B"); self.choose("移动 / 交换"); self.choose("战场第一行"); self.choose("4 · 空位")
        self.open_piece("杰尼龟"); self.choose("战术配置"); self.choose("设为本队天气手")
        self.assertIsNone(session.tactical[0]["weather"])
        self.click("C")
        self.assertIsNone(session.tactical[0]["weather"])
        self.choose("设为本队天气手"); self.choose("确认")
        self.assertEqual(session.tactical[0]["weather"], {"uid": water.uid})
        self.learn("晴天", "小火龙")
        self.open_piece("小火龙"); self.choose("战术配置"); self.choose("设为本队天气手"); self.choose("确认")
        fire = session.player.grid[(0, 2)]
        self.assertEqual(session.tactical[0]["weather"], {"uid": fire.uid})
        self.open_piece("小火龙"); self.choose("移动 / 交换"); self.choose("备战席"); self.click("C")
        self.assertIsNone(session.tactical[0]["weather"])  # Rain user never auto-relays.
        self.open_piece("杰尼龟"); self.choose("战术配置"); self.choose("设为本队天气手"); self.choose("确认")
        self.open_piece("杰尼龟"); self.choose("战术配置"); self.choose("关闭本队天气手"); self.choose("确认")
        self.assertIsNone(session.tactical[0]["weather"])
        self.assertEqual(water.technique, "rain_dance")

    def test_pending_reward_resume_skip_and_stale_held_confirmation(self):
        session = self.tactical()
        self.add_piece(session, 7, (0, 3), "guard")
        session.begin_round(6)
        session._grant_technique_choice(session.player, 5)
        self.save_fixture(session)
        frozen = copy.deepcopy(self.device._pending_rewards())
        self.choose("仓库与教学"); self.choose("待领补给"); self.click("C")
        self.choose("护卫"); self.click("B")
        self.input("down", "C")
        saved = demo.api_action({"sid": session.sid, "cmd": "save"})
        self.assertTrue(saved["ok"], saved)
        self.input("up", "C")
        self.assertEqual(self.device.page, "prep")
        self.assertEqual(session.player.inventory.techniques["guard"], 0)
        self.assertEqual(self.device._pending_rewards(), frozen)
        self.open_piece("杰尼龟"); self.choose("战术配置"); self.choose("选择护卫对象")
        self.choose("小火龙"); self.choose("确认")
        expected_tactics = copy.deepcopy(session.tactical[0])
        sid, sequence = self.device.sid, self.device.sequence
        demo.SESSIONS.clear()
        response = controls.api_input({"phase": "state", "sid": sid}, now=self.t+1)
        self.assertTrue(response["ok"], response)
        self.device_id = response["device_id"]
        self.t += 2
        self.input("state")
        self.assertEqual(self.device.sequence, sequence)
        self.assertEqual(self.device._pending_rewards(), frozen)
        self.assertEqual(self.device.state["tactical"], expected_tactics)
        self.choose("仓库与教学"); self.choose("待领补给"); self.click("C")
        self.choose("放弃本次"); self.long("B")
        self.assertEqual(self.device._pending_rewards(), frozen)
        self.choose("放弃本次"); self.choose("确认")
        self.assertFalse(self.device._pending_rewards())
        self.assertEqual(sum(demo.SESSIONS[sid].player.inventory.techniques.values()), 0)
        self.assertEqual(self.device.state["rewards"][0]["status"], "closed")

    def test_stale_guard_target_and_spent_machine_cancel_before_commit(self):
        session = self.tactical()
        water = self.add_piece(session, 7, (0, 3), "guard")
        grass = self.add_piece(session, 1, (1, 5))
        session.player.inventory.techniques["rest"] = 1
        self.save_fixture(session)
        self.open_piece("杰尼龟"); self.choose("战术配置"); self.choose("选择护卫对象")
        self.choose("小火龙"); self.click("B"); self.input("down", "C")
        changed = demo.api_action({"sid": session.sid, "cmd": "move", "from": "g0,2", "to": "g0,0"})
        self.assertTrue(changed["ok"], changed)
        self.input("up", "C")
        self.assertEqual(self.device.page, "prep")
        self.assertIsNone(session.tactical[0]["guard"])
        self.assertEqual(self.device.sequence, changed["state"]["save"]["sequence"])
        self.choose("仓库与教学"); self.choose("招式机器"); self.choose("睡觉")
        self.choose("小火龙"); self.click("B"); self.input("down", "C")
        other = demo.api_action({"sid": session.sid, "cmd": "learn", "uid": grass.uid, "technique": "rest"})
        self.assertTrue(other["ok"], other)
        self.input("up", "C")
        self.assertEqual(self.device.page, "prep")
        self.assertEqual(session.player.inventory.techniques["rest"], 0)
        self.assertIsNone(session.player.grid[(0, 0)].technique)
        self.assertEqual(water.technique, "guard")
        self.assertEqual(self.device.sequence, other["state"]["save"]["sequence"])

    @unittest.skipUnless(shutil.which("node"), "Node is required for native canvas bounds")
    def test_tactical_screens_fit_native_canvas_and_retain_board(self):
        snapshots = [copy.deepcopy(self.state)]
        session = self.tactical()
        self.add_piece(session, 7, (0, 3), "guard")
        session.begin_round(6)
        session._grant_technique_choice(session.player, 5)
        self.save_fixture(session)
        snapshots.append(copy.deepcopy(self.state))
        self.choose("仓库与教学"); snapshots.append(copy.deepcopy(self.state))
        self.choose("待领补给"); self.click("C")
        for _ in range(4):
            snapshots.append(copy.deepcopy(self.state)); self.click("B")
        self.long("B"); self.long("B"); self.long("B")
        self.open_piece("杰尼龟"); snapshots.append(copy.deepcopy(self.state))
        self.choose("战术配置"); snapshots.append(copy.deepcopy(self.state))
        self.choose("选择护卫对象"); snapshots.append(copy.deepcopy(self.state))
        self.choose("小火龙"); snapshots.append(copy.deepcopy(self.state))
        renderer = (Path(__file__).resolve().parents[1] / "tools/acceptance/device_renderer.js").read_text()
        setup = r'''
const assert=require('node:assert/strict');let drawing=[];
const noop=()=>{},context={font:'12px sans-serif',fillStyle:'#000',imageSmoothingEnabled:false,
measureText(s){const size=Number(this.font.match(/(\d+)px/)[1]);return {width:Array.from(String(s)).reduce((n,ch)=>n+(ch.charCodeAt(0)>255?size:size*.55),0)}},
fillRect(x,y,w,h){assert.ok(this.fillStyle, 'missing colour');drawing.push({kind:'rect',x,y,w,h});},
fillText(s,x,y){drawing.push({kind:'text',s,x,y,w:this.measureText(s).width,h:Number(this.font.match(/(\d+)px/)[1])});},drawImage:noop};
const elements={screen:{getContext:()=>context},status:{},'screen-text':{},'context-hint':{}};
global.document={getElementById:id=>elements[id]};global.location={search:''};
'''
        check = r'''
for(const state of screens){view=state;drawing=[];draw();
 for(const d of drawing){
   assert.ok(d.x>=0&&d.x+d.w<=241,JSON.stringify({page:state.screen.page,...d}));
   assert.ok(d.y>=0&&d.y<=320,JSON.stringify({page:state.screen.page,...d}));
   if(d.kind==='rect')assert.ok(d.y+d.h<=320,JSON.stringify({page:state.screen.page,...d}));
 }
 if(state.screen.page==='guard_targets'){
   assert.ok(drawing.some(d=>d.kind==='rect'&&d.y===130&&d.w===40),'own board disappeared');
   assert.ok(drawing.some(d=>d.kind==='text'&&d.s==='护'),'guard marker absent');
 }
 if(state.screen.page==='reward_options')assert.ok(drawing.filter(d=>d.kind==='rect'&&d.w===226).length>=4,'missing choice cards');
}
'''
        result = subprocess.run([shutil.which("node"), "-"], input=setup+renderer+"\nconst screens="+json.dumps(snapshots, ensure_ascii=False)+";\n"+check,
                                text=True, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
