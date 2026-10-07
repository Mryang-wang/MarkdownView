"""Sentence-aligned translation memory for one document, kept only in RAM."""
import re
from difflib import SequenceMatcher

from .translation_markdown import Chunk, ProtectedMarkdown
from .translation_segments import adjacent_context
from .i18n import t


class IncrementalMarkdown(ProtectedMarkdown):
    def __init__(self, source, limit=4000, previous=None):
        super().__init__(source, limit)
        self.units = []
        for piece in self.sentences:
            left, right = len(piece) - len(piece.lstrip()), len(piece.rstrip())
            unit = Chunk(piece.strip(), piece[:left], piece[right:]) if piece.strip() else Chunk('', piece, '')
            original = self.pattern.sub(lambda m: self.values[m[0]], piece)
            translatable = super().needs_translation(unit)
            self.units.append({'chunk': unit, 'source': original, 'target': None if translatable else original,
                               'translatable': translatable, 'reused': False})
        if previous is not None:
            self._reuse(previous.units)
        self.reused_units = sum(u['reused'] and u['translatable'] for u in self.units)
        self.changed_units = sum(u['target'] is None for u in self.units)
        self.chunks, self._batches, self._cached, self._separators = [], {}, {}, {}
        index = 0
        while index < len(self.units):
            unit = self.units[index]
            if unit['target'] is not None:
                chunk = unit['chunk']; self.chunks.append(chunk); self._cached[id(chunk)] = unit['target']
                index += 1
                continue
            indices, separators, text = [index], [], unit['chunk'].text
            index += 1
            while index < len(self.units) and not self.units[index]['reused']:
                next_text = self.units[index]['chunk'].text
                token = self.prefix + str(len(self.values)) + '@@'
                if len(text) + len(token) + len(next_text) > limit:
                    break
                self.values[token] = self.units[indices[-1]]['chunk'].suffix + self.units[index]['chunk'].prefix
                separators.append(token)
                text += token + next_text; indices.append(index); index += 1
            chunk = Chunk(text, self.units[indices[0]]['chunk'].prefix, self.units[indices[-1]]['chunk'].suffix)
            self.chunks.append(chunk)
            self._batches[id(chunk)], self._separators[id(chunk)] = indices, separators

    def _reuse(self, previous):
        old, new = [u['source'].strip() for u in previous], [u['source'].strip() for u in self.units]
        # Linear prefix/suffix matching handles ordinary edits even in repetitive
        # documents. Bound the more expensive comparison to the changed middle.
        prefix = 0
        while prefix < min(len(old), len(new)) and old[prefix] == new[prefix]:
            prefix += 1
        suffix = 0
        while suffix < min(len(old), len(new)) - prefix and old[-suffix - 1] == new[-suffix - 1]:
            suffix += 1
        pairs = [(i, i) for i in range(prefix)]
        pairs.extend((len(old) - i - 1, len(new) - i - 1) for i in range(suffix))
        a, b = old[prefix:len(old) - suffix], new[prefix:len(new) - suffix]
        if len(a) * len(b) <= 1_000_000:
            for match in SequenceMatcher(None, a, b, autojunk=False).get_matching_blocks():
                pairs.extend((prefix + match.a + i, prefix + match.b + i) for i in range(match.size))
        for before, after in pairs:
            if previous[before]['target'] is not None:
                source = self.units[after]['source']
                left, right = len(source) - len(source.lstrip()), len(source.rstrip())
                self.units[after]['target'] = source[:left] + previous[before]['target'].strip() + source[right:] if source.strip() else source
                self.units[after]['reused'] = True

    def needs_translation(self, chunk):
        if id(chunk) in getattr(self, '_cached', {}):
            return False
        return super().needs_translation(chunk)

    def restore(self, text, chunk, validate=True):
        if id(chunk) in self._cached:
            return self._cached[id(chunk)]
        super().restore(text, chunk, validate)
        separators = self._separators[id(chunk)]
        parts = re.split('|'.join(map(re.escape, separators)), text) if separators else [text]
        indices = self._batches[id(chunk)]
        restored = [super(IncrementalMarkdown, self).restore(part, self.units[i]['chunk'], validate)
                    for i, part in zip(indices, parts)]
        for i, value in zip(indices, restored):
            self.units[i]['target'] = value
        return ''.join(restored)

    def context_for(self, chunk):
        indices = self._batches.get(id(chunk), [])
        if not indices:
            return {}
        return adjacent_context(self.sentences, indices[0], indices[-1], self.pattern, self.values)

    def display_markdown(self):
        """Keep cached translations visible, with explicit placeholders for edits."""
        result = []
        waiting = '<span class="translation-awaiting">' + t('待更新') + '…</span>'
        for unit in self.units:
            if unit['target'] is not None:
                result.append(unit['target']); continue
            chunk = unit['chunk']; parts = self.pattern.split(chunk.text); tokens = self.pattern.findall(chunk.text)
            result.append(chunk.prefix)
            for index, part in enumerate(parts):
                result.append(waiting if any(c.isalpha() for c in part) else part)
                if index < len(tokens): result.append(self.values[tokens[index]])
            result.append(chunk.suffix)
        return ''.join(result)

    def source_before(self, chunk):
        indices = self._batches.get(id(chunk), [])
        return ''.join(u['source'] for u in self.units[:indices[0]]) if indices else ''
