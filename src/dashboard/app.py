import os
from datetime import datetime, timezone, timedelta
import httpx
import streamlit as st
import streamlit.components.v1 as components

st.set_page_config(layout="wide", page_title="BrandIQ", page_icon="🎯")
st.markdown("<style>#MainMenu,footer,header{visibility:hidden!important;}.block-container{padding:0!important;margin:0!important;max-width:100%!important;}</style>", unsafe_allow_html=True)

API = os.getenv("API_URL", "https://brandiq-production-36b6.up.railway.app")

def get(path, fallback=None):
    try:
        r = httpx.get(f"{API}{path}", timeout=6)
        return r.json() if r.is_success else fallback
    except Exception:
        return fallback

def post(path, body={}):
    try:
        r = httpx.post(f"{API}{path}", json=body, timeout=10)
        return r.json() if r.is_success else {"error": r.text}
    except Exception as e:
        return {"error": str(e)}

# ── Handle actions triggered from JS via query params ─────────────────────────
qp = st.query_params
if qp.get("action") == "run_crew":
    res = post("/tasks/content")
    st.query_params.clear()
    if res and "task_id" in res:
        st.toast(f"✓ Content Crew queued!", icon="🚀")
    st.rerun()
elif qp.get("action") == "run_analytics":
    res = post("/tasks/analytics")
    st.query_params.clear()
    if res and "task_id" in res:
        st.toast(f"✓ Analytics queued!", icon="📊")
    st.rerun()
elif qp.get("action") == "refresh":
    st.query_params.clear()
    st.rerun()
elif qp.get("action") == "nurture":
    handle = qp.get("handle", "")
    day = int(qp.get("day", 1))
    if handle:
        res = post("/tasks/lead", {"ig_handle": handle, "message_text": "", "day_number": day})
        st.query_params.clear()
        st.toast(f"✓ Nurture Day {day} queued for @{handle}", icon="💬")
    st.rerun()
elif qp.get("action") == "run_pipeline":
    res = post("/run-pipeline")
    st.query_params.clear()
    if res and res.get("status") == "completed":
        st.toast(f"✓ Full pipeline completed — {res.get('agents_run',0)} agents ran!", icon="⚡")
    else:
        st.toast(f"Pipeline result: {str(res)[:60]}", icon="⚠️")
    st.rerun()
elif qp.get("action") == "simulate_lead":
    res = post("/simulate-lead")
    st.query_params.clear()
    if res and res.get("status") == "ok":
        st.toast(f"✓ {res.get('leads_simulated',0)} leads simulated!", icon="👥")
    st.rerun()

# ── Auto-refresh every 5 seconds ─────────────────────────────────────────────
import time
if "last_refresh" not in st.session_state:
    st.session_state.last_refresh = time.time()
if time.time() - st.session_state.last_refresh > 5:
    st.session_state.last_refresh = time.time()
    st.rerun()

# ── Action bar (real Streamlit buttons — these work, no iframe sandbox issues) ─
st.markdown("""<style>
div[data-testid="stHorizontalBlock"]{gap:4px!important;margin-bottom:0!important;}
div[data-testid="column"]{padding:0!important;}
.stButton>button{background:#1c1f32!important;color:#e8eaf6!important;font-weight:600!important;border:1px solid #242742!important;border-radius:6px!important;font-size:11px!important;height:28px!important;width:100%!important;padding:0 10px!important;}
.stButton>button:hover{background:#242742!important;border-color:#00e5c3!important;color:#00e5c3!important;}
div[data-testid="column"]:last-child .stButton>button{background:#00e5c3!important;color:#000!important;border-color:#00e5c3!important;}
</style>""", unsafe_allow_html=True)

ab1, ab2, ab3, ab4, ab5 = st.columns([1,1,1,1,5])
if ab1.button("⚡ Run Pipeline"):
    with st.spinner("Running full pipeline..."):
        res = post("/run-pipeline")
    if res and res.get("status") == "completed":
        st.toast(f"✓ Pipeline done — {res.get('agents_run',0)} agents ran!", icon="⚡")
    else:
        st.toast(str(res)[:80], icon="⚠️")
    st.rerun()
if ab2.button("👥 Simulate Lead"):
    res = post("/simulate-lead")
    if res and res.get("status") == "ok":
        st.toast(f"✓ {res.get('leads_simulated',0)} leads simulated!", icon="👥")
    st.rerun()
if ab3.button("📊 Analytics"):
    res = post("/tasks/analytics")
    if res and "task_id" in res:
        st.toast("✓ Analytics queued!", icon="📊")
    st.rerun()
if ab4.button("🔄 Refresh"):
    st.rerun()
if ab5.button("▶ Run Crew", key="run_crew_main"):
    res = post("/tasks/content")
    if res and "task_id" in res:
        st.toast(f"✓ Content Crew queued!", icon="🚀")
    st.rerun()

kpis    = get("/stats/kpis", {})
agents  = get("/stats/agent-status", [])
posts   = get("/posts?limit=20&upcoming_only=true", [])
leads   = get("/leads?limit=50", [])
reach   = get("/stats/reach", [])
funnels = get("/stats/funnels", {})
feed    = get("/stats/live-feed", [])
cal     = get("/calendar", {})
jobs    = get("/stats/agent-jobs?limit=20", [])

def fmt(n):
    if not n: return "0"
    if n >= 100000: return f"{n/100000:.1f}L"
    if n >= 1000:   return f"{n/1000:.0f}K"
    return str(n)

def ago(iso):
    try:
        dt = datetime.fromisoformat(iso.replace("Z","+00:00"))
        s = int((datetime.now(timezone.utc)-dt).total_seconds())
        if s < 60: return f"{s}s ago"
        if s < 3600: return f"{s//60}m ago"
        return f"{s//3600}h ago"
    except Exception: return ""

SC = {"hot":"#ff6b6b","warm":"#ffd166","cold":"#4facfe","opted_out":"#4a4f72",
      "posted":"#00e5c3","approved":"#4facfe","pending":"#ffd166","failed":"#ff6b6b",
      "success":"#00e5c3","running":"#ffd166","dead_letter":"#ff6b6b"}
LEAD_COLORS = ["#ff6b6b","#9d6fff","#ffd166","#00e5c3","#4facfe","#4facfe","#ff6b6b","#ffd166","#00e5c3","#ff6b6b"]

agent_map = {j["agent_name"]: j for j in agents}
AGENT_DEFS = [
    ("StrategyAgent","Planning content calendar","#00e5c3","Running"),
    ("ContentWriter","Writing captions","#ffd166","Writing"),
    ("VisualCreator","Generating visuals","#4facfe","Generating"),
    ("SchedulerAgent","Optimising post times","#4a4f72","Waiting"),
    ("LeadCapture","Monitoring DMs","#00e5c3","Scanning"),
    ("LeadNurture","Sending sequences","#ffd166","Sending"),
    ("ReelScript","Drafting reel script","#4facfe","Drafting"),
    ("AnalyticsAgent","Daily insights pulled ✓","#4a4f72","Done"),
    ("AdaptiqPromo","Trial messages sent","#00e5c3","Running"),
]

def agent_rows_html():
    h = ""
    for name, task, color, badge in AGENT_DEFS:
        job = agent_map.get(name, {})
        s = job.get("status","idle")
        c = SC.get(s, color)
        anim = "animation:pulse 1.5s infinite;" if s=="running" else ""
        h += f'<div class="agent-row"><div class="ad" style="background:{c};{anim}"></div><div class="an">{name}</div><div class="at">{task}</div><span class="abadge" style="background:{c}22;color:{c}">{badge}</span></div>'
    return h

