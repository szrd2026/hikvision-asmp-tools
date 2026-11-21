from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QSignalBlocker, QThread, QTimer, Qt, QUrl, Slot
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QCompleter, QFileDialog, QGridLayout, QGroupBox,
    QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLayout, QLineEdit, QMainWindow,
    QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QSizePolicy, QSpinBox, QSplitter,
    QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
)

from .. import __version__
from ..api import ApiClient, AuthenticationExpired, SecurityBlocked
from ..config import ConfigStore, atomic_json
from ..engine import BatchEngine, ItemResult, Summary
from ..journal import Journal, STATE_LABELS
from ..models import (
    CLIENT_HISTORY_LIMIT, DEAL_OPTIONS, FAULT_OPTIONS, REPAIR_OPTIONS, RETURN_OPTIONS,
    Settings, UserError, display_time, parse_serials, validate_token,
)
from .login import LoginDialog
from .worker import TaskWorker

ITEM_LABELS = dict(STATE_LABELS, querying="查询中", submitting="提交中", queried="已查询", skipped="已跳过", cancelled="已停止")
COLORS = {"succeeded": "#187448", "queried": "#187448", "failed": "#b42318", "rejected": "#b42318",
          "unknown": "#b15b00", "pending": "#b15b00", "auth": "#b42318"}
STYLE = """
QMainWindow, QDialog { background: #f5f6f8; }
QWidget { font-size: 13px; color: #263244; }
QLabel#title { font-size: 23px; font-weight: 600; }
QLabel#muted { color: #697586; }
QLabel#auth { color: #697586; padding: 5px 12px; background: #edf0f4; border-radius: 10px; }
QGroupBox { background: white; border: 1px solid #dde2e9; border-radius: 7px; margin-top: 12px; padding: 12px 9px 9px; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 5px; font-weight: 600; }
QLineEdit, QComboBox, QSpinBox, QPlainTextEdit, QTableWidget { background: white; border: 1px solid #d6dce5; border-radius: 4px; }
QLineEdit, QComboBox, QSpinBox { min-height: 27px; padding: 2px 7px; }
QPushButton { background: white; border: 1px solid #cfd6e1; border-radius: 5px; padding: 7px 13px; }
QPushButton:hover { background: #eef1f6; }
QPushButton#primary { background: #ce2029; color: white; border-color: #ce2029; font-weight: 600; }
QPushButton#primary:hover { background: #b91c24; }
QPushButton:disabled { color: #98a1b1; background: #eef0f3; border-color: #e1e5eb; }
QHeaderView::section { background: #f1f3f7; padding: 8px; border: 0; border-bottom: 1px solid #dce2eb; }
QTabWidget::pane { border: 0; }
QTabBar::tab { padding: 9px 18px; }
QTabBar::tab:selected { color: #c51e28; border-bottom: 2px solid #c51e28; }
QProgressBar { border: 0; background: #e5e9ef; border-radius: 3px; min-height: 8px; max-height: 8px; }
QProgressBar::chunk { background: #ce2029; border-radius: 3px; }
"""


