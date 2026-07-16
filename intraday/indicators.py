"""Pure-python technical indicators (no pandas dependency, small candle lists)."""


def ema(values, period):
    """Exponential moving average. Returns a list the same length as values,
    with None for indices before the seed window."""
    n = len(values)
    if n < period:
        return [None] * n

    k = 2 / (period + 1)
    result = [None] * (period - 1)
    seed = sum(values[:period]) / period
    result.append(seed)
    prev = seed
    for v in values[period:]:
        prev = v * k + prev * (1 - k)
        result.append(prev)
    return result


def rsi(values, period=14):
    """Wilder's RSI. Returns the latest RSI value, or None if not enough data."""
    if len(values) < period + 1:
        return None

    gains, losses = [], []
    for i in range(1, len(values)):
        delta = values[i] - values[i - 1]
        gains.append(max(delta, 0.0))
        losses.append(max(-delta, 0.0))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))
