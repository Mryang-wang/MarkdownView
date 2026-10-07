"""Asynchronous Chat Completions, Responses and Anthropic Messages without SDKs."""
import base64
import ctypes
import json
import sys
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

from PySide6.QtCore import QObject, QSettings, QTimer, QUrl, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest
from PySide6.QtWidgets import QApplication

from .i18n import t


@dataclass
class TranslationConfig:
    endpoint: str = ""
    model: str = ""
    key: str = ""
    remember: bool = False
    stream: bool = True
    timeout: int = 90
    chunk_size: int = 4000
    protocol: str = "chat"
    max_tokens: int = 8192

    def url(self):
        value = self.endpoint.strip()
        try:
            parts = urlsplit(value)
            _ = parts.port
        except ValueError:
            raise ValueError(t("服务地址无效。")) from None
        if (parts.scheme not in ("https", "http") or not parts.hostname or
                parts.username is not None or parts.password is not None or
                parts.query or parts.fragment or any(c.isspace() for c in value)):
            raise ValueError(t("请填写完整的 HTTP 或 HTTPS 服务地址。"))
        routes = {"chat": "/chat/completions", "responses": "/responses", "anthropic": "/messages"}
        if self.protocol not in routes:
            raise ValueError(t("请选择支持的接口类型。"))
        path = parts.path.rstrip("/")
        for suffix in routes.values():
            if path.endswith(suffix):
                path = path[:-len(suffix)]
                break
        else:
            path = path or "/v1"
        path += routes[self.protocol]
        return urlunsplit((parts.scheme, parts.netloc, path, "", ""))

    def validate(self):
        self.url()
        if not self.model.strip() or len(self.model) > 200:
            raise ValueError(t("请填写模型名称。"))
        if len(self.key) > 4096 or any(ord(c) < 32 or ord(c) > 126 for c in self.key):
            raise ValueError(t("API Key 格式无效。"))
        if not 10 <= self.timeout <= 3600 or not 1000 <= self.chunk_size <= 32000:
            raise ValueError(t("超时或分段长度超出范围。"))
        if not 1 <= self.max_tokens <= 131072:
            raise ValueError(t("最大输出 Token 数超出范围。"))


def request_payload(config, messages):
    body = {"model": config.model.strip(), "stream": config.stream}
    if config.protocol == "chat":
        return {**body, "messages": messages}
    instructions = "\n\n".join(m["content"] for m in messages if m["role"] in ("system", "developer"))
    conversation = [m for m in messages if m["role"] not in ("system", "developer")]
    if config.protocol == "responses":
        return {**body, "instructions": instructions, "input": conversation, "store": False}
    body.update(messages=conversation, max_tokens=config.max_tokens)
    if instructions:
        body["system"] = instructions
    return body


