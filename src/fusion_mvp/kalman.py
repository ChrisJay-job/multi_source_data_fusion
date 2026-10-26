from __future__ import annotations

import numpy as np


class ConstantVelocityKF:
    def __init__(self, x: float, y: float, q_pos: float, q_vel: float, r: float):
        self.x = np.array([x, y, 0.0, 0.0], dtype=float)
        self.P = np.diag([r, r, 25.0, 25.0]).astype(float)
        self.q_pos = float(q_pos)
        self.q_vel = float(q_vel)

    def predict(self, dt: float) -> None:
        dt = max(float(dt), 1e-3)
        F = np.array(
            [
                [1, 0, dt, 0],
                [0, 1, 0, dt],
                [0, 0, 1, 0],
                [0, 0, 0, 1],
            ],
            dtype=float,
        )
        q = self.q_pos
        qv = self.q_vel
        Q = np.diag([q * dt, q * dt, qv * dt, qv * dt])
        self.x = F @ self.x
        self.P = F @ self.P @ F.T + Q

    def update(self, zx: float, zy: float, r: float) -> float:
        H = np.array([[1, 0, 0, 0], [0, 1, 0, 0]], dtype=float)
        z = np.array([zx, zy], dtype=float)
        R = np.diag([r, r])
        y = z - H @ self.x
        S = H @ self.P @ H.T + R
        K = self.P @ H.T @ np.linalg.inv(S)
        self.x = self.x + K @ y
        I = np.eye(4)
        self.P = (I - K @ H) @ self.P
        innov = float(np.hypot(y[0], y[1]))
        return innov

    @property
    def pos(self) -> tuple[float, float]:
        return float(self.x[0]), float(self.x[1])

    @property
    def vel(self) -> tuple[float, float]:
        return float(self.x[2]), float(self.x[3])


class ConstantVelocity1D:
    """Independent vertical [altitude_m, vertical_speed_mps] linear KF (MSL)."""

    def __init__(self, z: float, q_pos: float, q_vel: float, r: float):
        self.x = np.array([float(z), 0.0], dtype=float)
        self.P = np.diag([float(r), 25.0]).astype(float)
        self.q_pos = float(q_pos)
        self.q_vel = float(q_vel)

    def predict(self, dt: float) -> None:
        dt = max(float(dt), 1e-3)
        F = np.array([[1.0, dt], [0.0, 1.0]], dtype=float)
        Q = np.diag([self.q_pos * dt, self.q_vel * dt])
        self.x = F @ self.x
        self.P = F @ self.P @ F.T + Q

    def update(self, z: float, r: float) -> float:
        H = np.array([[1.0, 0.0]], dtype=float)
        zz = np.array([float(z)], dtype=float)
        R = np.array([[float(r)]], dtype=float)
        y = zz - H @ self.x
        S = H @ self.P @ H.T + R
        K = self.P @ H.T @ np.linalg.inv(S)
        self.x = self.x + (K @ y).reshape(2)
        I = np.eye(2)
        self.P = (I - K @ H) @ self.P
        return float(abs(y[0]))

    @property
    def alt(self) -> float:
        return float(self.x[0])

    @property
    def vspeed(self) -> float:
        return float(self.x[1])
