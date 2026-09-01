def choose(model, goal):
    return model.choose_action(goal)


def replan(model, observation):
    return model.replan(observation)
