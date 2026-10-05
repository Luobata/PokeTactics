#!/usr/bin/env python3
import json,sys
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2]; sys.path[:0]=[str(ROOT/'tools/acceptance'),str(ROOT/'sim'),str(ROOT)]
import demo
from bots import PERSONALITIES
import tactical_run_probe as base
from pressure_probe import patched_loss,summarize
ARMS={'r20_floor20':{'start':20,'floor':20},'r20_floor21':{'start':20,'floor':21}}
SEED_BASE=2026102000; GAMES=64; out={}
with patch.object(demo,'SESSIONS',{}),patch.object(demo,'Battle',base.ObservedBattle),patch.object(demo,'_render_battle_frames',side_effect=base.headless):
  for arm,cfg in ARMS.items():
    rows=[]
    with patch.object(demo.economy,'loss_damage',patched_loss(cfg)):
      for i in range(GAMES): rows.append(base.game(SEED_BASE+i,sorted(PERSONALITIES)[i%4],'tactics_v2'))
    out[arm]={'config':cfg,'summary':summarize(rows),'games':rows}; print(arm,json.dumps(out[arm]['summary'],ensure_ascii=False),flush=True)
Path(__file__).with_name('pressure-boundary-n64.json').write_text(json.dumps({'seed_base':SEED_BASE,'games_per_arm':GAMES,'arms':out},ensure_ascii=False,indent=2)+'\n')
