from langgraph.graph import StateGraph
from langchain_openai import ChatOpenAI
from langchain_openai import OpenAIEmbeddings
from langchain_community.vectorstores import FAISS
from langsmith import Client
import os

# --------------------------------
# LangSmith Configuration
# --------------------------------

os.environ["LANGSMITH_TRACING"] = "true"
os.environ["LANGSMITH_ENDPOINT"]="https://apac.api.smith.langchain.com"
os.environ["LANGSMITH_API_KEY"]="your_langsmith_api_key"
os.environ["LANGSMITH_PROJECT"]="Test-LangSmith"

# -------------------------
# LLM
# -------------------------

llm = ChatOpenAI(
    api_key="your_openai_api_key",
    model="gpt-4o-mini",
    temperature=0
)

# -------------------------
# Graph
# -------------------------

graph = StateGraph(dict)


# --------------------------------
# Tool: Budget Calculator
# --------------------------------

def budget_calculator(
    budget, days,
    hotel_limit, meal_limit
):

    daily_limit = hotel_limit + meal_limit

    min_required = daily_limit * days

    status = (
        "Within limits"
        if budget >= min_required
        else "Over budget"
    )

    return {
        "total_budget": budget,
        "hotel_limit": hotel_limit,
        "meal_limit": meal_limit,
        "daily_limit": daily_limit,
        "min_required": min_required,
        "status": status
    }

# --------------------------------
# Agent 1: Planner Agent
# --------------------------------
 
def planner_agent(state):
 
    request = state["request"]
 
    response = llm.invoke(
    f"""
    You are a Travel Planner.
 
    Create a short travel plan.
 
    Request:
    {request}
 
    Include:
    - Destination
    - Number of days
    - Activities per day
    - Estimated daily hotel cost
    - Estimated daily meal cost
    - Estimated flight cost
    - Estimated other costs
 
    Keep it brief.
    """
    )
 
    state["plan"] = response.content 
    return state

# --------------------------------
# Agent 2: Policy Retriever (RAG)
# --------------------------------

def policy_retriever(state):

    request = state["request"]

    docs = retriever.invoke(request)

    # Sort by original order in document
    sorted_docs = sorted(
        docs,
        key=lambda d: policy_texts.index(
            d.page_content
        )
        if d.page_content in policy_texts
        else 0
    )

    policy_text = "\n".join(
        [doc.page_content for doc in sorted_docs]
    )

    state["policy"] = policy_text

    return state

# --------------------------------
# Agent 3: Budget Agent (Tool)
# --------------------------------

def budget_agent(state):
    policy = state["policy"]
    request = state["request"]

    # Ask LLM to extract all numbers
    response = llm.invoke(
    f"""
    Read this travel request:

    {request}

    And this company policy:

    {policy}

    Return ONLY four numbers
    separated by commas:

    budget, days, hotel_limit, meal_limit

    Example: 50000,3,5000,1500
    """
    )

    parts = response.content.strip().split(",")

    budget = int(parts[0].strip())
    days = int(parts[1].strip())
    hotel_limit = int(parts[2].strip())
    meal_limit = int(parts[3].strip())

    # Use Budget Calculator Tool
    breakdown = budget_calculator(
        budget=budget,
        days=days,
        hotel_limit=hotel_limit,
        meal_limit=meal_limit
    )

    state["budget_status"] = (
        breakdown["status"]
    )

    return state

# --------------------------------
# Agent 4: Reviewer Agent
# (Guardrails)
# --------------------------------

def reviewer_agent(state):

    plan = state["plan"]
    policy = state["policy"]
    budget = state["budget_status"]

    review_count = state.get(
        "review_count", 0
    )

    review_count += 1
    state["review_count"] = review_count

    response = llm.invoke(
    f"""
    You are a Travel Reviewer.

    Review this travel request.

    Travel Plan:
    {plan}

    Policy Check:
    {policy}

    Budget Analysis:
    {budget}

    Review number: {review_count}

    Guardrails (ONLY reject if violated):
    - Reject ONLY if total > ₹500000
    - Reject ONLY if flight > ₹20000
    - Otherwise APPROVE

    Give a clear recommendation:
    APPROVE or REVISE

    If REVISE, suggest changes.

    Also check if escalation is needed.
    Set escalation = YES if:
    - Travel is international
    - Flight cost > ₹20000

    Format:
    Recommendation: APPROVE/REVISE
    Confidence: <score>/100
    Escalation: YES/NO
    Reason: <brief reason>

    Keep it brief.
    """
    )

    state["review"] = response.content

    review_text = response.content.upper()

    if "ESCALATION: YES" in review_text:
        state["escalation"] = "yes"
    else:
        state["escalation"] = "no"

    return state


