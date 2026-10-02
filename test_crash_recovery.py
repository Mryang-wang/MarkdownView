"""在独立进程中模拟异常退出，再启动并通过恢复面板取回文字与图片。"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def run_child(mode, profile):
    os.environ["MDVIEW_DATA_DIR"] = profile
    from PySide6.QtCore import Qt, QSettings, QTimer
    from PySide6.QtGui import QColor, QImage
    from PySide6.QtWidgets import QApplication
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    from app.main_window import MainWindow
    app = QApplication([])
    app.setOrganizationName("MarkdownViewCrashTest")
    app.setApplicationName("MarkdownViewCrashTest")
    QSettings().clear()
    window = MainWindow(restore_session=(mode == "restore"))
    window.show()
    status = {"failed": False}

    def wait_ready(callback):
        if all(tab.ready for tab in window._tab_list):
            QTimer.singleShot(300, callback)
        else:
            QTimer.singleShot(100, lambda: wait_ready(callback))

    if mode == "crash":
        def edit():
            tab = window.current_tab()
            image = QImage(40, 30, QImage.Format.Format_RGB32)
            image.fill(QColor("#6f8c76"))
            directory = window.store.asset_directory(tab.draft_id)
            tab.resource_dir = directory
            images = Path(directory) / "images"
            images.mkdir()
            image.save(str(images / "proof.png"))
            window._sync_md_dir(tab)
            tab.js("window.__setEditorValue('# 未保存的研究记录\\n\\nCrash recovery proof $x+y$.\\n\\n![证据](images/proof.png)');")
            QTimer.singleShot(1800, crash)

        def crash():
            drafts = window.store.drafts()
            if not drafts or "Crash recovery proof" not in drafts[0]["content"]:
                print("CRASH_CHECKPOINT: FAILED", flush=True)
                os._exit(2)
            print("CRASH_CHECKPOINT: WRITTEN", flush=True)
            # 不触发 closeEvent / QApplication 清理，模拟进程被终止。
            os._exit(77)

        wait_ready(edit)
    else:
        def find_dialog():
            dialog = getattr(window, "_recovery_dialog", None)
            if not dialog:
                QTimer.singleShot(100, find_dialog)
                return
            if dialog.list.count() != 1:
                status["failed"] = True
                app.exit(1)
                return
            dialog.restore_button.click()
            wait_ready(verify)

        def verify():
            tab = window.current_tab()
            code = """JSON.stringify({value:window.currentMarkdown(),
                images:Array.from(document.querySelectorAll('.vditor-ir img')).map(i=>i.complete&&i.naturalWidth>0)})"""
            def received(result):
                state = json.loads(result)
                passed = ("Crash recovery proof" in state["value"] and "\\(x+y\\)" in state["value"]
                          and state["images"] == [True] and tab.filepath is None and tab.dirty)
                print("CRASH_RESTORE:", "PASSED" if passed else "FAILED", flush=True)
                status["failed"] = not passed
                for editor in window._tab_list:
                    editor.dirty = False
                window.close()
                app.exit(0 if passed else 1)
            tab.view.page().runJavaScript(code, received)

        QTimer.singleShot(1400, find_dialog)

    QTimer.singleShot(20000, lambda: os._exit(3))
    result = app.exec()
    return result or int(status["failed"])


if __name__ == "__main__":
    if len(sys.argv) == 3:
        sys.exit(run_child(sys.argv[1], sys.argv[2]))
    with tempfile.TemporaryDirectory() as directory:
        crash = subprocess.run([sys.executable, __file__, "crash", directory], timeout=25)
        if crash.returncode != 77:
            raise SystemExit("Crash simulation did not write its draft")
        recovered = subprocess.run([sys.executable, __file__, "restore", directory], timeout=25)
        sys.exit(recovered.returncode)
