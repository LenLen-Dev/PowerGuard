# PowerGuard · 宿舍电量监控与邮件预警

![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)
![GUI](https://img.shields.io/badge/GUI-PySide6-41CD52?logo=qt&logoColor=white)
![Notifier](https://img.shields.io/badge/Notifier-SMTP%20Email-0EA5E9)
![Platform](https://img.shields.io/badge/Platform-Windows-0078D4?logo=windows&logoColor=white)

> 接管/代配置：可以向作者（`2653626988@qq.com`）提供宿舍号和对应宿舍人员的一个 QQ 邮箱即可接管；也可以填写腾讯文档：[[腾讯文档] 宿舍楼号](https://docs.qq.com/sheet/DWFNueEtUQkRsckxa)。

一个面向宿舍场景的电量监控项目，支持：
- 无 GUI 持续监控（`run.py`）
- GUI 卡片化管理多宿舍（`run_gui.py`）
- 低电量预警邮件 + 每晚汇总邮件
- 北京时间调度规则（静默时段、每日重置、22点汇总）
- 日志持久化到 `logs/`，按周自动清空

---

## 1. 功能总览

| 模块 | 能力 |
|---|---|
| 接口查询 | 定时请求电量接口，解析 `errmsg` 中剩余电量 |
| 多宿舍 | GUI/无GUI都支持多宿舍配置与独立轮询 |
| 告警策略 | 阈值触发（`<=`）+ 冷却时间防轰炸 |
| 邮件通知 | SMTP 文本+HTML模板，低电量红色高亮 |
| 静默时段 | 北京时间 `00:00:00 - 08:00:00` 不发送任何邮件 |
| 每日统计 | 每天 `00:00` 重置“今日耗电”统计 |
| 每晚汇总 | 仅在北京时间 `22` 点小时内发送，每宿舍每天最多1次 |
| 日志 | 输出到控制台与文件，默认在 `logs/` |

---

## 2. 项目结构

```text
dorm-power-alert/
├─ app/
│  ├─ clients/                # 接口请求
│  ├─ parsers/                # 返回解析
│  ├─ services/               # 监控核心逻辑
│  ├─ notifiers/              # 邮件通知
│  ├─ gui/                    # PySide6 GUI
│  ├─ config.py               # 环境变量配置与校验
│  ├─ logging_setup.py        # 日志配置（含周清空）
│  └─ main.py                 # 无GUI主调度（多宿舍）
├─ tests/
│  ├─ test_parser.py
│  └─ test_quiet_hours.py
├─ .env.example
├─ dorm_profiles.example.json
├─ requirements.txt
├─ requirements-build.txt
├─ build_gui.ps1
├─ run.py
└─ run_gui.py
```

---

## 3. 环境准备（uv + .venv）

> 你当前使用 `uv` 且虚拟环境在 `.venv`，推荐按以下方式。

```powershell
cd dorm-power-alert
uv venv .venv
.\.venv\Scripts\Activate.ps1
uv pip install -r requirements.txt
```

---

## 4. 配置 `.env`

先复制模板：

```powershell
Copy-Item .env.example .env
```

### 4.1 必填项（最少）

| 分类 | 变量 |
|---|---|
| 接口 | `REFERER` `JSESSIONID` `AID` `ACCOUNT` `AREA` `AREA_NAME` `BUILDING_ID` `BUILDING_NAME` `ROOM_ID` `ROOM_NAME` |
| 邮件 | `EMAIL_SMTP_HOST` `EMAIL_USERNAME` `EMAIL_PASSWORD` `EMAIL_FROM` `EMAIL_TO` |

### 4.2 常用可调项

| 变量 | 默认值 | 说明 |
|---|---:|---|
| `CHECK_INTERVAL_SECONDS` | `300` | 查询间隔（秒） |
| `LOW_BALANCE_THRESHOLD` | `10` | 低电量阈值 |
| `ALERT_COOLDOWN_SECONDS` | `1800` | 低电量告警冷却（秒） |
| `REQUEST_TIMEOUT_SECONDS` | `15` | 请求超时（秒） |
| `LOG_LEVEL` | `INFO` | 日志等级 |
| `DORM_PROFILES_FILE` | `gui_profiles.json` | 无GUI多宿舍配置文件 |
| `HEADLESS_LOG_FILE` | `logs/headless_monitor.log` | 无GUI日志文件 |
| `GUI_LOG_FILE` | `logs/gui_monitor.log` | GUI日志文件 |

### 4.3 `#` 字符注意事项

如果值中含 `#`（如 `男19#楼`），请加引号，避免被当成注释：

```env
BUILDING_NAME="男19#楼"
```

---

## 5. 运行方式

### 5.1 无 GUI 版本

```powershell
python run.py
```

特点：
- 适合长期后台运行
- 支持多宿舍（读取 `DORM_PROFILES_FILE`）
- 自动进行每日统计重置与22点汇总邮件

### 5.2 GUI 版本

```powershell
python run_gui.py
```

特点：
- 卡片式列表展示宿舍状态
- 支持新增/编辑/删除宿舍配置
- 楼栋下拉模糊搜索，房号可输入
- 列表项与详情联动，支持“立即查询/开始监控/停止监控”

---

## 6. 多宿舍配置

### 6.1 GUI 模式

GUI 会将配置保存到：
- `gui_profiles.json`
- `gui_usage_state.json`

### 6.2 无 GUI 模式

`run.py` 默认读取 `DORM_PROFILES_FILE=gui_profiles.json`，也可改成其他路径。  
格式参考 [dorm_profiles.example.json](./dorm_profiles.example.json)：

```json
[
  {
    "name": "男19-215",
    "building_id": "10",
    "building_name": "男19#楼",
    "room": "215",
    "alert_email": "receiver@example.com",
    "interval_seconds": 300,
    "threshold": 10
  }
]
```

---

## 7. 调度与告警规则（北京时间）

| 规则 | 行为 |
|---|---|
| 轮询查询 | 每宿舍按各自 `interval_seconds` 执行 |
| 低电量判断 | `balance <= threshold` |
| 冷却机制 | 同一低电量状态下，冷却时间内不重复告警 |
| 每日重置 | `00:00` 重置当日耗电统计，并触发下一次查询 |
| 每晚汇总 | 仅在 `22` 点小时内发送汇总（每天每宿舍最多1次） |
| 静默时段 | `00:00:00 - 08:00:00` 不发送任何邮件（含告警/汇总） |

---

## 8. 邮件模板说明

- 支持 HTML 样式邮件
- 正常提醒：蓝色头部
- 低电量提醒：红色头部 + 电量红色高亮
- 展示字段包括：项目、房间、账号、当前剩余电量、今日耗电量、接口提示、查询时间（北京时间）

---

## 9. 日志说明

默认日志文件：
- `logs/headless_monitor.log`
- `logs/gui_monitor.log`

行为：
- 自动创建 `logs/` 目录
- 文件日志按周自动清空（同文件滚动重置）
- GUI 日志颜色：`INFO` 绿色，`WARNING` 红色

---

## 10. 运行测试

```powershell
python -m unittest discover -s tests -v
```

当前包含：
- 解析器测试（`test_parser.py`）
- 静默时段边界测试（`test_quiet_hours.py`）

---

## 11. 打包 GUI 为 EXE（无 Python 机器可运行）

### 11.1 安装打包依赖

```powershell
uv pip install -r requirements-build.txt
```

### 11.2 一键打包

```powershell
powershell -ExecutionPolicy Bypass -File .\build_gui.ps1
```

### 11.3 产物

```text
dist/DormPowerAlertGUI/DormPowerAlertGUI.exe
```

脚本会优先使用以下 Python 解释器执行 `PyInstaller`：
- `dorm-power-alert/.venv/Scripts/python.exe`
- 工作区根目录 `.venv/Scripts/python.exe`

脚本会自动拷贝：
- `.env.example`
- `dorm_profiles.example.json`

并创建：
- `logs/`

### 11.4 部署到目标机器

直接拷贝整个 `dist/DormPowerAlertGUI` 目录到目标电脑，配置 `.env` 后双击 EXE 即可。

---

## 12. 已知限制

- 登录态依赖固定 `JSESSIONID` 与 `Referer`
- 暂未实现自动登录/自动续期
- 构建 EXE 建议 Python `3.11/3.12`（兼容性更稳）

---
