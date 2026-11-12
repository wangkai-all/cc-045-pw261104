# 五类兼容性场景样本

所有样本围绕同一数据集的两个锁定版本：

- **v1（旧版）**：`sku`(text,必填)、`qty`(integer,必填)、`price` decimal(8,2)、
  `tags`(text 数组)、`day`(date)
- **v2（新版）**：`sku` 改名为 `product_code` 并声明别名 `sku`；`price` 升为
  decimal(10,2)、必填且有默认值 `0.00`；`tags` 改为 **integer 数组**；
  新增必填布尔 `active`（有默认值 `true`）

## 样本文件 `v1_data.jsonl` 逐行复核

| 行 | 场景 | 预期结论 |
|----|------|----------|
| 1 | 基线（含整数 10 写入 decimal） | 通过：integer 无损读入 decimal(8,2) |
| 2 | 显式 null + 非法日期 | `price:null` 在 v1 可空规则下通过；`2026-02-30` 真实日历不存在，报 `invalid_date` |
| 3 | 小数越界 | `99.999` 小数位 3 > scale=2，报 `decimal_scale`（总位数与小数位分开校验） |
| 4 | 新增必填字段视角 | 缺少必填 `sku` 且无默认值，报 `missing_required` |
| 5 | 字符串不隐式转数字 | `qty:"1"` 报 `type_mismatch`，字符串不会转成 integer |

## 版本对比结论（双向）

运行 `python seed_demo.py` 可直接打印，也可在页面「版本对比」中复核：

1. **别名改名**：新读取方经别名 `sku` 读旧文件 → 兼容（info）；旧读取方不认识
   `product_code`，且旧定义 `sku` 必填无默认值 → 旧读取方方向 **error**
2. **数组类型变化**：`tags` 元素 text→integer，两个方向都报结构类型不兼容 **error**
3. **新增必填字段** `active`：带默认值，新旧方向均只产生 `default_fills` info
4. **null 规则**：`price` 由可空收紧为不可空，新读取方可能在旧文件遇到 null → error
5. **小数扩位**：decimal(8,2)→(10,2) 只放宽不收紧，无问题；反向才会报警告/错误

## 显式转换（不视为结构兼容）

`mapping_rules.json` 给出 v1→v2 的显式映射草稿：`sku` 改名 `product_code`、
为 `active` 补默认值。转换流程必须是：先预览逐行 before/after 变化 → 再生成新
JSONL 文件；结构版本本身保持锁定，转换能力不算兼容性。
