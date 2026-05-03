import os
import requests
import time
import re
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
# 1. Pydantic State Models
# ─────────────────────────────────────────────────────────────────────────────

class TravelPrefs(BaseModel):
    destination: str
    days: int
    budget_usd: float = Field(description="Budget converted to USD")
    budget_original: float = Field(description="Budget in user's local currency")
    user_currency: str = Field(description="ISO currency code, e.g. INR, EUR, USD")
    exchange_rate: float = Field(description="How many USD per 1 unit of user_currency")
    interests: List[str]
    start_date: str = Field(description="Trip start date in YYYY-MM-DD format")
    end_date: str = Field(description="Trip end date in YYYY-MM-DD format")

class Activity(BaseModel):
    name: str = Field(description="Name of the activity or place")
    time_start: str = Field(description="Start time in HH:MM 24h format, e.g. '09:00'")
    time_end: str = Field(description="End time in HH:MM 24h format, e.g. '11:30'")
    time_allocated_minutes: int = Field(description="Duration in minutes")
    estimated_cost_usd: float = Field(description="Estimated cost in USD")
    location_query: str = Field(description="Specific place query, e.g. 'Louvre Museum, Paris'")
    is_outdoors: bool = Field(description="True if primarily outdoors")
    description: str = Field(description="Short description of the activity")
    tips: str = Field(description="One useful insider tip for this activity")

class DayItinerary(BaseModel):
    day: int
    date: str = Field(description="The calendar date for this day, YYYY-MM-DD")
    accommodation_name: str = Field(description="Name of hotel / accommodation")
    accommodation_cost_usd: float = Field(description="Accommodation cost in USD")
    food_cost_usd: float = Field(description="Estimated food cost for the day in USD")
    activities: List[Activity]
    day_summary: str = Field(description="One-line thematic summary of the day")

class Itinerary(BaseModel):
    days: List[DayItinerary]
    destination_highlights: str = Field(description="2-3 sentence destination overview")

class BudgetReport(BaseModel):
    total_cost_usd: float
    is_over_budget: bool
    itemized_overages: List[str]
    day_costs: List[dict] = Field(description="Per-day cost breakdown list")

class Violation(BaseModel):
    day: int
    issue: str

class CurrencyInfo(BaseModel):
    user_currency: str
    exchange_rate: float
    budget_usd: float

class TravelPlannerState(TypedDict):
    raw_input: str
    user_prefs: Optional[TravelPrefs]
    currency_info: Optional[CurrencyInfo]
    current_itinerary: Optional[Itinerary]
    budget_status: Optional[BudgetReport]
    constraint_violations: List[Violation]
    iteration: int
    all_validators_passed: bool

# ─────────────────────────────────────────────────────────────────────────────
# 2. Helpers
# ─────────────────────────────────────────────────────────────────────────────

def get_llm():
    return ChatGroq(
        model="llama-3.3-70b-versatile",
        temperature=0.3,
        api_key=os.environ["GROQ_API_KEY"]
    )

def get_tavily():
    return TavilyClient(api_key=os.environ["TAVILY_API_KEY"])

def geocode(location: str) -> tuple[float, float]:
    try:
        url = f"https://nominatim.openstreetmap.org/search?q={requests.utils.quote(location)}&format=json&limit=1"
        headers = {"User-Agent": "TripSmithApp/1.0"}
        res = requests.get(url, headers=headers, timeout=6)
        data = res.json()
        if data:
            return float(data[0]["lon"]), float(data[0]["lat"])
    except Exception:
        pass
    return 2.3522, 48.8566  # fallback: Paris

