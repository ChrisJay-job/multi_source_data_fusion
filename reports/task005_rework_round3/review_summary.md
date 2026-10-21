# TASK-005 attempt-001 REWORK Round3 — review_summary

日期：2026-10-21  
状态：**REVIEW_READY**（继续 attempt-001；仅 R3-01）

## 基线

| 项 | 值 |
|---|---|
| Round2 包 SHA | `a0302dc6ce8b41c574afe4faef5a4397c5c039edf4f59476e24c76d575d76317` |
| 本包外置 SHA | 见 `bundle_sha256.txt` |
| 冻结算法 | 与 Round1 哈希一致（`match_r1=true`） |

## R3-01

`count_id_exchanges`：可映射帧 `<2` → `null`（不再报 0）。UI 显示「不可计算」+ note。可测稳定仍为真实 0。

## 证据

- `id_exchange_pre.json` / `id_exchange_post.json`
- `pytest_r3.log`、`full_pytest_worktree.log`、`clean_extract_full_pytest.log`
- `browser/browser_evidence.json`（匿名不可计算；有身份可测数值）
- `docs/task005/r3_closure_table.md`、`r2_metrics_definitions.md`（Round3 口径）

## 禁止项

未 commit/tag/push；未开下一阶段；TASK-004 仍待确认；真实三源 BLOCKED；现场精度/2GB NOT_TESTED。
