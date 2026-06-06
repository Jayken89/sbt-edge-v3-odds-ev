import os
import base64
from math import pow
from textwrap import dedent

import pandas as pd
import requests
import streamlit as st

# ==========================
# PAGE SETUP
# ==========================

st.set_page_config(
    page_title="SBT EDGE",
    page_icon="📈",
    layout="wide"
)

# ==========================
# SETTINGS
# ==========================

YEAR = 2026
START_RATING = 1500
K_FACTOR = 40
HOME_ADVANTAGE = 73
MARGIN_DIVISOR = 12

USER_AGENT = "Jayden AFL Predictor - jayken305@gmail.com"
TEAM_NAME_MAP = {
    "Adelaide": "Adelaide Crows",
    "Brisbane Lions": "Brisbane Lions",
    "Carlton": "Carlton Blues",
    "Collingwood": "Collingwood Magpies",
    "Essendon": "Essendon Bombers",
    "Fremantle": "Fremantle Dockers",
    "Geelong": "Geelong Cats",
    "Gold Coast": "Gold Coast Suns",
    "GWS Giants": "GWS Giants",
    "Hawthorn": "Hawthorn Hawks",
    "Melbourne": "Melbourne Demons",
    "North Melbourne": "North Melbourne Kangaroos",
    "Port Adelaide": "Port Adelaide Power",
    "Richmond": "Richmond Tigers",
    "St Kilda": "St Kilda Saints",
    "Sydney": "Sydney Swans",
    "West Coast": "West Coast Eagles",
    "Western Bulldogs": "Western Bulldogs",
}


# ==========================
# STYLING
# ==========================

def load_css():
    with open("sbt_edge_logo.png", "rb") as image_file:
        encoded = base64.b64encode(image_file.read()).decode()

    st.markdown(
        f"""
        <style>
        .stApp {{
            background-image:
                linear-gradient(rgba(2,8,18,0.88), rgba(2,8,18,0.92)),
                url("data:image/png;base64,{encoded}");
            background-size: cover;
            background-position: center;
            background-attachment: fixed;
        }}

        [data-testid="stMetric"] {{
            background: rgba(10, 16, 28, 0.80);
            border: 1px solid rgba(0, 163, 255, 0.45);
            border-radius: 18px;
            padding: 22px;
            box-shadow: 0 0 18px rgba(0,163,255,0.12);
        }}

        .stButton button {{
            background: linear-gradient(90deg, #0077ff, #00aaff);
            color: white;
            border-radius: 12px;
            border: 1px solid #00aaff;
            font-weight: bold;
            padding: 0.7rem 1.4rem;
            box-shadow: 0 0 16px rgba(0,163,255,0.25);
        }}

        .stButton button:hover {{
            border: 1px solid #66ccff;
            box-shadow: 0 0 25px rgba(0,163,255,0.55);
        }}
        </style>
        """,
        unsafe_allow_html=True
    )


load_css()

# ==========================
# API
# ==========================

def squiggle(query: str, **params):
    url = "https://api.squiggle.com.au/"
    params = {"q": query, **params}
    headers = {"User-Agent": USER_AGENT}

    response = requests.get(
        url,
        params=params,
        headers=headers,
        timeout=20
    )

    response.raise_for_status()
    return response.json()

# ==========================
# ELO MODEL
# ==========================

def expected_score(rating_a, rating_b):
    return 1 / (1 + pow(10, (rating_b - rating_a) / 400))


