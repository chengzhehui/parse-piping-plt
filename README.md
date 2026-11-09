# PLT 单线图还原与编号标注

Git 仓库只提交代码、配置、测试和说明；本地的历史资料与运行记录目录由 Git 忽略。输入 PDMS 导出的 IDF、PLT、HIT 及编号 CSV，输出按管线号和 sheet 命名的单页 PDF、简明问题清单和运行证据。

## 通用入口

安装依赖：

```powershell
python -m pip install -r requirements.txt
```

指定输入、输出目录：

```powershell
python run_pipeline.py --input-dir "D:\数据\PLT" --idf-dir "D:\数据\IDF" --hit-dir "D:\数据\HIT" --weld-table "D:\数据\焊口表.csv" --management-tables-dir "D:\数据\编号表" --out-dir "D:\结果\单线图" --workers 8
```

也可以单独指定三类管理表，文件名可以自定义：

```powershell
python run_pipeline.py --input-dir "D:\数据\PLT" --idf-dir "D:\数据\IDF" --hit-dir "D:\数据\HIT" --weld-table "D:\数据\welds.csv" --support-table "D:\数据\supports.csv" --valve-table "D:\数据\valves.csv" --flange-table "D:\数据\flanges.csv" --out-dir "D:\结果\单线图"
```

- PLT 命名为 `{管线号}_Sht_{页码}.plt`，IDF 为 `{管线号}.idf`，HIT 与 PLT 同名。PLT 目录递归读取；IDF、独立 HIT 目录按文件名查找。
- HIT 位于 PLT 旁时省略 `--hit-dir`。
- `--management-tables-dir` 仅读取目录内实际存在的 `支架表.csv`、`阀门表.csv`、`法兰表.csv`；单独指定表格可覆盖同类文件。
- 编号表均为 EP3D CSV，支持 UTF-8 和 GB18030。焊口按管线号、焊点编号和焊点位置关联，管理编号按管线号、编号及完整 UCI 关联。
- 表格可以按需提供；省略焊口表时只标管理编号，全部省略则仅还原原图。
- 默认不按管理表的单元号筛选；`--unit PD20` 可限定单元，但通用入口始终不加载北海单元专属配置。
- `--pipeline 管线号` 处理指定管线；`--spool` 根据焊口表增加管段号；`--workers` 指定页面工作进程数，默认 8。
- 当前图幅规则为北海已验证的 A2 横向图框，字高 6mm、固定 12mm 焊口红圈、蓝色紧凑管理编号框。使用 Windows SimHei 字体。

输出目录包含：

```text
PDF/{管线号}_Sht_{页码}.pdf
标注问题清单.xlsx
.audit/                       定位证据及 CPU/内存记录
```

输出目录必须位于代码项目之外。运行保留原始导出文件和 CSV。无法可靠定位的编号进入问题清单，不猜测焊口编号或 UCI。

## 代码组织

```text
run_pipeline.py                通用输入、输出入口
run_beihai.py / run_beihai.ps1  北海项目兼容入口
profiles/beihai/config.json    图幅、字体和标注配置
profiles/beihai/units/         北海单元名称、坐标及参考模型配置
profiles/beihai/workflow/      出图编排及按页多进程
profiles/beihai/parser/        PLT/HIT/IDF解析、编号关联、布局及PDF
  plt_layout_core.py          项目内独立布局求解器
  plt_label_metrics.py        管理编号框尺寸计算
tools/                        关联预检、余项分析、结果校验
tests/                        规则及真实项目回归测试代码
```

布局核心从已验证的成达布局代码中提取保留，包含相互避让、跨线及分档引线长度惩罚；运行不再依赖旁边的 `parse-piping-sha` 项目。字体和 Python 依赖仍需安装。

## 北海项目兼容与历史资料

原入口继续可用：`python run_beihai.py --unit PD20`，或 `.\run_beihai.ps1 -Unit PD20`。各单元参数位于 `profiles/beihai/units/`；运行前核对其中的输入路径、表格版本及明确的管线映射。

历史资料与运行记录保存在本项目内的以下本地目录，不提交 Git：

- `历史运行结果/archive/`：旧样例、PDF、问题表及源码快照。
- `运行记录/`：已有定位记录、预检、调试及资源监测结果；北海兼容入口的后续运行记录也写到此处。
- `历史运行结果/legacy_code/`：仅用于旧 PD60 运行历史汇总的辅助代码及整理前说明。

可通过环境变量 `PLT_AUDIT_DIR` 指定北海入口和诊断工具的运行记录目录。通用入口始终将本次记录放到指定输出目录的 `.audit/`。生产出图不读取历史审计数据。

测试代码保留；涉及实际项目的回归测试需要外部的北海原始资料或历史样例，数据不随代码分发。诊断工具分别为 `tools/preflight_beihai_annotations.py`、`tools/audit_beihai_remaining.py`、`tools/verify_beihai_outputs.py`。不再在新出图过程中自动追加旧 PD60 的历史轮次记录。