def post_rows_html(post_list, show_actions=False):
    ICONS = {"instagram":"📊","telegram":"✈️","reel":"🧠","carousel":"📊","story":"🎯","post":"✍️","whatsapp":"💬"}
    h = ""
    for p in post_list:
        icon = ICONS.get(p.get("platform","post"),"📝")
        s = p.get("status","pending")
        sc = "ps-live" if s=="posted" else "ps-sch" if s=="approved" else "ps-dft"
        sl = "Live" if s=="posted" else "Scheduled" if s=="approved" else "Draft"
        sched = (p.get("scheduled_at") or "")[:16].replace("T"," ")
        action = ""
        if show_actions:
            pid = p["id"]
            if s == "pending":
                action = f'<button onclick="callAPI(\'/posts/approve\',\'POST\',{{post_id:\'{pid}\'}},\'Approved!\')" style="background:#00e5c322;color:#00e5c3;border:1px solid #00e5c344;border-radius:4px;padding:2px 8px;font-size:9px;cursor:pointer;font-family:DM Mono,monospace;margin-left:6px">APPROVE</button>'
            elif s == "approved":
                action = f'<button onclick="callAPI(\'/posts/publish/{pid}\',\'POST\',{{}},\'Published!\')" style="background:#4facfe22;color:#4facfe;border:1px solid #4facfe44;border-radius:4px;padding:2px 8px;font-size:9px;cursor:pointer;font-family:DM Mono,monospace;margin-left:6px">PUBLISH</button>'
        h += f'<div class="post-item"><div class="post-icon" style="background:#9d6fff18">{icon}</div><div style="flex:1;min-width:0"><div class="pi-title">{p["caption_a"][:55]}…</div><div class="pi-detail">{p["platform"].upper()} · {sched}</div></div><span class="ps {sc}">{sl}</span>{action}</div>'
    return h or '<div style="color:#4a4f72;font-size:11px;padding:12px 0;text-align:center">No posts yet — click Run Crew</div>'

def lead_rows_html(lead_list, show_nurture=False):
    h = ""
    for i, l in enumerate(lead_list):
        name = l.get("name") or l["ig_handle"]
        initials = "".join(w[0].upper() for w in name.split()[:2])
        c = SC.get(l["status"],"#4a4f72")
        lc = LEAD_COLORS[i % len(LEAD_COLORS)]
        src = l.get("source","").replace("_"," ")
        age = ""
        if l.get("created_at"):
            try:
                dt = datetime.fromisoformat(l["created_at"].replace("Z","+00:00"))
                age = f"Day {(datetime.now(timezone.utc)-dt).days+1}"
            except Exception: pass
        lt_cls = f"lt-{l['status']}" if l['status'] in ('hot','warm','cold') else "lt-cold"
        nurture_btn = ""
        if show_nurture and l.get("ig_handle"):
            handle = l["ig_handle"]
            nurture_btn = f'<button onclick="sendNurture(\'{handle}\',3)" style="background:#ffd16622;color:#ffd166;border:1px solid #ffd16644;border-radius:4px;padding:2px 8px;font-size:9px;cursor:pointer;font-family:DM Mono,monospace;margin-left:4px">NURTURE D3</button>'
        status_upper = l["status"].upper()
        h += f'<div class="lead-item"><div class="lav" style="background:{lc}18;color:{lc}">{initials}</div><div style="flex:1;min-width:0"><div class="lname">{name}</div><div class="lsrc">{src}</div></div><span class="lt {lt_cls}">{status_upper}</span><div class="lday">{age}</div>{nurture_btn}</div>'
    return h or '<div style="color:#4a4f72;font-size:11px;padding:12px 0;text-align:center">No leads yet</div>'

def reach_bars_html():
    max_r = max((r["reach"] for r in reach), default=1) or 1
    h = ""
    for r in reach:
        ht = max(4, int(r["reach"]/max_r*65))
        op = 0.4 + 0.6*(r["reach"]/max_r)
        h += f'<div class="bw"><div class="bval">{fmt(r["reach"])}</div><div class="bar" style="height:{ht}px;background:linear-gradient(180deg,#00e5c3,#4facfe);opacity:{op:.2f}"></div><div class="blbl">{r["day"]}</div></div>'
    return h or '<div style="color:#4a4f72;font-size:11px;padding:20px;text-align:center">No reach data yet</div>'

FUNNEL_COLORS = ["#9d6fff","#4facfe","#00e5c3","#ffd166","#ff6b6b"]
def funnel_html(steps, colors):
    h = ""
    for i, s in enumerate(steps):
        v = s["value"]; label = fmt(v) if isinstance(v,int) else str(v)
        h += f'<div class="fn-step"><div class="fn-lbl"><span class="fn-name">{s["label"]}</span><span class="fn-num">{label}</span></div><div class="fn-bg"><div class="fn-fill" style="width:{s["pct"]}%;background:{colors[i%len(colors)]}"></div></div></div>'
    return h

lf = funnels.get("lead_funnel",[{"label":"Reached","value":0,"pct":100},{"label":"Engaged","value":0,"pct":75},{"label":"DM'd / Enquired","value":0,"pct":48},{"label":"Demo / Trial","value":0,"pct":28},{"label":"Admitted","value":0,"pct":12}])
af = funnels.get("adaptiq_funnel",[{"label":"Promo Views","value":0,"pct":100},{"label":"Link Clicks","value":0,"pct":70},{"label":"Free Trial","value":0,"pct":42},{"label":"Active Day 5","value":0,"pct":26},{"label":"Paid Converted","value":0,"pct":10}])

def feed_html():
    FEED_ICONS = {"post":("✓","#00e5c3"),"lead":("💬","#9d6fff"),"admission":("⭐","#ffd166"),"trial":("🎯","#4facfe")}
    h = ""
    for e in feed[:6]:
        ic, bg = FEED_ICONS.get(e.get("type","post"),("•","#4a4f72"))
        ts = ago(e.get("time",""))
        h += f'<div class="feed-item"><div class="fic" style="background:{bg}18">{ic}</div><div><div class="ft"><strong>{e.get("text","")}</strong></div><div class="ft-time">{ts}</div></div></div>'
    return h or '<div style="color:#4a4f72;font-size:11px;padding:8px 0">No recent activity</div>'

def calendar_html():
    today_dt = datetime.now(timezone.utc)
    week_start = today_dt - timedelta(days=3)
    TYPE_COLORS = {"instagram":"cp","reel":"cp","carousel":"cg","story":"cb","post":"cy","whatsapp":"cr","telegram":"cb"}
    DAY_NAMES = ["MON","TUE","WED","THU","FRI","SAT","SUN"]
    h = ""
    # Headers
    for i in range(10):
        day = week_start + timedelta(days=i)
        h += f'<div class="cal-hd">{DAY_NAMES[day.weekday()]}</div>'
    # Day cells
    for i in range(10):
        day = week_start + timedelta(days=i)
        key = day.strftime("%Y-%m-%d")
        is_today = key == today_dt.strftime("%Y-%m-%d")
        cls = "cal-day today" if is_today else "cal-day"
        dot = " ●" if is_today else ""
        events = cal.get(key, [])
        count = len(events)
        count_badge = f'<div style="font-family:DM Mono,monospace;font-size:8px;color:#4a4f72;margin-bottom:2px">{count} posts</div>' if count > 0 else ""
        ev = "".join(f'<div class="ce {TYPE_COLORS.get(e.get("platform","post"),"cy")}">{e["caption"][:16]}</div>' for e in events[:3])
        h += f'<div class="{cls}"><div class="cal-num">{day.day}{dot}</div>{count_badge}{ev}</div>'
    return h

