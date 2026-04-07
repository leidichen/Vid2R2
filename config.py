"""
Cloudflare R2 视频上传配置文件
"""
import os
from datetime import datetime

# ============ Cloudflare R2 配置 ============
R2_ACCESS_KEY_ID = os.getenv("R2_ACCESS_KEY_ID", "")
R2_SECRET_ACCESS_KEY = os.getenv("R2_SECRET_ACCESS_KEY", "")
R2_BUCKET_NAME = os.getenv("R2_BUCKET_NAME", "")
R2_REGION = os.getenv("R2_REGION", "auto")
R2_ENDPOINT_URL = os.getenv("R2_ENDPOINT_URL", "")
R2_CUSTOM_DOMAIN = os.getenv("R2_CUSTOM_DOMAIN", "")

# ============ 上传配置 ============
MAX_FILE_SIZE = 500 * 1024 * 1024  # 500MB
ALLOWED_EXTENSIONS = {'mp4', 'webm', 'mov', 'avi', 'mkv', 'flv', 'wmv', 'ogv'}
PRESIGNED_URL_EXPIRATION = 3600  # 1 小时

# ============ Flask 配置 ============
FLASK_ENV = os.getenv("FLASK_ENV", "production")
DEBUG = os.getenv("DEBUG", "False").lower() == "true"
SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-change-in-production")

# ============ 服务器配置 ============
HOST = "0.0.0.0"
PORT = 5000

# ============ 路径模板 ============
# 支持的变量: {year}, {month}, {day}, {md5}, {filename}, {ext}
PATH_TEMPLATE = os.getenv("PATH_TEMPLATE", "{year}/{month}/{md5}.{ext}")

def get_upload_path(filename: str, file_md5: str) -> str:
    """
    根据模板生成上传路径
    
    Args:
        filename: 原始文件名
        file_md5: 文件 MD5 哈希值
    
    Returns:
        生成的上传路径
    """
    now = datetime.now()
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else 'mp4'
    
    path = PATH_TEMPLATE.format(
        year=now.strftime("%Y"),
        month=now.strftime("%m"),
        day=now.strftime("%d"),
        md5=file_md5,
        filename=filename.rsplit('.', 1)[0],
        ext=ext
    )
    
    return path
