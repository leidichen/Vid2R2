import sys
import os
import hashlib
import threading
import subprocess
import imageio_ffmpeg
import math
import json
import re
import shutil
from datetime import datetime

from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QLabel,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QWidget,
    QProgressBar,
    QDialog,
    QFormLayout,
    QLineEdit,
    QFileDialog,
    QCheckBox,
    QMessageBox,
    QToolButton,
    QMenu,
    QSystemTrayIcon,
    QStyle,
)
from PySide6.QtCore import Qt, Signal, QObject, QThread, QTimer
from PySide6.QtGui import (
    QDragEnterEvent,
    QDropEvent,
    QPixmap,
    QIcon,
    QAction,
    QCloseEvent,
)

import boto3

import config

try:
    import winreg
except ImportError:
    winreg = None

APP_NAME = "Vid2R2"
APP_VERSION = "1.2.1"
if getattr(sys, "frozen", False):
    # 如果是打包后的 EXE，配置文件放在 EXE 同级目录，而不是临时解压目录
    application_path = os.path.dirname(sys.executable)
else:
    application_path = os.path.dirname(__file__)

SETTINGS_FILE = os.path.join(application_path, "vid2r2_settings.json")
AUTOSTART_REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
AUTOSTART_VALUE_NAME = APP_NAME

MIN_COMPRESS_SIZE_BYTES = 25 * 1024 * 1024
SHORT_VIDEO_SECONDS = 20
SHORT_VIDEO_SKIP_BYTES = 40 * 1024 * 1024
MIN_SAVINGS_RATIO = 0.05
BITRATE_THRESHOLDS_MBPS = {
    "hd": 1.8,
    "fhd": 3.0,
    "2k": 5.0,
    "4k": 10.0,
}
HIGH_EFFICIENCY_CODECS = {"hevc", "h265", "vp9", "av1"}
MODERN_CODECS = HIGH_EFFICIENCY_CODECS | {"h264", "avc"}


def format_size(size_bytes):
    if size_bytes <= 0:
        return "0 B"
    size_name = ("B", "KB", "MB", "GB", "TB")
    if size_bytes == 0:
        return "0 B"
    i = int(math.floor(math.log(size_bytes, 1024)))
    p = math.pow(1024, i)
    s = round(size_bytes / p, 2)
    return f"{s} {size_name[i]}"


def format_duration(seconds):
    if not seconds or seconds <= 0:
        return "未知"
    total_seconds = int(round(seconds))
    minutes, secs = divmod(total_seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def default_settings():
    return {
        "r2_access_key_id": getattr(config, "R2_ACCESS_KEY_ID", ""),
        "r2_secret_access_key": getattr(config, "R2_SECRET_ACCESS_KEY", ""),
        "r2_bucket_name": getattr(config, "R2_BUCKET_NAME", ""),
        "r2_region": getattr(config, "R2_REGION", "auto"),
        "r2_endpoint_url": getattr(config, "R2_ENDPOINT_URL", ""),
        "r2_custom_domain": getattr(config, "R2_CUSTOM_DOMAIN", ""),
        "path_template": getattr(config, "PATH_TEMPLATE", "{year}/{month}/{md5}.{ext}"),
        "compressed_output_dir": "",
        "launch_on_startup": False,
        "close_to_tray": False,
    }


def load_settings():
    settings = default_settings()
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                settings.update(json.load(f))
        except (OSError, json.JSONDecodeError):
            pass
    return settings


def save_settings(settings):
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)


def get_pythonw_executable():
    exe = sys.executable
    if exe.lower().endswith("python.exe"):
        pythonw = exe[:-10] + "pythonw.exe"
        if os.path.exists(pythonw):
            return pythonw
    found = shutil.which("pythonw")
    return found or exe


def set_launch_on_startup(enabled):
    if winreg is None:
        return
    command = f'"{get_pythonw_executable()}" "{os.path.abspath(__file__)}"'
    key = winreg.OpenKey(
        winreg.HKEY_CURRENT_USER, AUTOSTART_REG_PATH, 0, winreg.KEY_SET_VALUE
    )
    try:
        if enabled:
            winreg.SetValueEx(key, AUTOSTART_VALUE_NAME, 0, winreg.REG_SZ, command)
        else:
            try:
                winreg.DeleteValue(key, AUTOSTART_VALUE_NAME)
            except FileNotFoundError:
                pass
    finally:
        winreg.CloseKey(key)


def build_upload_path(path_template, filename, file_md5):
    now = datetime.now()
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "mp4"
    stem = filename.rsplit(".", 1)[0] if "." in filename else filename
    return path_template.format(
        year=now.strftime("%Y"),
        month=now.strftime("%m"),
        day=now.strftime("%d"),
        md5=file_md5,
        filename=stem,
        ext=ext,
    )


def validate_r2_settings(settings):
    required_fields = {
        "r2_access_key_id": "Access Key ID",
        "r2_secret_access_key": "Secret Access Key",
        "r2_bucket_name": "Bucket Name",
        "r2_endpoint_url": "Endpoint URL",
        "r2_custom_domain": "自定义域名",
    }
    missing = [
        label
        for key, label in required_fields.items()
        if not settings.get(key, "").strip()
    ]
    if missing:
        return False, "请先在设置中填写: " + "、".join(missing)
    return True, ""


def create_s3_client(settings):
    return boto3.client(
        "s3",
        aws_access_key_id=settings["r2_access_key_id"],
        aws_secret_access_key=settings["r2_secret_access_key"],
        region_name=settings["r2_region"] or "auto",
        endpoint_url=settings["r2_endpoint_url"],
    )


def test_r2_connection(settings):
    client = create_s3_client(settings)
    client.head_bucket(Bucket=settings["r2_bucket_name"])