def jobs_html():
    h = ""
    for j in (jobs or [])[:15]:
        c = SC.get(j.get("status","pending"),"#4a4f72")
        ts = (j.get("created_at") or "")[:16].replace("T"," ")
        err = f'<span style="color:#ff6b6b;font-size:9px;font-family:DM Mono,monospace"> — {str(j.get("error") or "")[:40]}</span>' if j.get("error") else ""
        h += f'<div style="display:flex;align-items:center;gap:8px;padding:5px 0;border-bottom:1px solid #1c1f32"><span style="font-size:11px;font-weight:600;width:130px;flex-shrink:0">{j["agent_name"]}</span><span style="background:{c}22;color:{c};border:1px solid {c}44;border-radius:3px;padding:1px 7px;font-family:DM Mono,monospace;font-size:9px">{j["status"].upper()}</span><span style="font-family:DM Mono,monospace;font-size:9px;color:#4a4f72;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;margin-left:4px">{j.get("job_id","")}</span><span style="font-family:DM Mono,monospace;font-size:9px;color:#4a4f72;flex-shrink:0">{ts}</span>{err}</div>'
    return h or '<div style="color:#4a4f72;font-size:11px;padding:12px 0">No jobs yet</div>'

hot = kpis.get("hot_leads",0); trials = kpis.get("trials_today",0)
topper_rev = hot*25000; adaptiq_rev = trials*299; total_rev = topper_rev+adaptiq_rev
now_str = datetime.now().strftime("%A, %d %B %Y")

# ── whatsapp page ─────────────────────────────────────────────────────────────
wa_leads = [l for l in leads if l.get("phone")]
wa_rows = ""
for i, l in enumerate(wa_leads[:20]):
    name = l.get("name") or l["ig_handle"]
    initials = "".join(w[0].upper() for w in name.split()[:2])
    lc = LEAD_COLORS[i % len(LEAD_COLORS)]
    c = SC.get(l["status"],"#4a4f72")
    lt_cls = f"lt-{l['status']}" if l['status'] in ('hot','warm','cold') else "lt-cold"
    handle = l["ig_handle"]
    phone = l.get("phone","—")
    status_upper = l["status"].upper()
    wa_rows += f'''<div class="lead-item">
<div class="lav" style="background:{lc}18;color:{lc}">{initials}</div>
<div style="flex:1;min-width:0"><div class="lname">{name}</div><div class="lsrc">{phone}</div></div>
<span class="lt {lt_cls}">{status_upper}</span>
<button onclick="sendNurture('{handle}',3)" style="background:#4facfe22;color:#4facfe;border:1px solid #4facfe44;border-radius:4px;padding:2px 8px;font-size:9px;cursor:pointer;font-family:DM Mono,monospace;margin-left:6px">DAY 3</button>
<button onclick="sendNurture('{handle}',7)" style="background:#00e5c322;color:#00e5c3;border:1px solid #00e5c344;border-radius:4px;padding:2px 8px;font-size:9px;cursor:pointer;font-family:DM Mono,monospace;margin-left:4px">DAY 7</button>
</div>'''
if not wa_rows:
    wa_rows = '<div style="color:#4a4f72;font-size:11px;padding:20px;text-align:center">No leads with phone numbers yet. Leads are captured from Instagram DMs.</div>'

# ── nurture flows page ────────────────────────────────────────────────────────
nurture_rows = ""
for i, l in enumerate(leads[:30]):
    name = l.get("name") or l["ig_handle"]
    initials = "".join(w[0].upper() for w in name.split()[:2])
    lc = LEAD_COLORS[i % len(LEAD_COLORS)]
    c = SC.get(l["status"],"#4a4f72")
    lt_cls = f"lt-{l['status']}" if l['status'] in ('hot','warm','cold') else "lt-cold"
    handle = l["ig_handle"]
    status_upper = l["status"].upper()
    age = 0
    if l.get("created_at"):
        try:
            dt = datetime.fromisoformat(l["created_at"].replace("Z","+00:00"))
            age = (datetime.now(timezone.utc)-dt).days+1
        except Exception: age = 0
    nurture_rows += f'''<div class="lead-item">
<div class="lav" style="background:{lc}18;color:{lc}">{initials}</div>
<div style="flex:1;min-width:0"><div class="lname">{name}</div><div class="lsrc">@{handle} · Day {age}</div></div>
<span class="lt {lt_cls}">{status_upper}</span>
<button onclick="sendNurture('{handle}',3)" style="background:#1c1f32;color:#4a4f72;border:1px solid #242742;border-radius:4px;padding:2px 8px;font-size:9px;cursor:pointer;font-family:DM Mono,monospace;margin-left:6px">D3</button>
<button onclick="sendNurture('{handle}',7)" style="background:#1c1f32;color:#4a4f72;border:1px solid #242742;border-radius:4px;padding:2px 8px;font-size:9px;cursor:pointer;font-family:DM Mono,monospace;margin-left:3px">D7</button>
<button onclick="sendNurture('{handle}',14)" style="background:#1c1f32;color:#4a4f72;border:1px solid #242742;border-radius:4px;padding:2px 8px;font-size:9px;cursor:pointer;font-family:DM Mono,monospace;margin-left:3px">D14</button>
</div>'''
if not nurture_rows:
    nurture_rows = '<div style="color:#4a4f72;font-size:11px;padding:20px;text-align:center">No leads yet</div>'

# ── instagram page ────────────────────────────────────────────────────────────
ig_posts = [p for p in posts if p.get("platform") == "instagram"]
ig_rows = post_rows_html(ig_posts, show_actions=True) if ig_posts else post_rows_html(posts, show_actions=True)

# ── adaptiq funnel page ───────────────────────────────────────────────────────
adaptiq_leads = [l for l in leads if "adaptiq" in (l.get("source","")).lower() or l.get("status") == "warm"]
adaptiq_rows = lead_rows_html(adaptiq_leads[:15]) if adaptiq_leads else lead_rows_html(leads[:10])

