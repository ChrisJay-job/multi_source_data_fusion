# Round5 浏览器说明

按 Round5 指令：不重跑整套无关 UI 链路。Round4 已认可的请求 speed、鼠标点选、FAIL/pinned 硬断言继续有效。

评估失败明细现含 `lifecycle_clock` / `display_clock` / `last_observation` / `gap_s` 等字段，页面若已渲染 `entity_check.details` 即可展示；本轮未强制重测整窗。

**登记**：fused/pred 坐标仍为弱匹配（样本命中 / 存在性），精确逐点比对 **未覆盖**，不宣称完成全部坐标验收。
