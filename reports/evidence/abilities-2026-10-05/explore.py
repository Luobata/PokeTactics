import json,sys
from dataclasses import replace
from pathlib import Path
sys.path[:0]=['tools/acceptance','sim']
from weather_ability_probe import SUN,RAIN,arm
from experiment_build_diversity import BUILDS
candidates=[replace(BUILDS[1],key='sun_battery',species=(9,6,38,26,65,82)),replace(BUILDS[1],key='rain_battery',species=(9,131,94,26,65,82)),replace(BUILDS[0],key='rain_garden',species=(143,131,3,80,76,2)),replace(BUILDS[3],key='sun_disrupt',species=(38,3,6,26,76,65))]
rows=[]
for a in candidates:
 for b in (BUILDS[0],BUILDS[2]):
  for version in ('tactics_v1','tactics_v2'):
   row=arm(a,b,range(310050,310070),version);rows.append(row)
   print(a.key,b.key,version,row['score'],row['a_windows']['window_buffed_casts'],flush=True)
Path('.build/entry-weather/exploration.json').write_text(json.dumps({'method':'Development-only candidate selection, 20 seeds reused across arms. Does not certify balance. Single same-cost unit substitutions retain all equipment, learning, partner and geometry.','candidates':[{'key':x.key,'species':x.species,'items':x.items,'learned':x.learned,'cost':x.cost} for x in candidates],'arms':rows},ensure_ascii=False,indent=2)+'\n')
