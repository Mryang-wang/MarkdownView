"""Model connection and editable translation prompts."""
import json
import sys

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import (
    QAbstractSpinBox, QCheckBox, QComboBox, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QPlainTextEdit, QPushButton, QSpinBox, QToolButton, QVBoxLayout, QWidget,
)

from .i18n import t
from .dialog_theme import AppDialog, style_dialog
from .translation import ChatRequest, TranslationConfig, load_config, save_config


PRESET_PROMPTS = {
    "通用翻译": "Translate accurately and naturally into {target_language}. Preserve the author's meaning and tone.",
    "学术论文": "Translate into formal academic {target_language}. Use precise terminology, preserve uncertainty, citations, numbers and units. Never add claims or explanations.",
    "技术文档": "Translate into clear technical {target_language}. Keep product names, API names and identifiers unchanged. Use consistent engineering terminology and concise instructions.",
    "商务沟通": "Translate into professional, polite {target_language}. Keep commitments, dates, amounts and names exact. Avoid exaggeration.",
    "自然易读": "Translate into fluent, accessible {target_language} for general readers. Use natural expressions while preserving all factual details. Do not summarize or omit content.",
}


def load_prompts():
    try:
        custom = json.loads(QSettings().value("translation/prompts", "{}"))
        custom = {k: v for k, v in custom.items() if isinstance(k, str) and isinstance(v, str) and len(v) <= 12000}
    except (ValueError, TypeError, AttributeError):
        custom = {}
    return {**PRESET_PROMPTS, **custom}


class PromptDialog(AppDialog):
    def __init__(self, parent, name, body, theme):
        super().__init__(parent)
        self.setWindowTitle(t("编辑翻译提示词"))
        self.resize(670, 480)
        style_dialog(self, theme)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)
        layout.addWidget(label("翻译提示词", "title"))
        self.name = QLineEdit(name)
        self.name.setMaxLength(80)
        self.name.setPlaceholderText(t("输入名称；使用新名称即可新增预设"))
        layout.addWidget(self.name)
        self.body = QPlainTextEdit(body)
        layout.addWidget(self.body, 1)
        layout.addWidget(label("可使用 {source_language} 和 {target_language}。提示词控制风格和专业要求；Markdown 保护规则始终生效。", "muted"))
        self.status = label("")
        layout.addWidget(self.status)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        remove = QPushButton(t("删除自定义 / 恢复预设"))
        remove.clicked.connect(self._remove)
        buttons.addButton(remove, QDialogButtonBox.ButtonRole.ActionRole)
        layout.addWidget(buttons)

    def _custom(self):
        try:
            data = json.loads(QSettings().value("translation/prompts", "{}"))
            return data if isinstance(data, dict) else {}
        except (ValueError, TypeError):
            return {}

    def _save(self):
        name, body = self.name.text().strip(), self.body.toPlainText().strip()
        if not name or not body or len(body) > 12000:
            self.status.setText(t("请填写名称和提示词，正文不超过 12000 字符。"))
            return
        data = self._custom()
        data[name] = body
        QSettings().setValue("translation/prompts", json.dumps(data, ensure_ascii=False))
        self.accept()

    def _remove(self):
        data = self._custom()
        data.pop(self.name.text().strip(), None)
        QSettings().setValue("translation/prompts", json.dumps(data, ensure_ascii=False))
        self.accept()


def label(text, role=None):
    widget = QLabel(t(text))
    widget.setWordWrap(True)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    if role:
        widget.setProperty("role", role)
    return widget


def step_control(spin):
    """Use separate, predictable hit targets instead of native theme spinner arrows."""
    row = QWidget()
    layout = QHBoxLayout(row); layout.setContentsMargins(0, 0, 0, 0); layout.setSpacing(6)
    spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
    spin.setMinimumHeight(36)
    layout.addWidget(spin, 1)
    for name, text, caption, action in (("decrease_button", "−", "减少数值", spin.stepDown),
                                        ("increase_button", "+", "增加数值", spin.stepUp)):
        button = QToolButton(); button.setText(text); button.setFixedSize(34, 34)
        button.setProperty("role", "stepper"); button.setAutoRepeat(True)
        button.setToolTip(t(caption)); button.setAccessibleName(t(caption)); button.clicked.connect(action)
        setattr(spin, name, button); layout.addWidget(button)
    def enabled():
        spin.decrease_button.setEnabled(spin.value() > spin.minimum())
        spin.increase_button.setEnabled(spin.value() < spin.maximum())
    spin.valueChanged.connect(enabled); enabled()
    return row


