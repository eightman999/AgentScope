def search(query):
    return query


def fetch(query):
    return query


TOOLS = {"search": search, "fetch": fetch}


def run(goal, model, state):
    while not state.done:
        action = model.choose_action(goal, state.observation)
        result = dispatch(TOOLS, action)
        state.observe(result)
        if result.failed:
            action = model.replan(goal, state)
    return finish(state)
