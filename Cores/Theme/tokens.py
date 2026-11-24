import os,json,re
from Cores import settings_lock as _settings_lock
from Cores.Theme import palettes as _palettes
def _root(*p):return os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)),"..","..",*p))
CSS_PATH=_root("UI","css","theme.css")
JSON_PATH=_root("UI","js","theme-tokens.json")
# Generated at startup and on every style change; main.html/mini.html load it synchronously in <head> so the saved style is on <html>
# before the first paint (no flash). If it cannot be written (read-only install) the HTML default plus the bridge call still apply it.
BOOT_JS_PATH=_root("UI","js","appearance-boot.js")
SETTINGS_PATH=_root("Data","settings.json")
MODES=("dark","light","royal","system")
GLASS={
    "dark":{"bg":"#05060a","bg-blob-a":"#3b82f688","bg-blob-b":"#a855f788","text":"#eaf6ff","text-dim":"#9fb3c8","glass-bg":"rgba(255,255,255,0.06)","glass-border":"rgba(255,255,255,0.14)","glass-blur":"22px","glass-shadow":"0 12px 40px rgba(0,0,0,0.5)","accent-a":"#3b82f6","accent-b":"#a855f7","accent-a-soft":"rgba(59,130,246,0.20)","accent-b-soft":"rgba(168,85,247,0.20)","radius":"18px","danger":"#ef4444"},
    "light":{"bg":"#e8edf6","bg-blob-a":"#3b82f655","bg-blob-b":"#a855f755","text":"#12172a","text-dim":"#4f596a","glass-bg":"rgba(255,255,255,0.66)","glass-border":"rgba(28,45,80,0.16)","glass-blur":"22px","glass-shadow":"0 1px 2px rgba(20,30,60,0.06),0 10px 32px -8px rgba(20,30,60,0.18)","accent-a":"#3b82f6","accent-b":"#a855f7","accent-a-soft":"rgba(59,130,246,0.15)","accent-b-soft":"rgba(168,85,247,0.15)","radius":"18px","danger":"#dc2626"},
    "royal":{"bg":"#0a0805","bg-blob-a":"#d4af3788","bg-blob-b":"#c0c0c088","text":"#f7f1e3","text-dim":"#b8ac8e","glass-bg":"rgba(255,223,158,0.05)","glass-border":"rgba(255,223,158,0.14)","glass-blur":"22px","glass-shadow":"0 12px 40px rgba(0,0,0,0.55)","accent-a":"#d4af37","accent-b":"#c0c0c0","accent-a-soft":"rgba(212,175,55,0.20)","accent-b-soft":"rgba(192,192,192,0.20)","radius":"18px","danger":"#ef4444"},
}
def _read_settings():
    try:
        with open(SETTINGS_PATH,"r",encoding="utf-8") as f:
            d=json.load(f)
        return d if isinstance(d,dict) else {}
    except Exception:
        return {}
def _write_settings(d):
    with _settings_lock.SETTINGS_LOCK:_settings_lock.write_json(SETTINGS_PATH,d)
def current_mode():
    d=_read_settings()
    appearance=d.get("appearance",{}) if isinstance(d.get("appearance"),dict) else {}
    mode=str(appearance.get("mode","") or appearance.get("theme","") or "").strip().lower()
    return mode if mode in MODES else _palettes.DEFAULT_THEME
def current_theme():
    mode=current_mode()
    return mode if mode in _palettes.PALETTES else _palettes.DEFAULT_THEME
@_settings_lock.serialized
def set_mode(mode):
    mode=str(mode or "").strip().lower()
    if mode not in MODES:return False
    d=_read_settings()
    appearance=d.get("appearance",{}) if isinstance(d.get("appearance"),dict) else {}
    appearance["mode"]=mode
    appearance["theme"]=mode if mode in _palettes.PALETTES else _palettes.DEFAULT_THEME
    d["appearance"]=appearance
    _write_settings(d)
    return True
# Appearance style is independent of the colour theme: "glass" (liquid-glass edges, the default) or "classic" (the original look).
STYLES=("glass","classic")
DEFAULT_STYLE="glass"
def current_style():
    d=_read_settings()
    appearance=d.get("appearance",{}) if isinstance(d.get("appearance"),dict) else {}
    style=str(appearance.get("style","") or "").strip().lower()
    return style if style in STYLES else DEFAULT_STYLE
def set_style(style):
    style=str(style or "").strip().lower()
    if style not in STYLES:return False
    from Cores import settings_lock as _settings_lock
    def mutate(d):
        appearance=d.get("appearance") if isinstance(d.get("appearance"),dict) else {}
        appearance["style"]=style
        d["appearance"]=appearance
    ok=bool(_settings_lock.update_json(SETTINGS_PATH,mutate))
    if ok:write_boot()
    return ok
def render_boot_js(style=None):
    style=style if style in STYLES else current_style()
    return f'document.documentElement.setAttribute("data-style","{style}");\n'
def write_boot():
    try:
        with open(BOOT_JS_PATH,"w",encoding="utf-8",newline="\n") as f:f.write(render_boot_js())
        return True
    except Exception:return False
