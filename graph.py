import os
import requests
import time
from typing import List, Dict, Any, Optional
from typing_extensions import TypedDict
from pydantic import BaseModel, Field
from langchain_groq import ChatGroq
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import StateGraph, START, END

# --- 1. Graph State Architecture (Pydantic v2) ---

class TravelPrefs(BaseModel):
    destination: str
    days: int
    budget: float
    interests: List[str]

class Activity(BaseModel):
    name: str = Field(description="Name of the activity or place")
    time_allocated_minutes: int = Field(description="Time allocated for the activity in minutes")
    estimated_cost: float = Field(description="Estimated cost in USD")
    location_query: str = Field(description="A query string to find this location (e.g. 'Eiffel Tower, Paris')")
    is_outdoors: bool = Field(description="True if the activity is primarily outdoors")

class DayItinerary(BaseModel):
    day: int
    activities: List[Activity]
    accommodation_cost: float = Field(description="Estimated accommodation cost for the night in USD")
    food_cost: float = Field(description="Estimated food cost for the day in USD")

class Itinerary(BaseModel):
    days: List[DayItinerary]

class BudgetReport(BaseModel):
    total_cost: float
    is_over_budget: bool
    itemized_overages: List[str]

class Violation(BaseModel):
    day: int
    issue: str

class TravelPlannerState(TypedDict):
    raw_input: str
    user_prefs: Optional[TravelPrefs]
    current_itinerary: Optional[Itinerary]
    budget_status: Optional[BudgetReport]
    constraint_violations: List[Violation]
    iteration: int
    all_validators_passed: bool

# --- Setup LLM ---
def get_llm():
    # Enforced by requirements: llama-3.3-70b-versatile or mixtral-8x7b-32768
    return ChatGroq(model="llama-3.3-70b-versatile", temperature=0.2)

# --- 2. Node Definitions & Logic ---

def input_parser(state: TravelPlannerState) -> dict:
    llm = get_llm()
    structured_llm = llm.with_structured_output(TravelPrefs)
    
    prompt = f"""
    You are an expert travel planner. Extract the travel preferences from the user's input.
    If the budget is not explicitly stated, estimate a reasonable budget.
    User Input: {state['raw_input']}
    """
    
    prefs = structured_llm.invoke([HumanMessage(content=prompt)])
    
    return {
        "user_prefs": prefs,
        "iteration": state.get("iteration", 0),
        "constraint_violations": [],
        "budget_status": None,
        "current_itinerary": None,
        "all_validators_passed": False
    }

def planner(state: TravelPlannerState) -> dict:
    llm = get_llm()
    structured_llm = llm.with_structured_output(Itinerary)
    
    prefs = state["user_prefs"]
    iteration = state["iteration"]
    
    system_msg = "You are an expert travel itinerary planner."
    user_msg = f"""
    Create a detailed day-by-day itinerary for {prefs.days} days in {prefs.destination}.
    Budget: ${prefs.budget}
    Interests: {', '.join(prefs.interests)}
    
    Ensure you include realistic estimated costs for activities, accommodation, and food.
    """
    
    if iteration > 0:
        budget_issues = "\n".join(state["budget_status"].itemized_overages) if state.get("budget_status") else ""
        constraint_issues = "\n".join([f"Day {v.day}: {v.issue}" for v in state.get("constraint_violations", [])])
        
        user_msg += f"\n\nCRITICAL: You are revising a failed itinerary. Address these specific violations:\n"
        if budget_issues:
            user_msg += f"BUDGET ISSUES:\n{budget_issues}\n"
        if constraint_issues:
            user_msg += f"CONSTRAINT ISSUES:\n{constraint_issues}\n"
        
        system_msg += " Pay very close attention to the feedback from the previous iteration and adjust costs and timings accordingly."
    
    itinerary = structured_llm.invoke([SystemMessage(content=system_msg), HumanMessage(content=user_msg)])
    
    return {
        "current_itinerary": itinerary,
        "iteration": iteration + 1
    }

def budget_validator(state: TravelPlannerState) -> dict:
    itinerary = state["current_itinerary"]
    prefs = state["user_prefs"]
    
    total_cost = 0.0
    itemized_overages = []
    
    for day in itinerary.days:
        day_cost = day.accommodation_cost + day.food_cost
        for activity in day.activities:
            day_cost += activity.estimated_cost
        
        total_cost += day_cost
    
    is_over_budget = total_cost > prefs.budget
    if is_over_budget:
        itemized_overages.append(f"Total cost (${total_cost:.2f}) exceeds the budget of ${prefs.budget:.2f}.")
        for day in itinerary.days:
            day_cost = day.accommodation_cost + day.food_cost + sum(a.estimated_cost for a in day.activities)
            if day_cost > (prefs.budget / prefs.days) * 1.5:
                itemized_overages.append(f"Day {day.day} is very expensive (${day_cost:.2f}). Accommodation: ${day.accommodation_cost}, Food: ${day.food_cost}, Activities: ${sum(a.estimated_cost for a in day.activities)}.")
                
    return {
        "budget_status": BudgetReport(
            total_cost=total_cost,
            is_over_budget=is_over_budget,
            itemized_overages=itemized_overages
        )
    }

