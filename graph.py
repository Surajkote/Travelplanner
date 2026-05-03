import os
import re
import time
import requests
from datetime import datetime, timedelta
from typing import List, Optional
from typing_extensions import TypedDict
from pydantic import BaseModel, Field
from langchain_groq import ChatGroq
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import StateGraph, START, END
from dotenv import load_dotenv
from tavily import TavilyClient

load_dotenv()

# ─────────────────────────────────────────────────────────────────────────────
# 1. Pydantic Models
# ─────────────────────────────────────────────────────────────────────────────

class TravelPrefs(BaseModel):
    destination: str
    days: int
    budget_usd: float
    budget_original: float
    user_currency: str
    exchange_rate: float
    interests: List[str]
    start_date: str  # YYYY-MM-DD
    end_date: str    # YYYY-MM-DD

class CurrencyInfo(BaseModel):
    user_currency: str
    exchange_rate: float
    budget_usd: float
    budget_original: float   # ← was missing before

class Activity(BaseModel):
    name: str = Field(description="Name of the activity or place")
    time_start: str = Field(description="Start time HH:MM")
    time_end: str = Field(description="End time HH:MM")
    time_allocated_minutes: int
    estimated_cost_usd: float
    location_query: str = Field(description="Specific searchable place, e.g. 'Eiffel Tower, Paris'")
    is_outdoors: bool
    description: str
    tips: str

class DayItinerary(BaseModel):
    day: int
    date: str  # YYYY-MM-DD
    accommodation_name: str
    accommodation_cost_usd: float
    food_cost_usd: float
    activities: List[Activity]
    day_summary: str
    weather_note: str = Field(default="", description="Weather note for the day")

class Itinerary(BaseModel):
    days: List[DayItinerary]
    destination_highlights: str

class BudgetReport(BaseModel):
    total_cost_usd: float
    is_over_budget: bool
    itemized_overages: List[str]
    day_costs: List[dict]

class Violation(BaseModel):
    day: int
    issue: str

class TravelPlannerState(TypedDict):
    raw_input: str
    user_prefs: Optional[TravelPrefs]
    currency_info: Optional[CurrencyInfo]
    destination_data: Optional[dict]   # Wikivoyage + Numbeo data
    weather_data: Optional[dict]       # Open-Meteo per-day forecast
    current_itinerary: Optional[Itinerary]
    budget_status: Optional[BudgetReport]
    constraint_violations: List[Violation]
    iteration: int
    all_validators_passed: bool

# ─────────────────────────────────────────────────────────────────────────────
# 2. API Helpers
# ─────────────────────────────────────────────────────────────────────────────

HEADERS = {"User-Agent": "TripSmithApp/1.0 (travel planner project)"}

def get_llm():
    return ChatGroq(model="llama-3.3-70b-versatile", temperature=0.2,
                    api_key=os.environ["GROQ_API_KEY"])

def get_tavily():
    return TavilyClient(api_key=os.environ["TAVILY_API_KEY"])

# ── Currency ──────────────────────────────────────────────────────────────────
def fetch_exchange_rate(user_currency: str) -> float:
    if user_currency.upper() == "USD":
        return 1.0
    fallbacks = {
        "INR": 0.012, "EUR": 1.08, "GBP": 1.27, "JPY": 0.0067,
        "CAD": 0.73, "AUD": 0.65, "CNY": 0.138, "SGD": 0.74,
        "AED": 0.27, "CHF": 1.12, "MXN": 0.058, "BRL": 0.19,
    }
    try:
        tavily = get_tavily()
        query = f"1 {user_currency} to USD exchange rate today"
        results = tavily.search(query=query, max_results=3)
        for r in results.get("results", []):
            text = r.get("content", "") + " " + r.get("title", "")
            # Pattern: "1 INR = 0.012 USD" or standalone "0.0120"
            matches = re.findall(
                r"(?:1\s*" + re.escape(user_currency) + r"\s*[=:]\s*)?([\d.]+)\s*USD",
                text, re.IGNORECASE
            )
            for m in matches:
                val = float(m)
                if 0.00001 < val < 10000:
                    return val
    except Exception:
        pass
    return fallbacks.get(user_currency.upper(), 1.0)

