# PLT 管线图转换与编号标注

北海项目固定入口，沿用 PD60 已确认的转换、定位和布局规则。输出按管线号和 sheet 号命名的单页 PDF，以及只含待处理条目的问题清单。

## 日常转换

在本目录运行：

```powershell
python run_beihai.py --list-units
python run_beihai.py --unit PD60 --workers 2
```

PowerShell 入口等效，支持从其他工作目录用完整路径调用：

```powershell
.\run_beihai.ps1 -Unit PD60 -Workers 2
```

后续单元将 `PD60` 替换为实际单元号即可，无需复制脚本。默认 2 个页面进程；4 进程可用 `--workers 4` 试跑，尚未进行全单元性能验证。

默认输入相对于上一级 `IDF解析` 目录：

| 输入 | 路径 |
|---|---|
| 原图与 UCI 索引 | `北海项目/PLT文件转换/{单元}/` 内的同名 `.plt`、`.hit` |
| 对应模型 | `北海项目/IDF/{单元}/{管线号}.idf` |
| 焊口、管段编号 | `北海项目/焊口表.csv` |
| 三类管理编号 | 同目录 `阀门表.csv`、`法兰表.csv`、`支架表.csv` |

每个单元只放一套导出版本，避免相同管线、sheet 的重复文件。默认同时标注焊口、管段、阀门、法兰、支架；仅需焊口和管段时加 `--no-management`。

默认交付到该单元输入目录：

- `转换标注PDF/{管线号}_Sht_{页码}.pdf`
- `北海{单元}_标注问题清单.xlsx`

重跑更新同名结果。问题清单保留“未标注编号”“已标注需核对”，有布局问题时才增加“布局需处理”。成功明细与资源监测写入本项目 `beihai_audit/`，不混入交付清单。

更多参数通过 `python run_beihai.py --help` 查看。可覆盖 `--input-dir`、`--idf-dir`、`--weld-table`、`--management-tables-dir`、`--out-dir`。单管线复核使用：

```powershell
python run_beihai.py --unit PD60 --pipeline 50-SIO2-66906-201 --workers 2
```

单管线默认写入独立复核子目录和独立问题清单。

## 目录组织

```text
run_beihai.py / run_beihai.ps1   日常转换入口
profiles/beihai/
  config.json                  已验证的样式与图框配置
  workflow/                    单元转换编排
  parser/                      PLT/HIT/IDF、编号定位、布局与 PDF 模块
  运行说明.txt                  定位规则及复核说明
tools/                         关联预检、完整结果校验
tests/                         当前规则回归测试
beihai_audit/
  render_records/              当前内部转换审计记录
  performance/                 CPU、内存采样与性能评估
archive/2026-10-29/             历史样例、试出图、调试证据与源码快照
```

部分解析模块保留早期名称（如 `render_complete_pdms.py`），它们仍提供现行入口所需的几何或布局函数，属于正式运行依赖。历史独立实验脚本已移入归档。

Git 仓库只保存正式代码、配置、说明及校验/回归测试代码。`archive/`、`beihai_audit/`、原始导出文件、业务表格和 PDF/预览等生成产物仅在本地保留，不提交。克隆仓库后需自行准备项目数据；使用 PD60 实例和历史证据的回归测试也需要对应本地资料。

## 预检与校验

```powershell
python tools/preflight_beihai_annotations.py --unit PD60 --revision latest
python tools/verify_beihai_outputs.py --unit PD60
python -m unittest discover -s tests -p "test_beihai_*.py"
```

预检只计算关联、不重绘 PDF；完整校验读取现有单页 PDF 和内部转换记录，检查来源覆盖、字体颜色、框线布局、阀门中心及管段实际线条落点。当前回归样例来自 PD60，部分历史证据由测试从归档读取。

若交付 PDF 文件夹已重命名，校验时加 `--out-dir "实际PDF目录"`。例如 PD60 当前交付目录为 `北海项目/PLT文件转换/PD60/北海PD60_转换标注PDF`，整理时保留该目录。

## 环境与适用范围

使用 Python 3.10 或更新版本，依赖安装：`python -m pip install -r requirements.txt`。字体使用 Windows `SimHei`。

布局继续复用相邻 SHA 项目的成达代码，必须保留 `IDF解析` 同级的 `PCF解析/parse-piping-sha/profiles/chengda_indonesia/{parser,workflow}`。归档整理没有复制或替换该套布局算法。

当前配置已验证北海 A2 横向图框（材料栏在右）。同格式后续单元可复用；更换图框时应先检查配置与结果。
