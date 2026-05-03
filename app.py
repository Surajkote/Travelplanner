import streamlit as st
import os
import requests
from datetime import date, timedelta
from dotenv import load_dotenv
from graph import build_graph, CurrencyInfo

load_dotenv()

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="TripSmith – AI Travel Planner",
    page_icon="✈️",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── CSS ───────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&family=Playfair+Display:wght@700&display=swap');

html, body, [data-testid="stAppViewContainer"] {
    background: linear-gradient(135deg,#0f0c29 0%,#1a1a2e 45%,#16213e 100%) !important;
    font-family:'Inter',sans-serif; color:#e8e8f0;
}
[data-testid="stHeader"]{background:transparent!important;}

.hero{text-align:center;padding:2.5rem 1rem 1.5rem;}
.hero-title{
    font-family:'Playfair Display',serif;
    font-size:clamp(2.2rem,5.5vw,4rem);
    background:linear-gradient(135deg,#f8cdda,#1d8fe1,#a78bfa);
    -webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;
}
.hero-sub{font-size:1.05rem;color:#94a3b8;margin-top:.4rem;}

.card{
    background:rgba(255,255,255,.05);
    border:1px solid rgba(255,255,255,.1);
    border-radius:20px;padding:1.8rem;margin-bottom:1.4rem;
    backdrop-filter:blur(12px);
}
.section-label{font-size:.72rem;font-weight:700;letter-spacing:2px;text-transform:uppercase;color:#a78bfa;margin-bottom:.9rem;}

.stTextInput>div>div>input,
.stNumberInput>div>div>input {
    background:rgba(255,255,255,.07)!important;
    border:1px solid rgba(167,139,250,.3)!important;
    border-radius:12px!important;color:#e8e8f0!important;
}

div[data-testid="stButton"]>button{
    width:100%;padding:.9rem 2rem;
    background:linear-gradient(135deg,#6366f1,#8b5cf6,#a78bfa);
    color:white;border:none;border-radius:14px;
    font-size:1.05rem;font-weight:700;font-family:'Inter',sans-serif;
    cursor:pointer;transition:all .3s;margin-top:.8rem;
}
div[data-testid="stButton"]>button:hover{
    transform:translateY(-2px);box-shadow:0 10px 30px rgba(99,102,241,.5);
}

.day-card{
    background:linear-gradient(135deg,rgba(99,102,241,.12),rgba(139,92,246,.08));
    border:1px solid rgba(167,139,250,.25);border-radius:20px;
    padding:1.6rem;margin-bottom:1.4rem;
}
.day-badge{
    display:inline-flex;align-items:center;justify-content:center;
    background:linear-gradient(135deg,#6366f1,#8b5cf6);
    color:white;border-radius:50%;width:50px;height:50px;
    font-size:1.2rem;font-weight:800;flex-shrink:0;
}
.day-title{font-size:1.15rem;font-weight:700;color:#e8e8f0;}
.day-date{font-size:.82rem;color:#94a3b8;margin-top:2px;}
.day-summary{font-size:.88rem;color:#a78bfa;font-style:italic;margin:.6rem 0 1rem;}
.weather-badge{
    display:inline-block;background:rgba(96,165,250,.15);
    color:#60a5fa;border-radius:8px;padding:3px 10px;
    font-size:.78rem;margin-bottom:1rem;
}

.act-row{
    display:flex;gap:.9rem;align-items:flex-start;
    background:rgba(255,255,255,.04);border-radius:14px;
    padding:.9rem 1.1rem;margin-bottom:.7rem;
    border-left:3px solid #6366f1;
}
.act-time{font-size:.76rem;font-weight:700;color:#a78bfa;white-space:nowrap;min-width:110px;padding-top:2px;}
.act-body{flex:1;}
.act-name{font-size:.98rem;font-weight:600;color:#e8e8f0;margin-bottom:3px;}
.act-desc{font-size:.83rem;color:#94a3b8;margin-bottom:4px;}
.act-tip{font-size:.78rem;color:#fbbf24;background:rgba(251,191,36,.08);border-radius:8px;padding:3px 8px;margin-bottom:5px;}
.act-tags{display:flex;gap:5px;flex-wrap:wrap;}
.tag{font-size:.7rem;font-weight:600;padding:2px 9px;border-radius:20px;}
.t-out{background:rgba(52,211,153,.15);color:#34d399;}
.t-in{background:rgba(96,165,250,.15);color:#60a5fa;}
.t-cost{background:rgba(167,139,250,.15);color:#a78bfa;}

.cost-bar{display:flex;gap:.9rem;margin-top:1rem;flex-wrap:wrap;}
.chip{background:rgba(255,255,255,.06);border:1px solid rgba(255,255,255,.1);border-radius:10px;padding:5px 12px;font-size:.8rem;color:#94a3b8;}
.chip span{color:#e8e8f0;font-weight:700;}

.budget-box{
    background:linear-gradient(135deg,rgba(99,102,241,.2),rgba(168,85,247,.15));
    border:1px solid rgba(167,139,250,.4);border-radius:18px;
    padding:1.4rem 2rem;margin-bottom:1.8rem;text-align:center;
}
.budget-total{font-size:1.9rem;font-weight:800;color:#a78bfa;}
.bpass{display:inline-block;background:rgba(52,211,153,.2);color:#34d399;border:1px solid #34d399;border-radius:20px;padding:3px 14px;font-size:.82rem;font-weight:700;margin-top:5px;}
.bwarn{display:inline-block;background:rgba(251,191,36,.2);color:#fbbf24;border:1px solid #fbbf24;border-radius:20px;padding:3px 14px;font-size:.82rem;font-weight:700;margin-top:5px;}
.highlights{background:rgba(255,255,255,.04);border-left:4px solid #6366f1;border-radius:0 14px 14px 0;padding:.9rem 1.3rem;margin-bottom:1.6rem;font-size:.93rem;color:#cbd5e1;line-height:1.7;}

.api-row{display:flex;gap:.6rem;flex-wrap:wrap;margin-bottom:.5rem;}
.api-chip{background:rgba(255,255,255,.06);border:1px solid rgba(255,255,255,.12);border-radius:8px;padding:3px 10px;font-size:.73rem;color:#94a3b8;}
</style>
""", unsafe_allow_html=True)

# ── Location detection ────────────────────────────────────────────────────────
@st.cache_data(show_spinner=False)
def detect_location():
    try:
        r = requests.get("http://ip-api.com/json/?fields=country,currency", timeout=5)
        d = r.json()
        return d.get("country", "United States"), d.get("currency", "USD")
    except Exception:
        return "United States", "USD"

user_country, user_currency = detect_location()

SYMBOLS = {
    "USD":"$","EUR":"€","GBP":"£","INR":"₹","JPY":"¥",
    "CAD":"CA$","AUD":"A$","CNY":"¥","SGD":"S$","AED":"د.إ",
    "CHF":"Fr","MXN":"MX$","BRL":"R$",
}
symbol = SYMBOLS.get(user_currency, user_currency + " ")

INTERESTS = [
    "Art & Museums","Food & Cuisine","History & Heritage","Nature & Hiking",
    "Nightlife & Bars","Shopping & Markets","Architecture","Photography",
    "Music & Concerts","Sports & Adventure","Wellness & Spa",
    "Beach & Water Sports","Gaming & Esports","Street Food",
    "Wine & Cocktails","Theatre & Performing Arts","Cycling",
    "Volunteering & Culture","Religious & Spiritual Sites",
    "Theme Parks & Rides","Local Festivals","Cooking Classes",
]

# ── Hero ──────────────────────────────────────────────────────────────────────
st.markdown("""
<div class="hero">
  <div class="hero-title">✈️ TripSmith</div>
  <div class="hero-sub">Real data. Real routes. Real weather. AI-planned itineraries that actually work.</div>
</div>
""", unsafe_allow_html=True)

# ── Data sources badge ────────────────────────────────────────────────────────
st.markdown("""
<div style="text-align:center;margin-bottom:1.4rem;">
  <div class="api-row" style="justify-content:center;">
    <span class="api-chip">🗺 OpenStreetMap Nominatim</span>
    <span class="api-chip">🚗 OSRM Transit Router</span>
    <span class="api-chip">🌦 Open-Meteo Forecast</span>
    <span class="api-chip">📖 Wikivoyage Destination</span>
    <span class="api-chip">💰 Numbeo Cost of Living</span>
    <span class="api-chip">🔍 Tavily FX Rates</span>
    <span class="api-chip">🤖 Groq LLM Formatter</span>
  </div>
</div>
""", unsafe_allow_html=True)

# ── Input Form ────────────────────────────────────────────────────────────────
st.markdown('<div class="card">', unsafe_allow_html=True)
st.markdown('<p class="section-label">🗺 Plan Your Trip</p>', unsafe_allow_html=True)

col1, col2 = st.columns([2, 1])
with col1:
    destination = st.text_input("Destination City / Country", placeholder="e.g. Tokyo, Japan")
with col2:
    st.caption(f"📍 {user_country} · 💱 {user_currency}")
    budget = st.number_input(
        f"Budget ({symbol}{user_currency})",
        min_value=0,
        max_value=10_000_000,
        value=None,
        step=500,
        placeholder="Enter your budget",
    )

today = date.today()

# Safe date handling with session_state
if "trip_start" not in st.session_state:
    st.session_state["trip_start"] = today + timedelta(days=7)

col3, col4 = st.columns(2)
with col3:
    start_date = st.date_input(
        "Start Date",
        value=st.session_state["trip_start"],
        min_value=today,
        key="sd_widget",
    )
    st.session_state["trip_start"] = start_date

safe_end_default = max(start_date + timedelta(days=3), st.session_state["trip_start"] + timedelta(days=3))
with col4:
    end_date = st.date_input(
        "End Date",
        value=safe_end_default,
        min_value=start_date,
        key="ed_widget",
    )

if end_date < start_date:
    st.error("End date must be on or after start date.")
    st.stop()

num_days = (end_date - start_date).days + 1
st.info(f"🗓️ {num_days} day{'s' if num_days != 1 else ''} — {start_date.strftime('%d %b %Y')} to {end_date.strftime('%d %b %Y')} (inclusive)")

selected_interests = st.multiselect(
    "Interests (choose or type your own)",
    options=INTERESTS,
    placeholder="Select at least one interest...",
)
custom = st.text_input("Custom interest (optional)", placeholder="e.g. Manga, Skydiving")
if custom.strip():
    selected_interests.append(custom.strip())

generate_btn = st.button("✨ Generate My Itinerary")
st.markdown('</div>', unsafe_allow_html=True)

# ── Run ───────────────────────────────────────────────────────────────────────
if generate_btn:
    errors = []
    if not destination or not destination.strip():
        errors.append("Please enter a destination.")
    if not budget or budget <= 0:
        errors.append("Please enter a valid budget.")
    if not selected_interests:
        errors.append("Please select at least one interest.")
    if errors:
        for e in errors:
            st.warning(e)
        st.stop()

    raw_input = (
        f"Plan a trip to {destination} from {start_date} to {end_date} "
        f"({num_days} days). Budget: {budget} {user_currency}. "
        f"Interests: {', '.join(selected_interests)}."
    )

    app = build_graph()
    initial_state = {
        "raw_input": raw_input,
        "iteration": 0,
        "constraint_violations": [],
        "destination_data": None,
        "weather_data": None,
        "currency_info": CurrencyInfo(
            user_currency=user_currency,
            exchange_rate=0.0,
            budget_usd=0.0,
            budget_original=float(budget),
        ),
    }

    final_state = {}

    with st.status("🧠 TripSmith Agent Running...", expanded=True) as status:
        for event in app.stream(initial_state, stream_mode="updates"):
            for node_name, node_state in event.items():
                if isinstance(node_state, dict):
                    final_state.update(node_state)

                if node_name == "currency_resolver":
                    ci = final_state.get("currency_info")
                    if ci and ci.exchange_rate:
                        st.write(f"💱 1 {user_currency} = {ci.exchange_rate:.5f} USD → **${ci.budget_usd:,.2f} USD** budget")

                elif node_name == "input_parser":
                    p = final_state.get("user_prefs")
                    if p:
                        st.write(f"✅ Parsed: **{p.destination}**, {p.days} days, **${p.budget_usd:,.2f} USD**")

                elif node_name == "destination_researcher":
                    dd = final_state.get("destination_data") or {}
                    wiki_ok = bool(dd.get("wikivoyage"))
                    numbeo_ok = bool(dd.get("numbeo"))
                    st.write(f"📖 Wikivoyage: {'✅' if wiki_ok else '⚠️ No data'}  |  💰 Numbeo: {'✅' if numbeo_ok else '⚠️ No data'}")

                elif node_name == "weather_fetcher":
                    wd = final_state.get("weather_data") or {}
                    st.write(f"🌦 Open-Meteo: {len(wd)} day forecast fetched for actual trip dates")

                elif node_name == "planner":
                    it = final_state.get("iteration", 1)
                    st.write(f"🔄 Iteration **{it}**: LLM drafting itinerary using all real data...")

                elif node_name == "aggregator":
                    b = final_state.get("budget_status")
                    v = final_state.get("constraint_violations", [])
                    prefs = final_state.get("user_prefs")
                    if b and b.is_over_budget:
                        over = b.total_cost_usd - (prefs.budget_usd if prefs else 0)
                        st.warning(f"💸 Over budget by **${over:.2f}**. Replanning...")
                        for ov in b.itemized_overages[:3]:
                            st.write(f"  › {ov}")
                    if v:
                        st.warning(f"🛑 {len(v)} OSRM/weather constraint violation(s). Replanning...")
                        for vv in v[:3]:
                            st.write(f"  › Day {vv.day}: {vv.issue}")
                    if (not b or not b.is_over_budget) and not v:
                        st.success("✅ All validators passed!")

                elif node_name == "formatter":
                    st.write("✨ Finalising...")

        passed = final_state.get("all_validators_passed", False)
        status.update(
            label="✅ Itinerary Ready!" if passed else "⚠️ Best itinerary generated",
            state="complete", expanded=False,
        )

    # ── Display ───────────────────────────────────────────────────────────────
    # ── Currency helpers ───────────────────────────────────────────────────────
    ci          = final_state.get("currency_info")
    itinerary   = final_state.get("current_itinerary")
    budget_stat = final_state.get("budget_status")
    prefs       = final_state.get("user_prefs")
    weather     = final_state.get("weather_data") or {}

    # user_rate: how many USD per 1 user_currency → to convert USD→user: divide by user_rate
    user_rate = (ci.exchange_rate if ci and ci.exchange_rate else 1.0)
    dest_currency = ci.dest_currency if ci else "USD"
    dest_rate = (ci.dest_rate if ci and ci.dest_rate else 1.0)

    DEST_SYMBOLS = {
        "USD":"$","EUR":"€","GBP":"£","INR":"₹","JPY":"¥",
        "CAD":"CA$","AUD":"A$","CNY":"¥","SGD":"S$","AED":"د.إ",
        "CHF":"Fr","MXN":"MX$","BRL":"R$","THB":"฿","KRW":"₩",
        "HKD":"HK$","MYR":"RM","IDR":"Rp","VND":"₫","PHP":"₱",
        "NZD":"NZ$","ZAR":"R","EGP":"E£","TRY":"₺","MAD":"MAD",
    }
    dsym = DEST_SYMBOLS.get(dest_currency, dest_currency + " ")

    def to_user(usd: float) -> str:
        """Convert USD → user currency, formatted."""
        val = usd / user_rate
        return f"{symbol}{val:,.0f}"

    def to_dest(usd: float) -> str:
        """Convert USD → destination currency, formatted."""
        val = usd / dest_rate
        return f"{dsym}{val:,.0f}"

    if not itinerary:
        st.error("No itinerary was generated. Please try again.")
        st.stop()

    st.markdown(f"## 🌍 Your Itinerary for {destination}")

    if itinerary.destination_highlights:
        st.markdown(f'<div class="highlights">{itinerary.destination_highlights}</div>', unsafe_allow_html=True)

    # Total cost box — shows BOTH user currency AND destination currency
    if budget_stat:
        badge = '<span class="bpass">✓ Within Budget</span>' if not budget_stat.is_over_budget else '<span class="bwarn">⚠ Over Budget</span>'
        total_user = to_user(budget_stat.total_cost_usd)
        total_dest = to_dest(budget_stat.total_cost_usd)
        budget_user = to_user(prefs.budget_usd if prefs else budget_stat.total_cost_usd)
        dest_label = f" / {total_dest} {dest_currency}" if dest_currency != user_currency else ""
        st.markdown(f"""
        <div class="budget-box">
          <div style="font-size:.82rem;color:#94a3b8;margin-bottom:3px">TOTAL ESTIMATED COST</div>
          <div class="budget-total">{total_user} {user_currency}
            <span style="font-size:.95rem;color:#94a3b8">{dest_label}</span>
          </div>
          <div style="font-size:.8rem;color:#64748b;margin-top:4px">Budget: {budget_user} {user_currency}</div>
          {badge}
        </div>""", unsafe_allow_html=True)

    for day in itinerary.days:
        dc = next((x for x in (budget_stat.day_costs if budget_stat else []) if x["day"] == day.day), {})
        w  = weather.get(day.date, {})
        wx_label = ""
        if w:
            wx_label = f"🌦 {w.get('description','')}, {w.get('temp_min','')}–{w.get('temp_max','')}°C, rain {w.get('rain_mm',0)}mm"

        st.markdown(f"""
        <div class="day-card">
          <div style="display:flex;align-items:center;gap:1rem;margin-bottom:.8rem;">
            <div class="day-badge">{day.day}</div>
            <div>
              <div class="day-title">Day {day.day} — {day.accommodation_name}</div>
              <div class="day-date">📅 {day.date}</div>
            </div>
          </div>
          {"<div class='weather-badge'>" + wx_label + "</div>" if wx_label else ""}
          <div class="day-summary">✦ {day.day_summary}</div>
        """, unsafe_allow_html=True)

        for act in day.activities:
            tag = '<span class="tag t-out">🌿 Outdoors</span>' if act.is_outdoors else '<span class="tag t-in">🏛 Indoors</span>'
            cost_str = to_user(act.estimated_cost_usd)
            st.markdown(f"""
            <div class="act-row">
              <div class="act-time">🕐 {act.time_start}–{act.time_end}</div>
              <div class="act-body">
                <div class="act-name">{act.name}</div>
                <div class="act-desc">{act.description}</div>
                <div class="act-tip">💡 {act.tips}</div>
                <div class="act-tags">
                  {tag}
                  <span class="tag t-cost">{cost_str}</span>
                </div>
              </div>
            </div>""", unsafe_allow_html=True)

        acc  = dc.get("accommodation", day.accommodation_cost_usd)
        food = dc.get("food", day.food_cost_usd)
        acts = dc.get("activities", sum(a.estimated_cost_usd for a in day.activities))
        tot  = dc.get("total", acc + food + acts)

        st.markdown(f"""
          <div class="cost-bar">
            <div class="chip">🏨 Hotel <span>${acc:.0f}</span></div>
            <div class="chip">🍽 Food <span>${food:.0f}</span></div>
            <div class="chip">🎭 Activities <span>${acts:.0f}</span></div>
            <div class="chip">📊 Day Total <span>${tot:.0f}</span></div>
          </div>
        </div>""", unsafe_allow_html=True)

    st.balloons()
