"""Stratégie de trading basée sur l'analyse des articles des Échos."""
import json
import re
from datetime import datetime, timedelta

from strategies.base import BaseStrategy
from src.lesechos_client import fetch_articles, is_available as lesechos_available

NEGATION_WORDS = ["pas", "sans", "aucun", "aucune", "ni", "non", "jamais", "peu"]
NEGATION_WINDOW = 25  # chars to look back before a keyword match for a negation marker


def _negated_count(keywords, text, window=NEGATION_WINDOW):
    """Count keyword hits, skipping any hit whose closest preceding word
    within `window` chars is a negation marker — plain substring counting
    scored "pas de hausse" as positive, since "hausse" alone is a hit."""
    count = 0
    for w in keywords:
        start = 0
        while True:
            idx = text.find(w, start)
            if idx == -1:
                break
            prefix = text[max(0, idx - window):idx]
            if not any(re.search(rf"\b{neg}\b", prefix) for neg in NEGATION_WORDS):
                count += 1
            start = idx + len(w)
    return count

# Mots-clés français pour l'analyse de sentiment financier
POSITIVE_WORDS = {
    "hausse", "bénéfice", "record", "croissance", "profit", "dividende",
    "augmentation", "progression", "succès", "partenariat", "innovation",
    "expansion", "rachat", "rendement", "performance", "optimisme",
    "relèvement", "excédent", "prospère", "dynamique", "rebond",
    "redressement", "surperformance", "bénef", "excédentaire",
    "amélioration", "reprise", "confiance", "investissement",
    "rayonnement", "prouesse", "conquête", "déploiement", "accélération",
    "redémarrage", "vigueur", "florissant", "essor", "embellie",
    "envolée", "boom", "afflux", "abondance", "prospérité", "résistance",
    "solidité", "excellence", "leader", "pionnier", "moteur",
    "compétitivité", "rentabilité", "productivité", "efficacité",
    "acquisition", "fusion", "croissance externe", "O.P.A.", "OPA",
    "récompense", "distinction", "certification", "label",
    "développement", "nouveau marché", "expansion internationale",
}

NEGATIVE_WORDS = {
    "baisse", "perte", "dette", "déficit", "licenciement", "faillite",
    "crise", "effondrement", "chute", "récession", "procès",
    "amende", "scandale", "fraude", "enquête", "sanction",
    "dégradation", "suppression", "restructuration", "plan social",
    "abandon", "contraction", "diminution", "dépréciation",
    "déclassement", "dégringolade", "plongeon", "décote",
    "contentieux", "litige", "pénalité", "défaillance",
    "préjudice", "préoccupation", "menace", "danger", "risque",
    "incertitude", "instabilité", "volatilité", "tension",
    "inflation", "récession", "stagnation", "récession",
    "déception", "contre-performance", "désillusion",
    "plainte", "réclamation", "condamnation",
    "blocage", "impasse", "paralysie", "ralentissement",
    "faiblesse", "fragilité", "vulnérabilité", "précarité",
    "déprécié", "dévalué", "pénalisé", "sanctionné", "amende",
    "révision à la baisse", "abaissement", "dégradation de note",
}

