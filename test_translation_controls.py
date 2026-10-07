"""Real WebEngine: reader stop/resume button and bidirectional scroll alignment."""
import json
import os
import tempfile
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

from PySide6.QtCore import QEventLoop, QSettings, QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
from app.main_window import MainWindow
from app.translation import TranslationConfig, save_config
from test_translation import wait
from test_translation_streaming import Provider as StreamingProvider


class Provider(StreamingProvider):
    hold = None
    requests = []

    def do_POST(self):
        self.gates = self.hold if len(self.requests) == 1 else None
        super().do_POST()


def run():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory); os.environ['MDVIEW_DATA_DIR'] = str(root / 'profile')
        app = QApplication([]); app.setOrganizationName('MarkdownViewTranslationControlsTest'); app.setApplicationName('isolated')
        QSettings().clear()
        source = '# Hello world\n\n' + '\n\n'.join(
            'Hello paragraph %d. ' % i + ('Hello world. ' * (4 + i % 9)) for i in range(65)) + '\n'
        path = root / 'source.md'; path.write_text(source, encoding='utf-8')
        server = ThreadingHTTPServer(('127.0.0.1', 0), Provider)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        save_config(TranslationConfig(f'http://127.0.0.1:{server.server_port}/v1', 'Reader controls fixture', 'fake-key', chunk_size=1000))
        gates = [threading.Event(), threading.Event()]; Provider.hold = gates; Provider.requests = []
        win = MainWindow(startup_file=str(path)); win.resize(1460, 900); win.show()
        output = Path('tmp/translation-controls'); output.mkdir(parents=True, exist_ok=True)

        def ev(code):
            values = []; loop = QEventLoop()
            win.view.page().runJavaScript('JSON.stringify((()=>{' + code + '})())', lambda v: (values.append(v), loop.quit()))
            QTimer.singleShot(5000, loop.quit); loop.exec()
            assert values and values[0], code
            return json.loads(values[0])

        toggle = 'document.querySelector("[data-translation-action=toggle]")'
        panes = '''const container=Array.from(document.querySelectorAll('#vditor .vditor-ir,#vditor .vditor-sv,#vditor .vditor-wysiwyg')).find(n=>n.clientHeight>0);
            const root=container.querySelector(':scope > pre') || container;
            const left=root.scrollHeight>root.clientHeight?root:root.parentElement;
            const right=document.querySelector('.translation-article');'''

        def align(side, index):
            # Jump first, then align after offscreen content-visibility estimates
            # have been replaced by actual layout (especially after zooming).
            for _ in range(2):
                ev(panes + f'''
                    const box={side}, node={'root.children' if side == 'left' else "document.querySelectorAll('.translation-pair')"}[{index}];
                    const scale=box.getBoundingClientRect().height/box.offsetHeight;
                    box.scrollTop+=(node.getBoundingClientRect().top-box.getBoundingClientRect().top)/scale;
                    return true;''')
                QTest.qWait(180)
            result = ev(panes + f'''
                const a=root.children[{index}], b=document.querySelectorAll('.translation-pair')[{index}];
                return {{left:a.getBoundingClientRect().top-left.getBoundingClientRect().top,
                         right:b.getBoundingClientRect().top-right.getBoundingClientRect().top,
                         leftScroll:left.scrollTop,rightScroll:right.scrollTop,
                         sourceBlocks:root.children.length,targetBlocks:document.querySelectorAll('.translation-pair').length}};''')
            assert abs(result['left']) < 6 and abs(result['right']) < 12, (side, index, result)
            return result

        try:
            wait(lambda: win.current_tab().ready); QTest.qWait(200)
            before = ev('return currentMarkdown();')
            win.open_translation(win.current_tab(), 'full')
            wait(lambda: getattr(win.current_tab(), 'translation', None) and win.current_tab().translation.job is not None)
            controller = win.current_tab().translation
            wait(lambda: len(Provider.requests) == 2 and len(controller.job.parts) == 1)
            wait(lambda: ev('return ' + toggle + '.textContent;') == '停止翻译')
            retained = list(controller.job.parts)
            ev(toggle + '.click();' + toggle + '.click();return true;')
            wait(lambda: controller.job.state == 'cancelled')
            wait(lambda: ev('return ' + toggle + '.textContent;') == '继续翻译')
            count = len(Provider.requests); QTest.qWait(300); assert len(Provider.requests) == count
            assert controller.job.parts == retained
            Provider.hold = None
            for gate in gates: gate.set()
            ev(toggle + '.click();' + toggle + '.click();return true;')
            wait(lambda: controller.job.state == 'complete'); QTest.qWait(250)
            assert controller.job.parts[:len(retained)] == retained
            assert all(p['text'] != Provider.requests[0]['text'] for p in Provider.requests[2:])
            assert ev('return ' + toggle + '.textContent;') == '重新翻译'
            requests = len(Provider.requests)
            measurements = [align('left', 12), align('right', 28), align('left', 5)]
            ev('window.setDocumentZoom(1.3);return true;'); QTest.qWait(150)
            measurements.extend([align('right', 40), align('left', 17)])
            # Endpoints stay together and settle rather than feeding scroll events back.
            ev(panes + 'window.__scrollEvents=0;left.addEventListener("scroll",()=>window.__scrollEvents++);right.addEventListener("scroll",()=>window.__scrollEvents++);right.scrollTop=right.scrollHeight;return true;')
            QTest.qWait(300)
            assert ev(panes + 'return Math.abs(left.scrollTop-(left.scrollHeight-left.clientHeight))<3;')
            count = ev('return window.__scrollEvents;'); QTest.qWait(250)
            assert ev('return window.__scrollEvents;') == count and count < 12
            ev(panes + 'left.scrollTop=0;return true;'); QTest.qWait(150)
            assert ev(panes + 'return right.scrollTop;') < 2
            # Hidden/single-column views must not move the source editor.
            ev('const v=document.querySelector(".translation-view");v.value="translated";v.onchange();return true;')
            ev(panes + 'right.scrollTop=1000;return true;'); QTest.qWait(150)
            assert ev(panes + 'return left.scrollTop;') < 2
            ev('const v=document.querySelector(".translation-view");v.value="edit";v.onchange();return true;')
            QTest.qWait(150)
            # Source/low-resource mode uses reading progress, not mismatched lines.
            ev('window.setLightweight(true);return true;'); QTest.qWait(200)
            ev(panes + 'left.scrollTop=(left.scrollHeight-left.clientHeight)*0.45;return true;'); QTest.qWait(200)
            assert ev(panes + 'return Math.abs(right.scrollTop/(right.scrollHeight-right.clientHeight)-0.45)<0.02;')
            ev('window.setLightweight(false);window.setDocumentZoom(1);return true;'); QTest.qWait(200)
            assert len(Provider.requests) == requests
            # Explicit reset exposes Start without sending a request; the same top
            # button starts exactly one task, even on a quick double click.
            controller.action('reset', {}); QTest.qWait(150)
            assert ev('return ' + toggle + '.textContent;') == '开始翻译'
            ev(toggle + '.click();' + toggle + '.click();return true;')
            wait(lambda: controller.job and controller.job.state == 'complete'); QTest.qWait(150)
            assert len(Provider.requests) - requests == len(controller.job.document.chunks)
            win.set_language('en'); QTest.qWait(150)
            assert ev('return ' + toggle + '.textContent;') == 'Translate again'
            win.set_language('zh_CN'); QTest.qWait(100)
            win.grab().save(str(output / 'reader-light.png'))
            win.toggle_theme(); QTest.qWait(100); win.grab().save(str(output / 'reader-dark.png'))
            win.resize(780, 650); QTest.qWait(150)
            assert ev('const b=' + toggle + ',r=b.getBoundingClientRect();return r.left>=0&&r.right<=innerWidth&&r.top>=0&&r.bottom<=innerHeight;')
            win.grab().save(str(output / 'reader-narrow.png'))
            assert ev('return currentMarkdown();') == before and path.read_text(encoding='utf-8') == source
            assert not win.current_tab().dirty and not ev('return window.__err;')
            (output / 'alignment.json').write_text(json.dumps(measurements, indent=2), encoding='utf-8')
            print('PASS toolbar start/stop/resume without duplicate tasks, retained results, two-way paragraph/zoom/endpoints/progress sync, no feedback, locales/themes/narrow layout and no scroll API calls')
        finally:
            for gate in gates: gate.set()
            for tab in win._tab_list: tab.dirty = False
            win.close(); QTest.qWait(100); QSettings().clear(); server.shutdown(); server.server_close()


if __name__ == '__main__': run()
