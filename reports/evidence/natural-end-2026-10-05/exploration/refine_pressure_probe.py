#!/usr/bin/env python3
import json, sys
from pathlib import Path
from unittest.mock import patch
ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/'tools/acceptance'), str(ROOT/'sim'), str(ROOT)]
import demo
from bots import PERSONALITIES
import tactical_run_probe as base
from pressure_probe import patched_loss, summarize
ARMS = {'baseline_v2': None, 'r20_floor22': {'start':20,'floor':22}, 'r20_floor24': {'start':20,'floor':24}}
SEED_BASE=2026102000; GAMES=64
rows_by_arm={}
with patch.object(demo,'SESSIONS',{}), patch.object(demo,'Battle',base.ObservedBattle), patch.object(demo,'_render_battle_frames',side_effect=base.headless):
    for arm, config in ARMS.items():
        rows=[]
        with patch.object(demo.economy,'loss_damage',patched_loss(config)):
            for i in range(GAMES): rows.append(base.game(SEED_BASE+i,sorted(PERSONALITIES)[i%4],'tactics_v2'))
        rows_by_arm[arm]={'config':config,'summary':summarize(rows),'games':rows}
        print(arm,json.dumps(rows_by_arm[arm]['summary'],ensure_ascii=False),flush=True)
Path(__file__).with_name('pressure-refine-n64.json').write_text(json.dumps({'seed_base':SEED_BASE,'games_per_arm':GAMES,'arms':rows_by_arm},ensure_ascii=False,indent=2)+'\n')
