import sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'sim'),str(ROOT/'tools/mockups')]
from arena_preview_scene import make_preview_scene
from presentation_modes import make_renderer
font=ImageFont.load_default()
sid=int(sys.argv[1]); tag=sys.argv[2] if len(sys.argv)>2 else 'new'
anim=make_preview_scene(sid,'cast',7); r=make_renderer(anim,'arena').renderer
a=next(a for a in anim.timeline.actions if a.attacker==0 and a.kind=='cast' and not a.secondary)
ts=[a.start+(a.release-a.start)*.4,a.start+(a.release-a.start)*.85,(a.release+a.impact)/2,a.impact+.02,a.impact+.08,a.impact+.16,a.impact+.3,a.impact+.5]
p0=r.cell_point((0.45,float(sys.argv[3]) if len(sys.argv)>3 else 0.6)); p1=r.cell_point((3.55,3.75))
box=(int(p0[0]),int(p0[1]-40),int(p1[0]),int(p1[1]+10)); cw=(box[2]-box[0]); ch=(box[3]-box[1])
sheet=Image.new('RGB',(cw*4,ch*2),(0,0,0)); d=ImageDraw.Draw(sheet)
for i,t in enumerate(ts):
    xy=((i%4)*cw,(i//4)*ch); sheet.paste(r.frame(t).crop(box),xy)
    d.text((xy[0]+4,xy[1]+4),f'{sid} t={t:.2f}',font=font,fill='white')
sheet.save(f'one-{sid:03d}-{tag}.png'); print(sheet.size)
