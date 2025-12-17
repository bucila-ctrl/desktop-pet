import os
import sys
import random
import math
from typing import Dict, Optional, Callable, List, Tuple

from PySide6.QtCore import Qt, QPoint, QSize, QTimer, QSettings, QElapsedTimer, Signal
from PySide6.QtGui import QMovie, QIcon, QGuiApplication, QPainter, QPainterPath, QColor
from PySide6.QtWidgets import (
    QApplication, QWidget, QLabel, QMenu, QSystemTrayIcon, QStyle,
    QVBoxLayout, QHBoxLayout, QPushButton, QSizePolicy
)

# -------------------------
# Assets (put these under ./assets/)
# -------------------------
ASSET_SIT = "dog_sit_tr.gif"
ASSET_LAY = "dog_laydown_tr.gif"
ASSET_WALK_L = "dog_walkingleft_tr.gif"
ASSET_WALK_R = "dog_walkingright_tr.gif"
ASSET_TRAY = "tray.ico"

# -------------------------
# Behavior
# -------------------------
# Rest reminder: show laydown pose for this long after a reminder, then back to sit.
AUTO_REST_POSE_MS = 15_000

# Random chatter interval range (ms)
CHATTER_MIN_MS = 45_000
CHATTER_MAX_MS = 140_000

# Auto roundtrip walk every 30 minutes (ms)
AUTO_ROUNDTRIP_MS = 30 * 60 * 1000

# Movement speed while walking (px per second). Tune to taste.
WALK_SPEED_PX_PER_SEC = 90

# How often to move window while walking (ms). Bigger = lower CPU but less smooth.
WALK_TICK_MS = 55

# GIF playback speed (%). 100 = original speed.
IDLE_GIF_SPEED = 20
WALK_GIF_SPEED = 115

# Optional tiny up/down bob while walking to feel less like pure translation.
# Set to 0 to disable.
WALK_BOB_PX = 2
WALK_BOB_PERIOD_MS = 420

# -------------------------
# Bubble UI
# -------------------------
BUBBLE_MIN_W = 160
BUBBLE_MAX_W = 360
BUBBLE_GAP_Y = 18
BUBBLE_ANCHOR_HEAD = True

# -------------------------
# macOS-ish styling
# -------------------------
MACOS_MENU_QSS = """
QMenu {
    background: rgba(248, 248, 248, 235);
    color: #111;
    border: 1px solid rgba(0, 0, 0, 0.12);
    border-radius: 12px;
    padding: 6px;
    font-size: 12px;
}
QMenu::item {
    padding: 8px 14px;
    border-radius: 10px;
}
QMenu::item:selected {
    background: rgba(0, 122, 255, 0.14);
}
QMenu::separator {
    height: 1px;
    margin: 6px 10px;
    background: rgba(0, 0, 0, 0.08);
}
"""

MACOS_PILL_BUTTON_QSS = """
QPushButton {
    background: rgba(0, 0, 0, 0.05);
    border: 1px solid rgba(0, 0, 0, 0.10);
    border-radius: 10px;
    padding: 5px 12px;
    font-size: 11px;
}
QPushButton:hover { background: rgba(0, 0, 0, 0.09); }
QPushButton:pressed { background: rgba(0, 0, 0, 0.12); }
"""


def resource_path(*parts: str) -> str:
    """Works for dev + PyInstaller onefile."""
    base = getattr(sys, "_MEIPASS", os.path.abspath(os.path.dirname(__file__)))
    return os.path.join(base, *parts)


def _to_bool(v, default=False) -> bool:
    if isinstance(v, bool):
        return v
    if v is None:
        return default
    s = str(v).strip().lower()
    return s in ("1", "true", "yes", "y", "on")


def _to_float(v, default=1.0) -> float:
    try:
        return float(v)
    except Exception:
        return default


def _to_int(v, default=0) -> int:
    try:
        return int(v)
    except Exception:
        return default


def _fmt_mmss(sec: int) -> str:
    sec = max(0, int(sec))
    m = sec // 60
    s = sec % 60
    return f"{m:02d}:{s:02d}"


