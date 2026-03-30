# mac.md

当前实现已经收敛成一个单脚本方案：`mac_stream_cli.py`。

只保留这条链路：

1. 读取本地 `session.json`
2. 如果没有登录态，或者登录态失效，就二维码扫码登录
3. 获取 `csrf` 和 `room_id`
4. 调用 `startLive`
5. 打印 RTMP / SRT 推流码

明确删除的内容：

- GUI
- pywebview
- Qt
- 分区管理
- 账号管理面板
- 弹幕
- 日志文件
- `login-only` / `relogin` 之类的辅助选项

默认分区固定为 `235`。
