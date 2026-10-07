"""Bounded project scans, snapshot retention and portable image references."""
import os
import queue
import tempfile
import zipfile
from pathlib import Path

from app.document_services import HistoryStore, ProjectScan, image_references, relocate_images, bundle_document


def run():
    with tempfile.TemporaryDirectory() as root:
        root = Path(root)
        project = root / 'project'; project.mkdir()
        (project / 'one.md').write_text('# Header\nneedle text\nNext needle\n', encoding='utf-8')
        (project / 'sub').mkdir(); (project / 'sub' / '二.md').write_text('中文 needle\n', encoding='utf-8')
        (project / 'node_modules').mkdir(); (project / 'node_modules' / 'skip.md').write_text('needle')
        (project / 'large.md').write_text('needle' * 400000)
        scan = ProjectScan(str(project), 'needle', True)
        result = []
        while True:
            item = scan.results.get(timeout=10)
            if item[0] == 'done': break
            result.append(item)
        assert len(result) == 3 and item[3] == 1, (result, item)
        assert {row[2] for row in result} == {1, 2, 3}
        scan = ProjectScan(str(project), '二', False)
        assert scan.results.get(timeout=10)[1].endswith('二.md')
        scan.cancelled.set(); scan.thread.join(2); assert not scan.thread.is_alive()
        history = HistoryStore(root, max_bytes=3500, per_file=3)
        path = str(project / 'one.md')
        for i in range(8): history.capture(path, str(i) * 1000)
        assert len(history.entries(path)) == 3
        history.capture(path, '7' * 1000); assert len(history.entries(path)) == 3
        history.capture(str(project / 'two.md'), 'a' * 2000)
        assert sum(p.stat().st_size for p in history.root.glob('*/*.md')) <= 3500
        image = project / '图 #1.png'; image.write_bytes(b'fake-image-for-copy-check')
        content = '![' + '图' + '](<图%20%231.png>)\n\n![again][asset]\n[asset]: <图%20%231.png>\n\n<img src="图%20%231.png" width="80">\n\n![remote](https://example.org/a.png)\n\n![missing](none.png)\n\n````md\n![code](none.png)\n```\n````\n'
        refs = image_references(content, str(project))
        assert len(refs) == 5, refs
        assert [r['status'] for r in refs].count('local') == 3, refs
        target = root / 'target'; target.mkdir()
        converted = relocate_images(content, str(project), str(target))
        assert len(list((target / 'images').iterdir())) == 1
        assert 'width="80"' in converted and '![code](none.png)' in converted
        assert all(r['status'] == 'local' for r in image_references(converted, str(target))[:3])
        archive = root / 'shared.zip'; bundle_document(content, str(project), str(archive), '共享.md')
        with zipfile.ZipFile(archive) as zipped:
            assert '共享.md' in zipped.namelist() and len(zipped.namelist()) == 2, zipped.namelist()
            assert 'https://example.org/a.png' in zipped.read('共享.md').decode('utf8')
        # Shortcut references are real images too, and must survive Save As / sharing.
        shortcut = '![asset]\n\n![ASSET][]\n\n![undefined]\n\n[asset]: <图%20%231.png>\n'
        refs = image_references(shortcut, str(project))
        assert len(refs) == 1 and refs[0]['status'] == 'local', refs
        shortcut_target = root / 'shortcut'; shortcut_target.mkdir()
        converted = relocate_images(shortcut, str(project), str(shortcut_target))
        assert '![undefined]' in converted and '![asset]' in converted
        assert image_references(converted, str(shortcut_target))[0]['status'] == 'local'
        bundle_document(shortcut, str(project), str(archive))
        with zipfile.ZipFile(archive) as zipped:
            assert len(zipped.namelist()) == 2, zipped.namelist()
            assert '[asset]: images/' in zipped.read('document.md').decode('utf8')
        history.max_bytes = 0; history.prune(); assert not list(history.root.glob('*/*.md'))
    print('PASS bounded scans, cancellation, history quotas, Markdown/image references and portable ZIP')


if __name__ == '__main__': run()