class BubbleWidget(QWidget):
    """Custom painted speech bubble with optional buttons + dynamic line."""
    closed = Signal()

    def __init__(self, parent=None, gap_y: int = BUBBLE_GAP_Y):
        super().__init__(parent)
        self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)

        # Geometry
        self._pad_x = 12
        self._pad_y = 10
        self._radius = 12
        self._tail_w = 16
        self._tail_h = 10

        self._gap_y = int(gap_y)
        self._anchor = QPoint(0, 0)

        # Content
        self.title = QLabel("")
        self.title.setTextFormat(Qt.RichText)
        self.title.setStyleSheet("color:#111; font-size:12px; font-weight:600;")
        self.title.setWordWrap(True)

        self.message = QLabel("")
        self.message.setTextFormat(Qt.RichText)
        self.message.setStyleSheet("color:#222; font-size:12px;")
        self.message.setWordWrap(True)

        self.dynamic = QLabel("")
        self.dynamic.setStyleSheet("color:#444; font-size:11px;")
        self.dynamic.setVisible(False)

        self._btn_row = QHBoxLayout()
        self._btn_row.setContentsMargins(0, 6, 0, 0)
        self._btn_row.setSpacing(8)

        self._btn_container = QWidget()
        self._btn_container.setLayout(self._btn_row)
        self._btn_container.setVisible(False)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(self._pad_x, self._pad_y, self._pad_x, self._pad_y + self._tail_h)
        lay.setSpacing(4)
        lay.addWidget(self.title)
        lay.addWidget(self.message)
        lay.addWidget(self.dynamic)
        lay.addWidget(self._btn_container)

        # Timers
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._do_close)

        self._dynamic_timer = QTimer(self)
        self._dynamic_timer.setTimerType(Qt.CoarseTimer)
        self._dynamic_timer.timeout.connect(self._dynamic_tick)
        self._dynamic_getter: Optional[Callable[[], str]] = None

        self.hide()

    def set_gap_y(self, gap_y: int):
        self._gap_y = int(gap_y)
        if self.isVisible():
            self._place_near_anchor()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)

        rect = self.rect().adjusted(0, 0, 0, -self._tail_h)
        path = QPainterPath()
        path.addRoundedRect(rect, self._radius, self._radius)

        cx = rect.center().x()
        tail = QPainterPath()
        tail.moveTo(cx - self._tail_w // 2, rect.bottom())
        tail.lineTo(cx, rect.bottom() + self._tail_h)
        tail.lineTo(cx + self._tail_w // 2, rect.bottom())
        tail.closeSubpath()
        path.addPath(tail)

        # Fill
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 240))
        p.drawPath(path)

        # Outline
        p.setBrush(Qt.NoBrush)
        p.setPen(QColor(0, 0, 0, 22))
        p.drawPath(path)
        p.setPen(QColor(0, 0, 0, 45))
        p.drawPath(path)

    def _clear_buttons(self):
        while self._btn_row.count():
            item = self._btn_row.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def _set_buttons(self, buttons: List[Tuple[str, Callable[[], None]]]):
        self._clear_buttons()
        if not buttons:
            self._btn_container.setVisible(False)
            return

        for text, cb in buttons:
            btn = QPushButton(text)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
            btn.setStyleSheet(MACOS_PILL_BUTTON_QSS)
            btn.clicked.connect(cb)
            self._btn_row.addWidget(btn)

        close_btn = QPushButton("✕")
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.setFixedWidth(32)
        close_btn.setStyleSheet(MACOS_PILL_BUTTON_QSS)
        close_btn.clicked.connect(self._do_close)
        self._btn_row.addWidget(close_btn)

        self._btn_container.setVisible(True)

    def _layout_to_size(self):
        max_content_w = BUBBLE_MAX_W - self._pad_x * 2
        self.title.setFixedWidth(max_content_w)
        self.message.setFixedWidth(max_content_w)
        self.dynamic.setFixedWidth(max_content_w)

        self.title.adjustSize()
        self.message.adjustSize()
        self.dynamic.adjustSize()

        w = max(
            self.title.sizeHint().width(),
            self.message.sizeHint().width(),
            BUBBLE_MIN_W - self._pad_x * 2
        )
        if self.dynamic.isVisible():
            w = max(w, self.dynamic.sizeHint().width())
        w = min(w, max_content_w)

        self.title.setFixedWidth(w)
        self.message.setFixedWidth(w)
        self.dynamic.setFixedWidth(w)

        self.title.adjustSize()
        self.message.adjustSize()
        self.dynamic.adjustSize()

        content_h = self.title.height() + self.message.height()
        if self.dynamic.isVisible():
            content_h += 4 + self.dynamic.height()
        if self._btn_container.isVisible():
            content_h += 6 + self._btn_container.sizeHint().height()

        W = w + self._pad_x * 2
        H = content_h + self._pad_y * 2 + self._tail_h
        self.resize(W, H)

    def _place_near_anchor(self):
        x = self._anchor.x() - self.width() // 2
        y = self._anchor.y() - self.height() - self._gap_y

        screen = QGuiApplication.screenAt(self._anchor) or QGuiApplication.primaryScreen()
        geo = screen.availableGeometry()

        x = max(geo.left(), min(x, geo.right() - self.width()))
        y = max(geo.top(),  min(y, geo.bottom() - self.height()))
        self.move(x, y)

    def show_bubble(
        self,
        title_html: str,
        message_html: str,
        anchor_pos: QPoint,
        ms: int = 3000,
        buttons: Optional[List[Tuple[str, Callable[[], None]]]] = None,
        dynamic_getter: Optional[Callable[[], str]] = None,
        dynamic_interval_ms: int = 1000,
    ):
        self._anchor = anchor_pos
        self.title.setText(title_html)
        self.message.setText(message_html)

        if dynamic_getter is not None:
            self._dynamic_getter = dynamic_getter
            self.dynamic.setVisible(True)
            self.dynamic.setText(dynamic_getter())
            self._dynamic_timer.start(max(250, int(dynamic_interval_ms)))
        else:
            self._dynamic_getter = None
            self._dynamic_timer.stop()
            self.dynamic.setVisible(False)
            self.dynamic.setText("")

        self._set_buttons(buttons or [])
        self._layout_to_size()
        self._place_near_anchor()

        self.show()
        self.raise_()

        if ms > 0:
            self._hide_timer.start(ms)
        else:
            self._hide_timer.stop()

    def update_anchor(self, anchor_pos: QPoint):
        self._anchor = anchor_pos
        if self.isVisible():
            self._place_near_anchor()

    def _dynamic_tick(self):
        if self._dynamic_getter is None:
            self._dynamic_timer.stop()
            return
        try:
            self.dynamic.setText(self._dynamic_getter())
            self._layout_to_size()
            self._place_near_anchor()
        except Exception:
            pass

    def _do_close(self):
        self._hide_timer.stop()
        self._dynamic_timer.stop()
        self.hide()
        self.closed.emit()