class MainWindow(QMainWindow):
    def __init__(self, config: ConfigStore, journal: Journal, settings: Settings, token: str = "", *, client_factory=ApiClient, diagnostics: bool = False):
        super().__init__()
        self.config_store = config
        self.journal = journal
        self.api_factory = client_factory
        self.engine = BatchEngine(journal, client_factory)
        self.diagnostics = diagnostics
        self._thread = None
        self._worker = None
        self._login_dialog = None
        self._completion = None
        self._busy = False
        self._secrets: set[str] = set()
        self._rows: dict[str, int] = {}
        self._history = []
        self._description_history = set()
        self._client_history = settings.repair_client_history
        self._committed_client = settings.repair_client.strip()
        self._saved_settings = settings if config.path.exists() else None
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(600)
        self._save_timer.timeout.connect(self._autosave_settings)
        self.last_error = ""
        self.last_summary = None
        self.log_directory = config.directory / "logs"
        self.log_directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.log_path = self.log_directory / ("app_" + datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid4().hex[:6] + ".log")
        self.setWindowTitle(f"海康 ASMP 批量登记工具 · {__version__}")
        self.resize(1220, 900)
        # Let Qt derive the minimum height when the return-address rows expand.
        self.setMinimumWidth(1020)
        self.setStyleSheet(STYLE)
        self._build_ui(settings)
        self.token_edit.setText(token)
        self._remember_token(token)
        self.refresh_history()
        self.refresh_descriptions()
        self._connect_autosave()
        self.log("就绪。先登录，再查询资料或提交登记。")

    def _build_ui(self, settings):
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(20, 15, 20, 15)
        title_row = QHBoxLayout()
        title = QLabel("ASMP 批量登记")
        title.setObjectName("title")
        subtitle = QLabel(f"Python 跨平台版  {__version__}")
        subtitle.setObjectName("muted")
        self.auth_status = QLabel("未验证登录")
        self.auth_status.setObjectName("auth")
        title_row.addWidget(title)
        title_row.addWidget(subtitle)
        title_row.addStretch()
        title_row.addWidget(self.auth_status)
        layout.addLayout(title_row)

        login_group = QGroupBox("登录会话")
        login_layout = QHBoxLayout(login_group)
        self.token_edit = QLineEdit()
        self.token_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.token_edit.setPlaceholderText("点击官方网页登录自动获取；也可粘贴令牌，仅本次会话使用")
        self.token_edit.textChanged.connect(lambda: self.auth_status.setText("未验证登录"))
        self.login_button = QPushButton("官方网页登录")
        self.login_button.setObjectName("primary")
        self.login_button.clicked.connect(self.show_login)
        self.check_button = QPushButton("检查登录")
        self.check_button.clicked.connect(lambda: self.check_login())
        login_layout.addWidget(self.token_edit, 1)
        login_layout.addWidget(self.login_button)
        login_layout.addWidget(self.check_button)
        layout.addWidget(login_group)

        self.settings_group = QGroupBox("登记设置")
        self.settings_group.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        grid = QGridLayout(self.settings_group)
        self.client_combo = QComboBox()
        self.client_combo.setEditable(True)
        self.client_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.client_combo.setMaxVisibleItems(12)
        self.client_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.client_combo.setToolTip("选择历史客户后，请核对联系人、电话和退回地址。")
        self.client_edit = self.client_combo.lineEdit()
        self.client_edit.setMaxLength(4000)
        self.client_edit.setPlaceholderText("输入客户名称或选择历史")
        self.client_combo.completer().setFilterMode(Qt.MatchFlag.MatchContains)
        self.delete_client_button = QPushButton("删除历史")
        self.delete_client_button.setToolTip("删除当前客户的历史建议，保留表单中的名称。")
        self.delete_client_button.clicked.connect(self.delete_client)
        self.client_combo.currentTextChanged.connect(self._update_client_delete)
        self.client_edit.setText(settings.repair_client)
        self._refresh_clients()
        self.client_edit.editingFinished.connect(self._remember_client)
        self.client_combo.textActivated.connect(self._select_client)
        client_row = QHBoxLayout()
        client_row.addWidget(self.client_combo, 1)
        client_row.addWidget(self.delete_client_button)
        self.contact_edit = QLineEdit(settings.linkman)
        self.phone_edit = QLineEdit(settings.linknumber)
        self.fault_combo = QComboBox()
        self.fault_combo.setEditable(True)
        self.fault_combo.addItems(FAULT_OPTIONS)
        self.fault_combo.setCurrentText(settings.reback_fault)
        self.description_combo = QComboBox()
        self.description_combo.setEditable(True)
        self.description_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.description_combo.setMaxVisibleItems(12)
        self.description_combo.setMinimumContentsLength(15)
        self.description_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.description_combo.setEditText(settings.fault_text)
        self.description_edit = self.description_combo.lineEdit()
        self.description_edit.setMaxLength(4000)
        self.description_edit.setPlaceholderText("输入描述或选择历史，按成功登记次数排序")
        self.description_combo.completer().setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self.description_combo.completer().setFilterMode(Qt.MatchFlag.MatchContains)
        self.delete_description_button = QPushButton("删除历史")
        self.delete_description_button.setToolTip("从历史下拉框删除当前描述；保留当前输入和登记记录")
        self.delete_description_button.clicked.connect(self.delete_description)
        self.description_combo.currentTextChanged.connect(self._update_description_delete)
        description_row = QHBoxLayout()
        description_row.addWidget(self.description_combo, 1)
        description_row.addWidget(self.delete_description_button)
        self.deal_combo = QComboBox()
        self.repair_combo = QComboBox()
        self.return_combo = QComboBox()
        for code, label in DEAL_OPTIONS.items():
            self.deal_combo.addItem(label, code)
        for code, label in REPAIR_OPTIONS.items():
            self.repair_combo.addItem(label, code)
        for code, label in RETURN_OPTIONS.items():
            self.return_combo.addItem(label, code)
        self.deal_combo.setCurrentIndex(self.deal_combo.findData(settings.deal_type))
        self.repair_combo.setCurrentIndex(self.repair_combo.findData(settings.repair_mode))
        self.return_combo.setCurrentIndex(self.return_combo.findData(settings.return_mode))
        self.delay_spin = QSpinBox()
        self.delay_spin.setRange(0, 600000)
        self.delay_spin.setSuffix(" 毫秒")
        self.delay_spin.setValue(settings.delay_ms)
        self.skip_checkbox = QCheckBox("跳过以前已成功登记的序列号（待核对记录始终跳过）")
        self.skip_checkbox.setChecked(settings.skip_success)
        fields = [("联系人", self.contact_edit, 0, 2),
                  ("联系电话", self.phone_edit, 0, 4), ("客户反馈故障", self.fault_combo, 1, 0),
                  ("处理方式", self.deal_combo, 2, 0), ("接修方式", self.repair_combo, 2, 2),
                  ("返回方式 *", self.return_combo, 2, 4)]
        for label, widget, row, column in fields:
            grid.addWidget(QLabel(label), row, column)
            grid.addWidget(widget, row, column + 1)
        client_label = QLabel("送修客户")
        client_label.setBuddy(self.client_combo)
        grid.addWidget(client_label, 0, 0)
        grid.addLayout(client_row, 0, 1)
        grid.addWidget(QLabel("故障描述"), 1, 2)
        grid.addLayout(description_row, 1, 3, 1, 3)
        self.return_address_panel = QWidget()
        self.return_address_panel.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        address_grid = QGridLayout(self.return_address_panel)
        address_grid.setContentsMargins(0, 0, 0, 0)
        address_grid.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        self.province_combo, self.city_combo, self.area_combo = QComboBox(), QComboBox(), QComboBox()
        for column, (label, combo, value) in enumerate([
            ("省份 *", self.province_combo, settings.province),
            ("城市 *", self.city_combo, settings.city), ("区域 *", self.area_combo, settings.area),
        ]):
            combo.setPlaceholderText("请选择")
            if value:
                combo.addItem(value)
                combo.setCurrentIndex(0)
            combo.setMinimumContentsLength(8)
            combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            address_grid.addWidget(QLabel(label), 0, column * 2)
            address_grid.addWidget(combo, 0, column * 2 + 1)
            address_grid.setColumnStretch(column * 2 + 1, 1)
        self.address_edit = QLineEdit(settings.address)
        self.address_edit.setPlaceholderText("寄回客户时必填；请先登录并加载省市区")
        self.region_button = QPushButton("加载省市区")
        self.region_button.clicked.connect(lambda: self.load_regions())
        address_grid.addWidget(QLabel("详细地址 *"), 1, 0)
        address_grid.addWidget(self.address_edit, 1, 1, 1, 4)
        address_grid.addWidget(self.region_button, 1, 5)
        grid.addWidget(self.return_address_panel, 3, 0, 1, 6)
        self.return_address_panel.setVisible(settings.return_mode == "0")
        self.return_combo.currentIndexChanged.connect(
            lambda: self.return_address_panel.setVisible(self.return_combo.currentData() == "0"))
        self.return_combo.activated.connect(self._return_selected)
        self.province_combo.currentIndexChanged.connect(lambda: self._clear_subregions(1))
        self.city_combo.currentIndexChanged.connect(lambda: self._clear_subregions(2))
        self.province_combo.activated.connect(lambda: self._load_missing_subregions(1))
        self.city_combo.activated.connect(lambda: self._load_missing_subregions(2))
        grid.addWidget(QLabel("请求间隔"), 4, 0)
        grid.addWidget(self.delay_spin, 4, 1)
        grid.addWidget(self.skip_checkbox, 4, 2, 1, 4)
        self.settings_status = QLabel("设置会自动保存到本机，下次启动自动恢复")
        self.settings_status.setObjectName("muted")
        self.settings_status.setWordWrap(True)
        grid.addWidget(self.settings_status, 5, 0, 1, 6)
        for column in (1, 3, 5):
            grid.setColumnStretch(column, 1)
        layout.addWidget(self.settings_group)

        self.tabs = QTabWidget()
        task_tab = QWidget()
        task_layout = QVBoxLayout(task_tab)
        task_layout.setContentsMargins(0, 8, 0, 0)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        serial_panel = QWidget()
        serial_layout = QVBoxLayout(serial_panel)
        serial_layout.setContentsMargins(0, 0, 5, 0)
        serial_layout.addWidget(QLabel("序列号 · 仅复制 Excel/WPS 的序列号列"))
        self.serial_edit = QPlainTextEdit()
        self.serial_edit.setPlaceholderText("每行一个序列号\n支持换行、逗号和分号\n同一批次自动去重")
        serial_layout.addWidget(self.serial_edit)
        self.serial_count = QLabel("0 个序列号")
        self.serial_count.setObjectName("muted")
        serial_layout.addWidget(self.serial_count)
        self.serial_edit.textChanged.connect(self._update_count)
        splitter.addWidget(serial_panel)
        self.result_table = self._table(["序列号", "产品型号", "保修截止", "保修情况", "客户名称", "状态", "说明 / RMA单号"])
        splitter.addWidget(self.result_table)
        splitter.setSizes([270, 890])
        task_layout.addWidget(splitter, 1)
        actions = QHBoxLayout()
        self.query_button = QPushButton("仅查询资料")
        self.query_button.clicked.connect(lambda: self.start_batch(query_only=True))
        self.submit_button = QPushButton("开始提交登记")
        self.submit_button.setObjectName("primary")
        self.submit_button.clicked.connect(lambda: self.start_batch(query_only=False))
        self.stop_button = QPushButton("停止")
        self.stop_button.clicked.connect(self.request_stop)
        self.stop_button.setEnabled(False)
        self.save_button = QPushButton("保存设置")
        self.save_button.clicked.connect(self.save_settings)
        for button in (self.query_button, self.submit_button, self.stop_button):
            actions.addWidget(button)
        actions.addStretch()
        actions.addWidget(self.save_button)
        task_layout.addLayout(actions)
        self.tabs.addTab(task_tab, "批量登记")

        history_tab = QWidget()
        history_layout = QVBoxLayout(history_tab)
        history_layout.setContentsMargins(0, 8, 0, 0)
        search_row = QHBoxLayout()
        self.history_search = QLineEdit()
        self.history_search.setPlaceholderText("按序列号筛选记录")
        self.history_search.textChanged.connect(self.refresh_history)
        refresh = QPushButton("刷新")
        refresh.clicked.connect(self.refresh_history)
        export = QPushButton("导出 CSV")
        export.clicked.connect(self.export_history)
        search_row.addWidget(self.history_search, 1)
        search_row.addWidget(refresh)
        search_row.addWidget(export)
        history_layout.addLayout(search_row)
        self.history_table = self._table(["时间", "序列号", "产品型号", "结果", "RMA单号", "说明"])
        history_layout.addWidget(self.history_table, 1)
        reconcile_row = QHBoxLayout()
        hint = QLabel("显示最近 2000 条。待核对记录请先在官网历史数据确认，再更新本地记录。")
        hint.setWordWrap(True)
        reconcile_row.addWidget(hint, 1)
        self.registered_button = QPushButton("核对：已登记")
        self.absent_button = QPushButton("核对：未登记")
        self.registered_button.clicked.connect(lambda: self.reconcile(True))
        self.absent_button.clicked.connect(lambda: self.reconcile(False))
        reconcile_row.addWidget(self.registered_button)
        reconcile_row.addWidget(self.absent_button)
        history_layout.addLayout(reconcile_row)
        self.tabs.addTab(history_tab, "提交记录")
        self.tabs.currentChanged.connect(lambda index: self.refresh_history() if index == 1 else None)
        layout.addWidget(self.tabs, 1)

        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)
        self.status_label = QLabel("就绪")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        log_header = QHBoxLayout()
        log_header.addWidget(QLabel("运行日志"))
        log_header.addStretch()
        open_logs = QPushButton("打开日志目录")
        open_logs.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.log_directory))))
        clear_logs = QPushButton("清空显示")
        log_header.addWidget(open_logs)
        log_header.addWidget(clear_logs)
        layout.addLayout(log_header)
        self.log_edit = QPlainTextEdit()
        self.log_edit.setReadOnly(True)
        self.log_edit.setMaximumBlockCount(5000)
        self.log_edit.setMaximumHeight(125)
        clear_logs.clicked.connect(self.log_edit.clear)
        layout.addWidget(self.log_edit)

    @staticmethod
    def _table(headers):
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.setAlternatingRowColors(True)
        table.verticalHeader().hide()
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        table.horizontalHeader().setStretchLastSection(True)
        table.setColumnWidth(0, 155)
        return table

    def settings(self) -> Settings:
        return Settings(
            repair_client=self.client_edit.text().strip(), linkman=self.contact_edit.text().strip(),
            linknumber=self.phone_edit.text().strip(), reback_fault=self.fault_combo.currentText().strip(),
            fault_text=self.description_edit.text().strip(), deal_type=self.deal_combo.currentData(),
            repair_mode=self.repair_combo.currentData(), delay_ms=self.delay_spin.value(),
            skip_success=self.skip_checkbox.isChecked(),
            return_mode=self.return_combo.currentData(), province=self.province_combo.currentText(),
            city=self.city_combo.currentText(), area=self.area_combo.currentText(),
            address=self.address_edit.text().strip(),
            repair_client_history=self._client_history,
        )

    def _connect_autosave(self):
        for edit in (self.client_edit, self.contact_edit, self.phone_edit, self.address_edit):
            edit.textChanged.connect(self._schedule_save)
        for combo in (self.fault_combo, self.description_combo, self.deal_combo, self.repair_combo,
                      self.return_combo, self.province_combo, self.city_combo, self.area_combo):
            combo.currentTextChanged.connect(self._schedule_save)
        self.delay_spin.valueChanged.connect(self._schedule_save)
        self.skip_checkbox.toggled.connect(self._schedule_save)

    def _schedule_save(self, *_args):
        self.settings_status.setText("设置已修改，正在自动保存…")
        self._save_timer.start()

    def _persist_settings(self, *, remember_client=False, delete_client=False):
        self._save_timer.stop()
        settings = self.settings()
        name = settings.repair_client
        history = self._client_history
        if delete_client:
            history = tuple(saved for saved in history if saved != name)
        elif remember_client and name and name != self._committed_client:
            history = (name, *(saved for saved in history if saved != name))[:CLIENT_HISTORY_LIMIT]
        settings = replace(settings, repair_client_history=history)
        try:
            if settings != self._saved_settings or not self.config_store.path.exists():
                self.config_store.save(settings)
                self._saved_settings = settings
        except UserError:
            self.settings_status.setText("设置保存失败，请检查数据目录或点击“保存设置”重试")
            raise
        if remember_client or delete_client:
            self._committed_client = name
        if history != self._client_history:
            self._client_history = history
            self._refresh_clients()
        self.settings_status.setText("设置已自动保存到本机，下次启动自动恢复")

    def _autosave_settings(self):
        try:
            self._persist_settings()
        except UserError as error:
            self.log(str(error))

    def save_settings(self):
        try:
            self._persist_settings(remember_client=True)
            self.log("设置已保存，登录令牌不会写入配置。")
        except UserError as error:
            self._job_error(str(error), False)

    def _remember_client(self):
        if self._busy or self.client_combo.view().isVisible():
            return
        try:
            self._persist_settings(remember_client=True)
        except UserError as error:
            self._job_error(str(error), False)

    def _select_client(self, name):
        self.client_combo.setEditText(name)
        self._remember_client()

    def _refresh_clients(self):
        text = self.client_edit.text()
        cursor = self.client_edit.cursorPosition()
        with QSignalBlocker(self.client_combo), QSignalBlocker(self.client_edit):
            self.client_combo.clear()
            self.client_combo.addItems(self._client_history)
            self.client_combo.setCurrentIndex(self.client_combo.findText(text))
            self.client_combo.setEditText(text)
            self.client_edit.setCursorPosition(cursor)
        self._update_client_delete()

    def _update_client_delete(self, *_args):
        self.delete_client_button.setEnabled(self.client_edit.text().strip() in self._client_history)

    def delete_client(self):
        try:
            self._persist_settings(delete_client=True)
            self.status_label.setText("已删除该客户的历史建议。")
        except UserError as error:
            self._job_error(str(error), False)

    def refresh_descriptions(self):
        try:
            records = self.journal.fault_descriptions()
        except UserError as error:
            self._job_error(str(error), False)
            return
        current = self.description_combo.currentText()
        cursor = self.description_edit.cursorPosition()
        with QSignalBlocker(self.description_combo):
            self.description_combo.clear()
            for record in records:
                self.description_combo.addItem(record["description"])
                self.description_combo.setItemData(self.description_combo.count() - 1,
                    f"成功登记 {record['use_count']} 次 · 最近 {display_time(record['last_used'])}",
                    Qt.ItemDataRole.ToolTipRole)
            self.description_combo.setEditText(current)
            self.description_edit.setCursorPosition(cursor)
        self._description_history = {row["description"] for row in records}
        self._update_description_delete()

    def _update_description_delete(self, *_args):
        self.delete_description_button.setEnabled(
            self.description_combo.currentText().strip() in self._description_history)

    def delete_description(self):
        if self._busy:
            return
        try:
            self.journal.delete_fault_description(self.description_combo.currentText())
            self.refresh_descriptions()
            self.status_label.setText("已从历史中删除该描述；当前输入和登记记录保留。")
        except UserError as error:
            self._job_error(str(error), False)

    def _return_selected(self, *_args):
        if self.return_combo.currentData() == "0" and self.token_edit.text().strip():
            self.load_regions()

    def _clear_subregions(self, start):
        for combo in (self.province_combo, self.city_combo, self.area_combo)[start:]:
            with QSignalBlocker(combo):
                combo.clear()

    def _load_missing_subregions(self, start):
        if not (self.province_combo, self.city_combo, self.area_combo)[start].count():
            self.load_regions(start)

    def load_regions(self, start=0):
        if self._busy:
            return
        try:
            token = validate_token(self.token_edit.text())
        except UserError as error:
            self._job_error(str(error), False)
            return
        combos = (self.province_combo, self.city_combo, self.area_combo)
        parent_code = str(combos[start - 1].currentData() or "") if start else ""
        if start and not parent_code:
            start = 0
        previous = [combo.currentText() for combo in combos]
        factory = self.api_factory
        self._remember_token(token)
        self.status_label.setText("正在加载官网省市区…")

        def operation(worker):
            result, parent = {}, parent_code if start else ""
            with factory(token) as api:
                for index in range(start, 3):
                    if worker.stop_event.is_set():
                        return None
                    options = api.regions(("province", "city", "district")[index], parent)
                    result[index] = options
                    selected = next((item for item in options if item["name"] == previous[index]), None)
                    if selected is None:
                        break
                    parent = selected["code"]
            if worker.stop_event.is_set():
                return None
            return result

        def complete(result):
            if result is None:
                self.status_label.setText("已停止加载省市区。")
                return
            for index in range(start, 3):
                combo = combos[index]
                with QSignalBlocker(combo):
                    combo.clear()
                    for item in result.get(index, []):
                        combo.addItem(item["name"], item["code"])
                    combo.setCurrentIndex(combo.findText(previous[index]))
            self._schedule_save()
            self.status_label.setText("省市区已加载，请依次选择并填写详细地址。")

        self._start_job(operation, complete)

    def _remember_token(self, token):
        if token:
            self._secrets.add(token)

    def redact(self, text):
        for secret in self._secrets:
            text = text.replace(secret, "[令牌已隐藏]")
        return text

    def log(self, message):
        line = datetime.now().strftime("[%H:%M:%S] ") + self.redact(str(message))
        self.log_edit.appendPlainText(line)
        try:
            with self.log_path.open("a", encoding="utf-8") as stream:
                stream.write(line + "\n")
        except OSError:
            self.status_label.setText("日志文件无法写入，请检查数据目录；提交状态仍由数据库保存。")

    def _update_count(self):
        try:
            self.serial_count.setText(f"{len(parse_serials(self.serial_edit.toPlainText()))} 个序列号（已去重）")
        except UserError:
            self.serial_count.setText("输入含无效序列号，请检查")

    def _set_busy(self, busy):
        self._busy = busy
        for widget in (self.login_button, self.check_button, self.query_button, self.submit_button,
                       self.save_button, self.token_edit, self.serial_edit, self.settings_group,
                       self.registered_button, self.absent_button):
            widget.setEnabled(not busy)
        self.stop_button.setEnabled(busy and self._worker is not None)

    def _start_job(self, operation, completion):
        if self._busy:
            return
        self.last_error = ""
        self._completion = completion
        thread = QThread(self)
        worker = TaskWorker(operation)
        worker.moveToThread(thread)
        self._thread, self._worker = thread, worker
        thread.started.connect(worker.run)
        worker.result.connect(self._job_result)
        worker.error.connect(self._job_error)
        worker.item.connect(self._item_result)
        worker.progress.connect(self._progress)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(self._thread_finished)
        thread.finished.connect(thread.deleteLater)
        self._set_busy(True)
        thread.start()

    @Slot(object)
    def _job_result(self, result):
        if self._completion:
            try:
                self._completion(result)
            except UserError as error:
                self._job_error(str(error), False)

    @Slot(str, bool)
    def _job_error(self, message, auth):
        self.last_error = self.redact(message)
        self.log(self.last_error)
        self.status_label.setText(self.last_error)
        if auth:
            self.token_edit.clear()
            self.auth_status.setText("登录已失效")
        if self.diagnostics:
            self._write_diagnostics({"authenticated": False, "error": self.last_error})

    def _write_diagnostics(self, data):
        try:
            atomic_json(self.config_store.directory / "diagnostics.json", data)
        except UserError:
            self.log("诊断状态文件无法保存。")

    @Slot()
    def _thread_finished(self):
        self._thread = self._worker = None
        self._completion = None
        self._set_busy(False)
        self.refresh_history()
        self.refresh_descriptions()

    def show_login(self):
        if self._busy:
            return
        self._set_busy(True)
        dialog = LoginDialog(self)
        self._login_dialog = dialog
        captured = []
        dialog.token_ready.connect(captured.append)
        def completed(_result):
            self._login_dialog = None
            self._set_busy(False)
            if captured:
                self.token_edit.setText(captured[0])
                self.check_login()
            else:
                self.log("已取消官方网页登录。")
        dialog.finished.connect(completed)
        dialog.open()

    def check_login(self):
        if self._busy:
            return
        try:
            token = validate_token(self.token_edit.text())
        except UserError as error:
            self._job_error(str(error), False)
            return
        self._remember_token(token)
        self.status_label.setText("正在检查登录…")
        factory = self.api_factory
        def operation(_worker):
            with factory(token) as api:
                info = api.login_info()
                try:
                    faults = api.fault_options()
                except (AuthenticationExpired, SecurityBlocked):
                    raise
                except UserError:
                    faults = []
                return info, faults
        def complete(result):
            _info, faults = result
            if faults:
                previous = self.fault_combo.currentText()
                self.fault_combo.clear()
                self.fault_combo.addItems(faults)
                self.fault_combo.setCurrentText(previous)
            self.auth_status.setText("登录有效")
            self.status_label.setText("登录检查通过，可以查询资料或提交登记。")
            self.log("登录检查通过。")
            if self.diagnostics:
                self._write_diagnostics({"authenticated": True})
        self._start_job(operation, complete)

    def start_batch(self, *, query_only=False):
        if self._busy:
            return
        try:
            token = validate_token(self.token_edit.text())
            text = self.serial_edit.toPlainText()
            serials = parse_serials(text)
            if not serials:
                raise UserError("请先粘贴序列号")
            settings = self.settings()
            settings.validate(required=not query_only)
            self._persist_settings(remember_client=True)
        except UserError as error:
            self._job_error(str(error), False)
            return
        self._remember_token(token)
        self._rows = {serial.casefold(): row for row, serial in enumerate(serials)}
        self.result_table.setRowCount(len(serials))
        for row, serial in enumerate(serials):
            for column in range(self.result_table.columnCount()):
                self.result_table.setItem(row, column, QTableWidgetItem(serial if column == 0 else ""))
        self.progress_bar.setRange(0, len(serials))
        self.progress_bar.setValue(0)
        self.tabs.setCurrentIndex(0)
        self.status_label.setText("仅查询资料，不创建登记" if query_only else "正在检查账号及登记权限…")
        self.log(f"开始{'查询' if query_only else '提交'}任务：{len(serials)} 个序列号。")
        engine = self.engine
        def operation(worker):
            return engine.run(text, token, settings, worker.stop_event, query_only=query_only,
                              on_item=worker.item.emit, on_progress=worker.progress.emit)
        self._start_job(operation, self._batch_complete)

    @Slot(object)
    def _item_result(self, result: ItemResult):
        row = self._rows.get(result.serial.casefold())
        if row is None:
            return
        data = result.data or {}
        values = [result.serial, result.model, data.get("repairEndtime") or "", data.get("repairSituation") or "",
                  data.get("clientName") or "", ITEM_LABELS.get(result.state, result.state), result.rma_id or result.message]
        for column, value in enumerate(values):
            item = QTableWidgetItem(self.redact(str(value)))
            if column == 5 and result.state in COLORS:
                item.setForeground(QColor(COLORS[result.state]))
            item.setToolTip(item.text())
            self.result_table.setItem(row, column, item)
        self.result_table.scrollToItem(self.result_table.item(row, 0))
        self.status_label.setText(f"{result.serial} · {ITEM_LABELS.get(result.state, result.state)}")
        self.log(f"{result.serial}：{result.message}")
        if result.state == "auth":
            self.token_edit.clear()
            self.auth_status.setText("登录已失效")

    @Slot(int, int)
    def _progress(self, current, total):
        self.progress_bar.setRange(0, total)
        self.progress_bar.setValue(current)

    def _batch_complete(self, summary: Summary):
        self.last_summary = summary
        status = "已停止" if summary.stopped else "完成"
        message = f"{status}：成功 {summary.succeeded}，查询 {summary.queried}，失败 {summary.failed}，跳过 {summary.skipped}"
        if summary.reason:
            message += " · " + summary.reason
        self.status_label.setText(message)
        self.log(message)

    def request_stop(self):
        if self._worker:
            self._worker.stop_event.set()
            self.stop_button.setEnabled(False)
            self.status_label.setText("正在停止：不再开始新提交，已发出的请求等待结果。")
            self.log("收到停止指令，等待当前请求结束。")

    def refresh_history(self, *_args):
        try:
            self._history = self.journal.records(self.history_search.text())
            self.history_table.setRowCount(len(self._history))
            for row, record in enumerate(self._history):
                values = [display_time(record["created_at"]), record["serial"], record["model"],
                          STATE_LABELS[record["state"]], record["rma_id"], record["message"]]
                for column, value in enumerate(values):
                    item = QTableWidgetItem(self.redact(str(value)))
                    item.setToolTip(item.text())
                    if column == 3 and record["state"] in COLORS:
                        item.setForeground(QColor(COLORS[record["state"]]))
                    self.history_table.setItem(row, column, item)
        except UserError as error:
            self._job_error(str(error), False)

    def export_history(self):
        path, _ = QFileDialog.getSaveFileName(self, "导出提交记录", "ASMP提交记录.csv", "CSV 文件 (*.csv)")
        if path:
            try:
                count = self.journal.export_csv(Path(path), self.history_search.text())
                self.log(f"已导出 {count} 条记录。")
            except UserError as error:
                self._job_error(str(error), False)

    def reconcile(self, registered: bool):
        if self._busy:
            return
        row = self.history_table.currentRow()
        if row < 0 or row >= len(self._history):
            self.status_label.setText("请先选择一条待核对记录。")
            return
        record = self._history[row]
        if record["state"] not in {"pending", "unknown"}:
            self.status_label.setText("仅可人工核对“提交中 / 待核对”记录。")
            return
        question = "已在官网历史数据找到该序列号的对应登记" if registered else "已在官网历史数据确认该次请求没有创建登记，允许重新提交"
        note, ok = QInputDialog.getText(self, "记录网页核对结果", question + "。\n请填写核对说明：")
        if ok:
            try:
                self.journal.reconcile(record["id"], registered=registered, note=note)
                self.log(f"已更新 {record['serial']} 的人工核对结果。")
                self.refresh_history()
                self.refresh_descriptions()
            except UserError as error:
                self._job_error(str(error), False)

    def closeEvent(self, event):
        if self._thread is not None:
            self.request_stop()
            event.ignore()
            return
        if self._login_dialog is not None:
            self._login_dialog.reject()
        try:
            self._persist_settings(remember_client=True)
        except UserError as error:
            QMessageBox.warning(self, "设置未保存", str(error))
            event.ignore()
            return
        event.accept()
