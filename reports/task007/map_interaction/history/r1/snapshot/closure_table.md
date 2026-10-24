# MI-R1 关闭表

| ID | 输入 | 断言 | 结果 | 原始路径 |
| --- | --- | --- | --- | --- |
| MI-R1-01 | binding_reuse 反例（同三元组 A/B） | containsOtherFusionObservation=false | PASS | `reports/task007/map_interaction/r1/independent_counterexamples.json` |
| MI-R1-02 | rolling_history 0..79 ∪ 1..80 | keepsFirst && count=81 | PASS | 同上 |
| MI-R1-03 | current_only_fit | distanceFromCenterCanvasPx≤1 | PASS | 同上 |
| MI-R1-04 | 1920×1080 DPR1 + 1280×800 DPR2 真实鼠标/UI/仿真路点 | browser_result.pass=true | PASS | `reports/task007/map_interaction/r1/browser/browser_result.json` |
| MI-R1-05 | 全新解压 + 隔离 compose 18121 | 静态/算法 SHA 匹配；浏览器 BASE=隔离 URL | PASS | `reports/task007/map_interaction/r1/isolated_repro.json` |

未执行扩展：大样全页性能、252MB、三源同机精度 → **NOT_TESTED**（沿用专项边界）。

算法指纹保持：multisensor `f5d91955…`，fusion.yaml `ab2d9b4f…`。
