# ui.py – Complete upgraded PyQt5 Chat UI
# Glass-Neon + Dark/Aurora theme, collapsible sidebar, animated theme transition,
# creative 'pastel sunrise' light mode, preserved public API & signals.
import os
import base64
from datetime import datetime
from functools import partial

from PyQt5.QtCore import (
    Qt,
    pyqtSignal,
    QTimer,
    QEasingCurve,
    QPropertyAnimation,
    QPointF,
    QSettings,
    QBuffer,
    QByteArray,
)
from PyQt5.QtGui import QImage, QPixmap, QColor, QFont, QIcon, QPainter, QRadialGradient
from PyQt5.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLineEdit,
    QFileDialog,
    QLabel,
    QRadioButton,
    QProgressBar,
    QScrollArea,
    QFrame,
    QListWidget,
    QListWidgetItem,
    QGraphicsDropShadowEffect,
    QSlider,
    QGroupBox,
    QMessageBox,
    QSizePolicy,
    QAction,
    QStackedLayout,
)
from PyQt5.QtWidgets import QSplitter


# ------------------- Helpers -------------------
def time_ts() -> int:
    return int(datetime.now().timestamp())


def is_image_filename(path: str) -> bool:
    ext = os.path.splitext(path)[1].lower()
    return ext in {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}


def _thumb_b64(path: str, max_h: int = 96) -> str:
    if not is_image_filename(path):
        return ""
    img = QImage(path)
    if img.isNull():
        return ""
    scaled = img.scaledToHeight(max_h, Qt.SmoothTransformation)
    buf = QBuffer()
    buf.open(QBuffer.ReadWrite)
    scaled.save(buf, "PNG")
    return base64.b64encode(bytes(buf.data())).decode("ascii")


# ------------------- Message & File Cards -------------------
class MessageCard(QFrame):
    def __init__(self, sender, text, mine=False, ts=None, theme="dark"):
        super().__init__()
        self.sender = sender
        self.text = text
        self.mine = mine
        self.ts = ts
        self.theme = theme
        self._build()

    def _build(self):
        # Clear layout if rebuilding
        try:
            if self.layout():
                for i in reversed(range(self.layout().count())):
                    item = self.layout().itemAt(i)
                    if item.widget():
                        item.widget().setParent(None)
                # Remove the old layout
                QWidget().setLayout(self.layout())
        except Exception:
            pass

        self.setFrameShape(QFrame.NoFrame)

        # Visuals based on theme
        if self.mine:
            if self.theme == "dark":
                bg = "qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #7c3aed, stop:1 #4f46e5)"
                text_color = "#ffffff"
            else:
                # pastel sunrise variant
                bg = "qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #ffd6b6, stop:1 #7ee7d8)"
                text_color = "#0f1724"
        else:
            bg = "#111216" if self.theme == "dark" else "#fffaf6"
            text_color = "#fff" if self.theme == "dark" else "#0f1724"

        self.setStyleSheet(
            f"""
            QFrame {{
              border-radius: 14px;
              background: {bg};
              padding: 12px 14px;
              margin: 6px 8px;
            }}
            QLabel {{ color: {text_color}; background: transparent; border: none; }}
            """
        )

        # Drop shadow (subtle)
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(20)
        if self.theme == "dark":
            shadow.setColor(QColor(0, 0, 0, 120))
        else:
            shadow.setColor(QColor(15, 23, 36, 18))
        shadow.setOffset(0, 6)
        self.setGraphicsEffect(shadow)

        v = QVBoxLayout(self)
        v.setSpacing(6)
        v.setContentsMargins(8, 8, 8, 8)

        top = QHBoxLayout()
        self.name_label = QLabel(f"{self.sender}")
        self.name_label.setStyleSheet(f"font-weight:700; color: {text_color};")
        if self.mine:
            top.addStretch(1)
            top.addWidget(self.name_label)
        else:
            top.addWidget(self.name_label)
            top.addStretch(1)

        if self.ts:
            self.ts_label = QLabel(datetime.fromtimestamp(self.ts).strftime("%H:%M"))
            ts_style = "color: rgba(255,255,255,0.6);" if self.theme == "dark" else "color: rgba(15,23,36,0.6);"
            self.ts_label.setStyleSheet(ts_style)
            top.addWidget(self.ts_label)

        v.addLayout(top)

        self.msg_label = QLabel(self.text)
        self.msg_label.setWordWrap(True)
        self.msg_label.setStyleSheet(f"color: {text_color}; font-size:14px; line-height:1.45;")
        v.addWidget(self.msg_label)

        self.setMaximumWidth(700)

    def _animate_in(self):
        anim = QPropertyAnimation(self, b"windowOpacity")
        anim.setDuration(240)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.start()
        self._fade_anim = anim

    def set_zoom(self, zoom_level: float):
        name_size = int(13 * zoom_level)
        msg_size = int(14 * zoom_level)
        text_color = "#fff" if self.theme == "dark" else "#0f1724"
        self.name_label.setStyleSheet(f"font-weight:700; color: {text_color}; font-size:{name_size}px;")
        self.msg_label.setStyleSheet(f"color: {text_color}; font-size:{msg_size}px; line-height:1.45;")
        if self.ts:
            ts_color = "rgba(255,255,255,0.6)" if self.theme == "dark" else "rgba(15,23,36,0.6)"
            self.ts_label.setStyleSheet(f"color: {ts_color}; font-size:{int(11*zoom_level)}px;")


