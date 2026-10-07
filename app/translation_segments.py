"""Conservative sentence boundaries in protected Markdown, without NLP models."""
import re


_HIDDEN = '\u2060'
_CLOSERS = '\"\'”’」』）)]}»'
_ABBREVIATIONS = frozenset(('mr mrs ms dr prof sr jr st vs etc e.g i.e al fig figs '
                            'eq eqs no nos vol vols p pp sec secs ch inc ltd dept approx').split())
_BLOCK_START = re.compile(r'^[ \t]*(?:#{1,6}[ \t]+|(?:[-+*]|\d+[.)])[ \t]+)')


def _enclosures(text):
    """Do not split a quoted phrase or parenthetical expression halfway."""
    pairs = {'(': ')', '（': '）', '[': ']', '{': '}', '“': '”', '「': '」', '『': '』', '«': '»'}
    stack, spans = [], []
    for index, char in enumerate(text):
        if stack and char == stack[-1][1]:
            start, _ = stack.pop(); spans.append((start, index + 1))
        elif char in pairs:
            stack.append((index, pairs[char]))
        elif char == '"' and (index == 0 or not text[index - 1].isalnum()):
            stack.append((index, char))
    return sorted(spans)


def sentence_pieces(encoded, pattern, values):
    """Keep offsets aligned with encoded text; hidden syntax cannot end a sentence.

    A single prose newline is only whitespace. Blank lines and Markdown block
    boundaries delimit fragments such as headings and list items. Ambiguous
    abbreviations are kept together rather than risking an incomplete sentence.
    Length never determines a sentence boundary.
    """
    projected, position, cuts = [], 0, {0, len(encoded)}
    for match in pattern.finditer(encoded):
        projected.append(encoded[position:match.start()])
        original = values[match[0]]
        # Only syntax/whitespace is invisible. Formula/code/URL contents remain
        # opaque so punctuation or newlines inside them cannot split prose.
        if original.isspace():
            count = original.count('\n')
            visible = '\n' * min(count, 2) if count else ' '
        elif re.fullmatch(r'\*{1,3}|_{1,3}|~~|</?[^>]+>|[ \t>]+', original):
            visible = ''
        elif _BLOCK_START.match(original):
            visible = '\x05' if original.lstrip().startswith('#') else '\x02'
            cuts.add(match.start())
        elif original == '|':
            visible = '\x03'
        elif re.match(r'^[ \t>]*(`{3,}|~{3,})', original) or original.startswith(('    ', '\t', '---\n', '---\r\n')):
            visible = '\x04'; cuts.update((match.start(), match.end()))
        else:
            visible = '\ufffc'
        projected.append(visible + _HIDDEN * (len(match[0]) - len(visible)))
        position = match.end()
    projected.append(encoded[position:])
    shadow = ''.join(projected)

    for match in re.finditer(r'\n[\s' + _HIDDEN + r']*\n[' + _HIDDEN + r']*', shadow):
        cuts.add(match.end())
    # A heading/table row ends at its newline, including its protected marker.
    line_start = 0
    for match in re.finditer(r'\n+[' + _HIDDEN + r']*', shadow):
        if '\x05' in shadow[line_start:match.start()] or '\x03' in shadow[line_start:match.start()]:
            cuts.add(match.end())
        line_start = match.end()

    enclosures = _enclosures(shadow)
    enclosure_index, enclosing_end = 0, 0
    for match in re.finditer(r'[。！？!?।॥؟]+|\.+', shadow):
        end = match.end()
        while end < len(shadow) and shadow[end] in _CLOSERS + _HIDDEN:
            end += 1
        while enclosure_index < len(enclosures) and enclosures[enclosure_index][0] < match.start():
            enclosing_end = max(enclosing_end, enclosures[enclosure_index][1]); enclosure_index += 1
        if end < enclosing_end:
            continue
        punctuation = match[0]
        if punctuation[0] in '.!?' and end < len(shadow) and not shadow[end].isspace():
            continue
        following = end
        while following < len(shadow) and (shadow[following].isspace() or shadow[following] == _HIDDEN):
            following += 1
        if punctuation[0] in '.!?' and following < len(shadow) and shadow[following].islower():
            continue
        if punctuation == '.':
            before = shadow[max(0, match.start() - 80):match.end()].replace(_HIDDEN, '')
            word = re.search(r'([\w.]+)\.$', before)
            if word and (word[1].lower() in _ABBREVIATIONS or
                         re.fullmatch(r'(?:[A-Za-z]\.)*[A-Za-z]', word[1])):
                continue
        cuts.add(end)

    ordered = sorted(cuts)
    pieces = []
    for start, end in zip(ordered, ordered[1:]):
        piece = encoded[start:end]
        # Whitespace belongs to the preceding unit, not to the next sentence's
        # cache key. It remains protected and is restored byte for byte.
        original = pattern.sub(lambda m: values[m[0]], piece)
        if not original.strip() and pieces:
            pieces[-1] += piece
        else:
            pieces.append(piece)
    return pieces


def adjacent_context(pieces, first, last, pattern, values, budget=240):
    """At most two complete neighbouring units per side; never a sliced tail."""
    def side(indices, reverse=False):
        selected, length = [], 0
        for index in indices:
            prose = pattern.sub(lambda m: ' ' if values[m[0]].isspace() else '', pieces[index])
            prose = ' '.join(prose.split())
            if not any(c.isalpha() for c in prose): continue
            if length + len(prose) + bool(selected) > budget: break
            selected.append(prose); length += len(prose) + (len(selected) > 1)
            if len(selected) == 2: break
        return ' '.join(reversed(selected) if reverse else selected)
    return {'previous_translation': '',
            'context_before': side(range(first - 1, max(-1, first - 3), -1), True),
            'context_after': side(range(last + 1, min(len(pieces), last + 3)))}
