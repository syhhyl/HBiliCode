# HBiliCode

这是一个纯 Python 单脚本，只用来打印你的 B 站直播推流码。

它会做的事：

- 如果本地没有登录态，就打印二维码并等待扫码登录
- 调用开播接口
- 打印 RTMP / SRT 推流信息

它不会做的事：

- GUI
- 托盘
- 弹幕
- 分区选择
- 日志系统
- 多余参数

脚本固定使用默认分区 `235`。

## 安装

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 用法

直接运行：

```bash
python3 mac_stream_cli.py
```

## session 文件

脚本会把登录态保存到：

- `~/Library/Application Support/HBiliCode/session.json`

也可以通过环境变量 `HBILICODE_CONFIG_HOME` 改掉目录。

## 重要说明

- 这个脚本通过开播接口拿推流码，所以运行时会真正尝试开播
- 如果 B 站返回 `60024`，脚本会把人脸认证二维码打印到终端
- 如果终端只显示登录链接而没有二维码，请安装 `qrcode`：`pip install -r requirements.txt`