class FileCard(QFrame):
    actionRequested = pyqtSignal(str, str)

    def __init__(self, sender, fname, size, offer_id, thumb_b64, theme="dark"):
        super().__init__()
        self.offer_id = offer_id
        self.theme = theme
        # Store all parameters as instance variables
        self.sender = sender
        self.fname = fname
        self.size = size
        self.thumb_b64 = thumb_b64
        self._build()

    def _build(self):
        # Use stored instance variables
        sender = self.sender
        fname = self.fname
        size = self.size
        thumb_b64 = self.thumb_b64
        
        # clear previous layout children (if any)
        try:
            if self.layout():
                for i in reversed(range(self.layout().count())):
                    item = self.layout().itemAt(i)
                    if item.widget():
                        item.widget().setParent(None)
                # Remove the old layout
                QWidget().setLayout(self.layout())
        except Exception:
            pass

        self.setFrameShape(QFrame.NoFrame)

        bg = "qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #2b2b2f, stop:1 #1f1f21)" if self.theme == "dark" else "#fff8f3"
        text_color = "#fff" if self.theme == "dark" else "#0f1724"

        self.setStyleSheet(
            f"""
            QFrame {{
              background: {bg};
              border-radius: 14px;
              border: 1px solid rgba(255,255,255,0.06);
              padding: 14px;
              margin: 6px 8px;
            }}
            QPushButton {{
              background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #667eea, stop:1 #764ba2);
              color: white; border-radius: 10px; padding: 8px 14px; font-weight:600; font-size:13px; border:none;
            }}
            QLabel {{ color: {text_color}; background: transparent; }}
            """
        )

        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(22)
        shadow.setColor(QColor(0, 0, 0, 110))
        shadow.setOffset(0, 6)
        self.setGraphicsEffect(shadow)

        v = QVBoxLayout(self)
        v.setSpacing(10)
        v.setContentsMargins(8, 8, 8, 8)

        head = QHBoxLayout()
        icon = QLabel("📎")
        icon.setStyleSheet("font-size:20px;")
        head.addWidget(icon)

        info = QVBoxLayout()
        title = QLabel(f"<b>{fname}</b>")
        title.setWordWrap(True)
        title.setStyleSheet("font-size:14px;")
        meta = QLabel(f"{self._fmt_size(size)} · from {sender}")
        meta.setStyleSheet("font-size:12px; color: rgba(255,255,255,0.6);" if self.theme == "dark" else "font-size:12px; color: rgba(15,23,36,0.6);")
        info.addWidget(title)
        info.addWidget(meta)
        head.addLayout(info, 1)
        v.addLayout(head)

        if thumb_b64:
            pixmap = QPixmap()
            pixmap.loadFromData(base64.b64decode(thumb_b64))
            th = QLabel()
            th.setPixmap(pixmap.scaledToHeight(120, Qt.SmoothTransformation))
            th.setAlignment(Qt.AlignCenter)
            th.setStyleSheet("border-radius:8px;")
            v.addWidget(th)

        btns = QHBoxLayout()
        self.prev_btn = QPushButton("👁 Preview")
        self.dl_btn = QPushButton("⬇ Download")
        btns.addWidget(self.prev_btn)
        btns.addWidget(self.dl_btn)
        v.addLayout(btns)

        self.progress = QProgressBar()
        self.progress.setTextVisible(True)
        self.progress.setVisible(False)
        self.progress.setFixedHeight(8)
        self.progress.setStyleSheet(
            """
            QProgressBar { border:none; border-radius:4px; background: rgba(255,255,255,0.06); text-align:center; }
            QProgressBar::chunk { background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #667eea, stop:1 #764ba2); border-radius:4px; }
            """
        )
        v.addWidget(self.progress)

        self.prev_btn.clicked.connect(lambda: self.actionRequested.emit("preview", self.offer_id))
        self.dl_btn.clicked.connect(lambda: self.actionRequested.emit("download", self.offer_id))

        self.setMaximumWidth(700)

    def _animate_in(self):
        anim = QPropertyAnimation(self, b"windowOpacity")
        anim.setDuration(240)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.start()
        self._fade_anim = anim

    @staticmethod
    def _fmt_size(size: int) -> str:
        for unit in ["B", "KB", "MB", "GB"]:
            if size < 1024.0:
                return f"{size:.1f} {unit}"
            size /= 1024.0
        return f"{size:.1f} TB"