ACCENT_PRESETS=[
    {"name":"Blue / Purple","a":"#3b82f6","b":"#a855f7"},
    {"name":"Teal / Cyan","a":"#14b8a6","b":"#06b6d4"},
    {"name":"Rose / Pink","a":"#f43f5e","b":"#ec4899"},
    {"name":"Amber / Orange","a":"#f59e0b","b":"#f97316"},
    {"name":"Green / Lime","a":"#22c55e","b":"#84cc16"},
    {"name":"Indigo / Violet","a":"#6366f1","b":"#8b5cf6"},
]
_HEX_RX=re.compile(r"^#[0-9a-fA-F]{6}$")
def current_accent():
    d=_read_settings()
    appearance=d.get("appearance",{}) if isinstance(d.get("appearance"),dict) else {}
    a=str(appearance.get("accent_a","") or "").strip()
    b=str(appearance.get("accent_b","") or "").strip()
    if not _HEX_RX.match(a):a=ACCENT_PRESETS[0]["a"]
    if not _HEX_RX.match(b):b=ACCENT_PRESETS[0]["b"]
    return a,b
@_settings_lock.serialized
def set_accent(a,b):
    a=str(a or "").strip();b=str(b or "").strip()
    if not _HEX_RX.match(a) or not _HEX_RX.match(b):return False
    d=_read_settings()
    appearance=d.get("appearance",{}) if isinstance(d.get("appearance"),dict) else {}
    appearance["accent_a"]=a
    appearance["accent_b"]=b
    d["appearance"]=appearance
    _write_settings(d)
    return True
ANSI_NAMES=("black","red","green","yellow","blue","magenta","cyan","white","brblack","brred","brgreen","bryellow","brblue","brmagenta","brcyan","brwhite")
ANSI={
    "dark":("#6b7280","#f87171","#4ade80","#facc15","#60a5fa","#e879f9","#22d3ee","#e5e7eb","#9ca3af","#fca5a5","#86efac","#fde047","#93c5fd","#f0abfc","#67e8f9","#f9fafb"),
    "light":("#4b5563","#dc2626","#15803d","#a16207","#1d4ed8","#a21caf","#0e7490","#374151","#6b7280","#ef4444","#16a34a","#ca8a04","#2563eb","#c026d3","#0891b2","#111827"),
    "royal":("#7c7259","#e06c6c","#b8c07a","#d4af37","#9aa8c0","#c9a0c9","#8fc0c8","#f7f1e3","#a89878","#f0a0a0","#d4dc9a","#f0d878","#bcc8e0","#e0c0e0","#b8dce4","#fffaf0"),
}
ANSI_BG_ALPHA="0.35"
def _hex_to_rgb(value):
    v=value.lstrip("#")
    return tuple(int(v[i:i+2],16) for i in (0,2,4))
def _ansi_rules(selector,theme):
    palette=ANSI.get(theme,ANSI["dark"])
    body=""
    for name,color in zip(ANSI_NAMES,palette):
        body+=f"--ansi-{name}:{color};"
        r,g,b=_hex_to_rgb(color)
        body+=f"--ansi-bg-{name}:rgba({r},{g},{b},{ANSI_BG_ALPHA});"
    return f"{selector}{{{body}}}"
def _rules(selector,pal,glass):
    body="".join(f"--pal-{k}:{v};" for k,v in pal.items())
    body+="".join(f"--{k}:{v};" for k,v in glass.items())
    return f"{selector}{{{body}}}"
def render_css():
    dark=_rules(":root",_palettes.DARK,GLASS["dark"])+"\n"+_ansi_rules(":root","dark")
    light=_rules('[data-theme="light"]',_palettes.LIGHT,GLASS["light"])+"\n"+_ansi_rules('[data-theme="light"]',"light")
    royal=_rules('[data-theme="royal"]',_palettes.ROYAL,GLASS["royal"])+"\n"+_ansi_rules('[data-theme="royal"]',"royal")
    return dark+"\n"+light+"\n"+royal+"\n"
def _ansi_tokens(theme):
    palette=ANSI.get(theme,ANSI["dark"])
    return {f"ansi-{name}":color for name,color in zip(ANSI_NAMES,palette)}
def render_json():
    return {"dark":{**_palettes.DARK,**GLASS["dark"],**_ansi_tokens("dark")},"light":{**_palettes.LIGHT,**GLASS["light"],**_ansi_tokens("light")},"royal":{**_palettes.ROYAL,**GLASS["royal"],**_ansi_tokens("royal")}}
def write():
    os.makedirs(os.path.dirname(CSS_PATH),exist_ok=True)
    with open(CSS_PATH,"w",encoding="utf-8") as f:f.write(render_css())
    os.makedirs(os.path.dirname(JSON_PATH),exist_ok=True)
    with open(JSON_PATH,"w",encoding="utf-8") as f:json.dump(render_json(),f,ensure_ascii=False,indent=2)
    write_boot()
if __name__=="__main__":
    write()
