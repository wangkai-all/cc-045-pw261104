# 数据集结构版本与兼容性平台

面向 JSONL 数据集的结构版本管理工具：维护字段结构、发布锁定版本、逐行校验上传文件、
双向判断新旧版本兼容性，并通过**显式映射**完成版本间数据转换。

技术栈：Python 3.11 + FastAPI + SQLite（标准库 `sqlite3`）+ React 18 + Vite。

## 快速开始

```bash
# 后端
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements.txt
.venv/bin/uvicorn app.main:app --app-dir backend --reload --port 8000

# 前端（另开终端）
cd frontend
npm install --cache ./.npm-cache   # 如全局 npm 缓存目录不可写
npm run dev                        # http://localhost:5173 ，/api 代理到 8000
```

测试与离线演示（无需起服务）：

```bash
.venv/bin/pytest backend/tests -q          # 56 项单元/API 测试
cd backend && ../.venv/bin/python -I seed_demo.py   # 五类样本场景全流程打印
.venv/bin/python -I backend/e2e_http.py    # 对运行中的后端做 HTTP 端到端断言
```

## 字段结构能力

页面「字段结构」编辑器递归支持七种类型：对象、数组、文本、整数、定点小数、布尔、
ISO 日期字符串。每个字段可设置：

- **必填 `required`**、**可空 `nullable`**、**默认值 `has_default/default`**；
- decimal 的**总位数 precision 与小数位数 scale 分开声明与校验**（scale ≤ precision）；
- **别名 `aliases`**：新版本声明旧字段名，用于改名后读取旧文件；
- 对象可嵌套子字段，数组声明元素定义；结构定义本身在保存时校验（含默认值是否符合自身类型）。

## 核心读取规则（校验与兼容性共用）

| 规则 | 行为 |
|------|------|
| 未声明字段 | 统一忽略，不报错 |
| 缺字段 | 有默认值才静默补齐；无默认值时仅必填字段报错 |
| 显式 `null` | 只按读取方自身的 `nullable` 规则判断，默认值不顶替显式 null |
| 整数 → 小数 | 精度足够时可无损读入 decimal，位数不够报溢出 |
| 小数 → 整数 | 禁止，不做隐式截断/取整 |
| 字符串 ↔ 数字 | 禁止任何隐式转换 |
| decimal | 总位数与小数位数分别校验，超限分别报 `decimal_overflow` / `decimal_scale` |
| 日期 | `date.fromisoformat` 按真实日历校验（2 月 30 日、闰年 2 月 29 日均正确识别） |
| JSONL | 逐行解析，问题定位到**行号**与嵌套路径（如 `$.meta.tag`、`$.tags[1]`） |

## 双向兼容性

每次对比同时给出两个方向的独立结论，再汇总总体结论：

- **旧读取方**：旧程序读取新文件——未声明的新字段被忽略；改名后的新字段名旧程序
  永远无法自动理解（旧定义必填无默认值时为 error，否则仅 info 级忽略）。
- **新读取方**：新程序读取旧文件——可通过别名识别改名；新增必填字段只有在新版
  本带默认值时才能容忍旧文件缺字段。

结论分三级：`compatible` / `compatible_with_warnings` / `incompatible`，每条发现
带方向、字段路径、代码、严重级和中文说明，可直接拿样本复核。

## 版本锁定与显式转换分离

- 结构版本发布后**锁定**，锁定版本拒绝任何字段修改（API 返回 409，前端编辑器冻结）。
- 数据转换**不**被视为结构兼容：必须新建显式映射（`rename` / `cast_decimal` /
  `set_default` / `drop`），先产出**草稿**并展示逐行 before→after 变化与目标结构
  复校结果，确认后才生成新 JSONL 文件；每个草稿只允许生成一次，源文件不被修改。

## 五类样本（`backend/samples/`）

`v1_data.jsonl` 每行对应一个要求场景，`README.md` 给出逐行预期结论：

1. 新增必填字段视角（第 4 行缺必填 `sku`）；
2. 显式 null（第 2 行 `price:null`，按可空规则放行）+ 非法真实日历日期；
3. 数组/小数越界（第 3 行 `99.999` 超过 scale=2；版本对比中 `tags` 元素 text→integer）；
4. 小数越界与整数无损入 decimal（第 1 行整数 `10` 正常读入 decimal）；
5. 别名改名（v2 用别名 `sku` 读旧文件）与字符串不隐式转数字（第 5 行 `qty:"1"`）。

## 目录结构

```
backend/
  app/
    domain.py       # 字段结构定义与默认值校验
    validation.py   # 单记录/JSONL 逐行校验引擎
    compat.py       # 双向兼容性判定引擎
    mapping.py      # 显式映射：草稿预览与文件生成
    storage.py      # SQLite 持久化（版本锁定、上传、映射记录）
    main.py         # FastAPI 路由
  tests/            # 56 项 pytest
  samples/          # 五类场景样本与复核说明
  seed_demo.py      # 离线领域层演示
  e2e_http.py       # 真实 HTTP 端到端断言
frontend/src/
  components/       # 递归字段树编辑器、上传面板
  pages/            # 数据集/版本、兼容性对比、映射转换
```
