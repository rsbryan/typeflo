"""Fit dictated text to the text already around the insertion point."""
import logging

WINDOW = 160
SENTENCE_END = ".!?"
LINE_BREAKS = "\n\r"
NO_SPACE_BEFORE = " \t([{\"'“‘/-"
NO_SPACE_AFTER = " \t,.;:!?)]}\"'”’/-"
CONTINUATION = ",;:)]}"


def read_context(pid):
    """Return (before, after) around the cursor of the focused text element in the app with pid, or None."""
    try:
        import ApplicationServices as AS
    except ImportError:
        return None
    try:
        app = AS.AXUIElementCreateApplication(pid)
        AS.AXUIElementSetMessagingTimeout(app, 0.25)
        error, focused = AS.AXUIElementCopyAttributeValue(app, AS.kAXFocusedUIElementAttribute, None)
        if error or focused is None:
            logging.debug("context: no focused element (%s)", error)
            return None
        AS.AXUIElementSetMessagingTimeout(focused, 0.25)
        error, role = AS.AXUIElementCopyAttributeValue(focused, AS.kAXRoleAttribute, None)
        if error or role == "AXSecureTextField":
            return None
        error, selection = AS.AXUIElementCopyAttributeValue(focused, AS.kAXSelectedTextRangeAttribute, None)
        if error or selection is None:
            logging.debug("context: no selection range (%s)", error)
            return None
        ok, (location, length) = AS.AXValueGetValue(selection, AS.kAXValueTypeCFRange, None)
        error, count = AS.AXUIElementCopyAttributeValue(focused, AS.kAXNumberOfCharactersAttribute, None)
        if not ok or error or count is None:
            return None
        start = max(0, location - WINDOW)
        before = _string(AS, focused, start, location - start)
        end = location + length
        after = _string(AS, focused, end, min(count, end + WINDOW) - end)
        if before is None or after is None:
            return None
        return before, after
    except Exception:
        logging.exception("context: reading the focused text failed")
        return None


def _string(AS, element, location, length):
    if length <= 0:
        return ""
    parameter = AS.AXValueCreate(AS.kAXValueTypeCFRange, (location, length))
    error, text = AS.AXUIElementCopyParameterizedAttributeValue(
        element, AS.kAXStringForRangeParameterizedAttribute, parameter, None)
    if error or text is None:
        logging.debug("context: string for range failed (%s)", error)
        return None
    return str(text)


def fit_to_context(text, before, after, dictionary=()):
    """Adjust capitalization, trailing punctuation, and spacing so text reads naturally where it is inserted."""
    text = text.strip()
    if not text or before is None or after is None:
        return text
    previous = before.rstrip(" \t")
    if previous and previous[-1] not in SENTENCE_END + LINE_BREAKS:
        text = _lowercase_first(text, dictionary)
    following = after.lstrip(" \t")
    if following and (following[0].islower() or following[0] in CONTINUATION + SENTENCE_END):
        text = text.rstrip(SENTENCE_END)
    if before and before[-1] not in NO_SPACE_BEFORE + LINE_BREAKS:
        text = " " + text
    if after and after[0] not in NO_SPACE_AFTER + LINE_BREAKS:
        text = text + " "
    return text


def _lowercase_first(text, dictionary):
    first = text.split(maxsplit=1)[0].rstrip(",.;:!?")
    if first == "I" or first.startswith("I'") or first.startswith("I’"):
        return text
    if any(character.isupper() for character in first[1:]):
        return text
    if any(word.lower() == first.lower() and word[:1].isupper() for word in dictionary):
        return text
    return text[0].lower() + text[1:]
