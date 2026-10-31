from __future__ import annotations

from threading import Event

from PySide6.QtCore import QObject, Signal, Slot

from ..api import AuthenticationExpired
from ..models import UserError


class TaskWorker(QObject):
    result = Signal(object)
    error = Signal(str, bool)
    item = Signal(object)
    progress = Signal(int, int)
    finished = Signal()

    def __init__(self, operation):
        super().__init__()
        self.operation = operation
        self.stop_event = Event()

    @Slot()
    def run(self):
        try:
            self.result.emit(self.operation(self))
        except AuthenticationExpired as error:
            self.error.emit(str(error), True)
        except UserError as error:
            self.error.emit(str(error), False)
        except Exception:
            self.error.emit("程序处理失败，任务已停止；请检查提交记录，有待核对记录时先核对官网历史数据。", False)
        finally:
            self.finished.emit()
