# 词间 · IELTS 词汇共学 v1.0

基于 Flask 和 SQLite 的本地双人词汇学习平台。支持分批背诵、中英互译、单词拼写、错题重练、每日复习统计和同一词池的双人对战。

## 运行

需要 Python 3.10 或以上。

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python app.py
```

打开 [本地学习平台](http://127.0.0.1:5000)，选择「学员 A」或「学员 B」。这是供可信设备使用的本地应用。两个账号的学习进度分别保存在新建的 SQLite 数据库中。

- 选择题默认聚焦第一项，支持数字 1–4、上下键和 Enter。
- 每日复习优先选尚未复习的已学词。某个词通过三轮后当日计一次。
- 内置四组共 24 个公开样例词。自定义词库可通过 `IELTS_VOCABULARY_FILE` 指向与 `data/sample_words.json` 同格式的 JSON。

## macOS 悬浮入口

创建并安装好上述虚拟环境后，运行 `./scripts/build_desktop.sh`，双击同目录生成的「词间悬浮学习.app」。悬浮版使用单独端口 52732。

## 测试

```sh
python -m unittest discover -s tests
```