# ── Geocoding via Nominatim ───────────────────────────────────────────────────
def geocode(location: str) -> tuple[float, float]:
    """Returns (lon, lat) using OpenStreetMap Nominatim."""
    try:
        url = (
            "https://nominatim.openstreetmap.org/search"
            f"?q={requests.utils.quote(location)}&format=json&limit=1"
        )
        r = requests.get(url, headers=HEADERS, timeout=7)
        data = r.json()
        if data:
            return float(data[0]["lon"]), float(data[0]["lat"])
    except Exception:
        pass
    return None, None

# ── Transit via OSRM ──────────────────────────────────────────────────────────
def osrm_transit_minutes(lon1, lat1, lon2, lat2) -> float:
    """Returns driving time in minutes via public OSRM API."""
    try:
        url = (
            f"http://router.project-osrm.org/route/v1/driving/"
            f"{lon1},{lat1};{lon2},{lat2}?overview=false"
        )
        r = requests.get(url, timeout=8)
        data = r.json()
        if data.get("routes"):
            return data["routes"][0]["duration"] / 60.0
    except Exception:
        pass
    return 0.0

# ── Weather via Open-Meteo ────────────────────────────────────────────────────
def fetch_weather(lat: float, lon: float, start_date: str, end_date: str) -> dict:
    """
    Fetches daily forecast from Open-Meteo for actual trip dates.
    Returns dict keyed by date string → {description, rain_mm, temp_max, temp_min}.
    """
    try:
        url = (
            "https://api.open-meteo.com/v1/forecast"
            f"?latitude={lat}&longitude={lon}"
            f"&daily=temperature_2m_max,temperature_2m_min,precipitation_sum,weathercode"
            f"&timezone=auto&start_date={start_date}&end_date={end_date}"
        )
        r = requests.get(url, timeout=8)
        data = r.json()
        daily = data.get("daily", {})
        dates = daily.get("time", [])
        result = {}
        wmo_desc = {
            0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
            45: "Fog", 51: "Light drizzle", 53: "Moderate drizzle", 61: "Light rain",
            63: "Moderate rain", 65: "Heavy rain", 71: "Light snow", 80: "Rain showers",
            95: "Thunderstorm",
        }
        for i, d in enumerate(dates):
            code = daily.get("weathercode", [0])[i] if i < len(daily.get("weathercode", [])) else 0
            result[d] = {
                "description": wmo_desc.get(code, f"Code {code}"),
                "rain_mm": daily.get("precipitation_sum", [0])[i] or 0,
                "temp_max": daily.get("temperature_2m_max", [0])[i] or 0,
                "temp_min": daily.get("temperature_2m_min", [0])[i] or 0,
                "weathercode": code,
            }
        return result
    except Exception:
        return {}

# ── Wikivoyage scrape ─────────────────────────────────────────────────────────
def fetch_wikivoyage(destination: str) -> str:
    """Scrape destination overview from Wikivoyage (plain text via API)."""
    try:
        city = destination.split(",")[0].strip().replace(" ", "_")
        url = (
            "https://en.wikivoyage.org/w/api.php"
            f"?action=query&titles={requests.utils.quote(city)}"
            "&prop=extracts&exintro=true&explaintext=true&format=json"
        )
        r = requests.get(url, headers=HEADERS, timeout=8)
        data = r.json()
        pages = data.get("query", {}).get("pages", {})
        for page in pages.values():
            extract = page.get("extract", "")
            if extract and len(extract) > 50:
                return extract[:2000]  # cap at 2000 chars
    except Exception:
        pass
    return ""

