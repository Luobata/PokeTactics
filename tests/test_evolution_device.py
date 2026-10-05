"""Three-key evolution decisions: preview, defer, lock, and explicit evolve."""
import copy
import json
from pathlib import Path
import shutil
import subprocess
import unittest
from unittest.mock import patch

import test_device_controls as base

demo, controls = base.demo, base.controls


class EvolutionDeviceContracts(unittest.TestCase):
    setUp = base.DeviceControlsContracts.setUp
    input = base.DeviceControlsContracts.input
    click = base.DeviceControlsContracts.click
    long = base.DeviceControlsContracts.long
    choose = base.DeviceControlsContracts.choose
    classic = base.DeviceControlsContracts.classic
    device = base.DeviceControlsContracts.device

    def tactical(self):
        self.choose("战术远征")
        self.choose("主搭档")
        self.choose("喷火龙")
        self.choose("出发")
        self.choose("确认")
        self.assertEqual(self.device.state["ruleset"], "tactics_v5")
        self.assertEqual(self.device.page, "prep")
        return demo.SESSIONS[self.device.sid]

    def pin_shop(self, session, species):
        for old in session.player.shop.slots:
            if old is not None:
                session.pool.put(old)
        session.player.shop.slots = [species] * 4
        for _ in range(4):
            session.pool.take(species)
        session.player.gold = 50
        self.assertTrue(demo.api_action({"cmd": "save", "sid": session.sid})["ok"])
        self.input("state")

    def buy_two(self, name):
        for _ in range(2):
            self.choose("商店")
            self.choose(name)

    def save_and_resume(self, session):
        self.assertTrue(demo.api_action({"cmd": "save", "sid": session.sid})["ok"])
        sid, locks = session.sid, [o.evolution_locked for o in session.player.bench]
        demo.SESSIONS.clear()
        self.input("state")
        self.choose("继续存档")
        self.assertEqual([o.evolution_locked for o in demo.SESSIONS[sid].player.bench], locks)
        return demo.SESSIONS[sid]

    def test_v5_buy_preview_cancel_auto_inheritance_and_repeat_release(self):
        session = self.tactical()
        self.pin_shop(session, 7)
        self.buy_two("杰尼龟")
        first = session.player.bench[0]
        session.player.bench[0].item = "leftovers"
        session.player.bench[0].technique = "surf"
        self.assertTrue(demo.api_action({"cmd": "save", "sid": session.sid})["ok"])
        self.input("state")

        sequence, gold = self.device.sequence, self.device.state["you"]["gold"]
        self.choose("商店"); self.choose("杰尼龟")
        self.assertEqual(self.device.page, "evolution_buy")
        self.assertEqual(self.device.sequence, sequence)
        self.assertEqual(len(self.device.state["bench"]), 2)
        preview = self.state["screen"]["evolution_preview"]
        merge = preview["merges"][0]
        self.assertEqual((merge["from_sid"], merge["to_sid"]), (7, 8))
        self.assertEqual(merge["source_uids"][0], first.uid)
        self.assertEqual(merge["inherit_item"], "leftovers")
        self.assertEqual(merge["inherit_technique"], "surf")
        self.assertIn("杰尼龟", merge["detail"])
        self.assertIn("羁绊", merge["detail"])
        self.assertIn("继承", merge["detail"])

        self.choose("购买并进化")
        self.click("C")  # Confirmation defaults to cancel and returns to the preview.
        self.assertEqual(self.device.sequence, sequence)
        self.assertEqual(len(session.player.bench), 2)
        self.choose("购买并进化"); self.choose("确认")
        self.assertEqual(self.device.sequence, sequence + 1)
        self.assertEqual(self.device.state["you"]["gold"], gold - 1)
        self.assertEqual(len(self.device.state["bench"]), 1)
        evolved = session.player.bench[0]
        self.assertEqual((evolved.piece.species_id, evolved.item, evolved.technique, evolved.uid),
                         (8, "leftovers", "surf", merge["result_uid"]))

        # A duplicate physical release cannot buy or open another transaction.
        sequence = self.device.sequence
        self.input("up", "C")
        self.input("tick")
        self.assertEqual(self.device.sequence, sequence)
        self.assertEqual(len(session.player.bench), 1)

    def test_v5_defer_persists_locks_and_manual_single_step_evolves(self):
        session = self.tactical()
        self.pin_shop(session, 7)
        self.buy_two("杰尼龟")
        self.choose("商店"); self.choose("杰尼龟"); self.choose("购买并暂缓")
        self.click("C")
        self.assertEqual(len(session.player.bench), 2)
        self.choose("购买并暂缓"); self.choose("确认")
        self.assertEqual(len(session.player.bench), 3)
        self.assertTrue(all(o.evolution_locked for o in session.player.bench))

        session = self.save_and_resume(session)
        self.assertTrue(all(o.evolution_locked for o in session.player.bench))
        uid = session.player.bench[0].uid
        self.choose("棋盘与备战"); self.choose("备战席"); self.choose("杰尼龟")
        labels = [row["label"] for row in self.device.rows()]
        self.assertIn("进化预览", labels)
        self.assertIn("解除形态锁定", labels)
        self.assertEqual(len(labels), 8)
        self.choose("进化预览")
        preview = self.state["screen"]["evolution_preview"]
        self.assertEqual(len(preview["merges"]), 1)
        self.assertIn("只进化一步", preview["detail"])
        self.choose("确认进化")
        self.click("C")
        self.assertEqual(len(session.player.bench), 3)
        self.choose("确认进化"); self.choose("确认")
        self.assertEqual(len(session.player.bench), 1)
        evolved = session.player.bench[0]
        self.assertEqual((evolved.piece.species_id, evolved.uid), (8, uid))
        self.assertFalse(evolved.evolution_locked)

        # Locked material was accepted by explicit evolve; a terminal species explains
        # why it neither combines nor exposes a lock.
        session.pool.take(131)
        session.player.bench.append(demo.shop_mod.OwnedPiece(session.templates[131], 3))
        self.assertTrue(demo.api_action({"cmd": "save", "sid": session.sid})["ok"])
        self.input("state")
        self.choose("棋盘与备战"); self.choose("备战席"); self.choose("拉普拉斯")
        labels = [row["label"] for row in self.device.rows()]
        self.assertIn("形态状态", labels)
        self.assertNotIn("解除形态锁定", labels)
        self.choose("形态状态")
        pages = ["".join(self.state["screen"]["detail"])]
        for _ in range(self.state["screen"]["detail_total"] - 1):
            pages.append("".join(self.click("B")["screen"]["detail"]))
        self.assertIn("已无后续关都进化", "".join(pages))

    def test_v5_unlock_cancel_confirm_and_locked_copies_do_not_combine(self):
        session = self.tactical()
        self.pin_shop(session, 7)
        self.buy_two("杰尼龟")
        self.choose("商店"); self.choose("杰尼龟"); self.choose("购买并暂缓"); self.choose("确认")
        self.assertEqual([o.evolution_locked for o in session.player.bench], [True, True, True])

        self.choose("棋盘与备战"); self.choose("备战席"); self.choose("杰尼龟")
        sequence = self.device.sequence
        self.choose("解除形态锁定"); self.click("C")
        self.assertEqual(self.device.sequence, sequence)
        self.assertEqual([o.evolution_locked for o in session.player.bench], [True, True, True])
        self.choose("解除形态锁定"); self.choose("确认")
        self.assertEqual([o.evolution_locked for o in session.player.bench], [False, True, True])

        session = self.save_and_resume(session)
        self.assertEqual([o.evolution_locked for o in session.player.bench], [False, True, True])
        self.choose("棋盘与备战"); self.choose("备战席"); self.choose("杰尼龟")
        self.choose("锁定当前形态"); self.choose("确认")
        self.assertEqual([o.evolution_locked for o in session.player.bench], [True, True, True])

        # With fewer than three unlocked copies, v5 keeps the old direct-buy flow.
        self.pin_shop(session, 7)
        sequence, bench = self.device.sequence, len(session.player.bench)
        self.choose("商店"); self.choose("杰尼龟")
        self.assertEqual(self.device.page, "prep")
        self.assertEqual(self.device.sequence, sequence + 1)
        self.assertEqual(len(session.player.bench), bench + 1)
        self.assertEqual([o.evolution_locked for o in session.player.bench[:3]], [True, True, True])

    def test_stale_evolution_confirmation_rejects_without_buy(self):
        session = self.tactical()
        self.pin_shop(session, 7)
        self.buy_two("杰尼龟")
        self.choose("商店"); self.choose("杰尼龟"); self.choose("购买并暂缓"); self.input("down", "C")
        changed = demo.api_action({"sid": session.sid, "cmd": "refresh"})
        self.assertTrue(changed["ok"], changed)
        self.input("state")
        self.assertEqual(self.device.page, "prep")
        self.assertEqual(len(session.player.bench), 2)
        self.assertEqual(session.player.gold, 46)
        self.assertEqual(self.device.sequence, changed["state"]["save"]["sequence"])

    def test_legacy_rules_keep_direct_automatic_combine(self):
        self.classic()
        session = demo.SESSIONS[self.device.sid]
        self.pin_shop(session, 7)
        self.buy_two("杰尼龟")
        self.assertFalse((self.device.state["shop"][0] or {}).get("evolution_preview"))
        self.choose("商店"); self.choose("杰尼龟")
        self.assertEqual(self.device.page, "prep")
        self.assertEqual(len(session.player.bench), 1)
        self.assertEqual(session.player.bench[0].piece.species_id, 8)
        self.assertFalse((self.device.state["bench"][0] or {}).get("evolution"))

    def test_renderer_evolution_text_and_native_canvas_bounds(self):
        session = self.tactical()
        self.pin_shop(session, 7)
        self.buy_two("杰尼龟")
        session.player.bench[0].item = "leftovers"
        self.assertTrue(demo.api_action({"cmd": "save", "sid": session.sid})["ok"])
        self.input("state")
        snapshots = []
        self.choose("商店"); self.choose("杰尼龟")
        snapshots.append(copy.deepcopy(self.state))
        rich = copy.deepcopy(snapshots[0])
        rich["screen"]["evolution_preview"]["merges"][0].update({
            "synergies_before": {"WATER": 2, "FIRE": 1},
            "synergies_after": {"WATER": 1},
            "returned_items": [],
            "returned_techniques": {"surf": 1},
            "inherit_item": None,
            "inherit_technique": None,
        })
        snapshots.append(rich)
        self.choose("购买并暂缓")
        snapshots.append(copy.deepcopy(self.state))
        self.choose("确认")
        self.choose("棋盘与备战"); self.choose("备战席"); self.choose("杰尼龟")
        snapshots.append(copy.deepcopy(self.state))

        renderer = (Path(__file__).resolve().parents[1] / "tools/acceptance/device_renderer.js").read_text()
        setup = r'''
const assert=require('node:assert/strict');let drawing=[];
const noop=()=>{},context={font:'12px sans-serif',fillStyle:'#000',imageSmoothingEnabled:false,
measureText(s){const size=Number(this.font.match(/(\d+)px/)[1]);return {width:Array.from(String(s)).reduce((n,ch)=>n+(ch.charCodeAt(0)>255?size:size*.55),0)}},
fillRect(x,y,w,h){assert.ok(this.fillStyle,'missing colour');drawing.push({kind:'rect',x,y,w,h});},
fillText(s,x,y){assert.ok(this.fillStyle,'missing colour');drawing.push({kind:'text',s,x,y,w:this.measureText(s).width,h:Number(this.font.match(/(\d+)px/)[1])});},drawImage:noop};
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
const text=drawing.filter(d=>d.kind==='text').map(d=>d.s).join('|');
 if(state.screen.page==='shop')assert.match(text,/三合一/);
 if(state.screen.page==='evolution_buy'){
   assert.match(text,/杰尼龟 → 卡咪龟/);
   assert.match(text,/上场/);assert.match(text,/羁绊/);
   if(!state.screen.evolution_preview?.merges?.[0]?.returned_techniques?.surf)assert.match(text,/装备继承/);
   assert.match(text,/购买并暂缓/);
   const cancel=drawing.find(d=>d.s==='取消购买');
   assert.ok(cancel&&cancel.y+cancel.h<=296,JSON.stringify(cancel));
   assert.ok(!text.includes('长按 C 查看完整代价'),'evolution rows must stay single-line');
   assert.ok(!text.includes('保留三只并锁定同名实例'),'evolution row subtitles must be hidden');
   const card=drawing.find(d=>d.kind==='rect'&&d.x===9&&d.y===60&&d.w===222&&d.h===123);
   assert.ok(card,'evolution detail card must contain the inheritance row');
 }
 if(state.screen.page==='evolution_buy'&&state.screen.evolution_preview?.merges?.[0]?.returned_techniques?.surf){
   assert.match(text,/水2、火1 → 水1/);
   assert.match(text,/多余教学回仓/);
   assert.doesNotMatch(text,/\[object Object\]/);
 }
 if(state.screen.page==='confirm')assert.match(text,/暂缓进化/);
 if(state.screen.page==='piece'){
   assert.match(text,/进化预览|形态状态/);
   assert.match(text,/解除形态锁定/);
 }
}
'''
        result = subprocess.run([shutil.which("node"), "-"], input=setup + renderer +
                                "\nconst screens=" + json.dumps(snapshots, ensure_ascii=False) + ";\n" + check,
                                text=True, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
