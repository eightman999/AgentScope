def execute(action):
    return dispatch(action)


def observe(result):
    return record_observation(result)