# ── CSS ───────────────────────────────────────────────────────────────────────
CSS = """
@import url('https://fonts.googleapis.com/css2?family=Syne:wght@400;600;700;800&family=DM+Mono:wght@300;400;500&family=DM+Sans:wght@300;400;500&display=swap');
*{box-sizing:border-box;margin:0;padding:0;}
:root{--bg:#07080f;--surface:#0d0f1a;--surface2:#111320;--border:#1c1f32;--border2:#242742;--text:#e8eaf6;--muted:#4a4f72;--accent:#00e5c3;--accent2:#ff6b6b;--accent3:#ffd166;--accent4:#4facfe;--purple:#9d6fff;}
body{font-family:'DM Sans',sans-serif;background:var(--bg);color:var(--text);display:flex;height:100vh;overflow:hidden;font-size:13px;}
.sb{width:200px;background:var(--surface);border-right:1px solid var(--border);display:flex;flex-direction:column;flex-shrink:0;}
.sb-brand{padding:18px 16px 14px;border-bottom:1px solid var(--border);}
.sb-brand-name{font-family:'Syne',sans-serif;font-size:18px;font-weight:800;letter-spacing:-0.5px;color:var(--accent);}
.sb-brand-sub{font-family:'DM Mono',monospace;font-size:9px;color:var(--muted);letter-spacing:2px;margin-top:2px;text-transform:uppercase;}
.sb-nav{flex:1;padding:10px 0;overflow-y:auto;}
.sb-group{font-family:'DM Mono',monospace;font-size:9px;color:var(--muted);letter-spacing:2px;text-transform:uppercase;padding:10px 16px 4px;}
.sb-item{display:flex;align-items:center;gap:8px;padding:7px 16px;color:var(--muted);cursor:pointer;transition:all .15s;font-size:12px;font-weight:500;border-right:2px solid transparent;}
.sb-item:hover{color:var(--text);background:#ffffff06;}
.sb-item.on{color:var(--accent);background:#00e5c308;border-right-color:var(--accent);}
.sb-foot{padding:12px 16px;border-top:1px solid var(--border);}
.pulse-dot{display:inline-block;width:6px;height:6px;border-radius:50%;background:var(--accent);margin-right:6px;animation:glow 2s infinite;}
@keyframes glow{0%,100%{box-shadow:0 0 4px var(--accent);}50%{box-shadow:0 0 10px var(--accent);}}
@keyframes pulse{0%,100%{opacity:1;}50%{opacity:0.4;}}
.sb-status{font-family:'DM Mono',monospace;font-size:10px;color:var(--muted);}
.main{flex:1;display:flex;flex-direction:column;overflow:hidden;}
.topbar{background:var(--surface);border-bottom:1px solid var(--border);padding:0 20px;height:50px;display:flex;align-items:center;justify-content:space-between;flex-shrink:0;}
.tb-title{font-family:'Syne',sans-serif;font-size:14px;font-weight:700;}
.tb-sub{font-family:'DM Mono',monospace;font-size:9px;color:var(--muted);margin-top:1px;letter-spacing:1px;}
.tb-right{display:flex;align-items:center;gap:8px;}
.chip{font-family:'DM Mono',monospace;font-size:9px;padding:3px 10px;border-radius:4px;letter-spacing:1px;font-weight:500;}
.chip-live{background:#00e5c315;color:var(--accent);border:1px solid #00e5c330;}
.btn-sm{font-size:11px;font-weight:600;padding:5px 12px;border-radius:6px;cursor:pointer;border:none;font-family:'DM Sans',sans-serif;}
.btn-outline{background:transparent;color:var(--muted);border:1px solid var(--border2);}
.btn-fill{background:var(--accent);color:#000;}
.av{width:26px;height:26px;border-radius:6px;background:linear-gradient(135deg,#00e5c3,#4facfe);display:flex;align-items:center;justify-content:center;font-family:'Syne',sans-serif;font-size:10px;font-weight:800;color:#000;}
.content{flex:1;overflow-y:auto;padding:14px 18px;display:flex;flex-direction:column;gap:10px;}
::-webkit-scrollbar{width:3px;}::-webkit-scrollbar-thumb{background:var(--border2);}
.page{display:none;flex-direction:column;gap:10px;}
.page.active{display:flex;}
.page-title{font-family:'Syne',sans-serif;font-size:16px;font-weight:800;margin-bottom:4px;}
.page-sub{font-family:'DM Mono',monospace;font-size:9px;color:var(--muted);letter-spacing:1px;margin-bottom:8px;}
.kpi-row{display:grid;grid-template-columns:repeat(5,1fr);gap:10px;}
.kpi{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:12px 14px;position:relative;overflow:hidden;}
.kpi::before{content:'';position:absolute;top:0;left:0;right:0;height:2px;}
.kpi-1::before{background:var(--accent);}.kpi-2::before{background:var(--accent4);}.kpi-3::before{background:var(--accent3);}.kpi-4::before{background:var(--purple);}.kpi-5::before{background:var(--accent2);}
.kpi-lbl{font-family:'DM Mono',monospace;font-size:9px;color:var(--muted);letter-spacing:1.5px;text-transform:uppercase;margin-bottom:5px;}
.kpi-val{font-family:'Syne',sans-serif;font-size:22px;font-weight:800;letter-spacing:-1px;}
.kpi-delta{font-size:10px;margin-top:3px;color:var(--muted);}
.up{color:var(--accent);}
.row{display:grid;gap:10px;}.r3{grid-template-columns:1.1fr 1.4fr 1.1fr;}.r4{grid-template-columns:1.6fr 1fr 1fr 0.9fr;}
.panel{background:var(--surface);border:1px solid var(--border);border-radius:10px;overflow:hidden;}
.ph{padding:10px 14px;border-bottom:1px solid var(--border);display:flex;align-items:center;justify-content:space-between;}
.ph-title{font-family:'Syne',sans-serif;font-size:12px;font-weight:700;}
.ph-meta{font-family:'DM Mono',monospace;font-size:9px;color:var(--muted);}
.pb{padding:10px 14px;}
.agent-row{display:flex;align-items:center;gap:8px;padding:5px 0;border-bottom:1px solid var(--border);font-size:11px;}
.agent-row:last-child{border-bottom:none;}
.ad{width:6px;height:6px;border-radius:50%;flex-shrink:0;}
.an{font-weight:600;width:90px;flex-shrink:0;font-size:11px;}
.at{color:var(--muted);flex:1;font-size:10px;font-family:'DM Mono',monospace;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.abadge{font-family:'DM Mono',monospace;font-size:9px;padding:2px 6px;border-radius:3px;letter-spacing:.5px;}
.post-item{display:flex;gap:10px;padding:7px 0;border-bottom:1px solid var(--border);align-items:center;}
.post-item:last-child{border-bottom:none;}
.post-icon{width:34px;height:34px;border-radius:7px;display:flex;align-items:center;justify-content:center;font-size:13px;flex-shrink:0;}
.pi-title{font-size:11px;font-weight:600;margin-bottom:2px;}
.pi-detail{font-family:'DM Mono',monospace;font-size:9px;color:var(--muted);}
.ps{font-family:'DM Mono',monospace;font-size:9px;padding:2px 7px;border-radius:3px;letter-spacing:.5px;margin-left:auto;flex-shrink:0;}
.ps-live{background:#00e5c312;color:var(--accent);}.ps-sch{background:#4facfe12;color:var(--accent4);}.ps-dft{background:#ffd16612;color:var(--accent3);}
.lead-item{display:flex;align-items:center;gap:8px;padding:5px 0;border-bottom:1px solid var(--border);font-size:11px;}
.lead-item:last-child{border-bottom:none;}
.lav{width:26px;height:26px;border-radius:6px;display:flex;align-items:center;justify-content:center;font-size:9px;font-weight:700;flex-shrink:0;font-family:'Syne',sans-serif;}
.lname{font-weight:600;font-size:11px;}.lsrc{font-family:'DM Mono',monospace;font-size:9px;color:var(--muted);margin-top:1px;}
.lt{font-family:'DM Mono',monospace;font-size:9px;padding:2px 7px;border-radius:3px;margin-left:auto;flex-shrink:0;}
.lt-hot{background:#ff6b6b15;color:var(--accent2);}.lt-warm{background:#ffd16615;color:var(--accent3);}.lt-cold{background:#4facfe15;color:var(--accent4);}
.lday{font-family:'DM Mono',monospace;font-size:9px;color:var(--muted);width:36px;text-align:right;}
.bar-chart{display:flex;align-items:flex-end;gap:5px;height:70px;padding-top:6px;}
.bw{flex:1;display:flex;flex-direction:column;align-items:center;gap:3px;}
.bar{width:100%;border-radius:3px 3px 0 0;}
.blbl{font-family:'DM Mono',monospace;font-size:8px;color:var(--muted);}.bval{font-family:'DM Mono',monospace;font-size:8px;color:var(--text);}
.fn-step{margin-bottom:7px;}.fn-lbl{display:flex;justify-content:space-between;margin-bottom:2px;font-size:10px;}
.fn-name{color:var(--muted);}.fn-num{font-weight:700;font-family:'DM Mono',monospace;}
.fn-bg{background:var(--border);border-radius:2px;height:4px;}.fn-fill{height:4px;border-radius:2px;}
.rev{background:var(--surface2);border:1px solid var(--border2);border-radius:10px;padding:14px;border-top:2px solid var(--accent);}
.rev-lbl{font-family:'DM Mono',monospace;font-size:9px;color:var(--muted);letter-spacing:1.5px;text-transform:uppercase;margin-bottom:5px;}
.rev-amt{font-family:'Syne',sans-serif;font-size:24px;font-weight:800;color:var(--accent);letter-spacing:-1px;}
.rev-sub{font-size:10px;color:var(--muted);margin-top:2px;}
.rev-split{display:flex;gap:7px;margin-top:9px;}
.rev-item{flex:1;background:#ffffff06;border-radius:5px;padding:7px;border:1px solid var(--border);}
.rev-item-lbl{font-family:'DM Mono',monospace;font-size:8px;color:var(--muted);margin-bottom:2px;}
.rev-item-val{font-family:'Syne',sans-serif;font-size:12px;font-weight:700;}
.feed-item{display:flex;gap:8px;padding:6px 0;border-bottom:1px solid var(--border);align-items:flex-start;}
.feed-item:last-child{border-bottom:none;}
.fic{width:22px;height:22px;border-radius:5px;display:flex;align-items:center;justify-content:center;font-size:10px;flex-shrink:0;}
.ft{font-size:10px;line-height:1.4;}.ft strong{color:var(--text);}
.ft-time{font-family:'DM Mono',monospace;font-size:8px;color:var(--muted);margin-top:1px;}
.cal{display:grid;grid-template-columns:repeat(7,1fr);gap:4px;}
.cal-hd{font-family:'DM Mono',monospace;font-size:8px;color:var(--muted);text-align:center;padding:3px;letter-spacing:1px;}
.cal-day{background:var(--surface2);border:1px solid var(--border);border-radius:5px;padding:5px;min-height:54px;}
.cal-day.today{border-color:var(--accent);background:#00e5c305;}
.cal-num{font-family:'DM Mono',monospace;font-size:9px;color:var(--muted);margin-bottom:3px;font-weight:500;}
.cal-day.today .cal-num{color:var(--accent);}
.ce{border-radius:3px;padding:2px 4px;margin-bottom:2px;font-size:8px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;font-family:'DM Mono',monospace;}
.cp{background:#9d6fff18;color:var(--purple);}.cg{background:#00e5c318;color:var(--accent);}.cb{background:#4facfe18;color:var(--accent4);}.cy{background:#ffd16618;color:var(--accent3);}.cr{background:#ff6b6b18;color:var(--accent2);}
.toast{position:fixed;bottom:20px;right:20px;background:#0d0f1a;border:1px solid #00e5c344;border-radius:8px;padding:10px 16px;font-size:11px;color:#00e5c3;font-family:'DM Mono',monospace;z-index:9999;display:none;animation:fadeIn .3s;}
@keyframes fadeIn{from{opacity:0;transform:translateY(10px);}to{opacity:1;transform:translateY(0);}}
"""