def get_ffmpeg_exe():
    """获取 ffmpeg 可执行文件路径，支持 PyInstaller 打包"""
    if getattr(sys, "frozen", False):
        # 尝试查找打包目录下的 ffmpeg (可能有版本名，如 ffmpeg-win-x86_64-v7.1.exe)
        for f in os.listdir(sys._MEIPASS):
            if f.startswith("ffmpeg") and f.endswith(".exe"):
                return os.path.join(sys._MEIPASS, f)
    return imageio_ffmpeg.get_ffmpeg_exe()


def get_ffprobe_exe():
    """获取 ffprobe 可执行文件路径，支持 PyInstaller 打包"""
    if getattr(sys, "frozen", False):
        # 尝试查找打包目录下的 ffprobe
        ffprobe_bundled = os.path.join(sys._MEIPASS, "ffprobe.exe")
        if os.path.exists(ffprobe_bundled):
            return ffprobe_bundled

    # 开发环境下，寻找与 imageio_ffmpeg 中 ffmpeg 同目录的 ffprobe
    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    ffprobe_exe = os.path.join(os.path.dirname(ffmpeg_exe), "ffprobe.exe")
    if os.path.exists(ffprobe_exe):
        return ffprobe_exe

    # 最后尝试系统路径
    system_ffprobe = shutil.which("ffprobe")
    if system_ffprobe:
        return system_ffprobe
    return ""


def get_resolution_bucket(height):
    if not height:
        return "fhd"
    if height <= 720:
        return "hd"
    if height <= 1080:
        return "fhd"
    if height <= 1440:
        return "2k"
    return "4k"


def probe_video_info(file_path):
    ffprobe_exe = get_ffprobe_exe()
    if ffprobe_exe:
        cmd = [
            ffprobe_exe,
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            file_path,
        ]
        result = subprocess.run(
            cmd, check=True, capture_output=True, text=True, encoding="utf-8"
        )
        data = json.loads(result.stdout)
        streams = data.get("streams", [])
        format_info = data.get("format", {})
        video_stream = next((s for s in streams if s.get("codec_type") == "video"), {})
        audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), {})

        duration = float(format_info.get("duration") or 0)
        file_size = os.path.getsize(file_path)
        avg_bitrate_bps = (file_size * 8 / duration) if duration > 0 else 0

        return {
            "video_codec": (video_stream.get("codec_name") or "").lower(),
            "width": int(video_stream.get("width") or 0),
            "height": int(video_stream.get("height") or 0),
            "duration": duration,
            "file_size": file_size,
            "avg_bitrate_bps": avg_bitrate_bps,
            "audio_bitrate_bps": int(audio_stream.get("bit_rate") or 0),
        }

    ffmpeg_exe = get_ffmpeg_exe()
    result = subprocess.run(
        [ffmpeg_exe, "-i", file_path],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="ignore",
    )
    output = result.stderr or result.stdout

    duration = 0.0
    duration_match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", output)
    if duration_match:
        hours = int(duration_match.group(1))
        minutes = int(duration_match.group(2))
        seconds = float(duration_match.group(3))
        duration = hours * 3600 + minutes * 60 + seconds

    width = 0
    height = 0
    video_codec = ""
    audio_bitrate_bps = 0

    video_match = re.search(
        r"Video:\s*([a-zA-Z0-9_]+).*?,\s*(\d{2,5})x(\d{2,5})", output
    )
    if video_match:
        video_codec = video_match.group(1).lower()
        width = int(video_match.group(2))
        height = int(video_match.group(3))

    audio_match = re.search(r"Audio:\s*([a-zA-Z0-9_]+).*?(\d+)\s*kb/s", output)
    if audio_match:
        audio_bitrate_bps = int(audio_match.group(2)) * 1000

    file_size = os.path.getsize(file_path)
    avg_bitrate_bps = (file_size * 8 / duration) if duration > 0 else 0

    return {
        "video_codec": video_codec,
        "width": width,
        "height": height,
        "duration": duration,
        "file_size": file_size,
        "avg_bitrate_bps": avg_bitrate_bps,
        "audio_bitrate_bps": audio_bitrate_bps,
    }


def analyze_compression_need(file_path):
    info = probe_video_info(file_path)
    file_size = info["file_size"]
    duration = info["duration"]
    codec = info["video_codec"]
    avg_bitrate_mbps = (
        info["avg_bitrate_bps"] / 1_000_000 if info["avg_bitrate_bps"] else 0
    )
    bitrate_threshold = BITRATE_THRESHOLDS_MBPS[get_resolution_bucket(info["height"])]

    if file_size < MIN_COMPRESS_SIZE_BYTES:
        return (
            False,
            f"文件小于 {format_size(MIN_COMPRESS_SIZE_BYTES)}，直接上传原文件更稳妥",
            info,
        )

    if (
        duration
        and duration < SHORT_VIDEO_SECONDS
        and file_size < SHORT_VIDEO_SKIP_BYTES
    ):
        return False, "短视频且体积不大，跳过压缩避免越压越大", info

    if (
        codec in MODERN_CODECS
        and avg_bitrate_mbps
        and avg_bitrate_mbps <= bitrate_threshold
    ):
        return False, f"{codec.upper()} 码率已较低，继续压缩大概率收益不高", info

    return True, "检测到仍可能有压缩空间，进入压缩流程", info


