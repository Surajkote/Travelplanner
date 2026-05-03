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
    exchange_rate: float        # how many USD per 1 user_currency unit
    budget_usd: float
    budget_original: float
    dest_currency: str = "USD"  # currency of the destination country
    dest_rate: float = 1.0      # how many USD per 1 dest_currency unit

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
    destination_data: Optional[dict]   # Wikivoyage + Numbeo + specifics
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

# ── Wikivoyage — robust with multiple name attempts + Tavily/Groq fallback ────
COUNTRY_CURRENCY = {
    "fr": "EUR", "de": "EUR", "it": "EUR", "es": "EUR", "pt": "EUR",
    "nl": "EUR", "be": "EUR", "at": "EUR", "gr": "EUR", "fi": "EUR",
    "gb": "GBP", "jp": "JPY", "in": "INR", "us": "USD", "ca": "CAD",
    "au": "AUD", "cn": "CNY", "sg": "SGD", "ae": "AED", "ch": "CHF",
    "mx": "MXN", "br": "BRL", "th": "THB", "id": "IDR", "my": "MYR",
    "vn": "VND", "kr": "KRW", "hk": "HKD", "tw": "TWD", "ph": "PHP",
    "nz": "NZD", "za": "ZAR", "eg": "EGP", "tr": "TRY", "ma": "MAD",
    "np": "NPR", "lk": "LKR", "pk": "PKR", "bd": "BDT",
}

def _wikivoyage_api(city_key: str) -> str:
    url = (
        "https://en.wikivoyage.org/w/api.php"
        f"?action=query&titles={requests.utils.quote(city_key)}"
        "&prop=extracts&exintro=true&explaintext=true&format=json&redirects=1"
    )
    r = requests.get(url, headers=HEADERS, timeout=8)
    pages = r.json().get("query", {}).get("pages", {})
    for page in pages.values():
        extract = page.get("extract", "")
        if extract and len(extract) > 80 and "may refer" not in extract[:80]:
            return extract[:2000]
    return ""

def fetch_wikivoyage(destination: str) -> str:
    """Try multiple name variants then fall back to Tavily + Groq summary."""
    raw = destination.strip()
    city = raw.split(",")[0].strip()
    # Build a set of candidate keys to try
    candidates = [
        city.replace(" ", "_"),
        city.replace(" ", "%20"),
        city.title().replace(" ", "_"),
        city.lower().replace(" ", "_"),
        raw.replace(",", "").replace(" ", "_"),
    ]
    # Also try Wikivoyage search API if direct lookup fails
    for key in dict.fromkeys(candidates):  # deduplicate while preserving order
        try:
            result = _wikivoyage_api(key)
            if result:
                return result
        except Exception:
            continue
    # Search-API fallback
    try:
        search_url = (
            "https://en.wikivoyage.org/w/api.php"
            f"?action=query&list=search&srsearch={requests.utils.quote(city)}"
            "&srnamespace=0&srlimit=3&format=json"
        )
        sr = requests.get(search_url, headers=HEADERS, timeout=8).json()
        hits = sr.get("query", {}).get("search", [])
        for hit in hits:
            title = hit.get("title", "")
            result = _wikivoyage_api(title.replace(" ", "_"))
            if result:
                return result
    except Exception:
        pass
    # Final fallback: Tavily search → Groq summary
    try:
        tavily = get_tavily()
        q = f"travel guide {destination} best attractions food culture tips"
        res = tavily.search(query=q, max_results=3)
        raw_text = " ".join(r.get("content", "") for r in res.get("results", []))[:3000]
        if raw_text.strip():
            llm = get_llm()
            summary = llm.invoke([
                SystemMessage(content="Summarise this travel information into 3 concise paragraphs covering: overview, highlights, practical tips."),
                HumanMessage(content=raw_text),
            ])
            return summary.content[:2000]
    except Exception:
        pass
    return ""

# ── Destination specifics — exact hotel/restaurant/dish names via Tavily ──────
def fetch_destination_specifics(destination: str, interests: list, budget_usd: float) -> dict:
    """Use Tavily to get exact hotel names, famous dishes, best restaurants."""
    try:
        tavily = get_tavily()
        daily = budget_usd / max(1, 7)  # rough daily
        hotel_q = f"best budget hotels in {destination} under {daily:.0f} USD per night names prices 2024"
        food_q  = f"most famous local food dishes must-eat restaurants {destination} names"
        h_res = tavily.search(query=hotel_q, max_results=3)
        f_res = tavily.search(query=food_q,  max_results=3)
        hotel_text = " | ".join(r.get("content", "")[:300] for r in h_res.get("results", []))
        food_text  = " | ".join(r.get("content", "")[:300] for r in f_res.get("results", []))
        return {"hotels": hotel_text[:800], "food": food_text[:800]}
    except Exception:
        return {}