# --------------------------------
# Human-in-the-Loop
# Manager Approval
# --------------------------------

def manager_approval(state):

    print("\n" + "=" * 40)
    print("MANAGER REVIEW")
    print("=" * 40)

    print("\nTravel Request:")
    print(state["request"])

    print("\nPolicy:")
    print(state["policy"])

    print("\Budget:")
    state["budget_status"]

    print("\nReviewer Recommendation:")
    print(state["review"])

    print("\n" + "=" * 40)

    approval = input(
        "\nManager: Approve? (yes/no): "
    )

    approval = approval.strip().lower()

    if approval == "yes":
        state["approval"] = "Approved"
    elif state.get("review_count", 0) >= 3:
        state["approval"] = "Auto-Rejected"
    else:
        state["approval"] = "Denied"

    return state


# --------------------------------
# Escalation: Director Approval
# --------------------------------

def director_approval(state):

    print("\n" + "=" * 40)
    print("DIRECTOR REVIEW (ESCALATED)")
    print("=" * 40)

    print("\nTravel Request:")
    print(state["request"])

    print("\nPolicy:")
    print(state["policy"])
    
    print("\Budget:")
    state["budget_status"]

    print("\nReviewer Recommendation:")
    print(state["review"])

    print("\nManager Decision:")
    print(state["approval"])

    print("\n" + "=" * 40)

    approval = input(
        "\nDirector: Approve? (yes/no): "
    )

    approval = approval.strip().lower()

    if approval == "yes":
        state["approval"] = (
            "Escalated - Director Approved"
        )
    else:
        state["approval"] = (
            "Escalated - Director Rejected"
        )

    return state


# --------------------------------
# Router: Conditional Routing
# --------------------------------

def approval_route(state):

    if state["approval"] == "Approved":

        if state.get("escalation") == "yes":
            return "escalate"

        return "approved"

    if state["approval"] == "Auto-Rejected":

        return "approved"

    return "denied"


# --------------------------------
# Output Node
# --------------------------------

def output(state):

    print("\n" + "=" * 40)
    print("FINAL OUTPUT")
    print("=" * 40)

    print(
        "\nTravel Plan:\n",
        state["plan"]
    )

    print(
        "\nBudget:\n",
        state["budget_status"]
    )

    print(
        "\nPolicy:\n",
        state["policy"]
    )

    print(
        "\nReview:\n",
        state["review"]
    )

    print(
        "\nManager:",
        state["approval"]
    )

    print("=" * 40)

    return state

# -------------------------
# RAG Setup - Load Travel Policy
# -------------------------

with open(
    "company_policy.txt",
    "r",
    encoding="utf-8"
) as f:
    policy_lines = f.readlines()

policy_texts = [
    line.strip()
    for line in policy_lines
    if line.strip()
]

embeddings = OpenAIEmbeddings(
    api_key="your_openai_api_key"
)

vectorstore = FAISS.from_texts(
    policy_texts,
    embeddings
)

retriever = vectorstore.as_retriever()

# --------------------------------
# Register Nodes
# --------------------------------

graph.add_node(
    "planner",
    planner_agent
)

graph.add_node(
    "policy",
    policy_retriever
)

graph.add_node(
    "budget",
    budget_agent
)

graph.add_node(
    "reviewer",
    reviewer_agent
)

graph.add_node(
    "manager",
    manager_approval
)

graph.add_node(
    "director",
    director_approval
)

graph.add_node(
    "output",
    output
)

graph.set_entry_point(
    "planner"
)

graph.add_edge(
    "planner",
    "policy"
)

graph.add_edge(
    "policy",
    "budget"
)

graph.add_edge(
    "budget",
    "reviewer"
)

graph.add_edge(
    "reviewer",
    "manager"
)

graph.add_conditional_edges(

    "manager",

    approval_route,

    {
        "approved": "output",

        "escalate": "director",

        "denied": "reviewer"
    }
)

graph.add_edge(
    "director",
    "output"
)

app = graph.compile()
result = app.invoke({
 
    "request":
    "Business Chennai trip for 3 days with budget 25000"
 
})
