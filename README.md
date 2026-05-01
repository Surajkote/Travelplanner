# TripSmith TravelPlanner Agent

An advanced, stateful AI agent built using LangGraph, LangChain, and Streamlit. This application generates a multi-day travel itinerary based on user inputs, strictly validates it against external APIs (budget and physical constraints), and utilizes a robust "Reflection Loop" to automatically replan until all constraints are met.

## Features

- **LangGraph Architecture**: Implements a strict Reflection Loop pattern.
- **Pydantic v2 Validation**: Structured data guarantees for the LLM output.
- **Real-World Validators**:
  - **Budget Validator**: Deterministically tallies expected costs to ensure they stay within budget.
  - **Constraint Checker**: 
    - Integrates Open-Meteo API to prevent outdoor activities during heavy rain.
    - Integrates OSRM API (with OpenStreetMap Nominatim Geocoding) to validate that physical transit time between consecutive activities is feasible.
- **Dynamic Streamlit UI**: Interactive interface that streams internal agent reasoning during iterations.

## Prerequisites

- Python 3.10+
- A [Groq API Key](https://console.groq.com/)
- (Optional) [LangSmith API Key](https://smith.langchain.com/) for observability.

## Installation & Setup

1. **Clone the repository:**
   ```bash
   git clone https://github.com/Surajkote/Travelplanner.git
   cd Travelplanner
   ```

2. **Create and activate the virtual environment:**
   ```bash
   python3 -m venv venv
   source venv/bin/activate  # On Windows use `venv\Scripts\activate`
   ```

3. **Install the dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Environment Variables:**
   Create a `.env` file in the root directory (or input these directly into the Streamlit UI):
   ```env
   GROQ_API_KEY="your_groq_api_key_here"
   LANGCHAIN_API_KEY="your_langsmith_api_key"
   LANGCHAIN_PROJECT="TripSmith"
   LANGCHAIN_TRACING_V2="true"
   ```

## Usage

**Start the Streamlit Agent Interface:**
```bash
streamlit run app.py
```

**Generate Architecture Diagram:**
If you need to generate a `.png` of the LangGraph architecture, simply run:
```bash
python graph.py
```
This will generate an `architecture.png` file in the root directory.
