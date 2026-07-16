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
}


def get_strategy(name):
    """Return an instance of the named strategy."""
    cls = STRATEGY_MAP.get(name)
    if cls is None:
        raise ValueError(f"Unknown strategy: {name}")
    return cls()