def get_transit_time_minutes(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    try:
        url = f"http://router.project-osrm.org/route/v1/driving/{lon1},{lat1};{lon2},{lat2}?overview=false"
        res = requests.get(url, timeout=6)
        data = res.json()
        if data.get("routes"):
            return data["routes"][0]["duration"] / 60.0
    except Exception:
        pass
    return 0.0

def get_exchange_rate(user_currency: str, destination_country: str) -> float:
    """Uses Tavily to search for live exchange rate from user_currency to USD."""
    if user_currency.upper() == "USD":
        return 1.0
    try:
        tavily = get_tavily()
        query = f"current exchange rate 1 {user_currency} to USD today {time.strftime('%B %Y')}"
        results = tavily.search(query=query, max_results=3)
        for r in results.get("results", []):
            content = r.get("content", "") + r.get("title", "")
            # Try to extract a float like "1 INR = 0.012 USD" or "0.012"
            matches = re.findall(r"(\d+\.?\d*)\s*USD", content, re.IGNORECASE)
            for m in matches:
                val = float(m)
                if 0.0001 < val < 1000:
                    return val
    except Exception:
        pass
    # Hardcoded fallbacks for common currencies
    fallbacks = {
        "INR": 0.012, "EUR": 1.08, "GBP": 1.27, "JPY": 0.0067,
        "CAD": 0.73, "AUD": 0.65, "CNY": 0.138, "SGD": 0.74,
        "AED": 0.27, "CHF": 1.12, "MXN": 0.058,
    }
    return fallbacks.get(user_currency.upper(), 1.0)

# ─────────────────────────────────────────────────────────────────────────────
# 3. Node Definitions
# ─────────────────────────────────────────────────────────────────────────────

def currency_resolver(state: TravelPlannerState) -> dict:
    """New node: Resolve user currency to USD using Tavily live search."""
    data = state.get("currency_info")
    if not data:
        return {}
    # If exchange_rate not yet set (0 or None), fetch it
    if not data.exchange_rate or data.exchange_rate == 0:
        rate = get_exchange_rate(data.user_currency, "")
        budget_usd = data.budget_original * rate
        return {
            "currency_info": CurrencyInfo(
                user_currency=data.user_currency,
                exchange_rate=rate,
                budget_usd=budget_usd,
            )
        }
    return {}

def input_parser(state: TravelPlannerState) -> dict:
    """Parse raw_input + currency_info into structured TravelPrefs."""
    llm = get_llm()
    structured_llm = llm.with_structured_output(TravelPrefs)

    currency_info = state.get("currency_info")
    budget_usd = currency_info.budget_usd if currency_info else 1500.0
    user_currency = currency_info.user_currency if currency_info else "USD"
    exchange_rate = currency_info.exchange_rate if currency_info else 1.0

    prompt = f"""
You are an expert travel planner. Extract trip details from the input below.

User Input: {state['raw_input']}

Important:
- budget_usd = {budget_usd:.2f} (already converted to USD for you)
- budget_original = {currency_info.budget_original if currency_info else budget_usd:.2f}
- user_currency = "{user_currency}"
- exchange_rate = {exchange_rate} (USD per 1 unit of user_currency)
- Extract start_date and end_date as YYYY-MM-DD strings from the input.
- Set days = number of inclusive days between start and end date.
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

def planner(state: TravelPlannerState) -> dict:
    """Draft or re-draft the itinerary with reflection on prior violations."""
    llm = get_llm()
    structured_llm = llm.with_structured_output(Itinerary)

    prefs = state["user_prefs"]
    iteration = state["iteration"]

    system_msg = (
        "You are a world-class travel itinerary planner. "
        "Always create realistic timelines starting mornings (08:00) and ending evenings. "
        "All costs must be in USD. Ensure day dates match the trip start date incrementally."
    )

    user_msg = f"""
Create a complete day-by-day itinerary for {prefs.days} days in {prefs.destination}.

Trip dates: {prefs.start_date} to {prefs.end_date}
Total budget (USD): ${prefs.budget_usd:.2f}
Interests: {', '.join(prefs.interests)}

For each day include:
- 3-4 activities with realistic start/end times (HH:MM), costs, location queries
- Accommodation name + cost, food cost
- Outdoor/indoor tag per activity
- Insider tips per activity
- A catchy day summary

Keep the TOTAL cost (all days) strictly under ${prefs.budget_usd:.2f}.
"""

    if iteration > 0:
        budget_issues = "\n".join(state["budget_status"].itemized_overages) if state.get("budget_status") else ""
        constraint_issues = "\n".join([f"Day {v.day}: {v.issue}" for v in state.get("constraint_violations", [])])

        user_msg += "\n\n⚠️ REVISION REQUIRED. Fix these specific violations from the last attempt:\n"
        if budget_issues:
            user_msg += f"BUDGET VIOLATIONS:\n{budget_issues}\n"
        if constraint_issues:
            user_msg += f"CONSTRAINT VIOLATIONS:\n{constraint_issues}\n"
        system_msg += " Be very precise in reducing costs and fixing timing conflicts."

    itinerary = structured_llm.invoke([SystemMessage(content=system_msg), HumanMessage(content=user_msg)])

    return {
        "current_itinerary": itinerary,
        "iteration": iteration + 1,
    }

def budget_validator(state: TravelPlannerState) -> dict:
    """Tally all costs and compare against budget."""
    itinerary = state["current_itinerary"]
    prefs = state["user_prefs"]

    total = 0.0
    itemized_overages = []
    day_costs = []

    daily_budget = prefs.budget_usd / prefs.days

    for day in itinerary.days:
        act_cost = sum(a.estimated_cost_usd for a in day.activities)
        day_total = day.accommodation_cost_usd + day.food_cost_usd + act_cost
        total += day_total
        day_costs.append({
            "day": day.day,
            "date": day.date,
            "accommodation": day.accommodation_cost_usd,
            "food": day.food_cost_usd,
            "activities": act_cost,
            "total": day_total,
        })
        if day_total > daily_budget * 1.4:
            itemized_overages.append(
                f"Day {day.day} ({day.date}) costs ${day_total:.2f}, "
                f"far exceeding the daily budget of ${daily_budget:.2f}. "
                f"Accommodation: ${day.accommodation_cost_usd:.2f}, "
                f"Food: ${day.food_cost_usd:.2f}, Activities: ${act_cost:.2f}."
            )

    is_over_budget = total > prefs.budget_usd
    if is_over_budget:
        itemized_overages.insert(0,
            f"Total trip cost (${total:.2f}) exceeds budget of ${prefs.budget_usd:.2f} "
            f"by ${total - prefs.budget_usd:.2f}. Please reduce accommodation or activity costs."
        )

    return {
        "budget_status": BudgetReport(
            total_cost_usd=total,
            is_over_budget=is_over_budget,
            itemized_overages=itemized_overages,
            day_costs=day_costs,
        )
    }

def constraint_checker(state: TravelPlannerState) -> dict:
    """Check transit feasibility via OSRM and weather via Open-Meteo."""
    itinerary = state["current_itinerary"]
    violations = []

    # ── Weather check ──────────────────────────────────────────────────────
    rainy_days = []
    try:
        lon, lat = geocode(state["user_prefs"].destination)
        weather_res = requests.get(
            f"https://api.open-meteo.com/v1/forecast"
            f"?latitude={lat}&longitude={lon}&daily=precipitation_sum&timezone=auto",
            timeout=6,
        )
        weather_data = weather_res.json()
        if "daily" in weather_data and "precipitation_sum" in weather_data["daily"]:
            for i, p in enumerate(weather_data["daily"]["precipitation_sum"]):
                if p and p > 10.0:
                    rainy_days.append(i + 1)
    except Exception:
        pass

    for day in itinerary.days:
        # Rain violations
        if day.day in rainy_days:
            for act in day.activities:
                if act.is_outdoors:
                    violations.append(Violation(
                        day=day.day,
                        issue=f"'{act.name}' is an outdoor activity on day {day.day}, "
                              f"but heavy rain (>10mm) is forecast. Consider an indoor alternative.",
                    ))

        # ── Transit time check via OSRM ───────────────────────────────────
        for i in range(len(day.activities) - 1):
            act1 = day.activities[i]
            act2 = day.activities[i + 1]

            try:
                lon1, lat1 = geocode(act1.location_query)
                time.sleep(1)  # Nominatim rate limit
                lon2, lat2 = geocode(act2.location_query)
                transit_mins = get_transit_time_minutes(lon1, lat1, lon2, lat2)

                if transit_mins > act1.time_allocated_minutes:
                    violations.append(Violation(
                        day=day.day,
                        issue=(
                            f"Transit from '{act1.name}' to '{act2.name}' takes "
                            f"{transit_mins:.0f} min, but only {act1.time_allocated_minutes} min "
                            f"were allocated for '{act1.name}'. Increase the gap or change the route."
                        ),
                    ))
                elif transit_mins > 90:
                    violations.append(Violation(
                        day=day.day,
                        issue=(
                            f"Transit from '{act1.name}' to '{act2.name}' takes "
                            f"{transit_mins:.0f} min — too long for a day trip. Pick closer venues."
                        ),
                    ))
            except Exception:
                pass

    return {"constraint_violations": violations}

def decision_gate(state: TravelPlannerState) -> str:
    """Route back to planner or forward to formatter."""
    budget_ok = not state["budget_status"].is_over_budget
    constraints_ok = len(state["constraint_violations"]) == 0

    if budget_ok and constraints_ok:
        return "formatter"
    elif state["iteration"] >= 3:
        return "formatter"  # Hard stop
    else:
        return "planner"

def formatter(state: TravelPlannerState) -> dict:
    """Finalise the all_validators_passed flag."""
    budget_ok = not state["budget_status"].is_over_budget
    constraints_ok = len(state["constraint_violations"]) == 0
    return {"all_validators_passed": budget_ok and constraints_ok}

# ─────────────────────────────────────────────────────────────────────────────
# 4. Graph Compilation
# ─────────────────────────────────────────────────────────────────────────────

def build_graph():
    workflow = StateGraph(TravelPlannerState)

    workflow.add_node("currency_resolver", currency_resolver)
    workflow.add_node("input_parser", input_parser)
    workflow.add_node("planner", planner)
    workflow.add_node("budget_validator", budget_validator)
    workflow.add_node("constraint_checker", constraint_checker)
    workflow.add_node("formatter", formatter)

    def aggregator(state: TravelPlannerState) -> dict:
        return {}

    workflow.add_node("aggregator", aggregator)

    workflow.add_edge(START, "currency_resolver")
    workflow.add_edge("currency_resolver", "input_parser")
    workflow.add_edge("input_parser", "planner")
    workflow.add_edge("planner", "budget_validator")
    workflow.add_edge("planner", "constraint_checker")
    workflow.add_edge("budget_validator", "aggregator")
    workflow.add_edge("constraint_checker", "aggregator")
    workflow.add_conditional_edges(
        "aggregator",
        decision_gate,
        {"formatter": "formatter", "planner": "planner"},
    )
    workflow.add_edge("formatter", END)

    return workflow.compile()

# ─────────────────────────────────────────────────────────────────────────────
# 5. Architecture Diagram Helper
# ─────────────────────────────────────────────────────────────────────────────

def save_graph_image(output_path="architecture.png"):
    try:
        app = build_graph()
        png_bytes = app.get_graph().draw_mermaid_png()
        with open(output_path, "wb") as f:
            f.write(png_bytes)
        print(f"Graph image saved to {output_path}")
    except Exception as e:
        print(f"Failed to generate graph image: {e}")

if __name__ == "__main__":
    save_graph_image()