# ── Destination currency via Nominatim country_code ───────────────────────────
def fetch_dest_currency(destination: str) -> tuple[str, float]:
    """Return (dest_currency_code, USD_per_1_dest_currency)."""
    try:
        url = (
            "https://nominatim.openstreetmap.org/search"
            f"?q={requests.utils.quote(destination)}&format=json&limit=1&addressdetails=1"
        )
        r = requests.get(url, headers=HEADERS, timeout=7)
        data = r.json()
        if data:
            cc = data[0].get("address", {}).get("country_code", "").lower()
            currency = COUNTRY_CURRENCY.get(cc, "USD")
            rate = fetch_exchange_rate(currency) if currency != "USD" else 1.0
            return currency, rate
    except Exception:
        pass
    return "USD", 1.0

# ── Numbeo cost of living ─────────────────────────────────────────────────────
def fetch_numbeo_costs(destination: str) -> dict:
    """Scrape Numbeo cost-of-living; fall back to Tavily if scrape fails."""
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

        if not costs:
            tavily = get_tavily()
            q = f"average tourist daily cost {destination} USD 2024 hotel meal transport"
            res = tavily.search(query=q, max_results=2)
            costs["tavily_summary"] = " ".join(r.get("content", "") for r in res.get("results", []))[:500]

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
    # Destination currency will be filled after input_parser runs;
    # store placeholder here, updated in destination_researcher.
    return {
        "currency_info": CurrencyInfo(
            user_currency=ci.user_currency,
            exchange_rate=rate,
            budget_usd=round(budget_usd, 2),
            budget_original=ci.budget_original,
            dest_currency=ci.dest_currency if ci.dest_currency else "USD",
            dest_rate=ci.dest_rate if ci.dest_rate else 1.0,
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

# Node 3 — destination_researcher (Wikivoyage + Numbeo + specifics + dest currency)
def destination_researcher(state: TravelPlannerState) -> dict:
    dest  = state["user_prefs"].destination
    prefs = state["user_prefs"]
    ci    = state.get("currency_info")

    wiki     = fetch_wikivoyage(dest)
    numbeo   = fetch_numbeo_costs(dest)
    specifics= fetch_destination_specifics(dest, prefs.interests, prefs.budget_usd)
    dest_cur, dest_rate = fetch_dest_currency(dest)

    # Update currency_info with destination currency
    updated_ci = CurrencyInfo(
        user_currency=ci.user_currency if ci else "USD",
        exchange_rate=ci.exchange_rate if ci else 1.0,
        budget_usd=ci.budget_usd if ci else prefs.budget_usd,
        budget_original=ci.budget_original if ci else prefs.budget_usd,
        dest_currency=dest_cur,
        dest_rate=dest_rate,
    )
    return {
        "currency_info": updated_ci,
        "destination_data": {
            "wikivoyage": wiki,
            "numbeo": numbeo,
            "specifics": specifics,
        },
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

    specifics    = dest_data.get("specifics", {})
    hotels_text  = specifics.get("hotels", "")[:600]
    food_text    = specifics.get("food",   "")[:600]

    system_msg = (
        "You are a world-class travel itinerary planner. "
        "Use ONLY the real data provided below — Wikivoyage overview, Numbeo cost benchmarks, "
        "exact hotel names and famous dishes from Tavily search, and the Open-Meteo weather forecast. "
        "Never use generic placeholders like 'local hotel' or 'try local cuisine'. "
        "Always name the specific hotel, dish, and restaurant. All costs in USD."
    )
    user_msg = f"""
Create a {prefs.days}-day itinerary for {prefs.destination}.
Trip: {prefs.start_date} → {prefs.end_date}
Total budget: ${prefs.budget_usd:.2f} USD
Interests: {', '.join(prefs.interests)}

=== DESTINATION OVERVIEW (Wikivoyage) ===
{wiki_text}

=== COST OF LIVING BENCHMARKS (Numbeo) ===
{numbeo_text}

=== REAL HOTELS WITH NAMES & PRICES (Tavily) ===
{hotels_text}
Instruction: Use the actual hotel names listed above. Pick one specific hotel per day that fits the budget.

=== FAMOUS LOCAL DISHES & RESTAURANTS (Tavily) ===
{food_text}
Instruction: Name the specific dish (e.g. Croissant at Du Pain et des Idées) and the restaurant.

=== WEATHER FORECAST FOR ACTUAL TRIP DATES (Open-Meteo) ===
{weather_text}

Rules:
- Keep TOTAL cost under ${prefs.budget_usd:.2f} USD
- 3-4 activities per day with HH:MM start/end times (start at 08:00)
- Each day date must match calendar starting {prefs.start_date}
- If rain > 10mm on a day, plan indoor activities
- accommodation_name must be a real hotel name, not 'budget hotel'
- food_cost_usd must reflect real Numbeo meal prices
- Mention specific famous dishes in tips
"""
    if iteration > 0:
        b_issues = "\n".join((state["budget_status"].itemized_overages if state.get("budget_status") else []))
        v_issues = "\n".join(f"Day {v.day}: {v.issue}" for v in state.get("constraint_violations", []))
        user_msg += "\n\n⚠️ REVISE — fix these specific violations:\n"
        if b_issues: user_msg += f"BUDGET:\n{b_issues}\n"
        if v_issues: user_msg += f"CONSTRAINTS:\n{v_issues}\n"
        system_msg += " Reduce costs precisely and fix timing conflicts."

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
