# MI-R2 关闭表

| ID | 输入 | 断言 | 结果 | 路径 |
| --- | --- | --- | --- | --- |
| MI-R2-01 | 附录 draw 探针 81 与 400 | renderedDistinct==n 且首点送入绘图 | **PASS** | `draw_probe_result.json` / `draw_probe_from_extract.json` |
| MI-R2-01 | 真实小样两视口，仅 fused+current，列表「查看航迹」 | early/late 点均出现在 draw 几何 | **PASS** | `browser/` / `browser_isolated/`（canvas `bc1c9f39…`） |
| MI-R2-02 | 全新解压 `pytest tests/` | 无普通 fixture 缺失失败 | **PASS** 277 passed / 2 skipped（完整 XLS 外部） | `pytest_extract.log` |

算法指纹保持。原 18089 保留。R1 旧浏览器目录已归档 history，不以混合 SHA 作本轮 PASS。