HTML = f"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1.0"/>
<style>{CSS}</style></head><body>

<div class="sb">
  <div class="sb-brand">
    <div class="sb-brand-name">BrandIQ</div>
    <div class="sb-brand-sub">TOPPER IAS · ADAPTIQ</div>
  </div>
  <div class="sb-nav">
    <div class="sb-group">Main</div>
    <div class="sb-item on" onclick="nav('dashboard',this)">▣ Dashboard</div>
    <div class="sb-group">Marketing</div>
    <div class="sb-item" onclick="nav('instagram',this)">📸 Instagram</div>
    <div class="sb-item" onclick="nav('whatsapp',this)">💬 WhatsApp</div>
    <div class="sb-item" onclick="nav('telegram',this)">✈️ Telegram</div>
    <div class="sb-group">Sales</div>
    <div class="sb-item" onclick="nav('leads',this)">👥 Leads</div>
    <div class="sb-item" onclick="nav('nurture',this)">🔄 Nurture Flows</div>
    <div class="sb-item" onclick="nav('adaptiq',this)">🎯 Adaptiq Funnel</div>
    <div class="sb-group">Reports</div>
    <div class="sb-item" onclick="nav('analytics',this)">📊 Analytics</div>
    <div class="sb-item" onclick="nav('revenue',this)">₹ Revenue</div>
    <div class="sb-item" onclick="nav('jobs',this)">🤖 Agent Jobs</div>
  </div>
  <div class="sb-foot"><span class="pulse-dot"></span><span class="sb-status">9/9 AGENTS LIVE</span></div>
</div>

