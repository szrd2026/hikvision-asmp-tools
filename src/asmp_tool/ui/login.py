from __future__ import annotations

from urllib.parse import unquote, urlsplit

from PySide6.QtCore import Qt, QUrl, Signal, Slot
from PySide6.QtNetwork import QNetworkCookie
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from ..models import LOGIN_URL, TOKEN_COOKIE, UserError, validate_token


def official_url(url: str) -> bool:
    try:
        parsed = urlsplit(url)
        return parsed.scheme == "https" and parsed.hostname == "asmp.hikvision.com" and parsed.port in (None, 443) and parsed.username is None and parsed.password is None
    except ValueError:
        return False


def cookie_token(name: str, value: str, domain: str, path: str) -> str:
    api_path = "/api/sendRepairWeb/"
    if name != TOKEN_COOKIE or domain.lstrip(".").lower() not in {"asmp.hikvision.com", "hikvision.com"}:
        return ""
    path = path or "/"
    if not api_path.startswith(path) or not (path.endswith("/") or len(path) == len(api_path) or api_path[len(path):].startswith("/")):
        return ""
    try:
        return validate_token(unquote(value))
    except UserError:
        return ""


class OfficialPage(QWebEnginePage):
    blocked = Signal()

    def acceptNavigationRequest(self, url, navigation_type, is_main_frame):
        if is_main_frame and not official_url(url.toString()):
            self.blocked.emit()
            return False
        return True

    def createWindow(self, window_type):
        # Same-origin navigation still passes acceptNavigationRequest.
        return self

    def javaScriptConsoleMessage(self, level, message, line_number, source_id):
        # Website console output is not part of the host application's logs.
        pass


class LoginDialog(QDialog):
    token_ready = Signal(str)
    page_loaded = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setWindowTitle("ASMP 官方网页登录")
        self.resize(1120, 800)
        self._candidate = ""
        self._offered = False
        self._disposed = False
        self.status = QLabel("请在海康官方网页输入账号和密码。登录成功后会自动验证会话。")
        self.status.setWordWrap(True)
        self.origin = QLabel("https://asmp.hikvision.com")
        self.origin.setObjectName("muted")
        self.view = QWebEngineView(self)
        # An unnamed profile is off-the-record: cookies/cache remain in memory.
        self.profile = QWebEngineProfile(self)
        self.profile.setHttpCacheType(QWebEngineProfile.HttpCacheType.MemoryHttpCache)
        self.profile.setPersistentCookiesPolicy(QWebEngineProfile.PersistentCookiesPolicy.NoPersistentCookies)
        self.page = OfficialPage(self.profile, self.view)
        self.view.setPage(self.page)
        self.page.settings().setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanAccessClipboard, False)
        self.page.settings().setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False)
        self.page.permissionRequested.connect(lambda permission: permission.deny())
        self.page.certificateError.connect(lambda error: error.rejectCertificate())
        self.page.blocked.connect(lambda: self.status.setText("已阻止离开 ASMP 官方域名，请在当前官网页面登录。"))
        self.profile.downloadRequested.connect(lambda download: download.cancel())
        self.profile.cookieStore().cookieAdded.connect(self._cookie_added)
        self.view.urlChanged.connect(self._url_changed)
        self.view.loadFinished.connect(self._loaded)
        reload_button = QPushButton("重新载入官网")
        reload_button.clicked.connect(lambda: self.view.setUrl(QUrl(LOGIN_URL)))
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        top = QHBoxLayout()
        top.addWidget(self.origin, 1)
        top.addWidget(reload_button)
        top.addWidget(cancel)
        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.status)
        layout.addWidget(self.view, 1)
        self.view.setUrl(QUrl(LOGIN_URL))

    @Slot(QNetworkCookie)
    def _cookie_added(self, cookie):
        try:
            value = cookie_token(bytes(cookie.name()).decode("ascii"), bytes(cookie.value()).decode("utf-8"), cookie.domain(), cookie.path())
        except UnicodeError:
            return
        if value:
            self._candidate = value
            self._maybe_ready()

    @Slot(QUrl)
    def _url_changed(self, _url):
        self._maybe_ready()

    @Slot(bool)
    def _loaded(self, ok: bool):
        self.page_loaded.emit(ok)
        if not ok:
            self.status.setText("官网页面加载失败，请检查网络后点击“重新载入官网”。")
        self._maybe_ready()

    def _maybe_ready(self):
        if self._disposed or not self._candidate or self._offered:
            return
        source = self.view.url().toString()
        route = urlsplit(source)
        if not official_url(source) or not route.path.startswith("/sr/"):
            return
        if route.fragment.startswith(("/login", "/signup")):
            return
        self._offered = True
        self.token_ready.emit(self._candidate)
        self.accept()

    def done(self, result):
        if not self._disposed:
            self._disposed = True
            self._candidate = ""
            self.view.stop()
            # Profiles must outlive their pages; deferred deletes are queued in order.
            self.page.deleteLater()
            self.view.deleteLater()
            self.profile.deleteLater()
        super().done(result)
