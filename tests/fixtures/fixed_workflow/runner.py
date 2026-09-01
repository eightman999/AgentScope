from llm_client import complete


def run_investigation(request):
    summary = complete(request)
    return run_search(request), run_fetch(request), summary


def run_search(request):
    return "search"


def run_fetch(request):
    return "fetch"