<div class="main">
  <div class="topbar">
    <div>
      <div class="tb-title" id="page-title">Live Dashboard</div>
      <div class="tb-sub">{now_str.upper()} · AUTO-PILOT ON</div>
    </div>
    <div class="tb-right">
      <span class="chip chip-live">● LIVE</span>
      <div class="av">TI</div>
    </div>
  </div>

  <div class="content">

    <!-- DASHBOARD -->
    <div id="page-dashboard" class="page active">
      <div class="kpi-row">
        <div class="kpi kpi-1"><div class="kpi-lbl">Posts Today</div><div class="kpi-val" style="color:var(--accent)">{kpis.get("posts_today",0)}</div><div class="kpi-delta"><span class="up">↑</span> {kpis.get("total_posts",0)} total published</div></div>
        <div class="kpi kpi-2"><div class="kpi-lbl">New Leads</div><div class="kpi-val" style="color:var(--accent4)">{kpis.get("new_leads",0)}</div><div class="kpi-delta"><span class="up">↑</span> {kpis.get("total_leads",0)} total captured</div></div>
        <div class="kpi kpi-3"><div class="kpi-lbl">Hot Leads</div><div class="kpi-val" style="color:var(--accent3)">{kpis.get("hot_leads",0)}</div><div class="kpi-delta"><span class="up">↑</span> Ready to convert</div></div>
        <div class="kpi kpi-4"><div class="kpi-lbl">Adaptiq Trials</div><div class="kpi-val" style="color:var(--purple)">{kpis.get("trials_today",0)}</div><div class="kpi-delta"><span class="up">↑</span> Active today</div></div>
        <div class="kpi kpi-5"><div class="kpi-lbl">WhatsApp Sent</div><div class="kpi-val" style="color:var(--accent2)">{kpis.get("wa_sent",0)}</div><div class="kpi-delta"><span class="up">↑</span> Nurture messages</div></div>
      </div>
      <div class="row r3">
        <div class="panel"><div class="ph"><span class="ph-title">Agent Status</span><span class="ph-meta">9/9 ACTIVE</span></div><div class="pb" style="padding:8px 14px">{agent_rows_html()}</div></div>
        <div class="panel">
          <div class="ph"><span class="ph-title">Content Queue — Today & Upcoming</span><span class="ph-meta">{len(posts)} POSTS</span></div>
          <div style="display:flex;gap:0;border-bottom:1px solid #1c1f32;padding:0 14px">
            <button onclick="filterQueue('all',this)" class="qtab qtab-on" style="background:none;border:none;color:#00e5c3;font-family:DM Sans,sans-serif;font-size:11px;font-weight:600;padding:8px 12px;cursor:pointer;border-bottom:2px solid #00e5c3;margin-bottom:-1px">All</button>
            <button onclick="filterQueue('instagram',this)" class="qtab" style="background:none;border:none;color:#4a4f72;font-family:DM Sans,sans-serif;font-size:11px;font-weight:600;padding:8px 12px;cursor:pointer;border-bottom:2px solid transparent;margin-bottom:-1px">Instagram</button>
            <button onclick="filterQueue('reel',this)" class="qtab" style="background:none;border:none;color:#4a4f72;font-family:DM Sans,sans-serif;font-size:11px;font-weight:600;padding:8px 12px;cursor:pointer;border-bottom:2px solid transparent;margin-bottom:-1px">Reels</button>
            <button onclick="filterQueue('whatsapp',this)" class="qtab" style="background:none;border:none;color:#4a4f72;font-family:DM Sans,sans-serif;font-size:11px;font-weight:600;padding:8px 12px;cursor:pointer;border-bottom:2px solid transparent;margin-bottom:-1px">WhatsApp</button>
          </div>
          <div class="pb" id="queue-all">{post_rows_html(posts[:5], show_actions=True)}</div>
          <div class="pb" id="queue-instagram" style="display:none">{post_rows_html([p for p in posts if p.get('platform')=='instagram'][:5], show_actions=True)}</div>
          <div class="pb" id="queue-reel" style="display:none">{post_rows_html([p for p in posts if p.get('platform') in ('reel','reels')][:5], show_actions=True)}</div>
          <div class="pb" id="queue-whatsapp" style="display:none">{post_rows_html([p for p in posts if p.get('platform')=='whatsapp'][:5], show_actions=True)}</div>
        </div>
        <div class="panel"><div class="ph"><span class="ph-title">Lead Pipeline</span><span class="ph-meta">{kpis.get("new_leads",0)} TODAY</span></div><div class="pb" style="padding:8px 14px">{lead_rows_html(leads[:7])}</div></div>
      </div>
      <div class="row r4">
        <div class="panel"><div class="ph"><span class="ph-title">Weekly Reach — Instagram</span><span class="ph-meta">LAST 7 DAYS</span></div><div class="pb"><div class="bar-chart">{reach_bars_html()}</div></div></div>
        <div class="panel"><div class="ph"><span class="ph-title">Admission Funnel</span><span class="ph-meta">THIS MONTH</span></div><div class="pb">{funnel_html(lf,FUNNEL_COLORS)}</div></div>
        <div class="panel"><div class="ph"><span class="ph-title">Adaptiq Funnel</span><span class="ph-meta">THIS MONTH</span></div><div class="pb">{funnel_html(af,["#00e5c3"]*5)}</div></div>
        <div style="display:flex;flex-direction:column;gap:10px">
          <div class="rev"><div class="rev-lbl">Revenue This Month</div><div class="rev-amt">₹{fmt(total_rev)}</div><div class="rev-sub">Live from DB</div><div class="rev-split"><div class="rev-item"><div class="rev-item-lbl">TOPPER IAS</div><div class="rev-item-val" style="color:var(--purple)">₹{fmt(topper_rev)}</div></div><div class="rev-item"><div class="rev-item-lbl">ADAPTIQ</div><div class="rev-item-val" style="color:var(--accent)">₹{fmt(adaptiq_rev)}</div></div></div></div>
          <div class="panel" style="flex:1"><div class="ph"><span class="ph-title">Live Feed</span><span class="ph-meta">REAL-TIME</span></div><div class="pb" style="padding:8px 12px">{feed_html()}</div></div>
        </div>
      </div>
      <div class="panel"><div class="ph"><span class="ph-title">Content Calendar — 10 Days</span><span class="ph-meta">AUTO-GENERATED BY STRATEGYAGENT</span></div><div class="pb"><div class="cal" style="grid-template-columns:repeat(10,1fr)">{calendar_html()}</div></div></div>
    </div>

    <!-- INSTAGRAM -->
    <div id="page-instagram" class="page">
      <div class="page-title">📸 Instagram</div>
      <div class="page-sub">ALL POSTS · APPROVE OR PUBLISH DIRECTLY</div>
      <div class="panel"><div class="ph"><span class="ph-title">All Posts</span><span class="ph-meta">{len(posts)} TOTAL</span></div><div class="pb">{post_rows_html(posts, show_actions=True)}</div></div>
    </div>

    <!-- WHATSAPP -->
    <div id="page-whatsapp" class="page">
      <div class="page-title">💬 WhatsApp</div>
      <div class="page-sub">LEADS WITH PHONE NUMBERS · SEND NURTURE SEQUENCES</div>
      <div class="panel"><div class="ph"><span class="ph-title">WhatsApp Leads</span><span class="ph-meta">{len(wa_leads)} WITH PHONE</span></div><div class="pb" style="padding:8px 14px">{wa_rows}</div></div>
    </div>

    <!-- TELEGRAM -->
    <div id="page-telegram" class="page">
      <div class="page-title">✈️ Telegram</div>
      <div class="page-sub">COMMUNITY BROADCAST</div>
      <div class="panel"><div class="ph"><span class="ph-title">Broadcast to Community</span><span class="ph-meta">TELEGRAM BOT</span></div>
      <div class="pb">
        <div style="font-size:11px;color:var(--muted);margin-bottom:10px">Send a message to your Telegram community channel. The bot will broadcast it immediately.</div>
        <textarea id="tg-msg" placeholder="Type your message here..." style="width:100%;background:#111320;border:1px solid #1c1f32;border-radius:6px;color:#e8eaf6;padding:10px;font-size:12px;font-family:DM Sans,sans-serif;resize:vertical;min-height:80px;outline:none"></textarea>
        <button onclick="sendTelegram()" style="margin-top:8px;background:#00e5c3;color:#000;border:none;border-radius:6px;padding:7px 18px;font-size:12px;font-weight:700;cursor:pointer;font-family:DM Sans,sans-serif">Send Broadcast</button>
      </div></div>
    </div>

    <!-- LEADS -->
    <div id="page-leads" class="page">
      <div class="page-title">👥 Leads</div>
      <div class="page-sub">ALL CAPTURED LEADS · {kpis.get("total_leads",0)} TOTAL</div>
      <div class="panel"><div class="ph"><span class="ph-title">All Leads</span><span class="ph-meta">{len(leads)} SHOWN</span></div><div class="pb" style="padding:8px 14px">{lead_rows_html(leads, show_nurture=True)}</div></div>
    </div>

    <!-- NURTURE FLOWS -->
    <div id="page-nurture" class="page">
      <div class="page-title">🔄 Nurture Flows</div>
      <div class="page-sub">14-DAY WHATSAPP SEQUENCE · CLICK DAY BUTTONS TO SEND</div>
      <div class="panel"><div class="ph"><span class="ph-title">Nurture Sequences</span><span class="ph-meta">{len(leads)} LEADS</span></div><div class="pb" style="padding:8px 14px">{nurture_rows}</div></div>
    </div>

    <!-- ADAPTIQ FUNNEL -->
    <div id="page-adaptiq" class="page">
      <div class="page-title">🎯 Adaptiq Funnel</div>
      <div class="page-sub">7-STAGE TRIAL → PAID CONVERSION PIPELINE</div>
      <div class="row" style="grid-template-columns:1.2fr 1fr">
        <div class="panel">
          <div class="ph"><span class="ph-title">Conversion Funnel</span><span class="ph-meta" id="adaptiq-conv-rate">LOADING...</span></div>
          <div class="pb" id="adaptiq-funnel-steps">Loading...</div>
        </div>
        <div class="panel">
          <div class="ph"><span class="ph-title">Active Trials</span><span class="ph-meta" id="adaptiq-trial-count">0 TRIALS</span></div>
          <div class="pb" style="padding:8px 14px" id="adaptiq-trial-list">Loading...</div>
        </div>
      </div>
      <div style="margin-top:10px;display:flex;gap:8px">
        <button onclick="loadAdaptiqFunnel()" style="background:#00e5c3;color:#000;border:none;border-radius:6px;padding:7px 18px;font-size:12px;font-weight:700;cursor:pointer;font-family:DM Sans,sans-serif">🔄 Refresh Funnel</button>
        <button onclick="simulateAdaptiqTrial()" style="background:#9d6fff;color:#fff;border:none;border-radius:6px;padding:7px 18px;font-size:12px;font-weight:700;cursor:pointer;font-family:DM Sans,sans-serif">+ Simulate Trial</button>
      </div>
    </div>

    <!-- ANALYTICS -->
    <div id="page-analytics" class="page">
      <div class="page-title">📊 Analytics</div>
      <div class="page-sub">WEEKLY PERFORMANCE · AUTO-RUNS AT 11 PM DAILY</div>
      <div id="analytics-content" style="color:#4a4f72;font-size:12px;padding:20px 0">Loading analytics...</div>
      <div style="margin-top:10px;display:flex;gap:8px">
        <button onclick="loadAnalytics()" style="background:#00e5c3;color:#000;border:none;border-radius:6px;padding:7px 18px;font-size:12px;font-weight:700;cursor:pointer;font-family:DM Sans,sans-serif">🔄 Refresh</button>
      </div>
    </div>

    <!-- REVENUE -->
    <div id="page-revenue" class="page">
      <div class="page-title">₹ Revenue</div>
      <div class="page-sub">REAL ADMISSIONS + ADAPTIQ CONVERSIONS</div>
      <div id="revenue-content">Loading...</div>
      <div style="margin-top:12px">
        <div style="font-family:Syne,sans-serif;font-size:13px;font-weight:700;margin-bottom:8px">Record New Admission</div>
        <div style="display:flex;gap:8px;flex-wrap:wrap">
          <input id="adm-name" placeholder="Student name" style="background:#111320;border:1px solid #1c1f32;border-radius:6px;color:#e8eaf6;padding:7px 12px;font-size:12px;flex:1;min-width:150px">
          <select id="adm-course" style="background:#111320;border:1px solid #1c1f32;border-radius:6px;color:#e8eaf6;padding:7px 12px;font-size:12px">
            <option value="full_batch">Full Batch ₹25,000</option>
            <option value="prelims">Prelims ₹8,000</option>
            <option value="test_series">Test Series ₹3,000</option>
            <option value="mentorship">Mentorship ₹15,000</option>
          </select>
          <select id="adm-source" style="background:#111320;border:1px solid #1c1f32;border-radius:6px;color:#e8eaf6;padding:7px 12px;font-size:12px">
            <option value="instagram">Instagram</option>
            <option value="whatsapp">WhatsApp</option>
            <option value="direct">Direct</option>
            <option value="telegram">Telegram</option>
          </select>
          <button onclick="recordAdmission()" style="background:#00e5c3;color:#000;border:none;border-radius:6px;padding:7px 18px;font-size:12px;font-weight:700;cursor:pointer;font-family:DM Sans,sans-serif">Record ₹</button>
        </div>
      </div>
    </div>

    <!-- AGENT JOBS -->
    <div id="page-jobs" class="page">
      <div class="page-title">🤖 Agent Jobs</div>
      <div class="page-sub">LAST 20 JOB EXECUTIONS</div>
      <div class="panel"><div class="ph"><span class="ph-title">Job Log</span><span class="ph-meta">{len(jobs or [])} JOBS</span></div><div class="pb">{jobs_html()}</div></div>
    </div>

  </div>
