# 词间 · IELTS 词汇共学 v1.0

词间是一个运行在本机的双人词汇学习工具。两位学员各自背词、复习和查看进度，也可以用两人共同学过的词发起同卷对战。公开版包含四组共 24 个样例词，默认使用匿名的「学员 A」和「学员 B」。

## 快速开始

需要 Python 3.10 或以上。在仓库目录运行：

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python app.py
```

打开 [词间本地页面](http://127.0.0.1:5000)，选择一个学员。在「单词背诵」选一个主题页，完成一批后就可以进入「每日复习」。账户通过页面直接选择，适合在可信设备上使用。

## 一次学习如何走完整个流程

```mermaid
flowchart LR
    A["样例或自备词库"] --> B["library.py 导入"]
    B --> C["SQLite pages 和 words"]
    C --> D["study.py 分批背诵"]
    D --> E["word_progress 和 progress"]
    E --> F["review.py 个人复习"]
    E --> G["app.py 双人共同词池"]
    F --> H["复习记录和统计"]
    G --> I["同一试卷、答卷、积分"]
```

### 1. 背诵按批进行，词和页分别记进度

选中词库页并填写词数后，[app.py](app.py) 的 `learn_page()` 调用 [study.py](study.py) 的 `begin_session()`。新批次优先取本页尚未完成的词；返回已有会话时会继续原来的进度。

一批依次经过**整体记忆 → 中译英 → 英译中 → 英文拼写**。整体记忆页可以查看词义、音标和现有例句。答错的题会回到本轮队尾，答对后可继续下一题。背诵环节提供跳过拼写的入口。一批结束后，服务端把该批词写入 `word_progress`；本页所有词都有完成记录时才写入 `progress`。

`study_sessions` 保存批次所含单词、当前轮次、题目队列和反馈。每一步提交都带当前状态的 `nonce`，这样刷新或重复提交旧表单时，学习会话不会被重复推进。

### 2. 每日复习从个人已学词中取题

从某个学员的已学词集合出发，`choose_words()` 优先选从未复习过的词，其次选距上次复习最久的词。`make_questions()` 为每个入选词生成中译英、英译中和拼写三道题。题目在创建时写入 `reviews`，答到哪一步保存在 `review_sessions`，所以退出后可以继续原来那组题。

[review.py](review.py) 的 `advance_review()` 负责逐题判分。错题回到本轮待答队列，继续作答时会再次遇到。复习中一个词通过两个互译轮次并答对拼写时，[app.py](app.py) 将它记入 `review_word_days`。一组完成后，结果页同时展示首次答对数和重试情况。

| 统计 | 计算口径 |
| --- | --- |
| 今日已复习 | 今天完成三轮的不同词数，以 UTC+8 日期为界 |
| 累计复习 | 各天复习词数之和，同一个词在不同日期可重复计入 |
| 日均复习 | 累计复习词次除以从首次复习到今天的自然日数 |
| 已复习和待复习 | 在我的已学词池中，分别统计曾复习通过的词和仍未通过的词 |
| 近 7 天 | 按天汇总复习词数，柱高按本区间最大值缩放，0 词显示零线 |

### 3. 对战取双方共同词池，发送相同试卷

`/battles` 查询双方均已学习的词。从共同词池抽题后，试题和参考答案一起保存到 `battles`，双方都使用这份题目快照。每位学员提交一次，对应 `attempts` 中一条记录。两人交卷后在数据库写事务里统一结算，按答对总题数判胜，胜者加 1 分，平局保持原积分。邀请、交卷和结算消息可在「账户消息」查看。

## 文件如何分工

| 文件 | 职责 |
| --- | --- |
| [app.py](app.py) | 创建 Flask 应用、登录与表单校验、注册页面路由、题目生成、对战评分和数据库事务 |
| [library.py](library.py) · [schema.sql](schema.sql) | 校验词库结构、按词库编号导入，并定义词汇、学习、复习、对战和消息表 |
| [study.py](study.py) · [templates/study.html](templates/study.html) | 维护背诵状态，渲染当前记忆卡、题目和学习反馈 |
| [review.py](review.py) · [templates/review.html](templates/review.html) · [templates/review_practice.html](templates/review_practice.html) | 维护复习队列、计算每日统计并渲染选题与作答页面 |
| [templates/quiz.html](templates/quiz.html) · [templates/result.html](templates/result.html) | 渲染整张试卷与交卷结果 |
| [static/study.js](static/study.js) · [static/theme.css](static/theme.css) | 实现选择题的 1–4、上下键和 Enter 操作，以及焦点提示和不同宽度的布局 |
| [desktop/StudyLauncher.swift](desktop/StudyLauncher.swift) | macOS 菜单栏和悬浮入口，启动本机 Python 服务并打开浏览器 |

## 数据与桌面入口

- [data/sample_words.json](data/sample_words.json) 是公开版默认词库。[data/study_materials.json](data/study_materials.json) 按英文词条补充例句和翻译。
- 自备词库可以沿用样例格式，包括 `key`、`title` 和 `pages`，每页包含序号、标题及带英文和中文的词条。用 `IELTS_VOCABULARY_FILE` 将应用指向该 JSON；为不同词库使用独立的 `key`，便于区分数据。
- 首次启动会在 `instance/` 新建 SQLite 数据库和应用会话密钥。学习与答卷记录保存在该数据库中。
- macOS 创建并安装好 `.venv` 后，运行 `./scripts/build_desktop.sh`，再双击生成的「词间悬浮学习.app」。桌面版使用 52732 端口。

## 测试

```sh
python -m unittest discover -s tests
```

[tests/](tests/) 覆盖样例词库导入、学习和复习进度、双人对战结算，以及旧数据迁移。
