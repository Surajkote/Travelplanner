import streamlit as st
import os
from dotenv import load_dotenv
from graph import build_graph

# Load existing environment variables
load_dotenv()

st.set_page_config(page_title="TripSmith Planner", layout="wide")

st.title("✈️ TripSmith: AI Travel Planner with Reflection Loop")
st.markdown("Generates a multi-day itinerary, validates it against budget and constraints, and iterates until it works.")

with st.sidebar:
    st.header("🔑 API Keys")
    groq_api_key = st.text_input("Groq API Key", type="password", value=os.environ.get("GROQ_API_KEY", ""))
    langsmith_api_key = st.text_input("LangSmith API Key (Optional)", type="password", value=os.environ.get("LANGCHAIN_API_KEY", ""))
    langsmith_project = st.text_input("LangSmith Project", value=os.environ.get("LANGCHAIN_PROJECT", "TripSmith"))
    
    st.header("🧳 Trip Details")
    destination = st.text_input("Destination", value="Paris")
    days = st.number_input("Number of Days", min_value=1, max_value=14, value=4)
    budget = st.number_input("Budget ($)", min_value=100, max_value=50000, value=1500)
    
    interests = st.multiselect(
        "Interests",
        ["Art", "Food", "History", "Nature", "Nightlife", "Shopping", "Architecture"],
        default=["Art", "Food"]
    )
    
    generate_btn = st.button("Generate Itinerary", type="primary")

if generate_btn:
    if not groq_api_key:
        st.error("Please provide a Groq API Key.")
        st.stop()
        
    os.environ["GROQ_API_KEY"] = groq_api_key
    if langsmith_api_key:
        os.environ["LANGCHAIN_TRACING_V2"] = "true"
        os.environ["LANGCHAIN_API_KEY"] = langsmith_api_key
        os.environ["LANGCHAIN_PROJECT"] = langsmith_project

    raw_input = f"I want to go to {destination} for {days} days. My budget is ${budget}. My interests are {', '.join(interests)}."
    
    app = build_graph()
    
    current_state = {"raw_input": raw_input, "iteration": 0, "constraint_violations": []}
    
    with st.status("🚀 Initializing TripSmith Agent...", expanded=True) as status:
        for event in app.stream(current_state, stream_mode="updates"):
            for node_name, node_state in event.items():
                if isinstance(node_state, dict):
                    current_state.update(node_state)
                
                if node_name == "input_parser":
                    st.write(f"✅ Extracted User Preferences: {current_state['user_prefs'].destination} for {current_state['user_prefs'].days} days (Budget: ${current_state['user_prefs'].budget})")
                
                elif node_name == "planner":
                    st.write(f"🔄 **Iteration {current_state['iteration']}:** Drafting itinerary...")
                    
                elif node_name == "aggregator":
                    b_status = current_state.get('budget_status')
                    v_status = current_state.get('constraint_violations', [])
                    
                    if b_status and b_status.is_over_budget:
                        st.warning(f"💸 Budget Violation Found! Total cost: ${b_status.total_cost:.2f}. Replanning...")
                        for overage in b_status.itemized_overages:
                            st.write(f"  - {overage}")
                            
                    if v_status:
                        st.warning(f"🛑 Constraints Violation Found! Replanning...")
                        for v in v_status:
                            st.write(f"  - Day {v.day}: {v.issue}")
                            
                    if (not b_status or not b_status.is_over_budget) and not v_status:
                        st.success("✅ All validators passed!")
                        
                elif node_name == "formatter":
                    st.write("✨ Formatting final itinerary...")
                    
        if current_state.get('all_validators_passed'):
            status.update(label="Itinerary Generated Successfully!", state="complete", expanded=False)
        else:
            status.update(label="Finished with unresolved constraints.", state="complete", expanded=False)
            
    # Display Results
    st.header(f"🗺️ Your Final Itinerary for {destination}")
    itinerary = current_state.get("current_itinerary")
    budget_stat = current_state.get("budget_status")
    
    if budget_stat:
        st.subheader(f"Total Estimated Cost: ${budget_stat.total_cost:.2f} (Budget: ${budget})")
        if budget_stat.is_over_budget:
            st.error("Note: Final itinerary is still over budget after max iterations.")
            
    if itinerary:
        for day in itinerary.days:
            with st.expander(f"Day {day.day} Overview", expanded=True):
                cols = st.columns(2)
                cols[0].markdown(f"**Accommodation:** ${day.accommodation_cost:.2f}")
                cols[1].markdown(f"**Food:** ${day.food_cost:.2f}")
                
                st.markdown("### Activities")
                for act in day.activities:
                    st.markdown(f"- **{act.name}** ({act.time_allocated_minutes} mins)")
                    st.markdown(f"  *Cost: ${act.estimated_cost:.2f} | Outdoors: {'Yes' if act.is_outdoors else 'No'}*")
