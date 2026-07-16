from .base import IntradayStrategy
from .crypto_scalper import CryptoScalper
from .crypto_mean_rev import CryptoMeanRev
from .crypto_momentum import CryptoMomentum
from .dip_buyer import DipBuyer
from .social_momentum import SocialMomentum

STRATEGY_CLASSES = {
    "crypto_scalper": CryptoScalper,
    "crypto_mean_rev": CryptoMeanRev,
    "crypto_momentum": CryptoMomentum,
    "dip_buyer": DipBuyer,
    "social_momentum": SocialMomentum,
}

__all__ = ["IntradayStrategy", "STRATEGY_CLASSES"]
