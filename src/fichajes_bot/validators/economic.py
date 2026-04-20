"""EconomicValidator — assess financial viability of a transfer for Real Madrid.

Reads modelo_economico (latest active row) and evaluates whether RM can
afford a player given the current salary cap margin and transfer budget.

Factor values:
  1.2  comfortable: fits easily (margen > 1.5× estimated annual cost)
  1.0  ok: fits within budget with reasonable room
  0.7  requires_sale: needs to offload to create headroom
  0.3  impossible: > DEFICIT_IMPOSSIBLE_M of deficit (e.g. 50M+)

Salary estimation (when not scraped from Capology):
  salario_estimado = valor_mercado_m × SALARY_RATIO_DEFAULT
  (typically ~4% of market value per year for top players)
"""

from __future__ import annotations

from loguru import logger

from fichajes_bot.persistence.d1_client import D1Client

# ── Factor thresholds ─────────────────────────────────────────────────────────

FACTOR_COMFORTABLE = 1.20
FACTOR_OK          = 1.00
FACTOR_NEEDS_SALE  = 0.70
FACTOR_IMPOSSIBLE  = 0.30

# Budget headroom multipliers that map to factors
HEADROOM_COMFORTABLE = 1.50    # margin > 1.5× salary → comfortable
HEADROOM_OK          = 1.00    # margin > 1.0× salary → ok
HEADROOM_SALE        = 0.50    # margin > 0.5× salary → needs sale
# below 0.5× → impossible

DEFICIT_IMPOSSIBLE_M = 50.0    # deficit (€M) above which → factor = IMPOSSIBLE

SALARY_RATIO_DEFAULT = 0.04    # annual salary ≈ 4% of market value
AMORTISATION_YEARS   = 5       # spread transfer fee over 5 years


class EconomicValidator:
    """Evaluates economic viability of a potential signing."""

    def __init__(self, db: D1Client) -> None:
        self.db = db
        self._modelo: dict | None = None  # cached for instance lifetime

    async def get_modelo_actual(self) -> dict | None:
        """Fetch the most recent active economic model from D1."""
        if self._modelo is not None:
            return self._modelo

        rows = await self.db.execute(
            "SELECT * FROM modelo_economico WHERE activo=1 "
            "ORDER BY fecha_actualizacion DESC LIMIT 1"
        )
        if rows:
            self._modelo = rows[0]
        return self._modelo

    async def evaluate(
        self,
        jugador_id: str,
        salario_estimado_m: float | None = None,
        traspaso_estimado_m: float | None = None,
    ) -> float:
        """Return economic viability factor in [0.3, 1.2].

        Args:
            jugador_id:            Player to evaluate.
            salario_estimado_m:    Override salary estimate (€M/year). If None,
                                   computed from jugadores.valor_mercado_m.
            traspaso_estimado_m:   Override transfer fee (€M). If None,
                                   computed from jugadores.valor_mercado_m.
        """
        modelo = await self.get_modelo_actual()
        if modelo is None:
            logger.debug("EconomicValidator: no modelo_economico found, returning neutral")
            return 1.0

        margen_salarial = float(modelo.get("margen_salarial") or 0.0) / 1_000_000
        presupuesto     = float(modelo.get("presupuesto_fichajes_restante") or 0.0) / 1_000_000

        # Fetch jugador data for estimates if not provided
        if salario_estimado_m is None or traspaso_estimado_m is None:
            jugador = await self._fetch_jugador(jugador_id)
            vm = float(jugador.get("valor_mercado_m") or 30.0) if jugador else 30.0
            if salario_estimado_m is None:
                salario_estimado_m = vm * SALARY_RATIO_DEFAULT
            if traspaso_estimado_m is None:
                traspaso_estimado_m = vm

        factor = _evaluate_factor(
            margen_salarial, presupuesto, salario_estimado_m, traspaso_estimado_m
        )

        logger.debug(
            f"EconomicValidator: {jugador_id[:8]} "
            f"salario={salario_estimado_m:.1f}M traspaso={traspaso_estimado_m:.1f}M "
            f"margen={margen_salarial:.1f}M presupuesto={presupuesto:.1f}M → {factor}"
        )
        return factor

    async def _fetch_jugador(self, jugador_id: str) -> dict | None:
        rows = await self.db.execute(
            "SELECT valor_mercado_m, posicion FROM jugadores WHERE jugador_id=? LIMIT 1",
            [jugador_id],
        )
        return rows[0] if rows else None


def _evaluate_factor(
    margen_salarial_m: float,
    presupuesto_m: float,
    salario_m: float,
    traspaso_m: float,
) -> float:
    """Pure function: map budget headroom to factor."""
    if salario_m <= 0:
        return FACTOR_OK

    salary_ratio   = margen_salarial_m / salario_m
    transfer_ratio = presupuesto_m / traspaso_m if traspaso_m > 0 else 2.0

    # Deficit check
    deficit = max(0.0, salario_m - margen_salarial_m)
    if deficit >= DEFICIT_IMPOSSIBLE_M:
        return FACTOR_IMPOSSIBLE

    if salary_ratio >= HEADROOM_COMFORTABLE and transfer_ratio >= 1.0:
        return FACTOR_COMFORTABLE
    if salary_ratio >= HEADROOM_OK and transfer_ratio >= 0.8:
        return FACTOR_OK
    if salary_ratio >= HEADROOM_SALE or transfer_ratio >= 0.5:
        return FACTOR_NEEDS_SALE
    return FACTOR_IMPOSSIBLE