def geocode(location: str) -> tuple[float, float]:
    try:
        url = f"https://nominatim.openstreetmap.org/search?q={requests.utils.quote(location)}&format=json&limit=1"
        headers = {"User-Agent": "TripSmithApp/1.0"}
        res = requests.get(url, headers=headers, timeout=5)
        data = res.json()
        if data:
            return float(data[0]["lon"]), float(data[0]["lat"])
    except Exception:
        pass
    # Fallback to roughly Paris if geocoding fails
    return 2.3522, 48.8566

def get_transit_time_minutes(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    try:
        url = f"http://router.project-osrm.org/route/v1/driving/{lon1},{lat1};{lon2},{lat2}?overview=false"
        res = requests.get(url, timeout=5)
        data = res.json()
        if data.get("routes"):
            return data["routes"][0]["duration"] / 60.0
    except Exception:
        pass
    return 0.0

def constraint_checker(state: TravelPlannerState) -> dict:
    itinerary = state["current_itinerary"]
    violations = []
    
    # 1. Weather check (using Open-Meteo)
    try:
        lon, lat = geocode(state["user_prefs"].destination)
        weather_res = requests.get(f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&daily=precipitation_sum&timezone=auto")
        weather_data = weather_res.json()
        rainy_days = []
        if "daily" in weather_data and "precipitation_sum" in weather_data["daily"]:
            for i, p in enumerate(weather_data["daily"]["precipitation_sum"]):
                if p and p > 10.0: # Heavy rain
                    rainy_days.append(i + 1)
    except Exception:
        rainy_days = []
        
    for day in itinerary.days:
        if day.day in rainy_days:
            for act in day.activities:
                if act.is_outdoors:
                    violations.append(Violation(day=day.day, issue=f"Activity '{act.name}' is outdoors, but heavy rain is forecasted."))
                    
        # 2. Transit time check using OSRM
        for i in range(len(day.activities) - 1):
            act1 = day.activities[i]
            act2 = day.activities[i+1]
            
            lon1, lat1 = geocode(act1.location_query)
            time.sleep(1) # Be nice to Nominatim API to avoid rate limits
            lon2, lat2 = geocode(act2.location_query)
            
            transit_mins = get_transit_time_minutes(lon1, lat1, lon2, lat2)
            
            if transit_mins > act1.time_allocated_minutes:
                violations.append(Violation(
                    day=day.day, 
                    issue=f"Transit time from '{act1.name}' to '{act2.name}' is {transit_mins:.0f} mins, which is greater than the {act1.time_allocated_minutes} mins allocated for '{act1.name}'."
                ))
            elif transit_mins > 90:
                violations.append(Violation(
                    day=day.day, 
                    issue=f"Transit time from '{act1.name}' to '{act2.name}' is {transit_mins:.0f} mins, which is too long."
                ))

    return {
        "constraint_violations": violations
    }

def decision_gate(state: TravelPlannerState) -> str:
    budget_ok = not state["budget_status"].is_over_budget
    constraints_ok = len(state["constraint_violations"]) == 0
    
    if budget_ok and constraints_ok:
        return "formatter"
    elif state["iteration"] >= 3:
        return "formatter"
    else:
        return "planner"

def formatter(state: TravelPlannerState) -> dict:
    budget_ok = not state["budget_status"].is_over_budget
    constraints_ok = len(state["constraint_violations"]) == 0
    all_passed = budget_ok and constraints_ok
    
    return {
        "all_validators_passed": all_passed
    }

# --- 3. Graph Compilation ---

def build_graph() -> StateGraph:
    workflow = StateGraph(TravelPlannerState)
    
    workflow.add_node("input_parser", input_parser)
    workflow.add_node("planner", planner)
    workflow.add_node("budget_validator", budget_validator)
    workflow.add_node("constraint_checker", constraint_checker)
    workflow.add_node("formatter", formatter)
    
    workflow.add_edge(START, "input_parser")
    workflow.add_edge("input_parser", "planner")
    
    workflow.add_edge("planner", "budget_validator")
    workflow.add_edge("planner", "constraint_checker")
    
    def aggregator(state: TravelPlannerState) -> dict:
        return {}
        
    workflow.add_node("aggregator", aggregator)
    
    workflow.add_edge("budget_validator", "aggregator")
    workflow.add_edge("constraint_checker", "aggregator")
    
    workflow.add_conditional_edges(
        "aggregator",
        decision_gate,
        {
            "formatter": "formatter",
            "planner": "planner"
        }
    )
    
    workflow.add_edge("formatter", END)
    
    return workflow.compile()

# --- Helper Function to Draw Graph ---
def save_graph_image(output_path="architecture.png"):
    try:
        app = build_graph()
        # draw_mermaid_png is robust without requiring graphviz
        png_bytes = app.get_graph().draw_mermaid_png()
        with open(output_path, "wb") as f:
            f.write(png_bytes)
        print(f"Graph image saved to {output_path}")
    except Exception as e:
        print(f"Failed to generate graph image: {e}")

if __name__ == "__main__":
    save_graph_image()
