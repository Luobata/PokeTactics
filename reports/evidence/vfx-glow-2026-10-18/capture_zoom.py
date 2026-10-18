import sys
from pathlib import Path
from PIL import Image
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'sim'),str(ROOT/'tools/mockups')]
from arena_preview_scene import make_preview_scene
from presentation_modes import make_renderer
sid=int(sys.argv[1]); cell=tuple(map(float,sys.argv[2].split(','))); offs=[float(x) for x in sys.argv[3].split(',')]
anim=make_preview_scene(sid,'cast',7); r=make_renderer(anim,'arena').renderer
a=next(a for a in anim.timeline.actions if a.attacker==0 and a.kind=='cast')
c=r.cell_point(cell); box=(int(c[0]-110),int(c[1]-120),int(c[0]+110),int(c[1]+20))
ims=[r.frame(a.impact+o).crop(box) for o in offs]
w,h=ims[0].size; s=Image.new('RGB',(w*len(ims),h))
for i,im in enumerate(ims): s.paste(im,(i*w,0))
s.resize((s.width*2,s.height*2),Image.NEAREST).save(f'zoom{sid}.png')