class CompressWorker(QObject):
    finished = Signal(object)
    error = Signal(str)
    status_update = Signal(str)

    def __init__(self, file_path, settings):
        super().__init__()
        self.file_path = file_path
        self.settings = settings

    def run(self):
        try:
            self.status_update.emit("分析视频中...")
            should_compress, reason, info = analyze_compression_need(self.file_path)
            orig_size = info["file_size"]

            result = {
                "upload_path": self.file_path,
                "used_compressed": False,
                "status_text": "",
                "detail_text": "",
            }

            if not should_compress:
                result["status_text"] = "智能判断后跳过压缩"
                result["detail_text"] = (
                    f"原始大小: {format_size(orig_size)}\n"
                    f"时长: {format_duration(info['duration'])}\n"
                    f"平均码率: {round(info['avg_bitrate_bps'] / 1_000_000, 2)} Mbps\n"
                    f"原因: {reason}"
                )
                self.finished.emit(result)
                return

            self.status_update.emit("压缩中...")
            base_name, ext = os.path.splitext(os.path.basename(self.file_path))
            output_dir = self.settings.get(
                "compressed_output_dir", ""
            ).strip() or os.path.dirname(self.file_path)
            os.makedirs(output_dir, exist_ok=True)
            compressed_path = os.path.join(output_dir, f"{base_name}_compressed{ext}")

            ffmpeg_exe = get_ffmpeg_exe()
            cmd = [
                ffmpeg_exe,
                "-y",
                "-i",
                self.file_path,
                "-vcodec",
                "libx264",
                "-preset",
                "fast",
                "-crf",
                "28",
                "-c:a",
                "aac",
                "-b:a",
                "128k",
                compressed_path,
            ]

            subprocess.run(
                cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )

            comp_size = os.path.getsize(compressed_path)
            saved_ratio = (orig_size - comp_size) / orig_size if orig_size > 0 else 0

            if saved_ratio >= MIN_SAVINGS_RATIO:
                result["upload_path"] = compressed_path
                result["used_compressed"] = True
                result["status_text"] = "压缩完成，建议上传压缩版"
                result["detail_text"] = (
                    f"原始大小: {format_size(orig_size)}\n"
                    f"压缩后: {format_size(comp_size)}\n"
                    f"节省体积: {round(saved_ratio * 100, 1)}%\n"
                    f"保存位置: {compressed_path}"
                )
            else:
                if os.path.exists(compressed_path):
                    os.remove(compressed_path)
                result["status_text"] = "压缩收益不足，改为上传原文件"
                result["detail_text"] = (
                    f"原始大小: {format_size(orig_size)}\n"
                    f"试压大小: {format_size(comp_size)}\n"
                    f"压缩收益不足 {round(MIN_SAVINGS_RATIO * 100)}%，已自动保留原文件"
                )

            self.finished.emit(result)

        except subprocess.CalledProcessError as e:
            self.error.emit(f"视频压缩失败: {e}")
        except Exception as e:
            self.error.emit(str(e))


class UploadWorker(QObject):
    progress = Signal(int)
    finished = Signal(str)
    error = Signal(str)
    status_update = Signal(str)

    def __init__(self, upload_path, original_path, settings):
        super().__init__()
        self.upload_path = upload_path
        self.original_path = original_path
        self.settings = settings

    def run(self):
        try:
            self.status_update.emit("上传中...")
            s3_client = create_s3_client(self.settings)

            md5_hash = hashlib.md5()
            file_size = os.path.getsize(self.upload_path)

            with open(self.upload_path, "rb") as f:
                while chunk := f.read(8192):
                    md5_hash.update(chunk)
            file_md5 = md5_hash.hexdigest()

            filename = os.path.basename(self.original_path)
            object_key = build_upload_path(
                self.settings["path_template"], filename, file_md5
            )

            class ProgressPercentage(object):
                def __init__(self, size, signal):
                    self._size = size
                    self._seen_so_far = 0
                    self._lock = threading.Lock()
                    self._signal = signal

                def __call__(self, bytes_amount):
                    with self._lock:
                        self._seen_so_far += bytes_amount
                        if self._size > 0:
                            percentage = int((self._seen_so_far / self._size) * 100)
                            self._signal.emit(percentage)

            s3_client.upload_file(
                self.upload_path,
                self.settings["r2_bucket_name"],
                object_key,
                Callback=ProgressPercentage(file_size, self.progress),
            )

            custom_url = f"{self.settings['r2_custom_domain'].rstrip('/')}/{object_key}"
            self.finished.emit(custom_url)

        except Exception as e:
            self.error.emit(str(e))


class DropZone(QLabel):
    file_dropped = Signal(str)

    def __init__(self):
        super().__init__()
        self.setObjectName("dropZone")
        self.setWordWrap(True)
        self.setMargin(18)
        self.setText("拖入视频文件\n自动压缩后上传到云端")
        self.setAlignment(Qt.AlignCenter)
        self.setAcceptDrops(True)
        self.setProperty("dragging", False)
        self.refresh_style()

    def refresh_style(self):
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.setProperty("dragging", True)
            self.refresh_style()

    def dragLeaveEvent(self, event):
        self.setProperty("dragging", False)
        self.refresh_style()

    def dropEvent(self, event: QDropEvent):
        self.setProperty("dragging", False)
        self.refresh_style()
        urls = event.mimeData().urls()
        if urls:
            file_path = urls[0].toLocalFile()
            self.file_dropped.emit(file_path)


