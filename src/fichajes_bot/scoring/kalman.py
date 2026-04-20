"""1D Kalman filter for transfer probability smoothing.

Why Kalman here?
  - Transfer probabilities are noisy (each rumor is a noisy observation).
  - The underlying "true probability" changes slowly (process noise Q is small).
  - We want to be responsive to genuine changes (hard signals: fichaje oficial,
    retractación) without being jerked around by every tabloid rumor.

Adaptive Q/R:
  - Q_adaptive = Q_base * hard_signal_mult  when a fichaje_oficial or
    retractación is detected. This widens the process noise, letting
    the filter update fast to the new reality.
  - R_adaptive = R_base / credibilidad_media  — a measurement from a set of
    credible journalists has less noise than one from tabloids.

State persistence:
  - x (filtered score) → jugadores.score_smoothed
  - P (error covariance) → jugadores.kalman_P

A P near 1.0 means high uncertainty (fresh player, no stable estimate yet).
A P near 0.001 means the filter has converged and will barely move per rumor.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# ── Default parameters (overridden from configs/scoring.yaml) ─────────────────

Q_BASE = 0.01          # process noise covariance
R_BASE = 0.04          # measurement noise covariance (base)
HARD_SIGNAL_MULT = 3.0 # multiply Q when hard signal detected
INITIAL_P = 1.0        # initial error covariance (max uncertainty)
INITIAL_X = 0.05       # initial state (low score before any news)


@dataclass
class KalmanState:
    """Kalman filter state for one player."""
    x: float = INITIAL_X   # current estimate (score_smoothed)
    P: float = INITIAL_P   # error covariance (uncertainty)


class KalmanFilter1D:
    """Discrete 1D Kalman filter for scalar score tracking.

    Model:
        x_k   = x_{k-1} + noise_process     (Q)
        z_k   = x_k     + noise_measurement  (R)

    Update equations:
        K   = P / (P + R)                    (Kalman gain)
        x'  = x + K * (z - x)               (posterior mean)
        P'  = (1 - K) * P + Q               (posterior covariance)
    """

    def __init__(
        self,
        Q_base: float = Q_BASE,
        R_base: float = R_BASE,
        hard_signal_mult: float = HARD_SIGNAL_MULT,
    ) -> None:
        self.Q_base = Q_base
        self.R_base = R_base
        self.hard_signal_mult = hard_signal_mult

    def update(
        self,
        state: KalmanState,
        observation: float,
        credibilidad_media: float = 0.50,
        hard_signal: bool = False,
    ) -> KalmanState:
        """Perform one Kalman update step.

        Args:
            state:               Current (x, P) state.
            observation:         New score_raw measurement (signal from rumores).
            credibilidad_media:  Mean reliability of the rumor batch (0..1).
                                 Higher credibility → lower R → stronger update.
            hard_signal:         True for confirmed transfers/retractions.
                                 Multiplies Q to allow fast state changes.

        Returns:
            New KalmanState after incorporating the observation.
        """
        x, P = state.x, state.P

        # Adaptive Q — allow faster changes when hard signals are present
        Q = self.Q_base * (self.hard_signal_mult if hard_signal else 1.0)

        # Adaptive R — credible sources = less measurement noise
        # Clamp credibilidad to [0.1, 1.0] to avoid division issues
        cred = max(0.1, min(1.0, credibilidad_media))
        R = self.R_base / cred

        # Prediction step (no control input, trivial in 1D)
        x_pred = x
        P_pred = P + Q

        # Update step
        K = P_pred / (P_pred + R)           # Kalman gain ∈ [0, 1)
        x_new = x_pred + K * (observation - x_pred)
        P_new = (1.0 - K) * P_pred

        # Clamp state to valid score range
        x_new = max(0.001, min(0.999, x_new))
        P_new = max(1e-6, P_new)

        return KalmanState(x=round(x_new, 6), P=round(P_new, 6))

    def convergence_rate(self, state: KalmanState, credibilidad: float = 0.5) -> float:
        """Kalman gain for current state — how much a new observation moves the estimate."""
        cred = max(0.1, min(1.0, credibilidad))
        R = self.R_base / cred
        P_pred = state.P + self.Q_base
        return P_pred / (P_pred + R)

    def predict_only(self, state: KalmanState) -> KalmanState:
        """Time update only (no measurement). Increases P slightly."""
        P_new = state.P + self.Q_base
        return KalmanState(x=state.x, P=round(P_new, 6))


def state_from_db(score_smoothed: float, kalman_P: float) -> KalmanState:
    """Reconstruct KalmanState from DB fields."""
    x = float(score_smoothed or INITIAL_X)
    P = float(kalman_P or INITIAL_P)
    return KalmanState(x=max(0.001, min(0.999, x)), P=max(1e-6, P))