# Mapping nom d'entreprise → ticker Yahoo Finance
# Inclut les sociétés françaises ET internationales couvertes par Les Échos
COMPANY_TICKERS = {
    # 🇫🇷 CAC 40
    "LVMH": "MC.PA",
    "TotalEnergies": "TTE.PA",
    "Sanofi": "SAN.PA",
    "Air Liquide": "AIR.PA",
    "BNP Paribas": "BNP.PA",
    "Schneider Electric": "SU.PA",
    "L'Oréal": "OR.PA",
    "Hermès": "RMS.PA",
    "AXA": "CS.PA",
    "Société Générale": "GLE.PA",
    "Crédit Agricole": "ACA.PA",
    "Vinci": "DG.PA",
    "Engie": "ENGI.PA",
    "Orange": "ORA.PA",
    "Danone": "BN.PA",
    "Renault": "RNO.PA",
    "Stellantis": "STLAP.PA",
    "Capgemini": "CAP.PA",
    "Michelin": "ML.PA",
    "Veolia": "VIE.PA",
    # 🇺🇸 US Big Tech
    "Apple": "AAPL",
    "Microsoft": "MSFT",
    "Google": "GOOGL",
    "Amazon": "AMZN",
    "Nvidia": "NVDA",
    "Meta": "META",
    "Tesla": "TSLA",
    "Netflix": "NFLX",
    # 🇺🇸 US Finance
    "JPMorgan": "JPM",
    "Goldman Sachs": "GS",
    "Morgan Stanley": "MS",
    "Bank of America": "BAC",
    "Berkshire Hathaway": "BRK-B",
    # 🇺🇸 US Industrie & Conso
    "Boeing": "BA",
    "McDonald's": "MCD",
    "Coca-Cola": "KO",
    "PepsiCo": "PEP",
    "Walmart": "WMT",
    # 🇪🇺 Europe
    "Nestlé": "NESN.SW",
    "Novartis": "NOVN.SW",
    "Siemens": "SIE.DE",
    "SAP": "SAP.DE",
    "Allianz": "ALV.DE",
    "Volkswagen": "VOW3.DE",
    "BMW": "BMW.DE",
    "Shell": "SHEL.L",
    "BP": "BP.L",
    "AstraZeneca": "AZN.L",
    "HSBC": "HSBA.L",
    "ASML": "ASML.AS",
    "Adyen": "ADYEN.AS",
    "Linde": "LIN.DE",
    "Adidas": "ADS.DE",
    # 🇨🇭 Suisse
    "UBS": "UBSG.SW",
    "Richemont": "CFR.SW",
    # 🇯🇵 Japon
    "Toyota": "7203.T",
    "Sony": "6758.T",
    "SoftBank": "9984.T",
}

# Recherche par mot-clé alternatif
COMPANY_ALIASES = {
    "BNP": "BNP Paribas",
    "Total": "TotalEnergies",
    "LVMH": "LVMH Moët Hennessy",
    "Société Générale": "Société Générale",
    "Crédit Agricole": "Crédit Agricole",
    "AXA": "AXA",
    "Air Liquide": "Air Liquide",
    "Schneider": "Schneider Electric",
    "Saint-Gobain": "Saint-Gobain",
    "Orange": "Orange",
    "Danone": "Danone",
    "Renault": "Renault",
    "Peugeot": "Stellantis",
    "Stellantis": "Stellantis",
    "Michelin": "Michelin",
    "Safran": "Safran",
    "Thales": "Thales",
    "Airbus": "Airbus",
    "Capgemini": "Capgemini",
    "EDF": "EDF",
    "Engie": "Engie",
    "Vinci": "Vinci",
    "Veolia": "Veolia",
    "Orange": "Orange",
    "L'Oréal": "L'Oréal",
    "Hermès": "Hermès",
    "Kering": "Kering",
    "Publicis": "Publicis",
}


DEFAULT_CONFIG = {
    "symbols": [
        # 🇫🇷 France
        "MC.PA", "TTE.PA", "SAN.PA", "AIR.PA", "BNP.PA",
        "SU.PA", "OR.PA", "CS.PA", "DG.PA", "BN.PA",
        "RNO.PA", "STLAP.PA", "CAP.PA", "ML.PA", "VIE.PA",
        "GLE.PA", "ACA.PA", "ENGI.PA", "ORA.PA",
        # 🇺🇸 US
        "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA",
        "META", "TSLA", "NFLX", "JPM", "GS",
        "MS", "BAC", "BRK-B", "BA", "MCD",
        "KO", "PEP", "WMT",
        # 🇪🇺 Europe
        "NESN.SW", "NOVN.SW", "SIE.DE", "SAP.DE",
        "ALV.DE", "SHEL.L", "AZN.L", "HSBA.L",
        "ASML.AS", "LIN.DE", "UBSG.SW",
        # 🇯🇵 Japon
        "7203.T", "6758.T", "9984.T",
    ],
    "lookback_days": 3,
    "min_articles": 1,
    "positive_threshold": 0.3,
    "negative_threshold": -0.2,
    "position_size_pct": 0.6,
    "section": "/finance-marches",
}


