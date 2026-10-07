"""Click the real spinner hit areas and verify model settings persistence."""
from pathlib import Path

from PySide6.QtCore import QSettings, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialogButtonBox, QScrollArea

from app.translation_dialog import TranslationSettingsDialog
from app.translation import load_config
from app.i18n import install_qt_language


def run():
    app = QApplication([]); app.setOrganizationName('MarkdownViewModelSettingsTest'); app.setApplicationName('isolated')
    QSettings().clear()
    install_qt_language()
    output = Path('tmp/model-settings'); output.mkdir(parents=True, exist_ok=True)
    try:
        for theme in ('light', 'dark'):
            dialog = TranslationSettingsDialog(None, theme); dialog.show(); QTest.qWait(100)
            dialog.grab().save(str(output / f'{theme}.png'))
            for spin in (dialog.timeout, dialog.chunk_size):
                before = spin.value()
                for button, expected in ((spin.increase_button, before + spin.singleStep()), (spin.decrease_button, before)):
                    assert button.width() >= 30 and button.height() >= 30
                    QTest.mouseClick(button, Qt.MouseButton.LeftButton)
                    assert spin.value() == expected, (theme, before, spin.value())
                spin.setValue(spin.maximum()); assert not spin.increase_button.isEnabled()
                spin.setValue(spin.minimum()); assert not spin.decrease_button.isEnabled()
            dialog.timeout.setValue(300); QTest.mouseClick(dialog.timeout.increase_button, Qt.MouseButton.LeftButton); assert dialog.timeout.value() == 301
            dialog.chunk_size.setValue(12000); QTest.mouseClick(dialog.chunk_size.increase_button, Qt.MouseButton.LeftButton); assert dialog.chunk_size.value() == 13000
            dialog.timeout.setFocus(); QTest.keyClick(dialog.timeout, Qt.Key.Key_Up); assert dialog.timeout.value() == 302
            dialog.endpoint.setText('http://203.0.113.8:8080/v1')
            dialog.model.setText('fixture')
            for protocol, suffix in (('chat', '/chat/completions'), ('responses', '/responses'), ('anthropic', '/messages')):
                dialog.protocol.setCurrentIndex(dialog.protocol.findData(protocol)); QTest.qWait(20)
                assert dialog.values().url().endswith(suffix)
                assert dialog.max_tokens_control.isVisible() == (protocol == 'anthropic')
                assert dialog.endpoint_preview.text().endswith(suffix)
            before = dialog.max_tokens.value()
            QTest.mouseClick(dialog.max_tokens.increase_button, Qt.MouseButton.LeftButton)
            assert dialog.max_tokens.value() == before + 1024
            QTest.mouseClick(dialog.max_tokens.decrease_button, Qt.MouseButton.LeftButton)
            assert dialog.max_tokens.value() == before
            save = dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Save)
            scroll = dialog.findChild(QScrollArea)
            for height in (500, 700):
                dialog.resize(650, height); QTest.qWait(50)
                for position in (0, scroll.verticalScrollBar().maximum()):
                    scroll.verticalScrollBar().setValue(position); QTest.qWait(20)
                    for button in (dialog.test_button, save):
                        point = button.mapTo(dialog, button.rect().center())
                        assert dialog.rect().contains(point) and dialog.childAt(point) is button
            dialog.grab().save(str(output / f'{theme}-anthropic.png'))
            dialog._save(); config = load_config()
            assert config.protocol == 'anthropic' and config.timeout == 302 and config.chunk_size == 13000
            dialog.close(); dialog.deleteLater()
        # Existing settings without a protocol retain Chat Completions behavior.
        QSettings().setValue('translation/config', '{"endpoint":"http://example.com/v1","model":"fixture"}')
        assert load_config().protocol == 'chat'
        print('PASS mouse/keyboard increment, old limits, bounds, both themes, protocol selection, URL preview, fixed footer and settings migration')
    finally:
        QSettings().clear()


if __name__ == '__main__': run()
