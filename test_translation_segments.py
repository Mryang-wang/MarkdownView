"""Sentence integrity, strict request budgets and cache stability regressions."""
import unittest
from unittest.mock import patch

from app.translation import TranslationConfig
from app.translation_markdown import ProtectedMarkdown, TranslationJob
from app.translation_memory import IncrementalMarkdown


def originals(document):
    return [document.pattern.sub(lambda m: document.values[m[0]], s).strip()
            for s in document.sentences]


def echo(document):
    return ''.join(document.restore(c.text, c) for c in document.chunks)


class Sentences(unittest.TestCase):
    def test_abbreviations_numbers_quotes_and_soft_lines(self):
        expected = ['Dr. Smith measured 3.14 mm, e.g. on Fig. 2, using v1.2.',
                    'Jonas E. Smith agrees.', 'The result continues\non the next line.',
                    '**"Ready?"**', '下一句保持完整。', '他说：“很好！”', '最后一句。']
        source = ' '.join(expected)
        for kind in (ProtectedMarkdown, IncrementalMarkdown):
            doc = kind(source, 1000)
            self.assertEqual(originals(doc), expected)
            self.assertEqual(echo(doc), source)

    def test_budget_moves_whole_sentence_to_next_batch(self):
        sentences = [('First ' + 'word ' * 100 + 'ends.'),
                     ('Second ' + 'word ' * 100 + 'ends.'), 'Third sentence.']
        for kind in (ProtectedMarkdown, IncrementalMarkdown):
            doc = kind(' '.join(sentences), 1000)
            self.assertEqual(len(doc.chunks), 2)
            outputs = [doc.restore(c.text, c) for c in doc.chunks]
            self.assertEqual(outputs[0].strip(), sentences[0])
            self.assertEqual(outputs[1].strip(), ' '.join(sentences[1:]))
            self.assertTrue(all(len(c.text) <= 1000 for c in doc.chunks))

    def test_quoted_and_parenthetical_sentences_stay_together(self):
        expected = ['He said "Stop!" and left.', 'She wrote “First. Second.”',
                    'A result (First case. Second case.) is available.', 'Next sentence.']
        doc = IncrementalMarkdown(' '.join(expected))
        self.assertEqual(originals(doc), expected)
        self.assertEqual(echo(doc), doc.source)

    def test_long_sentence_fails_before_any_network_request(self):
        source = 'This is one sentence ' + 'without punctuation ' * 65 + '.'
        with patch('app.translation_markdown.ChatRequest.start') as send:
            for kind in (ProtectedMarkdown, IncrementalMarkdown):
                with self.assertRaises(ValueError): kind(source, 1000)
                self.assertEqual(echo(kind(source, 2000)), source)
            config = TranslationConfig('http://localhost:1234/v1', 'fixture', chunk_size=1000)
            with self.assertRaises(ValueError): TranslationJob(config, source, 'auto', 'English')
            send.assert_not_called()

    def test_markdown_blocks_and_protected_inline_content(self):
        source = ('# Heading\nWrapped prose with $a.b$ and `first. second`\ncontinues here.\n\n'
                  '- First list item\n  wraps without a sentence ending\n- Second list item\n\n'
                  '```py\nprint("First. Second.")\n```\n\n'
                  '| Head | Value |\n| --- | --- |\n| Name | 3.14 |\n\n'
                  '[Link](https://example.org/v1.2) is **important.** Next sentence.\n')
        for kind in (ProtectedMarkdown, IncrementalMarkdown):
            doc = kind(source, 1000)
            units = originals(doc)
            self.assertIn('Wrapped prose with $a.b$ and `first. second`\ncontinues here.', units)
            self.assertIn('- First list item\n  wraps without a sentence ending', units)
            self.assertIn('[Link](https://example.org/v1.2) is **important.**', units)
            self.assertEqual(echo(doc), source)

    def test_complete_bounded_context_and_no_protected_content_leak(self):
        source = 'Before sentence. Current sentence. After sentence.'
        for kind in (ProtectedMarkdown, IncrementalMarkdown):
            doc = kind(source, 25)
            chunk = next(c for c in doc.chunks if 'Current' in c.text)
            context = doc.context_for(chunk)
            self.assertEqual(context['context_before'], 'Before sentence.')
            self.assertEqual(context['context_after'], 'After sentence.')
        initial = IncrementalMarkdown('Long ' + 'previous ' * 40 + 'sentence. Current sentence. After $secret$ sentence.')
        echo(initial)
        changed = IncrementalMarkdown(initial.source.replace('Current', 'Changed'), previous=initial)
        chunk = next(c for c in changed.chunks if changed.needs_translation(c))
        context = changed.context_for(chunk)
        self.assertEqual(context['context_before'], '')
        self.assertEqual(context['context_after'], 'After sentence.')
        self.assertNotIn('secret', str(context))

    def test_cache_units_do_not_depend_on_batch_size(self):
        source = ' '.join('Sentence number %d ends here.' % i for i in range(400))
        first = IncrementalMarkdown(source, 4000); echo(first)
        changed = IncrementalMarkdown(source.replace('number 20 ', 'number twenty '), 1000, first)
        self.assertEqual(changed.changed_units, 1)
        self.assertEqual(changed.reused_units, 399)
        self.assertEqual(echo(changed), changed.source)


if __name__ == '__main__': unittest.main()
