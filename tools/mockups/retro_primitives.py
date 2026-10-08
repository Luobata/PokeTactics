"""Bounded, deterministic pixel-art building blocks for authored arena moves.

All coordinates passed by renderers are actual screen positions. These helpers
draw only; they never select recipients or read/write simulation state.
"""
import math
from PIL import Image, ImageDraw

PIXEL = 3
_INKS = {
    'FIRE': ((92,27,30),(205,54,27),(253,123,32),(255,208,68),(255,247,194)),
    'WATER': ((22,47,91),(30,109,169),(55,185,232),(145,233,252),(233,255,255)),
    'ELECTRIC': ((92,48,36),(205,119,30),(254,203,42),(255,239,128),(255,255,225)),
    'GRASS': ((30,66,43),(53,127,58),(128,195,59),(207,238,112),(247,255,208)),
    'ICE': ((37,59,108),(71,130,188),(118,207,244),(189,246,255),(247,255,255)),
    'POISON': ((56,31,79),(123,55,160),(193,103,223),(235,171,244),(255,231,254)),
    'GHOST': ((30,21,56),(68,44,119),(141,88,199),(208,141,243),(255,218,251)),
    'PSYCHIC': ((60,31,79),(140,54,157),(235,107,205),(255,179,230),(255,239,255)),
    'FIGHTING': ((83,40,35),(171,70,44),(235,132,67),(255,199,123),(255,244,207)),
    'GROUND': ((63,45,36),(133,83,43),(199,141,74),(236,196,122),(255,236,186)),
    'ROCK': ((49,49,49),(104,89,75),(174,144,102),(225,200,155),(255,239,204)),
    'STEEL': ((38,53,68),(83,111,130),(154,182,195),(211,238,244),(252,255,255)),
    'BUG': ((37,61,30),(92,126,45),(161,195,69),(220,240,123),(249,255,202)),
    'FLYING': ((37,53,79),(92,130,178),(158,204,238),(214,244,254),(251,255,255)),
    'DARK': ((25,26,43),(64,54,99),(131,110,166),(204,173,222),(246,226,252)),
    'DRAGON': ((32,40,80),(70,82,166),(128,153,246),(195,217,255),(243,249,255)),
    'NORMAL': ((85,41,68),(174,84,133),(234,141,183),(255,202,218),(255,243,236)),
}


def settings(config):
    return (max(.7,min(1.3,float(config.get('effect_scale',1.)))),
            max(.5,min(1.,float(config.get('particle_density',1.)))))


def palette(element, config):
    colors = _INKS.get(element, _INKS['NORMAL'])
    if config.get('palette') != 'vivid':
        return colors
    return tuple(tuple(round(max(0,min(255,(v-sum(c)/3)*1.22+sum(c)/3+8)))
                       for v in c) for c in colors)


def cel(side=64):
    image = Image.new('RGBA',(side,side))
    return image, ImageDraw.Draw(image), (side//2,side//2)


def put(layer, image, position, scale=1.):
    if scale <= 0:
        return
    size = (max(1,round(image.width*scale))*PIXEL,
            max(1,round(image.height*scale))*PIXEL)
    scaled = image.resize(size,Image.Resampling.NEAREST)
    layer.alpha_composite(scaled,(round(position[0]-size[0]/2),round(position[1]-size[1]/2)))


def line(layer, points, color, width=3):
    if len(points)<2:
        return
    snapped = [(round(x/PIXEL)*PIXEL,round(y/PIXEL)*PIXEL) for x,y in points]
    ImageDraw.Draw(layer).line(snapped,fill=color,width=max(PIXEL,round(width/PIXEL)*PIXEL),joint='curve')


def point(a,b,p):
    return a[0]+(b[0]-a[0])*p, a[1]+(b[1]-a[1])*p


def burst(layer, position, colors, p, scale=1., density=1., kind='spark',count=12,seed=0):
    """Finite local chips with bright heads; each move chooses its material."""
    if not 0 <= p < 1:
        return
    if not isinstance(seed,(int,float)):
        seed=sum(str(seed).encode())
    draw=ImageDraw.Draw(layer)
    for i in range(max(0,min(24,round(count*density)))):
        life=.76+(i%3)*.08
        if p>=life:
            continue
        angle=i*2.399963+seed*.17
        radius=(15+49*p+(i%3)*7)*scale
        x=round((position[0]+math.cos(angle)*radius)/3)*3
        y=round((position[1]+math.sin(angle)*radius*.8-p*9*scale)/3)*3
        r=max(3,round((5 if i%4==0 else 3)*scale/3)*3)
        if kind=='drop':
            draw.polygon(((x,y-r*2),(x-r,y),(x-r,y+r),(x+r,y+r),(x+r,y)),fill=colors[2])
            draw.rectangle((x,y,x+2,y+2),fill=colors[4])
        elif kind in ('shard','leaf'):
            draw.polygon(((x-r,y+r),(x-r,y),(x+r,y-r*2),(x+r,y+r)),fill=colors[2])
            line(layer,((x-r,y+r),(x+r,y-r)),colors[4],3)
        elif kind=='dust':
            draw.rectangle((x-r,y-r,x+r,y+r),fill=colors[1 if i%2 else 3])
        else:
            tail=(x-math.cos(angle)*r*3,y-math.sin(angle)*r*3)
            line(layer,(tail,(x,y)),colors[1],r)
            draw.rectangle((x-r,y-r,x+r,y+r),fill=colors[3])
            draw.rectangle((x,y-r,x+r,y),fill=colors[4])