def build_elo(games_df):
    teams = sorted(
        set(games_df["hteam"].dropna())
        | set(games_df["ateam"].dropna())
    )

    elo = {
        team: START_RATING
        for team in teams
    }

    completed = games_df[
        games_df["complete"] == 100
    ].copy()

    completed = completed.sort_values(
        ["round", "date"]
    )

    for _, game in completed.iterrows():
        home = game["hteam"]
        away = game["ateam"]

        home_rating = elo[home] + HOME_ADVANTAGE
        away_rating = elo[away]

        home_expected = expected_score(
            home_rating,
            away_rating
        )

        if game["hscore"] > game["ascore"]:
            home_actual = 1
        elif game["hscore"] < game["ascore"]:
            home_actual = 0
        else:
            home_actual = 0.5

        margin = abs(
            game["hscore"] - game["ascore"]
        )

        margin_multiplier = max(
            1,
            margin / 30
        )

        change = (
            K_FACTOR
            * margin_multiplier
            * (home_actual - home_expected)
        )

        elo[home] += change
        elo[away] -= change

    return elo

# ==========================
# SQUIGGLE CONSENSUS
# ==========================

def get_squiggle_consensus(tips_df, game_id, home, away):
    game_tips = tips_df[
        tips_df["gameid"] == game_id
    ]

    home_votes = 0
    away_votes = 0

    for _, row in game_tips.iterrows():
        tipped_team = str(
            row.get("tip", "")
        ).strip()

        if tipped_team == home:
            home_votes += 1
        elif tipped_team == away:
            away_votes += 1

    if home_votes > away_votes:
        return home, f"{home_votes}-{away_votes}"

    if away_votes > home_votes:
        return away, f"{home_votes}-{away_votes}"

    return "No consensus", f"{home_votes}-{away_votes}"

# ==========================
# RISK + EDGE SCORE
# ==========================

def risk_rating(elo_tip, squiggle_tip, confidence):
    if squiggle_tip == "No consensus":
        return "HIGH"

    if elo_tip == squiggle_tip and confidence >= 70:
        return "LOW"

    if elo_tip == squiggle_tip and confidence >= 60:
        return "MEDIUM"

    if elo_tip == squiggle_tip:
        return "MEDIUM"

    return "HIGH"


def calculate_edge_score(confidence, risk):
    if risk == "LOW":
        risk_bonus = 1.5
    elif risk == "MEDIUM":
        risk_bonus = 0.5
    else:
        risk_bonus = -1.0

    edge_score = (confidence / 10) + risk_bonus

    edge_score = max(
        1,
        min(10, edge_score)
    )

    return round(edge_score, 1)

# ==========================
# ODDS / EV FUNCTIONS
# ==========================

# ==========================
# ODDS API
# ==========================

def fetch_afl_odds(api_key):
    url = "https://api.the-odds-api.com/v4/sports/aussierules_afl/odds/"

    params = {
        "apiKey": api_key,
        "regions": "au",
        "markets": "h2h",
        "oddsFormat": "decimal"
    }

    response = requests.get(
        url,
        params=params,
        timeout=20
    )

    response.raise_for_status()
    return response.json()

def break_even_probability(decimal_odds):
    if decimal_odds <= 0:
        return None

    return 1 / decimal_odds


def expected_roi(model_probability, decimal_odds):
    if decimal_odds <= 0:
        return None

    return (model_probability * decimal_odds) - 1


def value_rating(edge_percent, roi_percent):
    if edge_percent >= 8 and roi_percent >= 8:
        return "Strong Value"

    if edge_percent >= 4 and roi_percent >= 4:
        return "Value"

    if edge_percent >= 1 and roi_percent >= 1:
        return "Small Edge"

    return "No Value"


def multi_eligible(value_status, risk):
    if value_status in ["Strong Value", "Value"] and risk != "HIGH":
        return "YES"

    return "NO"

def find_best_odds_for_tip(odds_data, match_name, tipped_team):
    odds_team_name = TEAM_NAME_MAP.get(tipped_team, tipped_team)

    best_price = None
    best_bookmaker = None

    for game in odds_data:
        home_team = game.get("home_team", "")
        away_team = game.get("away_team", "")

        if odds_team_name not in [home_team, away_team]:
            continue

        for bookmaker in game.get("bookmakers", []):
            bookmaker_name = bookmaker.get("title", "Unknown")

            for market in bookmaker.get("markets", []):
                if market.get("key") != "h2h":
                    continue

                for outcome in market.get("outcomes", []):
                    if outcome.get("name") == odds_team_name:
                        price = outcome.get("price")

                        if best_price is None or price > best_price:
                            best_price = price
                            best_bookmaker = bookmaker_name

    if best_price is None:
        return None, None

    return best_price, best_bookmaker
    