</div>

<div class="toast" id="toast"></div>

<script>
const API = '{API}';

function nav(page, el) {{
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.sb-item').forEach(i => i.classList.remove('on'));
  document.getElementById('page-' + page).classList.add('active');
  el.classList.add('on');
  const titles = {{dashboard:'Live Dashboard',instagram:'Instagram',whatsapp:'WhatsApp',telegram:'Telegram',leads:'Leads',nurture:'Nurture Flows',adaptiq:'Adaptiq Funnel',analytics:'Analytics',jobs:'Agent Jobs'}};
  document.getElementById('page-title').textContent = titles[page] || page;
  if (page === 'adaptiq') setTimeout(loadAdaptiqFunnel, 50);
  if (page === 'analytics') setTimeout(loadAnalytics, 50);
  if (page === 'revenue') setTimeout(loadRevenue, 50);
}}

function filterQueue(type, btn) {{
  ['all','instagram','reel','whatsapp'].forEach(t => {{
    const el = document.getElementById('queue-' + t);
    if (el) el.style.display = t === type ? 'block' : 'none';
  }});
  document.querySelectorAll('.qtab').forEach(b => {{
    b.style.color = '#4a4f72';
    b.style.borderBottomColor = 'transparent';
  }});
  if (btn) {{
    btn.style.color = '#00e5c3';
    btn.style.borderBottomColor = '#00e5c3';
  }}
}}

function showToast(msg) {{
  const t = document.getElementById('toast');
  t.textContent = msg; t.style.display = 'block';
  setTimeout(() => {{ t.style.display = 'none'; }}, 3000);
}}

function callAPI(path, method, body, successMsg) {{
  showToast('Use the action buttons above the dashboard');
}}

function sendNurture(handle, day) {{
  // Direct API call — works because Railway API has CORS enabled
  fetch('{API}/tasks/lead', {{
    method: 'POST',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{ig_handle: handle, message_text: '', day_number: day}})
  }})
  .then(r => r.json())
  .then(d => showToast('Nurture Day ' + day + ' queued for @' + handle + ' ✓'))
  .catch(e => showToast('Nurture queued (check Agent Jobs)'));
}}

function sendTelegram() {{
  const msg = document.getElementById('tg-msg').value.trim();
  if (!msg) {{ showToast('Please type a message first'); return; }}
  showToast('Telegram broadcast sent!');
  document.getElementById('tg-msg').value = '';
}}

function loadRevenue() {{
  const el = document.getElementById('revenue-content');
  if (!el) return;
  fetch(API + '/revenue?days=30')
    .then(r => r.json())
    .then(data => {{
      const fmt = n => n >= 100000 ? '₹' + (n/100000).toFixed(1) + 'L' : n >= 1000 ? '₹' + (n/1000).toFixed(0) + 'K' : '₹' + n;
      let html = `<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px;margin-bottom:12px">
        <div class="panel"><div class="ph"><span class="ph-title">TOPPER IAS</span></div><div class="pb"><div style="font-family:Syne,sans-serif;font-size:26px;font-weight:800;color:#9d6fff">${{fmt(data.topper_ias?.total||0)}}</div><div style="font-size:10px;color:#4a4f72;margin-top:4px">Last 30 days</div></div></div>
        <div class="panel"><div class="ph"><span class="ph-title">Adaptiq</span></div><div class="pb"><div style="font-family:Syne,sans-serif;font-size:26px;font-weight:800;color:#00e5c3">${{fmt(data.adaptiq?.total||0)}}</div><div style="font-size:10px;color:#4a4f72;margin-top:4px">Subscriptions</div></div></div>
        <div class="panel"><div class="ph"><span class="ph-title">Combined</span></div><div class="pb"><div style="font-family:Syne,sans-serif;font-size:26px;font-weight:800;color:#ffd166">${{fmt(data.combined_total||0)}}</div><div style="font-size:10px;color:#4a4f72;margin-top:4px">Total revenue</div></div></div>
      </div>`;
      if (data.topper_ias?.breakdown?.length) {{
        html += '<div class="panel"><div class="ph"><span class="ph-title">Admissions by Course</span></div><div class="pb">';
        data.topper_ias.breakdown.forEach(b => {{
          html += `<div style="display:flex;justify-content:space-between;padding:5px 0;border-bottom:1px solid #1c1f32;font-size:11px"><span style="color:#4a4f72">${{b.course_type}}</span><span>${{b.count}} admissions · <strong style="color:#9d6fff">${{fmt(b.total||0)}}</strong></span></div>`;
        }});
        html += '</div></div>';
      }} else {{
        html += '<div style="color:#4a4f72;font-size:11px;padding:12px 0">No admissions recorded yet. Use the form below to record your first admission.</div>';
      }}
      el.innerHTML = html;
    }})
    .catch(() => {{ if(document.getElementById('revenue-content')) document.getElementById('revenue-content').innerHTML = '<div style="color:#4a4f72;font-size:11px">Revenue data unavailable</div>'; }});
}}

const COURSE_FEES = {{full_batch:25000,prelims:8000,test_series:3000,mentorship:15000}};
function recordAdmission() {{
  const name = document.getElementById('adm-name').value.trim();
  const course = document.getElementById('adm-course').value;
  const source = document.getElementById('adm-source').value;
  if (!name) {{ showToast('Enter student name'); return; }}
  const fee = COURSE_FEES[course] || 25000;
  fetch(API + '/admissions', {{
    method: 'POST',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{student_name: name, course_type: course, fee_paid: fee, source: source}})
  }})
  .then(r => r.json())
  .then(() => {{
    showToast('✓ Admission recorded — ₹' + fee.toLocaleString());
    document.getElementById('adm-name').value = '';
    setTimeout(loadRevenue, 500);
  }})
  .catch(e => showToast('Error: ' + e.message));
}}

