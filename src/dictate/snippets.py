import re


def expand_snippets(text: str, snippets) -> str:
    normalized = lambda value: " ".join(re.findall(r"\w+", value.casefold()))
    for snippet in sorted(snippets, key=lambda item: len(item["trigger"]), reverse=True):
        if normalized(text) == normalized(snippet["trigger"]):
            return snippet["text"]
    if not snippets:
        return text
    lookup = {item["trigger"].casefold(): item["text"] for item in snippets}
    triggers = sorted(lookup, key=len, reverse=True)
    pattern = r"(?<!\w)(?:" + "|".join(re.escape(trigger) for trigger in triggers) + r")(?!\w)"
    return re.sub(pattern, lambda match: lookup[match.group().casefold()], text, flags=re.IGNORECASE)
