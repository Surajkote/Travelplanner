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

# ── Custom CSS ────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&family=Playfair+Display:wght@700&display=swap');

*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

html, body, [data-testid="stAppViewContainer"] {
    background: linear-gradient(135deg, #0f0c29 0%, #1a1a2e 40%, #16213e 100%) !important;
    font-family: 'Inter', sans-serif;
    color: #e8e8f0;
}

[data-testid="stHeader"] { background: transparent !important; }

.hero-section {
    text-align: center;
    padding: 3rem 1rem 2rem;
}
.hero-title {
    font-family: 'Playfair Display', serif;
    font-size: clamp(2.4rem, 6vw, 4.2rem);
    background: linear-gradient(135deg, #f8cdda, #1d8fe1, #a78bfa);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    margin-bottom: 0.5rem;
}
.hero-sub {
    font-size: 1.1rem;
    color: #94a3b8;
    margin-bottom: 2.5rem;
}

.card {
    background: rgba(255,255,255,0.05);
    border: 1px solid rgba(255,255,255,0.1);
    border-radius: 20px;
    padding: 2rem;
    margin-bottom: 1.5rem;
    backdrop-filter: blur(12px);
}
.section-label {
    font-size: 0.75rem;
    font-weight: 700;
    letter-spacing: 2px;
    text-transform: uppercase;
    color: #a78bfa;
    margin-bottom: 1rem;
}

.stTextInput > div > div > input,
.stNumberInput > div > div > input,
.stDateInput > div > div > input {
    background: rgba(255,255,255,0.07) !important;
    border: 1px solid rgba(167,139,250,0.3) !important;
    border-radius: 12px !important;
    color: #e8e8f0 !important;
    font-family: 'Inter', sans-serif !important;
}
.stMultiSelect > div { border-radius: 12px !important; }

div[data-testid="stButton"] > button {
    width: 100%;
    padding: 1rem 2rem;
    background: linear-gradient(135deg, #6366f1, #8b5cf6, #a78bfa);
    color: white;
    border: none;
    border-radius: 14px;
    font-size: 1.1rem;
    font-weight: 700;
    font-family: 'Inter', sans-serif;
    cursor: pointer;
    transition: all 0.3s ease;
    letter-spacing: 0.5px;
    margin-top: 1rem;
}
div[data-testid="stButton"] > button:hover {
    transform: translateY(-2px);
    box-shadow: 0 10px 30px rgba(99,102,241,0.5);
}

.day-card {
    background: linear-gradient(135deg, rgba(99,102,241,0.12), rgba(139,92,246,0.08));
    border: 1px solid rgba(167,139,250,0.25);
    border-radius: 20px;
    padding: 1.8rem;
    margin-bottom: 1.5rem;
}
.day-header {
    display: flex;
    align-items: center;
    gap: 1rem;
    margin-bottom: 1.2rem;
}
.day-badge {
    background: linear-gradient(135deg, #6366f1, #8b5cf6);
    color: white;
    border-radius: 50%;
    width: 52px;
    height: 52px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 1.3rem;
    font-weight: 800;
    flex-shrink: 0;
}
.day-title { font-size: 1.2rem; font-weight: 700; color: #e8e8f0; }
.day-date { font-size: 0.85rem; color: #94a3b8; margin-top: 2px; }
.day-summary { font-size: 0.9rem; color: #a78bfa; font-style: italic; margin-bottom: 1.2rem; }

.activity-row {
    display: flex;
    gap: 1rem;
    align-items: flex-start;
    background: rgba(255,255,255,0.04);
    border-radius: 14px;
    padding: 1rem 1.2rem;
    margin-bottom: 0.8rem;
    border-left: 3px solid #6366f1;
}
.activity-time {
    font-size: 0.78rem;
    font-weight: 700;
    color: #a78bfa;
    white-space: nowrap;
    padding-top: 2px;
    min-width: 110px;
}
.activity-body { flex: 1; }
.activity-name { font-size: 1rem; font-weight: 600; color: #e8e8f0; margin-bottom: 3px; }
.activity-desc { font-size: 0.85rem; color: #94a3b8; margin-bottom: 5px; }
.activity-tip {
    font-size: 0.8rem;
    color: #fbbf24;
    background: rgba(251,191,36,0.08);
    border-radius: 8px;
    padding: 4px 8px;
    margin-bottom: 5px;
}
.activity-tags { display: flex; gap: 6px; flex-wrap: wrap; }
.tag {
    font-size: 0.72rem;
    font-weight: 600;
    padding: 3px 10px;
    border-radius: 20px;
}
.tag-outdoor { background: rgba(52,211,153,0.15); color: #34d399; }
.tag-indoor  { background: rgba(96,165,250,0.15); color: #60a5fa; }
.tag-cost    { background: rgba(167,139,250,0.15); color: #a78bfa; }

.cost-bar {
    display: flex;
    gap: 1rem;
    margin-top: 1.2rem;
    flex-wrap: wrap;
}
.cost-chip {
    background: rgba(255,255,255,0.06);
    border: 1px solid rgba(255,255,255,0.1);
    border-radius: 10px;
    padding: 6px 14px;
    font-size: 0.82rem;
    color: #94a3b8;
}
.cost-chip span { color: #e8e8f0; font-weight: 700; }

.budget-summary {
    background: linear-gradient(135deg, rgba(99,102,241,0.2), rgba(168,85,247,0.15));
    border: 1px solid rgba(167,139,250,0.4);
    border-radius: 18px;
    padding: 1.5rem 2rem;
    margin-bottom: 2rem;
    text-align: center;
}
.budget-total { font-size: 2rem; font-weight: 800; color: #a78bfa; }
.badge-pass {
    display: inline-block;
    background: rgba(52,211,153,0.2);
    color: #34d399;
    border: 1px solid #34d399;
    border-radius: 20px;
    padding: 4px 16px;
    font-size: 0.85rem;
    font-weight: 700;
    margin-top: 6px;
}
.badge-warn {
    display: inline-block;
    background: rgba(251,191,36,0.2);
    color: #fbbf24;
    border: 1px solid #fbbf24;
    border-radius: 20px;
    padding: 4px 16px;
    font-size: 0.85rem;
    font-weight: 700;
    margin-top: 6px;
}
.highlights-box {
    background: rgba(255,255,255,0.04);
    border-left: 4px solid #6366f1;
    border-radius: 0 14px 14px 0;
    padding: 1rem 1.4rem;
    margin-bottom: 2rem;
    font-size: 0.95rem;
    color: #cbd5e1;
    line-height: 1.7;
}

.iteration-log {
    font-family: 'Inter', sans-serif;
    font-size: 0.88rem;
}
</style>
""", unsafe_allow_html=True)


# ── Location detection ────────────────────────────────────────────────────────
@st.cache_data(show_spinner=False)
def detect_user_location():
    """Detect country + currency using ip-api.com (free, no key needed)."""
    try:
        r = requests.get("http://ip-api.com/json/?fields=country,currency", timeout=5)
        data = r.json()
        return data.get("country", "United States"), data.get("currency", "USD")
    except Exception:
        return "United States", "USD"

user_country, user_currency = detect_user_location()

CURRENCY_SYMBOLS = {
    "USD": "$", "EUR": "€", "GBP": "£", "INR": "₹", "JPY": "¥",
    "CAD": "CA$", "AUD": "A$", "CNY": "¥", "SGD": "S$", "AED": "د.إ",
    "CHF": "Fr", "MXN": "MX$",
}
symbol = CURRENCY_SYMBOLS.get(user_currency, user_currency + " ")

# ── Interests list ─────────────────────────────────────────────────────────────
INTERESTS = [
    "Art & Museums", "Food & Cuisine", "History & Heritage", "Nature & Hiking",
    "Nightlife & Bars", "Shopping & Markets", "Architecture", "Photography",
    "Music & Concerts", "Sports & Adventure", "Wellness & Spa", "Beach & Water Sports",
    "Gaming & Esports", "Street Food", "Wine & Cocktails", "Theatre & Performing Arts",
    "Cycling", "Volunteering & Culture", "Religious & Spiritual Sites",
    "Theme Parks & Rides", "Local Festivals", "Cooking Classes",
]

# ── Hero ──────────────────────────────────────────────────────────────────────
st.markdown("""
<div class="hero-section">
  <div class="hero-title">✈️ TripSmith</div>
  <div class="hero-sub">AI-powered travel planning with real-world validation. Every itinerary actually works.</div>
</div>
""", unsafe_allow_html=True)

# ── Input Form ────────────────────────────────────────────────────────────────
st.markdown('<div class="card">', unsafe_allow_html=True)
st.markdown('<p class="section-label">🗺 Plan Your Trip</p>', unsafe_allow_html=True)

col1, col2 = st.columns([2, 1])
with col1:
    destination = st.text_input("Destination City / Country", value="Paris, France", placeholder="e.g. Tokyo, Japan")
with col2:
    st.markdown(f"📍 Detected location: **{user_country}** &nbsp; 💱 Currency: **{user_currency}**", unsafe_allow_html=True)
    budget = st.number_input(
        f"Budget ({user_currency})",
        min_value=100,
        max_value=10_000_000,
        value=100_000 if user_currency == "INR" else 1500,
        step=500,
    )

col3, col4 = st.columns(2)
today = date.today()
with col3:
    start_date = st.date_input("Start Date", value=today + timedelta(days=7), min_value=today)
with col4:
    end_date = st.date_input("End Date", value=today + timedelta(days=11), min_value=start_date)

if end_date < start_date:
    st.error("End date must be on or after start date.")
    st.stop()

num_days = (end_date - start_date).days + 1
st.info(f"🗓️ Trip duration: **{num_days} day{'s' if num_days != 1 else ''}** (inclusive, full days)")

# Interests
selected_interests = st.multiselect(
    "Interests (choose any or type your own)",
    options=INTERESTS,
    default=["Art & Museums", "Food & Cuisine"],
    placeholder="Select interests or type a custom one...",
)
custom_interest = st.text_input("Add custom interest (optional)", placeholder="e.g. Manga, Rock Climbing")
if custom_interest.strip():
    selected_interests.append(custom_interest.strip())

generate_btn = st.button("✨ Generate My Itinerary")
st.markdown('</div>', unsafe_allow_html=True)

# ── Run the Agent ─────────────────────────────────────────────────────────────
if generate_btn:
    if not selected_interests:
        st.warning("Please select at least one interest.")
        st.stop()

    raw_input = (
        f"Trip to {destination} from {start_date} to {end_date} ({num_days} days). "
        f"Budget: {budget} {user_currency}. "
        f"Interests: {', '.join(selected_interests)}."
    )

    app = build_graph()

    initial_state = {
        "raw_input": raw_input,
        "iteration": 0,
        "constraint_violations": [],
        "currency_info": CurrencyInfo(
            user_currency=user_currency,
            exchange_rate=0.0,   # resolver will fill this
            budget_usd=0.0,
            budget_original=float(budget),
        ),
    }

    final_state = {}

    with st.status("🧠 TripSmith Agent Running...", expanded=True) as status:
        st.markdown('<div class="iteration-log">', unsafe_allow_html=True)
        for event in app.stream(initial_state, stream_mode="updates"):
            for node_name, node_state in event.items():
                if isinstance(node_state, dict):
                    final_state.update(node_state)

                if node_name == "currency_resolver":
                    ci = final_state.get("currency_info")
                    if ci and ci.exchange_rate:
                        st.write(f"💱 Exchange rate: 1 {user_currency} = {ci.exchange_rate:.4f} USD → Budget = **${ci.budget_usd:,.2f} USD**")

                elif node_name == "input_parser":
                    prefs = final_state.get("user_prefs")
                    if prefs:
                        st.write(f"✅ Parsed: **{prefs.destination}**, {prefs.days} days, budget **${prefs.budget_usd:,.2f} USD**")

                elif node_name == "planner":
                    it = final_state.get("iteration", 1)
                    st.write(f"🔄 Iteration **{it}**: Drafting itinerary...")

                elif node_name == "aggregator":
                    b = final_state.get("budget_status")
                    v = final_state.get("constraint_violations", [])
                    if b and b.is_over_budget:
                        st.warning(f"💸 Over budget by **${b.total_cost_usd - (final_state.get('user_prefs').budget_usd if final_state.get('user_prefs') else 0):.2f}**. Replanning...")
                        for ov in b.itemized_overages[:3]:
                            st.write(f"  › {ov}")
                    if v:
                        st.warning(f"🛑 {len(v)} constraint violation(s) found. Replanning...")
                        for vv in v[:3]:
                            st.write(f"  › Day {vv.day}: {vv.issue}")
                    if (not b or not b.is_over_budget) and not v:
                        st.success("✅ All validators passed!")

                elif node_name == "formatter":
                    st.write("✨ Finalising itinerary...")
        st.markdown('</div>', unsafe_allow_html=True)

        passed = final_state.get("all_validators_passed", False)
        status.update(
            label="✅ Itinerary Ready!" if passed else "⚠️ Best itinerary generated (some constraints remain)",
            state="complete",
            expanded=False,
        )

    # ── Display Results ───────────────────────────────────────────────────────
    itinerary = final_state.get("current_itinerary")
    budget_stat = final_state.get("budget_status")
    prefs = final_state.get("user_prefs")

    if not itinerary:
        st.error("No itinerary was generated. Please try again.")
        st.stop()

    # Destination header
    st.markdown(f"## 🌍 Your Itinerary for {destination}")

    if itinerary.destination_highlights:
        st.markdown(f'<div class="highlights-box">{itinerary.destination_highlights}</div>', unsafe_allow_html=True)

    # Budget summary
    if budget_stat:
        badge = '<span class="badge-pass">✓ Within Budget</span>' if not budget_stat.is_over_budget else '<span class="badge-warn">⚠ Over Budget</span>'
        orig_total = budget_stat.total_cost_usd / (prefs.exchange_rate if prefs and prefs.exchange_rate else 1)
        st.markdown(f"""
        <div class="budget-summary">
            <div style="font-size:0.85rem;color:#94a3b8;margin-bottom:4px">TOTAL ESTIMATED COST</div>
            <div class="budget-total">${budget_stat.total_cost_usd:,.2f} USD
                <span style="font-size:1rem;color:#94a3b8"> / {symbol}{orig_total:,.0f} {user_currency}</span>
            </div>
            {badge}
        </div>
        """, unsafe_allow_html=True)

    # Day cards
    for day in itinerary.days:
        day_cost_info = {}
        if budget_stat:
            for dc in budget_stat.day_costs:
                if dc["day"] == day.day:
                    day_cost_info = dc
                    break

        st.markdown(f"""
        <div class="day-card">
          <div class="day-header">
            <div class="day-badge">{day.day}</div>
            <div>
              <div class="day-title">Day {day.day} — {day.accommodation_name}</div>
              <div class="day-date">📅 {day.date}</div>
            </div>
          </div>
          <div class="day-summary">✦ {day.day_summary}</div>
        """, unsafe_allow_html=True)

        for act in day.activities:
            outdoor_tag = '<span class="tag tag-outdoor">🌿 Outdoors</span>' if act.is_outdoors else '<span class="tag tag-indoor">🏛 Indoors</span>'
            st.markdown(f"""
            <div class="activity-row">
              <div class="activity-time">🕐 {act.time_start} – {act.time_end}</div>
              <div class="activity-body">
                <div class="activity-name">{act.name}</div>
                <div class="activity-desc">{act.description}</div>
                <div class="activity-tip">💡 {act.tips}</div>
                <div class="activity-tags">
                  {outdoor_tag}
                  <span class="tag tag-cost">💵 ${act.estimated_cost_usd:.0f}</span>
                </div>
              </div>
            </div>
            """, unsafe_allow_html=True)

        acc = day_cost_info.get("accommodation", day.accommodation_cost_usd)
        food = day_cost_info.get("food", day.food_cost_usd)
        acts = day_cost_info.get("activities", sum(a.estimated_cost_usd for a in day.activities))
        total = day_cost_info.get("total", acc + food + acts)

        st.markdown(f"""
          <div class="cost-bar">
            <div class="cost-chip">🏨 Stay <span>${acc:.0f}</span></div>
            <div class="cost-chip">🍽 Food <span>${food:.0f}</span></div>
            <div class="cost-chip">🎭 Activities <span>${acts:.0f}</span></div>
            <div class="cost-chip">📊 Day Total <span>${total:.0f}</span></div>
          </div>
        </div>
        """, unsafe_allow_html=True)

    st.balloons()
