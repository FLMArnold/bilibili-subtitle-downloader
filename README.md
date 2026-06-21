# Bilibili Subtitle Downloader

B站视频中文字幕下载工具。支持 AI 自动生成字幕和人工字幕，多 P 分集，批量下载。

## 用法

```bash
# 视频 ID 支持 BV 号、AV 号、完整 URL
python bilibili_subtitle.py BV1Lt421w7UY

# 批量处理
python bilibili_subtitle.py BV1xx BV2xx BV3xx

# 指定分 P
python bilibili_subtitle.py BV1xx -p 2

# 指定输出目录
python bilibili_subtitle.py BV1xx -o ./subtitles

# 提供 Cookie（用于获取需登录的 AI 字幕）
python bilibili_subtitle.py BV1xx --cookie "SESSDATA=xxx; buvid3=xxx"

# 调整字幕一致性校验参数
python bilibili_subtitle.py BV1xx --retry 3 --retry-interval 2
```

Cookie 首次输入后会自动保存到脚本所在目录的 `.bilibili_cookie` 文件，后续无需重复传入。

## 输出

每个视频生成两个文件：

- `视频标题.txt` — 纯文本
- `视频标题-带时间戳.txt` — 每行带 `[开始 --> 结束]` 时间戳

## 功能

- BV 号、AV 号、完整 URL 识别
- AI 自动字幕 + 人工字幕
- 需要登录态的字幕自动降级（403 → WBI 签名）
- 字幕一致性校验：多次请求比对首段文字，防止 CDN 返回过期缓存
- Cookie 本地持久化 + 有效性自动验证
- HTTP 429 限流自动等待

## 依赖

- Python 3.8+
- `requests`

```bash
pip install requests
```

## 免责声明

本工具仅供学习研究使用。下载的字幕仅限个人学习，请遵守 B站 用户协议。