# ── Numbeo cost of living ─────────────────────────────────────────────────────
def fetch_numbeo_costs(destination: str) -> dict:
    """
    Scrape Numbeo cost-of-living page for the destination city.
    Returns dict with meal, hotel, transport estimates in USD.
    """
    try:
        city = destination.split(",")[0].strip().replace(" ", "+")
        url = f"https://www.numbeo.com/cost-of-living/in/{city}"
        r = requests.get(url, headers={**HEADERS, "Accept-Language": "en-US"}, timeout=8)
        html = r.text

        def extract_price(pattern):
            m = re.search(pattern, html)
            if m:
                try:
                    return float(m.group(1).replace(",", ""))
                except Exception:
                    pass
            return None

        meal_cheap = extract_price(r'Meal, Inexpensive Restaurant[^<]*</td>\s*<td[^>]*>\s*\$([\d,.]+)')
        meal_mid   = extract_price(r'Meal for 2 People[^<]*</td>\s*<td[^>]*>\s*\$([\d,.]+)')
        hotel      = extract_price(r'Hotel \(1 night\)[^<]*</td>\s*<td[^>]*>\s*\$([\d,.]+)')
        transport  = extract_price(r'One-way Ticket[^<]*</td>\s*<td[^>]*>\s*\$([\d,.]+)')

        costs = {}
        if meal_cheap: costs["meal_cheap_usd"] = meal_cheap
        if meal_mid:   costs["meal_for2_usd"]  = meal_mid
        if hotel:      costs["hotel_per_night_usd"] = hotel
        if transport:  costs["local_transport_usd"]  = transport

        # Fallback via Tavily if scrape got nothing
        if not costs:
            tavily = get_tavily()
            q = f"average cost of living per day tourist {destination} USD 2024 hotel meal transport"
            res = tavily.search(query=q, max_results=2)
            summary = " ".join(r.get("content", "") for r in res.get("results", []))
            costs["tavily_summary"] = summary[:500]

        return costs
    except Exception as e:
        return {"error": str(e)}

# ─────────────────────────────────────────────────────────────────────────────
# 3. Graph Nodes
# ─────────────────────────────────────────────────────────────────────────────

# Node 1 — currency_resolver
def currency_resolver(state: TravelPlannerState) -> dict:
    ci = state.get("currency_info")
    if not ci:
        return {}
    rate = fetch_exchange_rate(ci.user_currency)
    budget_usd = ci.budget_original * rate
    return {
        "currency_info": CurrencyInfo(
            user_currency=ci.user_currency,
            exchange_rate=rate,
            budget_usd=round(budget_usd, 2),
            budget_original=ci.budget_original,
        )
    }

# Node 2 — input_parser
def input_parser(state: TravelPlannerState) -> dict:
    llm = get_llm()
    structured_llm = llm.with_structured_output(TravelPrefs)
    ci = state.get("currency_info")
    budget_usd     = ci.budget_usd if ci else 1500.0
    budget_original= ci.budget_original if ci else budget_usd
    user_currency  = ci.user_currency if ci else "USD"
    exchange_rate  = ci.exchange_rate if ci else 1.0

    prompt = f"""
Extract structured trip details from the input below.

Input: {state['raw_input']}

Set:
- budget_usd = {budget_usd}
- budget_original = {budget_original}
- user_currency = "{user_currency}"
- exchange_rate = {exchange_rate}
- days = inclusive count of days from start_date to end_date
- start_date and end_date must be YYYY-MM-DD strings
"""
    prefs = structured_llm.invoke([HumanMessage(content=prompt)])
    return {
        "user_prefs": prefs,
        "iteration": 0,
        "constraint_violations": [],
        "budget_status": None,
        "current_itinerary": None,
        "all_validators_passed": False,
    }

# Node 3 — destination_researcher (Wikivoyage + Numbeo)
def destination_researcher(state: TravelPlannerState) -> dict:
    dest = state["user_prefs"].destination
    wiki = fetch_wikivoyage(dest)
    numbeo = fetch_numbeo_costs(dest)
    return {
        "destination_data": {
            "wikivoyage": wiki,
            "numbeo": numbeo,
        }
    }

# Node 4 — weather_fetcher (Open-Meteo with actual trip dates)
def weather_fetcher(state: TravelPlannerState) -> dict:
    prefs = state["user_prefs"]
    lon, lat = geocode(prefs.destination)
    if lon is None:
        return {"weather_data": {}}
    forecast = fetch_weather(lat, lon, prefs.start_date, prefs.end_date)
    return {"weather_data": forecast}