class LesEchosNewsStrategy(BaseStrategy):
    """Stratégie basée sur l'analyse des articles des Échos.
    
    Récupère les articles récents des Échos, détecte les mentions
    d'entreprises, analyse le sentiment, et trade en conséquence.
    """

    def generate_signals(self, bot, market_data):
        """Analyze Les Echos articles and generate trading signals."""
        if not lesechos_available():
            print("  [lesechos] ⚠️ Token Les Echos non trouvé — skip")
            return []

        config = bot["config"]
        symbols = config.get("symbols", [])
        lookback = config.get("lookback_days", 3)
        min_articles = config.get("min_articles", 1)
        pos_threshold = config.get("positive_threshold", 0.3)
        neg_threshold = config.get("negative_threshold", -0.2)
        pos_size = config.get("position_size_pct", 0.6)
        max_positions = config.get("max_positions", 5)
        section = config.get("section", "/finance-marches")

        # Fetch holdings from bot
        holdings = {h["symbol"]: h for h in (bot.get("holdings") or [])}
        current_positions = len(holdings)

        print(f"  [lesechos] 📰 Récupération des articles Échos...")
        articles = fetch_articles(section=section, limit=50)

        if not articles:
            print("  [lesechos] ⚠️ Pas d'articles récupérés")
            return []

        print(f"  [lesechos] ✅ {len(articles)} articles analysés")

        # Analyze sentiment per company
        company_scores = {}
        article_texts = {}

        for company_name, ticker in COMPANY_TICKERS.items():
            if ticker not in symbols:
                continue

            # Find articles mentioning this company
            company_articles = []
            for a in articles:
                text = (a.get("title", "") + " " + a.get("summary", "")).lower()
                # Check company name + aliases
                keywords = [company_name.lower()]
                # Add company name without spaces
                keywords.append(company_name.lower().replace(" ", ""))
                keywords.append(company_name.lower().replace(" ", "-"))
                # Add ticker root (only for non-generic tickers)
                ticker_root = ticker.replace(".PA", "").lower()
                # Only add ticker root if it's specific enough (> 2 chars and not a common word)
                common_tickers = {"mc", "or", "cs", "bn", "ho", "lr"}
                if len(ticker_root) > 2 and ticker_root not in common_tickers:
                    keywords.append(ticker_root)

                if any(kw in text for kw in keywords if len(kw) > 2):
                    company_articles.append(a)

            if not company_articles:
                continue

            # Score each article
            total_score = 0
            scored = 0
            article_list = []

            for a in company_articles[:5]:
                title = a.get("title", "")
                summary = a.get("summary", "")
                full_text = (title + " " + summary).lower()

                pos_count = _negated_count(POSITIVE_WORDS, full_text)
                neg_count = _negated_count(NEGATIVE_WORDS, full_text)
                total_words = pos_count + neg_count

                if total_words == 0:
                    article_score = 0  # neutral
                else:
                    article_score = (pos_count - neg_count) / max(total_words, 1)
                    article_score = max(-1, min(1, article_score))

                total_score += article_score
                scored += 1
                article_list.append({
                    "title": title[:80],
                    "score": round(article_score, 2),
                    "pos_words": pos_count,
                    "neg_words": neg_count,
                })

            avg_score = total_score / max(scored, 1) if scored > 0 else 0

            company_scores[ticker] = {
                "company": company_name,
                "avg_score": round(avg_score, 3),
                "article_count": len(company_articles),
                "articles": article_list,
            }

            print(f"  [lesechos] {company_name:20s} score={avg_score:+.2f} ({len(company_articles)} arts)")

        # Generate signals
        signals = []
        cash = bot.get("cash", 0)

        for ticker, info in company_scores.items():
            score = info["avg_score"]
            article_count = info["article_count"]

            if article_count < min_articles:
                continue

            already_held = ticker in holdings

            # Get current price from market_data
            price = None
            if market_data and ticker in market_data:
                df = market_data[ticker]
                if df is not None and not df.empty:
                    price = float(df["Close"].dropna().iloc[-1])
            elif already_held and holdings[ticker].get("avg_price"):
                price = holdings[ticker]["avg_price"]

            # BUY signal
            if score >= pos_threshold and not already_held and price and price > 0 and current_positions < max_positions:
                budget = cash * pos_size
                quantity = budget / price
                # Apply commission
                total = quantity * price
                if total > 0:
                    signals.append((ticker, "buy", quantity, price))
                    cash -= total
                    current_positions += 1
                    print(f"    ✅ ACHAT {ticker} — score {score:+.2f} ({info['company']})")

            # SELL signal
            elif score <= neg_threshold and already_held and price and price > 0:
                h = holdings[ticker]
                signals.append((ticker, "sell", h["quantity"], price))
                print(f"    ❌ VENTE {ticker} — score {score:+.2f} ({info['company']})")

        if not signals:
            print("  [lesechos] 📭 Aucun signal généré")
        else:
            print(f"  [lesechos] 📊 {len(signals)} signaux générés")

        return signals