class SettingsDialog(QDialog):
    settings_saved = Signal(dict)

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.setModal(True)
        self.resize(520, 440)
        self.settings = settings.copy()
        self.setStyleSheet("""
            QDialog {
                background: #f8fbff;
            }
            QLabel {
                color: #0f172a;
            }
            QLineEdit {
                min-height: 38px;
                padding: 0 12px;
                background: #ffffff;
                border: 1px solid #cbd5e1;
                border-radius: 10px;
                selection-background-color: #bfdbfe;
            }
            QLineEdit:focus {
                border: 1px solid #60a5fa;
            }
            QCheckBox {
                spacing: 8px;
                color: #334155;
            }
            QCheckBox::indicator {
                width: 16px;
                height: 16px;
            }
            QCheckBox::indicator:hover {
                width: 16px;
                height: 16px;
            }
            QPushButton {
                min-height: 40px;
                padding: 0 18px;
                border-radius: 10px;
                border: 1px solid #cbd5e1;
                background: #ffffff;
                color: #334155;
                font-weight: 600;
            }
            QPushButton:hover {
                border: 1px solid #93c5fd;
                background: #f8fbff;
                color: #1d4ed8;
            }
            QPushButton:pressed {
                padding-top: 1px;
                background: #eff6ff;
            }
            QPushButton#dialogPrimaryButton {
                background: #2563eb;
                border: 1px solid #2563eb;
                color: #ffffff;
                min-width: 84px;
            }
            QPushButton#dialogPrimaryButton:hover {
                background: #1d4ed8;
                border: 1px solid #1d4ed8;
                color: #ffffff;
            }
            QPushButton#dialogPrimaryButton:pressed {
                background: #1e40af;
                border: 1px solid #1e40af;
            }
            QPushButton#dialogSecondaryButton {
                min-width: 84px;
            }
            QPushButton#dialogGhostButton {
                background: #eef4ff;
                border: 1px solid #c7dbff;
                color: #1e3a8a;
            }
            QPushButton#dialogGhostButton:hover {
                background: #dbeafe;
                border: 1px solid #93c5fd;
                color: #1d4ed8;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(14)

        title = QLabel("Cloudflare R2 与应用设置")
        title.setStyleSheet("font-size: 18px; font-weight: 700; color: #0f172a;")
        layout.addWidget(title)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(10)

        self.access_key_input = QLineEdit(self.settings["r2_access_key_id"])
        self.secret_key_input = QLineEdit(self.settings["r2_secret_access_key"])
        self.secret_key_input.setEchoMode(QLineEdit.Password)
        self.bucket_input = QLineEdit(self.settings["r2_bucket_name"])
        self.endpoint_input = QLineEdit(self.settings["r2_endpoint_url"])
        self.domain_input = QLineEdit(self.settings["r2_custom_domain"])
        self.path_template_input = QLineEdit(self.settings["path_template"])

        output_wrap = QWidget()
        output_layout = QHBoxLayout(output_wrap)
        output_layout.setContentsMargins(0, 0, 0, 0)
        output_layout.setSpacing(8)
        self.output_dir_input = QLineEdit(self.settings["compressed_output_dir"])
        self.output_dir_input.setPlaceholderText("为空时保存到原视频所在文件夹")
        browse_button = QPushButton("浏览")
        browse_button.setObjectName("dialogGhostButton")
        browse_button.clicked.connect(self.choose_output_dir)
        output_layout.addWidget(self.output_dir_input, 1)
        output_layout.addWidget(browse_button)

        self.autostart_checkbox = QCheckBox("开机自启")
        self.autostart_checkbox.setChecked(self.settings["launch_on_startup"])
        self.tray_checkbox = QCheckBox("关闭到系统托盘")
        self.tray_checkbox.setChecked(self.settings["close_to_tray"])

        checkbox_wrap = QWidget()
        checkbox_wrap.setFixedSize(320, 38)
        checkbox_layout = QHBoxLayout(checkbox_wrap)
        checkbox_layout.setContentsMargins(0, 0, 0, 0)
        checkbox_layout.setSpacing(24)
        checkbox_layout.addWidget(self.autostart_checkbox)
        checkbox_layout.addWidget(self.tray_checkbox)
        checkbox_layout.addStretch(1)

        form.addRow(self.create_form_label("Access Key ID"), self.access_key_input)
        form.addRow(self.create_form_label("Secret Access Key"), self.secret_key_input)
        form.addRow(self.create_form_label("Bucket Name"), self.bucket_input)
        form.addRow(self.create_form_label("Endpoint URL"), self.endpoint_input)
        form.addRow(self.create_form_label("Custom Domain"), self.domain_input)
        form.addRow(self.create_form_label("路径模板"), self.path_template_input)
        form.addRow(self.create_form_label("压缩保存路径"), output_wrap)
        form.addRow(self.create_form_label("应用选项"), checkbox_wrap)
        layout.addLayout(form)

        help_label = QLabel("路径模板支持: {year} {month} {day} {md5} {filename} {ext}")
        help_label.setStyleSheet("color: #64748b; font-size: 12px;")
        layout.addWidget(help_label)

        test_button = QPushButton("检查通信")
        test_button.setObjectName("dialogGhostButton")
        test_button.clicked.connect(self.handle_test_connection)
        import_button = QPushButton("导入配置")
        import_button.setObjectName("dialogGhostButton")
        import_button.clicked.connect(self.handle_import)
        export_button = QPushButton("导出配置")
        export_button.setObjectName("dialogGhostButton")
        export_button.clicked.connect(self.handle_export)
        save_button = QPushButton("保存设置")
        save_button.setObjectName("dialogPrimaryButton")
        save_button.clicked.connect(self.handle_save)
        cancel_button = QPushButton("取消")
        cancel_button.setObjectName("dialogSecondaryButton")
        cancel_button.clicked.connect(self.reject)

        # Divider line
        divider = QWidget()
        divider.setFixedHeight(1)
        divider.setStyleSheet("background: #e2e8f0;")
        layout.addWidget(divider)

        # Top row: 检查通信、导入配置、导出配置 (居中)
        top_button_row = QHBoxLayout()
        top_button_row.setSpacing(10)
        top_button_row.addStretch(1)
        top_button_row.addWidget(test_button)
        top_button_row.addWidget(import_button)
        top_button_row.addWidget(export_button)
        top_button_row.addStretch(1)
        layout.addLayout(top_button_row)

        # Bottom row: 取消、保存设置 (居中)
        bottom_button_row = QHBoxLayout()
        bottom_button_row.setSpacing(10)
        bottom_button_row.addStretch(1)
        bottom_button_row.addWidget(cancel_button)
        bottom_button_row.addWidget(save_button)
        bottom_button_row.addStretch(1)
        layout.addLayout(bottom_button_row)

        # Version label display
        version_label = QLabel(f"v{APP_VERSION}")
        version_label.setStyleSheet("color: #94a3b8; font-size: 11px; margin-top: 5px;")
        version_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(version_label)

    def create_form_label(self, text):
        label = QLabel(text)
        label.setFixedHeight(38)
        label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        return label

    def show_message(self, icon, title, text):
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.setModal(True)
        dialog.setFixedWidth(420)
        dialog.setStyleSheet("""
            QDialog {
                background: #ffffff;
            }
            QLabel#messageTitle {
                color: #0f172a;
                font-size: 18px;
                font-weight: 700;
            }
            QLabel#messageText {
                color: #334155;
                font-size: 14px;
                line-height: 1.5;
            }
            QPushButton#messageOkButton {
                min-width: 76px;
                min-height: 34px;
                padding: 0 12px;
                border-radius: 10px;
                border: 1px solid #cbd5e1;
                background: #ffffff;
                color: #0f172a;
                font-weight: 600;
            }
            QPushButton#messageOkButton:hover {
                border: 1px solid #93c5fd;
                background: #f8fbff;
                color: #1d4ed8;
            }
            QPushButton#messageOkButton:pressed {
                background: #eff6ff;
                padding-top: 1px;
            }
        """)

        main_layout = QVBoxLayout(dialog)
        main_layout.setContentsMargins(22, 20, 22, 18)
        main_layout.setSpacing(18)

        content_layout = QHBoxLayout()
        content_layout.setSpacing(14)

        icon_label = QLabel()
        icon_label.setFixedSize(36, 36)
        icon_map = {
            QMessageBox.Information: QStyle.SP_MessageBoxInformation,
            QMessageBox.Warning: QStyle.SP_MessageBoxWarning,
            QMessageBox.Critical: QStyle.SP_MessageBoxCritical,
        }
        standard_icon = self.style().standardIcon(
            icon_map.get(icon, QStyle.SP_MessageBoxInformation)
        )
        icon_label.setPixmap(standard_icon.pixmap(32, 32))
        icon_label.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
        content_layout.addWidget(icon_label, 0, Qt.AlignTop)

        text_layout = QVBoxLayout()
        text_layout.setSpacing(6)

        title_label = QLabel(title)
        title_label.setObjectName("messageTitle")
        text_layout.addWidget(title_label)

        text_label = QLabel(text)
        text_label.setObjectName("messageText")
        text_label.setWordWrap(True)
        text_layout.addWidget(text_label)

        content_layout.addLayout(text_layout, 1)
        main_layout.addLayout(content_layout)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        ok_button = QPushButton("知道了")
        ok_button.setObjectName("messageOkButton")
        ok_button.clicked.connect(dialog.accept)
        button_row.addWidget(ok_button)
        main_layout.addLayout(button_row)

        dialog.exec()

    def show_success_toast(self, text, duration_ms=2200):
        toast = QDialog(self, Qt.FramelessWindowHint | Qt.Tool)
        toast.setAttribute(Qt.WA_ShowWithoutActivating, True)
        toast.setAttribute(Qt.WA_TranslucentBackground, True)
        toast.setModal(False)
        toast.setStyleSheet("""
            QDialog {
                background: rgba(0, 0, 0, 0);
            }
            QWidget#toastCard {
                background: rgba(31, 41, 55, 0.96);
                border-radius: 14px;
            }
            QLabel#toastIcon {
                color: #84cc16;
                font-size: 18px;
                font-weight: 700;
            }
            QLabel#toastText {
                color: #ffffff;
                font-size: 14px;
                font-weight: 600;
            }
        """)

        layout = QVBoxLayout(toast)
        layout.setContentsMargins(0, 0, 0, 0)

        card = QWidget()
        card.setObjectName("toastCard")
        card_layout = QHBoxLayout(card)
        card_layout.setContentsMargins(14, 10, 14, 10)
        card_layout.setSpacing(10)

        icon_label = QLabel("✓")
        icon_label.setObjectName("toastIcon")
        icon_label.setAlignment(Qt.AlignCenter)
        card_layout.addWidget(icon_label, 0, Qt.AlignVCenter)

        text_label = QLabel(text)
        text_label.setObjectName("toastText")
        text_label.setAlignment(Qt.AlignVCenter)
        card_layout.addWidget(text_label, 0, Qt.AlignVCenter)

        layout.addWidget(card)
        toast.adjustSize()

        if self.isVisible():
            parent_rect = self.frameGeometry()
            x = parent_rect.left() + (parent_rect.width() - toast.width()) // 2
            y = parent_rect.top() + (parent_rect.height() - toast.height()) // 2
            toast.move(x, y)

        toast.show()
        QTimer.singleShot(duration_ms, toast.close)

    def collect_settings(self):
        return {
            "r2_access_key_id": self.access_key_input.text().strip(),
            "r2_secret_access_key": self.secret_key_input.text().strip(),
            "r2_bucket_name": self.bucket_input.text().strip(),
            "r2_region": "auto",
            "r2_endpoint_url": self.endpoint_input.text().strip(),
            "r2_custom_domain": self.domain_input.text().strip(),
            "path_template": self.path_template_input.text().strip()
            or "{year}/{month}/{md5}.{ext}",
            "compressed_output_dir": self.output_dir_input.text().strip(),
            "launch_on_startup": self.autostart_checkbox.isChecked(),
            "close_to_tray": self.tray_checkbox.isChecked(),
        }

    def choose_output_dir(self):
        directory = QFileDialog.getExistingDirectory(self, "选择压缩文件保存路径")
        if directory:
            self.output_dir_input.setText(directory)

    def handle_test_connection(self):
        settings = self.collect_settings()
        ok, message = validate_r2_settings(settings)
        if not ok:
            self.show_message(QMessageBox.Warning, "配置不完整", message)
            return
        try:
            test_r2_connection(settings)
        except Exception as e:
            self.show_message(
                QMessageBox.Critical, "通信失败", f"R2 通信检查失败:\n{e}"
            )
            return
        self.show_success_toast("连接成功！")

    def handle_save(self):
        settings = self.collect_settings()
        save_settings(settings)
        set_launch_on_startup(settings["launch_on_startup"])
        self.settings_saved.emit(settings)
        self.accept()

    def handle_export(self):
        """Export current settings to a JSON file chosen by the user."""
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "导出配置",
            "settings_export.json",
            "JSON Files (*.json);;All Files (*)",
        )
        if file_path:
            try:
                with open(file_path, "w", encoding="utf-8") as f:
                    json.dump(self.collect_settings(), f, ensure_ascii=False, indent=2)
                self.show_success_toast("配置已导出")
            except Exception as e:
                self.show_message(QMessageBox.Critical, "导出失败", str(e))

    def handle_import(self):
        """Import settings from a JSON file and apply them to the UI."""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "导入配置", "", "JSON Files (*.json);;All Files (*)"
        )
        if file_path:
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    imported = json.load(f)
                # Update UI fields
                self.access_key_input.setText(imported.get("r2_access_key_id", ""))
                self.secret_key_input.setText(imported.get("r2_secret_access_key", ""))
                self.bucket_input.setText(imported.get("r2_bucket_name", ""))
                self.endpoint_input.setText(imported.get("r2_endpoint_url", ""))
                self.domain_input.setText(imported.get("r2_custom_domain", ""))
                self.path_template_input.setText(imported.get("path_template", ""))
                self.output_dir_input.setText(imported.get("compressed_output_dir", ""))
                self.autostart_checkbox.setChecked(
                    imported.get("launch_on_startup", False)
                )
                self.tray_checkbox.setChecked(imported.get("close_to_tray", False))
                # Save imported settings to file
                save_settings(imported)
                # Emit signal to update main window settings
                self.settings_saved.emit(imported)
                self.show_success_toast("配置已导入")
            except Exception as e:
                self.show_message(QMessageBox.Critical, "导入失败", str(e))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = load_settings()
        self.logo_path = os.path.join(
            os.path.dirname(__file__), "assets", "icons", "logo.png"
        )
        # allow_close 仅在从托盘退出时设置为 True，平时点击关闭按钮应遵循设置
        self.allow_close = False
        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION}")
        self.resize(520, 620)
        self.setMinimumSize(460, 560)
        self.setWindowFlags(Qt.WindowStaysOnTopHint)
        if os.path.exists(self.logo_path):
            self.setWindowIcon(QIcon(self.logo_path))
        self.setStyleSheet("""
            QMainWindow {
                background: #f4f7fb;
            }
            QWidget {
                color: #1f2937;
                font-family: "Microsoft YaHei UI", "PingFang SC", sans-serif;
            }
            QWidget#navBar {
                background: #ffffff;
                border: 1px solid #e2e8f0;
                border-radius: 18px;
            }
            QLabel#logoLabel {
                background: #0f172a;
                border-radius: 14px;
                padding: 6px;
            }
            QLabel#titleLabel {
                font-size: 24px;
                font-weight: 700;
                color: #0f172a;
            }
            QLabel#subtitleLabel {
                color: #64748b;
                font-size: 13px;
            }
            QToolButton#settingsButton {
                background: transparent;
                border: none;
                padding: 6px;
                min-width: 46px;
                min-height: 46px;
                font-size: 18px;
                color: #475569;
            }
            QToolButton#settingsButton:hover {
                background: transparent;
                border: none;
                font-size: 20px;
                color: #1d4ed8;
            }
            QToolButton#settingsButton:pressed {
                background: transparent;
                border: none;
                padding-top: 7px;
                padding-left: 7px;
                color: #1e40af;
            }
            QLabel#dropZone {
                border: 2px dashed #cbd5e1;
                border-radius: 20px;
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #ffffff, stop:1 #f8fbff);
                font-size: 20px;
                font-weight: 600;
                color: #334155;
                line-height: 1.5;
            }
            QLabel#dropZone[dragging="true"] {
                border: 2px dashed #2563eb;
                background: #eff6ff;
                color: #1d4ed8;
            }
            QLabel#statusLabel {
                background: #e2e8f0;
                color: #334155;
                border-radius: 10px;
                padding: 10px 12px;
                font-size: 12px;
                font-weight: 600;
            }
            QLabel#statusLabel[state="success"] {
                background: #dcfce7;
                color: #15803d;
            }
            QLabel#statusLabel[state="error"] {
                background: #fee2e2;
                color: #b91c1c;
            }
            QLabel#metaLabel {
                color: #475569;
                font-size: 12px;
                line-height: 1.65;
            }
            QLabel#footerLabel {
                color: #94a3b8;
                font-size: 12px;
            }
            QProgressBar {
                border: none;
                border-radius: 8px;
                text-align: center;
                height: 14px;
                background: #e2e8f0;
                color: #0f172a;
                font-weight: 600;
            }
            QProgressBar::chunk {
                border-radius: 8px;
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #38bdf8, stop:1 #2563eb);
            }
            QPushButton {
                border: none;
                border-radius: 12px;
                padding: 11px 18px;
                font-size: 14px;
                font-weight: 700;
            }
            QPushButton#primaryButton {
                background: #2563eb;
                color: white;
            }
            QPushButton#primaryButton:hover {
                background: #1d4ed8;
            }
            QPushButton#secondaryButton {
                background: #e2e8f0;
                color: #334155;
            }
            QPushButton#secondaryButton:hover {
                background: #cbd5e1;
            }
        """)

        self.setup_tray()

        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        layout = QVBoxLayout(main_widget)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(16)

        nav_bar = QWidget()
        nav_bar.setObjectName("navBar")
        nav_layout = QHBoxLayout(nav_bar)
        nav_layout.setContentsMargins(16, 12, 12, 16)
        nav_layout.setSpacing(14)
        nav_layout.setAlignment(Qt.AlignTop)

        logo_label = QLabel()
        logo_label.setObjectName("logoLabel")
        logo_label.setFixedSize(56, 56)
        logo_label.setAlignment(Qt.AlignCenter)
        if os.path.exists(self.logo_path):
            pixmap = QPixmap(self.logo_path)
            if not pixmap.isNull():
                logo_label.setPixmap(
                    pixmap.scaled(42, 42, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                )
        nav_layout.addWidget(logo_label, 0, Qt.AlignTop)

        title_wrap = QWidget()
        title_wrap_layout = QVBoxLayout(title_wrap)
        title_wrap_layout.setContentsMargins(0, 0, 0, 0)
        title_wrap_layout.setSpacing(4)
        title_wrap_layout.setAlignment(Qt.AlignTop)

        title_label = QLabel("Vid2R2")
        title_label.setObjectName("titleLabel")
        title_wrap_layout.addWidget(title_label)

        subtitle_label = QLabel(
            "拖入视频后自动压缩上传到 Cloudflare R2，成功后复制可用视频标签。"
        )
        subtitle_label.setObjectName("subtitleLabel")
        subtitle_label.setWordWrap(True)
        title_wrap_layout.addWidget(subtitle_label)

        nav_layout.addWidget(title_wrap, 1, Qt.AlignTop)

        layout.addWidget(nav_bar)

        self.drop_zone = DropZone()
        self.drop_zone.file_dropped.connect(self.start_compression)
        self.drop_zone.setMinimumHeight(150)
        layout.addWidget(self.drop_zone)

        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.hide()
        layout.addWidget(self.progress_bar)

        self.status_label = QLabel("等待拖入视频")
        self.status_label.setObjectName("statusLabel")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setProperty("state", "idle")
        layout.addWidget(self.status_label)

        self.info_label = QLabel("支持 mp4 / mov / mkv / webm 等常见格式")
        self.info_label.setObjectName("metaLabel")
        self.info_label.setAlignment(Qt.AlignCenter)
        self.info_label.setWordWrap(True)
        self.info_label.setContentsMargins(8, 6, 8, 10)
        layout.addWidget(self.info_label)

        # Action Buttons (Hidden by default)
        self.btn_layout = QHBoxLayout()
        self.btn_layout.setSpacing(12)

        self.btn_upload = QPushButton("确认上传")
        self.btn_upload.setObjectName("primaryButton")
        self.btn_upload.clicked.connect(self.start_upload)

        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.setObjectName("secondaryButton")
        self.btn_cancel.clicked.connect(self.cancel_upload)

        self.btn_layout.addWidget(self.btn_upload)
        self.btn_layout.addWidget(self.btn_cancel)

        # Wrap buttons in a widget to easily hide/show
        self.action_widget = QWidget()
        self.action_widget.setLayout(self.btn_layout)
        self.action_widget.hide()
        layout.addWidget(self.action_widget)

        layout.addStretch(1)

        footer_spacer = QWidget()
        footer_spacer.setFixedSize(46, 46)

        footer_label = QLabel("Vid2R2@Surfsun")
        footer_label.setObjectName("footerLabel")
        footer_label.setAlignment(Qt.AlignCenter)

        settings_button = QToolButton()
        settings_button.setObjectName("settingsButton")
        settings_button.setText("⚙")
        settings_button.setToolTip("设置")
        settings_button.setCursor(Qt.PointingHandCursor)
        settings_button.clicked.connect(self.open_settings_dialog)

        footer_row = QHBoxLayout()
        footer_row.setContentsMargins(0, 0, 0, 0)
        footer_row.setSpacing(8)
        footer_row.setAlignment(Qt.AlignVCenter)
        footer_row.addWidget(footer_spacer, 0, Qt.AlignVCenter | Qt.AlignLeft)
        footer_row.addWidget(footer_label, 1, Qt.AlignVCenter | Qt.AlignHCenter)
        footer_row.addWidget(settings_button, 0, Qt.AlignVCenter | Qt.AlignRight)
        layout.addLayout(footer_row)

        self.current_original_path = ""
        self.current_upload_path = ""
        self.current_upload_source = "原文件"

    def setup_tray(self):
        self.tray_icon = QSystemTrayIcon(self)
        if os.path.exists(self.logo_path):
            self.tray_icon.setIcon(QIcon(self.logo_path))
        else:
            self.tray_icon.setIcon(self.style().standardIcon(QStyle.SP_ComputerIcon))
        self.tray_icon.setToolTip(APP_NAME)
        self.tray_icon.activated.connect(self.handle_tray_activated)

        tray_menu = QMenu(self)
        show_action = QAction("显示主窗口", self)
        show_action.triggered.connect(self.restore_from_tray)
        exit_action = QAction("退出", self)
        exit_action.triggered.connect(self.exit_app)
        tray_menu.addAction(show_action)
        tray_menu.addSeparator()
        tray_menu.addAction(exit_action)
        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.show()

    def open_settings_dialog(self):
        """Open the SettingsDialog and handle updated settings."""
        dialog = SettingsDialog(self.settings, self)
        dialog.settings_saved.connect(self.apply_new_settings)
        dialog.exec()

    def apply_new_settings(self, new_settings):
        """Update the main window with settings returned from the dialog."""
        self.settings = new_settings
        # Update tray auto‑start flag
        set_launch_on_startup(self.settings.get("launch_on_startup", False))
        # 刷新托盘图标等
        if os.path.exists(self.logo_path):
            self.tray_icon.setIcon(QIcon(self.logo_path))

    def set_status(self, text, state="idle"):
        self.status_label.setText(text)
        self.status_label.setProperty("state", state)
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)
        self.status_label.update()

    def start_compression(self, file_path):
        ext = file_path.rsplit(".", 1)[-1].lower() if "." in file_path else ""
        if ext not in config.ALLOWED_EXTENSIONS:
            self.set_status("文件格式不支持", "error")
            self.info_label.setText(f"暂不支持 .{ext} 格式，请拖入常见视频文件。")
            return

        self.current_original_path = file_path
        self.current_upload_path = file_path
        self.current_upload_source = "原文件"
        file_name = os.path.basename(file_path)
        file_size = format_size(os.path.getsize(file_path))

        self.drop_zone.setText(f"正在分析\n{file_name}")
        self.drop_zone.setDisabled(True)
        self.progress_bar.show()
        self.progress_bar.setRange(0, 0)
        self.set_status("正在分析是否值得压缩", "idle")
        self.info_label.setText(f"文件名: {file_name}\n原始大小: {file_size}")
        self.action_widget.hide()

        self.thread = QThread()
        self.worker = CompressWorker(file_path, self.settings.copy())
        self.worker.moveToThread(self.thread)

        self.thread.started.connect(self.worker.run)
        self.worker.status_update.connect(self.update_status)
        self.worker.finished.connect(self.compression_finished)
        self.worker.error.connect(self.upload_error)

        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)
        self.worker.error.connect(self.thread.quit)
        self.worker.error.connect(self.worker.deleteLater)

        self.thread.start()

    def compression_finished(self, result):
        self.current_upload_path = result["upload_path"]
        self.current_upload_source = "压缩版" if result["used_compressed"] else "原文件"
        self.progress_bar.hide()
        self.set_status(result["status_text"], "success")
        self.info_label.setText(result["detail_text"])
        if result["used_compressed"]:
            self.drop_zone.setText("压缩完成\n确认后上传压缩版")
        else:
            self.drop_zone.setText("无需继续压缩\n确认后上传原文件")
        self.action_widget.show()

    def start_upload(self):
        ok, message = validate_r2_settings(self.settings)
        if not ok:
            self.set_status("请先完善设置", "error")
            self.info_label.setText(message)
            self.open_settings_dialog()
            return

        self.action_widget.hide()
        self.drop_zone.setText("正在上传\n请勿关闭窗口")
        self.progress_bar.show()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.set_status("正在上传到云端", "idle")
        self.info_label.setText(f"正在上传{self.current_upload_source}...")

        self.thread = QThread()
        self.worker = UploadWorker(
            self.current_upload_path, self.current_original_path, self.settings.copy()
        )
        self.worker.moveToThread(self.thread)

        self.thread.started.connect(self.worker.run)
        self.worker.status_update.connect(self.update_status)
        self.worker.progress.connect(self.update_progress)
        self.worker.finished.connect(self.upload_finished)
        self.worker.error.connect(self.upload_error)

        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)
        self.worker.error.connect(self.thread.quit)
        self.worker.error.connect(self.worker.deleteLater)

        self.thread.start()

    def cancel_upload(self):
        self.action_widget.hide()
        self.drop_zone.setDisabled(False)
        self.drop_zone.setText("拖入视频文件\n自动压缩后上传到云端")
        self.set_status("已取消本次上传", "idle")
        self.info_label.setText("压缩文件已保留在设定目录或原视频所在文件夹。")

    def update_status(self, val):
        self.set_status(val, "idle")

    def update_progress(self, val):
        self.progress_bar.setValue(val)
        self.info_label.setText(f"上传进度: {val}%")

    def upload_finished(self, url):
        video_html = f'<video src="{url}" controls width="100%"></video>'
        clipboard = QApplication.clipboard()
        clipboard.setText(video_html)

        self.progress_bar.hide()
        self.progress_bar.setRange(0, 100)
        self.drop_zone.setDisabled(False)
        self.drop_zone.setText("上传成功\n可以继续拖入其它视频")
        self.set_status("上传完成，视频标签已复制", "success")
        self.info_label.setText(f"已复制到剪贴板:\n{url}")

    def upload_error(self, err_msg):
        self.progress_bar.hide()
        self.progress_bar.setRange(0, 100)
        self.drop_zone.setDisabled(False)
        self.drop_zone.setText("操作失败\n拖入视频重新尝试")
        self.set_status("处理失败", "error")
        self.info_label.setText(f"错误信息: {err_msg}")
        self.action_widget.hide()

    def handle_tray_activated(self, reason):
        if reason == QSystemTrayIcon.Trigger:
            self.restore_from_tray()

    def restore_from_tray(self):
        self.show()
        self.raise_()
        self.activateWindow()

    def exit_app(self):
        self.allow_close = True
        self.tray_icon.hide()
        self.close()

    def closeEvent(self, event: QCloseEvent):
        if self.allow_close:
            event.accept()
            return

        if self.settings.get("close_to_tray") and self.tray_icon.isVisible():
            self.hide()
            event.ignore()
            return

        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