# Node 5 — planner (LLM uses all real data to draft itinerary)
def planner(state: TravelPlannerState) -> dict:
    llm = get_llm()
    structured_llm = llm.with_structured_output(Itinerary)
    prefs     = state["user_prefs"]
    iteration = state["iteration"]
    dest_data = state.get("destination_data") or {}
    weather   = state.get("weather_data") or {}

    wiki_text   = dest_data.get("wikivoyage", "")[:1000]
    numbeo_data = dest_data.get("numbeo", {})
    numbeo_text = str(numbeo_data)[:500]

    weather_lines = []
    for d, w in weather.items():
        weather_lines.append(
            f"  {d}: {w['description']}, rain={w['rain_mm']}mm, "
            f"max={w['temp_max']}°C, min={w['temp_min']}°C"
        )
    weather_text = "\n".join(weather_lines) if weather_lines else "No forecast available."

    system_msg = (
        "You are a world-class travel itinerary planner. "
        "Use the provided real destination data, cost estimates, and weather forecast strictly. "
        "All costs must be in USD. Plan days starting from 08:00."
    )
    user_msg = f"""
Create a {prefs.days}-day itinerary for {prefs.destination}.
Trip: {prefs.start_date} → {prefs.end_date}
Total budget: ${prefs.budget_usd:.2f} USD

=== DESTINATION OVERVIEW (Wikivoyage) ===
{wiki_text}

=== COST OF LIVING (Numbeo) ===
{numbeo_text}

=== WEATHER FORECAST FOR TRIP DATES (Open-Meteo) ===
{weather_text}

Rules:
- Keep TOTAL cost under ${prefs.budget_usd:.2f}
- 3-4 activities per day with realistic HH:MM start/end times
- Match each day's date to the actual calendar date starting {prefs.start_date}
- Use Numbeo cost data for realistic accommodation/food estimates
- If rain > 10mm, prefer indoor activities on that day
- Add a weather_note per day from the forecast above
- Interests to focus on: {', '.join(prefs.interests)}
"""
    if iteration > 0:
        b_issues = "\n".join((state["budget_status"].itemized_overages if state.get("budget_status") else []))
        v_issues = "\n".join(f"Day {v.day}: {v.issue}" for v in state.get("constraint_violations", []))
        user_msg += f"\n\n⚠️ REVISE — fix these violations from the last attempt:\n"
        if b_issues: user_msg += f"BUDGET:\n{b_issues}\n"
        if v_issues: user_msg += f"CONSTRAINTS:\n{v_issues}\n"
        system_msg += " Be very precise in reducing costs and fixing timing conflicts."

    itinerary = structured_llm.invoke([SystemMessage(content=system_msg), HumanMessage(content=user_msg)])
    return {"current_itinerary": itinerary, "iteration": iteration + 1}

# Node 6 — budget_validator (deterministic)
def budget_validator(state: TravelPlannerState) -> dict:
    itinerary = state["current_itinerary"]
    prefs     = state["user_prefs"]
    total     = 0.0
    overages  = []
    day_costs = []
    daily_budget = prefs.budget_usd / prefs.days

    for day in itinerary.days:
        act_cost = sum(a.estimated_cost_usd for a in day.activities)
        day_total = day.accommodation_cost_usd + day.food_cost_usd + act_cost
        total += day_total
        day_costs.append({
            "day": day.day, "date": day.date,
            "accommodation": day.accommodation_cost_usd,
            "food": day.food_cost_usd,
            "activities": act_cost,
            "total": day_total,
        })
        if day_total > daily_budget * 1.4:
            overages.append(
                f"Day {day.day} costs ${day_total:.2f} vs daily budget ${daily_budget:.2f}. "
                f"Hotel=${day.accommodation_cost_usd:.2f}, Food=${day.food_cost_usd:.2f}, "
                f"Activities=${act_cost:.2f}. Reduce costs."
            )

    is_over = total > prefs.budget_usd
    if is_over:
        overages.insert(0,
            f"Total ${total:.2f} exceeds budget ${prefs.budget_usd:.2f} "
            f"(over by ${total - prefs.budget_usd:.2f}). Cut accommodation or activities."
        )
    return {
        "budget_status": BudgetReport(
            total_cost_usd=total,
            is_over_budget=is_over,
            itemized_overages=overages,
            day_costs=day_costs,
        )
    }

