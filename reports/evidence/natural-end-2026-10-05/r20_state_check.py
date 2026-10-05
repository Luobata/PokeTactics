#!/usr/bin/env python3
"""Re-run the formal seeds through R20 and compare an explicit seat projection."""
import hashlib, json, random, statistics, sys
from collections import Counter
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'tools/acceptance'),str(ROOT/'sim'),str(ROOT)]
import demo, pacing
from bots import PERSONALITIES
import tactical_run_probe as base
from session_save import SessionCodec, rules_fingerprint
CODEC=SessionCodec()
SEED_BASE=2026103000; GAMES=100

def projection(session):
 return [{'seat':s.seat,'alive':s.alive,'hp':s.hp,'rank':s.rank,
          'level':s.level,'gold':s.gold,'board':len(s.board),
          'bench':len(s.bench),'combines':getattr(s,'combines',0),
          'machines':sum(s.inventory.techniques.values())+sum(o.technique is not None for o in s.all_pieces())}
         for s in session.seats]

def limited_game(seed,personality,ruleset):
 row={'seed':seed,'personality':personality,'ruleset':ruleset,
      'status':'running','current_round':1,'battle_count':0,
      'player_battle_count':0,'tactical_events':Counter(),
      'player_battle_tactical_events':Counter(),'actions':Counter(),
      'claimed_techniques':Counter(),'blocked_actions':[],'sample_events':[],
      'invalidated_configuration_notices':[],'guard_configured_rounds':0,
      'weather_configured_rounds':0,'checkpoints':[],'rounds':[]}
 base.CONTEXT['row']=row
 session=demo.Session(seed,ruleset=ruleset)
 session.sid=f'{seed:012x}'
 session.run_id=hashlib.sha256(f'tactics-smoke:{seed}'.encode()).hexdigest()[:32]
 session.expedition={'partner':6,'technique':None,'item':None}
 session.begin_round(1)
 from expedition import deploy_starter
 deploy_starter(session); session.observe()
 demo.SESSIONS[session.sid]=session
 pilot=base.Bot(0,2,personality,session.pool,session.templates)
 checkpoints=random.Random(seed).choice(((6,),(11,),(6,11)))
 def checkpoint(current,stage):
  before=CODEC.encode(current); restored=CODEC.decode(before,4)
  assert CODEC.encode(restored)==before
  restored.sid=current.sid; demo.SESSIONS[current.sid]=restored
  pilot.pool,pilot.templates=restored.pool,restored.templates
  return restored
 try:
  for _ in range(demo.MAX_ROUNDS):
   if session.phase=='over': break
   row['current_round']=session.round_no
   before_rewards=(seed+session.round_no)%2==0
   if session.round_no in checkpoints and before_rewards: session=checkpoint(session,'before_player_rewards')
   if session.player.alive: base.pilot_prep(session,pilot)
   if session.round_no in checkpoints and not before_rewards: session=checkpoint(session,'after_player_rewards')
   base.invariant(session); base.action(session,'end_prep'); base.invariant(session)
   if session.round_no==20:
    row['phase_after_r20']=session.phase
    row['seat_projection_after_r20']=projection(session)
    row['pending_rewards']=sum(r['status']=='pending' for r in session.rewards)
    row['status']='stopped_after_r20'
    return row
   base.action(session,'next')
  raise AssertionError(f'did not reach R20 at {session.round_no}')
 except Exception as exc:
  row.update(status='error',error=repr(exc))
  return row
 finally:
  demo.SESSIONS.pop(session.sid,None); base.CONTEXT['row']=None

def main():
 personalities=sorted(PERSONALITIES); games={}
 with patch.object(demo,'SESSIONS',{}),patch.object(demo,'Battle',base.ObservedBattle),patch.object(demo,'_render_battle_frames',side_effect=base.headless):
  for ruleset in ('tactics_v3','tactics_v4'):
   rows=[limited_game(SEED_BASE+i,personalities[i%4],ruleset) for i in range(GAMES)]
   games[ruleset]=rows
   print(ruleset,'complete',sum(r['status']=='stopped_after_r20' for r in rows),flush=True)
 base_rows=games['tactics_v3']; candidate_rows=games['tactics_v4']
 comparisons=[]
 fields=('alive','hp','rank','level','gold','board','bench','combines','machines')
 for a,b in zip(base_rows,candidate_rows):
  comparison={'seed':a['seed'],'status_pair':(a['status'],b['status']),
              'same_projection':a['seat_projection_after_r20']==b['seat_projection_after_r20'],
              'differing_fields':sorted({field for x,y in zip(a['seat_projection_after_r20'],b['seat_projection_after_r20'])
                                          for field in fields if x[field]!=y[field]}),
              'same_pending_rewards':a['pending_rewards']==b['pending_rewards']}
  comparisons.append(comparison)
 summary={'games':GAMES,'complete_pairs':sum(x['status_pair']==('stopped_after_r20','stopped_after_r20') for x in comparisons),
          'same_full_projection':sum(x['same_projection'] for x in comparisons),
          'same_pending_rewards':sum(x['same_pending_rewards'] for x in comparisons),
          'field_same_counts':{field:sum(all(x[field]==y[field] for x,y in zip(a['seat_projection_after_r20'],b['seat_projection_after_r20']))
                                          for a,b in zip(base_rows,candidate_rows)) for field in fields}}
 payload={'method':__doc__,'seed_base':SEED_BASE,'games':GAMES,'rules_fingerprint':rules_fingerprint(),
          'summary':summary,'comparisons':comparisons,
          'limits':['Limited state projection after end_prep(R20); not a claim that unrecorded runtime objects are identical.']}
 Path(__file__).with_name('r20-state-check.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n')
 print(json.dumps(summary,ensure_ascii=False,indent=2))
if __name__=='__main__': main()
