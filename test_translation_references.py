"""Reference keys survive translation without hiding ordinary bracketed prose."""
import unittest

from app.translation_markdown import ProtectedMarkdown
from app.translation_memory import IncrementalMarkdown


def translate(source, kind=ProtectedMarkdown):
    document = kind(source)
    return ''.join(document.restore(chunk.text.replace('asset', 'translated').replace('visible', 'shown'), chunk)
                   for chunk in document.chunks)


class ReferenceProtection(unittest.TestCase):
    def test_implicit_images_and_links_retain_defined_keys(self):
        source = '![asset] and ![visible][asset] and ![visible](image.png).\n\n[asset][] and [asset].\n\n[asset]: image.png\n'
        for kind in (ProtectedMarkdown, IncrementalMarkdown):
            self.assertEqual(translate(source, kind), source)

    def test_explicit_link_text_still_translates(self):
        source = '[visible][asset] and [asset](https://example.org).\n\n[asset]: image.png\n'
        for kind in (ProtectedMarkdown, IncrementalMarkdown):
            self.assertEqual(translate(source, kind), source.replace('[visible]', '[shown]').replace('[asset](', '[translated]('))

    def test_undefined_brackets_and_code_do_not_become_references(self):
        source = '[asset] and [asset][] and ![asset].\n\n```md\n[asset]: image.png\n```\n\n`[asset]: image.png`\n'
        expected = source.replace('[asset]', '[translated]', 3)
        for kind in (ProtectedMarkdown, IncrementalMarkdown):
            self.assertEqual(translate(source, kind), expected)

    def test_case_whitespace_and_definition_after_code(self):
        source = '![ASSET NAME] and [asset   name][].\n\n```py\nasset = 1\n```\n[Asset name]: image.png\n'
        self.assertEqual(translate(source), source)

    def test_front_matter_and_comments_are_not_definitions(self):
        source = '---\n[asset]: image.png\n---\n\n[asset].\n\n<!--\n[asset]: image.png\n-->\n'
        self.assertEqual(translate(source), source.replace('\n[asset].', '\n[translated].'))


if __name__ == '__main__':
    unittest.main(verbosity=2)
