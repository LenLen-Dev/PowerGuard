"""Modern PySide6 dashboard for multi-dorm power monitoring."""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QComboBox,
    QCompleter,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.config import AppConfig
from app.logging_setup import setup_logging
from app.main import build_email_notifier, build_monitor_service
from app.models import QueryResult
from app.notifiers.email import EmailNotifier
from app.services.monitor_service import MonitorService
from app.timezone_utils import BEIJING_TZ

PROFILE_PATH = Path.cwd() / "gui_profiles.json"
USAGE_STATE_PATH = Path.cwd() / "gui_usage_state.json"
logger = logging.getLogger(__name__)

BUILDING_OPTIONS: list[tuple[str, str]] = [
    ("6", "男25#栋"),
    ("74", "梦溪7-9-A栋"),
    ("42", "男11#楼"),
    ("26", "女01#楼"),
    ("30", "女03#楼"),
    ("19", "女11#楼"),
    ("70", "梦溪7-6栋"),
    ("68", "梦溪7-4栋"),
    ("15", "研03#楼"),
    ("16", "研04#楼"),
    ("71", "梦溪7-7栋"),
    ("61", "女13#楼"),
    ("8", "男20#楼"),
    ("52", "男16#楼"),
    ("69", "梦溪7-5栋"),
    ("10", "男19#楼"),
    ("37", "研01#楼"),
    ("25", "男05#楼"),
    ("66", "梦溪7-2栋"),
    ("72", "梦溪7-8栋"),
    ("4", "男22#栋"),
    ("63", "研05#楼"),
    ("36", "女07#楼"),
    ("67", "梦溪7-3栋"),
    ("77", "研7#楼（南楼）"),
    ("57", "女09#楼"),
    ("73", "梦溪7-9-B栋"),
    ("50", "男15#楼"),
    ("2", "男21#栋"),
    ("49", "男14#楼"),
    ("76", "研6#楼（北楼）"),
    ("34", "女05#楼"),
    ("32", "女04#楼"),
    ("75", "梦溪7-9-C栋"),
    ("12", "男18#楼"),
    ("44", "男12#楼"),
    ("21", "女14#楼"),
    ("14", "男17#楼"),
    ("56", "女06#楼"),
    ("60", "女12#楼"),
    ("28", "女02#楼"),
    ("65", "梦溪7-1栋"),
    ("59", "女10#楼"),
    ("46", "男13#楼"),
    ("17", "女08#楼"),
    ("38", "研02#楼"),
]


def find_building_id(name: str) -> str:
    for bid, bname in BUILDING_OPTIONS:
        if bname == name:
            return bid
    for bid, bname in BUILDING_OPTIONS:
        if name in bname:
            return bid
    return ""


@dataclass
class DormProfile:
    id: str
    building_id: str
    building_name: str
    room: str
    alert_email: str
    interval_seconds: int
    threshold: float

    @staticmethod
    def from_dict(raw: dict[str, Any]) -> "DormProfile":
        return DormProfile(
            id=str(raw["id"]),
            building_id=str(raw["building_id"]),
            building_name=str(raw["building_name"]),
            room=str(raw["room"]),
            alert_email=str(raw["alert_email"]),
            interval_seconds=int(raw["interval_seconds"]),
            threshold=float(raw.get("threshold", 10.0)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "building_id": self.building_id,
            "building_name": self.building_name,
            "room": self.room,
            "alert_email": self.alert_email,
            "interval_seconds": self.interval_seconds,
            "threshold": self.threshold,
        }


@dataclass
class ProfileRuntime:
    profile: DormProfile
    service: MonitorService
    summary_notifier: EmailNotifier
    next_run: datetime
    busy: bool = False
    last_result: QueryResult | None = None
    last_error: str | None = None
    daily_date: str | None = None
    daily_consumption: float = 0.0
    last_balance: float | None = None
    last_balance_at: datetime | None = None
    avg_hourly_rate: float = 0.0
    usage_identity: str | None = None
    summary_sent_date: str | None = None


class DormCard(QFrame):
    clicked = Signal(str)

    def __init__(self, profile: DormProfile) -> None:
        super().__init__()
        self.profile_id = profile.id
        self.setObjectName("dormCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(14)
        shadow.setOffset(0, 3)
        shadow.setColor(QColor(15, 23, 42, 22))
        self.setGraphicsEffect(shadow)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(6)
        self.title = QLabel(f"{profile.building_name}{profile.room}")
        self.title.setObjectName("cardTitle")
        self.meta = QLabel(f"{profile.alert_email} | 间隔 {profile.interval_seconds}s | 阈值 {profile.threshold:.1f}")
        self.meta.setObjectName("cardMeta")
        self.status = QLabel("状态: 未查询")
        self.status.setObjectName("cardStatusWarning")
        self.balance = QLabel("-- kWh")
        self.balance.setObjectName("cardBalance")
        layout.addWidget(self.title)
        layout.addWidget(self.meta)
        layout.addWidget(self.status)
        layout.addWidget(self.balance)

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        super().mousePressEvent(event)
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.profile_id)

    def set_selected(self, selected: bool) -> None:
        self.setProperty("selected", selected)
        self.style().unpolish(self)
        self.style().polish(self)

    def update_view(self, runtime: ProfileRuntime) -> None:
        p = runtime.profile
        self.title.setText(f"{p.building_name}{p.room}")
        self.meta.setText(f"{p.alert_email} | 间隔 {p.interval_seconds}s | 阈值 {p.threshold:.1f}")
        if runtime.last_error:
            self.status.setObjectName("cardStatusDanger")
            self.status.setText("状态: 异常")
            self.balance.setText("--")
        elif runtime.last_result:
            bal = runtime.last_result.reading.balance
            self.balance.setText(f"{bal:.2f} kWh")
            if bal <= p.threshold:
                self.status.setObjectName("cardStatusDanger")
                self.status.setText("状态: 低电量")
            else:
                self.status.setObjectName("cardStatusSuccess")
                self.status.setText("状态: 正常")
        else:
            self.status.setObjectName("cardStatusWarning")
            self.status.setText("状态: 未查询")
            self.balance.setText("-- kWh")
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)


