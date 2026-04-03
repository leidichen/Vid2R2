# Vid2R2 - 视频上传 Cloudflare R2 工具

[![Python Version](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/)
[![Framework](https://img.shields.io/badge/framework-PySide6-green.svg)](https://doc.qt.io/qtforpython/)

Vid2R2 是一个基于 PySide6 开发的轻量级视频压缩与上传工具，专为使用 Cloudflare R2 存储的用户设计。它集成了本地视频压缩与云端存储功能，极大地简化了视频分发流程。

## 🌟 主要功能

- **本地压缩**：使用 FFmpeg 技术，在上传前自动压缩视频，减少存储成本。
- **Cloudflare R2 集成**：支持一键上传到 R2 存储桶。
- **Obsidian 友好输出**：上传完成后自动返回标准的 `<video>` 标签链接，支持在 Obsidian、Notion 或任何前端网页中直接渲染播放。
- **自定义路径**：支持使用 `{year}`, `{month}`, `{md5}`, `{filename}` 等占位符自定义云端保存路径。
- **配置管理**：支持设置的导入与导出（JSON 文件），方便多机同步。
- **后台运行**：支持开机自启、最小化到系统托盘，不干扰日常工作。
- **现代 UI**：基于原生的丰富美学设计，提供流畅的用户体验。

## ⚙️ 配置说明 (Cloudflare R2)

为了使用本工具，您需要在“设置”中配置以下 Cloudflare R2 参数：

### 如何获取 Key？

1. 登录 [Cloudflare 控制台](https://dash.cloudflare.com/)。
2. 在左侧菜单点击 **R2**。
3. 点击右侧的 **Manage R2 API Tokens**。
4. 创建一个具有 **Edit** 权限的 Token。
5. 您将获得以下信息：
   - **Access Key ID**: 即 R2 的访问密钥 ID。
   - **Secret Access Key**: 即 R2 的私有访问密钥。
   - **Endpoint URL**: 在 R2 概览页面可以看到，格式通常为 `https://<account-id>.r2.cloudflarestorage.com`。

### 其他参数
- **Bucket Name**: 您在 R2 中创建的存储桶名称。
- **Custom Domain**: 如果您为存储桶绑定了自定义域名（如 `https://img.example.com`），请填入，以便程序生成完整的访问链接。

## 🚀 快速开始

### 源码运行

1. 克隆项目
2. 安装依赖：
   ```bash
   pip install -r requirements.txt
   ```
3. 运行程序：
   ```bash
   python minimal_uploader.py
   ```

### 打包为 EXE

项目已配置好 PyInstaller 环境，直接运行以下命令：
```bash
pyinstaller Vid2R2.spec --clean --noconfirm
```

## 🛠️ 技术栈

- **Python** (Core)
- **PySide6** (UI Framework)
- **Boto3** (R2/S3 Communication)
- **MoviePy/FFmpeg** (Video Processing)

## 📄 开源协议

MIT License
