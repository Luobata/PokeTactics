import sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT/'sim'),str(ROOT/'tools/mockups')]
from arena_preview_scene import make_preview_scene
from presentation_modes import make_renderer
from arena import ROSTER
out=ROOT/'.build/vfx-review'
font=ImageFont.load_default()
ids=list(ROSTER)[:20]
print(ids)
for sid in ids:
  for kind in ('attack','cast'):
    try:
      anim=make_preview_scene(sid,kind,7)
      r=make_renderer(anim,'arena').renderer
      a=next(a for a in anim.timeline.actions if a.attacker==0 and a.kind==kind and not a.secondary)
      ts=((a.start+a.release)/2,a.release,(a.release+a.impact)/2,a.impact,a.impact+.1,a.impact+.25)
      p0=r.cell_point((0.45,-0.3 if kind=='cast' else 1.2)); p1=r.cell_point((3.55,3.75))
      box=(int(p0[0]),int(p0[1]-40),int(p1[0]),int(p1[1]+10)); cw=(box[2]-box[0])*3//2; ch=(box[3]-box[1])*3//2
      sheet=Image.new('RGB',(cw*3,ch*2+2),(17,27,30)); d=ImageDraw.Draw(sheet)
      for i,t in enumerate(ts):
        im=r.frame(t).crop(box).resize((cw,ch),Image.Resampling.NEAREST)
        xy=((i%3)*cw,(i//3)*(ch+2)); sheet.paste(im,xy)
        d.text((xy[0]+4,xy[1]+4),f'{sid} {kind} {getattr(a,"move",None) or ""} t={t:.2f}',font=font,fill='white')
      sheet.save(out/f'{sid:03d}-{kind}.png')
    except Exception as e:
      print('ERR',sid,kind,repr(e))
