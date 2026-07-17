from .sma_crossover import SMACrossoverStrategy
from .rsi_mean_reversion import RSIMeanReversionStrategy
from .momentum import MomentumStrategy
from .bollinger_bands import BollingerBandsStrategy
from .dca import DCAStrategy
from .pairs_trading import PairsTradingStrategy
from .fundamental import FundamentalStrategy
from .sentiment import SentimentStrategy
from .sentiment_av import SentimentAVStrategy
from .lesechos_news import LesEchosNewsStrategy
from .donchian_breakout import DonchianBreakoutStrategy
from .pead import PEADStrategy
from .low_volatility import LowVolatilityStrategy
from .reversal_1day import Reversal1DayStrategy
from .sector_rotation import SectorRotationStrategy
from .post_fomc_drift import PostFOMCDriftStrategy

STRATEGY_MAP = {
    "sma_crossover": SMACrossoverStrategy,
    "rsi_mean_reversion": RSIMeanReversionStrategy,
    "momentum": MomentumStrategy,
    "bollinger_bands": BollingerBandsStrategy,
    "dca": DCAStrategy,
    "pairs_trading": PairsTradingStrategy,
    "fundamental": FundamentalStrategy,
    "sentiment": SentimentStrategy,
    "sentiment_av": SentimentAVStrategy,
    "lesechos_news": LesEchosNewsStrategy,
    "donchian_breakout": DonchianBreakoutStrategy,
    "pead": PEADStrategy,
    "low_volatility": LowVolatilityStrategy,
    "reversal_1day": Reversal1DayStrategy,
    "sector_rotation": SectorRotationStrategy,
    "post_fomc_drift": PostFOMCDriftStrategy,
}


def get_strategy(name):
    """Return an instance of the named strategy."""
    cls = STRATEGY_MAP.get(name)
    if cls is None:
        raise ValueError(f"Unknown strategy: {name}")
    return cls()
