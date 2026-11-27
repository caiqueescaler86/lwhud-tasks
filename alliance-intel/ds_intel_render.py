"""Classic battlefield schematic with named assignments; not an in-game screenshot."""
from functools import lru_cache
from ds_intel import BUILDINGS, TEXT, validate_plan
from ds_fonts import resolve_fonts, load_font, glyph_exists

# Relative arrangement from https://www.lastwartutorial.com/desert-storm/.
# Label positions are deliberately spaced; the illustration is not to scale.
POS = {'L1':(470,120),'L2':(360,330),'L3':(360,550),'L4':(470,760),
       'C1':(1100,265),'C2':(1100,450),'C3':(1100,635),
       'R1':(1730,120),'R2':(1840,330),'R3':(1840,550),'R4':(1730,760)}
ROMAN = {'L2':' I','R3':' II','L3':' I','L4':' III','R1':' IV','R2':' II'}


def render_png(path, match, plan, lang='en'):
    from PIL import Image, ImageDraw, ImageFont
    validate_plan(plan, match)
    t = TEXT[lang]
    paths = resolve_fonts()
    @lru_cache(maxsize=256)
    def font(p, size):
        return load_font(p,size)
    @lru_cache(maxsize=4096)
    def select(ch):
        if ch.isspace(): return paths[0]
        for p in paths:
            f=font(p,24)
            if glyph_exists(f,ch):
                return p
        return paths[0]
    def runs(s):
        out=[]
        for ch in s:
            p=select(ch)
            if out and out[-1][0]==p:out[-1]=(p,out[-1][1]+ch)
            else:out.append((p,ch))
        return out
    def measure(s,size):
        return sum(font(p,size).getlength(v) for p,v in runs(s))
    im=Image.new('RGB',(2200,2640),'#17222b');d=ImageDraw.Draw(im)
    def text(x,y,s,size=26,color='#eff5f8',width=2100):
        s=str(s)
        while measure(s,size)>width and size>16:size-=1
        if measure(s,size)>width:
            while s and measure(s+'…',size)>width:s=s[:-1]
            s+='…'
        baseline=y+size
        for p,v in runs(s):
            f=font(p,size);d.text((x,baseline),v,font=f,fill=color,anchor='ls');x+=f.getlength(v)
    own=match.get('own') or {};enemy=match.get('enemy') or {}
    text(48,20,f"{t['title']} | {t['team']} {match['team']}",48)
    text(48,87,f"{own.get('tag','?')} #{own.get('server_id','?')}  vs  {enemy.get('tag','?')} #{enemy.get('server_id','?')}",31,'#b9dfff')
    text(48,133,t[plan['intel_status']],25,'#ffcc86');text(48,169,t['schematic'],21,'#afc1ca')
    for phase,rows in enumerate(plan['phases']):
        top=222+phase*1080;board=top+70
        text(48,top,f"{t['phase']} {phase+1}   {'00:00–10:00' if phase==0 else '10:00–30:00'}",34)
        d.rounded_rectangle((25,board,2175,board+880),radius=30,fill='#bd935e',outline='#e1c495',width=4)
        outline=[(240,55),(760,20),(1450,20),(1980,55),(2130,270),(2100,610),(1890,820),(1270,860),(640,855),(190,795),(65,560),(70,285)]
        d.polygon([(x,board+y) for x,y in outline],fill='#d5ad73')
        for a in (0,1,2):
            inset=22+a*18
            d.line([(inset+70,board+250+a*25),(inset+190,board+100+a*14),(inset+410,board+56+a*12)],fill='#977345',width=3)
            d.line([(2130-inset,board+600-a*20),(1990-inset,board+750-a*10),(1800-inset,board+790-a*10)],fill='#977345',width=3)
        for a,b in [('L1','C1'),('R1','C1'),('L2','C2'),('R2','C2'),('L3','C2'),('R3','C2'),('L4','C3'),('R4','C3'),('C1','C2'),('C2','C3')]:
            x,y=POS[a];u,v=POS[b];d.line((x,board+y,u,board+v),fill='#ead2a0',width=18)
        for x in (115,2085):
            y=board+440;d.polygon([(x,y-52),(x+66,y),(x,y+52),(x-66,y)],fill='#665b48',outline='#f3dcb6',width=4)
        for key,(kind,rate,opens) in BUILDINGS.items():
            cx,cy=POS[key];cy+=board;x=cx-285;y=cy-75
            locked=opens>phase*10;blocked=key in plan['blocked']
            fill='#5f6059' if locked or blocked else '#233440'
            d.rounded_rectangle((x,y,x+570,y+150),radius=15,fill=fill,outline='#e7bd83' if locked or blocked else '#f0e5c9',width=3)
            text(x+14,y+8,key+'  '+t[kind]+ROMAN.get(key,''),27,'#ffffff',455)
            text(x+480,y+12,f'{rate}/s',23,'#e8d5a6',77)
            if locked or blocked:
                text(x+14,y+57,t['closed'] if locked else t['blocked'],25,'#ffe1aa',542);continue
            caps=[r['name'] for r in rows if r['role']=='capture' and r['target']==key]
            clears=[r['name'] for r in rows if r['role']=='clear' and key in r['target'].split('+')]
            text(x+14,y+52,t['capture']+': '+(', '.join(caps) or '—'),25,'#a9edba',542)
            text(x+14,y+94,t['clear']+': '+(', '.join(clears) or '—'),24,'#ffce8c',542)
        support=', '.join(r['name'] for r in rows if r['role']=='support') or '—'
        text(48,board+894,t['support']+': '+support,28,'#b9dfff')
    d.line((48,2320,2152,2320),fill='#506573',width=2)
    text(48,2335,t['reserve']+':',28,'#b9dfff')
    reserves=[r['name'] for r in plan['reserves']]
    text(48,2375,'  |  '.join(reserves[:5]) or '—',26)
    text(48,2413,'  |  '.join(reserves[5:]),26)
    text(48,2464,t['instruction'],23,'#ffcc86')
    text(48,2508,t['late'],22,'#c9d7de')
    text(48,2570,'Classic layout reference: lastwartutorial.com/desert-storm/',18,'#a6b8c2')
    im.save(path,format='PNG')