class TranslationSettingsDialog(AppDialog):
    def __init__(self, parent, theme="light"):
        super().__init__(parent)
        self.setWindowTitle(t("翻译模型设置"))
        self.setMinimumWidth(520)
        self.resize(650, 680)
        style_dialog(self, theme)
        self.config = load_config()
        self.request = ChatRequest(self)
        self.request.succeeded.connect(lambda _: self._tested(t("连接成功，模型已返回有效响应。")))
        self.request.failed.connect(self._tested)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 14, 24, 12)
        layout.setSpacing(14)
        layout.addWidget(label("选择服务支持的接口类型，可连接远程或本机的 HTTP / HTTPS 服务。", "muted"))
        form = QFormLayout()
        form.setSpacing(12)
        self.protocol = QComboBox()
        for text, value in (("OpenAI Chat Completions", "chat"), ("OpenAI Responses", "responses"), ("Anthropic Messages", "anthropic")):
            self.protocol.addItem(text, value)
        self.protocol.setCurrentIndex(max(0, self.protocol.findData(self.config.protocol)))
        form.addRow(t("接口类型"), self.protocol)
        self.endpoint = QLineEdit(self.config.endpoint)
        self.endpoint.setPlaceholderText("https://api.example.com/v1")
        self.endpoint.textEdited.connect(self._endpoint_changed)
        self.model = QLineEdit(self.config.model)
        self.model.setPlaceholderText(t("填写服务商提供的模型名称"))
        self.key = QLineEdit(self.config.key)
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        self.key.setPlaceholderText(t("本机免鉴权服务可留空"))
        self.key.setMaxLength(4096)
        key_row = QHBoxLayout()
        key_row.addWidget(self.key, 1)
        show = QCheckBox(t("显示"))
        show.toggled.connect(lambda checked: self.key.setEchoMode(
            QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password))
        key_row.addWidget(show)
        form.addRow(t("服务地址"), self.endpoint)
        self.endpoint_preview = label("", "muted")
        form.addRow("", self.endpoint_preview)
        form.addRow(t("模型名称"), self.model)
        form.addRow("API Key", key_row)
        self.remember = QCheckBox(t("在此 Windows 账户中加密保存密钥"))
        self.remember.setEnabled(sys.platform == "win32")
        self.remember.setChecked(self.config.remember and sys.platform == "win32")
        form.addRow("", self.remember)
        self.stream = QCheckBox(t("流式接收译文"))
        self.stream.setToolTip(t("边接收边显示译文；需要服务支持流式返回。"))
        self.stream.setChecked(self.config.stream)
        form.addRow(t("响应方式"), self.stream)
        self.timeout = QSpinBox()
        self.timeout.setRange(10, 3600)
        self.timeout.setValue(self.config.timeout)
        self.timeout.setSuffix(t(" 秒"))
        self.chunk_size = QSpinBox()
        self.chunk_size.setRange(1000, 32000)
        self.chunk_size.setSingleStep(1000)
        self.chunk_size.setValue(self.config.chunk_size)
        self.chunk_size.setToolTip(t("按完整句子合并发送，包含格式保护标记；提示词和上下文另计。单句超限时提示调整，不从中间截断。"))
        form.addRow(t("每段超时"), step_control(self.timeout))
        form.addRow(t("每次正文上限"), step_control(self.chunk_size))
        form.addRow("", label("按完整句子发送；单句超限时提示调整。", "muted"))
        self.max_tokens = QSpinBox(); self.max_tokens.setRange(1, 131072); self.max_tokens.setSingleStep(1024)
        self.max_tokens.setValue(self.config.max_tokens)
        self.max_tokens.setToolTip(t("Anthropic 接口必填；上限取决于服务和模型。"))
        self.max_tokens_label = label("最大输出 Token 数")
        self.max_tokens_control = step_control(self.max_tokens)
        form.addRow(self.max_tokens_label, self.max_tokens_control)
        self.protocol.currentIndexChanged.connect(self._protocol_changed)
        self.endpoint.textChanged.connect(self._preview_endpoint)
        self._protocol_changed()
        layout.addLayout(form)
        layout.addWidget(label("不勾选加密保存时，密钥仅保留到软件退出。翻译会将所选正文及术语表发送到你配置的服务，费用由该服务收取。", "muted"))
        layout.addStretch()
        footer = QVBoxLayout()
        footer.setContentsMargins(24, 0, 24, 12)
        footer.setSpacing(10)
        self.status = label("")
        self.status.setMinimumHeight(38)
        footer.addWidget(self.status)
        row = QHBoxLayout()
        self.test_button = QPushButton(t("测试连接"))
        self.test_button.clicked.connect(self._test)
        row.addWidget(self.test_button)
        row.addStretch()
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.StandardButton.Save).setProperty("role", "primary")
        row.addWidget(buttons)
        footer.addLayout(row)
        self.set_footer_layout(footer)
        self.finished.connect(lambda _: self.request.cancel())

    def _endpoint_changed(self, value):
        from urllib.parse import urlsplit
        try:
            if urlsplit(value).netloc != urlsplit(self.config.endpoint).netloc and self.key.text() == self.config.key:
                self.key.clear()
        except ValueError:
            pass

    def _protocol_changed(self):
        visible = self.protocol.currentData() == "anthropic"
        self.max_tokens_label.setVisible(visible); self.max_tokens_control.setVisible(visible)
        self._preview_endpoint()

    def _preview_endpoint(self):
        try:
            value = TranslationConfig(endpoint=self.endpoint.text(), protocol=self.protocol.currentData()).url()
            self.endpoint_preview.setText(t("实际接口：{0}").format(value))
        except ValueError:
            self.endpoint_preview.setText(t("可填写服务根地址、版本地址或完整接口地址。"))

    def values(self):
        config = TranslationConfig(self.endpoint.text().strip(), self.model.text().strip(),
                                   self.key.text().strip(), self.remember.isChecked(),
                                   self.stream.isChecked(), self.timeout.value(), self.chunk_size.value(),
                                   self.protocol.currentData(), self.max_tokens.value())
        config.validate()
        return config

    def _test(self):
        if self.request.reply is not None:
            self.request.cancel()
            self._tested(t("已取消连接测试。"))
            return
        try:
            config = self.values()
            self.request.start(config, [{"role": "user", "content": "Reply with OK only."}])
        except ValueError as error:
            self.status.setText(str(error))
            return
        self.test_button.setText(t("取消测试"))
        self.status.setText(t("正在测试连接…"))

    def _tested(self, message):
        self.test_button.setText(t("测试连接"))
        self.status.setText(message)

    def _save(self):
        try:
            config = self.values()
            save_config(config)
        except (ValueError, OSError) as error:
            self.status.setText(str(error))
            return
        self.config = config
        self.accept()