# ------------------- Main UI -------------------
class ChatUI(QWidget):
    # Signals used by client.py
    connectRequested = pyqtSignal(dict)  # {username, password, host, protocol}
    disconnectRequested = pyqtSignal()
    sendMessageRequested = pyqtSignal(str)
    shareFileRequested = pyqtSignal(str, str)  # path, thumb_b64
    fileActionRequested = pyqtSignal(str, str)  # action, offer_id

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Reach Chat – Secure Edition")
        self.setWindowIcon(QIcon.fromTheme("chat") if not QIcon.fromTheme("chat").isNull() else QIcon())
        self.resize(1280, 820)
        self.zoom_level = 1.0
        self.auto_scroll = True

        # settings
        self.settings = QSettings("reach", "reach_chat")
        self.theme = self.settings.value("theme", "dark")
        self.sidebar_open = True

        # Prepare overlay used in theme transition
        self._init_theme_overlay()

        # Apply base theme & build UI
        self._apply_theme(initial=True)
        self._build()

    # ---------------- Theme / QSS ----------------
    def _qss_common(self):
        # Common QSS snippets (component-neutral)
        return """
            QWidget { font-family: -apple-system, 'Segoe UI', Roboto, Ubuntu, Cantarell, sans-serif; }
            QLabel { background: transparent; }
            QScrollArea { background: transparent; }
        """

    def _qss_dark(self):
        # Dark theme core: Glass + Neon accents
        return f"""
        {self._qss_common()}
        QWidget {{
            background: #0b0b10;
            color: #F3F4F6;
        }}
        QLineEdit {{
            background: #0f1113;
            color: #F3F4F6;
            border: 1px solid rgba(255,255,255,0.04);
            border-radius: 10px;
            padding: 10px;
        }}
        QLineEdit:focus {{
            border: 1px solid #6366f1;
            box-shadow: 0 8px 30px rgba(99,102,241,0.08);
        }}
        QPushButton {{
            background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #667eea, stop:1 #764ba2);
            color: white; border:none; border-radius:10px; padding:8px 14px; font-weight:600;
        }}
        QPushButton:disabled {{ background: rgba(255,255,255,0.06); color: rgba(255,255,255,0.4); }}
        QListWidget {{ background: transparent; color: #F3F4F6; border:none; }}
        """

    def _qss_light(self):
        # Pastel sunrise – soft warm gradient, rich text contrast
        return f"""
        {self._qss_common()}
        QWidget {{
            background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #fff8f1, stop:1 #f3fbfb);
            color: #0f1724;
        }}
        QLineEdit {{
            background: rgba(255,255,255,0.92);
            color: #0f1724;
            border: 1px solid rgba(15,23,36,0.15);
            border-radius: 10px;
            padding: 10px;
        }}
        QLineEdit:focus {{
            border: 1px solid #4f46e5;
            box-shadow: 0 4px 18px rgba(79,70,229,0.1);
        }}
        QPushButton {{
            background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #ffd6b6, stop:1 #7ee7d8);
            color: #07202b;
            font-weight: 600;
            border: none;
            border-radius: 10px;
            padding: 8px 14px;
        }}
        QPushButton:disabled {{
            background: rgba(0,0,0,0.05);
            color: rgba(0,0,0,0.3);
        }}
        QListWidget {{
            background: transparent;
            color: #0f1724;
            border: none;
        }}
        QLabel {{
            color: #0f1724;
        }}
        QScrollBar:vertical {{
            background: transparent;
            width: 8px;
        }}
        QScrollBar::handle:vertical {{
            background: rgba(15,23,36,0.15);
            border-radius: 4px;
            min-height: 20px;
        }}
        QListWidget::item {{
            color: #0f1724;
        }}
        QGroupBox {{
            color: #0f1724;
            font-weight: 600;
        }}
        QGroupBox::title {{
            color: #0f1724;
        }}
        QScrollBar:vertical {{
            background: transparent;
            width: 8px;
        }}
        QScrollBar::handle:vertical {{
            background: rgba(15,23,36,0.25);
            border-radius: 4px;
            min-height: 20px;
        }}
        QScrollBar::handle:vertical:hover {{
            background: rgba(15,23,36,0.35);
        }}
        
        """


    def _apply_theme(self, initial=False):
        # Apply right QSS and palette variables
        if self.theme == "dark":
            self.primary_bg = "#0b0b10"
            self.surface = "rgba(255,255,255,0.04)"
            self.text = "#f3f4f6"
            self.muted = "rgba(255,255,255,0.65)"
            self.card_border = "rgba(255,255,255,0.06)"
            self.accent1 = "#6366f1"
            self.accent2 = "#8b5cf6"
            qss = self._qss_dark()
        else:
            # Pastel sunrise light theme
            self.primary_bg = "#fff8f1"
            self.surface = "rgba(255,255,255,0.85)"
            self.text = "#0f1724"
            self.muted = "#4a5568"  # Darker solid color for better visibility
            self.card_border = "rgba(0,0,0,0.08)"
            self.accent1 = "#ffd6b6"
            self.accent2 = "#7ee7d8"
            qss = self._qss_light()

        # set application stylesheet
        self.setStyleSheet(qss)

        # update any dynamic widgets immediately (if UI built)
        try:
            self._restyle_dynamic_widgets()
        except Exception as e:
            print(f"[UI] Error restyling widgets: {e}")

        # save
        if not initial:
            self.settings.setValue("theme", self.theme)

    def _restyle_dynamic_widgets(self):
        # update status visuals & some elements
        if not hasattr(self, 'left'):
            return
            
        self.left.setStyleSheet(f"QFrame {{ background: {self.surface}; border:1px solid {self.card_border}; border-radius:14px; }}")
        self.status_card.setStyleSheet(f"QFrame {{ background: transparent; border-radius:12px; padding:10px; }}")
        self.chat_container.setStyleSheet(f"QFrame {{ background: transparent; border-radius:12px; padding:6px; }}")
        # update left logo colors
        self.logo.setStyleSheet(
            f"border-radius:10px; background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 {self.accent1}, stop:1 {self.accent2}); color: #071127; font-weight:800; font-size:18px;"
        )
        # update existing message/file cards theme
        for i in range(self.chat_list.count()):
            lay = self.chat_list.itemAt(i)
            if lay is None or lay.layout() is None:
                continue
            for j in range(lay.layout().count()):
                item = lay.layout().itemAt(j)
                w = item.widget()
                if isinstance(w, MessageCard):
                    w.theme = self.theme
                    w._build()
                elif isinstance(w, FileCard):
                    w.theme = self.theme
                    w._build()  # Now works because FileCard stores its own data
        # update theme button icon
        if hasattr(self, "theme_btn"):
            self.theme_btn.setText("🌙" if self.theme == "dark" else "🌤️")

        if hasattr(self, 'subtitle'):
            subtitle_color = "#4a5568" if self.theme == "light" else self.muted
            for i in range(self.left.layout().count()):
                item = self.left.layout().itemAt(i)
                if item and item.layout():
                    for j in range(item.layout().count()):
                        w = item.layout().itemAt(j).widget()
                        if isinstance(w, QLabel) and w.text() == "Secure • Fast • Private":
                            w.setStyleSheet(f"font-size:12px; color: {subtitle_color}; font-weight: 500;")
        
        # Update protocol/server display colors
        if hasattr(self, 'protocol_display') and hasattr(self, 'server_display'):
            display_color = "#4a5568" if self.theme == "light" else self.muted
            self.protocol_display.setStyleSheet(f"color: {display_color}; font-weight:600;")
            self.server_display.setStyleSheet(f"color: {display_color}; font-weight:600;")
    
    # ---------------- Theme transition overlay ----------------
    def _init_theme_overlay(self):
        # overlay widget used to animate theme switches (radial sweep + fade)
        self.overlay = QWidget(self)
        self.overlay.hide()
        self.overlay.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.overlay.setStyleSheet("background: transparent;")
        self.overlay.raise_()

    def _on_theme_toggle_clicked(self):
    
        # Determine the next theme
        new_theme = "light" if self.theme == "dark" else "dark"

        def apply_new_theme():
            # Actually switch and apply theme
            self.theme = new_theme
            self._apply_theme()
            self.settings.setValue("theme", self.theme)
            # update the button icon immediately
            if hasattr(self, "theme_btn"):
                self.theme_btn.setText("🌙" if self.theme == "dark" else "🌤️")
            print(f"[Theme] Switched to {self.theme}")

        # If overlay exists, animate smoothly
        if hasattr(self, "overlay"):
            self._animate_theme_transition(on_complete=apply_new_theme)
        else:
            apply_new_theme()


    def _animate_theme_transition(self, on_complete=None):
        """
        Fixed overlay animation for theme switching (fade + radial glow)
        Ensures callback triggers and hides overlay properly.
        """
        # Ensure overlay exists
        if not hasattr(self, "overlay"):
            self.overlay = QWidget(self)
            self.overlay.hide()
            self.overlay.setAttribute(Qt.WA_TransparentForMouseEvents)
            self.overlay.setStyleSheet("background: transparent;")
            self.overlay.raise_()

        self.overlay.show()
        self.overlay.raise_()
        self.overlay.setGeometry(self.rect())

        # Add missing properties
        self.overlay._opacity = 0.0
        self.overlay._radial_progress = 0.0

        def paint_event(ev):
            p = QPainter(self.overlay)
            p.setRenderHint(QPainter.Antialiasing)
            opacity = getattr(self.overlay, "_opacity", 0.0)
            prog = getattr(self.overlay, "_radial_progress", 0.0)

            cx = self.overlay.width() // 2
            cy = self.overlay.height() // 2
            r = max(self.overlay.width(), self.overlay.height()) * (0.4 + 0.8 * prog)

            grad = QRadialGradient(cx, cy, r)
            if self.theme == "dark":
                grad.setColorAt(0.0, QColor(78, 62, 183, int(180 * opacity)))
                grad.setColorAt(1.0, QColor(10, 6, 30, int(160 * opacity)))
            else:
                grad.setColorAt(0.0, QColor(255, 214, 182, int(200 * opacity)))
                grad.setColorAt(1.0, QColor(243, 251, 251, int(180 * opacity)))

            p.fillRect(self.overlay.rect(), grad)
            p.end()

        self.overlay.paintEvent = paint_event

        # Animate opacity
        anim = QPropertyAnimation(self.overlay, b"windowOpacity")
        anim.setDuration(400)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.InOutQuad)

        def step_opacity(value):
            self.overlay._opacity = value
            self.overlay._radial_progress = value
            self.overlay.update()

        anim.valueChanged.connect(step_opacity)

        def fade_out():
            if on_complete:
                on_complete()  # ✅ Apply new theme at peak of fade

            anim_out = QPropertyAnimation(self.overlay, b"windowOpacity")
            anim_out.setDuration(400)
            anim_out.setStartValue(1.0)
            anim_out.setEndValue(0.0)
            anim_out.setEasingCurve(QEasingCurve.InOutQuad)

            def step_out(value):
                self.overlay._opacity = value
                self.overlay._radial_progress = max(0.0, 1.0 - value)
                self.overlay.update()

            anim_out.valueChanged.connect(step_out)
            anim_out.finished.connect(lambda: self.overlay.hide())
            anim_out.start()
            self._theme_anim_out = anim_out

        anim.finished.connect(fade_out)
        anim.start()
        self._theme_anim_in = anim

    # ------------------- Build UI -------------------
    def _build(self):
        # Left sidebar
        left = QFrame(self)
        left.setMinimumWidth(240)
        left.setMaximumWidth(600)

        left.setStyleSheet(f"QFrame {{ background: {self.surface}; border:1px solid {self.card_border}; border-radius:14px; }}")
        left_v = QVBoxLayout(left)
        left_v.setContentsMargins(16, 16, 16, 16)
        left_v.setSpacing(12)

        # Brand row (logo + title + theme toggle + collapse)
        brand = QHBoxLayout()
        self.logo = QLabel("RC")
        self.logo.setFixedSize(48, 48)
        self.logo.setAlignment(Qt.AlignCenter)
        self.logo.setStyleSheet(
            f"border-radius:12px; background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 {self.accent1}, stop:1 {self.accent2}); color: #071127; font-weight:800; font-size:18px;"
        )
        brand.addWidget(self.logo)

        title_v = QVBoxLayout()
        app_title = QLabel("Reach Chat")
        app_title.setStyleSheet("font-size:16px; font-weight:800;")
        subtitle = QLabel("Secure • Fast • Private")
        subtitle.setStyleSheet(f"font-size:12px; color: {self.muted};")
        title_v.addWidget(app_title)
        title_v.addWidget(subtitle)
        brand.addLayout(title_v)
        brand.addStretch()

        # theme toggle
        self.theme_btn = QPushButton("🌙" if self.theme == "dark" else "🌤️")
        self.theme_btn.setFixedSize(40, 40)
        self.theme_btn.setStyleSheet("border-radius:10px; background: transparent;")
        self.theme_btn.clicked.connect(self._on_theme_toggle_clicked)
        brand.addWidget(self.theme_btn)

        # collapse button
        self.collapse_btn = QPushButton("⟨")
        self.collapse_btn.setFixedSize(32, 32)
        self.collapse_btn.setStyleSheet("border-radius:8px; background: transparent;")
        self.collapse_btn.clicked.connect(self._toggle_sidebar)
        brand.addWidget(self.collapse_btn)

        left_v.addLayout(brand)

        # status card
        status_card = QFrame()
        status_card.setStyleSheet(f"QFrame {{ background: transparent; border-radius:12px; padding:10px; }}")
        sc_v = QVBoxLayout(status_card)
        sc_h = QHBoxLayout()
        self.status_dot = QLabel()
        self.status_dot.setFixedSize(12, 12)
        self._update_status_dot("disconnected")
        sc_h.addWidget(self.status_dot)
        sc_h.addSpacing(8)
        self.status_label = QLabel("Disconnected")
        self.status_label.setStyleSheet("font-weight:600;")
        sc_h.addWidget(self.status_label)
        sc_h.addStretch()
        sc_v.addLayout(sc_h)

        proto_row = QHBoxLayout()
        proto_lbl = QLabel("Protocol:")
        proto_lbl.setStyleSheet("font-weight: 600;")
        proto_row.addWidget(proto_lbl)
        self.protocol_display = QLabel("tcp")
        display_color = "#4a5568" if self.theme == "light" else self.muted
        self.protocol_display.setStyleSheet(f"color: {display_color}; font-weight:600;")
        proto_row.addWidget(self.protocol_display)
        proto_row.addStretch()
        sc_v.addLayout(proto_row)

        server_row = QHBoxLayout()
        srv_lbl = QLabel("Server:")
        srv_lbl.setStyleSheet("font-weight: 600;")
        server_row.addWidget(srv_lbl)
        self.server_display = QLabel("127.0.0.1")
        self.server_display.setStyleSheet(f"color: {display_color}; font-weight:600;")


        server_row.addWidget(self.server_display)
        sc_v.addLayout(server_row)

        left_v.addWidget(status_card)

        # Active users list
        # Active users list
        users_label = QLabel("Active Users")
        users_label.setStyleSheet("font-weight: 600; font-size: 13px;")
        left_v.addWidget(users_label)
        self.users_list = QListWidget()
        self.users_list.setSpacing(6)
        left_v.addWidget(self.users_list, 1)

        # zoom controls
        zoom_group = QGroupBox("Chat Zoom")
        z_v = QVBoxLayout()
        z_top = QHBoxLayout()
        z_icon = QLabel("🔍")
        z_top.addWidget(z_icon)
        z_top.addStretch()
        self.zoom_value = QLabel("100%")
        z_top.addWidget(self.zoom_value)
        z_v.addLayout(z_top)
        self.zoom = QSlider(Qt.Horizontal)
        self.zoom.setRange(50, 200)
        self.zoom.setValue(100)
        self.zoom.valueChanged.connect(self._on_zoom_changed)
        z_v.addWidget(self.zoom)
        z_btns = QHBoxLayout()
        z_minus = QPushButton("−")
        z_minus.setFixedSize(32, 32)
        z_minus.clicked.connect(lambda: self.zoom.setValue(max(50, self.zoom.value() - 10)))
        z_reset = QPushButton("Reset")
        z_reset.clicked.connect(lambda: self.zoom.setValue(100))
        z_plus = QPushButton("+")
        z_plus.setFixedSize(32, 32)
        z_plus.clicked.connect(lambda: self.zoom.setValue(min(200, self.zoom.value() + 10)))
        z_btns.addWidget(z_minus)
        z_btns.addWidget(z_reset)
        z_btns.addWidget(z_plus)
        z_v.addLayout(z_btns)
        zoom_group.setLayout(z_v)
        left_v.addWidget(zoom_group)

        # Right / main panel
        right = QWidget()
        right_v = QVBoxLayout(right)
        right_v.setContentsMargins(18, 18, 18, 18)
        right_v.setSpacing(12)

        # Connection card
        conn_card = QFrame()
        conn_card.setStyleSheet(f"QFrame {{ background: {self.surface}; border-radius:14px; padding:12px; border:1px solid {self.card_border}; }}")
        conn_v = QVBoxLayout(conn_card)
        proto_h = QHBoxLayout()
        proto_lbl = QLabel("Protocol:")
        self.protocol_tcp = QRadioButton("TCP (Reliable)")
        self.protocol_udp = QRadioButton("UDP (Fast)")
        self.protocol_tcp.setChecked(True)
        proto_h.addWidget(proto_lbl)
        proto_h.addWidget(self.protocol_tcp)
        proto_h.addWidget(self.protocol_udp)
        proto_h.addStretch()
        conn_v.addLayout(proto_h)

        creds = QHBoxLayout()
        creds.setSpacing(10)
        self.username = QLineEdit()
        self.username.setPlaceholderText("Username")
        self.password = QLineEdit()
        self.password.setPlaceholderText("Password")
        self.password.setEchoMode(QLineEdit.Password)
        self.server_ip = QLineEdit("127.0.0.1")
        self.server_ip.setPlaceholderText("Server IP")
        creds.addWidget(self.username, 1)
        creds.addWidget(self.password, 1)
        creds.addWidget(self.server_ip, 1)
        conn_v.addLayout(creds)

        btn_h = QHBoxLayout()
        btn_h.addStretch()
        self.connect_btn = QPushButton("🔗 Connect")
        self.disconnect_btn = QPushButton("⏹ Disconnect")
        self.disconnect_btn.setEnabled(False)
        self.disconnect_btn.setStyleSheet(
            "QPushButton { background: #dc3545; color: white; border-radius:10px; padding:8px 12px; } QPushButton:disabled { background: rgba(255,255,255,0.06); }"
        )
        btn_h.addWidget(self.connect_btn)
        btn_h.addWidget(self.disconnect_btn)
        conn_v.addLayout(btn_h)

        right_v.addWidget(conn_card)

        # Chat container (scroll)
        chat_container = QFrame()
        chat_container.setStyleSheet(f"QFrame {{ background: transparent; border-radius:12px; padding:6px; }}")
        chat_v = QVBoxLayout(chat_container)
        chat_v.setContentsMargins(0, 0, 0, 0)
        chat_v.setSpacing(8)

        self.chat_list = QVBoxLayout()
        self.chat_list.setAlignment(Qt.AlignTop)
        self.chat_list.setSpacing(8)
        wrapper_widget = QWidget()
        wrapper_widget.setLayout(self.chat_list)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setWidget(wrapper_widget)
        self.scroll.setStyleSheet(
            """
            QScrollArea { border:none; background: transparent; }
            QScrollBar:vertical { background: transparent; width:8px; margin:0; }
            QScrollBar::handle:vertical { background: rgba(255,255,255,0.08); border-radius:4px; min-height:20px; }
            """
        )
        self.scroll.verticalScrollBar().valueChanged.connect(self._on_scroll)
        chat_v.addWidget(self.scroll)
        right_v.addWidget(chat_container, 1)

        # Input card
        input_card = QFrame()
        input_card.setStyleSheet(f"QFrame {{ background: {self.surface}; border-radius:12px; padding:10px; border:1px solid {self.card_border}; }}")
        input_h = QHBoxLayout(input_card)
        input_h.setSpacing(10)
        self.file_btn = QPushButton("📎")
        self.file_btn.setFixedSize(48, 48)
        self.file_btn.setStyleSheet("QPushButton { background: transparent; border-radius: 10px; }")
        self.file_btn.setEnabled(False)
        self.msg_edit = QLineEdit()
        self.msg_edit.setPlaceholderText("Connect to start messaging…")
        self.msg_edit.setEnabled(False)
        self.send_btn = QPushButton("Send 🚀")
        self.send_btn.setMinimumWidth(110)
        self.send_btn.setFixedHeight(48)
        self.send_btn.setEnabled(False)
        input_h.addWidget(self.file_btn)
        input_h.addWidget(self.msg_edit, 1)
        input_h.addWidget(self.send_btn)
        right_v.addWidget(input_card)

        # assemble main layout with splitter
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setSizes([320, 960])
        splitter.setHandleWidth(14)
        splitter.setStyleSheet("""
            QSplitter::handle {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
                             stop:0 #6d28d9, stop:1 #9333ea);
                border-radius: 4px;
            }
            QSplitter::handle:hover {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
                             stop:0 #a78bfa, stop:1 #c084fc);
            }
        """)

        def paint_handle(self, ev):
            p = QPainter(self)
            p.setRenderHint(QPainter.Antialiasing)
            p.setBrush(QColor("#c084fc"))
            w, h = self.width(), self.height()
            for i in range(3):
                y = h/2 - 6 + i*6
                p.drawEllipse(w/2 - 2, y, 4, 4)
            p.end()
        for i in range(splitter.count() - 1):
            handle = splitter.handle(i)
            handle.paintEvent = paint_handle.__get__(handle, type(handle))

        main = QHBoxLayout(self)
        main.setContentsMargins(12, 12, 12, 12)
        main.addWidget(splitter)

        # keep references
        self.left = left
        self.right = right
        self.status_card = status_card
        self.chat_container = chat_container

        # wire signals (preserve existing names)
        self.connect_btn.clicked.connect(self._emit_connect)
        self.disconnect_btn.clicked.connect(self.disconnectRequested.emit)
        self.send_btn.clicked.connect(self._emit_send)
        self.msg_edit.returnPressed.connect(self._emit_send)
        self.file_btn.clicked.connect(self._emit_share)

        # set initial displays
        self.server_display.setText(self.server_ip.text())
        self.protocol_display.setText("udp" if self.protocol_udp.isChecked() else "tcp")
        self.collapse_btn.setToolTip("Collapse sidebar")

    # ---------------- Public API (kept) ----------------
    def lock_connected(self):
        self.username.setEnabled(False)
        self.password.setEnabled(False)
        self.server_ip.setEnabled(False)
        self.protocol_tcp.setEnabled(False)
        self.protocol_udp.setEnabled(False)
        self.connect_btn.setEnabled(False)
        self.disconnect_btn.setEnabled(True)
        self.msg_edit.setEnabled(True)
        self.msg_edit.setPlaceholderText("Type your message…")
        self.send_btn.setEnabled(True)
        self.file_btn.setEnabled(True)
        self._update_status_dot("connected")
        self.status_label.setText("Connected")
        self.server_display.setText(self.server_ip.text())
        self.protocol_display.setText("udp" if self.protocol_udp.isChecked() else "tcp")

    def unlock_disconnected(self):
        self.username.setEnabled(True)
        self.password.setEnabled(True)
        self.server_ip.setEnabled(True)
        self.protocol_tcp.setEnabled(True)
        self.protocol_udp.setEnabled(True)
        self.connect_btn.setEnabled(True)
        self.disconnect_btn.setEnabled(False)
        self.msg_edit.setEnabled(False)
        self.msg_edit.setText("")
        self.msg_edit.setPlaceholderText("Connect to start messaging…")
        self.send_btn.setEnabled(False)
        self.file_btn.setEnabled(False)
        self.users_list.clear()
        self._update_status_dot("disconnected")
        self.status_label.setText("Disconnected")

    def add_system(self, text: str, mine=False):
        card = MessageCard("You" if mine else "System", text, mine=mine, ts=time_ts(), theme=self.theme)
        card.setProperty("mine", mine)
        self._add_widget(card)

    def add_chat(self, sender: str, text: str, mine: bool, ts: int = None):
        card = MessageCard(sender if not mine else "You", text, mine=mine, ts=ts or time_ts(), theme=self.theme)
        card.setProperty("mine", mine)
        self._add_widget(card)

    def add_file_offer(self, sender, filename, size, offer_id, thumb_b64):
        card = FileCard(sender, filename, size, offer_id, thumb_b64, theme=self.theme)
        card.actionRequested.connect(self.fileActionRequested)
        self._add_widget(card)

    def update_progress(self, offer_id, bytes_so_far, total):
        percent = int(bytes_so_far * 100 / max(1, total))
        for i in range(self.chat_list.count()):
            lay = self.chat_list.itemAt(i)
            if lay is None or lay.layout() is None:
                continue
            inner = lay.layout()
            for j in range(inner.count()):
                item = inner.itemAt(j)
                w = item.widget()
                if isinstance(w, FileCard) and getattr(w, "offer_id", None) == offer_id:
                    w.progress.setVisible(True)
                    w.progress.setValue(percent)
                    return

    def update_roster(self, users):
        self.users_list.clear()
        for u in users:
            item = QListWidgetItem(f"🟢 {u}")
            item.setFont(QFont("Segoe UI", 13))
            self.users_list.addItem(item)

    # ---------------- Internal helpers ----------------
    def _add_widget(self, widget):
        wrapper = QHBoxLayout()
        wrapper.setContentsMargins(6, 0, 6, 0)
        if isinstance(widget, MessageCard) and widget.property("mine"):
            wrapper.addStretch(1)
            wrapper.addWidget(widget, 0, Qt.AlignRight)
        else:
            wrapper.addWidget(widget, 0, Qt.AlignLeft)
            wrapper.addStretch(1)
        self.chat_list.addLayout(wrapper)
        if self.auto_scroll:
            QTimer.singleShot(40, self._scroll_to_bottom)

    def _scroll_to_bottom(self):
        sb = self.scroll.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _on_scroll(self):
        sb = self.scroll.verticalScrollBar()
        self.auto_scroll = (sb.value() >= sb.maximum() - 10)

    def _on_zoom_changed(self, val):
        self.zoom_level = val / 100.0
        self.zoom_value.setText(f"{val}%")
        for i in range(self.chat_list.count()):
            lay = self.chat_list.itemAt(i)
            if lay is None or lay.layout() is None:
                continue
            for j in range(lay.layout().count()):
                item = lay.layout().itemAt(j)
                w = item.widget()
                if isinstance(w, MessageCard):
                    w.set_zoom(self.zoom_level)

    # ---------------- Emitters ----------------
    def _emit_connect(self):
        name = self.username.text().strip()
        pwd = self.password.text().strip()
        host = self.server_ip.text().strip()
        if not name or not pwd:
            QMessageBox.warning(self, "Missing Info", "Please enter username and password.")
            return
        protocol = "udp" if self.protocol_udp.isChecked() else "tcp"
        self.connectRequested.emit({"username": name, "password": pwd, "host": host, "protocol": protocol})

    def _emit_send(self):
        msg = self.msg_edit.text().strip()
        if not msg:
            return
        self.sendMessageRequested.emit(msg)
        self.msg_edit.clear()

    def _emit_share(self):
        path, _ = QFileDialog.getOpenFileName(self, "Choose File to Share")
        if not path:
            return
        self.shareFileRequested.emit(path, _thumb_b64(path))

    def _fmt_size(self, size: int) -> str:
        for unit in ["B", "KB", "MB", "GB"]:
            if size < 1024.0:
                return f"{size:.1f} {unit}"
            size /= 1024.0
        return f"{size:.1f} TB"

    def _update_status_dot(self, status):
        if status == "connected":
            color = "#10b981"
        elif status == "connecting":
            color = "#f59e0b"
        elif status == "error":
            color = "#ef4444"
        else:
            color = "#9ca3af"
        self.status_dot.setStyleSheet(f"background: {color}; border-radius: 6px;")

    # ---------------- Sidebar collapse animation ----------------
    def _toggle_sidebar(self):
        target_open = not self.sidebar_open
        start_w = self.left.width() if self.sidebar_open else 0
        end_w = 320 if target_open else 0
        anim = QPropertyAnimation(self.left, b"maximumWidth")
        anim.setDuration(360)
        anim.setStartValue(start_w)
        anim.setEndValue(end_w)
        anim.setEasingCurve(QEasingCurve.InOutCubic)
        anim.start()

        # rotate collapse button glyph
        self.collapse_btn.setText("⟩" if target_open else "⟨")
        self.sidebar_open = target_open
        # keep reference to animation to avoid GC
        self._sidebar_anim = anim