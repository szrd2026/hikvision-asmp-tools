import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QCoreApplication, Qt

QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)

from asmp_tool.models import Settings


@pytest.fixture
def settings():
    return Settings(repair_client="测试送修客户", linkman="测试联系人", linknumber="010-12345678",
                    reback_fault="其他", fault_text="测试故障", delay_ms=0)


@pytest.fixture
def account():
    return {"currentUser": {"permissionList": [{"code": "SR02", "value": 0}]},
            "currentCollectingPoint": {"localRepair": 1, "hikExchange": 0}}


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    yield app
