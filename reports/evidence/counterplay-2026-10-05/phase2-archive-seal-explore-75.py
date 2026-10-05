import sys
sys.path.insert(0,'sim')
import inspect,textwrap,json
from dataclasses import replace
from experiment_tactics import measure
from experiment_build_diversity import BUILDS
import combat
from combat import Battle
garden,battery,dive,disrupt=BUILDS
orig_l,orig_h,orig_d=Battle._land_hit,Battle._heal,Battle._deploy
def deploy(self,*args,**kwargs):
 orig_d(self,*args,**kwargs)
 for u in self.units:
  if getattr(u,'item_key',None)=='focus_lens': u.item_ult_dmg=0.;u.energy=0
Battle._deploy=deploy
def land(self,u,target,dmg,t,**kw):
 orig_l(self,u,target,dmg,t,**kw)
 if getattr(u,'item_key',None)=='focus_lens' and kw.get('cast') and dmg>0 and target.alive and not getattr(u,'seal_used',False):
  u.seal_used=True
  target.seal_until=t+10
  self.events.append((t,'tactical_effect',u.idx,target.idx,'seal',{}))
def heal(self,u,amount,t):
 if t<getattr(u,'seal_until',-1): amount=int(amount*.25)
 return orig_h(self,u,amount,t)
source=textwrap.dedent(inspect.getsource(Battle.run))
old="""healed = min(u.max_hp, u.hp + max(
                            1, int(u.max_hp * (u.synergy_heal + u.item_heal)))) - u.hp
                        u.hp += healed
                        if healed:
                            self.events.append((t, "regen", u.idx, healed))
                            self._emit_state(u, t)"""
source=source.replace(textwrap.dedent(old),textwrap.dedent(old))
# Match body after dedenting outer method.
start=source.index('                healed = min')
end=source.index('        next_regen += 1.0',start)
source=source[:start]+"""                self._heal(u, max(1,int(u.max_hp*(u.synergy_heal+u.item_heal))),t)
"""+source[end:]
namespace=dict(vars(combat));exec(source,namespace)
Battle.run=namespace['run'];Battle._land_hit,Battle._heal=land,heal
rows=[]
for a in (battery,disrupt,replace(battery,key='lens_on_gengar',items=('sash',None,'focus_lens','swift_feather',None,None)),replace(disrupt,key='lens_on_gengar',items=('focus_lens',None,'swift_feather',None,'sash',None))):
 r=measure('seal_60_8',a,garden,range(310300,310320))
 rows.append({k:r[k] for k in ('arm','a','b','a_win_rate','a_casts_mean','tactical_trigger_trials','side_swap_failures')})
print(json.dumps(rows,indent=2))