# Node 7 — constraint_checker (OSRM + Open-Meteo weather from state)
def constraint_checker(state: TravelPlannerState) -> dict:
    itinerary = state["current_itinerary"]
    weather   = state.get("weather_data") or {}
    violations = []

    for day in itinerary.days:
        # Weather check using already-fetched Open-Meteo data
        w = weather.get(day.date, {})
        rain_mm = w.get("rain_mm", 0)
        if rain_mm > 10:
            for act in day.activities:
                if act.is_outdoors:
                    violations.append(Violation(
                        day=day.day,
                        issue=f"'{act.name}' is outdoors but {rain_mm}mm rain forecast on {day.date}. Swap for indoor activity."
                    ))

        # Transit check using Nominatim geocoding + OSRM routing
        for i in range(len(day.activities) - 1):
            act1 = day.activities[i]
            act2 = day.activities[i + 1]
            try:
                lon1, lat1 = geocode(act1.location_query)
                time.sleep(1.1)  # Nominatim rate limit (1 req/sec)
                lon2, lat2 = geocode(act2.location_query)

                if lon1 is None or lon2 is None:
                    continue

                transit = osrm_transit_minutes(lon1, lat1, lon2, lat2)

                if transit > act1.time_allocated_minutes:
                    violations.append(Violation(
                        day=day.day,
                        issue=(
                            f"OSRM: Transit from '{act1.name}' → '{act2.name}' = {transit:.0f} min "
                            f"but only {act1.time_allocated_minutes} min allocated. Increase gap or pick closer venues."
                        )
                    ))
                elif transit > 90:
                    violations.append(Violation(
                        day=day.day,
                        issue=f"OSRM: Transit from '{act1.name}' → '{act2.name}' = {transit:.0f} min. Too long for a day trip."
                    ))
            except Exception:
                continue

    return {"constraint_violations": violations}

# Node 8 — decision_gate (conditional edge function)
def decision_gate(state: TravelPlannerState) -> str:
    budget_ok = not state["budget_status"].is_over_budget
    transit_ok = len(state["constraint_violations"]) == 0
    if (budget_ok and transit_ok) or state["iteration"] >= 3:
        return "formatter"
    return "planner"

# Node 9 — formatter
def formatter(state: TravelPlannerState) -> dict:
    b_ok = not state["budget_status"].is_over_budget
    v_ok = len(state["constraint_violations"]) == 0
    return {"all_validators_passed": b_ok and v_ok}

# ─────────────────────────────────────────────────────────────────────────────
# 4. Graph Compilation
# ─────────────────────────────────────────────────────────────────────────────

def build_graph():
    wf = StateGraph(TravelPlannerState)

    wf.add_node("currency_resolver",    currency_resolver)
    wf.add_node("input_parser",         input_parser)
    wf.add_node("destination_researcher", destination_researcher)
    wf.add_node("weather_fetcher",      weather_fetcher)
    wf.add_node("planner",              planner)
    wf.add_node("budget_validator",     budget_validator)
    wf.add_node("constraint_checker",   constraint_checker)
    wf.add_node("formatter",            formatter)

    def aggregator(state): return {}
    wf.add_node("aggregator", aggregator)

    # Linear setup phase
    wf.add_edge(START,                "currency_resolver")
    wf.add_edge("currency_resolver",  "input_parser")
    wf.add_edge("input_parser",       "destination_researcher")
    wf.add_edge("destination_researcher", "weather_fetcher")
    wf.add_edge("weather_fetcher",    "planner")

    # Parallel validation
    wf.add_edge("planner",            "budget_validator")
    wf.add_edge("planner",            "constraint_checker")
    wf.add_edge("budget_validator",   "aggregator")
    wf.add_edge("constraint_checker", "aggregator")

    # Reflection gate
    wf.add_conditional_edges("aggregator", decision_gate,
                              {"formatter": "formatter", "planner": "planner"})
    wf.add_edge("formatter", END)

    return wf.compile()

# ─────────────────────────────────────────────────────────────────────────────
# 5. Architecture diagram helper
# ─────────────────────────────────────────────────────────────────────────────

def save_graph_image(output_path="architecture.png"):
    try:
        png = build_graph().get_graph().draw_mermaid_png()
        with open(output_path, "wb") as f:
            f.write(png)
        print(f"Saved to {output_path}")
    except Exception as e:
        print(f"Failed: {e}")

if __name__ == "__main__":
    save_graph_image()