class DesktopPet(QWidget):
    """
    States:
      - sit / laydown
      - walk_left / walk_right

    Walking mode:
      - Roundtrip: walk to one screen edge -> reverse -> walk to the other edge -> stop (back to sit).
      - Manual trigger: menu "Walk roundtrip"
      - Auto trigger: every 30 minutes (only when not dragging / not pomodoro / not laydown / not already walking)
    """

    def __init__(self):
        super().__init__()

        # ---------- Window ----------
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)

        # ---------- Settings ----------
        self.settings = QSettings("MyDesktopPet", "Pet")
        self.locked = _to_bool(self.settings.value("locked", False), False)
        self.chatter_enabled = _to_bool(self.settings.value("chatter_enabled", True), True)
        self.rest_enabled = _to_bool(self.settings.value("rest_enabled", True), True)
        self.rest_interval_min = _to_int(self.settings.value("rest_interval_min", 50), 50)
        self.scale = _to_float(self.settings.value("scale", 1.0), 1.0)
        self.auto_roundtrip_enabled = _to_bool(self.settings.value("auto_roundtrip_enabled", True), True)

        # ---------- UI ----------
        self.label = QLabel(self)
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setStyleSheet("background: transparent;")
        self.label.setAttribute(Qt.WA_TranslucentBackground, True)

        # ---------- Movies ----------
        self.movies: Dict[str, QMovie] = {}
        self._uniform_base_size: Optional[QSize] = None
        self._scaled_size: Optional[QSize] = None
        self._load_movies()

        self.state = "sit"
        self._active_movie: Optional[QMovie] = None

        # Bubble
        self.bubble = BubbleWidget(gap_y=BUBBLE_GAP_Y)

        # ---------- Drag/click detection ----------
        self._dragging = False
        self._drag_offset = QPoint(0, 0)
        self._press_global = QPoint(0, 0)
        self._moved = False
        self._click_timer = QElapsedTimer()
        self._drag_threshold = 6
        self._snap_margin = 18

        # ---------- Pomodoro ----------
        self.pomo_running = False
        self.pomo_work_sec = 25 * 60
        self.pomo_break_sec = 5 * 60
        self._pomo_left = 0
        self._pomo_mode = "work"  # work/break
        self._pomo_timer = QTimer(self)
        self._pomo_timer.timeout.connect(self._tick_pomo)

        # ---------- Rest reminder ----------
        self._rest_timer = QTimer(self)
        self._rest_timer.setTimerType(Qt.CoarseTimer)
        self._rest_timer.timeout.connect(self._rest_ping)

        self._rest_snooze_timer = QTimer(self)
        self._rest_snooze_timer.setSingleShot(True)
        self._rest_snooze_timer.timeout.connect(self._resume_rest_after_snooze)

        self._rest_pose_back_timer = QTimer(self)
        self._rest_pose_back_timer.setSingleShot(True)
        self._rest_pose_back_timer.timeout.connect(lambda: self.set_state("sit"))

        # ---------- Random chatter ----------
        self._chatter_timer = QTimer(self)
        self._chatter_timer.setTimerType(Qt.CoarseTimer)
        self._chatter_timer.setSingleShot(True)
        self._chatter_timer.timeout.connect(self._chatter_once)

        # ---------- Walking movement ----------
        self._walk_timer = QTimer(self)
        self._walk_timer.setTimerType(Qt.CoarseTimer)
        self._walk_timer.timeout.connect(self._tick_walk)

        self._walk_dir = 0  # -1 left, +1 right, 0 none
        self._walk_step_acc = 0.0
        self._walk_base_y: Optional[int] = None
        self._walk_elapsed = QElapsedTimer()

        self._roundtrip_active = False
        self._roundtrip_edge_hits_remaining = 0

        # ---------- Auto roundtrip (30 min) ----------
        self._auto_roundtrip_timer = QTimer(self)
        self._auto_roundtrip_timer.setTimerType(Qt.CoarseTimer)
        self._auto_roundtrip_timer.timeout.connect(self._auto_roundtrip_fire)

        # ---------- Menus ----------
        self._init_tray()
        self.menu = self._build_menu()

        # Restore last pos
        self._restore_position()

        # Start optional features
        self._apply_chatter_state()
        self._apply_rest_state()
        self._apply_auto_roundtrip_state()

        # Initial state
        self.set_state("sit", say=False)

        QTimer.singleShot(180, self._ensure_on_screen)
        QTimer.singleShot(650, self._say_hello)

    # -------------------------
    # Bubble helpers
    # -------------------------
    def _bubble_anchor_global(self) -> QPoint:
        if BUBBLE_ANCHOR_HEAD:
            local = QPoint(self.width() // 2, 0)
            return self.mapToGlobal(local)
        return self.mapToGlobal(self.rect().center())

    def _sync_bubble_anchor(self):
        self.bubble.update_anchor(self._bubble_anchor_global())

    def _say_hello(self):
        # Greeting at startup
        self._notify("<b>你好</b>", "我叫 <b>doei</b> 🐶", ms=3200)

    def _notify(self, title: str, msg: str, ms: int = 3200, buttons=None, dynamic_getter=None):
        self.bubble.show_bubble(
            title_html=title,
            message_html=msg,
            anchor_pos=self._bubble_anchor_global(),
            ms=ms,
            buttons=buttons,
            dynamic_getter=dynamic_getter,
            dynamic_interval_ms=1000,
        )
        try:
            self.tray.showMessage("Desktop Pet", self._strip_html(title + " " + msg), QSystemTrayIcon.Information, 2500)
        except Exception:
            pass

    @staticmethod
    def _strip_html(s: str) -> str:
        return s.replace("<br/>", " ").replace("<br>", " ").replace("<b>", "").replace("</b>", "")

    # -------------------------
    # Movies / States
    # -------------------------
    @staticmethod
    def _probe_movie_size(mv: QMovie) -> Optional[QSize]:
        try:
            mv.jumpToFrame(0)
            sz = mv.currentPixmap().size()
            if not sz.isEmpty():
                return sz
        except Exception:
            pass
        return None

    def _load_movies(self):
        paths = {
            "sit": resource_path("assets", ASSET_SIT),
            "laydown": resource_path("assets", ASSET_LAY),
            "walk_left": resource_path("assets", ASSET_WALK_L),
            "walk_right": resource_path("assets", ASSET_WALK_R),
        }
        for k, p in paths.items():
            if not os.path.exists(p):
                raise FileNotFoundError(f"Missing GIF for '{k}': {p}")

        self.movies["sit"] = QMovie(paths["sit"])
        self.movies["laydown"] = QMovie(paths["laydown"])
        self.movies["walk_left"] = QMovie(paths["walk_left"])
        self.movies["walk_right"] = QMovie(paths["walk_right"])

        for name, mv in self.movies.items():
            mv.setCacheMode(QMovie.CacheAll)
            mv.setSpeed(WALK_GIF_SPEED if name.startswith("walk") else IDLE_GIF_SPEED)

        # Unify base size across all GIFs (prevents resizing/jumping)
        sizes = []
        for mv in self.movies.values():
            sz = self._probe_movie_size(mv)
            if sz:
                sizes.append(sz)
        if sizes:
            self._uniform_base_size = QSize(
                max(s.width() for s in sizes),
                max(s.height() for s in sizes),
            )

    def set_state(self, state: str, say: bool = False, title: str = "", text: str = ""):
        if state not in self.movies:
            return

        # Stop all movies (saves CPU)
        for mv in self.movies.values():
            try:
                mv.stop()
            except Exception:
                pass

        self.state = state
        mv = self.movies[state]
        self._active_movie = mv
        self.label.setMovie(mv)
        mv.start()

        # Walking movement on/off
        if state == "walk_left":
            self._start_walk(dir_=-1)
        elif state == "walk_right":
            self._start_walk(dir_=+1)
        else:
            self._stop_walk()

        self._apply_scale()

        if say and (title or text):
            self._notify(title or "<b>Hey</b>", text or "", ms=2400)

    def _get_base_size(self) -> Optional[QSize]:
        return self._uniform_base_size

    # -------------------------
    # Roundtrip walking
    # -------------------------
    def start_roundtrip(self, start_dir: Optional[int] = None, announce: bool = True):
        """
        Start roundtrip:
          - walk to first edge (according to start_dir)
          - reverse
          - walk to the other edge
          - stop -> sit
        """
        if self._dragging:
            return
        if self.state == "laydown":
            return
        if self.pomo_running:
            # Keep behavior predictable: don't interrupt pomodoro
            return
        if self.state.startswith("walk"):
            return

        if start_dir is None:
            start_dir = random.choice([-1, +1])

        self._roundtrip_active = True
        self._roundtrip_edge_hits_remaining = 2  # first edge then opposite edge
        self.set_state("walk_left" if start_dir < 0 else "walk_right", say=False)

        if announce:
            self._notify("<b>Walk</b>", "I’m going all the way to the side", ms=2600)

    def _finish_roundtrip(self):
        self._roundtrip_active = False
        self._roundtrip_edge_hits_remaining = 0
        self._stop_walk()
        self.set_state("sit", say=False)
        self._notify("<b>Walk finished</b>", "back to study～", ms=2200)

    # -------------------------
    # Auto roundtrip (30 min)
    # -------------------------
    def _apply_auto_roundtrip_state(self):
        if self.auto_roundtrip_enabled:
            self._auto_roundtrip_timer.start(AUTO_ROUNDTRIP_MS)
        else:
            self._auto_roundtrip_timer.stop()
        self._refresh_toggle_texts()

    def toggle_auto_roundtrip(self):
        self.auto_roundtrip_enabled = not self.auto_roundtrip_enabled
        self.settings.setValue("auto_roundtrip_enabled", self.auto_roundtrip_enabled)
        self._apply_auto_roundtrip_state()
        self._notify("<b>Auto walk</b>", "ON ✅" if self.auto_roundtrip_enabled else "OFF ❎", ms=2200)

    def _auto_roundtrip_fire(self):
        # Only trigger when idle-ish
        if (not self.auto_roundtrip_enabled) or self._dragging or self.pomo_running:
            return
        if self.state in ("laydown", "walk_left", "walk_right"):
            return
        # sit is the intended idle state
        self.start_roundtrip(announce=False)
        if self._roundtrip_active:
            self._notify("<b>Auto walk</b>", "30 mins，let’s take a walk～", ms=2400)

    # -------------------------
    # Walking movement tick
    # -------------------------
    def _start_walk(self, dir_: int):
        self._walk_dir = -1 if dir_ < 0 else +1
        self._walk_step_acc = 0.0
        self._walk_base_y = self.y()
        self._walk_elapsed.start()
        if not self._walk_timer.isActive():
            self._walk_timer.start(WALK_TICK_MS)

    def _stop_walk(self):
        self._walk_dir = 0
        self._walk_step_acc = 0.0
        self._walk_timer.stop()
        if self._walk_base_y is not None:
            self.move(self.x(), self._walk_base_y)
        self._walk_base_y = None
        self._sync_bubble_anchor()

    def _tick_walk(self):
        if self._walk_dir == 0 or self._dragging:
            return

        step = WALK_SPEED_PX_PER_SEC * (WALK_TICK_MS / 1000.0)
        self._walk_step_acc += step
        dx = int(self._walk_step_acc)
        if dx <= 0:
            return
        self._walk_step_acc -= dx
        dx = dx * self._walk_dir

        center = self.mapToGlobal(self.rect().center())
        screen = QGuiApplication.screenAt(center) or QGuiApplication.primaryScreen()
        geo = screen.availableGeometry()

        min_x = geo.left()
        max_x = geo.right() - self.width()

        new_x = self.x() + dx

        # optional bobbing
        new_y = self.y()
        if WALK_BOB_PX > 0 and self._walk_base_y is not None and WALK_BOB_PERIOD_MS > 0:
            t = self._walk_elapsed.elapsed()
            phase = (2.0 * math.pi) * (t % WALK_BOB_PERIOD_MS) / float(WALK_BOB_PERIOD_MS)
            new_y = self._walk_base_y + int(round(math.sin(phase) * WALK_BOB_PX))

        # Clamp Y too
        new_y = max(geo.top(), min(new_y, geo.bottom() - self.height()))

        hit_edge = False
        if new_x <= min_x:
            new_x = min_x
            hit_edge = True
        elif new_x >= max_x:
            new_x = max_x
            hit_edge = True

        self.move(new_x, new_y)
        self._sync_bubble_anchor()

        if hit_edge and self._roundtrip_active:
            self._roundtrip_edge_hits_remaining -= 1

            if self._roundtrip_edge_hits_remaining <= 0:
                self._finish_roundtrip()
                return

            # reverse direction and flip animation
            self._walk_dir *= -1
            if self._walk_dir < 0:
                self.set_state("walk_left", say=False)
            else:
                self.set_state("walk_right", say=False)

    # -------------------------
    # Size / scale (low CPU)
    # -------------------------
    def _apply_scale(self):
        base = self._get_base_size()
        if base is None:
            return

        self.scale = max(0.3, min(float(self.scale), 2.0))
        w = int(base.width() * self.scale)
        h = int(base.height() * self.scale)

        if self.width() != w or self.height() != h:
            self.resize(w, h)
            self.label.resize(w, h)

        # setScaledSize is relatively expensive; only do it when needed
        if self._scaled_size != self.label.size():
            for mv in self.movies.values():
                mv.setScaledSize(self.label.size())
            self._scaled_size = self.label.size()

        self.settings.setValue("scale", self.scale)
        self._ensure_on_screen()
        self._sync_bubble_anchor()

    def _set_scale(self, s: float):
        self.scale = float(s)
        self._apply_scale()

    def wheelEvent(self, event):
        if self._get_base_size() is None:
            return
        self.scale *= 1.1 if event.angleDelta().y() > 0 else 1 / 1.1
        self._apply_scale()
        event.accept()

    # -------------------------
    # Position helpers
    # -------------------------
    def _restore_position(self):
        pos = self.settings.value("pos", None)
        if isinstance(pos, QPoint):
            self.move(pos)
            return
        x = _to_int(self.settings.value("pos_x", 80), 80)
        y = _to_int(self.settings.value("pos_y", 80), 80)
        self.move(x, y)

    def _save_position(self):
        self.settings.setValue("pos", self.pos())
        self.settings.setValue("pos_x", self.x())
        self.settings.setValue("pos_y", self.y())

    def _ensure_on_screen(self):
        center = self.mapToGlobal(self.rect().center())
        screen = QGuiApplication.screenAt(center) or QGuiApplication.primaryScreen()
        geo = screen.availableGeometry()
        x = min(max(self.x(), geo.left()), geo.right() - self.width())
        y = min(max(self.y(), geo.top()),  geo.bottom() - self.height())
        self.move(x, y)
        self._sync_bubble_anchor()

    def _snap_to_edges(self):
        center = self.mapToGlobal(self.rect().center())
        screen = QGuiApplication.screenAt(center) or QGuiApplication.primaryScreen()
        geo = screen.availableGeometry()

        x, y = self.x(), self.y()
        if abs(x - geo.left()) <= self._snap_margin:
            x = geo.left()
        if abs((x + self.width()) - geo.right()) <= self._snap_margin:
            x = geo.right() - self.width()

        if abs(y - geo.top()) <= self._snap_margin:
            y = geo.top()
        if abs((y + self.height()) - geo.bottom()) <= self._snap_margin:
            y = geo.bottom() - self.height()

        self.move(x, y)
        self._sync_bubble_anchor()

    # -------------------------
    # Tray / Menu
    # -------------------------
    def _init_tray(self):
        tray_icon_path = resource_path("assets", ASSET_TRAY)
        icon = QIcon(tray_icon_path) if os.path.exists(tray_icon_path) else self.style().standardIcon(QStyle.SP_ComputerIcon)

        self.tray = QSystemTrayIcon(icon, self)
        self.tray.setToolTip("Desktop Pet (doei)")

        tray_menu = QMenu()
        tray_menu.setStyleSheet(MACOS_MENU_QSS)  # may be ignored by OS for tray menus

        tray_menu.addAction("Show", self.show_normal)
        tray_menu.addAction("Hide", self.hide_all)
        tray_menu.addSeparator()

        tray_menu.addAction("Sit (Focus)", lambda: self.set_state("sit", say=True, title="<b>Focus</b>", text=random.choice(self._encourage_lines())))
        tray_menu.addAction("Lay Down (Break)", lambda: self.set_state("laydown", say=True, title="<b>Break</b>", text="Take 60 seconds. Roll your shoulders."))
        tray_menu.addSeparator()

        tray_menu.addAction("Walk roundtrip", lambda: self.start_roundtrip(announce=True))
        tray_menu.addSeparator()

        tray_menu.addAction("Start Pomodoro (25/5)", self.start_pomodoro)
        tray_menu.addAction("Stop Pomodoro", self.stop_pomodoro)
        tray_menu.addSeparator()

        tray_menu.addAction("Snooze Rest 10 min", lambda: self.snooze_rest(10))
        tray_menu.addSeparator()

        self._act_auto_roundtrip = tray_menu.addAction("Auto roundtrip: ON", self.toggle_auto_roundtrip)
        self._act_rest_toggle_tray = tray_menu.addAction("Rest Reminder: ON", self.toggle_rest_reminder)
        self._act_chatter_toggle_tray = tray_menu.addAction("Random Chatter: ON", self.toggle_chatter)
        self._act_lock_toggle_tray = tray_menu.addAction("Lock: OFF", self.toggle_lock)

        tray_menu.addSeparator()
        tray_menu.addAction("Quit", QApplication.quit)

        self.tray.setContextMenu(tray_menu)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()
        self._refresh_toggle_texts()

    def _build_menu(self) -> QMenu:
        m = QMenu(self)
        m.setStyleSheet(MACOS_MENU_QSS)

        m.addAction("Motivate me", lambda: self._notify("<b>Keep going</b>", random.choice(self._encourage_lines()), ms=2400))
        m.addAction("Take a short break", lambda: self.set_state("laydown", say=True, title="<b>Break</b>", text="Breathe in, breathe out."))
        m.addSeparator()

        m.addAction("Walk roundtrip", lambda: self.start_roundtrip(announce=True))
        m.addSeparator()

        m.addAction("Start Pomodoro (25/5)", self.start_pomodoro)
        m.addAction("Stop Pomodoro", self.stop_pomodoro)
        m.addSeparator()

        m.addAction("Snooze Rest 10 min", lambda: self.snooze_rest(10))
        m.addSeparator()

        m.addAction("Toggle Auto roundtrip", self.toggle_auto_roundtrip)
        m.addAction("Toggle Rest Reminder", self.toggle_rest_reminder)
        m.addAction("Toggle Random Chatter", self.toggle_chatter)
        m.addAction("Lock / Unlock", self.toggle_lock)
        m.addSeparator()

        size_menu = m.addMenu("Size")
        size_menu.setStyleSheet(MACOS_MENU_QSS)
        size_menu.addAction("Small (50%)", lambda: self._set_scale(0.5))
        size_menu.addAction("Medium (75%)", lambda: self._set_scale(0.75))
        size_menu.addAction("Normal (100%)", lambda: self._set_scale(1.0))
        size_menu.addAction("Large (125%)", lambda: self._set_scale(1.25))

        m.addSeparator()
        m.addAction("Hide", self.hide_all)
        m.addAction("Quit", QApplication.quit)
        return m

    def _refresh_toggle_texts(self):
        self._act_auto_roundtrip.setText(f"Auto roundtrip: {'ON' if self.auto_roundtrip_enabled else 'OFF'}")
        self._act_rest_toggle_tray.setText(f"Rest Reminder: {'ON' if self.rest_enabled else 'OFF'}")
        self._act_chatter_toggle_tray.setText(f"Random Chatter: {'ON' if self.chatter_enabled else 'OFF'}")
        self._act_lock_toggle_tray.setText(f"Lock: {'ON' if self.locked else 'OFF'}")

    def show_normal(self):
        self.show()
        self.raise_()

    def hide_all(self):
        self.hide()
        self.bubble.hide()

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.Trigger:  # left click
            self.hide_all() if self.isVisible() else self.show_normal()

    # -------------------------
    # Pomodoro
    # -------------------------
    def start_pomodoro(self):
        if self.pomo_running:
            self._notify("<b>Pomodoro</b>", "Already running.", ms=1800)
            return
        self.pomo_running = True
        self._pomo_mode = "work"
        self._pomo_left = self.pomo_work_sec
        self.set_state("sit", say=False)
        self._pomo_timer.start(1000)
        self._show_pomo_bubble(first=True)

    def stop_pomodoro(self):
        self._pomo_timer.stop()
        self.pomo_running = False
        self._notify("<b>Pomodoro</b>", "Stopped.", ms=2000)

    def _pomo_force_break(self):
        if not self.pomo_running:
            self._notify("<b>Pomodoro</b>", "Start it first.", ms=1800)
            return
        self._pomo_mode = "break"
        self._pomo_left = self.pomo_break_sec
        self.set_state("laydown", say=False)
        self._notify("<b>Break</b>", "Starting break now.", ms=1800)
        self._show_pomo_bubble()

    def _pomo_force_work(self):
        if not self.pomo_running:
            self._notify("<b>Pomodoro</b>", "Start it first.", ms=1800)
            return
        self._pomo_mode = "work"
        self._pomo_left = self.pomo_work_sec
        self.set_state("sit", say=False)
        self._notify("<b>Focus</b>", "Back to work.", ms=1800)
        self._show_pomo_bubble()

    def _pomo_countdown_line(self) -> str:
        if not self.pomo_running:
            return ""
        label = "Focus" if self._pomo_mode == "work" else "Break"
        return f"{label}: {_fmt_mmss(self._pomo_left)} remaining"

    def _show_pomo_bubble(self, first: bool = False):
        if not self.pomo_running:
            return

        if self._pomo_mode == "work":
            title = "<b>Focus time</b>"
            msg = "Write one small piece: <b>one sentence</b> or <b>one citation</b>."
            buttons = [("Start break", self._pomo_force_break), ("Snooze 10 min", lambda: self.snooze_rest(10))]
        else:
            title = "<b>Break time</b>"
            msg = "Stand up. Stretch your neck & shoulders."
            buttons = [("Back to focus", self._pomo_force_work), ("Snooze 10 min", lambda: self.snooze_rest(10))]

        self.bubble.show_bubble(
            title_html=title,
            message_html=msg,
            anchor_pos=self._bubble_anchor_global(),
            ms=0,
            buttons=buttons,
            dynamic_getter=self._pomo_countdown_line,
            dynamic_interval_ms=1000,
        )

        if first:
            try:
                self.tray.showMessage("Desktop Pet", "Pomodoro started.", QSystemTrayIcon.Information, 2000)
            except Exception:
                pass

    def _tick_pomo(self):
        self._pomo_left -= 1
        if self._pomo_left <= 0:
            if self._pomo_mode == "work":
                self._pomo_mode = "break"
                self._pomo_left = self.pomo_break_sec
                self.set_state("laydown", say=False)
                self._notify("<b>Time's up</b>", "Nice work. Break time starts now.", ms=2600)
            else:
                self._pomo_mode = "work"
                self._pomo_left = self.pomo_work_sec
                self.set_state("sit", say=False)
                self._notify("<b>Time's up</b>", "Break over. Back to focus.", ms=2600)
            self._show_pomo_bubble()
        self._sync_bubble_anchor()

    # -------------------------
    # Rest reminder + snooze
    # -------------------------
    def _apply_rest_state(self):
        self._rest_snooze_timer.stop()
        if self.rest_enabled:
            self._rest_timer.start(self.rest_interval_min * 60 * 1000)
        else:
            self._rest_timer.stop()
        self._refresh_toggle_texts()

    def toggle_rest_reminder(self):
        self.rest_enabled = not self.rest_enabled
        self.settings.setValue("rest_enabled", self.rest_enabled)
        self._apply_rest_state()
        self._notify("<b>Rest reminder</b>", "ON ✅" if self.rest_enabled else "OFF ❎", ms=2200)

    def snooze_rest(self, minutes: int = 10):
        if minutes <= 0:
            return
        self._rest_timer.stop()
        self._rest_snooze_timer.start(int(minutes) * 60 * 1000)
        self._notify("<b>Snoozed</b>", f"Rest reminder paused for {minutes} min.", ms=2400)

    def _resume_rest_after_snooze(self):
        if self.rest_enabled:
            self._rest_timer.start(self.rest_interval_min * 60 * 1000)

    def _rest_ping(self):
        tips = [
            "Time to stretch. Relax your shoulders.",
            "Hydration check ✅ Take a sip of water.",
            "Look 20 seconds at something far away.",
            "Stand up for 30 seconds—your neck will thank you.",
        ]
        # Rest forces laydown temporarily
        self._roundtrip_active = False
        self._roundtrip_edge_hits_remaining = 0
        self.set_state("laydown", say=False)
        self._rest_pose_back_timer.start(AUTO_REST_POSE_MS)

        buttons = [
            ("Snooze 10 min", lambda: self.snooze_rest(10)),
        ]
        self._notify("<b>Rest time</b>", random.choice(tips), ms=0, buttons=buttons)

    # -------------------------
    # Random chatter
    # -------------------------
    def _apply_chatter_state(self):
        if self.chatter_enabled:
            self._schedule_next_chatter()
        else:
            self._chatter_timer.stop()
        self._refresh_toggle_texts()

    def toggle_chatter(self):
        self.chatter_enabled = not self.chatter_enabled
        self.settings.setValue("chatter_enabled", self.chatter_enabled)
        self._apply_chatter_state()
        self._notify("<b>Random chatter</b>", "ON ✅" if self.chatter_enabled else "OFF ❎", ms=2200)

    def _schedule_next_chatter(self):
        self._chatter_timer.start(random.randint(CHATTER_MIN_MS, CHATTER_MAX_MS))

    def _encourage_lines(self):
        return [
            "Write one sentence. That’s progress.",
            "Draft first, polish later.",
            "Keep it simple: one paragraph at a time.",
            "Cite as you go—future you will thank you.",
            "If it feels hard, shrink the task.",
            "Save your work. Ctrl+S 😉",
        ]

    def _chatter_once(self):
        if self.chatter_enabled and self.isVisible() and (not self._dragging):
            if random.random() < 0.6:
                self._notify("<b>Keep going</b>", random.choice(self._encourage_lines()), ms=2600)
        if self.chatter_enabled:
            self._schedule_next_chatter()

    # -------------------------
    # Lock
    # -------------------------
    def toggle_lock(self):
        self.locked = not self.locked
        self.settings.setValue("locked", self.locked)
        self._refresh_toggle_texts()
        self._notify("<b>Lock</b>", "Locked 🔒 (no dragging)" if self.locked else "Unlocked 🔓 (dragging enabled)", ms=2400)

    # -------------------------
    # Mouse interaction
    # -------------------------
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._moved = False
            self._click_timer.start()

            if self.locked:
                self._dragging = False
                event.accept()
                return

            self._dragging = True
            self._press_global = event.globalPosition().toPoint()
            self._drag_offset = self._press_global - self.frameGeometry().topLeft()
            event.accept()

        elif event.button() == Qt.RightButton:
            self.menu.popup(event.globalPosition().toPoint())
            event.accept()

    def mouseMoveEvent(self, event):
        if self._dragging:
            gp = event.globalPosition().toPoint()
            if (gp - self._press_global).manhattanLength() > self._drag_threshold:
                self._moved = True
            self.move(gp - self._drag_offset)
            self._sync_bubble_anchor()
            event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            is_click = (self._click_timer.elapsed() < 350)

            if self._dragging:
                self._dragging = False
                self._ensure_on_screen()
                self._snap_to_edges()
                self._save_position()

                if (not self._moved) and is_click:
                    self._notify("<b>Focus</b>", random.choice(self._encourage_lines()), ms=2400)
                event.accept()
                return

            if self.locked and is_click:
                self._notify("<b>Locked</b>", "Right click to unlock.", ms=2200)
                event.accept()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            if self.state == "sit":
                self.set_state("laydown", say=True, title="<b>Break</b>", text="Quick break. Breathe in, breathe out.")
            else:
                self.set_state("sit", say=True, title="<b>Focus</b>", text="Back to it. One small step.")
            event.accept()


def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    pet = DesktopPet()
    pet.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
