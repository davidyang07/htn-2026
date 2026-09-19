"""A small, real LangGraph multi-agent app: a ResearchAgent that calls a
WebSearchTool, hands its findings to a SummarizerAgent, which reports to a
SentinelAgent that oversees the pipeline. This is the external application
AgentShield imports and adversarially evaluates -- see export_topology.py and
backend/app/importers/external_topology.py.
"""

from typing import TypedDict

from langgraph.graph import END, START, StateGraph


class PipelineState(TypedDict):
    query: str
    findings: str
    summary: str
    flagged: bool


def research_agent(state: PipelineState) -> PipelineState:
    return {**state, "findings": f"raw findings for: {state['query']}"}


def web_search_tool(state: PipelineState) -> PipelineState:
    return {**state, "findings": state["findings"] + " [web_search tool result]"}


def summarizer_agent(state: PipelineState) -> PipelineState:
    return {**state, "summary": f"summary of: {state['findings']}"}


def sentinel_agent(state: PipelineState) -> PipelineState:
    return {**state, "flagged": False}


def build_graph():
    graph = StateGraph(PipelineState)
    graph.add_node("research_agent", research_agent)
    graph.add_node("web_search_tool", web_search_tool)
    graph.add_node("summarizer_agent", summarizer_agent)
    graph.add_node("sentinel_agent", sentinel_agent)

    graph.add_edge(START, "research_agent")
    graph.add_edge("research_agent", "web_search_tool")
    graph.add_edge("web_search_tool", "summarizer_agent")
    graph.add_edge("summarizer_agent", "sentinel_agent")
    graph.add_edge("sentinel_agent", END)
    return graph.compile()


# Tool ownership and sentinel role are AgentShield-specific concepts LangGraph's
# own graph structure doesn't natively encode (a tool node is just another
# node; there's no first-class "monitors" relationship) -- tracked here,
# alongside the graph definition, since this file is this app's source of
# truth, and read by export_topology.py.
TOOL_BINDINGS = {"research_agent": ["web_search"]}
SENTINEL_AGENTS = ["sentinel_agent"]


if __name__ == "__main__":
    app = build_graph()
    result = app.invoke({"query": "example", "findings": "", "summary": "", "flagged": False})
    print(result)