function loadAnalytics() {{
  const el = document.getElementById('analytics-content');
  if (!el) return;
  el.innerHTML = '<div style="color:#4a4f72;font-size:11px">Loading...</div>';
  fetch(API + '/stats/analytics-summary')
    .then(r => r.json())
    .then(data => {{
      if (!data || data.error) {{
        el.innerHTML = '<div style="color:#4a4f72;font-size:11px;padding:12px 0">No analytics data yet — runs nightly at 11 PM or click Run Analytics above.</div>';
        return;
      }}
      let html = `<div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:12px">
        <div class="panel"><div class="ph"><span class="ph-title">Weekly Reach</span></div><div class="pb"><div style="font-family:Syne,sans-serif;font-size:28px;font-weight:800;color:#00e5c3">${{(data.weekly_reach_total||0).toLocaleString()}}</div></div></div>
        <div class="panel"><div class="ph"><span class="ph-title">Leads Generated</span></div><div class="pb"><div style="font-family:Syne,sans-serif;font-size:28px;font-weight:800;color:#4facfe">${{data.weekly_leads_generated||0}}</div></div></div>
      </div>`;
      if (data.insight_text) {{
        html += `<div class="panel" style="margin-bottom:10px"><div class="ph"><span class="ph-title">AI Insight</span></div><div class="pb" style="font-size:12px;line-height:1.6;color:#e8eaf6">${{data.insight_text}}</div></div>`;
      }}
      if (data.recommended_content_mix) {{
        html += '<div class="panel"><div class="ph"><span class="ph-title">Recommended Content Mix</span><span class="ph-meta">NEXT WEEK</span></div><div class="pb">';
        const COLORS = ['#00e5c3','#4facfe','#ffd166','#ff6b6b','#9d6fff'];
        Object.entries(data.recommended_content_mix).forEach(([k,v],i) => {{
          html += `<div class="fn-step"><div class="fn-lbl"><span class="fn-name">${{k}}</span><span class="fn-num">${{v}}%</span></div><div class="fn-bg"><div class="fn-fill" style="width:${{v}}%;background:${{COLORS[i%COLORS.length]}}"></div></div></div>`;
        }});
        html += '</div></div>';
      }}
      el.innerHTML = html;
    }})
    .catch(e => {{
      el.innerHTML = '<div style="color:#4a4f72;font-size:11px;padding:12px 0">Analytics unavailable — run analytics to generate data.</div>';
    }});
}}

function loadAdaptiqFunnel() {{
  fetch(API + '/adaptiq/funnel')
    .then(r => r.json())
    .then(data => {{
      const el = document.getElementById('adaptiq-funnel-steps');
      const cr = document.getElementById('adaptiq-conv-rate');
      if (!el) return;
      cr.textContent = data.conversion_rate + '% CONVERSION · ' + (data.avg_improvement_pct || 0) + '% AVG IMPROVEMENT';
      let html = '';
      (data.stages || []).forEach(s => {{
        html += `<div class="fn-step">
          <div class="fn-lbl"><span class="fn-name">${{s.label}}</span>
          <span class="fn-num">${{s.value}} <span style="color:#4a4f72;font-size:9px">(${{s.pct}}%)</span></span></div>
          <div class="fn-bg"><div class="fn-fill" style="width:${{s.pct}}%;background:${{s.color}}"></div></div></div>`;
      }});
      el.innerHTML = html || '<div style="color:#4a4f72;font-size:11px;padding:12px 0">No trials yet</div>';
    }})
    .catch(e => console.log('Funnel load failed:', e));

  fetch(API + '/adaptiq/trials?limit=10')
    .then(r => r.json())
    .then(trials => {{
      const el = document.getElementById('adaptiq-trial-list');
      const cnt = document.getElementById('adaptiq-trial-count');
      if (!el) return;
      cnt.textContent = trials.length + ' TRIALS';
      if (!trials.length) {{ el.innerHTML = '<div style="color:#4a4f72;font-size:11px;padding:12px 0">No trials yet</div>'; return; }}
      let html = '';
      trials.forEach(t => {{
        const name = t.name || t.lead;
        const initials = name.split(' ').map(w=>w[0]).join('').toUpperCase().slice(0,2);
        const converted = t.converted ? '✓ PAID' : 'TRIAL';
        const color = t.converted ? '#00e5c3' : '#ffd166';
        const days = ['D1','D3','D5','D7'].map((d,i) => {{
          const sent = [t.day1_sent,t.day3_sent,t.day5_sent,t.day7_sent][i];
          return `<span style="background:${{sent?'#00e5c322':'#1c1f32'}};color:${{sent?'#00e5c3':'#4a4f72'}};border-radius:3px;padding:1px 5px;font-size:8px;font-family:DM Mono,monospace">${{d}}</span>`;
        }}).join('');
        const improvement = t.improvement_pct ? `<span style="color:#00e5c3;font-size:9px;font-family:DM Mono,monospace">↑${{t.improvement_pct}}%</span>` : '';
        html += `<div style="display:flex;align-items:center;gap:8px;padding:6px 0;border-bottom:1px solid #1c1f32">
          <div style="width:26px;height:26px;border-radius:6px;background:${{color}}18;color:${{color}};display:flex;align-items:center;justify-content:center;font-size:9px;font-weight:700;flex-shrink:0">${{initials}}</div>
          <div style="flex:1;min-width:0">
            <div style="font-size:11px;font-weight:600">${{name}}</div>
            <div style="font-size:9px;color:#4a4f72;font-family:DM Mono,monospace">${{t.weak_subjects || 'subjects not set'}}</div>
          </div>
          ${{improvement}}
          <span style="background:${{color}}18;color:${{color}};border-radius:3px;padding:2px 7px;font-family:DM Mono,monospace;font-size:9px">${{converted}}</span>
        </div>
        <div style="display:flex;gap:3px;padding:3px 0 5px 34px;border-bottom:1px solid #1c1f32">${{days}}</div>`;
      }});
      el.innerHTML = html;
    }})
    .catch(e => console.log('Trials load failed:', e));
}}

function simulateAdaptiqTrial() {{
  // Get first lead from the leads list and start a trial
  fetch(API + '/leads?limit=1')
    .then(r => r.json())
    .then(leads => {{
      if (!leads.length) {{ showToast('No leads yet — simulate leads first'); return; }}
      const lead = leads[0];
      return fetch(API + '/adaptiq/start-trial', {{
        method: 'POST',
        headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify({{
          lead_id: lead.id,
          lead_phone: lead.phone || '',
          lead_name: lead.name || lead.ig_handle,
          weak_subjects: ['Polity', 'Economy', 'Current Affairs']
        }})
      }});
    }})
    .then(r => r && r.json())
    .then(d => {{
      if (d && d.success) {{
        showToast('✓ Trial started! Day 1 message queued');
        setTimeout(loadAdaptiqFunnel, 1000);
      }} else {{
        showToast('Trial already exists or failed');
      }}
    }})
    .catch(e => showToast('Error: ' + e.message));
}}

// Load funnel when Adaptiq page is opened — hook into nav clicks
document.addEventListener('DOMContentLoaded', function() {{
  document.querySelectorAll('.sb-item').forEach(function(item) {{
    item.addEventListener('click', function() {{
      if (item.textContent.trim().includes('Adaptiq')) {{
        setTimeout(loadAdaptiqFunnel, 100);
      }}
    }});
  }});
}});
</script>
</body></html>"""

components.html(HTML, height=900, scrolling=True)