# ==========================
# PREDICTIONS
# ==========================

def format_margin_tip(home, away, predicted_margin):
    margin_value = abs(predicted_margin)
    rounded_margin = round(margin_value)

    if predicted_margin >= 0:
        team = home
    else:
        team = away

    if rounded_margin == 0:
        return f"{team} by less than 1"

    return f"{team} by {rounded_margin}"


def make_predictions(round_number):
    games_data = squiggle(
        "games",
        year=YEAR
    )

    tips_data = squiggle(
        "tips",
        year=YEAR
    )

    games_df = pd.DataFrame(
        games_data["games"]
    )

    tips_df = pd.DataFrame(
        tips_data["tips"]
    )

    elo = build_elo(games_df)

    upcoming = games_df[
        (games_df["round"] == round_number)
        & (games_df["complete"] < 100)
    ].copy()

    rows = []

    for _, game in upcoming.iterrows():
        home = game["hteam"]
        away = game["ateam"]
        game_id = game["id"]

        home_rating = elo[home] + HOME_ADVANTAGE
        away_rating = elo[away]

        home_prob = expected_score(
            home_rating,
            away_rating
        )

        rating_difference = home_rating - away_rating
        predicted_margin = rating_difference / MARGIN_DIVISOR

        margin_tip = format_margin_tip(
            home,
            away,
            predicted_margin
        )
        
        abs_margin = abs(predicted_margin)

        if abs_margin < 10:
            margin_category = "Close Game"
        elif abs_margin < 25:
            margin_category = "Solid Margin"
        else:
            margin_category = "Strong Margin"

        away_prob = 1 - home_prob

        if home_prob >= away_prob:
            elo_tip = home
        else:
            elo_tip = away

        confidence = max(
            home_prob,
            away_prob
        ) * 100

        squiggle_tip, squiggle_votes = (
            get_squiggle_consensus(
                tips_df,
                game_id,
                home,
                away
            )
        )

        risk = risk_rating(
            elo_tip,
            squiggle_tip,
            confidence
        )

        edge_score = calculate_edge_score(
            confidence,
            risk
        )

        rows.append({
            "Match": f"{home} v {away}",
            "Final Tip": elo_tip,
            "Predicted Margin": margin_tip,
            "Raw Margin": round(predicted_margin, 1),
            "Margin Category": margin_category,
            "Elo Confidence": round(confidence, 1),
            "Edge Score": edge_score,
            "Home Win %": round(home_prob * 100, 1),
            "Away Win %": round(away_prob * 100, 1),
            "Squiggle Tip": squiggle_tip,
            "Squiggle Votes": squiggle_votes,
            "Risk": risk
        })

    return pd.DataFrame(rows)

# ==========================
# HERO SECTION
# ==========================

st.markdown(
    "<h1 style='text-align:center; font-size:82px; color:white; margin-bottom:0;'>SBT EDGE</h1>",
    unsafe_allow_html=True
)

st.markdown(
    "<h3 style='text-align:center; color:#00A3FF; margin-top:10px;'>AFL Prediction Engine</h3>",
    unsafe_allow_html=True
)

st.markdown(
    "<p style='text-align:center; color:#CCCCCC; font-size:18px;'>Validated Elo Model + Margin Predictor + Odds/EV Layer</p>",
    unsafe_allow_html=True
)

# ==========================
# KPI CARDS
# ==========================

col1, col2, col3, col4 = st.columns(4)

with col1:
    st.metric(
        "Model Accuracy",
        "69.36%"
    )

