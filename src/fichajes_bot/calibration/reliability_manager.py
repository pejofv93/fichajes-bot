"""ReliabilityManager — Bayesian per-journalist reliability with contextual shrinkage.

Reliability model
─────────────────
Each journalist has a Beta distribution over their prediction accuracy:
    prior:   Beta(alpha_0, beta_0)  [typically (1.0, 1.0) = uniform]
    posterior after k successes in n predictions:
             Beta(alpha_0 + k, beta_0 + n - k)
    point estimate:  E[p] = alpha / (alpha + beta)

Contextual shrinkage (Apéndice C)
──────────────────────────────────
When we have few RM-specific observations (n < SHRINKAGE_THRESHOLD), we blend
the RM-specific reliability toward the journalist's global reliability:

    reliability_ctx = (n_ctx * r_ctx + K * r_global) / (n_ctx + K)

where K = SHRINKAGE_K (= 10 pseudo-observations equivalent).

This prevents over-fitting to a small sample:
  - If n_ctx = 0:  reliability_ctx ≈ r_global  (no local info, use global)
  - If n_ctx = 30: reliability_ctx ≈ r_ctx      (enough local data to trust)

Cache
─────
An in-process dict cache avoids repeated DB queries within a single job run.
The cache is per-instance. Call `clear_cache()` between batches if needed.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from loguru import logger

from fichajes_bot.persistence.d1_client import D1Client

SHRINKAGE_K = 10.0        # pseudo-observations toward global prior
SHRINKAGE_THRESHOLD = 30  # n below which we apply shrinkage
BETA_ALPHA_PRIOR = 1.0    # uniform prior alpha
BETA_BETA_PRIOR = 1.0     # uniform prior beta


@dataclass
class ReliabilityEstimate:
    """Point estimate + uncertainty for one journalist/context combination."""
    reliability: float          # E[p] = alpha / (alpha + beta)
    alpha: float                # posterior alpha
    beta: float                 # posterior beta
    n_observations: int         # total observations used
    n_global: int               # journalist's global observation count
    shrinkage_applied: bool     # True if blended with global
    context: str = "global"     # "global", "rm", "club:xxx", "tipo:xxx"

    @property
    def uncertainty(self) -> float:
        """Variance of the Beta distribution — higher = less certain."""
        a, b = self.alpha, self.beta
        return (a * b) / ((a + b) ** 2 * (a + b + 1))

    @property
    def credible_interval_95(self) -> tuple[float, float]:
        """95% credible interval [lo, hi] (approximation via ±2σ)."""
        std = self.uncertainty ** 0.5
        lo = max(0.0, self.reliability - 2 * std)
        hi = min(1.0, self.reliability + 2 * std)
        return lo, hi


class ReliabilityManager:
    """Manage journalist reliability with Bayesian Beta-Binomial updates.

    Usage:
        mgr = ReliabilityManager(db)
        est = await mgr.get_reliability("fabrizio-romano")
        est_rm = await mgr.get_reliability("fabrizio-romano", context="rm")
        await mgr.update_after_outcome("fabrizio-romano", "CONFIRMADO", context="rm")
    """

    def __init__(self, db: D1Client) -> None:
        self.db = db
        self._cache: dict[str, ReliabilityEstimate] = {}

    def clear_cache(self) -> None:
        self._cache.clear()

    # ── Public API ────────────────────────────────────────────────────────────

    async def get_reliability(
        self,
        periodista_id: str,
        context: str = "global",   # "global" | "rm" | "club:xxx" | "tipo:xxx"
        club: str | None = None,
        liga: str | None = None,
        tipo: str | None = None,
    ) -> ReliabilityEstimate:
        """Return reliability estimate for a journalist, optionally contextual.

        Parameters
        ----------
        periodista_id:  journalist slug, e.g. "fabrizio-romano"
        context:        preferred context key (overrides individual params)
        club:           club name for club-specific context
        liga:           liga name for liga-specific context
        tipo:           transfer type ("FICHAJE", "SALIDA", etc.)
        """
        # Build canonical context key
        ctx_key = self._context_key(context, club, liga, tipo)
        cache_key = f"{periodista_id}|{ctx_key}"

        if cache_key in self._cache:
            return self._cache[cache_key]

        est = await self._compute_reliability(periodista_id, ctx_key)
        self._cache[cache_key] = est
        return est

    async def update_after_outcome(
        self,
        periodista_id: str,
        outcome: str,              # "CONFIRMADO" or "FALLIDO"
        context: str = "global",
        rumor_id: str | None = None,
        club: str | None = None,
        liga: str | None = None,
        tipo: str | None = None,
    ) -> None:
        """Beta-Binomial update after observing an outcome.

        Updates both the specific context AND global stats.
        """
        success = 1 if outcome == "CONFIRMADO" else 0
        ctx_key = self._context_key(context, club, liga, tipo)

        # Always update global stats
        await self._update_global(periodista_id, success)

        # Update context-specific stats if not global
        if ctx_key != "global":
            await self._update_context(periodista_id, ctx_key, success)

        # Log to calibracion_periodistas for traceability
        if rumor_id:
            await self._log_calibration(periodista_id, rumor_id, success)

        # Invalidate cache
        self._cache = {k: v for k, v in self._cache.items()
                       if not k.startswith(periodista_id)}

        logger.debug(
            f"Reliability updated: {periodista_id} | outcome={outcome} | ctx={ctx_key}"
        )

    async def batch_update(
        self,
        updates: list[dict[str, Any]],
    ) -> None:
        """Process multiple outcome updates efficiently.

        Each item: {periodista_id, outcome, context?, rumor_id?, ...}
        """
        for upd in updates:
            await self.update_after_outcome(
                periodista_id=upd["periodista_id"],
                outcome=upd["outcome"],
                context=upd.get("context", "global"),
                rumor_id=upd.get("rumor_id"),
                club=upd.get("club"),
                liga=upd.get("liga"),
                tipo=upd.get("tipo"),
            )

    async def get_top_journalists(
        self, n: int = 10, min_observations: int = 5
    ) -> list[ReliabilityEstimate]:
        """Return top-n journalists by global reliability (with enough data)."""
        rows = await self.db.execute(
            "SELECT periodista_id, reliability_global, alpha_global, beta_global, "
            "n_predicciones_global, n_aciertos_global "
            "FROM periodistas "
            "WHERE n_predicciones_global >= ? "
            "ORDER BY reliability_global DESC LIMIT ?",
            [min_observations, n],
        )
        result = []
        for r in rows:
            alpha = float(r["alpha_global"] or BETA_ALPHA_PRIOR)
            beta_val = float(r["beta_global"] or BETA_BETA_PRIOR)
            n_obs = int(r["n_predicciones_global"] or 0)
            est = ReliabilityEstimate(
                reliability=_beta_mean(alpha, beta_val),
                alpha=alpha,
                beta=beta_val,
                n_observations=n_obs,
                n_global=n_obs,
                shrinkage_applied=False,
                context="global",
            )
            result.append(est)
        return result

    # ── Internal: compute ─────────────────────────────────────────────────────

    async def _compute_reliability(
        self, periodista_id: str, ctx_key: str
    ) -> ReliabilityEstimate:
        # Fetch journalist row
        rows = await self.db.execute(
            "SELECT * FROM periodistas WHERE periodista_id=? LIMIT 1",
            [periodista_id],
        )

        if not rows:
            # Unknown journalist — return weak prior
            return ReliabilityEstimate(
                reliability=0.5,
                alpha=BETA_ALPHA_PRIOR,
                beta=BETA_BETA_PRIOR,
                n_observations=0,
                n_global=0,
                shrinkage_applied=False,
                context=ctx_key,
            )

        row = rows[0]
        global_alpha = float(row.get("alpha_global") or BETA_ALPHA_PRIOR)
        global_beta = float(row.get("beta_global") or BETA_BETA_PRIOR)
        global_n = int(row.get("n_predicciones_global") or 0)
        global_r = _beta_mean(global_alpha, global_beta)

        # Global context — return directly
        if ctx_key == "global":
            return ReliabilityEstimate(
                reliability=global_r,
                alpha=global_alpha,
                beta=global_beta,
                n_observations=global_n,
                n_global=global_n,
                shrinkage_applied=False,
                context="global",
            )

        # RM-specific context
        if ctx_key == "rm":
            rm_alpha = float(row.get("alpha_rm") or BETA_ALPHA_PRIOR)
            rm_beta = float(row.get("beta_rm") or BETA_BETA_PRIOR)
            rm_n = int(row.get("n_predicciones_rm") or 0)
            rm_r = _beta_mean(rm_alpha, rm_beta)

            if rm_n < SHRINKAGE_THRESHOLD:
                blended = _shrinkage(rm_r, rm_n, global_r, SHRINKAGE_K)
                return ReliabilityEstimate(
                    reliability=blended,
                    alpha=rm_alpha,
                    beta=rm_beta,
                    n_observations=rm_n,
                    n_global=global_n,
                    shrinkage_applied=True,
                    context="rm",
                )

            return ReliabilityEstimate(
                reliability=rm_r,
                alpha=rm_alpha,
                beta=rm_beta,
                n_observations=rm_n,
                n_global=global_n,
                shrinkage_applied=False,
                context="rm",
            )

        # Generic context (club/liga/tipo) — read from calibracion_periodistas
        return await self._compute_generic_context(
            periodista_id, ctx_key, global_r, global_n
        )

    async def _compute_generic_context(
        self,
        periodista_id: str,
        ctx_key: str,
        global_r: float,
        global_n: int,
    ) -> ReliabilityEstimate:
        # Count outcomes for this journalist/context from calibracion_periodistas
        rows = await self.db.execute(
            "SELECT outcome_real FROM calibracion_periodistas "
            "WHERE periodista_id=? AND contexto LIKE ? "
            "ORDER BY fecha_outcome DESC LIMIT 100",
            [periodista_id, f'%"context":"{ctx_key}"%'],
        )

        n_ctx = len(rows)
        k_ctx = sum(1 for r in rows if r["outcome_real"] == 1)

        alpha_ctx = BETA_ALPHA_PRIOR + k_ctx
        beta_ctx = BETA_BETA_PRIOR + (n_ctx - k_ctx)
        r_ctx = _beta_mean(alpha_ctx, beta_ctx)

        shrinkage_applied = n_ctx < SHRINKAGE_THRESHOLD
        if shrinkage_applied:
            r_ctx = _shrinkage(r_ctx, n_ctx, global_r, SHRINKAGE_K)

        return ReliabilityEstimate(
            reliability=r_ctx,
            alpha=alpha_ctx,
            beta=beta_ctx,
            n_observations=n_ctx,
            n_global=global_n,
            shrinkage_applied=shrinkage_applied,
            context=ctx_key,
        )

    # ── Internal: update ─────────────────────────────────────────────────────

    async def _update_global(self, periodista_id: str, success: int) -> None:
        await self.db.execute(
            """UPDATE periodistas SET
                 n_predicciones_global = n_predicciones_global + 1,
                 n_aciertos_global = n_aciertos_global + ?,
                 alpha_global = alpha_global + ?,
                 beta_global = beta_global + ?,
                 reliability_global = (alpha_global + ?) / (alpha_global + ? + beta_global + ?)
               WHERE periodista_id = ?""",
            [success, success, 1 - success,
             success, success, 1 - success,
             periodista_id],
        )

    async def _update_context(
        self, periodista_id: str, ctx_key: str, success: int
    ) -> None:
        if ctx_key == "rm":
            await self.db.execute(
                """UPDATE periodistas SET
                     n_predicciones_rm = n_predicciones_rm + 1,
                     n_aciertos_rm = n_aciertos_rm + ?,
                     alpha_rm = alpha_rm + ?,
                     beta_rm = beta_rm + ?,
                     reliability_rm = (alpha_rm + ?) / (alpha_rm + ? + beta_rm + ?)
                   WHERE periodista_id = ?""",
                [success, success, 1 - success,
                 success, success, 1 - success,
                 periodista_id],
            )

    async def _log_calibration(
        self, periodista_id: str, rumor_id: str, success: int
    ) -> None:
        import json
        from datetime import datetime, timezone

        rows = await self.db.execute(
            "SELECT rumor_id, confianza_extraccion FROM rumores WHERE rumor_id=? LIMIT 1",
            [rumor_id],
        )
        prediccion = float(rows[0]["confianza_extraccion"]) if rows else 0.5
        brier = (prediccion - success) ** 2

        await self.db.execute(
            """INSERT INTO calibracion_periodistas
               (cal_id, periodista_id, rumor_id, prediccion, outcome_real,
                brier_contribution, fecha_outcome)
               VALUES (?,?,?,?,?,?,datetime('now'))""",
            [str(uuid.uuid4()), periodista_id, rumor_id, prediccion, success, brier],
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _context_key(
        context: str,
        club: str | None,
        liga: str | None,
        tipo: str | None,
    ) -> str:
        if context not in ("global", "rm"):
            return context
        if club:
            return f"club:{club.lower().replace(' ', '_')}"
        if liga:
            return f"liga:{liga.lower().replace(' ', '_')}"
        if tipo:
            return f"tipo:{tipo.upper()}"
        return context


# ── Pure math helpers ─────────────────────────────────────────────────────────

def _beta_mean(alpha: float, beta: float) -> float:
    """E[X] where X ~ Beta(alpha, beta)."""
    return alpha / (alpha + beta)


def _shrinkage(
    local_r: float,
    n_local: int,
    global_r: float,
    k: float = SHRINKAGE_K,
) -> float:
    """Shrink local estimate toward global when sample is small.

    Formula: (n_local * local_r + k * global_r) / (n_local + k)
    """
    return (n_local * local_r + k * global_r) / (n_local + k)
