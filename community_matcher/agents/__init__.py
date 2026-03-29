try:
    from strands import tool
except ImportError:
    def tool(fn):
        return fn