def protect_key(value, decrypt=False):
    """Windows user-bound DPAPI, with prompts disabled. Never persist plain text."""
    if sys.platform != "win32":
        raise ValueError(t("此平台仅支持在本次运行中保存密钥。"))
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]

    raw = base64.b64decode(value, validate=True) if decrypt else value.encode("utf-8")
    buffer = ctypes.create_string_buffer(raw)
    source = Blob(len(raw), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    target = Blob()
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    function = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    function.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                         ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    function.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    if not function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise ValueError(t("Windows 无法读取或加密此密钥，请重新输入。"))
    try:
        result = ctypes.string_at(target.data, target.size)
        return result.decode("utf-8") if decrypt else base64.b64encode(result).decode("ascii")
    finally:
        kernel.LocalFree(target.data)


def load_config():
    settings = QSettings()
    try:
        data = json.loads(settings.value("translation/config", "{}"))
        config = TranslationConfig(**{k: v for k, v in data.items()
                                      if k in TranslationConfig.__dataclass_fields__ and k != "key"})
    except (ValueError, TypeError, AttributeError):
        config = TranslationConfig()
    saved = getattr(QApplication.instance(), "_translation_key", None)
    if saved and saved[0] == config.endpoint:
        config.key = saved[1]
    elif config.remember:
        try:
            encrypted = settings.value("translation/key", "")
            if encrypted:
                payload = json.loads(protect_key(encrypted, decrypt=True))
                if payload["endpoint"] == config.endpoint:
                    config.key = payload["key"]
        except (ValueError, KeyError, TypeError, OSError):
            pass  # A moved profile must ask for a fresh key, never use another credential.
    return config


def save_config(config):
    config.validate()
    encrypted = protect_key(json.dumps({"endpoint": config.endpoint, "key": config.key})) \
        if config.remember and config.key else ""
    settings = QSettings()
    data = {k: v for k, v in vars(config).items() if k != "key"}
    settings.setValue("translation/config", json.dumps(data))
    if encrypted:
        settings.setValue("translation/key", encrypted)
    else:
        settings.remove("translation/key")
    settings.sync()
    QApplication.instance()._translation_key = (config.endpoint, config.key)


class ChatRequest(QObject):
    delta = Signal(str)
    succeeded = Signal(str)
    failed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.manager = QNetworkAccessManager(self)
        self.reply = None
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(lambda: self._fail(t("请求超时，可重试当前段落。")))

    def start(self, config, messages):
        config.validate()
        self.cancel()
        self.buffer = bytearray()
        self.raw = bytearray()
        self.event_lines = []
        self.output = ""
        self.finish_reason = None
        self.done = False
        self.received = 0
        self.protocol = config.protocol
        request = QNetworkRequest(QUrl(config.url()))
        request.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader, "application/json")
        request.setRawHeader(b"Accept", b"text/event-stream, application/json")
        if config.protocol == "anthropic":
            request.setRawHeader(b"anthropic-version", b"2023-06-01")
            if config.key:
                request.setRawHeader(b"x-api-key", config.key.encode("ascii"))
        elif config.key:
            request.setRawHeader(b"Authorization", ("Bearer " + config.key).encode("ascii"))
        request.setAttribute(QNetworkRequest.Attribute.RedirectPolicyAttribute,
                             QNetworkRequest.RedirectPolicy.ManualRedirectPolicy)
        request.setTransferTimeout(config.timeout * 1000)
        body = json.dumps(request_payload(config, messages), ensure_ascii=False).encode("utf-8")
        reply = self.manager.post(request, body)
        self.reply = reply
        reply.readyRead.connect(lambda: self._read(reply))
        reply.finished.connect(lambda: self._finished(reply))
        self.timer.start(config.timeout * 1000)

    def cancel(self):
        self.timer.stop()
        reply, self.reply = self.reply, None
        if reply is not None:
            reply.abort()
            reply.deleteLater()

    def _fail(self, message):
        if self.reply is None:
            return
        self.cancel()
        self.failed.emit(message)

    def _read(self, reply):
        if reply is not self.reply:
            return
        data = bytes(reply.readAll())
        self.received += len(data)
        if self.received > 8 * 1024 * 1024:
            self._fail(t("服务响应过大，请减小分段长度。"))
            return
        status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute) or 0
        if status >= 300:
            return  # Never echo an arbitrary provider error body or a credential.
        mime = bytes(reply.rawHeader("Content-Type")).lower()
        if b"text/event-stream" not in mime:
            self.raw.extend(data)
            return
        self.buffer.extend(data)
        while b"\n" in self.buffer and self.reply is reply:
            line, _, rest = self.buffer.partition(b"\n")
            self.buffer = bytearray(rest)
            try:
                line = line.rstrip(b"\r").decode("utf-8")
                if not line:
                    self._event()
                elif line.startswith("data:"):
                    self.event_lines.append(line[5:].lstrip(" "))
            except (ValueError, TypeError, KeyError, IndexError, AttributeError):
                self._fail(t("服务返回了无法解析的数据。"))

    def _event(self):
        if not self.event_lines:
            return
        data = "\n".join(self.event_lines)
        self.event_lines.clear()
        if data == "[DONE]":
            if self.protocol == "chat": self.done = True
            return
        self._consume(json.loads(data), streaming=True)

    def _consume(self, data, streaming=False):
        if not isinstance(data, dict) or data.get("error") or data.get("type") == "error":
            raise ValueError("provider error")
        if self.protocol == "responses":
            self._responses(data, streaming)
            return
        if self.protocol == "anthropic":
            self._anthropic(data, streaming)
            return
        choices = data.get("choices", [])
        if not choices:  # A final usage-only event is permitted.
            return
        choice = choices[0]
        message = choice.get("delta" if streaming else "message", {}) or {}
        if message.get("refusal") or message.get("tool_calls"):
            raise ValueError("no translation")
        content = message.get("content") or ""
        if not isinstance(content, str):
            raise ValueError("unsupported content")
        if content:
            self.output += content
            self.delta.emit(content)
        if choice.get("finish_reason"):
            self.finish_reason = choice["finish_reason"]

    def _append(self, text):
        if not isinstance(text, str):
            raise ValueError("unsupported content")
        if text:
            self.output += text
            self.delta.emit(text)

    def _response_text(self, response):
        text = []
        for item in response.get("output", []):
            kind = item.get("type")
            if kind == "reasoning":
                continue
            if kind != "message":
                raise ValueError("unsupported output")
            for block in item.get("content", []):
                if block.get("type") != "output_text" or not isinstance(block.get("text"), str):
                    raise ValueError("no translation")
                text.append(block["text"])
        return "".join(text)

    def _responses(self, data, streaming):
        kind = data.get("type", "")
        if streaming and kind == "response.output_text.delta":
            self._append(data["delta"])
        elif streaming and (kind.startswith("response.refusal.") or kind == "response.failed"):
            raise ValueError("no translation")
        elif not streaming or kind in ("response.completed", "response.incomplete"):
            response = data.get("response", {}) if streaming else data
            if response.get("error"):
                raise ValueError("provider error")
            status = response.get("status")
            if status == "incomplete" and (response.get("incomplete_details") or {}).get("reason") == "max_output_tokens":
                self.finish_reason, self.done = "length", True
                return
            if status != "completed":
                raise ValueError("incomplete response")
            complete = self._response_text(response)
            if complete:
                if not complete.startswith(self.output):
                    raise ValueError("inconsistent response")
                self._append(complete[len(self.output):])
            self.finish_reason, self.done = "stop", True

    def _anthropic_blocks(self, blocks):
        for block in blocks:
            kind = block.get("type")
            if kind == "text":
                self._append(block["text"])
            elif kind not in ("thinking", "redacted_thinking"):
                raise ValueError("no translation")

    def _anthropic_stop(self, reason):
        if reason:
            self.finish_reason = {"end_turn": "stop", "stop_sequence": "stop", "max_tokens": "length"}.get(reason, reason)

    def _anthropic(self, data, streaming):
        if not streaming:
            if data.get("type") != "message": raise ValueError("invalid message")
            self._anthropic_blocks(data.get("content", []))
            self._anthropic_stop(data.get("stop_reason"))
            self.done = True
            return
        kind = data.get("type")
        if kind == "message_start":
            self._anthropic_blocks(data.get("message", {}).get("content", []))
        elif kind == "content_block_start":
            self._anthropic_blocks([data["content_block"]])
        elif kind == "content_block_delta":
            delta = data["delta"]
            if delta.get("type") == "text_delta": self._append(delta["text"])
            elif delta.get("type") == "input_json_delta": raise ValueError("no translation")
        elif kind == "message_delta":
            self._anthropic_stop(data.get("delta", {}).get("stop_reason"))
        elif kind == "message_stop":
            self.done = True

    def _finished(self, reply):
        if reply is not self.reply:
            return
        self._read(reply)
        if reply is not self.reply:
            return
        status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute) or 0
        if status != 200:
            details = {401: "密钥无效或已过期。", 403: "服务拒绝访问，请检查权限。",
                       404: "接口或模型不存在，请检查服务地址和模型名称。",
                       429: "服务限流或额度不足，请稍后重试。"}
            message = t(details.get(status, "连接失败，请检查网络、服务地址或稍后重试。"))
            if 300 <= status < 400:
                message = t("服务返回了重定向，请直接填写最终接口地址。")
            self._fail(message + (f" (HTTP {status})" if status else ""))
            return
        if reply.error() != reply.NetworkError.NoError:
            self._fail(t("连接中断，可重试当前段落。"))
            return
        try:
            if self.raw:
                self._consume(json.loads(self.raw))
                self.done = True
            else:
                # Accept a final event without its optional trailing blank line.
                if self.buffer:
                    line = self.buffer.decode("utf-8").strip()
                    if line.startswith("data:"):
                        self.event_lines.append(line[5:].lstrip())
                self._event()
            if self.finish_reason == "length":
                self._fail(t("译文被模型截断，请减小分段长度后重新翻译。"))
                return
            if self.finish_reason not in (None, "stop") or not (self.done or self.finish_reason == "stop"):
                raise ValueError("incomplete response")
            if self.protocol != "chat" and (not self.done or self.finish_reason != "stop"):
                raise ValueError("missing completion event")
            if not self.output.strip():
                raise ValueError("empty response")
        except (ValueError, TypeError, KeyError, IndexError, AttributeError):
            self._fail(t("服务响应为空、不完整或格式不兼容。"))
            return
        output = self.output
        self.timer.stop()
        self.reply = None
        reply.deleteLater()
        self.succeeded.emit(output)
