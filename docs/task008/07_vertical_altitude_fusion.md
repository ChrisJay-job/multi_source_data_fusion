# multisensor-3d-v1 海拔垂直滤波说明

日期：2026-10-24。Profile：`multisensor-3d-v1`。单位：米；契约基准：MSL（`database_altitude_msl_v1`）。

## 模型

- 水平：沿用 `multisensor-v1` 二维 CV KF + 身份/扫描关联（不变）。
- 垂直：独立状态 `[海拔高度, 垂直速度]` 线性 KF（`ConstantVelocity1D`）。
- 解耦三维位置估计；不是全耦合六状态或三维距离关联。

## 配置（`config/fusion.yaml` → `multisensor_3d_v1`）

| 项 | 含义 | 初值 |
|---|---|---|
| `q_alt` / `q_vspeed` | 过程噪声 | 1.0 / 0.5 |
| `altitude_std_m.{rid,spectrum,radar}` | 测量标准差（米） | 5 / 15 / 25 |
| `altitude_innov_m` | 创新门（米） | 80 |
| `mapping_version` | 字段映射版本 | `database_altitude_msl_v1` |

未现场标定；工程初值。陌生 `altitudeDatum` 不参与垂直更新。

## 证据分轴

- `trajectoryUpdates[].altitudeObservationIds`：该水平提交点关联的垂直证据。
- `altitudeUpdates[]`：无新水平点时的独立垂直增量（含稳定 `altitudeUpdateId`）。
- Snapshot：`altitudeMode` / `altitudeStateTime` / `lastAltitudeObservedAt`。

Secondary 仅高度可更新垂直状态，不得推进水平 KF 时钟或把 lost 续成 tracked。

## HTTP / MQTT

同一 profile；MQTT 适配调用既有 `/v1/fusion/process`。省略 profile 仍为 legacy。
