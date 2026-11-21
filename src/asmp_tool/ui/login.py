from __future__ import annotations

from urllib.parse import unquote, urlsplit

from PySide6.QtCore import QTimer, Qt, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtNetwork import QNetworkCookie
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from ..models import LOGIN_URL, TOKEN_COOKIE, UserError, validate_token

LOGIN_HINT = "请在海康官方网页输入账号和密码。登录成功后会自动验证会话。"
RENDERER_ERROR = "内置浏览器无法启动（{status}，代码 {code}）。请重新载入；如仍失败，可在系统浏览器打开官网。"


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

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setWindowTitle("ASMP 官方网页登录")
        self.resize(1120, 800)
        self._candidate = ""
        self._offered = False
        self._disposed = False
        self.renderer_error: tuple[str, int] | None = None
        self.page_loaded = False
        self.status = QLabel(LOGIN_HINT)
        self.status.setWordWrap(True)
        self.origin = QLabel("https://asmp.hikvision.com")
        self.origin.setObjectName("muted")
        self.view = QWebEngineView(self)
        # An unnamed profile is off-the-record: cookies/cache remain in memory.
        self.profile = QWebEngineProfile(self)
        self.profile.setHttpCacheType(QWebEngineProfile.HttpCacheType.MemoryHttpCache)
        self.profile.setPersistentCookiesPolicy(QWebEngineProfile.PersistentCookiesPolicy.NoPersistentCookies)
        self.page = self._create_page()
        self.profile.downloadRequested.connect(lambda download: download.cancel())
        self.profile.cookieStore().cookieAdded.connect(self._cookie_added)
        self.view.urlChanged.connect(self._url_changed)
        self.view.loadFinished.connect(self._loaded)
        reload_button = QPushButton("重新载入官网")
        reload_button.clicked.connect(self.reload_official_page)
        browser_button = QPushButton("在系统浏览器打开官网")
        browser_button.clicked.connect(self.open_in_browser)
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        top = QHBoxLayout()
        top.addWidget(self.origin, 1)
        top.addWidget(reload_button)
        top.addWidget(browser_button)
        top.addWidget(cancel)
        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.status)
        layout.addWidget(self.view, 1)
        QTimer.singleShot(0, self, self.reload_official_page)

    def _create_page(self) -> OfficialPage:
        page = OfficialPage(self.profile, self.view)
        page.settings().setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanAccessClipboard, False)
        page.settings().setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False)
        page.permissionRequested.connect(lambda permission: permission.deny())
        page.certificateError.connect(lambda error: error.rejectCertificate())
        page.blocked.connect(lambda: self.status.setText("已阻止离开 ASMP 官方域名，请在当前官网页面登录。"))
        page.renderProcessTerminated.connect(self._renderer_terminated)
        self.view.setPage(page)
        return page

    @Slot()
    def reload_official_page(self):
        if self._disposed:
            return
        if self.renderer_error:
            previous = self.page
            previous.renderProcessTerminated.disconnect(self._renderer_terminated)
            self.page = self._create_page()
            previous.deleteLater()
        self.renderer_error = None
        self.page_loaded = False
        self.status.setText("正在加载 ASMP 官网登录页…")
        self.view.load(QUrl(LOGIN_URL))

    @Slot()
    def open_in_browser(self):
        if QDesktopServices.openUrl(QUrl(LOGIN_URL)):
            self.status.setText("已在系统浏览器打开官网。系统浏览器的登录会话不会自动同步到本程序。")
        else:
            self.status.setText("无法启动系统浏览器，请手动访问 asmp.hikvision.com/sr/。")

    def _renderer_terminated(self, status, code):
        if self._disposed:
            return
        self.page_loaded = False
        self.renderer_error = status.name, code
        self.status.setText(RENDERER_ERROR.format(status=status.name, code=code))

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
        if self._disposed or self.renderer_error:
            return
        self.page_loaded = ok
        if not ok:
            self.status.setText("官网页面加载失败，请检查网络或访问权限后点击“重新载入官网”。")
        else:
            self.status.setText(LOGIN_HINT)
        self._maybe_ready()

    def _maybe_ready(self):
        if self._disposed or self.renderer_error or not self.page_loaded or not self._candidate or self._offered:
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
