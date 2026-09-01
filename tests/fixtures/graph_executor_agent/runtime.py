class GraphBuilder:
    def add_node(self, name, handler):
        return None

    def add_conditional_edges(self, source, router, path_map=None):
        return None

    def add_edge(self, source, target):
        return None


class ToolNode:
    def __init__(self, tools):
        self.tools = tools


def call_model(model, state):
    return model.invoke(state)


def route_after_model(state):
    return "tools" if state["messages"][-1].tool_calls else "end"


def execute_tool(tool_call):
    return tool_call


workflow = GraphBuilder()
workflow.add_node("agent", call_model)
workflow.add_node("tools", ToolNode([execute_tool]))
workflow.add_conditional_edges(
    "agent",
    route_after_model,
    path_map={"tools": "tools", "end": "end"},
)
workflow.add_edge("tools", "agent")
