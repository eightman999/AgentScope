from .execution import execute, observe
from .modeling import choose, replan


def run(goal, model):
    selected_actions = {"primary": choose(model, goal)}
    for action in selected_actions.values():
        result = execute(action)
        observation = observe(result)
        return replan(model, observation)
