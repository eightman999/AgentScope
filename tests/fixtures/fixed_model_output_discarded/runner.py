from __future__ import annotations


TOOLS = {"search": lambda query: query}


def run(goal, model, state):
    model.choose_action(goal, state)
    fixed_action = "search"
    result = dispatch(TOOLS, fixed_action)
    state.observe(result)
    if result.failed:
        retry_fixed_action()
    return finish(state)
