from PIL import Image, ImageDraw, ImageFont

W,H=1600,900
PAPER=(250,249,244); INK=(40,42,54); INK2=(104,106,120); INK3=(150,150,160)
RED=(197,47,42); GREEN=(44,110,78); RULE=(214,212,204); PAPER2=(243,241,233)

SER="/System/Library/Fonts/Supplemental/Georgia.ttf"
SERB="/System/Library/Fonts/Supplemental/Georgia Bold.ttf"
SANS="/System/Library/Fonts/Helvetica.ttc"
MONO="/System/Library/Fonts/Menlo.ttc"
def f(p,s): return ImageFont.truetype(p,s)

def base():
    im=Image.new("RGB",(W,H),PAPER); return im,ImageDraw.Draw(im)
def center(d,y,txt,font,fill,track=0):
    w=d.textlength(txt,font=font); d.text(((W-w)/2,y),txt,font=font,fill=fill)
def kicker(d,y,txt):
    fo=f(MONO,20); s=" ".join(txt.upper()); w=d.textlength(s,font=fo)
    d.text(((W-w)/2,y),s,font=fo,fill=INK3)
def rule(d,y,half=120):
    d.line([(W/2-half,y),(W/2+half,y)],fill=RED,width=3)

def fit(img,maxw,maxh):
    r=min(maxw/img.width,maxh/img.height); return img.resize((int(img.width*r),int(img.height*r)))

def text_frame(kick,lines):  # lines: list of (text,font,fill)
    im,d=base()
    kicker(d,150,kick); rule(d,205)
    total=sum(fs+26 for _,fs,_,_ in lines)
    y=(H-total)/2+40
    for txt,fs,fill,fam in lines:
        fo=f(fam,fs); w=d.textlength(txt,font=fo)
        d.text(((W-w)/2,y),txt,font=fo,fill=fill); y+=fs+26
    return im

def img_frame(kick,title,sub,imgpath):
    im,d=base()
    fo=f(MONO,20); s=" ".join(kick.upper()); d.text((90,70),s,font=fo,fill=INK3)
    d.text((90,108),title,font=f(SERB,40),fill=INK)
    if sub: d.text((90,168),sub,font=f(SANS,24),fill=INK2)
    pic=fit(Image.open(imgpath).convert("RGB"),W-180,560)
    px=(W-pic.width)//2; py=230+(560-pic.height)//2
    d.rectangle([px-2,py-2,px+pic.width+1,py+pic.height+1],outline=RULE,width=2)
    im.paste(pic,(px,py))
    return im

frames=[]
# 1 title
t=text_frame("Appropriations Data Pipeline",[
    ("Reading the Unreadable",84,INK,SERB),
    ("Verified extraction of House appropriations tables",30,INK2,SER),
    ("H. Rept. 118-553  ·  Homeland Security  ·  FY2025",24,INK3,MONO),
]); frames+=[(t,3200)]
# 2 problem
frames+=[(img_frame("01 · The problem","The numbers arrive as a picture.",
    "Comparative statements are scanned images. No text layer to copy.","demo/assets/voteroster.png"),3000)]
# 3 extraction
t=text_frame("02 · Extraction",[
    ("Vision model reads each page into structure",34,INK,SER),
    ("926",96,INK,MONO),("line items  ·  63 image pages  ·  0 page failures",26,INK2,SANS),
]); frames+=[(t,3000)]
# 4 TSA gross/net
frames+=[(img_frame("03 · First check","Gross versus net, reconciled.",
    "net 6,800,287  +  offsetting 3,770,000  =  gross 10,570,287","demo/assets/tsa.png"),3400)]
# 5 the catch
frames+=[(img_frame("06 · The catch","It found the one real error.",
    "Vision read 20,836.  The table says 20,636.","demo/assets/nep_tight.png"),3400)]
# 6 delta arithmetic
t=text_frame("05 · Verification",[
    ("Every row checks itself",40,INK,SER),
    ("recommended  -  enacted  =  delta",30,INK2,MONO),
    ("436 / 436",92,GREEN,MONO),("value-bearing comparative rows pass",26,INK2,SANS),
]); frames+=[(t,3200)]
# 7 bottom line
t=text_frame("Bottom line",[
    ("Two independent checks. Both clean.",40,INK,SER),
    ("46/52  external      436/436  internal",30,INK,MONO),
    ("The hard part works, and it is verified.",30,GREEN,SER),
]); frames+=[(t,3800)]

imgs=[fr for fr,_ in frames]; durs=[d for _,d in frames]
imgs[0].save("demo/demo.gif",save_all=True,append_images=imgs[1:],duration=durs,loop=0,optimize=True)
import os; print("demo.gif %.2f MB, %d frames"%(os.path.getsize("demo/demo.gif")/1e6,len(imgs)))
