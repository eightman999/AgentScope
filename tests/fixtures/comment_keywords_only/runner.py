"""A fixed workflow with deliberately misleading Agent vocabulary."""


def run(goal):
    # model output -> action selector -> tool dispatch -> observation
    # feedback -> replan -> retry -> budget -> termination
    return "fixed"
