"""将后续启动的打开请求转交给当前用户已运行的窗口。"""
import ctypes
import hashlib
import json
import os
from pathlib import Path
import time

from PySide6.QtCore import QLockFile, QObject, QStandardPaths, QTimer
from PySide6.QtNetwork import QLocalServer, QLocalSocket


class SingleInstance(QObject):
    def __init__(self, parent):
        super().__init__(parent)
        root = Path(os.environ.get("MDVIEW_DATA_DIR") or
                    QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation)).resolve()
        root.mkdir(parents=True, exist_ok=True)
        identity = hashlib.sha256(os.path.normcase(str(root)).encode("utf-8")).hexdigest()[:24]
        self.name = "MarkdownView-" + identity
        self.lock = QLockFile(str(root / "instance.lock"))
        self.lock.setStaleLockTime(0)
        self.server = QLocalServer(self)
        self.server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        self.server.newConnection.connect(self._accept_connections)
        self._handler = None
        self._pending = []

    def start_or_forward(self, paths):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            # Windows 允许两个 QLocalServer 同时监听同名管道，因此先持有进程锁。
            if self.lock.tryLock(0):
                QLocalServer.removeServer(self.name)
                if not self.server.listen(self.name):
                    self.lock.unlock()
                    raise RuntimeError("无法接收文档打开请求：" + self.server.errorString())
                return True
            if self.lock.error() != QLockFile.LockError.LockFailedError:
                raise RuntimeError("无法访问应用的窗口锁，请检查本地数据目录权限。")
            socket = QLocalSocket()
            socket.connectToServer(self.name)
            if socket.waitForConnected(200):
                if os.name == "nt":
                    pid, *_ = self.lock.getLockInfo()
                    if pid > 0:
                        ctypes.windll.user32.AllowSetForegroundWindow(pid)
                socket.write((json.dumps({"paths": paths}, ensure_ascii=False) + "\n").encode("utf-8"))
                socket.flush()
                remaining = max(1, int((deadline - time.monotonic()) * 1000))
                if (socket.bytesAvailable() or socket.waitForReadyRead(remaining)):
                    if bytes(socket.readAll()).strip() == b"ok":
                        socket.disconnectFromServer()
                        return False
            socket.abort()
            time.sleep(.05)
        raise RuntimeError("现有窗口暂时没有响应，请稍后重新打开文件。")

    def set_handler(self, handler):
        self._handler = handler
        self._dispatch_pending()

    def _accept_connections(self):
        while self.server.hasPendingConnections():
            socket = self.server.nextPendingConnection()
            socket._request = bytearray()
            socket.readyRead.connect(lambda s=socket: self._read_request(s))
            socket.disconnected.connect(socket.deleteLater)
            if socket.bytesAvailable():
                self._read_request(socket)

    def _read_request(self, socket):
        socket._request.extend(bytes(socket.readAll()))
        if b"\n" not in socket._request:
            return
        try:
            request = json.loads(socket._request.split(b"\n", 1)[0])
            paths = request["paths"]
            if not isinstance(paths, list) or not all(isinstance(path, str) for path in paths):
                raise ValueError("Invalid paths")
        except (ValueError, KeyError, TypeError):
            socket.disconnectFromServer()
            return
        self._pending.append(paths)
        socket.write(b"ok\n")
        socket.flush()
        socket.disconnectFromServer()
        QTimer.singleShot(0, self._dispatch_pending)

    def _dispatch_pending(self):
        if self._handler is not None:
            while self._pending:
                self._handler(self._pending.pop(0))

    def close(self):
        self.server.close()
        if self.lock.isLocked():
            QLocalServer.removeServer(self.name)
            self.lock.unlock()