class AddProfileDialog(QDialog):
    """Create a new dorm profile with empty defaults."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("新增宿舍")
        self.setModal(True)
        self.resize(520, 320)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)

        self.building_combo = QComboBox()
        self.building_combo.setEditable(True)
        self.building_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.building_combo.setCurrentIndex(-1)
        self.building_combo.setEditText("")
        for bid, name in BUILDING_OPTIONS:
            self.building_combo.addItem(name, bid)
        comp = QCompleter([n for _, n in BUILDING_OPTIONS], self.building_combo)
        comp.setFilterMode(Qt.MatchFlag.MatchContains)
        comp.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.building_combo.setCompleter(comp)

        self.room_input = QLineEdit()
        self.room_input.setPlaceholderText("例如 215")
        self.email_input = QLineEdit()
        self.email_input.setPlaceholderText("例如 123@qq.com")
        self.interval_input = QSpinBox()
        self.interval_input.setRange(30, 86400)
        self.interval_input.setValue(300)
        self.interval_input.setSuffix(" 秒")
        self.interval_input.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.threshold_input = QDoubleSpinBox()
        self.threshold_input.setRange(0, 9999)
        self.threshold_input.setDecimals(2)
        self.threshold_input.setValue(10.0)
        self.threshold_input.setSuffix(" kWh")
        self.threshold_input.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)

        layout.addWidget(QLabel("宿舍楼"))
        layout.addWidget(self.building_combo)
        layout.addWidget(QLabel("宿舍房号"))
        layout.addWidget(self.room_input)
        layout.addWidget(QLabel("告警邮箱"))
        layout.addWidget(self.email_input)

        row = QHBoxLayout()
        col1 = QVBoxLayout()
        col2 = QVBoxLayout()
        col1.addWidget(QLabel("查询间隔"))
        col1.addWidget(self.interval_input)
        col2.addWidget(QLabel("预警值"))
        col2.addWidget(self.threshold_input)
        row.addLayout(col1)
        row.addLayout(col2)
        layout.addLayout(row)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.result_profile: DormProfile | None = None

    def _on_accept(self) -> None:
        building_name = self.building_combo.currentText().strip()
        building_id = str(self.building_combo.currentData() or "").strip() or find_building_id(building_name)
        room = self.room_input.text().strip()
        email = self.email_input.text().strip()

        if not building_name or not building_id:
            QMessageBox.warning(self, "参数错误", "请选择有效宿舍楼")
            return
        if not room:
            QMessageBox.warning(self, "参数错误", "宿舍房号不能为空")
            return
        if not email or "@" not in email or "." not in email:
            QMessageBox.warning(self, "参数错误", "请输入有效告警邮箱")
            return

        self.result_profile = DormProfile(
            id=uuid.uuid4().hex,
            building_id=building_id,
            building_name=building_name,
            room=room,
            alert_email=email,
            interval_seconds=int(self.interval_input.value()),
            threshold=float(self.threshold_input.value()),
        )
        self.accept()


class MainWindow(QMainWindow):
    result_ready = Signal(str, object)
    error_raised = Signal(str, str)

    def __init__(self, base_config: AppConfig) -> None:
        super().__init__()
        self.base_config = base_config
        self.setWindowTitle(f"{base_config.app_name} - Dashboard")
        self.resize(1220, 780)

        self.profiles: dict[str, DormProfile] = {}
        self.runtimes: dict[str, ProfileRuntime] = {}
        self.cards: dict[str, DormCard] = {}
        self.selected_profile_id: str | None = None
        self.monitoring_enabled = False
        self.usage_state: dict[str, dict[str, Any]] = {}

        self._build_ui()
        self._apply_styles()
        self._bind_events()
        self._load_profiles()
        self._load_usage_state()
        self._rebuild_runtime_and_cards()
        if not self.profiles:
            self._prompt_add_profile(first_time=True)

    def _build_ui(self) -> None:
        root = QWidget(self)
        page = QVBoxLayout(root)
        page.setContentsMargins(20, 16, 20, 16)
        page.setSpacing(12)

        header = QHBoxLayout()
        header_title = QLabel("宿舍电量控制台")
        header_title.setObjectName("headerTitle")
        header_sub = QLabel("卡片列表 + 详情编辑")
        header_sub.setObjectName("subtle")
        left = QVBoxLayout()
        left.addWidget(header_title)
        left.addWidget(header_sub)

        self.start_btn = QPushButton("开始监控")
        self.start_btn.setObjectName("primaryButton")
        self.stop_btn = QPushButton("停止监控")
        self.stop_btn.setObjectName("secondaryButton")
        self.stop_btn.setEnabled(False)
        self.query_btn = QPushButton("立即查询")
        self.query_btn.setObjectName("successButton")
        self.add_btn = QPushButton("+")
        self.add_btn.setObjectName("roundButton")
        self.add_btn.setFixedSize(40, 40)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        actions.addWidget(self.start_btn)
        actions.addWidget(self.stop_btn)
        actions.addWidget(self.query_btn)
        actions.addWidget(self.add_btn)
        header.addLayout(left, 1)
        header.addLayout(actions)

        body = QHBoxLayout()
        body.setSpacing(12)

        left_panel = QFrame()
        left_panel.setObjectName("panelCard")
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(12, 12, 12, 12)
        left_layout.setSpacing(10)
        left_layout.addWidget(QLabel("宿舍列表"))
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.list_host = QWidget()
        self.list_layout = QVBoxLayout(self.list_host)
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.setSpacing(10)
        self.list_layout.addStretch(1)
        self.scroll.setWidget(self.list_host)
        left_layout.addWidget(self.scroll, 1)

        self.detail_panel = QFrame()
        self.detail_panel.setObjectName("panelCard")
        detail = QVBoxLayout(self.detail_panel)
        detail.setContentsMargins(16, 16, 16, 16)
        detail.setSpacing(10)
        detail.addWidget(QLabel("详情"))

        metrics = QHBoxLayout()
        metrics.setSpacing(8)
        self.balance_box = self._metric_box("剩余电量", "-- kWh")
        self.today_box = self._metric_box("今日耗电(北京时间0点起)", "-- kWh")
        metrics.addWidget(self.balance_box[0])
        metrics.addWidget(self.today_box[0])
        detail.addLayout(metrics)

        form1 = QHBoxLayout()
        self.building_combo = QComboBox()
        self.building_combo.setEditable(True)
        self.building_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        for bid, name in BUILDING_OPTIONS:
            self.building_combo.addItem(name, bid)
        comp = QCompleter([n for _, n in BUILDING_OPTIONS], self.building_combo)
        comp.setFilterMode(Qt.MatchFlag.MatchContains)
        comp.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.building_combo.setCompleter(comp)
        self.room_input = QLineEdit()
        self.room_input.setPlaceholderText("宿舍房号")
        form1.addWidget(self._field("宿舍楼", self.building_combo))
        form1.addWidget(self._field("宿舍房号", self.room_input))

        form2 = QHBoxLayout()
        self.email_input = QLineEdit()
        self.email_input.setPlaceholderText("告警邮箱")
        self.interval_input = QSpinBox()
        self.interval_input.setRange(30, 86400)
        self.interval_input.setSuffix(" 秒")
        self.interval_input.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.threshold_input = QDoubleSpinBox()
        self.threshold_input.setRange(0, 9999)
        self.threshold_input.setDecimals(2)
        self.threshold_input.setSuffix(" kWh")
        self.threshold_input.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        form2.addWidget(self._field("告警邮箱", self.email_input))
        form2.addWidget(self._field("查询间隔", self.interval_input))
        form2.addWidget(self._field("预警值", self.threshold_input))

        self.save_btn = QPushButton("保存")
        self.save_btn.setObjectName("primaryButton")
        self.save_btn.setFixedWidth(120)
        self.delete_btn = QPushButton("删除")
        self.delete_btn.setObjectName("dangerButton")
        self.delete_btn.setFixedWidth(120)
        detail.addLayout(form1)
        detail.addLayout(form2)
        action_row = QHBoxLayout()
        action_row.addStretch(1)
        action_row.addWidget(self.delete_btn)
        action_row.addWidget(self.save_btn)
        detail.addLayout(action_row)

        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setMaximumHeight(160)
        detail.addWidget(QLabel("日志"))
        detail.addWidget(self.log_box)

        body.addWidget(left_panel, 4)
        body.addWidget(self.detail_panel, 7)
        page.addLayout(header)
        page.addLayout(body, 1)
        self.setCentralWidget(root)

        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self._clear_detail()

    def _field(self, label: str, widget: QWidget) -> QWidget:
        w = QWidget()
        l = QVBoxLayout(w)
        l.setContentsMargins(0, 0, 0, 0)
        l.setSpacing(4)
        t = QLabel(label)
        t.setObjectName("subtle")
        l.addWidget(t)
        l.addWidget(widget)
        return w

    def _metric_box(self, title: str, value: str) -> tuple[QFrame, QLabel]:
        frame = QFrame()
        frame.setObjectName("metricCard")
        l = QVBoxLayout(frame)
        l.setContentsMargins(12, 10, 12, 10)
        l.setSpacing(4)
        t = QLabel(title)
        t.setObjectName("subtle")
        v = QLabel(value)
        v.setObjectName("metricValue")
        l.addWidget(t)
        l.addWidget(v)
        return frame, v

    def _apply_styles(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow { background: #F5F7FB; }
            QLabel { color: #111827; font-size: 13px; }
            QLabel#headerTitle { font-size: 24px; font-weight: 800; color: #2563EB; }
            QLabel#subtle { color: #6B7280; }
            QFrame#panelCard, QFrame#metricCard, QFrame#dormCard {
                background: #FFFFFF; border: 1px solid #E8EDF5; border-radius: 12px;
            }
            QFrame#dormCard[selected="true"] { border: 1px solid #3B82F6; background: #EFF6FF; }
            QLabel#cardTitle { font-size: 17px; font-weight: 700; }
            QLabel#cardMeta { color: #6B7280; }
            QLabel#cardBalance { font-size: 26px; font-weight: 800; color: #111827; }
            QLabel#cardStatusSuccess { color: #10B981; font-weight: 700; }
            QLabel#cardStatusWarning { color: #F59E0B; font-weight: 700; }
            QLabel#cardStatusDanger { color: #EF4444; font-weight: 700; }
            QLabel#metricValue { font-size: 28px; font-weight: 800; color: #1F2937; }
            QPushButton {
                border: none; border-radius: 10px; color: white;
                min-height: 36px; padding: 0 14px; font-weight: 700;
            }
            QPushButton#primaryButton { background: #3B82F6; }
            QPushButton#primaryButton:hover { background: #2563EB; }
            QPushButton#secondaryButton { background: #9CA3AF; }
            QPushButton#secondaryButton:hover { background: #6B7280; }
            QPushButton#successButton { background: #10B981; }
            QPushButton#successButton:hover { background: #059669; }
            QPushButton#dangerButton { background: #EF4444; }
            QPushButton#dangerButton:hover { background: #DC2626; }
            QPushButton#roundButton { background: #F97316; border-radius: 20px; font-size: 24px; padding: 0; }
            QPushButton#roundButton:hover { background: #EA580C; }
            QPushButton:disabled { background: #D1D5DB; color: #F3F4F6; }
            QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox {
                min-height: 34px; border: 1px solid #D1D5DB; border-radius: 8px;
                background: #FFFFFF; padding: 0 10px; font-size: 13px;
            }
            QComboBox::drop-down {
                subcontrol-origin: padding;
                subcontrol-position: top right;
                width: 26px;
                border-left: 1px solid #E5E7EB;
                background: #F8FAFC;
                border-top-right-radius: 8px;
                border-bottom-right-radius: 8px;
            }
            QComboBox::down-arrow { image: none; width: 0px; height: 0px; }
            QTextEdit {
                background: #FFFFFF; border: 1px solid #E5E7EB; border-radius: 8px;
                color: #111827; padding: 8px; font-size: 13px;
            }
            """
        )

    def _bind_events(self) -> None:
        self.add_btn.clicked.connect(lambda: self._prompt_add_profile(first_time=False))
        self.start_btn.clicked.connect(self._start_all)
        self.stop_btn.clicked.connect(self._stop_all)
        self.query_btn.clicked.connect(self._query_all)
        self.save_btn.clicked.connect(self._save_selected_profile)
        self.delete_btn.clicked.connect(self._delete_selected_profile)
        self.timer.timeout.connect(self._on_tick)
        self.result_ready.connect(self._on_result)
        self.error_raised.connect(self._on_error)

    def _load_profiles(self) -> None:
        if not PROFILE_PATH.exists():
            return
        try:
            raw = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
            for item in raw:
                p = DormProfile.from_dict(item)
                self.profiles[p.id] = p
        except Exception as exc:
            self._log(f"读取配置失败: {exc}", "WARNING")

    def _save_profiles(self) -> None:
        raw = [p.to_dict() for p in self.profiles.values()]
        PROFILE_PATH.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")

    def _load_usage_state(self) -> None:
        self.usage_state.clear()
        if not USAGE_STATE_PATH.exists():
            return
        try:
            raw = json.loads(USAGE_STATE_PATH.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                self.usage_state = raw
        except Exception as exc:
            self._log(f"读取用电统计缓存失败: {exc}", "WARNING")

    def _save_usage_state(self) -> None:
        data: dict[str, dict[str, Any]] = {}
        for pid, rt in self.runtimes.items():
            data[pid] = {
                "daily_date": rt.daily_date,
                "daily_consumption": rt.daily_consumption,
                "last_balance": rt.last_balance,
                "last_balance_at": rt.last_balance_at.isoformat() if rt.last_balance_at else None,
                "avg_hourly_rate": rt.avg_hourly_rate,
                "usage_identity": rt.usage_identity,
                "summary_sent_date": rt.summary_sent_date,
            }
        USAGE_STATE_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def _prompt_add_profile(self, *, first_time: bool) -> None:
        dialog = AddProfileDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted or dialog.result_profile is None:
            if first_time:
                self._log("首次配置被取消，未创建宿舍项。", "WARNING")
            return
        p = dialog.result_profile
        self.profiles[p.id] = p
        self._save_profiles()
        self._rebuild_runtime_and_cards(select_id=p.id)
        self._log(f"已添加宿舍：{p.building_name}{p.room}", "INFO")
        if first_time:
            QMessageBox.information(self, "首次配置", "已创建首个宿舍配置，可继续编辑后点击保存。")

    def _rebuild_runtime_and_cards(self, select_id: str | None = None) -> None:
        while self.list_layout.count() > 1:
            item = self.list_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        self.cards.clear()
        old_results = {
            k: (
                v.last_result,
                v.last_error,
                v.daily_date,
                v.daily_consumption,
                v.last_balance,
                v.last_balance_at,
                v.avg_hourly_rate,
                v.usage_identity,
                v.summary_sent_date,
            )
            for k, v in self.runtimes.items()
        }
        self.runtimes.clear()

        for p in self.profiles.values():
            cfg = self._build_profile_config(p)
            rt = ProfileRuntime(
                profile=p,
                service=build_monitor_service(cfg),
                summary_notifier=build_email_notifier(cfg),
                next_run=datetime.now(),
            )
            if p.id in old_results:
                (
                    last_result,
                    last_error,
                    daily_date,
                    daily_consumption,
                    last_balance,
                    last_balance_at,
                    avg_hourly_rate,
                    usage_identity,
                    summary_sent_date,
                ) = old_results[p.id]
                if usage_identity == self._profile_identity(p):
                    rt.last_result = last_result
                    rt.last_error = last_error
                    rt.daily_date = daily_date
                    rt.daily_consumption = daily_consumption
                    rt.last_balance = last_balance
                    rt.last_balance_at = last_balance_at
                    rt.avg_hourly_rate = avg_hourly_rate
                    rt.usage_identity = usage_identity
                    rt.summary_sent_date = summary_sent_date
            self._apply_usage_state(p.id, rt)
            self.runtimes[p.id] = rt

            card = DormCard(p)
            card.clicked.connect(self._on_card_clicked)
            card.update_view(rt)
            self.cards[p.id] = card
            self.list_layout.insertWidget(self.list_layout.count() - 1, card)

        if not self.profiles:
            self.selected_profile_id = None
            self._clear_detail()
            return

        target = select_id or self.selected_profile_id or next(iter(self.profiles.keys()))
        self._select_profile(target)

    def _apply_usage_state(self, profile_id: str, rt: ProfileRuntime) -> None:
        raw = self.usage_state.get(profile_id)
        if not raw:
            return
        try:
            usage_identity = str(raw.get("usage_identity") or "")
            if usage_identity and usage_identity != self._profile_identity(rt.profile):
                return
            rt.daily_date = raw.get("daily_date")
            rt.daily_consumption = float(raw.get("daily_consumption", 0.0))
            lb = raw.get("last_balance")
            rt.last_balance = float(lb) if lb is not None else None
            lbt = raw.get("last_balance_at")
            rt.last_balance_at = datetime.fromisoformat(lbt) if lbt else None
            rt.avg_hourly_rate = float(raw.get("avg_hourly_rate", 0.0))
            rt.usage_identity = usage_identity or self._profile_identity(rt.profile)
            ssd = raw.get("summary_sent_date")
            rt.summary_sent_date = str(ssd) if ssd else None
        except Exception:
            return

    def _build_profile_config(self, profile: DormProfile) -> AppConfig:
        return replace(
            self.base_config,
            building_id=profile.building_id,
            building_name=profile.building_name,
            room_id=profile.room,
            room_name=profile.room,
            email_to=profile.alert_email,
            check_interval_seconds=profile.interval_seconds,
            low_balance_threshold=profile.threshold,
        )

    def _on_card_clicked(self, profile_id: str) -> None:
        self._select_profile(profile_id)

    def _select_profile(self, profile_id: str) -> None:
        if profile_id not in self.profiles:
            return
        self.selected_profile_id = profile_id
        for pid, card in self.cards.items():
            card.set_selected(pid == profile_id)
        self._load_detail(profile_id)

    def _load_detail(self, profile_id: str) -> None:
        p = self.profiles[profile_id]
        rt = self.runtimes[profile_id]
        self.save_btn.setEnabled(True)
        self.delete_btn.setEnabled(True)
        self._set_combo_to(p.building_id, p.building_name)
        self.room_input.setText(p.room)
        self.email_input.setText(p.alert_email)
        self.interval_input.setValue(p.interval_seconds)
        self.threshold_input.setValue(p.threshold)

        if rt.last_result:
            bal = rt.last_result.reading.balance
            today = self._today_usage(rt)
            self.balance_box[1].setText(f"{bal:.2f} kWh")
            self.today_box[1].setText(f"{today:.2f} kWh")
        else:
            self.balance_box[1].setText("-- kWh")
            self.today_box[1].setText("-- kWh")

    def _clear_detail(self) -> None:
        self.save_btn.setEnabled(False)
        self.delete_btn.setEnabled(False)
        self.building_combo.setCurrentIndex(-1)
        self.building_combo.setEditText("")
        self.room_input.clear()
        self.email_input.clear()
        self.interval_input.setValue(300)
        self.threshold_input.setValue(10.0)
        self.balance_box[1].setText("-- kWh")
        self.today_box[1].setText("-- kWh")

    def _save_selected_profile(self) -> None:
        if not self.selected_profile_id:
            return
        p = self.profiles[self.selected_profile_id]
        building_name = self.building_combo.currentText().strip()
        building_id = str(self.building_combo.currentData() or "").strip() or find_building_id(building_name)
        room = self.room_input.text().strip()
        email = self.email_input.text().strip()
        if not building_name or not building_id or not room or not email:
            QMessageBox.warning(self, "参数错误", "楼栋/房号/邮箱不能为空")
            return
        if "@" not in email or "." not in email:
            QMessageBox.warning(self, "参数错误", "请输入有效邮箱")
            return

        new_profile = replace(
            p,
            building_id=building_id,
            building_name=building_name,
            room=room,
            alert_email=email,
            interval_seconds=int(self.interval_input.value()),
            threshold=float(self.threshold_input.value()),
        )
        old_identity = self._profile_identity(p)
        new_identity = self._profile_identity(new_profile)
        if old_identity != new_identity:
            self.usage_state.pop(p.id, None)
        self.profiles[p.id] = new_profile
        self._save_profiles()
        self._rebuild_runtime_and_cards(select_id=p.id)
        self._log(f"已保存：{new_profile.building_name}{new_profile.room}", "INFO")

    def _delete_selected_profile(self) -> None:
        if not self.selected_profile_id:
            return
        p = self.profiles.get(self.selected_profile_id)
        if not p:
            return
        confirm = QMessageBox.question(
            self,
            "确认删除",
            f"确认删除宿舍 {p.building_name}{p.room} 吗？此操作不可撤销。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        pid = p.id
        self.profiles.pop(pid, None)
        self.usage_state.pop(pid, None)
        self._save_profiles()
        self._rebuild_runtime_and_cards()
        self._save_usage_state()
        self._log(f"已删除：{p.building_name}{p.room}", "WARNING")

        if not self.profiles:
            self.monitoring_enabled = False
            self.timer.stop()
            self.start_btn.setEnabled(True)
            self.stop_btn.setEnabled(False)

    def _start_all(self) -> None:
        if not self.runtimes:
            QMessageBox.information(self, "提示", "请先添加宿舍")
            return
        self.monitoring_enabled = True
        for rt in self.runtimes.values():
            rt.next_run = datetime.now()
        self.timer.start()
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self._log("已开始监控全部宿舍", "INFO")

    def _stop_all(self) -> None:
        self.monitoring_enabled = False
        self.timer.stop()
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self._log("已停止监控", "INFO")

    def _query_all(self) -> None:
        for pid in self.runtimes.keys():
            self._schedule_run(pid, immediate=True)
        self._log("已触发全部立即查询", "INFO")

    def _on_tick(self) -> None:
        self._apply_midnight_reset_if_needed()
        self._maybe_send_nightly_summary_all()
        if not self.monitoring_enabled:
            return
        now = datetime.now()
        for pid, rt in self.runtimes.items():
            if rt.busy:
                continue
            if now >= rt.next_run:
                self._schedule_run(pid, immediate=False)

    def _apply_midnight_reset_if_needed(self) -> None:
        now_bj = datetime.now(BEIJING_TZ)
        day_key = now_bj.strftime("%Y-%m-%d")
        reset_happened = False
        initialized_only = False
        for rt in self.runtimes.values():
            if rt.daily_date == day_key:
                continue
            is_first_init = rt.daily_date is None
            rt.daily_date = day_key
            rt.daily_consumption = 0.0
            rt.avg_hourly_rate = 0.0
            rt.last_balance = None
            rt.last_balance_at = None
            rt.last_result = None
            rt.last_error = None
            rt.summary_sent_date = None
            rt.next_run = datetime.now()  # force first query right after midnight when monitoring on
            if is_first_init:
                initialized_only = True
            else:
                reset_happened = True
        if reset_happened or initialized_only:
            self._save_usage_state()
        if reset_happened:
            self._log("北京时间 00:00 已重置当日统计", "INFO")

    def _maybe_send_nightly_summary_all(self) -> None:
        now_bj = datetime.now(BEIJING_TZ)
        if now_bj.hour != 22:
            return
        day_key = now_bj.strftime("%Y-%m-%d")

        for rt in self.runtimes.values():
            if rt.summary_sent_date == day_key:
                continue
            if rt.daily_date != day_key:
                continue
            if rt.last_result is None:
                continue

            title, content = self._compose_nightly_summary(rt)
            try:
                rt.summary_notifier.send(title, content)
                rt.summary_sent_date = day_key
                self._log(f"{rt.profile.building_name}{rt.profile.room} 已发送22:00汇总邮件", "INFO")
            except Exception as exc:
                self._log(f"{rt.profile.building_name}{rt.profile.room} 22:00汇总邮件发送失败: {exc}", "WARNING")
        self._save_usage_state()

    def _compose_nightly_summary(self, rt: ProfileRuntime) -> tuple[str, str]:
        assert rt.last_result is not None
        reading = rt.last_result.reading
        today_usage = self._today_usage(rt)
        query_time = reading.fetched_at.astimezone(BEIJING_TZ).strftime("%Y-%m-%d %H:%M:%S")

        if reading.balance <= rt.profile.threshold:
            title = "[电量预警] 每晚电量提醒（低电量）"
        else:
            title = "[电量提醒] 每晚电量汇总"

        content = (
            f"项目: {self.base_config.app_name}\n"
            f"房间: {rt.profile.building_name}{rt.profile.room}\n"
            f"账号: {reading.account}\n"
            f"当前剩余电量: {reading.balance:.2f}\n"
            f"今日耗电量: {today_usage:.2f}\n"
            f"接口提示: {reading.message}\n"
            f"查询时间(北京时间): {query_time}"
        )
        return title, content

    def _schedule_run(self, profile_id: str, *, immediate: bool) -> None:
        rt = self.runtimes.get(profile_id)
        if not rt or rt.busy:
            return
        rt.busy = True
        if not immediate:
            rt.next_run = datetime.now() + timedelta(seconds=rt.profile.interval_seconds)
        threading.Thread(target=self._worker, args=(profile_id,), daemon=True).start()

    def _worker(self, profile_id: str) -> None:
        rt = self.runtimes[profile_id]
        try:
            result = rt.service.run_once()
            self.result_ready.emit(profile_id, result)
        except Exception as exc:
            self.error_raised.emit(profile_id, str(exc))
        finally:
            rt.busy = False

    def _on_result(self, profile_id: str, result: QueryResult) -> None:
        rt = self.runtimes.get(profile_id)
        if not rt:
            return
        rt.last_result = result
        rt.last_error = None
        self._refresh_daily(rt)
        self._save_usage_state()
        card = self.cards.get(profile_id)
        if card:
            card.update_view(rt)
        if self.selected_profile_id == profile_id:
            self._load_detail(profile_id)
        self._log(
            f"{rt.profile.building_name}{rt.profile.room} 查询成功: {result.reading.balance:.2f} kWh",
            "WARNING" if result.alert_sent else "INFO",
        )

    def _on_error(self, profile_id: str, message: str) -> None:
        rt = self.runtimes.get(profile_id)
        if not rt:
            return
        rt.last_error = message
        card = self.cards.get(profile_id)
        if card:
            card.update_view(rt)
        if self.selected_profile_id == profile_id:
            self.today_box[1].setText("查询异常")
        self._log(f"{rt.profile.building_name}{rt.profile.room} 查询失败: {message}", "WARNING")
        self._save_usage_state()

    def _refresh_daily(self, rt: ProfileRuntime) -> None:
        if not rt.last_result:
            return
        rt.usage_identity = self._profile_identity(rt.profile)
        now_bj = datetime.now(BEIJING_TZ)
        day_key = now_bj.strftime("%Y-%m-%d")
        balance = rt.last_result.reading.balance
        if rt.daily_date != day_key:
            rt.daily_date = day_key
            rt.daily_consumption = 0.0
            rt.avg_hourly_rate = 0.0
            rt.last_balance = balance
            rt.last_balance_at = now_bj
            rt.summary_sent_date = None
            return

        if rt.last_balance is not None and rt.last_balance_at is not None:
            delta = rt.last_balance - balance
            elapsed_h = max((now_bj - rt.last_balance_at).total_seconds() / 3600.0, 1e-6)
            if delta > 0:
                rt.daily_consumption += delta
                instant_rate = delta / elapsed_h
                if rt.avg_hourly_rate <= 0:
                    rt.avg_hourly_rate = instant_rate
                else:
                    rt.avg_hourly_rate = rt.avg_hourly_rate * 0.7 + instant_rate * 0.3
            else:
                # Decay stale rate when no additional consumption is observed.
                rt.avg_hourly_rate *= max(0.0, 1.0 - min(elapsed_h * 0.2, 0.6))

        rt.last_balance = balance
        rt.last_balance_at = now_bj

    def _today_usage(self, rt: ProfileRuntime) -> float:
        return max(0.0, rt.daily_consumption)

    def _set_combo_to(self, bid: str, bname: str) -> None:
        for i in range(self.building_combo.count()):
            if str(self.building_combo.itemData(i)) == bid or self.building_combo.itemText(i) == bname:
                self.building_combo.setCurrentIndex(i)
                return
        self.building_combo.setEditText(bname)

    @staticmethod
    def _profile_identity(profile: DormProfile) -> str:
        return f"{profile.building_id}|{profile.room}"

    def _log(self, text: str, level: str = "INFO") -> None:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        upper = level.upper()
        color = "#10B981" if upper == "INFO" else "#EF4444"
        self.log_box.append(
            f"<span style='color:#9CA3AF'>[{ts}]</span> "
            f"<span style='color:{color}'><b>{upper}</b> {text}</span>"
        )
        if upper == "WARNING":
            logger.warning(text)
        else:
            logger.info(text)


def main() -> None:
    config = AppConfig.from_env()
    gui_log_file = os.getenv("GUI_LOG_FILE", os.getenv("HEADLESS_LOG_FILE", "logs/gui_monitor.log"))
    setup_logging(config.log_level, log_file=gui_log_file, weekly_reset=True)
    app = QApplication(sys.argv)
    window = MainWindow(config)
    window.show()
    sys.exit(app.exec())
