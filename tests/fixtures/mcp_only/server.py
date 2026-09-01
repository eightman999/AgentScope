from mcp.server.fastmcp import FastMCP

mcp = FastMCP("fixture")


@mcp.tool()
def search(query: str) -> str:
    return query


def run(request):
    return search(request)