with col2:
    st.metric(
        "Avg Margin Error",
        "28.63 pts"
    )

with col3:
    st.metric(
        "Historical Games",
        "2,716"
    )

with col4:
    st.metric(
        "Model Version",
        "V3.0 Odds/EV"
    )

st.info(
    "V3 adds bookmaker odds comparison using manual input or auto-fetched AFL odds. "
    "The app calculates break-even probability, model edge, expected ROI, value rating, "
    "and best available bookmaker price where odds data is available."
)
# ==========================
# ROUND SELECTOR
# ==========================

round_number = st.number_input(
    "Round to predict",
    min_value=1,
    max_value=30,
    value=13,
    step=1
)

try:
    odds_api_key = st.secrets["ODDS_API_KEY"]
except Exception:
    odds_api_key = None
    st.warning(
        "Odds API key is not configured. "
        "Auto odds will not load until ODDS_API_KEY is added to Streamlit Secrets."
    )



# ==========================
# RUN PREDICTOR
# ==========================

if st.button("Run Predictor"):

    with st.spinner("Running SBT EDGE..."):
        df = make_predictions(round_number)

    if df.empty:
        st.warning("No upcoming games found for this round.")

    else:
        st.subheader(f"🏉 Round {round_number} Predictions")

        # --------------------------
        # ODDS INPUT
        # --------------------------

        st.subheader("💰 Bookmaker Odds Input")

        st.caption(
            "Enter decimal odds for the team SBT EDGE has tipped. "
            "Example: 1.57 means $1.57 return for every $1 staked."
        )

        auto_odds_enabled = False
        odds_data = []

        if odds_api_key:
            try:
                odds_data = fetch_afl_odds(odds_api_key)
                auto_odds_enabled = True
                st.success(f"Auto odds loaded. Found {len(odds_data)} AFL games.")
            except Exception as e:
                st.warning(f"Could not fetch auto odds: {e}")

        odds_values = []
        bookmaker_values = []

        for index, row in df.iterrows():

            default_odds = 1.50
            best_bookmaker = "Manual"

            if auto_odds_enabled:
                best_odds, api_bookmaker = find_best_odds_for_tip(
                    odds_data,
                    row["Match"],
                    row["Final Tip"]
                )

                if best_odds is not None:
                    default_odds = float(best_odds)
                    best_bookmaker = api_bookmaker

            odds = st.number_input(
                f'Odds for {row["Final Tip"]} — {row["Match"]}',
                min_value=1.01,
                max_value=20.00,
                value=default_odds,
                step=0.01,
                key=f"odds_{index}"
            )

            odds_values.append(odds)
            bookmaker_values.append(best_bookmaker)

        df["Bookmaker Odds"] = odds_values
        df["Best Bookmaker"] = bookmaker_values

        # --------------------------
        # ODDS / EV CALCULATION
        # --------------------------

        break_even_list = []
        edge_list = []
        roi_list = []
        value_list = []
        multi_list = []

        for _, row in df.iterrows():
            model_probability = row["Elo Confidence"] / 100
            decimal_odds = row["Bookmaker Odds"]

            break_even = break_even_probability(decimal_odds)
            roi = expected_roi(model_probability, decimal_odds)

            break_even_percent = break_even * 100
            roi_percent = roi * 100
            edge_percent = row["Elo Confidence"] - break_even_percent

            status = value_rating(
                edge_percent,
                roi_percent
            )

            multi_status = multi_eligible(
                status,
                row["Risk"]
            )

            break_even_list.append(round(break_even_percent, 1))
            edge_list.append(round(edge_percent, 1))
            roi_list.append(round(roi_percent, 1))
            value_list.append(status)
            multi_list.append(multi_status)

        df["Break Even %"] = break_even_list
        df["Model Edge %"] = edge_list
        df["Expected ROI %"] = roi_list
        df["Value Rating"] = value_list
        df["Multi Eligible"] = multi_list

        # --------------------------
        # BEST PICK OF THE ROUND
        # --------------------------

        best_pick = df.sort_values(
            "Edge Score",
            ascending=False
        ).iloc[0]

        st.success(
            f'🏆 BEST PICK OF THE ROUND: '
            f'{best_pick["Predicted Margin"]} '
            f'({best_pick["Match"]}) | '
            f'{best_pick["Margin Category"]} | '
            f'Confidence {best_pick["Elo Confidence"]}% | '
            f'Edge {best_pick["Edge Score"]}/10'
        )

        # --------------------------
        # BEST VALUE PICK
        # --------------------------

        value_candidates = df[
            df["Value Rating"].isin(
                ["Strong Value", "Value", "Small Edge"]
            )
        ].copy()

        if not value_candidates.empty:
            best_value = value_candidates.sort_values(
                "Expected ROI %",
                ascending=False
            ).iloc[0]

            st.success(
                f'💰 BEST VALUE PICK: '
                f'{best_value["Predicted Margin"]} '
                f'@ ${best_value["Bookmaker Odds"]:.2f} | '
                f'{best_value["Best Bookmaker"]} | '
                f'ROI {best_value["Expected ROI %"]}% | '
                f'Edge {best_value["Model Edge %"]}% | '
                f'{best_value["Value Rating"]}'
            )
        else:
            st.warning("No value picks found from the entered odds.")

        # --------------------------
        # VALUE BETS TABLE
        # --------------------------

        st.subheader("💎 Value Bets Table")

        value_table = df[
            df["Value Rating"].isin(
                ["Strong Value", "Value", "Small Edge"]
            )
        ].copy()

        value_table = value_table.sort_values(
            "Expected ROI %",
            ascending=False
        )

        if value_table.empty:
            st.warning("No value bets found from the current odds.")
        else:
            value_table = value_table[
                [
                    "Final Tip",
                    "Match",
                    "Predicted Margin",
                    "Bookmaker Odds",
                    "Best Bookmaker",
                    "Elo Confidence",
                    "Break Even %",
                    "Model Edge %",
                    "Expected ROI %",
                    "Value Rating",
                    "Multi Eligible",
                    "Risk"
                ]
            ]

            st.dataframe(
                value_table,
                use_container_width=True,
                hide_index=True
            )

                    # --------------------------
        # MULTI BUILDER CANDIDATES
        # --------------------------

        st.subheader("🧩 Multi Builder Candidates")

        multi_table = df[
            df["Multi Eligible"] == "YES"
        ].copy()

        multi_table = multi_table.sort_values(
            "Expected ROI %",
            ascending=False
        )

        if multi_table.empty:
            st.warning("No multi-eligible selections found.")
        else:
            multi_table = multi_table[
                [
                    "Final Tip",
                    "Match",
                    "Predicted Margin",
                    "Bookmaker Odds",
                    "Best Bookmaker",
                    "Elo Confidence",
                    "Model Edge %",
                    "Expected ROI %",
                    "Value Rating",
                    "Risk"
                ]
            ]

            st.dataframe(
                multi_table,
                use_container_width=True,
                hide_index=True
            )
            
            combined_odds = 1

            for odds in multi_table["Bookmaker Odds"]:
                combined_odds *= odds

            st.success(
                f'🧩 Combined Multi Odds: ${combined_odds:.2f}'
            )

        # --------------------------
        # CLOSEST / BIGGEST MARGIN
        # --------------------------

        closest_game = df.loc[
            df["Raw Margin"].abs().idxmin()
        ]

        biggest_margin = df.loc[
            df["Raw Margin"].abs().idxmax()
        ]

        summary_col1, summary_col2 = st.columns(2)

        with summary_col1:
            st.info(
                f'🎯 CLOSEST GAME: '
                f'{closest_game["Predicted Margin"]} '
                f'({closest_game["Match"]})'
            )

        with summary_col2:
            st.info(
                f'💥 BIGGEST PROJECTED MARGIN: '
                f'{biggest_margin["Predicted Margin"]} '
                f'({biggest_margin["Match"]})'
            )

        # --------------------------
        # PREDICTION CARDS
        # --------------------------

        for _, row in df.iterrows():

            risk = row["Risk"]

            if risk == "LOW":
                risk_display = "🟢 LOW"
            elif risk == "MEDIUM":
                risk_display = "🟡 MEDIUM"
            else:
                risk_display = "🔴 HIGH"

            with st.container(border=True):

                st.subheader(row["Match"])

                top_col1, top_col2, top_col3, top_col4 = st.columns(4)

                with top_col1:
                    st.caption("FINAL TIP")
                    st.write(f'**{row["Final Tip"]}**')

                with top_col2:
                    st.caption("PREDICTED MARGIN")
                    st.write(f'**{row["Predicted Margin"]}**')

                with top_col3:
                    st.caption("CONFIDENCE")
                    st.write(f'**{row["Elo Confidence"]}%**')

                with top_col4:
                    st.caption("RISK")
                    st.write(f'**{risk_display}**')

                bottom_col1, bottom_col2, bottom_col3, bottom_col4, bottom_col5 = st.columns(5)

                with bottom_col1:
                    st.caption("MARGIN TYPE")
                    st.write(f'**{row["Margin Category"]}**')

                with bottom_col2:
                    st.caption("EDGE SCORE")
                    st.write(f'**{row["Edge Score"]}/10**')

                with bottom_col3:
                    st.caption("SQUIGGLE")
                    st.write(f'**{row["Squiggle Tip"]}**')
                    st.caption(f'Votes: {row["Squiggle Votes"]}')

                with bottom_col4:
                    st.caption("BEST ODDS")
                    st.write(f'**${row["Bookmaker Odds"]:.2f}**')
                    st.caption(
                        f'{row["Best Bookmaker"]} | '
                        f'Break-even: {row["Break Even %"]}%'
                    )

                with bottom_col5:
                    st.caption("VALUE")
                    st.write(f'**{row["Value Rating"]}**')
                    st.caption(
                        f'Edge: {row["Model Edge %"]}% | '
                        f'ROI: {row["Expected ROI %"]}%'
                    )

        # --------------------------
        # PICK GROUPS
        # --------------------------

        safe = df[df["Risk"] == "LOW"]
        solid = df[df["Risk"] == "MEDIUM"]
        danger = df[df["Risk"] == "HIGH"]

        group_col1, group_col2, group_col3 = st.columns(3)

        with group_col1:
            st.subheader("🔥 Best Picks")

            if safe.empty:
                st.write("No low-risk picks found.")
            else:
                for _, row in safe.iterrows():
                    st.success(
                        f'{row["Predicted Margin"]} | '
                        f'{row["Elo Confidence"]}% | '
                        f'Edge {row["Edge Score"]}/10'
                    )

        with group_col2:
            st.subheader("🟡 Solid Picks")

            if solid.empty:
                st.write("No medium-risk picks found.")
            else:
                for _, row in solid.iterrows():
                    st.info(
                        f'{row["Predicted Margin"]} | '
                        f'{row["Elo Confidence"]}% | '
                        f'Edge {row["Edge Score"]}/10'
                    )

        with group_col3:
            st.subheader("⚠️ Danger Games")

            if danger.empty:
                st.write("No high-risk games.")
            else:
                for _, row in danger.iterrows():
                    st.warning(
                        f'{row["Match"]} → '
                        f'{row["Predicted Margin"]} | '
                        f'{row["Elo Confidence"]}%'
                    )

        # --------------------------
        # CSV EXPORT
        # --------------------------

        os.makedirs("outputs", exist_ok=True)

        output_path = f"outputs/round_{round_number}_app_tips.csv"

        df.to_csv(output_path, index=False)

        st.success(f"Saved CSV to {output_path}")