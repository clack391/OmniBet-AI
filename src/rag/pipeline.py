import os
import json
import re
import requests
import google.generativeai as genai
from dotenv import load_dotenv
from datetime import datetime, timezone, timedelta
from src.utils.time_utils import get_now_wat, get_today_wat_str, to_wat

load_dotenv()

# Initialize Gemini
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

# Use a standard stable model compatible with the free tier/broad availability
# We use gemini-3-pro-preview for deeper analytical reasoning and Google Search Grounding support 
MODEL_NAME = "gemini-3.1-pro-preview"
model = genai.GenerativeModel(MODEL_NAME)

def get_active_model() -> str:
    """Read the active Gemini model from app settings at call time."""
    try:
        from src.database.db import get_app_setting
        return get_app_setting("gemini_model", MODEL_NAME) or MODEL_NAME
    except Exception:
        return MODEL_NAME

def check_cancelled(match_id: int = None, job_id: str = None):
    """Checks the global cancellation registry. Raises Exception to kill the thread if cancelled."""
    
    # 1. Check Redis (for Celery Worker context)
    if job_id:
        try:
            import redis as redis_lib
            r = redis_lib.Redis(host="localhost", port=6379, db=0, decode_responses=True)
            if r.exists(f"job:{job_id}:cancel"):
                print(f"🛑 [KILL SWITCH] Aborting active Gemini task for Job {job_id}")
                raise Exception("Prediction manually cancelled by user")
        except Exception as e:
            if "manually cancelled" in str(e): raise e
            print(f"⚠️ Redis Check Error: {e}")
            pass

    # 2. Check in-memory flags (for Sync API context)
    try:
        from src.api.main import CANCELLATION_FLAGS
        if match_id and CANCELLATION_FLAGS.get(match_id):
            print(f"🛑 [KILL SWITCH] Aborting active Gemini task for Match {match_id}")
            raise Exception("Prediction manually cancelled by user")
    except ImportError:
        pass

    # 3. Check Database for Global/Cron Kill Signal
    try:
        from src.database.db import get_app_setting
        if get_app_setting("cron_kill_signal", "false") == "true":
            print(f"🛑 [GLOBAL KILL] Aborting active Gemini task due to global stop signal")
            raise Exception("Daily Cron manually stopped by user")
    except Exception:
        pass


def predict_match(team_a: str, team_b: str, match_stats: dict, odds_data: list = None, h2h_data: dict = None, home_form: dict = None, away_form: dict = None, home_standings: dict = None, away_standings: dict = None, advanced_stats: dict = None, match_date: str = None, match_id: int = None, job_id: str = None):

    check_cancelled(match_id, job_id)

    # Check for Stale Data (e.g. API stuck in IN_PLAY for > 4 hours)
    is_stale = False
    is_historical = False
    before_date = ""
    try:
        if match_date:
            # Parse ISO8601 string (e.g. 2026-02-19T00:30:00Z)
            match_dt = datetime.fromisoformat(match_date.replace("Z", "+00:00"))
            now_dt = datetime.now(timezone.utc)
            duration = (now_dt - match_dt).total_seconds() / 3600

            # Blind Backtest Mode: If match started in the past, constrain search to pre-match data only
            if duration > 0:
                is_historical = True
                before_date = (match_dt - timedelta(days=1)).strftime("%Y-%m-%d")
                
            if match_stats.get('status') == 'IN_PLAY' and duration > 4:
                is_stale = True
    except Exception as e:
        print(f"Error parse match_date: {e}")

    # Construct Prompt
    stale_warning = ""
    if is_stale:
        stale_warning = """
    ### DATA WARNING: STALE API FEED
    - The match start time was over 4 hours ago, but the API still reports 'IN_PLAY' with a 0-0 score.
    - **THIS IS LIKELY AN API ERROR.** The match has almost certainly finished.
    - **IGNORE THE 0-0 SCORE.** It is likely incorrect/stale.
    - Treat this as a PREDICTION based on pre-match form and stats, NOT a live commentary.
    """

    current_date_str = get_today_wat_str()

    prompt = f"""
    Act as an expert quantitative sports analyst for OmniBet AI.
    Current Date: {current_date_str}
    
    Match: {team_a} vs {team_b}
    {stale_warning}
    
    ### Match Stats / Data
    {json.dumps(match_stats, indent=2)}
    
    ### Head-to-Head & Form (Historical Context)
    {json.dumps(h2h_data, indent=2) if h2h_data else "No H2H data available."}
    
    ### The Fortress Effect: Isolated Venue Form (Last 5 Matches)
    Home Team ({team_a}) Form AT HOME: {json.dumps(home_form, indent=2) if home_form else "N/A"}
    Away Team ({team_b}) Form AWAY FROM HOME: {json.dumps(away_form, indent=2) if away_form else "N/A"}
    
    ### League Standings
    Home Team ({team_a}): {json.dumps(home_standings, indent=2) if home_standings else "N/A"}
    Away Team ({team_b}): {json.dumps(away_standings, indent=2) if away_standings else "N/A"}
    
    ### Market Odds (Implied Probability Context)
    {json.dumps(odds_data, indent=2) if odds_data else "No live odds available."}
    
    ### Advanced Tactical Metrics (RapidAPI SofaScore)
    {json.dumps(advanced_stats, indent=2) if advanced_stats else "No advanced tactical metrics available."}
    
    ### CRITICAL: HOME/AWAY VENUE SPLITS
    If the data above contains a "home_away_split" key, it holds venue-filtered stats:
    - The Home team's stats are from HOME matches ONLY.
    - The Away team's stats are from AWAY matches ONLY.
    - **SAMPLE SIZE MANDATE**: If the number of matches in the split is $< 5$, you MUST "blend" this data with the general "metrics" block. Do NOT anchor exclusively on a 3-match venue streak, as it is statistically noisy. Use the general season metrics as the baseline and only use the venue split to "adjust" your confidence slightly. 
    - **IF THE "home_away_split" KEY IS MISSING**: This means venue-specific data is unavailable. You MUST rely on the general "metrics" block.
    
    ### CRITICAL INSTRUCTIONS
    1. **CHECK THE MATCH STATUS**:
       - 'TIMED'/'SCHEDULED'/'UPCOMING' -> Match NOT started.
       - 'IN_PLAY'/'PAUSED' (with >0 score or recent start) -> Live Prediction.
       - **Ignore 0-0 score** if Stale Data Warning is present.
       
    2. **DYNAMIC WEIGHTING & DATA SEARCH FALLBACK**:
       - **Advanced Tactical Analysis**: Use the `Advanced Tactical Metrics` block to mathematically determine the match script. Do not just look at "Goals Scored." Compare "Shots on target", "Big chances missed", "Interceptions per game", and "Ball possession". For example, if a team has 65% possession but the opponent averages 18 interceptions and 20 tackles, expect a frustrating low-block scenario.
       - If any critical data block above says "No data available." or "N/A" (especially Odds or Standings), you MUST use Google Search to fetch recent team news, historical results, or odds.
       - **Rule 1 - Contextualize Motivation**: You must explicitly state how each team's current league table position dictates their motivation and likely tactical setup (e.g., desperate for points near relegation vs. comfortable mid-table).
        - **Rule 2 - Evaluate True Fatigue (The Cumulative Fatigue Override / 120-Minute Penalty)**: Do not just state a team is "fatigued." Analyze their `recent_scorelines` history and use Google Search to verify if the underdog played a 120-minute extra-time fixture within the last 7 days. While fatigue often slows down an elite offense, it **catastrophically destroys** a poor defense's concentration and reaction speed late in the game. If a heavy underdog is entering a match following a 120-minute extra-time fixture within the last 7 days, their defensive block will inevitably collapse late in the game due to physical exhaustion. You must heavily downgrade their projected defensive solidity.
       - **Rule 3 - Net Impact of Absences**: Cross-reference Team A's missing attackers against Team B's missing defenders using your Google Search. Explicitly name the available bench/impact players who will be relied upon.
       - **Rule 4 - The Ineptitude Floor**: If a team has a statistically abysmal scoring record (e.g., averaging < 0.8 goals per game or failing to score in multiple recent matches), you MUST NOT predict them to score purely based on narrative concepts like "desperation" or "derby rivalry." Data supersedes narrative. A team missing key attackers cannot magically produce goals.
       - **Rule 4a - The Cross-Competition Data Wall**: When analyzing matches in inter-league tournaments or domestic cups, you are strictly FORBIDDEN from blending domestic league statistics (e.g. goals scored in a weak domestic league) with tournament statistics to justify a Safe Banker. A team averaging 2.5 goals per game in a weaker domestic league does not translate to continental competition against superior opposition. You must isolate and heavily weight the team's specific form within the current competition tier.
       - **Rule 4b - The Step-Up Penalty**: If a team from a lower-coefficient league is playing away against a team from a higher-coefficient league (e.g. Champions League or Europa League), you MUST apply a severe 'Step-Up Penalty' to their offensive metrics. Never trust a domestic flat-track bully to score away in Europe/Continental play. If the data is mixed, pivot to structural game-state markets or declare 'NO BET'.
       - **Competition Isolation & The First Leg Anchor**: Explicitly separate domestic league form from cup/continental form. IF THIS IS A CUP OR CONTINENTAL MATCH, YOU MUST USE GOOGLE SEARCH TO FIND OUT IF THIS IS A 2ND-LEG TIE. If a team is leading on aggregate, they do not need to win; they will play highly conservative, suffocating football. Do not blindly predict the favorite to win if a draw advances them. 
       - **ANTI-HALLUCINATION & TEMPORAL INTEGRITY**: You are STRICTLY FORBIDDEN from inventing historical narratives. Google Search snippets often pull up old articles. If an article mentions a player injury or a match result from years ago, you MUST ignore it.
        - **STRICT ROSTER VERIFICATION (ZERO TOLERANCE)**: You are STRICTLY FORBIDDEN from mentioning players who are NOT in the `Team Squads` lists provided above. For example, if Man City is not playing, you MUST NOT mention Jack Grealish, Haaland, or Alcaraz. If you mention a player for a "Player Prop" or in your "Strategy," verify their name exists in the squad list for that specific team. If they aren't there, THEY ARE HALLUCINATIONS—DELETE THEM IMMEDIATELY.
        - **Player Prop Validation**: In the `Player Props` section, you MUST predict a specific player from the active squad lists (e.g., "Phil Foden over 0.5 Shots on Target"). Do NOT output generic text like "Market Suggestion". If the main strikers are injured, predict the next most likely attacking midfielder or winger who will step up. If NO attacking players are reliable, you MUST pivot to a defensive prop for a specific player, such as "[Defender Name] To Be Booked" or "[Midfielder Name] Over 1.5 Tackles". Never suggest a player who plays for a team NOT involved in this match.
       - **Rule 5 - Regression to the Mean**: If a team is on an extreme streak (e.g., 5+ games without scoring, or a 10-match winless/winning streak), you MUST apply Regression to the Mean logic. The probability of a breakout or reversion increases with each game. Do NOT anchor your prediction to the assumption that an extreme streak will continue indefinitely into this specific match.
       - **Rule 6 - High-Variance Desperation States**: If a team is facing relegation or knockout desperation, they may attempt to abandon defensive structures to chase points. HOWEVER, desperation often leads to frustration and forced errors, not high-quality goals. If they lack the offensive metrics to score, they will simply concede more goals without replying. Do NOT automatically predict BTTS or Over 2.5 just because a team is desperate.
       - **Rule 7 - The "Post-European Hangover"**: For top-tier teams coming off a massive midweek continental fixture (e.g., Champions League), you MUST drastically penalize their domestic away rating. Physical and emotional hangovers highly expose them to energetic underdog disruptions. If Scenario B maps out a frustrated favorite losing to lower-table counters, prioritize low-scoring outcomes like Under 2.5 or Underdog Double Chance (1X/X2).
       - **Rule 8 - The Derby Chaos Directive**: If your Google Search confirms this match is a historic or fierce local derby/rivalry, recognize that Derbies are emotionally charged. While this can sometimes mean goals, it very often means cagey, foul-heavy, and violently defensive 0-0 or 1-0 matches. You MUST analyze the underlying offensive stats: if both teams are missing playmakers, the derby will likely be a low-scoring battle of attrition. Do not force an Over 2.5 prediction purely because it is a derby.
       - **Rule 9 - The Star Player Trap**: Do not overreact to the absence of a famous, aging "star" player (e.g., Radamel Falcao, Lionel Messi). While a big name missing generates news, professional teams often adapt by playing a tighter, more cohesive, and devastating tactical counter-attack system without them. A historic club missing a star striker is NEVER guaranteed to lose. Do NOT automatically downgrade a team just because a famous name is injured.
        - **Rule 10 - The Derby Form Toss (Superclásico Rule)**: If this is a massive historic rivalry, "Superclásico", or a high-stakes Cup Qualifier between two giant clubs in the same country, you MUST heavily discount recent domestic league form (like a 4-0-0 home streak). In one-off emotional bloodbaths, sheer tactical spite and underdog motivation routinely violently override sterile statistical home streaks. Underdogs in these situations are extremely dangerous and often win outright.
        - **Rule 11 - Goal Logic Anchoring**: You MUST NOT predict 'Under' for matches where both teams have a combined expected goals (xG) > 3.0 or where defensive fatigue is 'High'. Conversely, you MUST NOT predict 'Over' if the total xG + historical matchup average is < 2.0. If the tactical data is conflicted, you MUST remain neutral (e.g., "Goal outcome highly variant").
        - **Rule 12 - The Demoralization Catalyst (Blowout Detection)**: If a top-tier Home team (high xG, high possession) faces a bottom-tier opponent with abysmal defensive metrics and high goals-conceded averages, do NOT automatically predict "Under 2.5" just because the Home team is tired or missing a striker. Demoralized underdogs often stop defending entirely after conceding the second goal. In these "Mismatch" scenarios, fatigue is a catalyst for a 4-0 or 5-0 blowout, not a reason for a 1-0 snoozer.
         - **Rule 13 - The Confidence Ceiling (Anti-Inflation Mandate)**: Football is inherently chaotic. You MUST NOT assign a confidence score above **80%** to ANY single-match prediction unless ALL of these conditions are met: (a) the team is 15+ points clear at the top of their league, (b) playing at home, (c) facing a bottom-3 team, AND (d) has zero key injuries. In all other cases, your confidence MUST reflect the realistic upset probability. A "safe" bet in football is 70-78%. Reserve 80%+ for rare, data-proven situations only. **THE EXCEPTION**: If your chosen Banker pick survives BOTH Scenario A AND Scenario B, AND the H2H record shows 10+ consecutive favorable results, you MAY raise confidence to a maximum of **85%**. But NEVER above 85% — football chaos is real. Remember: if your 88% predictions fail 2 out of 3 times, your calibration is broken.
         - **Rule 14 - Elite Club Resilience (The Galactico Factor)**: If a club has won 3+ domestic league titles in the last 10 years (e.g., Real Madrid, Bayern Munich, PSG, Man City, Juventus, Inter Milan), you MUST NOT over-penalize them for missing 2-3 key players. These clubs have world-class squad depth, winning mentality, and tactical adaptability that smaller clubs lack. Missing players should reduce your confidence by 10-15%, NOT 30-40%. History shows elite clubs routinely win "impossible" games with B-squads through sheer institutional excellence. Do NOT treat an injured Real Madrid the same as an injured Heracles.
         - **Rule 15 - Banker Market Priority (The Survival Rule)**: For your `primary_pick` (The Banker), you MUST NOT default to "Match Winner (1X2)" unless the predicted winner wins in BOTH Scenario A AND Scenario B. The 1X2 market has only a ~33% base probability and is one of the RISKIEST markets. Instead, prioritize markets with the highest dual-scenario survival rate. Use this priority ladder for the Banker:
           1. **Tier 1 (Safest)**: Over 0.5 Goals, Double Chance, Team Over 0.5 Goals
           2. **Tier 2 (Safe)**: Over 1.5 Goals, BTTS, Draw No Bet, Asian Handicap (+0.5 or wider)
           3. **Tier 3 (Moderate)**: Over 2.5 Goals, Match Winner, Team Over 1.5 Goals
           You MUST pick from the highest tier where you have 70%+ confidence. Only drop to Tier 3 if the data overwhelmingly supports it across BOTH scenarios. A "Banker" that loses half the time is not a Banker — it is a gamble.
          - **Rule 16 - The Sample Size Safety Valve (Early Season Caution)**: If the current league season has played fewer than 5 rounds (Matchdays 1-4), you MUST NOT strictly enforce "Rule 4 (Ineptitude Floor)". One or two "sterile" games in the opener do NOT establish a trend. If a team dominated possession (60%+) but scored 0 goals in Game 1, they are statistically PRIMED for a breakout in Games 2-4. You MUST apply a **10% Confidence Tax** to any "Under" pick justified solely by a sterile opener. Early season volatility favors the "Over" more than the "Under" as teams find their rhythm.
        - **Rule 17 - THE ANTI-BIAS PROTOCOL (CRITICAL)**: You must actively resist two common analytical biases:
            1. **THE "FIRST-LEG" FALLACY**: Do NOT automatically assume 1st Leg matches will be low-scoring or conservative. Base your Match Goals and 1X2 predictions strictly on the teams' xG and defensive metrics, not on tournament tropes.
            2. **THE "SYSTEM VS. INDIVIDUAL" RULE**: If a superior team (e.g., an away favorite) is missing a star striker, do NOT automatically downgrade them to 'Under' or 'Draw'. If their underlying team system creates high possession and high Big Chances, trust the system to overcome the injury. Do not let Agent 2 panic you into downgrading a fundamentally superior team just because a name is missing from the lineup.
        - **Rule 18 - THE SMALL SAMPLE WEIGHTING DIRECTIVE**: If your analysis relies on a venue-specific metric (like a "home win streak") derived from fewer than 5 matches, you MUST explicitly state in your reasoning: "Venue data is based on a small sample size (N < 5); results have been blended with overall season metrics for reliability." Failing to do so is a statistical error.
        - **Rule 19 - THE EXPECTED GOALS (xG) REALITY CHECK**: You MUST prioritize Expected Goals (xG) over raw goals scored to detect "luck". FIRST, check the 'Advanced Tactical Metrics' JSON block provided above for 'Expected goals (xG) per game'. If the API provided it, use it immediately. If a team's actual goals are much higher than their xG, they are lucky and due for regression. If the xG data is MISSING from the JSON payload (e.g., obscure leagues), you may fallback to your Google Search tool to find recent xG data. If search also fails, default to 'Big chances created' to evaluate their true offensive threat.
        - **Rule 20 - THE SMALL SAMPLE & WOUNDED ANIMAL OVERRIDE**: You are strictly FORBIDDEN from declaring any team's defense an 'absolute fortress' or fully reliable if the current season sample size is fewer than 10 matches. Early-season variance is a massive trap. Furthermore, you must NEVER assume an opposing team's offensive output will drop to zero simply because 1 or 2 starting attackers are injured or suspended. Backup players introduce extreme, unpredictable variance (The Wounded Animal Effect) and often play with a high-intensity point to prove.
        - **THE DATA PURITY MANDATE**: When conducting Live Searches for rosters, injuries, or stats, you MUST ONLY pull data from official, verified sports databases (e.g., Transfermarkt, Soccerway, Flashscore, Sofascore, or official club websites). You are strictly forbidden from citing data from gaming wikis (SOFIFA, Football Manager), Reddit career mode threads, or fan-concept sites.


       Do not just give a flat prediction. You MUST simulate conditional timelines based on who controls the game script.
       - **Scenario A (The Expected Script)**: If the pre-match favorite (Home or Away) scores first within 30 minutes, how does the opponent historically respond? Do they have the tactical discipline to avoid a blowout, or do they collapse?
       - **Scenario B (The Underdog Disruption)**: If the underdog (Home or Away) scores first against the run of play, what happens? Does the favorite have the attacking metrics to break down a low block, or do they leave themselves vulnerable to devastating counter-attacks?
       - **Scenario C (The Red Card Disruption)**: If the match favorite (or the team your primary pick favors) receives a red card before the 60th minute, detail exactly how they will alter their tactical formation (e.g., dropping into a deep low block). State exactly how this will impact the 'Total Corners' market for the 11-man team and whether the 'Match Goals' market will explode (due to defensive collapse) or freeze (due to defensive stubbornness).
    
    4. **Analyze the following 17 Core Betting Markets**:
       - **Match Winner (1X2)**: Home, Draw, or Away?
       - **Match Total Goals**: Over/Under 2.5?
       - **BTTS**: Both Teams To Score (Yes/No)?
       - **Team Total Goals**: e.g. Home Over 1.5, Away Under 0.5.
       - **Double Chance**: 1X, X2, or 12.
       - **Draw No Bet (DNB)**: Home or Away (moneyback on draw).
       - **Asian Handicap**: e.g. Home -0.5, Away +1.5.
       - **First Half Goals**: Over/Under 0.5 or 1.5.
       - **Second Half Goals**: Over/Under 0.5 or 1.5.
       - **HT/FT**: Half Time/Full Time result.
       - **Correct Score**: Exact final score prediction.
       - **Team Exact Goals**: Exact number of goals scored by Home or Away team.
       - **Total Match Corners**: Over/Under based on tactical matchups & possession.
       - **Total Match Cards**: Over/Under based on motivation, fouls, and derby intensity.
       - **Highest Scoring Half**: 1st Half, 2nd Half, or Tie.
       - **10 Minute Draw**: Prediction on whether the match will realistically be a draw at the 10:00 minute mark (Yes/No).
       - **Player Props**: e.g. Anytime Goalscorer, Shots on Target for specific players.
    
    5. **Mathematical Synthesis**:
       - Weigh probabilities of ALL 17 markets against each other.
       - **Cross-Reference**:
         - *The Fortress Effect*: Strongly factor in the isolated home vs away form. 
         - *CRITICAL NEWS IMPACT*: If Google Search reveals a Top Goalscorer, Star Player, or Captain is missing/injured or recently left the club in a transfer, you MUST drastically reduce the confidence of goal-heavy markets.
    
    6. **Chain-of-Thought Process**: Before declaring any predictions, you MUST think step-by-step. 
       - FIRST: If you have Google Search access, explicitly search for: "confirmed injuries, suspended players, and official starting lineups for {team_a} vs {team_b} today". Do NOT search for transfer rumors.
       - SECOND: For the 'Total Match Cards' market, check the "referee" field in the metadata. If a referee name is provided, use your Google Search tool to find that specific referee's historical average cards per game. If no referee is in the metadata, search for who is assigned. This is MANDATORY for accurate card predictions.
       - THIRD: Check the "tournament" and "round" fields in the metadata. Use this to assess match importance (e.g., Cup Final vs. early round, relegation battle vs. mid-table). Factor motivation into all markets.
       - FOURTH: Analyze the offensive stats vs defensive stats, xG, and Fatigue.
    
    7. **Select the Dual Expert Tips (DETERMINISTIC SELECTION)**:
       - **RESTRICTION**: You are STRICTLY FORBIDDEN from inventing or using outside betting markets (e.g., "Win to Nil", "Team to Score in Both Halves", "Player to Score 2+"). Both your Primary and Alternative picks MUST be selected directly from the 17 core markets you analyzed above.
       - **Primary Pick (The Banker)**: Must be the absolute SAFEST mathematical bet from the 17 core markets. You MUST select the single market that has the highest mathematical probability of winning. If the data screams 'Over 1.5 Goals' or 'BTTS: Yes' as the safest possible outcome over 'Double Chance', you must choose that. Act as a pure quantitative expert finding the most undeniable edge.
       - **Alternative Pick**: Must be a VALUE bet from the 17 core markets. Find a market that offers a significantly higher ROI (higher odds) but is still heavily supported by the statistics and scenario analysis. NO "Win to Nil".
        - **ODDS EXTRACTION**: You MUST provide the realistic Decimal Odds for both picks. If you have the Odds API payload, use those exact numbers. If the payload is empty, you MUST use your Google Search to find the real market odds for ALL 17 categories below. If search also fails, estimate the exact decimal odds based on implied probability.
    
    ### Output Format
    CRITICAL: Ensure your JSON structure is perfectly valid and contains ZERO trailing commas at the end of objects or lists.
    Return ONLY valid JSON with this exact structure:
    {{
        "step_by_step_reasoning": "Sentence 1 MUST state exactly who is injured/missing/transferred from the starting lineups based on your search. Sentence 2 MUST state how this changes your confidence. Then write your normal thought process.",
        "scenario_analysis": {{
            "scenario_a_expected_script": "Detailed projection of what happens if the favorite/home team scores first and controls possession.",
            "scenario_b_underdog_disruption": "Detailed projection of what happens if the underdog/away team scores first and forces the favorite to chase the game.",
            "scenario_c_red_card_disruption": "Detailed simulation of the favorite receiving a red card, tactical shifts, corner impacts for the opponent, and goal market projections."
        }},
        "match": "{team_a} vs {team_b}",
        "full_analysis": {{
            "1X2": {{"prediction": "[Home/Draw/Away]", "odds": 1.95, "reasoning": "..."}},
            "Match_Goals": {{"prediction": "[Over/Under 2.5]", "odds": 1.80, "reasoning": "..."}},
            "BTTS": {{"prediction": "[Yes/No]", "odds": 1.70, "reasoning": "..."}},
            "Team_Goals": {{"prediction": "[Team + O/U]", "odds": 1.65, "reasoning": "..."}},
            "Double_Chance": {{"prediction": "[1X/X2/12]", "odds": 1.35, "reasoning": "..."}},
            "DNB": {{"prediction": "[Home/Away]", "odds": 1.55, "reasoning": "..."}},
            "Asian_Handicap": {{"prediction": "[Pick]", "odds": 1.90, "reasoning": "..."}},
            "First_Half_Goals": {{"prediction": "[O/U]", "odds": 1.45, "reasoning": "..."}},
            "Second_Half_Goals": {{"prediction": "[O/U]", "odds": 1.25, "reasoning": "..."}},
            "HT_FT": {{"prediction": "[Pick]", "odds": 4.50, "reasoning": "..."}},
            "Correct_Score": {{"prediction": "[Score]", "odds": 12.0, "reasoning": "..."}},
            "Team_Exact_Goals": {{"prediction": "[Team + Exact]", "odds": 3.20, "reasoning": "..."}},
            "Total_Corners": {{"prediction": "[O/U]", "odds": 1.85, "reasoning": "..."}},
            "Total_Cards": {{"prediction": "[O/U]", "odds": 1.85, "reasoning": "..."}},
            "Highest_Scoring_Half": {{"prediction": "[1H/2H/Tie]", "odds": 2.10, "reasoning": "..."}},
            "10_Minute_Draw": {{"prediction": "[Yes/No]", "odds": 1.20, "reasoning": "..."}},
            "Player_Props": {{"prediction": "[Player Bet]", "odds": 2.50, "reasoning": "..."}}
        }},
        "primary_pick": {{
            "tip": "The Safest Banker Prediction",
            "confidence": 85,
            "odds": 1.45
        }},
        "alternative_pick": {{
            "tip": "The Higher ROI Value Prediction",
            "confidence": 65,
            "odds": 2.10
        }},
        "reasoning": ["point 1", "point 2", "point 3"]
    }}
    """
    try:
        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise ValueError("API Key is missing")
            
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{get_active_model()}:generateContent?key={api_key}"
        
        # Blind Backtest Mode: prepend date-bound search protocol header so the LLM
        # never retrieves post-match reports. Normal predictions are unaffected.
        if is_historical:
            blind_backtest_header = f"""    ⚠️ BLIND BACKTEST MODE — ACTIVE ⚠️
    You are analysing a HISTORICAL match for validation and backtesting purposes.
    The match has already been played, but you MUST NOT discover or use the final result.

    MANDATORY SEARCH PROTOCOL (violations invalidate this backtest):
    1. You MUST append the operator before:{before_date} to EVERY search query you execute.
    2. You MUST include at least one of these terms in every query: "preview", "predicted lineup", "injury news", "team news", "pre-match", "form guide".
    3. You are STRICTLY FORBIDDEN from searching bare team names alone. Every query MUST include pre-match terms AND the before:{before_date} operator.
    4. If a query does not contain before:{before_date}, DO NOT execute it — reformulate it first.
    5. You are STRICTLY FORBIDDEN from referencing, using, or incorporating the final score, match result, half-time score, or any in-game statistics from this fixture.

    Your goal: produce a full pre-match prediction exactly as if the match has not yet been played.
    ---

"""
            prompt = blind_backtest_header + prompt

        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.0,
                "responseMimeType": "application/json"
            }
        }

        payload["tools"] = [{"google_search": {}}]
        if is_historical:
            print(f"🔍 [Agent 1] Blind Backtest Mode: Search enabled with before:{before_date} date constraints for {team_a} vs {team_b}")

        print(f"🧠 [Agent 1] Generating analysis for {team_a} vs {team_b} (Searching web if future match)...")
        request_start = get_now_wat()
        
        max_retries = 3
        for attempt in range(max_retries):
            check_cancelled(match_id)
            try:
                # Add timeout and retry logic to gracefully handle RemoteDisconnected drops
                # Increased to 600s for heavy Google Search grounding
                response = requests.post(url, headers={'Content-Type': 'application/json'}, json=payload, timeout=600)
                response.raise_for_status()
                break
            except requests.exceptions.RequestException as e:
                if attempt < max_retries - 1:
                    import time
                    print(f"⚠️ Network Error during API call. Retrying {attempt + 1}/{max_retries} in 5s ...")
                    time.sleep(5)
                else:
                    raise
                    
        request_end = get_now_wat()
        print(f"✅ [Agent 1] Analysis finished in {(request_end - request_start).total_seconds():.2f}s")
        
        # When using search grounding, the response might have multiple parts
        data = response.json()
        candidates = data.get('candidates', [])
        if not candidates:
            raise ValueError("No candidates returned")
            
        parts = candidates[0].get('content', {}).get('parts', [])
        
        text_content = ""
        for part in parts:
            if 'text' in part:
                text_content += part['text']
                
        # Proactively clean trailing commas introduced by LLM hallucinations before parsing
        text_content = re.sub(r',\s*}', '}', text_content)
        text_content = re.sub(r',\s*\]', ']', text_content)
                
        parsed = json.loads(text_content)
        if isinstance(parsed, list) and len(parsed) > 0:
            return parsed[0]
        return parsed
    except Exception as e:
        safe_error = re.sub(r'key=[^&\s]+', 'key=[REDACTED]', str(e))
        print(f"Gemini API Error in predict_match: {safe_error}")
        try:
             print(f"Raw Response: {response.text}")
        except:
             pass
        return {
            "error": safe_error,
            "match": f"{team_a} vs {team_b}",
            "primary_pick": {"tip": "Analysis Failed", "confidence": 0},
            "alternative_pick": {"tip": "Analysis Failed", "confidence": 0}
        }

def needs_fact_checking(agent_1_prediction: dict) -> bool:
    """
    Determine if Agent 2 needs Google Search capabilities for fact-checking.
    Only enable search when Agent 1 makes specific factual claims that need verification.

    Returns:
        bool: True if search is needed, False for quick review mode
    """
    # Extract reasoning text from Agent 1's analysis
    reasoning_text = ""
    reasoning_text += agent_1_prediction.get("step_by_step_reasoning", "")
    reasoning_text += " ".join(agent_1_prediction.get("reasoning", []))

    # Extract scenario analysis text
    scenario_analysis = agent_1_prediction.get("scenario_analysis", {})
    if isinstance(scenario_analysis, dict):
        reasoning_text += str(scenario_analysis.get("scenario_a_expected_script", ""))
        reasoning_text += str(scenario_analysis.get("scenario_b_underdog_disruption", ""))
        reasoning_text += str(scenario_analysis.get("scenario_c_red_card_disruption", ""))

    reasoning_lower = reasoning_text.lower()

    # Triggers that require fact-checking via search
    search_triggers = [
        "recently transferred",
        "just signed",
        "new signing",
        "injury news",
        "injured",
        "suspended for this match",
        "suspended",
        "missing due to",
        "ruled out",
        "confirmed out",
        "historical h2h",
        "last meeting",
        "previous encounter",
        "derby",
        "rivalry",
        "cup final",
        "knockout",
        "must-win",
        "referee",
        "red card history",
        "lineup confirmed"
    ]

    # Check if any search trigger is present
    needs_search = any(trigger in reasoning_lower for trigger in search_triggers)

    # Also check confidence level - if Agent 1 is very confident (>85%), might need validation
    primary_pick = agent_1_prediction.get("primary_pick", {})
    if isinstance(primary_pick, dict):
        confidence = primary_pick.get("confidence", 0)
        if confidence > 85:
            needs_search = True  # High confidence claims should be fact-checked

    return needs_search

def risk_manager_review(initial_prediction_json: dict, match_date: str = None, match_id: int = None, job_id: str = None) -> dict:
    """
    Second agent in the Multi-Agent Loop. Acts as a strict Risk Manager to verify
    the safety of the initial prediction.
    """
    check_cancelled(match_id, job_id)
    # Harden against list-wrapped JSON from Agent 1
    if isinstance(initial_prediction_json, list) and len(initial_prediction_json) > 0:
        initial_prediction_json = initial_prediction_json[0]

    if "error" in initial_prediction_json:
        print("⚠️ [Agent 2] Skipping Risk Review: Primary Agent failed with an API error.")
        return initial_prediction_json

    prompt = f"""
    Act as a strict, mathematically-driven Sports Betting Risk Manager.
    Your job is to review the following initial AI prediction's two picks (`primary_pick` and `alternative_pick`) to evaluate if they are truly safe and viable.
    
    ### Initial Prediction & Primary Agent's Notes
    {json.dumps(initial_prediction_json, indent=2)}
    
    ### RISK MANAGEMENT RULES

    ⚠️ **CRITICAL: SUPREME COURT VETO AWARENESS**
    Your downgrades will be reviewed by the Supreme Court (Agent 3), which has VETO AUTHORITY over certain rules.
    Before applying high-variance rules (Mutual Collapse, Glass Cannon, etc.), you MUST check Dead Engine status:
    - If EITHER team has < 0.8 goals/game AND < 1.5 big chances/game → Dead Engine ACTIVE
    - Dead Engine VETOES: Rule 19 (Mutual Collapse), Rule 20 (Dam Break), Rule 24 (Glass Cannon)
    - If Dead Engine active: DO NOT downgrade to Over/BTTS picks, use Under 3.5 or Match Control instead

    This prevents your pick from being overturned by Supreme Court, creating user confusion.

    1. **Catching the "Human Bias"**: Identify any widespread public narratives about this match (e.g., "The Home Team is unbeatable at home" or "They drew 0-0 last match so it will be low scoring again"). Cross-reference this bias with the underlying defensive/offensive data. If the public expectation contradicts the deep data, aggressive bet sizing against the public is warranted.

    2. **Catching the "Gambler's Fallacy"**: Do not assume extreme streaks (e.g., 5 games without scoring) will continue indefinitely; enforce Regression to the Mean when probabilistically appropriate.

    3. **Small Sample Size Audit**: If Agent 1 cites a "perfect home record" or "leaky away defense" based on fewer than 5 games, you MUST discount the weight of that claim. If the overall season stats contradict the small home/away sample, you MUST prioritize the larger dataset and potentially downgrade or overrule the pick if it is too risky.

    4. **The "Squad Depth" & Ineptitude Audit**: If the primary agent justified an aggressive 'Over 2.5' or 'BTTS: Yes' pick but a top scorer is missing, perform a **Squad Depth Check**. Search for the backup striker's current form or the team's goals-per-game without that star player. If depth is confirmed, you may approve the pick with a minor confidence penalty. If no depth exists and the team averages < 0.8 goals/game, you MUST downgrade to a safer Under/Conservative market.

    5. **The "Derby Caution Directive"**: If the primary agent upgraded a goal market purely because it is a "Derby", exercise extreme caution. Derbies are notoriously tight, card-heavy, defensive struggles. If the baseline data points to a low-scoring match, OVERRULE the agent's derby narrative and reinstate the mathematically sound Under/Conservative pick.

    6. **Scrutinize the `primary_pick` (The Banker)**: Is it truly the safest mathematical edge among all 17 markets? 
       - **SCENARIO CHECK**: Read the `scenario_analysis` block provided by the primary agent. The primary pick might be 'Match Winner', 'Over 1.5', 'BTTS', etc. Whatever it is, if it completely fails in **Scenario B (Underdog Disruption)** OR **Scenario C (Red Card Disruption)**, it is NOT a safe banker. Downgrade it to a safer, more resilient market (e.g. pivoting from 'Match Winner' to 'Double Chance' or 'Draw No Bet').
       - **HONOR INJURY NEWS**: If the primary agent chose a goal-dependent market (Over 2.5, BTTS) but discovered injuries to top strikers, you MUST downgrade the pick. Do not ignore structural problems just because of a narrative.
       - **CRITICAL INSTRUCTION - CONFLICT RESOLUTION**: Before finalizing your analysis, cross-reference all statistics you are about to output. Your final narrative must be logically consistent. If you downgrade the tip to an "Under" market, ensure the text explicitly cites the data (e.g., missing players or low expected goals).
       - **CRITICAL**: If you downgrade the tip, you MUST choose the absolute safest option from the OTHER 11 MARKETS already analyzed in the `full_analysis` section that better survives both Scenarios.
        - **THE HEDGING MANDATE (Anti-0-0 Shield)**: If the primary agent's pick is a goal market (Over 2.5, BTTS: Yes, Team Over 1.5), you MUST explicitly calculate the probability of a 0-0 or 1-0 result using the defensive metrics, clean sheet percentages, and "Goals per game" stats from both teams. If the low-scoring probability (Under 1.5 goals) exceeds **15%**, you MUST downgrade to a safer floor: Over 2.5 -> Over 1.5, BTTS -> Team Over 0.5. Never recommend Over 2.5 as a "Banker" unless both teams average 1.5+ goals per game AND have fewer than 3 clean sheets each in their last 10.
        
    7. **Early Season Sample Size Audit**: You MUST identify if the primary agent is over-correcting based on Matchday 1 or 2 results. If the agent justifies an 'Under 2.5' or 'No BTTS' pick solely because "Team X failed to score in their opener", you MUST challenge this as **Sample Size Bias**. If Team X had high possession/xG in that opener, they are likely to regress (breakout) in this match. Downgrade any Under 2.5 pick to Under 3.5 or Double Chance if the reasoning relies on a single-game "sterile" performance during the first 4 rounds of the season.
       
    8. **THE HALLUCINATION PENALTY (CRITICAL)**: If your Google Search reveals that your colleague (Agent 1) has hallucinated a player who is NOT in the squad or mentioned a stat that is provably false, you MUST automatically:
       - Reduce the `confidence` of the primary pick by at least **20%**.
       - If the hallucinated player was used to justify a goal-scoring market (e.g., "Gu00fcndogan/Osimhen will score"), you MUST DOWNGRADE that market (e.g., BTTS -> Team Over 0.5 or No Bet).
       - A hallucination is a sign of a flawed tactical model; do not ignore it just because the "firepower" is still high.

    9. **THE DERBY LOCKDOWN**: If the match is a high-intensity derby (e.g., Istanbul Derby, North London Derby, El Clasico):
       - Goal-scoring markets (BTTS: Yes, Over 2.5) should be judged with **Extreme Skepticism**.
       - Search for the last 3 H2H results. If at least TWO were low-scoring (Under 2.5), you MUST overrule any 'Over 2.5' or 'BTTS: Yes' recommendation to a more conservative market (Under 3.5, Over 1.5, or Team Under).
       - Derbies are about tactical shutdowns and cards, not always goals.

    10. **THE ANTI-BIAS PROTOCOL (MANDATORY)**:
       - **ANTI-FIRST-LEG BIAS**: Do not downgrade goal markets purely because it is a "First Leg" and "both teams will be cautious." If the xG and defensive consolidation metrics for both teams exceed 2.5 combined goals, you MUST approve or recommend the Over. Data overrides the trope.
       - **SYSTEM OVER INDIVUDAL**: If a top-tier team (Real Madrid, Bayern, etc.) is missing their main striker, but their midfield provides 80%+ pass accuracy and high shot volume, do NOT downgrade their goal markets. The system outlives the individual.
    11. **THE DEFENSIVE COLLAPSE OVERRIDE**: The 'System vs. Individual' rule applies strictly to offensive injuries. If a team is missing 2 or more starting defenders or their starting Goalkeeper, you MUST heavily penalize their defensive integrity. A broken defensive line destroys a tactical system. You must not blindly trust a team's offensive system to outscore opponents if their defensive foundation is verified as collapsed.
    12. **THE HALLUCINATION CONTEXT RULE**: When applying the Hallucination Penalty (Rule 8), evaluate the context of the correction. If Agent 1 hallucinates that a star player is injured/suspended, but your live search proves the player is actually ELIGIBLE and PLAYING, do NOT downgrade the team's prediction. The team is actually stronger than Agent 1 calculated. Only apply the penalty and downgrade the bet if the fact-check proves the team is materially weaker than claimed.

    13. **THE CROSS-COMPETITION DATA WALL**: You MUST audit Agent 1 for "Stat-Padding Bias." If Agent 1 justifies an "Over" or "Match Winner" pick for a team from a significantly weaker league playing in a continental tournament solely based on their high domestic scoring average, you MUST overrule or downgrade the pick. Apply the **Step-Up Penalty** yourself. Football is tiered; a dominant domestic form in a lower-coefficient league (e.g., scoring 3.0 goals/game) is often irrelevant in a cross-border clash against a higher-coefficient opponent. Force the prediction to focus strictly on competition-specific form or structural markets (Under Goals/Draw No Bet).

    14. **THE CUMULATIVE FATIGUE OVERRIDE (THE 120-MINUTE PENALTY)**: If a heavy underdog is entering a match following a 120-minute extra-time fixture within the last 7 days, their defensive block will inevitably collapse late in the game due to physical exhaustion. You are strictly FORBIDDEN from relying on their defensive metrics to justify an 'Under' Match Goals banker, a positive Asian Handicap, or a low-scoring game script. You must heavily upgrade the superior opponent's offensive ceiling, specifically targeting 2nd-half goals, team totals, or high-variance goal markets to capitalize on the underdog's inevitable late-game physical collapse. If no safe offensive market exists, declare 'NO BET'.

    15. **THE SMALL SAMPLE & WOUNDED ANIMAL OVERRIDE**: If a match features a heavy favorite relying on a small-sample-size defense (under 10 games) facing an underdog with key attacking suspensions, you must immediately ABANDON all team-based Banker markets (Match Winner, 1X2, Double Chance) that rely on a clean sheet. You must pivot your Safe Banker to wide-margin, structural goal totals (e.g., Over 1.5 Goals or Under 3.5 Goals) to absorb the unpredictable variance of backup players playing with a point to prove.

    16. **THE STERILE POSSESSION PROTOCOL (THE 1-0 CHOKEHOLD)**: If Agent 1's tactical script describes a game state where a heavily favored possession team (60%+ average possession) is facing a severely fatigued OR offensively sterile underdog (< 1.0 goals per game), you MUST audit any 'Over Goals' markets (Over 2.5, BTTS: Yes) with EXTREME SKEPTICISM. Elite possession teams use the ball as a defensive weapon. If they score early, the game devolves into a 'Sterile Possession Exercise' with zero urgency. You are STRICTLY FORBIDDEN from approving Over 2.5 Goals or BTTS: Yes as the primary banker in this scenario. You MUST downgrade to Match Control markets (1X, Home Win) if the favorite has a reliable defense (< 1.0 goals conceded per game), OR pivot to wide-margin Under ceilings (Under 3.5 / Under 4.5 Goals) to absorb the slow, clock-killing game script. If Agent 1's reasoning explicitly mentions "possession dominance," "low pressing from underdog," "control without urgency," or if the H2H history shows consecutive 1-0 or 0-0 results, this rule MUST be activated.

    17. **THE ASYMMETRIC FATIGUE PROTOCOL (THE EARLY KILL TRAP)**: If Agent 1 flags the HOME FAVORITE for 'Fatigue' (midweek European match, 120-minute match in last 7 days, congested fixture schedule) but the opponent is a vastly inferior underdog (bottom 25% of table, concedes >= 1.5 goals per game, OR recent defeats by 2+ goal margins), you MUST audit any Match Goals 'Under' markets (Under 2.5, Under 3.5) with EXTREME SKEPTICISM. Superior teams dealing with fatigue do NOT play slow football against bad teams—they execute an 'Early Kill Strategy,' scoring 2-3 goals in the first 40 minutes to secure the game early, then coasting in the second half. You are STRICTLY FORBIDDEN from approving Under 2.5 or Under 3.5 Match Goals as the primary banker when there is a massive class disparity. Instead, you MUST pivot to: (1) Away Team Under 0.5/1.5 Goals (isolate the underdog's ineptitude), (2) Home Win, (3) Home Team Over 1.5 Goals, or (4) Asian Handicap -1.5/-2.0. Do NOT cap the favorite's goal ceiling—target the underdog's weakness. This rule OVERRIDES Rule 14 (Cumulative Fatigue Override) when the FAVORITE is fatigued but facing relegation fodder. The goals will come early, not late.

    18. **THE HOME BUZZSAW OVERRIDE (THE AWAY FAVORITE TRAP)**: If Agent 1 identifies the Home Underdog as a high-scoring threat (averaging > 1.3 goals per game this season, OR recently scoring multiple goals against elite opposition), you MUST immediately audit any Away Team Asian Handicap (Away +1.0, Away +1.5) or Away Double Chance (X2) that Agent 1 selected as the Safe Banker. These markets are FORBIDDEN when the Home Buzzsaw is active. The blowout risk is real: an away favorite who falls behind a potent home underdog will push forward to equalize, exposing their defensive line to devastating counter-attacks — turning a projected 2-1 defeat into a 3-1 or 4-1 blowout. You MUST downgrade any Away Match Control market and force a pivot to: 'Home Over 0.5 Goals', 'Home +2.5 Asian Handicap', or 'Over 1.5 Match Goals'. Additionally, you MUST completely disregard any H2H win streak the away team holds — current offensive potency of the home team overrides all historical H2H data.

    19. **THE MUTUAL COLLAPSE EXEMPTION AUDIT**: If Agent 1's data reveals BOTH teams are missing critical defensive personnel (starting center-backs or starting goalkeeper) OR both teams concede > 1.8 goals per game, you MUST flag the Mutual Collapse as ACTIVE and audit any 'Under Goals' market Agent 1 selected. These markets are FORBIDDEN under a mutual collapse. You MUST downgrade to chaos/volume markets: 'BTTS: Yes', 'Over 4.5 Cards', or 'Over 8.5 Corners'. This rule overrides Sterile Offense and Clinical Ineptitude entirely — poor finishing stats cannot survive a match with zero defensive resistance on either side. IMPORTANT: This rule is DISTINCT from the Mud Fight Trigger. The Mud Fight fires when one team has a broken defense AND the other has a broken offense (missing supply line with no depth) → NO_BET. Rule 19 fires when BOTH defensive structures are broken simultaneously, producing high-volume end-to-end chaos that is exploitable via volume markets — do NOT invoke a NO_BET under Rule 19.

    20. **THE DAM BREAK EXEMPTION AUDIT**: If Agent 1 flags a team for Clinical Ineptitude (high Big Chance Miss Rate 80%+) BUT simultaneously reports that team is creating > 2.0 Big Chances per game OR double-digit Big Chances in recent matches, you MUST activate the Dam Break Exemption and REJECT any 'Under 2.5' or 'Under 3.5' Safe Banker. High chance volume is evidence of elite offensive quality — the miss rate is temporary negative variance, not structural ineptitude. You MUST downgrade the Under pick and force a pivot to: 'Home Win', 'Home -1.0 Asian Handicap', or 'Over 1.5 Team Goals' to capture the inevitable positive regression.

    21. **THE DEAD ENGINE VETO AUDIT**: Before approving any 'BTTS: Yes', 'Over 2.5', or 'Over 3.5' market justified by RULE 19 (Mutual Collapse) activation, you MUST run the Dead Engine Check. If ANY team in the match averages < 0.8 goals per game AND creates < 1.5 Big Chances per game, the Dead Engine Veto is active and RULE 19 is immediately suspended. You MUST REJECT or DOWNGRADE any volume market (BTTS: Yes, Over 2.5, Over 3.5) that relies on both teams attacking freely — a broken defense is only exploitable if the opponent has a functioning engine. A Dead Engine cannot produce a transition shootout. THE PIVOT: Downgrade to 'Under 3.5 Goals', 'Match Winner + Under 4.5', or 'Double Chance + Under 3.5' favoring the functional team.

    22. **THE H2H OBSESSION TRAP AUDIT**: If Agent 1's data shows historical H2H records (e.g., consecutive 0-0s, low-scoring Derby results) were used to justify an 'Under Goals' market, you MUST immediately check current season form. If BOTH teams currently average > 1.0 goals per game (scored OR conceded), the Current Form Supremacy trigger is ACTIVE. You MUST REJECT or DOWNGRADE any 'Under 2.5' or 'Under 3.5' Safe Banker justified purely by H2H history or Derby/Rivalry narratives. Current defensive metrics are demonstrably poor — historical H2H data cannot override live, current-season evidence. PIVOT: Downgrade to 'Over 1.5 Goals' or 'BTTS: Yes', treating the H2H record as statistically irrelevant.
    
    23. **THE PLAYOFF PARALYSIS AUDIT (HIGH-STAKES FEAR OVERRIDE)**: If Agent 1's analysis identifies the match as a high-stakes fixture — a Cup Final, a Knockout Match, a late-stage UEFA/Continental Qualifier, or a relegation survival decider — you MUST immediately audit any high-goal or BTTS market Agent 1 selected. These markets are STRICTLY FORBIDDEN when the Playoff Paralysis trigger is active. THE TACTICAL REALITY: Fear of losing overrides statistical offensive averages in knockout football. If a key defender or goalkeeper is missing, the manager OVERCOMPENSATES with a hyper-conservative low-block — the match devolves into a 0-0 or 1-0 grind, NOT a chaotic shootout. RULE VETO: This rule STRICTLY VETOES RULE 19 (Mutual Collapse Audit) — missing defenders in a Cup Final do NOT create a shootout. THE FORBIDDEN ACTION: You MUST REJECT or DOWNGRADE 'Over 2.5 Goals', 'Over 3.5 Goals', or 'BTTS: Yes' if they are the primary banker in a verified high-stakes match. THE PIVOT: Force Agent 1's pick to survival markets — wide Match Control (e.g., '1X' for the stronger home side) or a massive ceiling (e.g., 'Under 3.5 Goals'). Flag the downgrade explicitly in your step_by_step_reasoning.

    24. **THE GLASS CANNON AUDIT (BROKEN FAVORITE VETO)**: If Agent 1 identifies a Heavy Favorite (dominant odds, superior talent) BUT simultaneously flags them for Defensive Collapse (missing key CB, GK, or defensive captain), AND the Underdog has a functional offense (Dead Engine is INACTIVE for the underdog), you MUST immediately audit any Match Winner (1X2) or negative Asian Handicap pick Agent 1 used as the Safe Banker. These markets are STRICTLY FORBIDDEN when the Glass Cannon is active. THE TACTICAL REALITY: A heavy favorite with a broken defense will dominate possession but concede from underdog counter-attacks — frequently resulting in 1-1 or 2-2 draws. THE FORBIDDEN ACTION: You MUST REJECT or DOWNGRADE any Match Winner (1X2) or negative Asian Handicap (-1.0, -1.5) on the Favorite as the primary banker. THE PIVOT: Force the Safe Banker to structural goal floors: 'Over 1.5 Match Goals' or 'BTTS: Yes'. Flag the downgrade with is_downgraded: true.

    25. **THE EXHIBITION VOID AUDIT (FRIENDLY MATCH WIPE)**: If Agent 1's analysis identifies the match as a Non-Competitive Fixture — a Club Friendly, a U21/U19 International Friendly, or a pre-season exhibition — you MUST immediately wipe any Match Control market Agent 1 selected as the Safe Banker. RULE VETO: This rule STRICTLY VETOES Agent 1's Home Buzzsaw rule — these rules were built on competitive match data and CANNOT be applied in friendly exhibitions. THE FORBIDDEN ACTION: You MUST REJECT any Match Control market (Match Winner 1X2, Double Chance, Draw No Bet, Asian Handicap) as the primary banker if the Exhibition Void is active. THE PIVOT: Force the Safe Banker to purely structural goal floors: 'Under 3.5 Goals', '1st Half Under 1.5 Goals', or — if both teams have elite offensive squad depth — 'Over 1.5 Match Goals'. Flag all downgraded markets explicitly.
    
    26. **THE UNCERTAINTY CEILING AUDIT (DEFENSIVE APATHY)**: If Agent 1 selects an 'Under Goals' market (Under 2.5, Under 3.5) for a match flagged as an Exhibition/Friendly OR involving a 'Dead Engine' that ALSO concedes >1.3 goals/game, you MUST activate the Defensive Apathy trigger. THE TACTICAL REALITY: Apathy breeds goals. Without competitive pressure, defensive structures collapse and second-half mass substitutions destroy tactical discipline. THE FORBIDDEN ACTION: You MUST REJECT any 'Under' market used as a Safe Banker in these scenarios. You cannot cap a game that has no defensive floor. THE PIVOT: Downgrade the pick and force a pivot to: 'Over 1.5 Match Goals', 'Favorite Over 1.5 Team Goals', or wide Match Control ('1X'). Flag the downgrade with is_downgraded: true.

    27. **THE BORDERLINE SURVIVAL VETO (ACCUMULATOR PROTECTION)**: Before approving Agent 1's Safe Banker pick, you MUST pre-emptively assess its likely Monte Carlo survival rate based on the combined xG and variance characteristics. If the match has ANY of these red flags, the pick is TOO RISKY for an 8+ leg accumulator even if it's technically "safe":

        **BORDERLINE RED FLAGS (82-85% Survival Zone - NOT SAFE ENOUGH):**
        - Combined xG between 2.5-3.0 with variance > 1.2 (chaos spreads probability too thin)
        - Missing 2+ starting defenders but opponent is NOT a Dead Engine
        - Rule 42 (Glass Cannon) or Rule 62 (Nothing to Lose) active (defensive variance too high)
        - Top scoreline probability < 10% (probability too diffused across scorelines)
        - Over 1.5 pick where 0-0 is the highest individual scoreline (borderline cumulative edge)

        **THE FORBIDDEN ACTION:** If 2+ red flags are present, you MUST immediately downgrade to a SAFER market:
        - Over 1.5 → Over 0.5 (rock-solid floor)
        - Over 2.5 → Over 1.5 (one-level downgrade)
        - BTTS: Yes → Over 1.5 or Match Control (eliminate double-condition risk)
        - Match Winner → Double Chance or Draw No Bet (eliminate single-outcome risk)

        **THE PIVOT MANDATE:** Your Safe Banker MUST target 85%+ survival for 8-leg accumulators. If Agent 1 picked a 82-84% survival market, that is a MEDIUM RISK pick, NOT a Safe Banker. Downgrade it or recommend it ONLY as a standalone/value bet, NOT for the accumulator. Flag with: "⚠️ BORDERLINE SURVIVAL: Downgraded for accumulator safety."

    28. **Scrutinize the `alternative_pick` (The Value Bet)**: Is it completely reckless?
       - A value bet can be risky, but it must be backed by the data timeline. If it predicts an Away win, ensure "Scenario A" doesn't completely wipe them out in the first 15 minutes.

    29. **Update the JSON**:
       - Rewrite the `primary_pick` and `alternative_pick` objects with your final approved tips.
       - **STRICT HARMONIZATION**: The exact text inside `primary_pick["tip"]` and `alternative_pick["tip"]` MUST perfectly match the prediction part of one of the items inside your `full_analysis` grid.
       - **NO BRACKETS IN TIP**: The `tip` string MUST be short and punchy (e.g., "Hamburger SV Over 0.5 Goals" or "Draw No Bet: Home"). You are STRICTLY FORBIDDEN from including `[Reasoning...]` text or brackets inside the `tip` string itself. Put all reasoning in the `reasoning` array or `step_by_step_reasoning`.
       - **GRID OVERWRITE**: If you downgraded a tip to be more defensive, you MUST completely overwrite the `full_analysis` grid to perfectly harmonize with your new defensive logic (e.g., updating Asian Handicap to tighter spreads, Correct Score to a low sum, BTTS to No). DO NOT leave contradictory high-scoring alternative markets if you predicted a defensive stalemate.
       - **FACT-CHECKING DIRECTIVE**: Your colleague is not infallible. You have Live Google Search access! Whenever you review a major claim (such as a key player injury, a massive historical win streak, or team lineups), actively use your Search Tool to fact-check your colleague's data before downgrading or approving the bet. If your search proves your colleague lied, explicitly call them out in your step_by_step_reasoning.
       - Preserve the `scenario_analysis` object exactly as the primary agent wrote it, so the user can read those scenarios.
       - Add a completely new thought process to `step_by_step_reasoning` explaining *why* you approved or downgraded the original tips based on the Ineptitude Floor and Scenarios.
       - Set `"is_downgraded": true` if you had to change the `primary_pick`, otherwise `false`.
       - Update the `reasoning` array to reflect your defensive mindset.
       
    ### Output Format
    CRITICAL: Ensure your JSON structure is perfectly valid and contains ZERO trailing commas at the end of objects or lists.
    Return ONLY valid JSON. It MUST EXACTLY MATCH this schema:
    {{
        "step_by_step_reasoning": "Risk Manager's evaluation of the original tips...",
        "scenario_analysis": {json.dumps(initial_prediction_json.get('scenario_analysis', {})) if isinstance(initial_prediction_json, dict) else '[]'},
        "match": "{initial_prediction_json.get('match') if isinstance(initial_prediction_json, dict) else 'Unknown'}",
        "full_analysis": {{
            "1X2": {{"prediction": "[Home/Draw/Away]", "odds": 1.95, "reasoning": "..."}},
            "Match_Goals": {{"prediction": "[Over/Under 2.5]", "odds": 1.80, "reasoning": "..."}},
            "BTTS": {{"prediction": "[Yes/No]", "odds": 1.70, "reasoning": "..."}},
            "Team_Goals": {{"prediction": "[Team + O/U]", "odds": 1.65, "reasoning": "..."}},
            "Double_Chance": {{"prediction": "[1X/X2/12]", "odds": 1.35, "reasoning": "..."}},
            "DNB": {{"prediction": "[Home/Away]", "odds": 1.55, "reasoning": "..."}},
            "Asian_Handicap": {{"prediction": "[Pick]", "odds": 1.90, "reasoning": "..."}},
            "First_Half_Goals": {{"prediction": "[O/U]", "odds": 1.45, "reasoning": "..."}},
            "Second_Half_Goals": {{"prediction": "[O/U]", "odds": 1.25, "reasoning": "..."}},
            "HT_FT": {{"prediction": "[Pick]", "odds": 4.50, "reasoning": "..."}},
            "Correct_Score": {{"prediction": "[Score]", "odds": 12.0, "reasoning": "..."}},
            "Team_Exact_Goals": {{"prediction": "[Team + Exact]", "odds": 3.20, "reasoning": "..."}},
            "Total_Corners": {{"prediction": "[O/U]", "odds": 1.85, "reasoning": "..."}},
            "Total_Cards": {{"prediction": "[O/U]", "odds": 1.85, "reasoning": "..."}},
            "Highest_Scoring_Half": {{"prediction": "[1H/2H/Tie]", "odds": 2.10, "reasoning": "..."}},
            "10_Minute_Draw": {{"prediction": "[Yes/No]", "odds": 1.20, "reasoning": "..."}},
            "Player_Props": {{"prediction": "[Player Bet]", "odds": 2.50, "reasoning": "..."}}
        }},
        "primary_pick": {{
            "tip": "The Final Safe Bet (e.g., 'Home Win' - NO BRACKETS/REASONING)",
            "confidence": 90,
            "odds": 1.45
        }},
        "alternative_pick": {{
            "tip": "The Final Value Bet (e.g., 'Over 2.5' - NO BRACKETS/REASONING)",
            "confidence": 65,
            "odds": 2.10
        }},
        "is_downgraded": true,
        "reasoning": ["Risk Manager point 1", "Risk Manager point 2"]
    }}
    """
    
    import time
    
    try:
        print(f"⏳ [Agent 2] Pausing 5 seconds to clear Gemini API Rate Limits...")
        time.sleep(5)
        print(f"🔎 [Agent 2] Risk Manager is now reviewing {initial_prediction_json.get('match')}...")
        rm_start = get_now_wat()
        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise ValueError("API Key is missing")
            
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{get_active_model()}:generateContent?key={api_key}"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.0, 
                "responseMimeType": "application/json"
            }
        }
        
        is_historical = False
        before_date = ""
        if match_date:
            try:
                match_dt = datetime.fromisoformat(match_date.replace("Z", "+00:00"))
                now_dt = datetime.now(timezone.utc)
                duration = (now_dt - match_dt).total_seconds() / 3600
                if duration > 0:
                    is_historical = True
                    before_date = (match_dt - timedelta(days=1)).strftime("%Y-%m-%d")
            except Exception:
                pass

        if is_historical:
            blind_backtest_header = f"""    ⚠️ BLIND BACKTEST MODE — ACTIVE ⚠️
    You are analysing a HISTORICAL match for validation and backtesting purposes.
    The match has already been played, but you MUST NOT discover or use the final result.

    MANDATORY SEARCH PROTOCOL (violations invalidate this backtest):
    1. You MUST append the operator before:{before_date} to EVERY search query you execute.
    2. You MUST include at least one of these terms in every query: "preview", "predicted lineup", "injury news", "team news", "pre-match", "form guide".
    3. You are STRICTLY FORBIDDEN from searching bare team names alone. Every query MUST include pre-match terms AND the before:{before_date} operator.
    4. If a query does not contain before:{before_date}, DO NOT execute it — reformulate it first.
    5. You are STRICTLY FORBIDDEN from referencing, using, or incorporating the final score, match result, half-time score, or any in-game statistics from this fixture.

    Your goal: produce a full pre-match prediction exactly as if the match has not yet been played.
    ---

"""
            prompt = blind_backtest_header + prompt
            # Rebuild payload with updated prompt
            payload["contents"] = [{"parts": [{"text": prompt}]}]
            print(f"🔍 [Agent 2] Blind Backtest Mode: Search enabled with before:{before_date} date constraints")

        # Conditional search enablement - only use search when Agent 1 makes specific factual claims
        enable_search = needs_fact_checking(initial_prediction_json)
        if enable_search:
            payload["tools"] = [{"google_search": {}}]
            print(f"🔍 [Agent 2] Fact-checking mode enabled - Google Search active")
        else:
            print(f"⚡ [Agent 2] Quick review mode - No search needed (saves 3-5s)")
        
        max_retries = 3
        for attempt in range(max_retries):
            check_cancelled(match_id, job_id)
            try:
                # Increased to 600s for Risk Manager deep fact-checking
                response = requests.post(url, headers={'Content-Type': 'application/json'}, json=payload, timeout=600)
                response.raise_for_status()
                break
            except requests.exceptions.RequestException as e:
                if attempt < max_retries - 1:
                    import time
                    print(f"⚠️ Network error (Risk Manager). Retrying {attempt + 1}/{max_retries} in 5s...")
                    time.sleep(5)
                else:
                    raise
        
        rm_end = get_now_wat()
        print(f"✅ [Agent 2] Risk review completed in {(rm_end - rm_start).total_seconds():.2f}s")
        
        response_json = response.json()
        raw_text = response_json['candidates'][0]['content']['parts'][0]['text']
        
        return json.loads(raw_text)
    except Exception as e:
        print(f"Risk Manager Error: {e}")
        # Fallback to the initial prediction if the second agent fails
        return initial_prediction_json

def generate_best_picks(saved_predictions: list, target_odds: float = None) -> dict:
    target_instruction = ""
    if target_odds:
        target_instruction = f"""
    - **TARGET ODDS REQUIREMENT**: The user explicitly requested this accumulator to reach approximately **{target_odds}x total odds**.
      You MUST select enough highly-safe picks to mathematically multiply out to around {target_odds}x. 
      Do NOT select reckless bets just to hit the target. If hitting {target_odds}x requires picking unviable/dangerous matches, stop before ruining the accumulator and explain why you fell short.
      If {target_odds}x is easily achievable, select the absolute safest combinations of 'primary_pick' or 'alternative_pick' across the matches to hit it.
        """

    prompt = f"""
    ## ROLE AND PRIMARY DIRECTIVE
    You are the OmniBet AI Final Risk Manager and Portfolio Allocator. Your sole responsibility is to protect the CEO's capital by sorting betting predictions into strict mathematical tiers. You are the final gatekeeper.

    ## THE "NO NARRATIVE" RULE
    You are STRICTLY FORBIDDEN from being influenced by the Supreme Court's tactical analysis, narrative, or confidence level (e.g., "Condition Green"). You must ignore the essay. Your ONLY source of truth is the Supreme Court Pick Survival percentage found inside the `simulation_audit` field attached to each match.

    ## VALIDATED ALTERNATIVE MARKETS (MULTI-PICK OPTIMIZATION)
    **CRITICAL NEW FEATURE**: Some matches now include `alternative_results` — a list of validated alternative markets that were tested by the Monte Carlo Simulator alongside the Supreme Court's main pick.

    **YOUR OPTIMIZATION MANDATE:**
    1. **Check for Alternative Results**: For each match, look for the `alternative_results` field in the prediction data.
    2. **Compare Survival Rates**: If alternative results exist, compare the survival rates of:
       - Supreme Court's main pick (from `simulation_audit`)
       - All alternative validated markets (from `alternative_results`)
    3. **Choose the Safest Option**: Select the market with the HIGHEST survival rate, regardless of which one the Supreme Court originally chose.
       - If "Over 0.5 Goals" has 94.2% survival and "Over 1.5 Goals" (Supreme Court pick) has 85.4%, you MUST choose "Over 0.5 Goals"
       - If Supreme Court's pick is already the highest, keep it
    4. **Market Integrity**: All alternative markets are from the SAME correlation bucket, so they maintain tactical coherence
    5. **Update chosen_tip AND odds**: When selecting an alternative market:
       - Find the alternative in the `validated_alternative_markets` array from the prediction data
       - Use the alternative's exact `tip` name
       - **CRITICAL**: Use the alternative's `odds` value (NOT the Supreme Court's original odds)
       - Update the `market` field to match the alternative's market type
       - Update `confidence` to match the alternative's confidence level

    **EXAMPLE:**
    Match has:
    - Supreme Court Pick: "Over 1.5 Goals" (85.4% survival, odds: 1.50)
    - Alternative Results: {{"Over 0.5 Goals": 94.2%, "BTTS Yes": 81.3%, "Over 2.5 Goals": 73.1%}}
    - validated_alternative_markets: [
        {{"tip": "Over 0.5 Goals", "odds": 1.15, "confidence": 95, "market": "Match_Goals"}},
        {{"tip": "BTTS: Yes", "odds": 1.85, "confidence": 82, "market": "BTTS"}},
        {{"tip": "Over 2.5 Goals", "odds": 2.10, "confidence": 72, "market": "Match_Goals"}}
      ]

    **Your Action:**
    - Choose "Over 0.5 Goals" (94.2%) instead of Supreme Court's "Over 1.5 Goals" (85.4%)
    - Use odds: 1.15 (from validated_alternative_markets, NOT 1.50)
    - Use confidence: 95 (from validated_alternative_markets)
    - Place it in Tier 1 (94.2% exceeds 85% threshold)
    - Reasoning: "Over 0.5 Goals upgraded from Supreme Court's validated alternatives (94.2% vs 85.4%)"

    ## THE TRI-TIER PORTFOLIO SORTING PROTOCOL
    You must extract the Survival Rate percentage and assign every match to EXACTLY ONE of the following three tiers based on strict mathematical boundaries:

    **TIER 1: THE MASTER ACCUMULATOR (85.0% to 100%)**
    Criteria: Absolute mathematical locks.
    Action: Approve for the primary Master Accumulator (4+ legs). Place into the `picks` array.

    **TIER 2: VALUE TREBLES & DOUBLES (75.0% to 84.9%)**
    Criteria: High-probability picks that possess too much variance for a long parlay.
    Action: Ban from the Master Accumulator. Isolate into smaller 2-leg or 3-leg secondary tickets. Place into the `tier_2_picks` array.

    **TIER 3: SINGLES & EV SNIPES (0.0% to 74.9%)**
    Criteria: High variance, coin-flips, or mathematical traps.
    Action: Ban from all accumulators/parlays. Play strictly as a standalone single bet, or discard entirely. Place into the `tier_3_picks` array.

    {target_instruction}

    ### Matches to Analyze:
    {json.dumps(saved_predictions)}

    ### Output Format
    CRITICAL: Ensure your JSON structure is perfectly valid and contains ZERO trailing commas at the end of objects or lists.
    Return ONLY valid JSON matching this exact structure:
    {{
        "master_reasoning": "Explain the overarching theme of the TIER 1 accumulator. Explicitly state the average mathematical survival rate of the TIER 1 picks selected and confirm they were sorted by the No Narrative mathematical protocol.",
        "total_accumulator_odds": 5.45,
        "picks": [
            {{
                "match_id": 12345,
                "teams": "Home vs Away",
                "match_date": "YYYY-MM-DDTHH:MM:SSZ",
                "chosen_tip": "The singular safest tip you selected",
                "odds": 1.45,
                "confidence": 95,
                "survival_rate": 88.4,
                "tier": "TIER 1: MASTER ACCUMULATOR",
                "portfolio_action": "Approved for 4+ leg master accumulator",
                "mathematical_reason": "Survival 88.4% clears the 85.0% TIER 1 floor by +3.4 percentage points.",
                "home_logo": "url_if_exists",
                "away_logo": "url_if_exists",
                "reasoning": ["Brief reason 1", "Brief reason 2"]
            }}
        ],
        "tier_2_picks": [
            {{
                "match_id": 12345,
                "teams": "Home vs Away",
                "match_date": "YYYY-MM-DDTHH:MM:SSZ",
                "chosen_tip": "The selected tip",
                "odds": 1.55,
                "confidence": 80,
                "survival_rate": 79.1,
                "tier": "TIER 2: VALUE TREBLES & DOUBLES",
                "portfolio_action": "Banned from master accumulator. Use in 2-3 leg secondary tickets only.",
                "mathematical_reason": "Survival 79.1% falls in the 75.0-84.9% TIER 2 band. Deficit of -5.9pp from TIER 1 floor.",
                "home_logo": "url_if_exists",
                "away_logo": "url_if_exists",
                "reasoning": ["Brief reason 1", "Brief reason 2"]
            }}
        ],
        "tier_3_picks": [
            {{
                "match_id": 12345,
                "teams": "Home vs Away",
                "match_date": "YYYY-MM-DDTHH:MM:SSZ",
                "chosen_tip": "The selected tip",
                "odds": 1.70,
                "confidence": 65,
                "survival_rate": 68.2,
                "tier": "TIER 3: SINGLES & EV SNIPES",
                "portfolio_action": "Banned from all accumulators. Standalone single bet only, or discard.",
                "mathematical_reason": "Survival 68.2% is below the 75.0% TIER 2 floor. High variance — coin-flip territory.",
                "home_logo": "url_if_exists",
                "away_logo": "url_if_exists",
                "reasoning": ["Brief reason 1", "Brief reason 2"]
            }}
        ]
    }}
    """
    
    try:
        print(f"🏆 [Risk Officer] Building the safest master accumulator. Please wait...")
        master_start = get_now_wat()
        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise ValueError("API Key is missing")
            
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{get_active_model()}:generateContent?key={api_key}"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.0, # Strict determinism for master parlay selection
                "responseMimeType": "application/json"
            }
        }
        
        max_retries = 3
        for attempt in range(max_retries):
            try:
                # Increased to 600s for Accumulator generation
                response = requests.post(url, headers={'Content-Type': 'application/json'}, json=payload, timeout=600)
                response.raise_for_status()
                break
            except requests.exceptions.RequestException as e:
                if attempt < max_retries - 1:
                    import time
                    print(f"⚠️ Network error (Risk Officer). Retrying {attempt + 1}/{max_retries} in 5s...")
                    time.sleep(5)
                else:
                    raise
        master_end = get_now_wat()
        print(f"✅ [Risk Officer] Master parlay crafted in {(master_end - master_start).total_seconds():.2f}s")
        
        response_json = response.json()
        raw_text = response_json['candidates'][0]['content']['parts'][0]['text']
        
        return json.loads(raw_text)
        
    except Exception as e:
        print(f"Error generating best picks: {e}")
        return {
            "master_reasoning": "Failed to generate AI accumulator due to an error.",
            "picks": []
        }

def audit_match(initial_prediction: dict, user_selected_bet: str, match_date: str = None, match_id: int = None, job_id: str = None):
    """
    The Betslip Auditor Mode (Pipeline B - Dual Agent Phase 2)
    Evaluates the 'user_selected_bet' against Agent 1's full tactical breakdown.

    CRITICAL: If initial_prediction contains supreme_court data (from 3-agent pipeline),
    the auditor MUST prioritize Supreme Court's final verdict over Agent 1's original analysis,
    as Supreme Court has already vetoed/corrected any Agent 1 errors.
    """
    check_cancelled(match_id, job_id)
    # Harden against list-wrapped JSON from Agent 1
    if isinstance(initial_prediction, list) and len(initial_prediction) > 0:
        initial_prediction = initial_prediction[0]

    prompt = f"""
    You are the Lead Risk Manager and Betslip Auditor for OmniBet AI.
    Your colleague (The Master Tactical Analyzer) has just produced a rigorous, deeply researched 17-market statistical breakdown of an upcoming football match.
    
    ### Colleague's Master Breakdown
    {json.dumps(initial_prediction, indent=2)}
    
    ============
    USER'S SELECTED BET: "{user_selected_bet}"
    ============
    
    Your job is to act as the "Judge." You must evaluate the User's Bet against your colleague's hard data and scenario analysis. Decide if the user's bet is safe, if it needs to be downgraded for safety, or if it is a complete trap.

    ⚠️ **CRITICAL: SUPREME COURT FINAL VERDICT PRIORITY**
    If the breakdown above contains "supreme_court" data (from the 3-agent pipeline), you MUST prioritize the Supreme Court's final verdict over Agent 1's original analysis. The Supreme Court has already:
    - Vetoed any Agent 1 hallucinations
    - Applied Rule 35 (Dead Engine Veto) checks
    - Corrected xG/variance contradictions
    - Run Monte Carlo simulation validation

    When Supreme Court data exists, evaluate the user's bet against:
    1. FIRST: Supreme Court's "Arbiter_Safe_Pick" and "Supreme_Court_Final_Ruling"
    2. SECOND: Agent 1's original analysis (only if it aligns with Supreme Court)
    3. NEVER: Approve a user bet that Supreme Court explicitly overturned

    *** CRITICAL: FACT-CHECKING DIRECTIVE ***
    Your colleague is not infallible and may hallucinate. You have Live Google Search access! 
    Whenever you review a major claim (such as a key player injury, a massive historical win streak, or team lineups), actively use your Search Tool to fact-check your colleague's data before passing your verdict. If your search proves your colleague lied or used outdated data, explicitly call them out in your internal_debate and reject/downgrade the bet accordingly.

    You MUST return your analysis strictly in JSON format. Do not use markdown wrappers around the JSON.
    {{
      "internal_debate": "string (Critique the user's bet against Agent 1's Scenario Analysis BEFORE making your verdict)",
      "audit_verdict": {{
        "status": "APPROVED | DOWNGRADED | REJECTED",
        "original_bet": "{user_selected_bet}",
        "ai_recommended_bet": "string (CRITICAL: EXACTLY ONE standard betting market. NEVER use the word 'or'. Example: 'Over 1.5 Goals' or 'Home Draw No Bet')",
        "estimated_odds": 1.95,
        "risk_level": "Low | Medium | Extreme"
      }},
      "verdict_reasoning": "string (A 2-sentence explanation of why you approved or changed their bet citing the advanced stats)"
    }}

    *** AUDIT RULES ***
    - **RULE 1: THE HALLUCINATION PENALTY (CRITICAL)**: If your Search Tool reveals that your colleague (Agent 1) has hallucinated a player (e.g., Gündogan in a team he doesn't play for) or cited a false historical streak, you MUST DOWNGRADE the user's bet if it relies on that "firepower" or "resilience" narrative. A single hallucination discredits the entire tactical weight of that agent's reasoning.
    - **RULE 2: DERBY LOCKDOWN**: In high-stakes derbies, if the user picks 'Both Teams To Score' or 'Over 2.5', look for tactical reasons to DOWNGRADE. If the H2H history shows cagey 1-0 or 1-1 results, do not approve a high-scoring bet.
    - **RULE 3: SQUAD DEPTH VERIFICATION (INJURIES)**: If a team's top goalscorer is OUT, do NOT automatically forbid goal markets. Instead, perform a **Squad Depth Check** via search. Look for the backup striker's recent form or the team's goals-per-game in matches where that star player was absent. If depth is confirmed, you may APPROVE the bet with a minor confidence reduction. Only downgrade if proof of replacement quality is missing. Additionally, if you have confirmed a defensive collapse on the *opposing* team (Defensive Collapse Override conditions met) but the attacking team's top creator is also OUT with no proven depth, flag this as a **POTENTIAL MUD FIGHT** in your `internal_debate`. Do NOT approve or recommend 'Over 1.5' or 'Over 2.5' markets in this scenario. Instruct the Supreme Court to evaluate the Supply Line Mandate under Rule 10 before forcing any Over market.
    - **RULE 4: EARLY SEASON SAMPLE SIZE ALERT**: If this is Matchday 1-4 of the new season, you MUST NOT reject a user's 'Over 2.5' or 'Win' bet purely because the team failed to score in their opener. This is **Sample Size Bias**. One sterile game is not a trend. If the team had high possession/xG but finished poorly, they are likely to breakout. Downgrade their bet if necessary, but do NOT reject it based on Matchday 1 "ineptitude". 
    - MARKET INTERPRETABILITY: You are an expert in ALL global football betting markets...
    - APPROVED: If the user's bet is mathematically sound and matches the likely Game Script.
    - DOWNGRADED: If the user has the right idea but is being too greedy. (e.g., User picks 'Over 2.5', but stats show a tight game -> Downgrade to 'Over 1.5').
    - REJECTED: If the user is walking into a statistical trap. **CRITICAL RESTRICTION**: You may ONLY reject a user's bet if it would fail in BOTH Scenario A (Expected Script) AND Scenario B (Underdog Disruption). If the user's bet wins in at least ONE scenario, you MUST downgrade it to a safer variant instead of rejecting it outright. The user's instinct has value - your job is to refine it, not override it.
    - STRICT OUTPUT: The 'ai_recommended_bet' MUST be exactly ONE actionable bet. NEVER offer multiple choices or conversational text in this field.

      - **RULE 5: THE ODDS VERIFICATION MANDATE**: You MUST verify the realism of the `odds` provided in Agent 1's 17-market grid. If Agent 1 used Google Search to find odds, cross-reference them against its tactical xG/metrics. If the odds look too high for the predicted safety (e.g., 2.50 for a "safe" Over 1.5 Goals), you MUST mention this discrepancy in your internal_debate and downgrade the bet accordingly.
      - **RULE 6: THE ANTI-BIAS PROTOCOL (CRITICAL)**:
        1. **THE "FIRST-LEG" FALLACY**: Do NOT automatically assume 1st Leg matches will be low-scoring or conservative. Base your verdict strictly on the teams' xG and defensive metrics.
        2. **THE "SYSTEM VS. INDIVIDUAL" RULE**: If a superior team (e.g., an away favorite) is missing a star striker, do NOT automatically downgrade them to 'Under' or 'Draw' if their underlying team system creates high possession and high Big Chances. Trust the system to overcome the individual absence.
        3. **THE DEFENSIVE COLLAPSE OVERRIDE**: The 'System vs. Individual' rule applies strictly to offensive injuries. If a team is missing 2 or more starting defenders or their starting Goalkeeper, you MUST heavily penalize their defensive integrity. A broken defensive line destroys a tactical system. You must not blindly trust a team's offensive system to outscore opponents if their defensive foundation is verified as collapsed.
        4. **THE HALLUCINATION CONTEXT RULE**: When applying the Hallucination Penalty (Rule 1), evaluate the context of the correction. If Agent 1 hallucinates that a star player is injured/suspended, but your live search proves the player is actually ELIGIBLE and PLAYING, do NOT downgrade the team's prediction. The team is actually stronger than Agent 1 calculated. Only apply the penalty and downgrade the bet if the fact-check proves the team is materially weaker than claimed.
        5. **ESTIMATED ODDS**: You MUST provide a realistic `estimated_odds` (Decimal format) for your recommended bet. Use Agent 1's odds or the Odds API payload as a reference. If no odds are available, estimate based on the implied probability of your own tactical analysis.
      4. **GRID CORRECTIONS (CONSISTENCY)**: If you OVERTURN a ruling (Scenario 1), you MUST provide a `grid_corrections` object. This object should contain corrected prediction strings for matching keys in the `full_analysis` grid (specifically `Match_Goals`, `BTTS`, and `Correct_Score`) to ensure the entire card is logically consistent with your Verdict. If Agent 2 changed the score to "1-0" but you ruled "Over 1.5 Goals," you MUST provide a correction for `Correct_Score` (e.g., "2-1").
      3. **STATISTICAL RELIABILITY (SAMPLE SIZE)**: If your colleagues rely on venue-specific trends from fewer than 5 matches, you MUST prioritize the broader season metrics. Do not approve a high-risk bet justified solely by a 1-4 game "venue streak" if the overall data is conflicting.
      - **RULE 7: THE MUTUAL COLLAPSE EXEMPTION AUDIT**: If the match data reveals BOTH teams are missing critical defensive personnel (starting center-backs or starting goalkeeper) OR both teams concede > 1.8 goals per game, you MUST REJECT or DOWNGRADE any 'Under Goals' bet the user has selected ('Under 2.5', 'Under 3.5', 'Under 4.5') or any 'First Half Under' pick. You CANNOT approve a goal ceiling bet when both defensive structures are structurally absent. The market reality is an end-to-end transition shootout where even poor finishers score. Downgrade to: 'BTTS: Yes', 'Over 2.5 Match Goals', 'Over 4.5 Cards', or 'Over 8.5 Corners'.
      - **RULE 8: THE DAM BREAK EXEMPTION AUDIT**: If Agent 1's data shows a team has been flagged for a high Big Chance Miss Rate (Clinical Ineptitude conditions) BUT is simultaneously creating > 2.0 Big Chances per game, you MUST REJECT or DOWNGRADE any 'Under 2.5' or 'Under 3.5' bet the user has selected for that team's matches. The miss rate is temporary negative variance — the high creation volume signals elite offensive quality primed for positive regression. Downgrade to: 'Home Win', 'Home -1.0 Asian Handicap', or 'Over 1.5 Team Goals'.
      - **RULE 9: THE HOME BUZZSAW AUDIT**: If the match data shows the Home Underdog averages > 1.3 goals per game in the current season, OR has recently scored multiple goals against elite/top-tier opposition, you MUST REJECT or DOWNGRADE any Away Team Asian Handicap (Away +1.0, Away +1.5) or Away Double Chance (X2) the user has selected. These markets cannot absorb the blowout risk of a potent home underdog — if the away favorite falls behind, they chase, expose their defensive line, and concede devastating counter-attacks. Downgrade to: 'Home Over 0.5 Goals', 'Home +2.5 Asian Handicap', or 'Over 1.5 Match Goals'. You MUST also ignore any H2H win streak the away team holds — current home offensive form overrides all historical H2H data.
      - **RULE 10: THE DEAD ENGINE VETO AUDIT**: Before approving any user-selected 'BTTS: Yes', 'Over 2.5', or 'Over 3.5' bet backed by RULE 7 (Mutual Collapse Exemption), you MUST run the Dead Engine Check. If ANY team in the match averages < 0.8 goals per game AND creates < 1.5 Big Chances per game, the Dead Engine Veto is active and RULE 7 is immediately suspended. You MUST REJECT the user's over/BTTS selection — a terrible defense is only a liability if the opponent can attack. A Dead Engine cannot generate a shootout. Downgrade to: 'Under 3.5 Goals', 'Match Winner + Under 4.5', or 'Double Chance + Under 3.5' favoring the functional team.
      - **RULE 11: THE H2H OBSESSION TRAP AUDIT**: Before approving any user-selected 'Under 2.5' or 'Under 3.5' bet backed by H2H history or Derby/Rivalry narratives, check current season metrics. If BOTH teams average > 1.0 goals per game (scored OR conceded) in the current season, you MUST REJECT the Under bet — historical low-scoring H2H records cannot override currently leaking defenses. Derby emotion does not create tactical discipline; it creates chaotic mistakes. Downgrade to: 'Over 1.5 Goals' or 'BTTS: Yes', ignoring the historical H2H entirely.
      - **RULE 12: THE PLAYOFF PARALYSIS AUDIT (HIGH-STAKES FEAR)**: If the match is a high-stakes fixture: a Cup Final, a Knockout Match, a late-stage UEFA Qualifier, or a relegation survival decider. THE TACTICAL REALITY: In high-stakes matches, the fear of losing overrides statistical attacking averages. Teams abandon their open playstyles to avoid season-ending mistakes. Furthermore, if a team is missing key defenders/goalkeepers in these matches, the manager overcompensate by playing a hyper-conservative, protective low-block. The match will devolve into a nervous, low-event 0-0 or 1-0 grind. THE GENERAL RULE VETO: This rule strictly VETOES Rule 7 (Mutual Collapse). Missing defenders in a Cup Final/Qualifier do NOT create a shootout; they create a fortified bunker. THE FORBIDDEN ACTION: If the Playoff Paralysis trigger is active, the AI is strictly FORBIDDEN from using 'Over 2.5', 'Over 3.5', or 'BTTS: Yes' as a Safe Banker. THE PIVOT: The AI MUST pivot to survival markets. Set the Safe Banker to wide Match Control (e.g., '1X' for a strong home team) or a massive structural ceiling (e.g., 'Under 3.5 Goals'). Respect the fear.
      - **RULE 13: THE GLASS CANNON AUDIT (THE BROKEN FAVORITE)**: If the AI identifies a Heavy Favorite (e.g., highly superior talent, dominant odds) BUT flags them for a structural defensive collapse (Rule 10 active - missing key CB/GK/Captain), AND the Underdog has a functional offense (Rule 10 Dead Engine Veto is INACTIVE). THE TACTICAL REALITY (THE COUNTER-ATTACK TRAP): A heavy favorite with a broken defense is a 'Glass Cannon.' Because they are the favorite, they will push high up the pitch and dominate possession. Because their defense is broken, the underdog will successfully counter-attack and score. If the underdog scores, the favorite must score twice just to win the game. This introduces massive variance and frequently results in 1-1 or 2-2 draws. THE FORBIDDEN ACTION: If the Glass Cannon trigger is active, the AI is strictly FORBIDDEN from using the Match Winner (1X2) market or negative Asian Handicaps (-1.0, -1.5) on the Favorite as the Safe Banker. You cannot trust a broken defense to secure all 3 points. THE PIVOT: The AI MUST decouple the Safe Banker from the Match Winner entirely. Since both teams are highly likely to score, pivot the Safe Banker to structural goal floors: 'Over 1.5 Match Goals' or 'BTTS: Yes'.
      - **RULE 14: THE EXHIBITION VOID AUDIT (THE FRIENDLY MATCH TRAP)**: If the match is a Non-Competitive Fixture: Club Friendlies, U21/U19 International Friendlies, or pre-season exhibitions. THE TACTICAL REALITY (NO MATCH CONTROL): In friendly matches, 'Home Advantage' is a mirage (empty stadiums, no crowd pressure). Furthermore, managers prioritize player evaluation over winning, leading to mass substitutions (6+ changes) in the second half. This completely destroys tactical structure and makes Match Control entirely unpredictable. A superior team will easily lose 0-1 to a late fluke goal from a reserve player. THE GENERAL RULE VETO: This rule strictly VETOES Rule 9 (Home Buzzsaw). Home and Away splits are mathematically invalid in friendly exhibitions. THE FORBIDDEN ACTION: If the Exhibition Void trigger is active, the AI is strictly FORBIDDEN from using Match Control markets (1X2, Double Chance, Draw No Bet, Asian Handicaps) as the Safe Banker. You cannot trust a team to win or draw a match they do not care about winning. THE PIVOT: The AI MUST decouple the Safe Banker from the Match Winner entirely. Pivot to purely structural goal floors that survive disjointed, sloppy football: 'Under 3.5 Goals', '1st Half Under 1.5 Goals', or if both teams have elite offensive depth, 'Over 1.5 Match Goals'.
      - **RULE 15: THE UNCERTAINTY CEILING AUDIT (DEFENSIVE APATHY)**: If Agent 1 selects an 'Under Goals' market (Under 2.5, Under 3.5) for a match flagged as an Exhibition/Friendly (Rule 14) OR involving a 'Dead Engine' that ALSO concedes >1.3 goals/game, you MUST REJECT or DOWNGRADE the 'Under' bet. THE TACTICAL REALITY: Apathy and lack of motivation in friendlies or among failing teams breed goals, not stalemates. You cannot trust a goal ceiling where there is no defensive floor. THE PIVOT: Force a pivot to: 'Over 1.5 Match Goals', 'Favorite Over 1.5 Team Goals', or wide Match Control ('1X').
    """
    
    try:
        team_a_name = initial_prediction.get('home_team') or "the Match"
        print(f"⚖️ [Auditor] Evaluating {user_selected_bet} against Agent 1 report for {team_a_name}...")
        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise ValueError("API Key is missing")
            
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{get_active_model()}:generateContent?key={api_key}"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.2, 
                "responseMimeType": "application/json"
            }
        }
        
        is_historical = False
        if match_date:
            try:
                match_dt = datetime.fromisoformat(match_date.replace("Z", "+00:00"))
                now_dt = datetime.now(timezone.utc)
                duration = (now_dt - match_dt).total_seconds() / 3600
                if duration > 0:
                    is_historical = True
            except Exception:
                pass
                
        if is_historical:
            print(f"🛡️ Auditor Backtesting Mode: Disabling Search for past match")
        else:
            payload["tools"] = [{"google_search": {}}]
        
        max_retries = 3
        for attempt in range(max_retries):
            check_cancelled(match_id, job_id)
            try:
                # Increased to 600s for Betslip Auditor
                response = requests.post(url, headers={'Content-Type': 'application/json'}, json=payload, timeout=600)
                response.raise_for_status()
                break
            except requests.exceptions.RequestException as e:
                if attempt < max_retries - 1:
                    import time
                    print(f"⚠️ Network error (Auditor). Retrying {attempt + 1}/{max_retries} in 5s...")
                    time.sleep(5)
                else:
                    raise
        
        response_json = response.json()
        raw_text = response_json['candidates'][0]['content']['parts'][0]['text']
        
        parsed = json.loads(raw_text)
        if isinstance(parsed, list) and len(parsed) > 0:
            return parsed[0]
        return parsed
        
    except Exception as e:
        print(f"Error executing Auditor: {e}")
        return {
            "internal_debate": f"Failed to audit bet due to API Error: {str(e)}",
            "audit_verdict": {
                "status": "REJECTED",
                "original_bet": user_selected_bet,
                "ai_recommended_bet": "API Error",
                "risk_level": "Extreme"
            },
            "verdict_reasoning": "Could not extract statistical data to verify bet safety."
        }

def get_threshold_for_league(league_name: str, manual_threshold: float = None) -> tuple:
    """
    Automatically determine the optimal Rule 64 threshold based on league characteristics.

    Args:
        league_name: Name of the league/competition
        manual_threshold: User's manual threshold setting (if auto-detection is OFF)

    Returns:
        tuple: (threshold, is_auto_detected, league_tier_description)
    """
    from src.database.db import get_app_setting

    # Check if auto-detection is enabled
    auto_detect = get_app_setting("rule64_auto_detect", "true") == "true"

    if not auto_detect or not league_name:
        # Use manual threshold
        from src.database.db import get_rule64_threshold
        threshold = manual_threshold if manual_threshold is not None else get_rule64_threshold()
        return (threshold, False, "Manual Setting")

    league_lower = league_name.lower()

    # TIER 1: Elite Consistent Leagues (30-40% threshold - STRICT)
    elite_leagues = [
        "premier league", "premiership", "epl", "english premier",
        "la liga", "primera división", "spanish la liga",
        "bundesliga", "german bundesliga",
        "serie a", "italian serie a",
        "ligue 1", "french ligue 1",
        "champions league", "uefa champions league", "ucl"
    ]

    for elite in elite_leagues:
        if elite in league_lower:
            return (0.35, True, "Elite League (Tier 1)")

    # TIER 2: Moderate Consistency Leagues (40-50% threshold - BALANCED)
    moderate_leagues = [
        "eredivisie", "netherlands", "dutch",
        "primeira liga", "portugal", "portuguese",
        "pro league", "belgium", "belgian",
        "süper lig", "super lig", "turkey", "turkish",
        "championship", "english championship",
        "segunda división", "la liga 2",
        "serie b", "2. bundesliga",
        "europa league", "uefa europa league", "uel",
        "scottish premiership", "scotland"
    ]

    for moderate in moderate_leagues:
        if moderate in league_lower:
            return (0.45, True, "Moderate League (Tier 2)")

    # TIER 3: High Variance Leagues (60-70% threshold - LENIENT)
    high_variance_leagues = [
        "azerbaijan", "premier liqası",
        "kazakhstan", "premier league",
        "georgia", "erovnuli liga",
        "armenia", "premier league",
        "uzbekistan", "super league",
        "moldova", "divizia națională",
        "league one", "league two", "national league",
        "regionalliga", "oberliga",
        "tercera división", "serie c",
        "youth", "u21", "u19", "u18", "u17",
        "reserve", "second team", "b team"
    ]

    for high_var in high_variance_leagues:
        if high_var in league_lower:
            return (0.65, True, "High Variance League (Tier 3)")

    # TIER 4: Special Cases

    # Cup competitions (domestic cups, not continental)
    if any(cup in league_lower for cup in ["cup", "copa", "coupe", "pokal"]) and \
       not any(elite in league_lower for elite in ["champions", "europa", "uefa"]):
        return (0.50, True, "Domestic Cup (Neutral)")

    # Friendly/Exhibition matches
    if any(friendly in league_lower for friendly in ["friendly", "friendlies", "exhibition", "testimonial"]):
        return (0.70, True, "Friendly Match (High Variance)")

    # DEFAULT: Use balanced threshold for unknown leagues
    return (0.50, True, "Unknown League (Default)")


def calculate_recent_form_xg(form_data: dict, is_home: bool) -> tuple:
    """
    Calculate recent form metrics from last 5 matches.

    Args:
        form_data: Form data containing recent matches
        is_home: True if home team, False if away team

    Returns:
        tuple: (recent_goals_avg, big_chances_avg, matches_analyzed)
    """
    if not form_data:
        return None, None, 0

    try:
        # Extract recent matches (usually last 5)
        recent_matches = form_data.get("matches", [])
        if not recent_matches:
            return None, None, 0

        total_goals = 0
        total_big_chances = 0
        matches_count = 0

        for match in recent_matches[:5]:  # Analyze last 5 matches
            # Extract goals scored in this match
            if is_home:
                goals = match.get("homeScore", {}).get("current", 0)
            else:
                goals = match.get("awayScore", {}).get("current", 0)

            total_goals += goals if goals is not None else 0

            # Extract big chances if available
            big_chances = match.get("statistics", {}).get("bigChancesCreated", 0)
            total_big_chances += big_chances if big_chances is not None else 0

            matches_count += 1

        if matches_count == 0:
            return None, None, 0

        recent_goals_avg = total_goals / matches_count
        recent_big_chances_avg = total_big_chances / matches_count

        return recent_goals_avg, recent_big_chances_avg, matches_count
    except (TypeError, KeyError, ZeroDivisionError, AttributeError):
        return None, None, 0


def get_xg_with_intelligent_fallback(raw_xg, team_metrics: dict, is_home: bool, match_data: dict = None) -> float:
    """
    Extract xG with intelligent league-aware fallback logic.
    NOW WITH RECENT FORM ANALYSIS to prevent stale season data overriding drought scenarios.

    Args:
        raw_xg: Raw xG value from Supreme Court (may be None)
        team_metrics: Dictionary containing team's advanced tactical metrics
        is_home: True if home team, False if away team
        match_data: Full match data for additional context

    Returns:
        float: Best available xG estimate with recent form weighting
    """
    # Priority 1: Use Supreme Court's xG if provided
    if raw_xg is not None:
        return float(raw_xg)

    # Priority 2: Extract from team's advanced tactical metrics
    xg_from_metrics = team_metrics.get("Expected goals (xG) per game")
    if xg_from_metrics is not None:
        season_xg = float(xg_from_metrics)

        # CRITICAL FIX: Check recent form to detect goal droughts
        if match_data:
            form_data = match_data.get("home_form" if is_home else "away_form")
            recent_goals_avg, recent_big_chances_avg, matches_analyzed = calculate_recent_form_xg(form_data, is_home)

            if matches_analyzed >= 3:  # Need at least 3 recent matches
                # Apply home/away adjustment to recent form
                adjustment = 1.10 if is_home else 0.95
                recent_xg = recent_goals_avg * adjustment

                # FORM VARIANCE DETECTION: Detect if recent form contradicts season average
                # Use auto-detected threshold based on league OR manual setting
                league_name = match_data.get("league", {}).get("name", "") if match_data else ""
                variance_threshold, is_auto, league_tier = get_threshold_for_league(league_name)

                variance_ratio = abs(season_xg - recent_xg) / max(season_xg, 0.5)

                if variance_ratio > variance_threshold:  # Significant divergence based on league-specific or user setting
                    # Weight recent form more heavily (70% recent, 30% season)
                    blended_xg = (recent_xg * 0.70) + (season_xg * 0.30)
                    print(f"⚠️ [Rule 64 Triggered] Variance: {variance_ratio:.1%} > Threshold: {variance_threshold:.1%}")
                    print(f"   League: '{league_name}' ({league_tier}) | {'Auto-detected' if is_auto else 'Manual'}")
                    print(f"   Season xG: {season_xg:.2f}, Recent xG: {recent_xg:.2f} → Blended: {blended_xg:.2f}")
                    return blended_xg
                else:
                    print(f"✅ [Form Alignment] Variance: {variance_ratio:.1%} ≤ Threshold: {variance_threshold:.1%} (No penalty)")
                    print(f"   League: '{league_name}' ({league_tier}) | {'Auto-detected' if is_auto else 'Manual'}")


        return season_xg

    # Priority 3: Check RECENT FORM first before falling back to season averages
    if match_data:
        form_data = match_data.get("home_form" if is_home else "away_form")
        recent_goals_avg, recent_big_chances_avg, matches_analyzed = calculate_recent_form_xg(form_data, is_home)

        if matches_analyzed >= 3:  # Need at least 3 recent matches for reliability
            adjustment = 1.10 if is_home else 0.95
            recent_xg = recent_goals_avg * adjustment
            print(f"⚙️ [Monte Carlo] Using RECENT FORM xG: {recent_xg:.2f} (from {matches_analyzed} recent matches, avg {recent_goals_avg:.2f} goals)")
            return recent_xg

    # Priority 4: Calculate from actual season data (goals / matches)
    goals_scored = team_metrics.get("Goals scored per game")
    if goals_scored is not None:
        # Apply home advantage adjustment
        adjustment = 1.10 if is_home else 0.95
        return float(goals_scored) * adjustment

    # Priority 5: Try to extract from total season stats
    try:
        # Some APIs provide "Matches" and total goals
        total_matches = team_metrics.get("Matches", 0)
        # Try to find total goals (various API formats)
        total_goals = (team_metrics.get("Goals scored", 0) or
                       team_metrics.get("Total goals", 0) or
                       team_metrics.get("Goals", 0))

        if total_matches >= 5 and total_goals > 0:  # Minimum 5 matches for reliability
            actual_avg = total_goals / total_matches
            adjustment = 1.10 if is_home else 0.95
            calculated_xg = actual_avg * adjustment
            print(f"⚙️ [Monte Carlo] Calculated xG from season data: {calculated_xg:.2f} (from {total_goals} goals in {total_matches} matches)")
            return calculated_xg
    except (TypeError, ZeroDivisionError):
        pass

    # Priority 6: League-aware neutral fallback
    # Try to detect league characteristics from match data
    league_avg_home = 1.3
    league_avg_away = 1.1

    if match_data:
        # Check if we can infer league scoring from standings data
        try:
            standings = match_data.get("home_standings", {}) if is_home else match_data.get("away_standings", {})
            if standings:
                # If we have standings data, we can estimate league average
                league_goals = standings.get("goalsFor", 0)
                league_matches = standings.get("playedGames", 0)
                if league_matches >= 10:  # Need reasonable sample
                    league_team_avg = league_goals / league_matches
                    # Adjust for home/away
                    if is_home:
                        league_avg_home = league_team_avg * 1.10
                    else:
                        league_avg_away = league_team_avg * 0.95
        except (TypeError, KeyError, ZeroDivisionError):
            pass

    # Ultimate fallback with warning
    fallback_value = league_avg_home if is_home else league_avg_away
    team_type = "Home" if is_home else "Away"
    print(f"⚠️ [Monte Carlo] Using neutral fallback for {team_type}: {fallback_value:.2f} xG (no season data available)")

    return fallback_value


def check_dead_engine_veto(home_metrics: dict, away_metrics: dict, home_form: dict = None, away_form: dict = None) -> dict:
    """
    ALGORITHMIC RULE 35 (DEAD ENGINE VETO) VALIDATOR
    Runs BEFORE Supreme Court ruling to catch Dead Engine scenarios that should veto high-variance rules.

    Args:
        home_metrics: Home team's advanced tactical metrics
        away_metrics: Away team's advanced tactical metrics
        home_form: Recent form data for home team
        away_form: Recent form data for away team

    Returns:
        dict: {
            "home_is_dead_engine": bool,
            "away_is_dead_engine": bool,
            "home_gpg": float,
            "away_gpg": float,
            "home_big_chances": float,
            "away_big_chances": float,
            "veto_active": bool,
            "veto_message": str
        }
    """
    result = {
        "home_is_dead_engine": False,
        "away_is_dead_engine": False,
        "home_gpg": None,
        "away_gpg": None,
        "home_big_chances": None,
        "away_big_chances": None,
        "veto_active": False,
        "veto_message": ""
    }

    # Check Home Team
    home_gpg = home_metrics.get("Goals scored per game") or home_metrics.get("Goals per game")
    if home_gpg is None and home_form:
        # Calculate from recent form if season data missing
        recent_goals_avg, _, matches_analyzed = calculate_recent_form_xg(home_form, is_home=True)
        if matches_analyzed >= 3:
            home_gpg = recent_goals_avg

    home_big_chances_total = home_metrics.get("Big chances created", 0)
    home_matches = home_metrics.get("Matches", 1)
    home_big_chances_pg = home_big_chances_total / max(home_matches, 1) if home_big_chances_total else 0

    result["home_gpg"] = home_gpg
    result["home_big_chances"] = home_big_chances_pg

    # Dead Engine Check: < 0.8 GPG AND < 1.5 Big Chances per game
    if home_gpg is not None and home_gpg < 0.8 and home_big_chances_pg < 1.5:
        result["home_is_dead_engine"] = True

    # Check Away Team
    away_gpg = away_metrics.get("Goals scored per game") or away_metrics.get("Goals per game")
    if away_gpg is None and away_form:
        # Calculate from recent form if season data missing
        recent_goals_avg, _, matches_analyzed = calculate_recent_form_xg(away_form, is_home=False)
        if matches_analyzed >= 3:
            away_gpg = recent_goals_avg

    away_big_chances_total = away_metrics.get("Big chances created", 0)
    away_matches = away_metrics.get("Matches", 1)
    away_big_chances_pg = away_big_chances_total / max(away_matches, 1) if away_big_chances_total else 0

    result["away_gpg"] = away_gpg
    result["away_big_chances"] = away_big_chances_pg

    # Dead Engine Check: < 0.8 GPG AND < 1.5 Big Chances per game
    if away_gpg is not None and away_gpg < 0.8 and away_big_chances_pg < 1.5:
        result["away_is_dead_engine"] = True

    # Set veto flag
    if result["home_is_dead_engine"] or result["away_is_dead_engine"]:
        result["veto_active"] = True
        dead_team = "Home" if result["home_is_dead_engine"] else "Away"
        result["veto_message"] = (
            f"⚠️ RULE 35 VETO ACTIVE: {dead_team} team is a Dead Engine "
            f"({dead_team.lower()}_gpg={result[f'{dead_team.lower()}_gpg']:.2f}, "
            f"{dead_team.lower()}_big_chances={result[f'{dead_team.lower()}_big_chances']:.2f}). "
            f"FORBIDDEN: Over 1.5/2.5/3.5 Goals, BTTS: Yes. "
            f"REQUIRED: Pivot to Under 3.5 Goals or Match Control (1X/X2)."
        )

    return result


def check_bilateral_dead_engine(home_metrics: dict, away_metrics: dict, home_form: dict = None, away_form: dict = None) -> dict:
    """
    BILATERAL DEAD ENGINE DETECTOR - Checks if BOTH teams are simultaneously in drought.

    This catches scenarios like Hull 0-0 Coventry where BOTH offenses fail simultaneously.

    Args:
        home_metrics: Home team's advanced tactical metrics
        away_metrics: Away team's advanced tactical metrics
        home_form: Recent form data for home team
        away_form: Recent form data for away team

    Returns:
        dict: {
            "bilateral_drought": bool,
            "both_teams_dead": bool,
            "home_recent_gpg": float,
            "away_recent_gpg": float,
            "combined_recent_gpg": float,
            "veto_message": str
        }
    """
    result = {
        "bilateral_drought": False,
        "both_teams_dead": False,
        "home_recent_gpg": None,
        "away_recent_gpg": None,
        "combined_recent_gpg": None,
        "veto_message": ""
    }

    # Get recent form for both teams
    home_recent_goals, _, home_matches = calculate_recent_form_xg(home_form, is_home=True)
    away_recent_goals, _, away_matches = calculate_recent_form_xg(away_form, is_home=False)

    # Need at least 3 recent matches for both teams
    if home_matches < 3 or away_matches < 3:
        return result

    result["home_recent_gpg"] = home_recent_goals
    result["away_recent_gpg"] = away_recent_goals
    result["combined_recent_gpg"] = home_recent_goals + away_recent_goals

    # Bilateral Dead Engine: BOTH teams < 0.8 GPG in recent form
    if home_recent_goals < 0.8 and away_recent_goals < 0.8:
        result["bilateral_drought"] = True
        result["both_teams_dead"] = True
        result["veto_message"] = (
            f"⚠️ BILATERAL DEAD ENGINE DETECTED: Both teams in simultaneous drought. "
            f"Home: {home_recent_goals:.2f} GPG, Away: {away_recent_goals:.2f} GPG (last {min(home_matches, away_matches)} matches). "
            f"Combined: {result['combined_recent_gpg']:.2f} GPG. "
            f"FORBIDDEN: Over 1.5/2.5/3.5 Goals, BTTS: Yes. "
            f"REQUIRED: Force NO BET or Under 2.5 Goals. "
            f"Rule 53 (Defensive Clown Show) is VETOED by bilateral offensive collapse."
        )

    # Partial bilateral drought: Combined < 1.5 GPG (e.g., 0.9 + 0.5 = 1.4)
    elif result["combined_recent_gpg"] < 1.5:
        result["bilateral_drought"] = True
        result["both_teams_dead"] = False  # Not both dead individually, but combined output too low
        result["veto_message"] = (
            f"⚠️ BILATERAL LOW-SCORING DETECTED: Combined recent form < 1.5 GPG. "
            f"Home: {home_recent_goals:.2f} GPG, Away: {away_recent_goals:.2f} GPG. "
            f"Combined: {result['combined_recent_gpg']:.2f} GPG. "
            f"HIGH RISK: Over 2.5/3.5 Goals. Consider Under 2.5 or NO BET."
        )

    return result


def validate_supreme_court_pick(pick: str, home_ga: float, away_ga: float, dead_engine_check: dict, bilateral_check: dict = None, combined_xg: float = None) -> dict:
    """
    Validates Supreme Court pick against Rule 53 (Defensive Clown Show), Rule 35 (Dead Engine Veto),
    and Bilateral Dead Engine scenarios.

    Args:
        pick: The Supreme Court's proposed Arbiter_Safe_Pick
        home_ga: Home team goals conceded per game
        away_ga: Away team goals conceded per game
        dead_engine_check: Result from check_dead_engine_veto()
        bilateral_check: Result from check_bilateral_dead_engine()
        combined_xg: Combined expected goals (home_xg + away_xg) for xG-based validation

    Returns:
        dict: {
            "is_valid": bool,
            "violation": str or None,
            "recommended_pivot": str or None
        }
    """
    pick_lower = pick.lower()

    # PRIORITY 1: Check Bilateral Dead Engine (most restrictive)
    if bilateral_check and bilateral_check.get("bilateral_drought"):
        if bilateral_check.get("both_teams_dead"):
            # Both teams < 0.8 GPG - FORCE NO BET or Under 2.5 ONLY
            if "over 1.5" in pick_lower or "over 2.5" in pick_lower or "over 3.5" in pick_lower or "btts: yes" in pick_lower:
                return {
                    "is_valid": False,
                    "violation": f"BILATERAL DEAD ENGINE: {bilateral_check['veto_message']}",
                    "recommended_pivot": "NO BET or Under 2.5 Goals"
                }
        elif bilateral_check.get("combined_recent_gpg", 999) < 1.5:
            # Combined < 1.5 GPG - High risk for Over 2.5+
            if "over 2.5" in pick_lower or "over 3.5" in pick_lower:
                return {
                    "is_valid": False,
                    "violation": f"BILATERAL LOW-SCORING: {bilateral_check['veto_message']}",
                    "recommended_pivot": "Under 2.5 Goals or Over 1.5 Goals (safer floor)"
                }

    # PRIORITY 2: Check Rule 53 with xG Context
    # Rule 53 should only force Over markets when BOTH conditions are met:
    # 1. Both defenses are bad (GA > 1.1)
    # 2. Combined xG supports scoring (xG >= 2.8)
    rule_53_active = home_ga > 1.1 and away_ga > 1.1

    # NEW: Add xG-based validation
    if rule_53_active and combined_xg is not None:
        # If combined xG < 2.8, Rule 53 is "weak" - bad defenses but weak offenses
        # Allow Under markets as safe bankers in this case
        if combined_xg < 2.8:
            # Weak Rule 53: Defenses bad, but offenses can't exploit it
            # Over 1.5 is still valid (74%+ survival), but don't forbid Under 3.5
            print(f"⚠️ [Rule 53 Context] Weak activation: GA > 1.1 but combined xG only {combined_xg:.2f}")
            print(f"   Bad defenses + weak offenses = moderate scoring (not a shootout)")
            # Allow both Over 1.5 AND Under 3.5 as valid safe picks
            return {"is_valid": True, "violation": None, "recommended_pivot": None}

    # PRIORITY 3: Check Rule 53 violation with Dead Engine override
    if rule_53_active and dead_engine_check["veto_active"]:
        # Rule 35 should VETO Rule 53's Over forcing logic
        if "under 2.5" in pick_lower or "under 3.5" in pick_lower:
            # Under picks are ALLOWED when Dead Engine vetoes Rule 53
            return {"is_valid": True, "violation": None, "recommended_pivot": None}
        elif "over 1.5" in pick_lower or "over 2.5" in pick_lower or "over 3.5" in pick_lower or "btts: yes" in pick_lower:
            return {
                "is_valid": False,
                "violation": "Rule 53 (Defensive Clown Show) attempted to force Over/BTTS, but Rule 35 (Dead Engine Veto) VETOES this. Cannot use Over markets when one team cannot attack.",
                "recommended_pivot": "Under 3.5 Goals or Match Control (1X/X2)"
            }

    # PRIORITY 3: Check Dead Engine with Over picks (regardless of Rule 53)
    if dead_engine_check["veto_active"]:
        if "over 1.5" in pick_lower or "over 2.5" in pick_lower or "over 3.5" in pick_lower or "btts: yes" in pick_lower:
            return {
                "is_valid": False,
                "violation": f"Dead Engine Veto active. {dead_engine_check['veto_message']}",
                "recommended_pivot": "Under 3.5 Goals or Match Control (1X/X2)"
            }

    return {"is_valid": True, "violation": None, "recommended_pivot": None}


def enforce_rule_40_strict(home_metrics: dict, away_metrics: dict, combined_xg: float, league_name: str = "") -> dict:
    """
    RULE 40 STRICT ENFORCEMENT: Force NO BET when sample size too small or sport variant detected.

    Triggers:
    1. Either team < 5 matches
    2. Combined xG > 6.0 (suggests sport variant like 6v6)
    3. Non-standard format detected in league name

    Args:
        home_metrics: Home team metrics (must contain "Matches")
        away_metrics: Away team metrics (must contain "Matches")
        combined_xg: Combined expected goals
        league_name: League/competition name for format detection

    Returns:
        dict: {
            "force_no_bet": bool,
            "reason": str,
            "trigger": str
        }
    """
    result = {
        "force_no_bet": False,
        "reason": "",
        "trigger": ""
    }

    # Extract match counts (defensive programming to avoid false positives)
    home_matches = home_metrics.get("Matches")
    away_matches = away_metrics.get("Matches")

    # CRITICAL FIX: Only enforce Rule 40 if we actually have valid match count data
    # If data is missing (None), this is a data extraction issue, NOT an early-season scenario
    if home_matches is None or away_matches is None:
        print(f"⚠️ [Rule 40 Warning] Match count data missing. Home: {home_matches}, Away: {away_matches}")
        print(f"   Skipping Rule 40 enforcement - cannot validate sample size without data.")
        return result  # force_no_bet remains False

    # Convert to integers for safety
    home_matches = int(home_matches)
    away_matches = int(away_matches)
    min_matches = min(home_matches, away_matches)

    # Trigger 1: Sample size too small (ONLY if we have valid data showing < 5 matches)
    if min_matches < 5:
        result["force_no_bet"] = True
        result["trigger"] = "SAMPLE_SIZE"
        result["reason"] = (
            f"⛔ RULE 40 STRICT ENFORCEMENT: Minimum sample size violation. "
            f"Home: {home_matches} matches, Away: {away_matches} matches. "
            f"Minimum required: 5 matches per team. "
            f"Statistical models are INVALID with N < 5. Forcing NO BET."
        )
        return result

    # Trigger 2: Outlier combined xG (suggests sport variant)
    if combined_xg > 6.0:
        result["force_no_bet"] = True
        result["trigger"] = "OUTLIER_XG"
        result["reason"] = (
            f"⛔ RULE 40 STRICT ENFORCEMENT: Outlier xG detected. "
            f"Combined xG: {combined_xg:.2f} > 6.0. "
            f"Standard 11v11 football rarely exceeds 4.0 combined xG. "
            f"This suggests sport variant (6v6, 7v7, futsal) or data error. "
            f"Standard models are NOT calibrated for this scenario. Forcing NO BET."
        )
        return result

    # Trigger 3: Sport variant detection
    sport_variants = ["6v6", "7v7", "5v5", "futsal", "beach soccer", "baller league", "indoor"]
    league_lower = league_name.lower()

    for variant in sport_variants:
        if variant in league_lower:
            result["force_no_bet"] = True
            result["trigger"] = "SPORT_VARIANT"
            result["reason"] = (
                f"⛔ RULE 40 STRICT ENFORCEMENT: Sport variant detected. "
                f"League: '{league_name}' contains '{variant}'. "
                f"Standard 11v11 models (Poisson/Dixon-Coles) are NOT valid for {variant} format. "
                f"Different goal dynamics require specialized models. Forcing NO BET."
            )
            return result

    return result


def supreme_court_judge(match_data: dict, agent_1_pitch: dict, agent_2_critique: dict, match_id: int = None, job_id: str = None) -> dict:
    """
    The Final Risk Arbiter (Pipeline B - Phase 3).
    Resolves the debate between Agent 1 (Tactical) and Agent 2 (Risk Manager).
    Applies the OmniBet 17-Market Correlation Matrix for EV calculation.

    RULE HIERARCHY & CONFLICT RESOLUTION:
    =====================================

    TIER 0 - ABSOLUTE VETOES (Cannot be overridden by ANY other rule):
    - Rule 48: 0-0 Anchor Ban
    - Rule 53: Defensive Clown Show
      → CRITICAL EXCEPTION: Rule 35 (Dead Engine Veto) overrides Rule 53 when ONE team
        averages < 0.8 GPG AND creates < 1.5 Big Chances per game. Two leaky defenses
        do NOT guarantee goals if one team literally cannot attack.
    - Rule 57: Sterility Supremacy Mandate (enforces Rules 48 & 53, subject to Rule 35 exception)

    TIER 1 - SAMPLE SIZE QUARANTINE (Overrides all goal-direction rules):
    - Rule 40: Early-Season Quarantine (N < 5 matches)
      → Overrides: Rules 16, 33, 35, all goal markets
      → NOTE: The enforcement threshold is N < 5 (not 8). Matches with 5+ games have sufficient sample size.

    TIER 2 - STRUCTURAL OVERRIDES (Override tactical rules):
    - Rule 41: Playoff Paralysis (High-Stakes Fear)
      → Holds ABSOLUTE SUPREMACY over Rule 18 (Youth Variance)
      → VETOES Rule 33 (Mutual Collapse in Cup Finals)
    - Rule 43: Exhibition Void (Friendly Matches)
      → VETOES Rule 32 (Home Buzzsaw)
      → VETOES Rule 35 (Dead Engine)

    TIER 3 - FATIGUE RULES (Hierarchical by severity):
    - Rule 56: Biological Supremacy (< 3 days rest, BOTH teams)
      → Overrides: Rules 18, 43
    - Rule 51: Symmetric Fatigue Grind (< 4 days rest, BOTH teams)
    - Rule 22: Cumulative Fatigue Override (120-min penalty, ONE team)
    - Rule 29: Asymmetric Fatigue Protocol (ONE team fatigued)
    NOTE: Rules 22 and 51 are NOT contradictory - they apply to different scenarios

    TIER 4 - DEFENSIVE ANALYSIS:
    - Rule 33: Mutual Collapse Exemption (BOTH defenses broken)
      → Overrides: Rule 16 (Sterile Offense), Rule 31 (Clinical Ineptitude)
      → VETOED BY: Rule 35 (Dead Engine), Rule 41 (Playoff Paralysis)
    - Rule 10: Defensive Collapse Override (ONE defense broken)
      → Enables: Rule 62 (Nothing to Lose Shootout)
      → Blocked by: Rule 10's Supply Line Mandate (Mud Fight check)

    TIER 5 - OFFENSIVE ANALYSIS:
    - Rule 34: Dam Break Exemption (high chance volume)
      → Overrides: Rule 31 (Clinical Ineptitude), Rule 16 (Sterile Offense)
    - Rule 35: Dead Engine Veto
      → VETOES: Rule 33 (Mutual Collapse), Rule 18 (Youth Variance)
    - Rule 64: xG Form Penalty (The Drought Discount)
      → MANDATORY SIMULATION PARAMETER OVERRIDE: Slash xG by 50% for teams in 3+ match drought
      → Applies to: Monte Carlo input parameters (home_xG, away_xG)
      → Cannot be overridden by season-long averages or "regression to mean" logic

    TIER 6 - CONTEXTUAL RULES:
    - Rule 32: Home Buzzsaw Override
      → Overrides: Rule 20 (H2H Respect Clause)
      → VETOED BY: Rule 61 (U23 vs Senior)
    - Rule 36: H2H Obsession Trap
      → Overrides: Rule 20 (H2H Respect Clause)

    CONFLICT RESOLUTION PRINCIPLES:
    1. Higher tier always wins over lower tier
    2. Within same tier, VETO rules beat OVERRIDE rules
    3. Structural rules (game state) beat statistical rules (averages)
    4. Sample size mandates beat all data-driven rules
    5. **xG-Variance Alignment MANDATORY**: variance_multiplier MUST align with combined_xG:
       - combined_xG < 2.5 → variance = 1.0 (FORCED, even if high-variance rule active)
       - combined_xG 2.5-3.5 → variance = 1.0-1.3 (use 1.3 only if BOTH offenses functional)
       - combined_xG >= 3.5 → variance = 1.3-1.5 (chaos mode justified)
    6. **Rule 35 Veto Check MANDATORY**: Before applying Rule 53, 33, 19, or 62:
       - Check if EITHER team is Dead Engine (< 0.8 GF/game AND < 1.5 big chances)
       - If yes: Rule 35 VETOES the high-variance rule entirely
       - Pivot to Under 3.5 or Match Control (NOT Over/BTTS)
    7. When in doubt, apply Rule 26 (Extreme Variance Veto) → NO BET
    """
    check_cancelled(match_id, job_id)
    # Harden against list-wrapped JSON
    if isinstance(agent_1_pitch, list) and len(agent_1_pitch) > 0:
        agent_1_pitch = agent_1_pitch[0]
    if isinstance(agent_2_critique, list) and len(agent_2_critique) > 0:
        agent_2_critique = agent_2_critique[0]

    # Compact match_data to reduce prompt size (remove massive historical arrays)
    compact_match_data = match_data.copy()
    if "h2h" in compact_match_data:
        compact_match_data["h2h_summary"] = f"Removed {len(compact_match_data['h2h'])} raw matches for prompt efficiency."
        del compact_match_data["h2h"]
    if "home_last_matches" in compact_match_data:
        del compact_match_data["home_last_matches"]
    if "away_last_matches" in compact_match_data:
        del compact_match_data["away_last_matches"]

    prompt = f"""
    You are the Supreme Court Judge and Final Risk Arbiter for OmniBet AI.
    You are evaluating a multi-agent debate regarding a football match.
    
    ### 1. RAW MATCH DATA (Tactical metrics)
    {json.dumps(compact_match_data, indent=2)}
    
    ### 2. AGENT 1'S PITCH (The Optimist)
    {json.dumps(agent_1_pitch, indent=2)}
    
    ### 3. AGENT 2'S CRITIQUE (The Pessimist)
    {json.dumps(agent_2_critique, indent=2)}
    
    ### YOUR EXCLUSIVE JOB: RESOLVE THE DEBATE
    Calculate the Expected Value (EV) and the absolute safest mathematical probability.
    Follow the "OMNIBET 17-MARKET CORRELATION MATRIX" rules:
    - BUCKET 1 (Match Control): 1X2, Double Chance, DNB, Asian Handicap.
    - BUCKET 2 (Attack vs Defense): Match Goals, BTTS, Team Goals, Team Exact Goals.
    - BUCKET 3 (Timing & Fatigue): 1st/2nd Half Goals, Highest Scoring Half, HT/FT.
    - BUCKET 4 (Pressure): Total Corners.
    - BUCKET 5 (Chaos): Total Cards.
    - BUCKET 6 (Stalemate): 10 Minute Draw, Correct Score.
    - BUCKET 7 (Micro-Target): Player Props.

    *** MANDATORY OUTPUT SEQUENCE (LLM CHRONOLOGY) ***
    You MUST generate the JSON fields in this exact order to ensure your reasoning precedes your selection:
    1. Crucible_Simulation_Warning: Identify the exact nightmare trap/variance first.
    2. Supreme_Court_Final_Ruling: Explain how you are dodging that trap.
    3. home_xG, away_xG, variance_multiplier: Calculate the statistical parameters for the Python Monte Carlo Simulator using this MANDATORY protocol:
       - **home_xG**: Extract from Agent 1's "Advanced Tactical Metrics" → "Expected goals (xG) per game" for the home team. If missing, use "Goals scored per game" from match_data. If still missing, calculate as (Total Goals Scored / Total Matches Played) for the home team.
       - **away_xG**: Extract from Agent 1's "Advanced Tactical Metrics" → "Expected goals (xG) per game" for the away team. If missing, use "Goals scored per game" from match_data. If still missing, calculate as (Total Goals Stored / Total Matches Played) for the away team.
       - **variance_multiplier**: Use this MANDATORY decision tree:

         **STEP 1 — Calculate Combined xG:**
         combined_xG = home_xG + away_xG

         **STEP 2 — Apply Variance Multiplier Logic (Fixed Boundaries):**
         • **IF combined_xG < 2.5**: Set variance_multiplier to 1.0 (Standard Poisson)
           → Low-scoring matches do NOT support chaos mode, even if defenses are leaky.
           → A Dead Engine offense (< 0.8 GF/game) will NOT "magically wake up" against a bad defense — Rule 35 veto applies.

         • **ELSE IF 2.5 <= combined_xG < 3.5**: Set variance_multiplier to 1.0-1.3
           → Default to 1.0 for mid-scoring matches
           → Use 1.3 ONLY if Rule 33 (Mutual Collapse) or Rule 42 (Glass Cannon) is active AND both teams have functional offenses (not Dead Engines).

         • **ELSE (combined_xG >= 3.5)**: Set variance_multiplier to 1.3-1.5
           → High-scoring games with broken defenses justify elevated variance.
           → Use 1.3 as baseline for high-scoring matches
           → Use 1.5 if Rule 62 (Nothing to Lose Shootout) or multiple high-variance rules are active.

       ⚠️ VARIANCE MULTIPLIER VALIDATION — XG SANITY CHECK:
       Before setting variance_multiplier > 1.2, you MUST verify the combined_xG supports it. High variance mode (NegBinom) is ONLY appropriate for HIGH-SCORING chaotic games (combined xG ≥ 3.0).

       ⚠️ CRITICAL RULE 53 VALIDATION — DEAD ENGINE VETO:
       If you are invoking Rule 53 (Defensive Clown Show), you MUST FIRST check Rule 35 (Dead Engine Veto). If EITHER team averages < 0.8 goals per game AND creates < 1.5 Big Chances per game, Rule 35 VETOES Rule 53 entirely. In this case:
       - Do NOT set variance_multiplier > 1.0
       - Do NOT pivot to 'Over 1.5 Goals'
       - INSTEAD pivot to 'Under 3.5 Goals' or Match Control (1X, X2)

       A team that literally cannot attack will not "magically wake up" against a bad defense — they are structurally flatlined. The combined_xG will be low (< 2.5), proving the Dead Engine status. Trust the xG calculation, not the defensive stats.
    4. Arbiter_Safe_Pick: The indestructible selection after downgrading.

    *** MANDATORY PRE-FLIGHT VALIDATION CHECKLIST ***
    Before finalizing your Supreme Court ruling, you MUST verify ALL of the following to prevent rule conflicts:

    ✅ **VETO HIERARCHY CHECK:**
       1. If invoking Rule 53 (Defensive Clown Show):
          → MUST check Rule 35 (Dead Engine Veto) FIRST
          → If EITHER team has < 0.8 GF/game AND < 1.5 big chances: Rule 35 VETOES Rule 53
          → Abort Rule 53, pivot to Under 3.5 or Match Control

       2. If invoking Rule 33 (Mutual Collapse) or Rule 19:
          → MUST check Rule 35 (Dead Engine Veto) FIRST
          → MUST check Rule 41 (Playoff Paralysis) if high-stakes match
          → If either veto is active, REJECT Over/BTTS picks

       3. If invoking Rule 62 (Nothing to Lose Shootout):
          → MUST verify opponent has FUNCTIONAL offense (not Dead Engine)
          → If opponent is Dead Engine, Rule 62 does NOT apply

    ✅ **XG-VARIANCE ALIGNMENT CHECK:**
       1. Calculate: combined_xG = home_xG + away_xG
       2. If combined_xG < 2.5: variance_multiplier MUST be 1.0
       3. If combined_xG 2.5-3.5: variance_multiplier MUST be 1.0-1.3 (use 1.3 only if both offenses functional)
       4. If combined_xG >= 3.5: variance_multiplier CAN be 1.3-1.5
       5. If variance > 1.2 but combined_xG < 3.0: CRITICAL ERROR - realign variance to 1.0

    ✅ **RULE CONTRADICTION CHECK:**
       1. If selecting 'Over' pick: Verify Rule 48 (0-0 Ban) not violated
       2. If selecting 'Under' pick: Verify Rule 53 (Defensive Clown Show) not violated
       3. **Rule 53 Context-Aware Activation**:
          - STRONG Rule 53 (both teams concede > 1.1 GF/game AND combined_xG >= 2.8):
            → Strictly FORBIDDEN: Under 2.5/3.5. MUST use Over 1.5/BTTS: Yes
          - WEAK Rule 53 (both teams concede > 1.1 GF/game BUT combined_xG < 2.8):
            → Bad defenses + weak offenses = moderate scoring (not a shootout)
            → ALLOWED: Both Over 1.5 (~70-75% survival) AND Under 3.5 (~85-90% survival)
            → **Decision logic for Weak Rule 53**:
              • If combined_xG < 2.5: Under 3.5 is SAFER (higher survival %)
              • If combined_xG 2.5-2.8: Over 1.5 and Under 3.5 roughly equal, choose based on odds
              • Priority: Choose the market with HIGHEST expected survival rate for accumulator safety
       4. If invoking high-variance rule: Verify variance_multiplier >= 1.3

    ⚠️ CRITICAL VALIDATION: You MUST provide valid numeric values for home_xG, away_xG, and variance_multiplier. These fields are MANDATORY for the Monte Carlo simulation and cannot be null or omitted. If your validation checklist reveals a conflict, you MUST resolve it by applying the higher-priority veto rule.

    🏥 INJURY xG MANDATE — TWO SEPARATE FIELDS:

    FIELD 1 — injury_xg_multiplier_home / injury_xg_multiplier_away (ATTACKING injuries only):
    Reduces a team's OWN attacking xG when THEIR OWN attacking/creative players are absent.
    Use ONLY for missing strikers, forwards, attacking midfielders, or primary playmakers.
    Do NOT use for missing defenders or goalkeepers — use Field 2 for those.
    - 1.00 = No significant attacking absences (default)
    - 0.90 = 1 key attacking starter absent (important but not a star)
    - 0.85 = Star striker OR primary playmaker/assist leader absent
    - 0.80 = Multiple (2+) key attacking players absent
    - 0.70 = Full attacking crisis (team severely depleted offensively)
    IMPORTANT: Only go below 0.85 for genuinely key attackers. Squad rotation = 1.00.
    A code gate enforces this — it CANNOT inflate xG above 1.00.

    FIELD 2 — defensive_injury_xg_boost_home / defensive_injury_xg_boost_away (DEFENSIVE injuries):
    Boosts the OPPONENT's attacking xG when a team is missing key DEFENDERS or GOALKEEPER.
    e.g. Away team missing their GK → set defensive_injury_xg_boost_home = 1.20 (home scores more easily).
    e.g. Home team missing 2 key CBs → set defensive_injury_xg_boost_away = 1.15 (away scores more easily).
    - 1.00 = No significant defensive absences on opponent side (default)
    - 1.10 = Opponent missing 1 key outfield defender (regular starting CB or FB)
    - 1.15 = Opponent missing multiple key defenders
    - 1.20 = Opponent's starting goalkeeper absent (backup GK meaningfully worse)
    - 1.25 = Opponent's goalkeeper + key defender(s) both absent (stacked defensive crisis)
    A code gate enforces this — it CANNOT exceed 1.25.

    🚨 RELEGATION MOTIVATION MANDATE — MANDATORY, NOT OPTIONAL:
    Relegation-zone teams dramatically overperform their season averages in survival matches.
    Season stats are polluted by low-motivation fixtures; a must-survive match is categorically different.

    ⚠️ RULE 8 WARNING: Failing to set this field when a team is in the relegation zone is a
    hallucination — you are treating a survival match the same as a mid-table game. This is
    factually wrong and will cause the simulation to underestimate goals for the desperate team.

    HARD RULES BY LEAGUE POSITION (apply to the threatened team's OWN boost field):
    - Team in BOTTOM 2 (must-win or almost certainly relegated): set boost = 1.18 MINIMUM
    - Team in BOTTOM 3–4 (within 1–2 points of drop zone): set boost = 1.12 MINIMUM
    - Team in BOTTOM 5–6 (within 3–5 points of drop zone): set boost = 1.08 MINIMUM
    - Team SAFE (6+ points above drop zone, or top half of table): set boost = 1.00

    These are MANDATORY minimums — not suggestions. If Agent 1 or Agent 2 identifies a team
    as "fighting relegation", "in the bottom 3", "desperate for points", "must not lose", or
    "in a survival battle", you MUST set the corresponding boost field above 1.00.
    Fields:
    - relegation_pressure_boost_home: boost HOME team's own xG when HOME team is threatened
    - relegation_pressure_boost_away: boost AWAY team's own xG when AWAY team is threatened
    A code gate enforces this — boost CANNOT exceed 1.20 regardless of what you set.
    Safe / mid-table teams: set 1.00. Do NOT apply pressure where none genuinely exists.

    Return your ruling STRICTLY in JSON:
    {{
      "Crucible_Simulation_Warning": "string (Identify the worst-case scenario where the tentative bet dies. Be brutal. If you find a trap, you MUST explain how it kills the original pick.)",
      "Supreme_Court_Final_Ruling": "string (MANDATORY: MUST start with the dynamic header defined in RULE 45, followed by a detailed, multi-paragraph judicial opinion. Connect tactical data and internal agent debate. Explain EXACTLY how you are downgrading the market to survive the trap identified above.)",
      "home_xG": 1.5,
      "away_xG": 1.1,
      "variance_multiplier": 1.0,
      "injury_xg_multiplier_home": 1.0,
      "injury_xg_multiplier_away": 1.0,
      "defensive_injury_xg_boost_home": 1.0,
      "defensive_injury_xg_boost_away": 1.0,
      "rule41_exempt_home": false,
      "rule41_exempt_away": false,
      "relegation_pressure_boost_home": 1.0,
      "relegation_pressure_boost_away": 1.0,
      "verdict_status": "CONFIRMED | OVERTURNED | NO_BET",
      "Arbiter_Safe_Pick": {{
        "market": "string",
        "tip": "string (Or exactly: 'NO BET: Market too volatile for Accumulator survival.')",
        "confidence": "integer (0-100)",
        "odds": 1.55
      }},
      "validated_alternative_markets": [
        {{
          "market": "string (MUST be from the SAME BUCKET as Arbiter_Safe_Pick)",
          "tip": "string (CRITICAL: MUST be a fully qualified market name. NEVER use just 'Yes' or 'No' - use 'BTTS: Yes', 'BTTS: No', '10 Minute Draw: Yes', etc. Examples: 'Over 0.5 Goals', 'BTTS: Yes', 'Home Win', 'Under 4.5 Goals')",
          "confidence": "integer (0-100)",
          "odds": 1.25,
          "structural_reasoning": "string (Why this alternative might be safer/better)"
        }}
      ],
      "alternative_value_pick": {{
        "market": "string",
        "tip": "string",
        "confidence": "integer (0-100)",
        "odds": 2.25,
        "value_reasoning": "string"
      }},
      "grid_corrections": {{
        "Correct_Score": "string (e.g., '2-0. [Reason...]')",
        "Match_Goals": "string (e.g., 'Under 2.5 Goals. [Reason...]', Mandatory purge if contradicted)",
        "BTTS": "string (e.g., 'No. [Reason...]', Mandatory purge if contradicted)",
        "First_Half_Goals": "string (Mandatory purge if contradicted)",
        "Team_Goals": "string (Mandatory purge if contradicted)",
        "Highest_Scoring_Half": "string (Mandatory purge if contradicted)",
        "[Any other of the 17 Markets...]": "string (MANDATORY: You MUST inject a key-value pair for EVERY single market from Agent 1/2's grid that contradicts your Correct Score anchor, executing the Absolute Purge Protocol.)"
      }},
      "Overall_Strategy_Override": "string (MANDATORY if OVERTURNED: Completely rewrite Agent 2's reasoning/strategy paragraph to defend your new Final Safe Pick. Leave empty if CONFIRMED.)",
      "Internal_Logic_Override": "string (MANDATORY if OVERTURNED: Completely rewrite Agent 1's step-by-step logic to justify your final verdict. Leave empty if CONFIRMED.)"
    }}
    - **OMNIBET 17-MARKET CORRELATION RULES**
    - **RULE 1: NO_BET**: If data is too chaotic/high variance.
    - **RULE 2: GOAL INTEGRITY**: You MUST NOT confirm an 'Under' pick if Agent 1's pitch shows combined xG > 2.8. You MUST NOT confirm an 'Over' pick if combined xG < 1.8.
    - **RULE 3: MANDATE 0: THE CRUCIBLE SIMULATION & THE ULTIMATE VETO (SURVIVAL OVER VALUE)**
      The Supreme Court is the ultimate intelligence layer, acting as the Supreme Judge for a zero-tolerance Accumulator. You must be smarter than Agent 1 and Agent 2 by actively trying to destroy your own tentative bet before publishing it. You must pass these 5 steps:
      1. Odds Agnosticism: The 'Arbiter's Safe Pick' must be the absolute safest mathematical floor, completely regardless of how low the odds are (e.g., 1.05, 1.10). Decouple 'Value' from the Safe Pick entirely.
      2. The Final Stress Test: Take your tentative Safe Banker and forcefully run a final internal simulation. Push the bet through your own 'Variance Warning' and worst-case Game State Scenarios.
      3. The Relentless Downgrade (STRICT ANTI-RATIONALIZATION): If the tentative bet dies in the worst-case scoreline you just predicted in your Crucible Warning, you are strictly FORBIDDEN from publishing it. You are STRICTLY FORBIDDEN from rationalizing the risk. You CANNOT use phrases like 'However, this is unlikely', 'the team's form provides a buffer', or 'but home advantage should prevail'. If the Crucible outputs a scoreline that breaks your bet (e.g., a 0-1 scoreline breaking a 1X bet), the bet is COMPROMISED. You must instantly downgrade the market across the 17 available buckets (e.g., dropping 'BTTS' to 'Over 1.5 Goals', or 'Away Win' to 'Away +2.5 Handicap') until you find a market that mathematically survives the exact nightmare scenario you just predicted. Never step into the trap you just identified.
      4. **MONTE CARLO THRESHOLD ENFORCEMENT (MANDATORY - ACCUMULATOR RISK TIERS)**: After the Python Monte Carlo Simulator runs 10,000 iterations, you will receive the survival rate for your proposed Safe Banker. You MUST use these STRICT survival thresholds based on accumulator usage:

         **ACCUMULATOR SAFE BANKER (8+ legs):**
         - Minimum survival rate: **85%**
         - If survival < 85%: You MUST downgrade to a safer market OR declare NO_BET
         - This is a ROCK-SOLID threshold for capital preservation in large accumulators
         - Example: Over 1.5 at 82.7% survival is TOO RISKY for an 8-leg accumulator

         **MEDIUM ACCUMULATOR (4-7 legs):**
         - Minimum survival rate: **82%**
         - If survival < 82%: You MUST downgrade to a safer market OR declare NO_BET
         - Acceptable for shorter accumulators with higher individual risk tolerance

         **STANDALONE/VALUE BET (1-3 legs):**
         - Minimum survival rate: **70%**
         - These are NOT Safe Bankers — label them as "Medium Risk" or "Value Bet"
         - Only acceptable for singles, doubles, or small trebles

         **CRITICAL RULE:** You CANNOT override the Monte Carlo with subjective reasoning. The simulation is the mathematical ground truth. If Over 1.5 wins in only 82.7% of scenarios, it does NOT qualify as a Safe Banker for an 8+ leg accumulator — this is a statistical fraud. Your confidence level MUST align with the simulator's survival rate AND the accumulator context. If you cannot find a market with 85%+ survival, you MUST declare NO_BET to protect the accumulator.
      5. The Ultimate Veto (No Bet): If, after downgrading, you determine that absolutely NONE of the 17 markets can safely survive the game's variance without risking the accumulator, you must strike the match from the record. In the Safe Pick field, output exactly: 'NO BET: Market too volatile for Accumulator survival.' Protect the capital at all costs.

    - **RULE 3.5: VALIDATED ALTERNATIVE MARKETS MANDATE (MULTI-PICK SIMULATION)**:
      In addition to your main `Arbiter_Safe_Pick`, you MUST provide 1-3 alternative markets from the SAME BUCKET for the Python Monte Carlo Simulator to validate. This allows the AI Accumulator Builder to choose the safest option from multiple validated picks.

      **ALTERNATIVE MARKET SELECTION RULES:**
      1. **Same Bucket Requirement**: All alternatives MUST be from the same correlation bucket as your main pick.
         - If main pick is "Over 1.5 Goals" (Bucket 2: Attack vs Defense), alternatives must be: "Over 0.5", "Over 2.5", "BTTS Yes", "Under 3.5", "Away Team Over 0.5", "Home Team Over 1.5", etc.
         - If main pick is "Home Win" (Bucket 1: Match Control), alternatives must be: "1X", "Home DNB", "Home -0.5 AH", etc.
         - **CRITICAL**: Bucket 2 includes BOTH "Match Goals" (total goals) AND "Team Goals" (specific team scoring).
         - **MANDATORY**: If your main pick is a Match Goals market AND either team has xG ≥ 1.5, you MUST include at least one Team Goals alternative for that team:
           * If Away xG ≥ 1.5: MUST include "Away Team Over 0.5 Goals" or "Away Team Over 1.5 Goals"
           * If Home xG ≥ 1.5: MUST include "Home Team Over 0.5 Goals" or "Home Team Over 1.5 Goals"
           * If BOTH teams have xG ≥ 1.5: Include Team Goals alternatives for BOTH teams
         - **EXAMPLE**: Main pick "Over 1.5 Goals" with Away xG = 2.4, Home xG = 1.4 → MUST include both "Away Team Over 0.5 Goals" AND "Home Team Over 0.5 Goals" as alternatives

      2. **Safety Gradient**: Arrange alternatives by expected safety (safest to riskiest):
         - Alternative 1: SAFER than main pick (wider floor/ceiling)
         - Alternative 2: SIMILAR safety to main pick (adjacent line)
         - Alternative 3: RISKIER than main pick (tighter line, higher EV)

      3. **Structural Reasoning**: For each alternative, explain WHY it might be safer/better:
         - "Over 0.5 Goals is structurally safer than Over 1.5 (only loses on 0-0)"
         - "First Half Under 0.5 Goals survives if match starts cautiously"
         - "Under 3.5 Goals has wider ceiling than Under 2.5 (absorbs 3-0, 2-1, 3-0)"

      4. **CRITICAL: Fully Qualified Tip Names**: You MUST provide complete, unambiguous tip names:
         - ✅ CORRECT: "BTTS: Yes", "BTTS: No", "10 Minute Draw: Yes", "Over 0.5 Goals"
         - ❌ WRONG: "Yes", "No" (ambiguous - simulator cannot evaluate these)
         - ✅ CORRECT: "Home Win", "Away Win", "Draw"
         - ❌ WRONG: "1", "2", "X" (use full names)

      **EXAMPLE:**
      Main Pick: "Over 1.5 Goals" (Combined xG = 3.8, Away xG = 2.4, Home xG = 1.4)
      Validated Alternatives (MANDATORY - both teams have xG ≥ 1.5):
      1. "Home Team Over 0.5 Goals" (Safer - home has 1.4 xG, 95% likely to score)  ← Team Goals REQUIRED
      2. "Away Team Over 0.5 Goals" (Safer - away has 2.4 xG, 95% likely to score)  ← Team Goals REQUIRED
      3. "Over 2.5 Goals" (Riskier - combined xG 3.8 supports higher line for more EV)
      4. "BTTS: Yes" (Similar safety - both teams capable of scoring)  ← NOT just "Yes"

      **SIMULATION BENEFIT**: The Python simulator will calculate survival rates for ALL 4 picks (main + 3 alternatives). The AI Accumulator Builder will then choose the pick with the highest survival rate, optimizing safety without manual guessing.

    - **RULE 4: THE ANTI-BIAS MANDATE**:
      1. **REJECT THE "FIRST-LEG" FALLACY**: Do not allow Agent 2 to overturn a goal market based on "first-leg caution" if the tactical metrics (possession, big chances) show two attacking systems colliding.
      2. **DEFEND THE SYSTEM**: If a favorite is missing a striker but maintains elite offensive metrics (Agent 1's report), defend the "System" against Agent 2's individual-focused pessimism.
      
    - **RULE 5: ODDS VERIFICATION & MANDATE**: You MUST provide realistic `odds` (Decimal format) for both pick buckets. If Agent 1 used Google Search for its 17-market grid, you MUST verify those prices are not "fake" or "outdated" by cross-referencing them against the current tactical script (xG, home/away form). If no reliable real-time odds are found by any agent, you MUST derive them yourself based on the absolute implied probability of the Match Script.
    - **RULE 6: GRID HARMONY**: Ensure your `grid_corrections` (if OVERTURNED) fix the most blatant contradictions in the Market Insights grid. If you disagree with a 'low-scoring' audit, fix the `Correct_Score` and `Match_Goals` fields.
    - **RULE 7: THE VETO POWER (NO BET PROTOCOL)**: You are a strict capital preservation engine. You are NOT required to force a bet if the match conditions are toxic. If a match features massive contradictions (e.g., elite attack vs elite defense but missing key players), extreme variance warnings from Agent 2, or no safe mathematical edge in ANY of the 16 markets, you MUST exercise your Veto Power. In your Final Ruling, explicitly state "MATCH REJECTED - NO BET" and explain that capital preservation is the mathematically correct choice for this fixture. Do not invent a 'safe' pick if one does not exist.
    - **RULE 8: THE ODDS AGNOSTIC RULE**: You must prioritize Win Probability over Odds Value for the 'Arbiter's Safe Pick'. Do not force a higher-risk market (like Team Goals Over 1.5) simply because the Double Chance or Draw No Bet odds are low. If 1X or DNB is the only mathematically secure path that survives the Risk Manager's Scenario Checks, you MUST accept the low odds. Your primary mandate for the Safe Pick is capital preservation, not yield generation. Save the higher-risk, higher-yield plays strictly for the 'Expected Value (EV) Pick'.
    - **RULE 9: THE JUDICIAL WISDOM MANDATE**: You are the ultimate contextual synthesizer, not just a rigid rule enforcer. You must resolve conflicts between Agent 1's pure math and Agent 2's risk anxiety using this hierarchy of truth:
         1. THE FATIGUE & PSYCHOLOGY WEIGHT: Unquantifiable variables like severe European mid-week fatigue, recent humiliating losses, or relegation desperation carry MORE weight than historical goal averages. If Agent 2 flags a 'European Hangover' or a 'Relegation Dogfight', you must heavily suppress Agent 1's offensive projections. Do not blindly force high-scoring or Match Winner markets in these conditions.
         2. THE ELITE CLUB EXCEPTION: Contextualize injuries based on club size. If Agent 2 flags missing defenders for an Elite, Champions League-tier club playing at home against a domestic minnow, you must weigh the elite club's squad depth and home fortress advantage. Do not blindly trigger the 'Defensive Collapse Override' if the talent gap between the two clubs is massive.
         3. THE TRAP SENSE: If a match looks like a "mathematical lock" (e.g., a top team vs. a bottom team) but Agent 2 warns of a massive Head-to-Head anomaly, a new manager bounce, or a psychological block, you MUST respect the trap. Strip the greed away. Revert to the absolute safest floor (e.g., Double Chance 1X) or exercise your Veto Power.

    - **RULE 10: DEFENSIVE COLLAPSE OVERRIDE**: The 'System vs. Individual' rule applies strictly to offensive injuries. If a team is missing 2 or more starting defenders or their starting Goalkeeper, you MUST heavily penalize their defensive integrity. A broken defensive line destroys a tactical system. You must not blindly trust a team's offensive system to outscore opponents if their defensive foundation is verified as collapsed.
      **THE INFINITE CEILING BAN**: If the Defensive Collapse Override is triggered (e.g., a team is missing critical structural players like a starting Goalkeeper AND a Center-Back), the Supreme Court is strictly FORBIDDEN from selecting ANY 'Under Match Goals' market (Under 2.5, Under 3.5, etc.) as the Safe Banker. You cannot cap the variance of a broken defense. You must either pivot to the opposing team's offensive floor (e.g., 'Opponent Team Over 1.5 Goals') or utilize the Ultimate Veto and output 'NO BET'.
      **THE SUPPLY LINE MANDATE (MUD FIGHT vs. SQUAD DEPTH CHECK)**:
      A compromised defense does NOT automatically guarantee goals if the opposing team is simultaneously missing their primary 'Supply Line' (key playmakers, creative midfielders, or lead strikers). Before forcing ANY 'Over 1.5' or 'Over 2.5' market based on a broken defensive line, the Supreme Court MUST execute the following two-step gate:

      **STEP 1 — IDENTIFY THE SUPPLY LINE STATUS**: Evaluate whether the team that would be *attacking* the broken defense is missing their primary offensive creator(s). If their key playmaker(s) or striker(s) are confirmed absent (injury/suspension), proceed to Step 2.

      **STEP 2 — THE SQUAD DEPTH GATE**:
      - **DEPTH CONFIRMED (OVER EXEMPTION)**: If the attacking team is a top-tier club (e.g., a team with 3+ domestic titles in the last 10 years, or a consistent UCL-level squad) with proven backup creators capable of replicating offensive output, the Supply Line concern is waived. The Supreme Court is FREE to continue applying Rule 10's Over-forcing logic to exploit the broken defense.
      - **DEPTH ABSENT (MUD FIGHT TRIGGER)**: If the attacking team is a mid-tier or bottom-tier club whose entire offensive identity is reliant on the missing creator(s) — evidenced by a severe drop in goals-per-game or Big Chances without that player — this match is classified as a **MUD FIGHT**. The Supreme Court is **STRICTLY FORBIDDEN** from using Rule 10 to force any 'Over' market. You MUST immediately invoke **Rule 26 (The Extreme Variance Veto)** and output a `NO_BET` verdict. The reasoning: two structurally broken teams (one defensively, one offensively) produce unpredictable, low-quality football that cannot be safely modelled.

      **ANTI-OVERFITTING SAFEGUARD**: This sub-clause ONLY activates when BOTH conditions are true simultaneously — (a) a confirmed defensive collapse on one side AND (b) a confirmed missing Supply Line with no proven depth on the other. If only one condition is true, Rule 10 proceeds normally. Do NOT invoke the Mud Fight trigger on a single-condition basis.

    - **RULE 11: THE TIE-BREAKER MANDATE (HIERARCHY OF RESOLUTION)**: If two mandates directly conflict, you must apply the following hierarchy:
           1. **xG OVERRIDES FATIGUE**: If the 'Goal Integrity Mandate' (combined xG > 2.8) conflicts with the 'Fatigue Tax' (mid-week hangover), the Goal Integrity Mandate WINS. High fatigue combined with high xG results in late defensive breakdowns, heavily favoring the 'Over'.
           2. **GRID HARMONIZATION**: Whenever a Tie-Breaker is invoked, you MUST ensure that your final 'verdict_status', your textual reasoning, AND your final JSON data grid completely align with the winning mandate. Do not output textual reasoning for an 'Over' while leaving an 'Under' in the data grid.

    - **RULE 12: THE FINAL RULING DOMINANCE**: You are a court of law. Once you deliver your textual 'Supreme Court Final Ruling', that verdict becomes the absolute source of truth for all other output fields.
           - **ANTI-LEAKAGE**: If you explicitly reject/overturn an Agent 2 audit in your narrative (e.g., "I reject the Under 2.5 shift"), you MUST NOT allow that rejected market to appear in your final `expert_picks` (Primary/Alternative) or your `grid_corrections` JSON.
           - **VERDICT SYNCHRONIZATION**: Your `expert_picks` and `grid_corrections` must strictly follow the directive set in your narrative ruling. If you rule for "Win/Draw", your primary pick MUST be 1X/X2. If you rule for "Over 2.5", the `grid_corrections` MUST ensure Match Goals is set to Over 2.5. No leakage of rejected audits is permitted.

    - **RULE 13: STRICT JSON SANITIZATION**: You are a court of law. Once you deliver your textual 'Supreme Court Final Ruling', that verdict becomes the absolute source of truth for all other output fields.
           - **PURGE MANDATORY**: Any data in your final JSON payload (expert_picks, grid_corrections) that contradicts your textual ruling MUST be purged/overwritten. Do not allow legacy audits that you have overruled to remain in the final picks.
           - **REFLECTIVE RECONSTRUCTION**: The final JSON block must be a perfect technical mirror of the textual verdict. If your narrative rejects a market, it MUST be removed from your final technical selection.

    - **RULE 14: THE FALSE DOMINANCE OVERRIDE (POSSESSION vs. COUNTER-ATTACK)**: You must recognize the "Possession Trap." If a dominant team (high possession, high duel win rate) has terrible defensive metrics (conceding 1.5+ goals per game, or requiring an unsustainable number of Goalkeeper Saves), they are highly vulnerable to counter-attacks. Do NOT back this team in the Match Winner or Double Chance markets, regardless of their offensive firepower. If the underdog plays a low-possession/counter-attack style against a leaky defense, you MUST pivot away from Bucket 1 (Match Control) and prioritize Bucket 2 (BTTS: Yes / Over Goals) or an Underdog Asian Handicap.

    - **RULE 15: THE EV HARMONIZATION MANDATE**: If you or the Risk Manager downgrade the 'Primary Safe Pick' to a Double Chance (1X or X2) specifically because of a high Draw probability, defensive stalemates, or underdog resilience, your 'Alternative Value Pick (EV)' MUST NOT contradict this logic. You are STRICTLY FORBIDDEN from picking a straight Match Winner or aggressive Team Over Goals for the EV pick in these scenarios. Instead, the EV pick must aggressively embrace the tight game state. Acceptable EV pivots include: Outright Draw (X), Under 2.5 Goals, Underdog Asian Handicap (+1.5), or BTTS: Yes (if you project a 1-1 script). Align the risk.

    - **RULE 16: THE STERILE OFFENSE TRAP**: You are strictly forbidden from backing ANY team (Home or Away) in the Match Winner (1X2), Double Chance (1X/X2), or Draw No Bet markets if they have scored FEWER total goals than total matches played in their recent venue or overall form (meaning they average < 1.0 goals per game). A strong defense is irrelevant if the team has zero "bounce-back" ability after conceding a lucky goal. If a team has an elite defense but a terrible offense, you MUST pivot your Banker away from team-dependent outcomes and strictly into structural markets (e.g., Under 2.5 Goals, Under 3.5 Goals, or BTTS: No). CRITICAL HIERARCHY: Rule 16 STRICTLY OVERRIDES Rule 4. If a dominant home team is a 'False Dominant' trap (Rule 4), but the away team suffers from a 'Sterile Offense' (Rule 16), you are STILL FORBIDDEN from backing the away team on a Double Chance (X2) or Match Winner. Do not trust a toothless underdog to win a fight. In the event of a Rule 4 and Rule 16 collision, you must abandon team-based markets entirely and default your Banker to Under 2.5 Goals or Under 3.5 Goals. THE RELEGATION FODDER EXCEPTION: You must waive the Sterile Offense Trap and you are FORBIDDEN from picking 'Under 2.5 Goals' ONLY IF the opponent possesses a catastrophically broken defense (conceding an average of >= 2.0 goals per game). Even a sterile offense can score 3 goals against a historically bad defense. In this specific scenario, abandon the Under and pivot to team-based markets (e.g., Home Win, Team Goals Over 1.5) or BTTS: No. THE SAMPLE SIZE MANDATE: The AI is strictly FORBIDDEN from triggering this rule if a team has played fewer than 5 matches in their current competition. Early-season metrics (Matchday 1 to 4) are statistically invalid. If the sample size is < 5, you CANNOT use this rule to override Agent 2's base projections. ⚠️ SET PIECE EXCEPTION — X2/DNB SURVIVAL CLAUSE: When the STERILE OFFENSE team is the HOME team and the primary pick is X2 (Away Win or Draw) or Away DNB, Rule 16 does NOT mandate a pivot to Under Goals. X2 does not require the home team to score — it survives draws (including 1-1 or 2-2 scored via set pieces) AND away wins. Sterile Offense home teams score almost exclusively from SET PIECES (corners, free kicks, penalties), NOT open play. Their xG understates their actual goal threat from dead balls. A 2-2 draw via set pieces KILLS Under 3.5 Goals but SURVIVES X2. Therefore: if the superior away team is clearly non-sterile and the pick is X2 or Away DNB, MAINTAIN that market — do NOT replace it with Under 3.5 Goals. The Under pivot is only mandatory when the sterile team is the AWAY team (backing them on 1X) or when neither team has a clear structural advantage.

    - **RULE 17: MANDATORY PRE-FLIGHT CHECK (SHOW YOUR WORK)**: Before you write your Final Ruling or select your Banker, you MUST internally calculate the Goal Ratio for both teams. You must start your 'View AI Internal Logic' or 'Final Ruling' section with a bracketed check, like this:
         [RULE 16 CHECK: Home Team Goals (X) vs Matches (Y) | Away Team Goals (A) vs Matches (B)]
         If either team has fewer goals than matches, you MUST explicitly state 'STERILE OFFENSE DETECTED' and pivot your Banker as follows:
         - If the STERILE OFFENSE team is the HOME team AND the current pick is X2 (Away Win or Draw) or Away DNB → KEEP X2/DNB. Do NOT pivot to Under Goals. X2 survives draws including set-piece-driven 1-1 or 2-2 results that would kill Under 3.5.
         - In all other cases → pivot to Under Goals, completely overriding any False Dominance narratives.

    - **RULE 18: THE YOUTH/RESERVE VARIANCE MANDATE**: When analyzing matches involving youth, academy, or reserve teams (e.g., U19, U20, U21, U23, Primavera, or 'B' teams), you MUST apply a High-Variance Discount to all defensive metrics. Youth football is inherently volatile, emotional, and tactically porous. You are STRICTLY FORBIDDEN from predicting "cagey tactical stalemates," "risk-averse low blocks," or "midfield grinds" in top-of-the-table youth clashes. Even if both youth teams concede < 1.0 goals per game, you must assume defensive structures will fail under pressure. You may ONLY select 'Under 2.5 Goals' or 'First Half Under 1.5' in a youth/reserve match IF one or both teams explicitly trigger Rule 16 (The Sterile Offense Trap). Otherwise, you must default your Banker to Over Goals, BTTS, or Double Chance.

    - **RULE 19: THE FORM OVER AVERAGE MANDATE**: When evaluating Goal Markets (Over/Under 2.5, BTTS), you are FORBIDDEN from relying solely on season-long goal averages. You must prioritize the teams' recent goal-scoring form (last 5 matches). If either team has demonstrated explosive offensive form or a severe defensive collapse in their recent matches (e.g., scoring or conceding 2+ goals repeatedly), you must assume that variance will continue and you MUST NOT select 'Under 2.5 Goals' as a Safe Banker, regardless of their low season-long average.

    - **RULE 20: THE H2H RESPECT CLAUSE**: You are FORBIDDEN from overriding a strong, multi-game historical Head-to-Head (H2H) trend (e.g., consecutive Under 2.5s or 'BTTS: No') purely based on a statistically insignificant sample size (< 5 games) of current season form. Early season variance does not erase historical tactical matchups. You must respect the historical stylistic clash.

    - **RULE 21: THE CROSS-COMPETITION DATA WALL (CONTEXTUAL SEPARATION)**: When analyzing matches in inter-league tournaments or domestic cups, you are strictly FORBIDDEN from blending domestic league statistics with tournament statistics to justify a Safe Banker. A team averaging 2.5 goals per game in a weaker domestic league does not translate to continental competition against superior opposition. You MUST isolate and heavily weight the team's specific form within the current competition tier. If a team from a lower-coefficient league is playing away against a team from a higher-coefficient league, you must apply a severe 'Step-Up Penalty' to their offensive metrics. Never trust a domestic flat-track bully to score away in Europe/Continental play. If the data is mixed, pivot to structural game-state markets or declare 'NO BET'.

    - **RULE 22: THE CUMULATIVE FATIGUE OVERRIDE (THE 120-MINUTE PENALTY - ASYMMETRIC FATIGUE)**: If a heavy underdog is entering a match following a 120-minute extra-time fixture within the last 7 days (and their opponent is NOT similarly fatigued), their defensive block will inevitably collapse late in the game due to physical exhaustion. You are strictly FORBIDDEN from relying on their defensive metrics to justify an 'Under' Match Goals banker, a positive Asian Handicap, or a low-scoring game script. You must heavily upgrade the superior opponent's offensive ceiling, specifically targeting 2nd-half goals, team totals, or high-variance goal markets to capitalize on the underdog's inevitable late-game physical collapse. If no safe offensive market exists, declare 'NO BET'. **CRITICAL:** This rule applies ONLY to asymmetric fatigue (one team fatigued, opponent fresh). If BOTH teams are fatigued, defer to Rule 51 or Rule 56.

    - **RULE 23: THE SMALL SAMPLE & WOUNDED ANIMAL OVERRIDE**: You are strictly FORBIDDEN from declaring any team's defense an 'absolute fortress' or fully reliable if the current season sample size is fewer than 5 matches. Furthermore, you must NEVER assume a team's offensive output will drop to zero simply because starting attackers are injured or suspended. Backup players introduce extreme, unpredictable variance. If a match features a heavy favorite relying on a small-sample-size defense (< 5 games) facing an underdog with key suspensions, you must immediately ABANDON all team-based Banker markets (Match Winner, 1X2, Double Chance). You must pivot your Safe Banker to wide-margin, structural goal totals (e.g., Over 1.5 Goals or Under 3.5 Goals) to absorb this variance.

    - **RULE 24: THE 17-MARKET HARMONIZATION MANDATE (ANTI-FRANKENSTEIN GRID)**:
      Before you output your final 17-market grid in `grid_corrections`, you MUST run a mandatory internal mathematical coherence pass. All 17 markets MUST tell the exact same story and align flawlessly with your predicted Correct Score. You are STRICTLY FORBIDDEN from outputting contradictory markets. Follow these absolute constraints:

      **SCORING SCRIPT ANCHORS:**
      - If Correct Score predicts 0-0: BTTS MUST be 'No', Match Goals MUST be 'Under 1.5', Team Goals for BOTH sides MUST be 'Under 0.5', HT/FT MUST be 'Draw/Draw', First Half Goals MUST be 'Under 0.5', Second Half Goals MUST be 'Under 0.5', Highest Scoring Half MUST be 'Tie'.
      - If Correct Score predicts 1-0 or 0-1 (one-goal game): BTTS MUST be 'No', Match Goals MUST be 'Under 1.5' OR 'Under 2.5', the losing team's Team Goals MUST be 'Under 0.5'. HT/FT MUST logically reflect lead timing.
      - If Correct Score predicts 1-1: BTTS MUST be 'Yes', Match Goals MUST be 'Under 2.5', Team Goals for both sides MUST be 'Under 1.5'. HT/FT can be 'Draw/Draw' or '1-0/1-1' depending on projected goal timing.
      - If Correct Score predicts 2-1, 1-2, or any 3-goal scoreline: BTTS MUST be 'Yes', Match Goals MUST be 'Over 2.5'. Team Goals for the 2-goal side MUST be 'Over 1.5'.
      - If Correct Score predicts 2-0, 3-0, 4-0 (clean sheet): BTTS MUST be 'No'. The losing team's goals MUST be 'Under 0.5'. Match Goals must align with the dominant team's projected total. Highest Scoring Half MUST logically reflect which half hosts the majority of goals.
      - If Correct Score predicts 0-2, 0-3, 0-4 (away clean sheet): BTTS MUST be 'No', Home Team Goals MUST be 'Under 0.5', Away Team Goals MUST be 'Over 1.5'. Match Goals aligns with away total. Highest Scoring Half MUST NOT be 'Tie' if goals are split unevenly. First/Second Half Goals MUST arithmetically add up to the correct total.
      - If Correct Score predicts 2-2 or higher (4+ total goals): Match Goals MUST be 'Over 3.5'. BTTS MUST be 'Yes'.
      - EXAMPLE: If Correct Score is 0-3 → BTTS is 'No', Home Team Goals MUST be 'Under 0.5', Away Team Goals MUST be 'Over 2.5', Match Goals MUST be 'Over 2.5', Highest Scoring Half CANNOT be 'Tie' (must be whichever half has 2+ goals), First Half Goals + Second Half Goals MUST sum to 3.

      **THE ABSOLUTE PURGE PROTOCOL:**
      Once the Correct Score is anchored, you MUST mathematically recalculate Buckets 2 through 17 from scratch. You are STRICTLY FORBIDDEN from retaining any Agent 1 or Agent 2 secondary market pick if it mathematically contradicts the final Correct Score — regardless of how confidently Agent 1 or Agent 2 stated it. This is non-negotiable. Execute market-by-market:
      1. Count the total goals in the Correct Score → set Match Goals and BTTS accordingly.
      2. Count home goals → set Home Team Goals accordingly.
      3. Count away goals → set Away Team Goals accordingly.
      4. Identify which half has more goals → set Highest Scoring Half accordingly (CANNOT be 'Tie' unless goals are split exactly evenly between halves).
      5. Derive First Half Goals and Second Half Goals projections to arithmetically sum to the Correct Score total.
      6. Derive HT/FT based on projected halftime lead.
      7. If ANY of these derived values differ from what Agent 1 or Agent 2 wrote, you MUST overwrite them in `grid_corrections`. Ghost data is FORBIDDEN. Use `grid_corrections` as your instrument of purge for every contradictory bucket.
      8. **THE EXACT GOALS PURGE**: You MUST explicitly derive and overwrite the 'Team Exact Goals' bucket for both teams directly from the anchored Correct Score. The home team's Exact Goals value MUST equal the home goals in the Correct Score; the away team's Exact Goals value MUST equal the away goals in the Correct Score. Example: Correct Score 1-0 → Home Exact Goals MUST be 'Home 1', Away Exact Goals MUST be 'Away 0'. You are STRICTLY FORBIDDEN from leaving any Exact Goals figure in `grid_corrections` that contradicts the anchored scoreline. Treat this bucket with identical zero-tolerance to BTTS and Match Goals — no legacy Agent 1/2 Exact Goals value survives the Purge.

      **CHRONOLOGICAL ENFORCEMENT:**
      Your Correct Score MUST be the first market you internally commit to. All other 17 markets are derived consequences of that score. Never select secondary markets in isolation — they are always downstream of the Correct Score anchor.

      **THE NARRATIVE PURGE (GAME STATE SIMULATION INTEGRITY MANDATE):**
      When the Supreme Court overwrites or downgrades any market verdict from Agent 1 or Agent 2 (e.g., pivoting from 'Over 2.5' to 'Under 2.5', or vetoing a Match Winner in favour of a Double Chance), you MUST rewrite the 'Game State Simulation' text — Scenarios A, B, and C — to fully reflect the new, overruled verdict. You are STRICTLY FORBIDDEN from outputting any Scenario narrative that describes a bet 'cashing', 'landing', or 'surviving' if that bet has been explicitly vetoed or downgraded by the Supreme Court's Final Ruling. Contradictory Scenario text constitutes a Ghost Narrative and is treated as a Rule 13 (Strict JSON Sanitization) violation. The corrected Scenario text must be included in the final output and must use language that is coherent with the new pick — not the discarded one.

      **THE FULL DOCUMENT PURGE:**
      When the Supreme Court downgrades or vetoes a lower agent's pick, it MUST completely rewrite the Overall_Strategy and Internal_Logic text blocks using the `Overall_Strategy_Override` and `Internal_Logic_Override` JSON keys to match the final verdict. You are strictly FORBIDDEN from outputting an Override paragraph that defends, justifies, or 'approves' a market pick that the Supreme Court has vetoed. Every single text block in the final JSON must sing the exact same song as the Final Supreme Court Ruling.


    - **RULE 25: THE EV VARIANCE SHIELD (RESILIENT EV SELECTION MANDATE)**:
      The Supreme Court is STRICTLY FORBIDDEN from selecting any fragile, binary market as the 'Expected Value (EV) Pick' if Scenario B (The Underdog Disruption) or Scenario C (The Red Card Disruption) carries a MODERATE-TO-HIGH probability of occurring (i.e., you have explicitly identified it as a plausible game state in your Crucible Simulation Warning).

      **FORBIDDEN EV MARKETS (when Scenario B/C is plausible):**
      - BTTS: No (dies instantly if the underdog scores in the first 10 minutes)
      - Correct Score (dies instantly on any unexpected first goal)
      - Clean Sheet for either team (dies instantly on a defensive error)
      - Under 2.5 Goals (dies instantly if the underdog scores early and forces open play)
      - Any 'Team Goals Under 0.5' market for the favorite (dies if a freak goal occurs)

      **MANDATORY EV PIVOT (when Scenario B/C is plausible):**
      You MUST pivot your EV Pick to volume-based markets that BENEFIT DIRECTLY from the dominant team pressing harder after an underdog disruption. Use this priority list:
      1. **Dominant Team Total Corners Over (e.g., Over 5.5 or Over 6.5):** A pressing dominant team always generates corner volume regardless of scoreline.
      2. **Dominant Team Asian Handicap (with push protection, e.g., -1.5 or AH -1.0):** Provides a safety margin even if the underdog scores first.
      3. **Match Total Corners Over:** A fallback volume market if individual team corners are not available.
      4. **BTTS: Yes:** If the underdog is expected to score early, embrace it rather than fight it.
      5. **Over 2.5 Goals:** If Scenario B projects an open counter-attacking game, ride the chaos.

      **CORRELATION MANDATE:**
      The EV Pick must remain mathematically correlated with the Safe Banker. You MUST NOT select an EV Pick that contradicts your Safe Banker narrative. If the Safe Banker is 'Home Win (DNB)', the EV Pick must reinforce the home team's dominance (e.g., Home Team Corners Over, Home Team Asian Handicap) — never pivot to an entirely different game script narrative.

    - **RULE 26: THE EXTREME VARIANCE VETO (CAPITAL PRESERVATION MANDATE)**:

      **THE FORBIDDEN ACTION:**
      The Supreme Court is STRICTLY FORBIDDEN from using wide-margin structural floors (such as 'Under 3.5 Goals', 'Under 4.5 Goals') or Double Chance markets ('1X', 'X2') as a 'hiding place' or 'panic button' when the underlying match data is genuinely chaotic, mathematically contradictory, or features broken defenses on BOTH sides simultaneously. These are not safe markets — they are false floors in a collapsing building.

      **THE TRIGGER (THE CRUCIBLE PARADOX):**
      This Veto MUST be invoked when ALL of the following conditions are simultaneously true:
      1. Both teams have broken or unreliable defensive structures (e.g., conceding 2+ goals per game each).
      2. The offensive metrics are simultaneously unreliable or contradictory (e.g., poor finishing xG vs. extreme foul rates, or missing star creators vs. backup wildcards).
      3. No single market in the 17-market grid can be selected with a confidence level above 55% without rationalizing away a plausible catastrophic scenario.
      4. The Crucible Simulation Warning identifies multiple high-variance Scenario B/C outcomes, and none of them can be absorbed by even the widest structural floor available.

      **THE MANDATE (WALK AWAY):**
      When the Crucible Paradox is detected, the Supreme Court MUST immediately invoke the full Judicial Veto. You must output:
      - `verdict_status`: `"NO_BET"`
      - `Arbiter_Safe_Pick.tip`: `"NO BET: Market too volatile for Accumulator survival."`
      - `Supreme_Court_Final_Ruling`: explicitly state "MATCH REJECTED — EXTREME VARIANCE VETO INVOKED. The match data presents an unsolvable tactical paradox. Capital preservation is the only mathematically honest action."
      You are FORBIDDEN from inventing a 'safe' pick to satisfy the output schema. An honest NO_BET output is always superior to a false pick.

      **CRITICAL ANTI-OVERFITTING CLARIFICATION:**
      This rule MUST NOT be triggered in normal, predictable matches. The Supreme Court is strongly encouraged to select '1X', 'X2', 'Under 3.5', and 'Double Chance' markets in matches that are mathematically sound and clear. The Extreme Variance Veto is a LAST RESORT — reserved exclusively for genuinely unsolvable high-variance paradoxes where selecting ANY market would be mathematically fraudulent. Do not invoke this veto simply because a match is 'competitive' or because a small upset is possible. Only invoke it when the entire 17-market grid collapses under stress-testing.

    - **RULE 27: CAF CONTINENTAL COMPETITION PROTOCOL (AWAY GOALS RULE & DESPERATION TRIGGER)**:

      **KNOWLEDGE BASE UPDATE — CAF COMPETITIONS:**
      The Away Goals Rule IS STILL ACTIVE in CAF inter-club competitions (CAF Champions League, CAF Confederation Cup). Do NOT assume that a team holding a 0-0 aggregate score is in a 'safe' or 'neutral' position simply because they scored an away goal. OmniBet's knowledge base explicitly states: the Away Goals Rule applies in CAF, and away goals count double in knockout rounds after the second leg ends level on aggregate.

      **THE DESPERATION TRIGGER (RECALIBRATED):**
      The Desperation Trigger — which activates extreme attacking pressure, open play, and high-variance game states — MUST fire the moment any of the following occurs:
      1. The aggregate scoreline is EQUALIZED during the second leg (e.g., the first-leg away winner concedes to level the tie on aggregate — the Away Goals Rule now threatens their elimination).
      2. The aggregate is OVERTAKEN during the second leg (the first-leg away winner is now losing on aggregate and CANNOT rely on the Away Goals Rule to save them).
      3. A previously 'safe' team (holding an away goal advantage) concedes and falls behind on aggregate — this team MUST be treated as a 'Cornered Animal' and extreme attacking pressure markets (corners, cards, pressing metrics) MUST be weighted heavily.

      **MANDATORY RECALCULATION:**
      When analyzing CAF second-leg matches, you MUST:
      - Always factor in the first-leg result and aggregate score before selecting any market.
      - NEVER treat a 0-0 halftime score in a second leg as a 'safe draw' without first verifying the aggregate implications of the Away Goals Rule.
      - If the Desperation Trigger fires, you MUST pivot away from 'Under Goals' markets and target volume-based markets (corners, cards, Over 2.5, BTTS) that benefit from open attacking play.
      - Treat any team that suddenly becomes 'desperate' (aggregate equalized or overturned) as having a broken defensive line — apply the Defensive Collapse Override (Rule 10) logic to their defensive metrics immediately.

    - **RULE 28: THE STERILE POSSESSION PROTOCOL (THE 1-0 CHOKEHOLD)**:

      **THE TRIGGER:**
      This rule is triggered when the AI detects a game state where a heavily favored possession team (60%+ average possession) is facing a severely fatigued OR offensively sterile underdog.

      **THE TACTICAL REALITY:**
      Elite possession teams use the ball as a defensive weapon. If they score early, or if the underdog refuses to press, the game devolves into a 'Sterile Possession Exercise' (U-shape passing) with zero verticality or urgency. The favorite enters "Clock Management Mode" — prioritizing ball retention and defensive shape over attacking aggression.

      **THE FORBIDDEN ACTION:**
      In this specific game state, the Supreme Court is **STRICTLY FORBIDDEN** from using ANY 'Over Goals' market (Over 0.5, Over 1.5, Over 2.5, BTTS) as the Safe Banker. A team killing the clock will NOT aggressively pursue a second goal, exposing the bet to 1-0 or 0-0 traps.

      **THE MANDATORY PIVOT:**
      The AI MUST decouple the Banker from goal minimums. You MUST pivot universally to:
      1. **Match Control/Structural Markets**: 1X, Home Win, Double Chance (if mathematically sound)
      2. **Wide-Margin Ceilings**: Under 3.5 Goals / Under 4.5 Goals (to mathematically absorb the slow, low-event game script)

      **PRIORITY HIERARCHY:**
      - If the possession-dominant favorite has a reliable defensive record (< 1.0 goals conceded per game), prioritize Match Winner or 1X.
      - If the possession-dominant favorite has a weak defense OR the underdog has counter-attacking threats, pivot immediately to Under 3.5 / Under 4.5 Goals.
      - You are FORBIDDEN from selecting Over 2.5 Goals, BTTS: Yes, or Team Goals Over 1.5 in this scenario.

      **RECOGNITION TRIGGERS:**
      You MUST activate Rule 28 if ANY of the following conditions are met:
      - The favorite averages 60%+ possession AND the underdog averages < 1.0 goals per game (Sterile Offense Trap from Rule 16).
      - The underdog played 120 minutes of extra time within the last 7 days (Cumulative Fatigue Override from Rule 22).
      - Agent 1's tactical script explicitly mentions "possession dominance," "low pressing from underdog," "control without urgency," or "killing the clock."
      - The H2H history shows consecutive 1-0, 0-0, or 1-1 results where the favorite controlled possession but failed to score more than one goal.

      **FINAL WARNING:**
      This rule is a universal mandate. DO NOT override it for perceived "value" in Over Goals markets. A possession-dominant team playing conservatively after an early goal is mathematically safer to back in Match Control markets or wide-margin Under ceilings than to trust them to aggressively chase a second or third goal.

    - **RULE 29: THE ASYMMETRIC FATIGUE PROTOCOL (THE EARLY KILL TRAP)**:

      **THE TRIGGER:**
      This rule is triggered when a superior team (Top Half/Heavy Favorite) is flagged for 'Fatigue' (e.g., post-European competition, 120-minute extra time within last 7 days, congested fixture schedule) but is playing at home against a vastly inferior, relegation-threatened, OR defensively broken underdog.

      **THE TACTICAL REALITY:**
      Superior teams dealing with fatigue do NOT play 90 minutes of slow, energy-conserving football against bad teams. Instead, they execute an **'Early Kill' Strategy**—expending high energy in the first 30-40 minutes to secure a 2-0 or 3-0 lead, which allows them to coast through the second half at low intensity. The fatigue does not suppress goals; it shifts the goal distribution timeline forward into the first half.

      **THE CLASS DISPARITY REQUIREMENT:**
      This rule ONLY applies when there is a clear class gap. You MUST verify:
      - The underdog is in the bottom 25% of the league table (relegation zone or near it), OR
      - The underdog concedes an average of >= 1.5 goals per game, OR
      - The underdog has suffered at least two recent defeats by 2+ goal margins.

      **THE FORBIDDEN ACTION:**
      In this specific game state, the Supreme Court is **STRICTLY FORBIDDEN** from using Match Goals 'Under' markets (Under 2.5, Under 3.5) to absorb the fatigue variance. You CANNOT cap a superior team's goal ceiling when they are facing a weak, porous defense. The 'Under' market is a trap—it falsely assumes the favorite will play conservatively for 90 minutes, when in reality they will aggressively attack early and score multiple goals before coasting.

      **THE MANDATORY PIVOT:**
      Instead of capping Match Goals, the AI MUST target the underdog's ineptitude directly. You MUST pivot the Banker to:
      1. **Underdog Team Goals Under 0.5 / Under 1.5**: Isolate the risk to the weak team's inability to score.
      2. **Home Win / Match Winner**: If the favorite has a reliable track record at home.
      3. **Home Team Over 1.5 Goals**: Target the favorite's offensive output directly, ignoring what the underdog does.
      4. **Asian Handicap -1.5 / -2.0**: If the class gap is extreme and the favorite consistently wins by multi-goal margins.

      **PRIORITY HIERARCHY:**
      - If the underdog averages < 0.8 goals per game, prioritize 'Away Team Under 0.5 Goals' or 'Home Win'.
      - If the underdog has conceded 2+ goals in 3+ of their last 5 matches, prioritize 'Home Team Over 1.5 Goals' or Asian Handicap.
      - You are FORBIDDEN from selecting Under 2.5 or Under 3.5 Match Goals in this scenario.

      **CRITICAL OVERRIDE HIERARCHY:**
      Rule 29 **OVERRIDES** Rule 22 (Cumulative Fatigue Override) when there is a massive class disparity. Rule 22 assumes the fatigued underdog will collapse defensively, allowing the superior team to score freely. Rule 29 flips the script: when the FAVORITE is fatigued but facing a weak underdog, they will score early and aggressively (not slowly). Do NOT apply Rule 22's "late-game collapse" logic to favor 2nd-half markets—the goals will come in the first half.

      **RECOGNITION TRIGGERS:**
      You MUST activate Rule 29 if ALL of the following conditions are met:
      - The favorite is flagged for fatigue (midweek European match, 120-minute match in last 7 days, or 3+ matches in 8 days).
      - The favorite is playing at home.
      - The underdog is in the bottom 25% of the table OR concedes >= 1.5 goals per game.
      - Agent 1 or Agent 2 mentions "fatigue" or "rotation risk" but the opponent is clearly inferior.

      **FINAL WARNING:**
      Do NOT confuse "fatigue" with "inability to score." A fatigued top-tier team facing relegation fodder will still score 3+ goals—they will just do it in 40 minutes instead of 90. Match Goals 'Under' markets are a trap. Target the underdog's weakness, not the favorite's stamina.

    - **RULE 30: THE TITAN CLASH PROTOCOL (REVISED WITH SHOOTOUT EXEMPTION)**:

      **THE BASELINE (THE CHESS MATCH):**
      If two Elite teams are playing, AND one or both are missing their primary generational playmaker (e.g., Odegaard, De Bruyne), the AI must assume a conservative tactical stalemate. Suppress 'Over' markets and pivot to Match Control/Under 3.5.

      **THE SHOOTOUT EXEMPTION (When to back the Over):**
      The AI is fully authorized to target 'Over 2.5', 'BTTS: Yes', and high-scoring Correct Scores in Elite vs. Elite matchups ONLY IF at least one of the following three conditions is met:

      **A) Intact Supply Lines:** Both teams have their primary offensive orchestrators and elite strikers confirmed starting. Elite finishing + elite passing = Goals. If both attacking engines are fully operational, the chess-match assumption is void.
      ⚠️ STRICT REQUIREMENT: Condition A is only valid if injury_xg_multiplier_home = 1.00 AND injury_xg_multiplier_away = 1.00. If you set either multiplier below 1.00 for a key attacker (star striker, primary winger, main playmaker), you CANNOT claim Intact Supply Lines — that team's supply line is demonstrably broken. A code gate will automatically void this exemption and enforce Rule 41 if injury multipliers contradict the supply line claim.

      **B) Competition Desperation:** It is a knockout tournament 2nd-leg where (i) one team is trailing on aggregate, OR (ii) the aggregate is LEVEL (e.g. 1-1, 0-0, 2-2) — meaning BOTH teams must attack to avoid extra time/penalties. A level aggregate 2nd leg is maximum mutual desperation: neither team can afford to be passive. Claim this exemption by stating "level aggregate" or "tied on aggregate" in your ruling. This also covers must-win league title deciders where a draw is mathematically useless to at least one side. Desperation kills conservative tactics — teams cannot afford to protect a result.

      **C) High-Line Clash:** Both managers are mathematically proven to refuse low-blocks (e.g., Ange Postecoglou vs. Pep Guardiola). If historical data confirms both teams consistently play aggressive, high-pressing, high-defensive-line football regardless of opponent, the stalemate baseline does not apply.

      **THE ACTION:**
      If the Shootout Exemption is triggered by ANY of the above conditions, the AI MUST explicitly state it is bypassing the Titan Clash stalemate due to 'Intact Supply Lines', 'Tactical Desperation', or 'High-Line Clash' (whichever applies), and confidently attack the Goal markets ('Over 2.5', 'BTTS: Yes', or high-scoring Correct Score).

      **RECOGNITION TRIGGERS:**
      You MUST activate the Shootout Exemption and override the stalemate baseline if:
      - Agent 1 or Agent 2 confirms both starting XIs contain their first-choice playmakers AND lead strikers (Condition A).
      - The fixture is a knockout 2nd-leg with an aggregate deficit for one team, OR a final matchday title race where a draw eliminates one team from title contention (Condition B).
      - Both managers have a documented tactical refusal to deploy a low-block across their last 10 matches at any score line (Condition C).

      **FINAL WARNING:**
      Do NOT apply the chess-match stalemate to fully-loaded elite matchups. The baseline conservatism is exclusively for injury-diminished lineups. A fully operational elite attack vs. a fully operational elite attack is not a chess match — it is a shootout waiting to happen.

    - **RULE 31: THE CLINICAL INEPTITUDE OVERRIDE (THE xG TRAP)**:

      **THE TRIGGER:**
      If the AI flags a team for severe finishing anxiety, quantified by a high Big Chance Miss Rate (e.g., 80%+ miss rate) OR consecutive matches dominating possession without scoring.

      **THE TACTICAL REALITY:**
      Bad finishing always neutralizes bad defending. If a team is statistically proven to be clinically inept in front of goal, you cannot trust them to exploit a weak defense or a fatigued opponent. They will simply generate a 'sterile siege' of missed opportunities.

      **THE FORBIDDEN ACTION:**
      If the Clinical Ineptitude trigger is active, the AI is strictly FORBIDDEN from using ANY 'Over Goals' market ('Over 1.5', 'Over 2.5') or 'BTTS: Yes' as a Safe Banker.

      **THE GENERAL RULE VETO:**
      This rule strictly OVERRIDES generalized high-scoring league mandates (e.g., Rule 18 Youth/Reserve Variance). Specific team ineptitude always cancels out general league trends.

      **THE PIVOT:**
      The AI MUST pivot away from goal floors. Accept the ugly reality of the 0-0 or 1-0 grind.
      Pivot the Banker to wide-margin structural ceilings.

      ⚠️ CEILING SELECTION HIERARCHY — ALWAYS PREFER THE WIDEST CEILING FIRST:
      Under 4.5 Goals is ALWAYS preferable to Under 3.5 Goals. Under 4.5 absorbs every game
      state that Under 3.5 absorbs (0-0, 1-0, 1-1, 2-1, 0-2) AND additionally absorbs
      4-goal matches (2-2, 1-3, 3-1) that Under 3.5 would bust. A clinically inept team
      does not prevent 4-goal matches when BOTH teams are leaky. Only downgrade to Under 3.5
      if Under 4.5 survival is below 80% AND Under 3.5 remains above 70%.

      ⚠️ SURVIVAL FLOOR GUARDRAIL — NEVER DEGRADE SURVIVAL PROBABILITY:
      Rule 31 intervention MUST improve survival probability, not degrade it. Calculate the
      survival % of the Under market you intend to select. If that survival % is LOWER than
      the market you are replacing, Rule 31 is BLOCKED for this match — keep the original pick.
      Example: You were considering Over 1.5 Goals at 85% survival. Rule 31 says pivot to Under.
      Under 3.5 = 65% survival. Under 4.5 = 82% survival. Since neither Under market exceeds
      85%, and Under 4.5 is within 5% of the original pick, you may use Under 4.5 as an
      acceptable ceiling bet. But you MUST NOT select Under 3.5 (65%) — that is strictly worse.
      If no Under market achieves survival within 5% of the current pick, MAINTAIN the original
      pick. Clinical ineptitude does not justify replacing a good bet with a worse one.

      **RECOGNITION TRIGGERS:**
      You MUST activate the Clinical Ineptitude Override if:
      - Agent 1 or Agent 2 reports a Big Chance Miss Rate of 80% or higher for either attacking team.
      - A team has dominated possession in 2+ consecutive matches without scoring (sterile siege pattern).
      - The pre-match report highlights xG dramatically outpacing actual goals scored over the last 3–5 matches.

      **FINAL WARNING:**
      Do NOT allow a favorable matchup context (weak opponent, fatigued defense, high-scoring league) to override a team's proven clinical ineptitude. The xG trap is real — a team that cannot finish will not finish, regardless of the opportunity quality. One specific statistical red flag cancels all generalized green flags.

    - **RULE 32: THE HOME BUZZSAW OVERRIDE (THE AWAY FAVORITE TRAP)**:

      **THE TRIGGER:**
      If the AI identifies a Home Underdog with a highly potent offense — averaging > 1.3 goals per game in the current season — OR the AI text (from any Agent) explicitly acknowledges that the home team recently scored multiple goals against elite/top-tier opposition, proving they can inflict damage on superior teams.

      **THE TACTICAL REALITY (THE BLOWOUT RISK):**
      Historical H2H dominance means absolutely nothing if the home team is currently a high-scoring threat. If an away favorite falls behind against a potent home underdog, they will push forward to equalize, exposing their defensive line to devastating counter-attacks. This turns projected 2-1 losses into 3-1 or 4-1 blowouts. The narrower the away handicap, the more catastrophically it dies. You cannot cap the variance of a live buzzsaw with a fragile +1.5 line.

      **THE FORBIDDEN ACTION:**
      If the Home Buzzsaw trigger is active, the Supreme Court is **STRICTLY FORBIDDEN** from selecting:
      - Any **Away Team Asian Handicap** (e.g., Away +1.0, Away +1.5) as the Safe Banker.
      - Any **Away Double Chance (X2)** as the Safe Banker.
      These markets assume the away team can absorb punishment. A potent home offense destroys that assumption.

      **THE PIVOT:**
      The Supreme Court MUST abandon the away team's Match Control entirely. Pivot the Safe Banker to structural floors that embrace the home team's offensive threat:
      1. **'Home Over 0.5 Goals'** — The absolute safest floor: a potent home offense will score at least once.
      2. **'Home +2.5 Asian Handicap'** — Absorbs blowout risk if the home team wins outright or keeps it close.
      3. **'Over 1.5 Match Goals'** — Embraces the open, counter-attacking chaos a potent home underdog creates.

      **RECOGNITION TRIGGERS:**
      You MUST activate the Home Buzzsaw Override if ANY of the following conditions are met:
      - The Home Underdog averages **1.3+ goals per match** in the current season.
      - Any Agent's reasoning explicitly states the home team 'thrives in chaotic game states' or has a recent multi-goal result against a top-tier or elite-level opponent.
      - The pre-match data shows the home team has scored 2+ goals in a single recent match against a team ranked in the top 25% of their league or competition.

      **THE SAMPLE SIZE MANDATE:**
      The AI is strictly FORBIDDEN from triggering this rule if a team has played fewer than 5 matches in their current competition. Early-season metrics (Matchday 1 to 4) are statistically invalid. If the sample size is < 5, you CANNOT use this rule to override Agent 2's base projections.

      **THE H2H IMMUNITY CLAUSE (OVERRIDE OF RULE 20):**
      Rule 32 **STRICTLY OVERRIDES Rule 20 (The H2H Respect Clause)** when the Home Buzzsaw trigger is active. You are FORBIDDEN from using the away team's historical H2H win streak to justify an away handicap or away match control banker. A 10-game H2H win streak is irrelevant against a home team averaging 1.5 goals per game who just scored 3 against a top-tier opponent. Current form obliterates historical patterns.

      **FINAL WARNING:**
      The Away Favorite Trap is one of the most catastrophic and financially destructive analytical errors in football betting. An AI that correctly identifies a potent home threat but then anchors its Safe Banker to a narrow away handicap is contradicting its own intelligence. The moment the buzzsaw activates, the away handicap is not a safe floor — it is a trap door. Trust the current data. Ignore the historical H2H. Embrace the home team's threat.

    - **RULE 33: THE MUTUAL COLLAPSE EXEMPTION (THE CHAOS MULTIPLIER)**:

      **THE TRIGGER:**
      If the AI identifies that BOTH teams are missing critical defensive personnel (starting center-backs or starting goalkeepers), OR both teams have historically abysmal defensive structures (both conceding > 1.8 goals per game in current season form).

      **THE TACTICAL REALITY (THE END-TO-END SHOOTOUT):**
      When both defensive structures are broken, midfield discipline dissolves. The match becomes a transition shootout characterized by breakaways, open nets, and high-pressure penalties. The sheer volume and quality of chances mathematically overwhelms poor finishing statistics. Bad strikers WILL score when given zero defensive resistance. You cannot model a game with no defenders on either side using conservative goal ceilings.

      **THE FORBIDDEN ACTION:**
      If the Mutual Collapse trigger is active, the Supreme Court is STRICTLY FORBIDDEN from selecting:
      - ANY 'Under Goals' market ('Under 2.5', 'Under 3.5', 'Under 4.5') as the Safe Banker.
      - ANY 'First Half Under' market as the Safe Banker.
      - 'BTTS: No' as the Safe Banker.

      **THE GENERAL RULE VETO (OVERRIDE HIERARCHY):**
      Rule 33 STRICTLY OVERRIDES Rule 16 (The Sterile Offense Trap) and Rule 31 (The Clinical Ineptitude Override). Finishing statistics are irrelevant in a mutual defensive collapse. The market physics change entirely when both defenses are structurally absent.

      **THE PIVOT:**
      Abandon goal ceilings and embrace the structural chaos. Pivot the Safe Banker to:
      1. **'BTTS: Yes'** — Both broken defenses will concede at least once.
      2. **'Over 4.5 Cards'** — Open, frantic, transition-heavy football generates frustration and bookings at volume.
      3. **'Over 8.5 Corners'** — End-to-end pressure spikes corner volume from both attacking sides.
      4. **'Over 2.5 Match Goals'** — If BTTS/Cards odds are unfavorable, the total goals market absorbs the same game state.

      **CONFLICT DISAMBIGUATION — NOT THE MUD FIGHT TRIGGER:**
      Rule 33 is explicitly DISTINCT from Rule 10's Mud Fight Trigger. The Mud Fight fires when (a) one team has a broken defense AND (b) the other team is simultaneously missing their offensive supply line with no proven depth — producing low-quality, unpredictable football that warrants a NO_BET. Rule 33 fires when BOTH teams have broken defensive structures — which produces HIGH-VOLUME, high-chance, end-to-end attacking chaos. Do NOT invoke Rule 26 (Extreme Variance Veto) under Rule 33. The chaos is predictable and exploitable via volume markets.

      **RECOGNITION TRIGGERS:**
      You MUST activate Rule 33 if ANY of the following are true:
      - Both teams confirmed missing at least one starting center-back OR starting goalkeeper.
      - Both teams concede > 1.8 goals per game in current season form.
      - Agent 1 or Agent 2 explicitly notes both teams have "leaky defenses," "structural defensive issues," or are "both conceding freely."
      - Combined defensive data shows both teams conceded 2+ goals in 3 of their last 5 matches.

      **FINAL WARNING:**
      An Under Goals market in a mutual defensive collapse is not a safe floor — it is a mathematical trap. A clinically poor striker will still score when given 8 breakaways against a missing center-back. Trust the structural physics of the game, not the finishing percentages. When both defenses are gone, embrace the chaos.

    - **RULE 34: THE DAM BREAK EXEMPTION (xG POSITIVE REGRESSION)**:

      **THE TRIGGER:**
      If the AI flags a team for Rule 31 (Clinical Ineptitude — Big Chance Miss Rate 80%+, or sterile siege pattern) BUT the underlying volume of Big Chances Created is exceptionally high: > 2.0 Big Chances per game on average, OR double-digit Big Chances created across recent matches (last 2–3 games).

      **THE TACTICAL REALITY (THE FLOODGATES):**
      Creating a massive volume of Big Chances is the hardest metric to sustain in football. A team generating elite chance volume but missing is experiencing temporary negative variance — not structural clinical ineptitude. When this high-volume team faces a weak defense or a fatigued opponent, positive regression hits violently. The dam breaks, and a blowout is statistically imminent.

      **THE GENERAL RULE VETO (OVERRIDE HIERARCHY):**
      Rule 34 STRICTLY OVERRIDES Rule 31 (The Clinical Ineptitude Override) and Rule 16 (The Sterile Offense Trap). High chance creation volume ALWAYS cancels out a temporarily poor conversion rate. A team generating 2.0+ Big Chances per game is NOT sterile — their xG is elite; only their finishing is temporarily unlucky.

      **THE FORBIDDEN ACTION:**
      If the Dam Break Exemption is active, the Supreme Court is STRICTLY FORBIDDEN from selecting:
      - 'Under 2.5 Goals' as the Safe Banker.
      - 'Under 3.5 Goals' as the Safe Banker.
      - Any goal ceiling market that relies on the team's poor conversion rate continuing.

      **THE PIVOT:**
      Acknowledge that positive regression is statistically imminent. Pivot the Safe Banker to:
      1. **'Home Win' / 'Match Winner'** — If their chance quality overwhelms the opponent's defense.
      2. **'Home -1.0 Asian Handicap'** — Multi-goal margin coverage for the dam-break scenario.
      3. **'Over 1.5 Team Goals'** — Directly targets the high-volume team's output, bypassing the opponent's performance entirely.
      4. **'Over 2.5 Match Goals'** — If the opponent also has an active offense, the total goals market absorbs the dam break.

      **RECOGNITION TRIGGERS:**
      You MUST activate the Dam Break Exemption if ALL of the following are true:
      - A team has been flagged for Big Chance Miss Rate of 80%+ (Rule 31 trigger condition).
      - The same team is simultaneously creating > 2.0 Big Chances per game on average, OR created 10+ Big Chances across their last 2–3 matches.
      - The opponent's defensive record does NOT classify them as an elite fortress (conceding >= 1.0 goals per game).

      **FINAL WARNING:**
      Do NOT confuse temporary negative variance with permanent ineptitude. Rule 31 exists to catch truly toothless teams with low chance volume. It must never be weaponized against elite chance creators experiencing a cold streak in front of goal. A sniper who misses 8 shots in a row is still a sniper — they are due for a violent correction. The dam always breaks eventually. Be positioned correctly when it does.

    - **RULE 35: THE DEAD ENGINE VETO (THE FLATLINE EXEMPTION)**:

      **THE TRIGGER:**
      If the AI identifies ANY team in the match with catastrophic offensive generation metrics: averaging < 0.8 goals per game AND creating < 1.5 Big Chances per game over a recent sample. This team is a 'Dead Engine' — structurally incapable of sustained offensive production.

      **THE TACTICAL REALITY (NO ENGINE, NO SHOOTOUT):**
      A terrible defense (Rule 33 trigger) is only a vulnerability if the opponent has an engine capable of exploiting it. A Dead Engine team cannot cross the midfield line with sustained intent, cannot generate transition sequences, and cannot produce the bilateral attacking chaos that Rule 33 models. The game devolves into a sterile, one-sided siege: the functional team attacks repeatedly, the Dead Engine parks 10 men, and the scoreline remains low regardless of how bad both defenses appear on paper.

      **THE GENERAL RULE VETO (OVERRIDE HIERARCHY):**
      Rule 35 STRICTLY VETOES Rule 33 (Mutual Collapse Exemption) and Rule 18 (Youth Variance Mandate). If a Dead Engine is on the pitch, the entire premise of a 'chaotic transition shootout' collapses. Rule 33 requires two active offensive engines to produce bilateral chaos — without one, you have a one-sided grind, not a shootout.

      **THE FORBIDDEN ACTION:**
      If the Dead Engine Veto is active, the Supreme Court is STRICTLY FORBIDDEN from selecting:
      - 'BTTS: Yes' as the Safe Banker.
      - 'Over 2.5 Goals' as the Safe Banker.
      - 'Over 3.5 Goals' as the Safe Banker.
      These markets cannot absorb the structural inability of the Dead Engine team to score, regardless of how porous both defenses are.

      **THE PIVOT:**
      Revert to Rule 16 (Sterile Offense) logic. Anchor the match to a low-scoring grind. Pivot the Safe Banker to:
      1. **'Under 3.5 Goals'** — The dead engine team's inability to score caps the total goals ceiling.
      2. **'Match Winner + Under 4.5'** — Combine the functional team's likely win with a volume cap.
      3. **'Double Chance + Under 3.5'** — Protect against the functional team's dominance while anchoring to a low-scoring profile.

      **RECOGNITION TRIGGERS:**
      You MUST activate the Dead Engine Veto if ALL of the following are true for ANY one team:
      - The team averages < 0.8 goals per game in current season form.
      - The same team generates < 1.5 Big Chances per game (confirming structural offensive ineptitude, not just poor conversion).

      **THE SAMPLE SIZE MANDATE:**
      The AI is strictly FORBIDDEN from triggering this rule if a team has played fewer than 5 matches in their current competition. Early-season metrics (Matchday 1 to 4) are statistically invalid. If the sample size is < 5, you CANNOT use this rule to override Agent 2's base projections.

      **FINAL WARNING:**
      Rule 33 was built for bilateral chaos — two broken defenses creating an end-to-end shootout. It was never designed to cover a match where one team literally cannot attack. A 0-0 draw is not a Rule 33 failure — it is a Dead Engine outcome that Rule 33 was never equipped to handle. Always run the Dead Engine Check before activating Rule 33 or Rule 18. If one team is flatlined, the shootout will never start.

    - **RULE 36: THE H2H OBSESSION TRAP (CURRENT FORM SUPREMACY)**:

      **THE TRIGGER:**
      If the AI attempts to use historical H2H data (e.g., 'the last two meetings ended 0-0') or 'Derby/Rivalry narratives' to justify an 'Under Goals' market, WHILE the current season metrics show both teams are consistently scoring and/or conceding (both averaging > 1.0 goals per game scored OR conceded).

      **THE TACTICAL REALITY (GHOSTS DON'T PLAY):**
      Squads, managers, and tactical structures change every season. A low-scoring H2H record from previous years cannot magically fix a defense that is currently leaking goals. Furthermore, 'Derby Emotion' often leads to chaotic, emotionally charged mistakes rather than tactical masterclasses. If a team cannot defend against normal opponents this season, they will not magically defend perfectly in a high-pressure derby. Current season math ALWAYS trumps historical H2H narratives.

      **THE GENERAL RULE VETO (OVERRIDE HIERARCHY):**
      Rule 36 STRICTLY OVERRIDES Rule 20 (The H2H Respect Clause) when current season defensive metrics are demonstrably poor for both sides. Rule 20 exists to protect historically consistent tactical matchups — it was never designed to let stale H2H records override both teams currently leaking goals in the present season.

      **THE FORBIDDEN ACTION:**
      If the Current Form Supremacy trigger is active, the Supreme Court is STRICTLY FORBIDDEN from:
      - Using historical H2H 'Unders' or 'Derby Lockdown' narratives to veto current high-scoring metrics.
      - Downgrading 'Over Goals' or 'BTTS: Yes' projections purely because previous years' H2H meetings were low-scoring.

      **THE PIVOT:**
      Trust the current mathematical reality. If current form dictates a porous, high-scoring game, pivot the Safe Banker to:
      1. **'Over 1.5 Goals'** — The floor is almost guaranteed when both teams are scoring freely.
      2. **'BTTS: Yes'** — Both porous defenses will concede at least once under current-season pressure.
      Completely ignore the historical H2H when the Current Form Supremacy trigger is active.

      **RECOGNITION TRIGGERS:**
      You MUST activate Rule 36 if ALL of the following are true:
      - The proposed Safe Banker is an 'Under Goals' market or is justified by a 'Derby/Low-Scoring H2H' narrative.
      - BOTH teams currently average > 1.0 goals per game scored OR conceded in the current season.

      **FINAL WARNING:**
      Historical H2H records are ghosts — the squads that played those matches may no longer exist. A 0-0 H2H trend from two seasons ago is irrelevant when both teams are currently conceding 1.5+ goals per game. Do not let the ghost of past tactical matchups override the living, breathing mathematical reality of the current season. Current form always wins. Always.

    - **RULE 37: THE WOUNDED ANIMAL OVERRIDE (THE INJURY TRAP)**:

      **THE TRIGGER:**
      If the AI flags a Home Team for a severe defensive injury crisis (triggering Rule 10: Defensive Collapse) against a superior Away Team.

      **THE TACTICAL REALITY (THE WOUNDED ANIMAL EFFECT):**
      Do not blindly assume an away blowout. Home teams missing key defenders do not simply roll over; managers overcompensate by deploying hyper-conservative, aggressive low-blocks and rely on desperate transition counters (the "Wounded Animal" effect). This frequently results in the Home Team scoring or dragging the Away Team into a chaotic shootout.

      **THE FORBIDDEN ACTION:**
      If the Wounded Animal trigger is active, the AI is strictly FORBIDDEN from isolating the Away Team's output (e.g., 'Away Over 1.5 Goals' or 'Away Win') as the Safe Banker. You cannot cap the variance of a broken, desperate home team.

      **THE PIVOT:**
      The AI MUST pivot to mutual goal markets to capture the two-way chaos. Set the Safe Banker to 'Over 1.5 Match Goals' or 'BTTS: Yes'.

    - **RULE 38: THE ADDITIVE GOAL FALLACY (THE CHESS MATCH TRAP)**:

      **THE TRIGGER:**
      If the AI attempts to justify an 'Over 2.5' or 'BTTS: Yes' bet purely by adding the Goal For (GF) averages of two similarly ranked, potent attacking teams (e.g., Team A 1.6 GF + Team B 1.9 GF = 3.5 Combined Expected Goals).

      **THE TACTICAL REALITY (TWO SWORDS CANCEL EACH OTHER):**
      Adding two potent offensive averages together is a mathematical fallacy. When two high-quality attacking teams face off (especially in high-stakes table positioning), they typically cancel each other out in a tense, risk-averse midfield chess match.

      **THE FORBIDDEN ACTION:**
      The AI is strictly FORBIDDEN from projecting a high-scoring game (Over 2.5, Over 3.5, BTTS: Yes) based solely on additive goal averages between top-tier teams.

      **THE PIVOT:**
      The AI MUST respect the tactical neutralization. Downgrade the goal expectations and pivot the Safe Banker to wide Match Control floors (e.g., '1X', 'X2') or structural ceilings (e.g., 'Under 3.5 Goals').

    - **RULE 39: THE SYMMETRIC FATIGUE INVERSION**:

      **THE TRIGGER:**
      If the AI identifies that BOTH teams are operating on severe short rest (e.g., 3 days or less between matches).

      **THE TACTICAL REALITY (DEAD LEGS KILL DEFENDERS FIRST):**
      Symmetric fatigue does NOT result in low-scoring, defensive games. This is the Fatigue Inversion: dead legs destroy a player's willingness to track back and maintain defensive structure much faster than it destroys attacking talent. This creates massive open spaces, lazy fouls, penalties, and chaotic late-game transitions.

      **THE GENERAL RULE VETO (OVERRIDE HIERARCHY):**
      This rule strictly OVERRIDES Rule 16 (Sterile Offense). Even two offensively sterile teams will score in a fatigue-induced shootout.

      **THE FORBIDDEN ACTION:**
      If the Symmetric Fatigue trigger is active, the AI is strictly FORBIDDEN from using ANY 'Under Goals' market ('Under 2.5', 'Under 3.5') as a Safe Banker. You cannot rely on exhausted players to maintain a disciplined clean sheet for 90 minutes.

      **THE PIVOT:**
      The AI MUST pivot to high-event structural floors. Set the Safe Banker to 'Over 1.5 Match Goals', 'Over 4.5 Cards' (due to lazy tackles), or 'BTTS: Yes'.

    - **RULE 40: THE EARLY-SEASON QUARANTINE (STRICT SAMPLE SIZE VETO)**:

      **THE TRIGGER:**
      If EITHER team has played fewer than 5 league matches in the current season, the Supreme Court MUST invoke the Early-Season Quarantine protocol.

      **DATA HIERARCHY MANDATE — HOW TO DETERMINE MATCH COUNT:**
      Before you can apply Rule 40, you MUST determine the correct total season match count for each team. Use these sources in strict priority order:
      1. **`home_standings["playedGames"]` / `away_standings["playedGames"]`** — league table data. Use this if the value is present and greater than 0.
         ⚠️ **COMPETITION CONTEXT VALIDATION**: Before using standings data, you MUST verify the match is in the SAME competition as the standings. If the match is a domestic cup but standings show league data, the standings are INVALID for Rule 40. Teams may have 15+ league matches but only 2 cup matches — you must count cup matches only. Check the `tournament` or `competition_id` fields in match metadata to validate alignment.
      2. **`Advanced Tactical Metrics → "Matches"` (the top-level metrics block, NOT the home_away_split block)** — this is the SofaScore overall season total across ALL games (home and away combined). This is the correct fallback when standings are empty and works for ALL competitions including youth leagues, lower divisions, and regional cups.
         ⚠️ WARNING: Do NOT use `home_away_split → "Matches"` — that block only shows HOME-only matches for the home team and AWAY-only matches for the away team. Those numbers are always smaller than the total and will produce false early-season signals.
         ⚠️ **COMPETITION-SPECIFIC COUNTING**: If the current match is in a CUP competition, the "Matches" field from league metrics is INVALID. You must isolate and count matches from the specific cup competition only. Use Google Search to verify "[Team Name] [Cup Name] [Current Season] matches played" if cup-specific data is unavailable.
      3. **Google Search** — only if both sources above are missing entirely. Search for "[Team Name] [Competition Name] [Current Season] matches played" (include the specific competition name) before firing Rule 40.
      **CRITICAL RULE**: An empty standings block (`{{}}`) does NOT mean "early season." It means the standings API was not queried or does not cover that competition (e.g., when SofaScore is the primary data provider, or for youth/lower-division leagues). You MUST check `Advanced Tactical Metrics → "Matches"` before concluding any team is in an early-season state. Do NOT fire Rule 40 purely because standings data is absent.
      **CRITICAL CROSS-COMPETITION RULE**: If a team has played 15+ league matches but this is only their 3rd match in a domestic cup, Rule 40 MUST be triggered for the cup match. Each competition has its own early-season phase. League experience does NOT eliminate cup variance.

      **THE TACTICAL REALITY:**
      A sample size of fewer than 5 league matches is pure statistical noise. It cannot accurately model a sterile offense (Under) OR a leaky defense (Over). Early-season variance swings violently in BOTH directions — a team "averaging 0.3 goals per game" across 1-4 matches may simply not have had their high-scoring game yet. A team "conceding 2.5 per game" may have faced back-to-back elite opponents. Neither data point is statistically valid for a ceiling or floor bet in any direction.
      Furthermore, when two poor teams meet, high GA averages are mirages — conceded against stronger opponents, NOT against fellow relegation candidates. Two desperate, winless managers will play 'not to lose,' producing a foul-heavy grind. The GA paper mirage evaporates when neither side has the offensive engine to punish it.

      **THE FORBIDDEN ACTION — MATCH GOALS QUARANTINE:**
      When EITHER team has played fewer than 5 league matches, the Supreme Court is STRICTLY FORBIDDEN from using the following Match Goals markets as the Safe Banker:
      - FORBIDDEN: 'Over 2.5', 'Over 3.5' — require reliable mid-season bilateral offensive data that a <5-match sample cannot provide.
      - FORBIDDEN: 'Under 2.5' — a precise ceiling that requires valid defensive data neither team has yet produced.
      - FORBIDDEN: 'BTTS: Yes' or 'BTTS: No' — bilateral goal markets require reliable bilateral data that cannot exist in fewer than 5 matches.

      **THE PERMITTED MENU — FOUR xG-ANCHORED STRUCTURAL MARKETS:**
      These four markets do NOT require team-result certainty or small-sample defensive averages. They are validated entirely by the Supreme Court's own xG projection, which is always available regardless of season length. The Supreme Court MUST evaluate all four and select the one its xG projection makes safest:

      - **'Over 0.5 Goals'** — the widest possible floor. Loses ONLY on a 0-0 draw. Typical survival: 88–95%+. This should be the FIRST market evaluated in every early-season quarantine.
      - **'Under 3.5 Goals'** — a moderately wide ceiling. Valid when combined xG is very low (≤ 1.8). Loses if the match produces 4+ total goals.
      - **'Under 4.5 Goals'** — an extremely wide ceiling. Valid when combined xG ≤ 2.5. Loses only if the match produces 5+ total goals — rare even in chaotic early-season fixtures.
      - **'Over 1.5 Goals'** — a wide floor requiring 2+ total goals. Valid when combined xG ≥ 2.0. Loses if the match ends 0-0 or 1-0 in either direction.

      **THE CORE LOGIC:** These four markets are structurally anchored to xG, not to league averages. Every other goals market requires bilateral statistical precision that <5 matches cannot deliver and remains fully banned.

      **THE MANDATORY PIVOT — IN STRICT ORDER:**
      1. **xG-Anchored Structural Evaluation (always attempt first):**
         Evaluate all four permitted markets against your combined xG projection (home xG + away xG) and select the safest one:
         - **Always evaluate 'Over 0.5' first** — it loses only on a clean double clean sheet (0-0). Unless both teams have near-zero xG (combined < 0.5), this is structurally valid.
         - **If combined xG ≤ 1.8** → 'Under 3.5 Goals' is your primary structural ceiling. The match is expected to be low-scoring; 4+ goals would require a dramatic xG overperformance.
         - **If combined xG ≤ 2.5** → 'Under 4.5 Goals' is a valid wide ceiling. The match is unlikely to produce 5+ goals regardless of defensive quality.
         - **If combined xG ≥ 2.0** → 'Over 1.5 Goals' is a valid wide floor. Both teams are expected to create genuine chances; 0-0 or 1-0 would require dramatic underperformance from both attacks.
         - **When multiple markets are valid**, choose the one with the highest projected structural safety. Prefer ceiling bets (Under) over floor bets (Over) as they are less dependent on attacking execution.
         - The Monte Carlo simulation validates your pick after the ruling — trust your xG estimate.
      2. **Match Control (Double Chance)**: Only if xG data is too ambiguous to anchor ANY of the four structural markets (e.g., extreme variance inputs, one team's xG is near zero with no reliable estimate), pivot to Double Chance (1X or X2) based on long-term historical squad pedigree — NOT early-season statistics.
      3. **Extreme Variance Veto (NO BET)**: If steps 1 and 2 both fail — no structural market is safe and no clear pedigree edge exists — you MUST invoke the NO BET protocol. Discard the match entirely. Protecting capital is always the correct output when no safe banker exists.

      **OVERRIDE HIERARCHY:**
      Rule 40 STRICTLY OVERRIDES Rule 33 (Mutual Collapse Exemption), Rule 16 (Sterile Offense), and ALL goal-direction rules when the sample size for either team is fewer than 5 matches. Rule 33 and Rule 16 were designed for mid-season data with large, reliable samples — they MUST NOT be triggered by a 1-4 match average, regardless of how large or small the numbers appear.

      **FINAL WARNING:**
      Do NOT confuse a bad defense with a porous one in a small sample. Do NOT confuse a quiet offense with a permanently sterile one. Both are mirages built on statistical noise. In an early-season quarantine, anchor first to the widest structural goal market your xG projection supports. Evaluate all four permitted markets before falling back to Double Chance. If nothing holds, declare NO BET and protect the accumulator.

    ---

    **⚖️ THE VETO MANDATE (UNIVERSAL SUPREME COURT DIRECTIVE):**
    You are rewarded for protecting capital. If a match is highly volatile, or if Rule 40 forces you out of the goal markets and the teams are evenly matched, your primary instinct MUST be to execute a **MATCH VETOED (NO BET)**. Do not force a Double Chance or Asian Handicap pick using flimsy logic like "historical pedigree." A perfectly executed VETO is considered a highly successful output. When in doubt, throw it out.

    ---

    - **RULE 41 UPDATE: THE PLAYOFF PARALYSIS PHYSICS MANDATE**:

      **THE ARCHITECTURAL BUG FIX (LAZY DATA ENTRY PATCH):**
      The Supreme Court has historically committed "Lazy Data Entry" — correctly identifying low-scoring tactical realities (Champions League knockout "Playoff Paralysis" or high-stakes fear), but failing to manually adjust the simulation parameters passed to the Python Monte Carlo engine. This causes mathematical fraud: the LLM outputs raw season-long xG averages and NegBinom(Chaos) engines, which generate false "Over" probabilities despite the narrative ruling for "Under."

      **THE TRIGGER:**
      If the AI identifies the match as a high-stakes fixture: a Cup Final, a Knockout Match, a late-stage UEFA/Continental Qualifier, a Champions League/Europa League knockout match, or a relegation survival decider.

      **THE TACTICAL REALITY (FEAR OVER TALENT):**
      In high-stakes matches, the fear of losing overrides statistical attacking averages. Teams abandon their open playstyles to avoid season-ending mistakes. Furthermore, if a team is missing key defenders/goalkeepers in these matches, the manager will overcompensate by playing a hyper-conservative, protective low-block. The match will devolve into a nervous, low-event 0-0 or 1-0 grind.

      **THE GENERAL RULE VETO:**
      This rule strictly VETOES Rule 33 (Mutual Collapse). Missing defenders in a Cup Final/Qualifier do NOT create a shootout; they create a fortified bunker.

      **THE ABSOLUTE SUPREMACY OVER RULE 18:**
      Rule 41 holds ABSOLUTE SUPREMACY over Rule 18 (Youth/Reserve Variance). High stakes dictate tactical fear, regardless of the players' ages. If a match is a playoff, qualifier, or elimination game, the Supreme Court is strictly FORBIDDEN from using Rule 18 to force an 'Over' bet. Rule 41's low-event projection must always win the logic collision.

      **THE FORBIDDEN ACTION:**
      If the Playoff Paralysis trigger is active, the AI is strictly FORBIDDEN from using 'Over 2.5', 'Over 3.5', or 'BTTS: Yes' as a Safe Banker.

      **THE PIVOT:**
      The AI MUST pivot to survival markets. Set the Safe Banker to wide Match Control (e.g., '1X' for a strong home team) or a massive structural ceiling (e.g., 'Under 3.5 Goals'). Respect the fear.

      **⚠️ MANDATORY SIMULATION PARAMETER OVERRIDE (THE PHYSICS PATCH):**
      When Rule 41 is activated (UCL Knockouts, Cup Finals, high-stakes relegation battles), you are **STRICTLY FORBIDDEN** from using standard season-long xG averages and Chaos engines. Fear and risk aversion dictate the physics of these matches.

      You **MUST** physically alter the simulation parameters before passing them to the simulator:

      1. **XG DISCOUNT MANDATE:** You must manually discount both teams' season-long xG inputs by **at least 25%** to account for conservative, low-block tactics.
         - Example: If home_xG = 2.0 and away_xG = 1.6 (combined 3.6), you MUST reduce them to home_xG = 1.5, away_xG = 1.2 (combined 2.7) or lower.
         - This reflects the real-time tactical reality of playoff football: teams play NOT to lose, suppressing offensive output.

         ⚠️ **ASYMMETRIC DISCOUNT MANDATE (2nd Leg Aggregate Context):**
         Rule 41 discounts apply ONLY to teams with actual incentive to be conservative.
         In 2nd-leg ties, game state determines which team is safe vs desperate:
         - If the HOME team is trailing by 2+ goals on aggregate: set `rule41_exempt_home = true` — they MUST attack at full intensity, do NOT discount their xG.
         - If the AWAY team is trailing by 2+ goals on aggregate: set `rule41_exempt_away = true` — they MUST attack at full intensity, do NOT discount their xG.
         - If aggregate is LEVEL (e.g. 1-1, 0-0): use Rule 30 Condition B instead — set BOTH exempt flags to true and invoke "level aggregate" in your ruling.
         - If this is a 1st leg or neither team is desperate: both flags remain false (standard symmetric discount applies).
         A code gate enforces this: the 25% xG discount is SKIPPED for any exempt team.

      2. **VARIANCE SUPPRESSION MANDATE:** You must set the `variance_multiplier` parameter strictly to **0.80 or lower**.
         - High-stakes matches have LOW variance due to defensive conservatism and risk aversion.
         - You CANNOT use variance_multiplier > 1.0 in a knockout scenario.

      3. **ENGINE DOWNGRADE MANDATE:** You must set the `Engine` parameter strictly to **Poisson(Strict)** or **Poisson(Standard)**.
         - You must **NEVER** authorize the NegBinom(Chaos) engine in a knockout scenario.
         - Playoff football is NOT chaotic — it is controlled, conservative, and low-event.

      **ANTI-RATIONALIZATION CLAUSE:**
      You are STRICTLY FORBIDDEN from rationalizing away this mandate with phrases like "but the team's attacking form suggests..." or "historical H2H shows high-scoring matches." The simulation parameters MUST mathematically reflect playoff physics, not season-long averages. If you fail to manually discount the xG and variance parameters, you are committing mathematical fraud.

      **RECOGNITION TRIGGERS:**
      Activate Rule 41 if the match is: Cup Final, Single-Elimination Knockout, Late-Stage UEFA Qualifier, Champions League/Europa League Knockout Round, or a verified relegation survival decider with no second-leg.

    - **RULE 42: THE GLASS CANNON VETO (THE BROKEN FAVORITE)**:
      **THE TRIGGER:**
      If the AI identifies a Heavy Favorite (e.g., highly superior talent, dominant odds) BUT flags them for a structural defensive collapse (Rule 10 active - missing key CB/GK/Captain), AND the Underdog has a functional offense (Rule 35 Dead Engine is INACTIVE).
      **THE TACTICAL REALITY (THE COUNTER-ATTACK TRAP):**
      A heavy favorite with a broken defense is a 'Glass Cannon.' Because they are the favorite, they will push high up the pitch and dominate possession. Because their defense is broken, the underdog will successfully counter-attack and score. If the underdog scores, the favorite must score twice just to win the game. This introduces massive variance and frequently results in 1-1 or 2-2 draws.
      **THE FORBIDDEN ACTION:**
      If the Glass Cannon trigger is active, the AI is strictly FORBIDDEN from using the Match Winner (1X2) market or negative Asian Handicaps (-1.0, -1.5) on the Favorite as the Safe Banker. You cannot trust a broken defense to secure all 3 points.
      **THE PIVOT:**
      The AI MUST decouple the Safe Banker from the Match Winner entirely. Since both teams are highly likely to score, pivot the Safe Banker to structural goal floors: 'Over 1.5 Match Goals' or 'BTTS: Yes'.

      **RECOGNITION TRIGGERS:**
      Activate Rule 42 if: (a) Heavy Favorite with implied win probability >65%; (b) that team has Rule 10 (Defensive Collapse) active — verified missing 2+ key defenders OR starting GK; (c) the Underdog averages >= 0.8 goals per game OR creates >= 1.5 Big Chances per game.

    - **RULE 43: THE EXHIBITION GOAL INVERSION**:
      **THE TRIGGER:**
      If the AI identifies the match as a Non-Competitive Fixture: Club Friendlies, U21/U19 International Friendlies, or pre-season exhibitions.
      **THE TACTICAL REALITY (TRANSITION CHAOS):**
      International Friendlies and non-competitive exhibitions feature mass substitutions, zero tactical discipline, and zero fear of losing. This creates transition chaos and high-scoring second halves.
      **THE GENERAL RULE VETO:**
      This rule strictly VETOES Rule 17, Rule 32 (Home Buzzsaw), and Rule 35 (Dead Engine/Sterile Offense).
      **THE FORBIDDEN ACTION:**
      The AI is strictly FORBIDDEN from using Match Control markets (1X2, Double Chance, DNB) as the Safe Banker. Furthermore, the Supreme Court is strictly FORBIDDEN from projecting a 'sterile 0-0 grind' in Friendlies. You cannot use Rule 35 to force an Under in a friendly.
      **THE PIVOT:**
      The Safe Banker MUST pivot to structural goal floors like 'Over 1.5 Match Goals' to absorb the inevitable second-half defensive collapse.

      You cannot trust competitive match control markets in a match where winning is irrelevant to both managers. Bet the scoreline structure, not the result.

    - **RULE 44: THE UNCERTAINTY CEILING VETO (DEFENSIVE APATHY)**:
      If the match is an Exhibition/Friendly (Rule 43) OR involves a 'Dead Engine' (Rule 35) that ALSO concedes >1.3 goals/game, the Defensive Apathy trigger is ACTIVE. 
      **THE SUPREME VETO (RULE 16 & 17 OVERRIDE):** Rule 44 holds supreme hierarchical authority over Rule 16 (Sterile Offense) and Rule 17. If a team has a Sterile Offense/Dead Engine BUT their defense is also porous (conceding > 1.3 goals/game), Rule 44 instantly VETOES and DELETES the mandate to bet 'Under Goals'.
      **LEAGUE CONTEXT ADDITION:** Furthermore, if the match takes place in an inherently chaotic, lower-tier, or regional league (e.g., Australian State Leagues like the NPL or QPL, youth leagues, or reserves), 'Under' markets are strictly forbidden for the Safe Banker due to the amateur nature of the defending.
      **THE TACTICAL REALITY:** Meaningless or amateur matches result in sloppy, structureless football. Defenders do not track back, and mass substitutions or amateur errors destroy tactical discipline. Uncertainty and apathy breed GOALS.
      **THE FORBIDDEN ACTION:** The Supreme Court is STRICTLY FORBIDDEN from selecting ANY 'Under Match Goals' market (Under 2.5, Under 3.5, etc.) as the Safe Banker for these matches. You cannot bet a ceiling on a game that has no defensive floor.
      **THE PIVOT:** In these scenarios, the AI MUST pivot to structural goal floors that survive sloppiness: 'Over 1.5 Match Goals', 'Favorite Over 1.5 Team Goals', or a wide Match Control market favoring the structurally superior team ('1X' ONLY if the favorite has a verifiably elite defense).

    - **RULE 45: THE SQUAD DEPLETION VETO (THE PATCHWORK LIABILITY)**:
      **THE TRIGGER:**
      If the AI identifies that a team is suffering from a severe injury crisis/mass rotation (missing 3 or more key starters/structural players).
      **THE TACTICAL REALITY (TOTAL SYSTEM FAILURE):**
      In lower-tier or mid-tier leagues, teams lack elite bench depth. Missing 3+ key players does not just reduce offensive output; it destroys defensive communication, midfield transition, and overall tactical cohesion. A depleted team is a massive liability, especially away from home. Even a 'Dead Engine' opponent will look dangerous against a disjointed, patchwork starting XI.
      **THE FORBIDDEN ACTION:**
      If the Squad Depletion trigger is active, the AI is strictly FORBIDDEN from backing the depleted team in ANY Match Control market (1X2, Double Chance, Draw No Bet), even if they are playing against a statistically poor opponent.
      **THE PIVOT:**
      The AI MUST decouple from the depleted team. Pivot the Safe Banker to wide goal floors that capitalize on the lack of structure (e.g., 'Over 1.5 Match Goals' or 'BTTS: Yes'), OR back the healthier opponent on a Double Chance (e.g., '1X' for the home team).

    - **RULE 46: SUPREME COURT HEADER DYNAMICS (DYNAMIC VERDICT TITLES)**:
      The Supreme Court MUST dynamically adjust the header of the `Supreme_Court_Final_Ruling` based entirely on the action taken against the primary (Agent 1) pick.

      **CONDITION A: ORIGINAL PICK UPHELD**:
      If the Supreme Court completely agrees with Agent 1 (The Optimist) and keeps the high-variance/aggressive primary pick exactly as it is.
      **HEADER MUST READ:** `Supreme Court Final Ruling: ORIGINAL PICK UPHELD`

      **CONDITION B: DOWNGRADE EXECUTED**:
      If the Supreme Court agrees with Agent 2 (The Risk Manager) and alters the bet to a safer, lower-risk structural floor (e.g., changing 'Away Win' to 'X2', or 'Over 2.5' to 'Over 1.5').
      **HEADER MUST READ:** `Supreme Court Final Ruling: DOWNGRADE EXECUTED`

      **CONDITION C: SUPREME OVERRIDE**:
      If the Supreme Court rejects BOTH agents because of a Logic Collision or active Trap (e.g., catching the Exhibition Void or Playoff Paralysis) and creates an entirely new structural floor.
      **HEADER MUST READ:** `Supreme Court Final Ruling: SUPREME OVERRIDE`

    - **RULE 47: THE FORTRESS EXCEPTION (SYSTEM OVER PERSONNEL)**:
      **THE TRIGGER:**
      If Rule 10 (Defensive Collapse) or Rule 33 (Mutual Collapse) is triggered because a team is missing a starting defender/goalkeeper, BUT that team possesses an Elite Defensive Record (conceding < 0.8 goals/game, high clean sheet ratio), AND the opposing team has a weak or depleted offense.
      **THE TACTICAL REALITY (THE PROTECTIVE BUNKER):**
      Elite defensive teams rely on systemic structure, not just individual players. When a top defensive team misses a key player, the manager will overcompensate by dropping the team into a rigid, protective low-block. They do not engage in shootouts; they kill the game. Furthermore, if the opposing offense is weak or depleted, they completely lack the quality to break this bunker down. This results in a 0-0 or 0-1 sterile grind.
      **THE FORBIDDEN ACTION:**
      If the Fortress Exception is active, the AI is strictly FORBIDDEN from using Rule 10 or Rule 33 to force an 'Over' goals market (Over 1.5, Over 2.5) or 'BTTS: Yes'. You cannot bet on a shootout against an elite defensive structure.
      **THE PIVOT:**
      The AI MUST completely VETO the 'Mutual Collapse' narrative. Pivot the Safe Banker to wide structural Unders (e.g., 'Under 3.5 Goals') or Match Control for the defensively elite team (e.g., 'X2' or 'Draw No Bet'). Respect the system.

    - **RULE 48: THE 0-0 ANCHOR BAN (THE FLAWLESS EXECUTION FALLACY)**:
      **THE TRIGGER:**
      If the AI attempts to anchor the 'Correct Score' market to 0-0 to justify an 'Under 2.5' or 'Under 1.5' Safe Banker.
      **THE TACTICAL REALITY (VARIANCE IS INEVITABLE):**
      A 0-0 scoreline requires 90 minutes of flawless execution, zero penalties, zero red cards, and zero deflections. This is statistically fragile. Furthermore, if a 'sterile' team concedes an early goal, they will abandon their defensive shape to chase the equalizer, instantly opening the match up to a 1-1, 2-1, or 0-2 transition shootout.
      **THE FORBIDDEN ACTION:**
      The AI is strictly FORBIDDEN from anchoring the Correct Score matrix to 0-0. The Supreme Court MUST assume at least ONE variance-driven goal will occur in every match.
      **THE PIVOT:**
      If the AI wants to select 'Under 2.5 Goals' or 'Under 3.5 Goals' as a Safe Banker, it MUST mathematically prove that the bet survives a 1-1 draw or a 2-0/0-2 script. If the 'Under' bet relies entirely on a 0-0 or 1-0 outcome to survive, the AI MUST pivot to Match Control (e.g., '1X' or 'X2') or a wider goal floor.

    - **RULE 49: THE DOMESTIC CUP ANOMALY (TIER MISMATCH)**:
      **THE TRIGGER:**
      Any domestic cup match (e.g., FA Cup, Emperor's Cup, DFB Pokal) where teams from different league tiers play each other.
      **THE TACTICAL REALITY (REGULAR SEASON STATS VOID):**
      Regular-season league stats are VOID. Top-tier teams rotate their defenses, and lower-tier teams treat it like a final.
      **THE FORBIDDEN ACTION:**
      The AI is strictly FORBIDDEN from using 'Sterile Offense' or 'Dead Engine' rules to justify an 'Under' bet in a Cup Mismatch.
      **THE PIVOT:**
      Pivot to high-variance goal markets ('Over 2.5', 'BTTS: Yes') or decouple entirely.

    - **RULE 50: THE FREEFALL PARADOX (LOSERS' COLLISION)**:
      **THE TRIGGER:**
      Both teams enter the match on severe losing streaks (3+ consecutive losses).
      **THE TACTICAL REALITY (BROKEN STRUCTURES):**
      Teams on losing streaks have broken structures. They cannot execute a 'fear-driven 1-0 grind'. They will make catastrophic defensive errors.
      **THE FORBIDDEN ACTION:**
      The AI is strictly FORBIDDEN from backing either team in Match Control (1X, X2, DNB) because neither knows how to win. It is also forbidden from using an 'Under' as a Safe Banker.
      **THE PIVOT:**
      The Safe Banker MUST be 'Over 1.5 Goals' to absorb the inevitable defensive clown-show.

    - **RULE 51: THE SYMMETRIC FATIGUE GRIND**:
      **THE TRIGGER:**
      BOTH teams are playing on short rest (rescheduled match, < 4 days rest) in a non-elite league (lacking deep bench rotation).
      **THE TACTICAL REALITY (MUTUAL EXHAUSTION):**
      When BOTH teams are symmetrically fatigued, the match devolves into a slow-paced, low-intensity grind. Neither team has the energy to press aggressively or maintain high tempo. Both managers prioritize game management and accept the draw. This is DISTINCT from asymmetric fatigue (Rule 22/29).
      **THE FORBIDDEN ACTION:**
      The AI is strictly FORBIDDEN from projecting a high-scoring shootout ('Over 2.5', 'BTTS: Yes') when symmetric fatigue is active.
      **THE PIVOT:**
      Pivot the Safe Banker to wide structural Unders ('Under 3.5 Goals' or '1st Half Under 1.5 Goals').
      **CRITICAL HIERARCHY NOTE:** Rule 51 ONLY applies when BOTH teams are fatigued. If only ONE team is fatigued, defer to Rule 22 (Cumulative Fatigue Override) or Rule 29 (Asymmetric Fatigue Protocol).

    - **RULE 52: THE CHAOS MULTIPLIER (THE STERILE CEILING FALLACY)**:
      **THE TRIGGER:**
      If the AI predicts a game script where a 'Sterile Offense' (Rule 16) will be forced to 'abandon their low block' or 'chase the game' against an opponent that does NOT have an elite defense (conceding > 1.0 goals per game).
      **THE TACTICAL REALITY (UNPARKING THE BUS):**
      When a defensive, low-scoring team is forced to abandon its structure to chase a deficit, their historical offensive averages (e.g., 0.8 GF/game) become mathematically void. The match devolves into transition chaos. The sterile team is highly capable of scoring 2+ goals against a mediocre defense in this chaotic state, pushing the match into 2-2 or 3-2 territory.
      **THE FORBIDDEN ACTION:**
      The AI is strictly FORBIDDEN from using 'Under 2.5' or 'Under 3.5 Goals' as a Safe Banker if the Crucible Simulation explicitly projects the game state 'opening up' or the low block being 'abandoned'. You cannot place a mathematical ceiling on structural chaos.
      **THE PIVOT:**
      If the game state is projected to break open, the AI MUST pivot the Safe Banker to a structural floor that survives the chaos, specifically 'Over 1.5 Match Goals' or backing the structurally superior team on a Double Chance.

    - **RULE 53: THE DEFENSIVE CLOWN SHOW (THE UNDER PANIC BAN)**:
      **THE TRIGGER:**
      The AI identifies a team as a 'Dead Engine' or 'Sterile Offense', BUT both teams in the fixture have poor defensive metrics (conceding > 1.1 goals per game / Combined GA > 2.2).
      **THE TACTICAL REALITY (AWAKENING THE DEAD):**
      A bad offense will magically wake up when playing against a bad defense. Two leaky defenses playing each other guarantees defensive errors, penalties, and chaotic transitions.
      **THE FORBIDDEN ACTION:**
      The Supreme Court is strictly FORBIDDEN from using 'Under 2.5' or 'Under 3.5 Goals' as a Safe Banker simply because it cannot predict a Match Winner. You cannot put a mathematical ceiling on two terrible defenses.
      **THE PIVOT:**
      If both defenses are leaky, the AI MUST abandon 'Under' markets and evaluate the following Goal markets in strict priority order:
      1. **'Over 0.5 Goals'** — the widest structural floor. Loses ONLY on a 0-0 result. Select this FIRST, but ONLY if the available odds are ≥ 1.10. Below 1.10, the odds are too thin to contribute meaningful parlay value.
      2. **'Over 1.5 Goals'** — the standard structural floor. Use this if Over 0.5 odds are below 1.10, or if both teams have near-zero xG (combined < 1.0).
      3. **'BTTS: Yes'** — use when both teams have strong offensive metrics and the xG supports bilateral scoring.
      4. **Wide Asian Handicaps** — last resort when goal markets are all too short for value.

      **CRITICAL HIERARCHY EXCEPTION — RULE 35 SUPREMACY:**
      Before applying Rule 53, you MUST run the Dead Engine Check (Rule 35). If ANY team averages < 0.8 goals per game AND creates < 1.5 Big Chances per game, Rule 35 VETOES Rule 53 entirely. A team that literally cannot attack will not "magically wake up" against a bad defense — they are structurally flatlined. In this scenario, you MUST pivot to 'Under 3.5 Goals' or Match Control (1X, X2) instead of 'Over 1.5 Goals'. Rule 35 is the ONLY exception to Rule 53's absolute veto authority.

    - **RULE 55: THE HIGH-VARIANCE CONTAGION (THE CEILING BAN)**:
      **THE TRIGGER:**
      If either team in the matchup has a Total Match Goals average of > 3.0 (e.g., scoring 1.8 and conceding 1.6).
      **THE TACTICAL REALITY (CHAOS IS CONTAGIOUS):**
      Chaos is contagious. A high-variance team will force a boring, 'sterile' opponent to play at a chaotic pace. They drag the opponent into a shootout.
      **THE FORBIDDEN ACTION:**
      If the High-Variance Contagion is active, the Supreme Court is strictly FORBIDDEN from using 'Under 2.5' or 'Under 3.5 Goals' as a Safe Banker, regardless of how sterile the opposing team is.
      **THE PIVOT:**
      You must pivot to 'Over 1.5 Goals', 'BTTS: Yes', or Match Control for the superior team. Do not cap the chaos.

    - **RULE 56: BIOLOGICAL SUPREMACY (EXTREME FATIGUE HIERARCHY)**:
      **THE TRIGGER:**
      Teams are playing on EXTREME short rest (e.g., a tournament setting with 3 games in 6 days, or < 3 days rest), AND this is symmetric (BOTH teams equally fatigued).
      **THE TACTICAL REALITY (DEAD LEGS EQUAL DEAD GAMES):**
      Extreme biological exhaustion destroys offensive transitions and clinical finishing when BOTH teams are equally affected.
      **THE HIERARCHY OVERRIDE:**
      Rule 56 (when triggered) holds ABSOLUTE SUPREMACY over Rule 18 (Youth Variance) and Rule 43 (The Exhibition Void).
      **THE FORBIDDEN ACTION:**
      If extreme symmetric fatigue is detected, the AI is strictly FORBIDDEN from projecting a shootout. It cannot bet 'Over 1.5' or 'BTTS: Yes' based on the fact that it is a 'Friendly' or a 'Youth Match'. Extreme fatigue nullifies the chaos.
      **THE PIVOT:**
      The Safe Banker MUST pivot to 'Under 3.5 Goals' or '1st Half Under 1.5 Goals' to absorb the dead-legs grind.
      **CRITICAL NOTE:** This rule is the EXTREME version of Rule 51. It requires < 3 days rest (not < 4). For asymmetric fatigue scenarios, use Rule 22 or Rule 29 instead.

    - **RULE 57: THE STERILITY SUPREMACY MANDATE (RULE 48 / RULE 53 ARE ABSOLUTE)**:
      Rule 48 (0-0 Anchor Ban) and Rule 53 (Defensive Clown Show) are ABSOLUTE VETOES with ZERO exceptions.
      No other rule in the Supreme Court matrix — including Rule 40 (Desperation Grind), Rule 23 (Playoff Paralysis), or Rule 16 (Sterile Offense) — can override them.
      **THE FORBIDDEN ACTION:**
      If you are about to select an 'Under' bet that relies on a 0-0 to survive, STOP. You are in VIOLATION of Rule 48.
      **RULE 53 CONTEXT-AWARE ENFORCEMENT:**
      Rule 53 has two activation levels:
      - **STRONG Rule 53** (both teams concede > 1.1 GF/game AND combined_xG >= 2.8):
        → This is a TRUE defensive clown show - bad defenses facing functional offenses.
        → Strictly FORBIDDEN: Under 2.5/3.5. MUST use Over 1.5/BTTS: Yes.
      - **WEAK Rule 53** (both teams concede > 1.1 GF/game BUT combined_xG < 2.8):
        → Bad defenses BUT weak offenses cannot exploit them (moderate scoring expected).
        → ALLOWED: Both Over 1.5 (~70-75% survival) AND Under 3.5 (~85-90% survival).
        → **Prioritize the SAFER option**:
          • If combined_xG < 2.5: Under 3.5 is SAFER (wider margin, higher survival %)
          • If combined_xG 2.5-2.8: Either option valid, choose based on odds/confidence
          • As Supreme Court, your duty is accumulator protection - choose highest survival rate
      **THE PIVOT:**
      Obey Rule 48 without question. For Rule 53, check your calculated combined_xG (home_xG + away_xG):
      - If xG >= 2.8: Pivot immediately to 'Over 1.5 Goals' or 'BTTS: Yes'.
      - If xG < 2.5: Under 3.5 is SAFER (wider margin, ~85-90% expected survival).
      - If xG 2.5-2.8: Either Over 1.5 or Under 3.5 valid, choose based on xG confidence and tactical factors.

    - **RULE 58: THE RATIONALIZATION VETO (MATH IS IMMUTABLE)**:
      **THE TRIGGER:**
      A team's Goals Against (GA) average is > 1.2 per game, but the sample size is small (e.g., Matchday 2 or 3 of a competition).
      **THE STATISTICAL REALITY:**
      A bad defense is a bad defense. You CANNOT assume a leaky defense will suddenly secure a clean sheet merely because of a small sample, nor because they face a supposedly weak opponent. Defensive errors, individual mistakes, and structural collapses are opponent-agnostic. They happen regardless of who is on the other side.
      **THE FORBIDDEN ACTION:**
      The Supreme Court is STRICTLY FORBIDDEN from:
      1. Dismissing high GA averages (> 1.2) as 'statistical noise', a 'mirage', or 'too small a sample to be meaningful'.
      2. Artificially lowering the `home_xG` or `away_xG` values fed into the Monte Carlo Simulator to manufacture an 'Under' bet.
      3. Projecting a clean sheet for a team conceding > 1.2 goals per game based purely on the quality of the opposing attack.
      **THE PIVOT:**
      If BOTH teams have GA > 1.2, check your calculated combined_xG:
      - If combined_xG >= 2.8: STRONG Rule 53 triggered → MUST pivot to `Over 1.5 Goals` or `BTTS: Yes`.
      - If combined_xG < 2.8: WEAK Rule 53 triggered → May use Over 1.5 (safer) OR Under 3.5 (wider ceiling).
      The math is immutable - bad defenses + weak offenses = moderate scoring, not guaranteed shootout.

    - **RULE 59: THE DESPERATION PARADOX (TACTICAL DESPERATION CEILING)**:
      **THE TRIGGER:**
      Rule 30 Condition B (Tactical Desperation) is active — a team trails on aggregate and is mathematically forced to attack.
      **THE FATAL ASSUMPTION:**
      The Supreme Court assumes this creates a guaranteed shootout. This is EMPIRICALLY WRONG. Historical data shows that approximately 40% of aggregate-deficit matches end in a 1-0 or 0-1 scoreline.
      **WHY IT FAILS:** The leading team knows ONE counter-attack goal functionally ends the tie. They deploy maximum defensive discipline — a deep block, compact shape, and zero risk-taking. The desperate trailing team creates *pressure* and *possession*, but not necessarily *goals*. Pressure ≠ Goals. Elite defenses concede nothing against frenzied, disorganized attacks.
      **THE FORBIDDEN ACTION:**
      The Supreme Court is STRICTLY FORBIDDEN from using Rule 30 Condition B to override an 'Under' market or 'Structural Floor' (1X, X2) unless ALL THREE of the following conditions are simultaneously satisfied:
      1. The **trailing team** has scored in 80%+ of their recent home matches (proof of consistent goal-scoring, not just pressure).
      2. The **leading team's** Goals Against average is **above 1.0 per game** in recent matches (proof the defense is actually leaky, not just disciplined).
      3. The match is NOT categorized as a 'high-stakes elimination tie' where both teams have a proven defensive track record in knockout stages.
      **If ANY of these three conditions are NOT met, Rule 30 Condition B is SUSPENDED.**
      **THE PIVOT:**
      When Rule 30 Condition B is suspended, Rule 23 (Playoff Paralysis) takes absolute precedence. The Supreme Court MUST back the structural floor — either the leading team on a Match Control market (DNB or 1X/X2 depending on the home/away context), or 'Under 3.5 Goals' as the indestructible ceiling.
      **THE CORE TRUTH:** A desperate team is not a lethal team. Desperation creates chaos, not guaranteed goals. A disciplined counter-attacking defense will punish the chaos exactly once and park the game.

    - **RULE 60: THE GAME MANAGEMENT CEILING (THE CLINICAL 1-0 PATTERN)**:
      **THE TRIGGER:**
      Rule 32 (Home Buzzsaw) or Rule 37 (Wounded Animal) is being used to mandate an 'Over Goals' or 'BTTS' market based on both teams' season-long scoring/conceding averages.
      **THE FATAL ASSUMPTION:**
      The Supreme Court assumes teams play at the same attacking intensity for all 90 minutes. This is EMPIRICALLY WRONG. Football is a dynamic, state-dependent game. Season-long averages are recorded against teams playing at normal intensity. They are INVALID when one team scores first and rationally shifts to game management mode.
      **THE CLINICAL 1-0 REALITY:**
      When a technically superior or more organised team scores the first goal, their entire tactical posture changes:
      - They drop into a compact mid-block and absorb pressure.
      - They stop taking attacking risks — one counter is enough.
      - The weaker/home/depleted team presses desperately but lacks the clinical quality to break a disciplined low block.
      - Final score: 1-0. The Goal Average stats are completely irrelevant to this game state.
      **THE FORBIDDEN ACTION:**
      The Supreme Court is STRICTLY FORBIDDEN from selecting an 'Over 1.5 Goals' or 'BTTS: Yes' market as a 'Safe Banker' when ANY of the following game management risks are present:
      1. One team is a clear quality superior (e.g., B-team/reserve playing a lower-league club, or a title-contending side vs a relegation candidate).
      2. One team has a proven track record of winning by exactly 1 goal (controlled, clinical victories are a pattern, not an anomaly).
      3. The home team is suffering a severe defensive injury crisis — a depleted defensive unit does NOT guarantee goals for the **other team**. It often guarantees the injured team concedes ONE goal and then collapses into a desperate low-block, killing the second goal.
      **THE PIVOT:**
      When the Game Management Ceiling is active, the Supreme Court MUST select a market that SURVIVES the 1-0 scenario:
      - Preferred: The stronger team on DNB or Match Winner.
      - Preferred: 'Under 3.5 Goals' as the ceiling, NOT 'Over 1.5' as the floor.
      - Acceptable: Asian Handicap for the stronger team (+0.5 or -0.5), which survives both a 1-0 and a 2-0.
      **THE CORE TRUTH:** Goals on paper are not goals on the pitch. A superior team that scores first does NOT need a second goal. They play chess while the inferior team plays panic. The clinical 1-0 is not a surprise — it is the expected, rational outcome of superior game management.

    - **RULE 61: THE "MEN VS. BOYS" PARADOX (U23 VS SENIOR)**:
      **THE TRIGGER:**
      A fixture where a U23/Reserve team (e.g., Dortmund II) plays against a Senior men's team (e.g., Fortuna Köln).
      **THE TACTICAL REALITY:**
      U23 offensive stats are a mirage generated against other youth teams. When boys play men, physical maturity and tactical discipline always win. The senior team will physically bully the youth team into a low-scoring grind. Youth teams do not unlock against senior opposition — they are overwhelmed by physicality, press resistance, and competitive experience.
      **THE FORBIDDEN ACTION:**
      The Supreme Court is STRICTLY FORBIDDEN from labeling any U23/Reserve team a "Home Buzzsaw" (Rule 32 override) when their opponent is a top-half senior team. You MUST NOT use a U23 team's domestic youth goal average to justify an 'Over Goals' or 'BTTS: Yes' market, as that data is explicitly generated against other youth teams and is statistically invalid in this fixture tier.
      **THE MANDATORY PIVOT:**
      You MUST favor the senior team via one of the following routes:
      1. **Match Control (Away Win / Draw No Bet)**: If the senior team is a top-half outfit with a functioning defense, target Match Control markets that survive the physical disparity.
      2. **'Under' Goal Ceilings**: If the senior team has an elite defense (conceding < 1.0 goals per game), pivot to 'Under 2.5 Goals' or 'Under 3.5 Goals', as the U23 team will fail to convert their few opportunities against experienced senior defenders.
      **RECOGNITION TRIGGERS:**
      You MUST activate Rule 61 if ANY of the following are true:
      - Team name explicitly contains 'II', 'B', 'U19', 'U21', 'U23', 'Primavera', 'Reserve', or 'Academy'.
      - Agent 1 or 2 identifies the team as a youth or reserve squad in their tactical analysis.
      - The fixture is in a lower-division league where reserve teams compete (e.g., German Bundesliga 3, English League Two).
      **FINAL WARNING:**
      Do NOT apply Rule 18 (Youth Variance Mandate) to override Rule 61 in the direction of 'Over Goals'. Rule 61 recognizes that youth-vs-youth variance is fundamentally different from youth-vs-senior variance. In a Men vs. Boys clash, the senior team's experience and physicality systematically suppress the youth team's offensive output. The mismatch is physical, not tactical.

    - **RULE 62: THE "NOTHING TO LOSE" SHOOTOUT (BROKEN DEFENSE AGGRESSION)**:
      **THE TRIGGER:**
      Rule 10 (Defensive Collapse Override) is active — a team is confirmed missing their Starting Goalkeeper AND/OR two or more starting Center-Backs.
      **THE TACTICAL REALITY:**
      A team with a catastrophically broken defense will NOT set up to defend for a 0-0 draw. They know with mathematical certainty that they will concede. Their rational managerial response is to overcompensate offensively — pressing higher, pushing full-backs forward, and playing recklessly aggressive attacking football in a bid to outscore their defensive mistakes. The match devolves into a high-variance, end-to-end transition shootout — not the sterile low-scoring grind that Match Control markets assume.
      **THE FORBIDDEN ACTION:**
      When Rule 10 (Defensive Collapse) is triggered, the Supreme Court is STRICTLY FORBIDDEN from using ANY Match Control market as the Safe Banker:
      - No Match Winner (1X2)
      - No Double Chance (1X, X2, 12)
      - No Draw No Bet
      - No Asian Handicap
      These markets assume tactical stability — which is mathematically impossible with a broken defensive structure. A broken defense creates high-variance game states that kill all Match Control bets via unexpected early concessions.
      **THE MANDATORY PIVOT:**
      The Supreme Court MUST pivot to High-Variance Goal Markets that BENEFIT from the inevitable shootout dynamic. Evaluate in strict priority order:
      1. **'Over 0.5 Goals'** — the widest structural floor. Loses ONLY on a 0-0 result. A team with nothing to lose WILL push forward — a complete double blank is structurally implausible. Select this FIRST, but ONLY if the available odds are ≥ 1.10. Below 1.10, the odds are too thin to contribute meaningful parlay value — fall through to step 2.
      2. **'BTTS: Yes'** — A team playing with nothing to lose WILL score. Their opponent with a broken defense WILL concede. Both teams will find the net.
      3. **'Over 2.5 Goals'** — The reckless, open attacking play from the broken-defense team guarantees voluminous goal chances for both sides.
      4. **'Over 1.5 Goals'** — The structural floor fallback when Over 0.5 odds are below 1.10 and BTTS/Over 2.5 odds are too low for value.
      **CONFLICT DISAMBIGUATION:**
      Rule 62 STRICTLY OVERRIDES Rule 28 (Sterile Possession Protocol) and Rule 60 (Game Management Ceiling). You CANNOT enforce a clinical 1-0 game management ceiling when the team managing the game has a broken defensive line — they cannot absorb a counter-attack, so the game CANNOT remain at 1-0.
      Rule 62 is DISTINCT from Rule 10's Supply Line Mandate / Mud Fight Trigger: The Mud Fight fires only when BOTH the attacking supply line AND the opposing defense are broken. Rule 62 fires when ONE team's defense is broken and the opponent has a functional offense. If only one condition (broken defense) exists, Rule 62 proceeds.
      **RECOGNITION TRIGGERS:**
      You MUST activate Rule 62 if ALL of the following are true:
      - One team is confirmed missing their Starting GK OR two or more starting CBs (Rule 10 trigger confirmed).
      - The opposing team has a functional offense (Dead Engine Veto from Rule 26 is NOT active for the attacking side).
      **FINAL WARNING:**
      A Match Control market in a "Nothing to Lose" game state is a death trap. Accumulator safety demands you embrace the chaos and pivot to Goal Markets. A team with nothing to lose does not park the bus — they throw everyone forward and accept the shootout. Trust the tactical reality, not the season-long Match Control statistics.


    - **RULE 63: THE DISCIPLINE PARADOX (THE FOUL-HEAVY TRAP)**:
      **THE TRIGGER:**
      A match involving teams with exceptionally high foul or yellow/red card averages.
      **THE TACTICAL REALITY:**
      The AI frequently assumes high foul counts lead to a "stop-start" game that suffocates goals. This is a FALLACY. High foul counts lead to dangerous set-pieces, penalties, and defenders playing tentatively on yellow cards. Aggressive, sloppy defending increases variance and heavily favors messy, high-scoring games.
      **THE RULE:**
      The AI is strictly FORBIDDEN from using high foul counts, yellow cards, or "stop-start/physical" narratives as justification to select an Under market (Under 2.5, Under 3.5).
      **THE PIVOT:**
      If the game is highly physical and lacks elite defensive structure, you must assume defensive errors will occur and pivot your Safe Banker to Match Control or Over markets.

    ---

    - **RULE 64: THE XG FORM PENALTY (THE DROUGHT DISCOUNT)**:

      **THE ARCHITECTURAL BUG FIX (LAZY DATA ENTRY PATCH #2):**
      The Supreme Court has historically committed a second form of "Lazy Data Entry" — correctly identifying severe recent goal droughts or catastrophic offensive form collapses in its narrative analysis, but then feeding the team's season-long Expected Goals (xG) or Goals For (GF) average directly into the Monte Carlo Simulator without any manual discount. This causes mathematical fraud: the Python engine calculates survival rates using optimistic historical averages that do not reflect the team's real-time broken confidence and offensive paralysis.

      **THE TRIGGER:**
      A team is experiencing a **severe recent goal drought** (e.g., failing to score in **3 or more consecutive matches**) OR a **sudden, catastrophic drop in offensive form** (e.g., scoring 0.3 goals per game in their last 5 matches despite a season average of 1.5+ goals per game).

      **THE TACTICAL REALITY (THE FORM OVER AVERAGE FALLACY):**
      Season-long averages are mathematically fraudulent when a team's real-time confidence is shattered. A team that has failed to score in 3+ consecutive matches is NOT the same offensive unit that their season-long 1.80 xG average suggests. Their strikers are panicking, their creative system has collapsed, and their manager is likely deploying ultra-defensive formations to stop the bleeding. Using their season average as the simulation input is a lie.

      **THE MANDATORY SIMULATION PARAMETER OVERRIDE (THE DROUGHT DISCOUNT):**
      You are **STRICTLY FORBIDDEN** from feeding a broken team's season-long average into the Simulator.

      You **MUST** manually slash their input xG parameter by **at least 50%** to reflect their real-time reality:

      1. **THE 50% DROUGHT PENALTY:**
         - Example: If a team's season average is 1.80 xG per game, but they have failed to score in their last 3 matches, you MUST input **0.90 xG or lower** into the simulation.
         - Example: If a team's season average is 1.40 xG per game, but they have scored only 1 goal in their last 5 matches (0.20 GPG), you MUST input **0.70 xG or lower** into the simulation.

      2. **THE FORM OVERRIDE MANDATE:**
         - Form overrides history. A 4-game scoreless drought is a structural offensive collapse, not a statistical anomaly.
         - If the team's recent form shows < 0.5 goals per game over their last 5 matches, you MUST use their recent form average as the xG input (with home/away adjustment), NOT their season average.

      3. **THE ANTI-RATIONALIZATION CLAUSE:**
         - You are STRICTLY FORBIDDEN from rationalizing away this mandate with phrases like "they are due to score," "regression to the mean," or "the drought will end."
         - Confidence is a real, quantifiable variable. A striker who has missed 10 consecutive Big Chances will NOT suddenly become clinical. A team that has scored 1 goal in 5 matches will NOT suddenly score 3.
         - The simulation parameters MUST reflect the team's CURRENT psychological and tactical state, not their historical potential.

      **THE FORBIDDEN ACTION:**
      If the xG Form Penalty trigger is active for a team, the Supreme Court is **STRICTLY FORBIDDEN** from:
      - Selecting ANY 'Over Goals' market ('Over 1.5', 'Over 2.5', 'BTTS: Yes') that depends on that team scoring.
      - Using that team's season-long xG average in the Monte Carlo simulation without applying the 50% Drought Discount.
      - Projecting that team to score in your Correct Score anchor (e.g., you CANNOT anchor 1-1 or 2-1 if the drought team is the one expected to score).

      **THE PIVOT:**
      If a team triggers the Drought Discount, the AI MUST pivot the Safe Banker to:
      1. **'Opponent Team Over 0.5 Goals'** (if the opponent has a functional offense).
      2. **'Under 2.5 Goals'** or **'Under 3.5 Goals'** (if BOTH teams are in drought).
      3. **'BTTS: No'** (if the drought team is unlikely to score).
      4. **Match Control markets** ('1X' or 'X2') that do NOT depend on the drought team scoring multiple goals.

      **RECOGNITION TRIGGERS:**
      Activate Rule 64 if:
      - A team has failed to score in **3 or more consecutive matches** (verified drought).
      - A team has scored fewer than **3 total goals in their last 5 matches** (< 0.6 GPG) despite a season average of >= 1.2 GPG (catastrophic form drop).
      - Agent 1 or Agent 2 explicitly mentions "goal drought," "scoreless streak," "offensive collapse," or "struggling to score."

      **CRITICAL VALIDATION:**
      Before finalizing your Supreme Court ruling, you MUST verify:
      - If you have identified a goal drought in your narrative analysis, have you applied the 50% Drought Discount to the team's xG parameter?
      - If you have NOT applied the discount, you are committing mathematical fraud and the simulation survival rates will be falsely inflated.

      **THE SAMPLE SIZE MANDATE:**
      The AI is strictly FORBIDDEN from triggering this rule if a team has played fewer than 5 matches in their current competition. Early-season metrics (Matchday 1 to 4) are statistically invalid. If the sample size is < 5, you CANNOT use this rule to override Agent 2's base projections.

        """




    
    try:
        print(f"⚖️ [Supreme Court] Adjudicating {agent_1_pitch.get('match')}...")
        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise ValueError("API Key is missing")

        # ============================================================================
        # 🛡️ RULE 40 STRICT ENFORCEMENT - Check BEFORE generating Supreme Court pick
        # ============================================================================

        # CRITICAL FIX: Extract metrics correctly from the actual data structure
        # Structure: match_data["metrics"]["Statistic Name"][team_name] = value
        metrics_dict = match_data.get("metrics", {})
        metadata = match_data.get("metadata", {})
        home_team_name = metadata.get("home_team", "")
        away_team_name = metadata.get("away_team", "")

        # Build flat metrics dicts for each team
        home_metrics = {}
        away_metrics = {}

        if metrics_dict and home_team_name and away_team_name:
            for stat_name, team_values in metrics_dict.items():
                if isinstance(team_values, dict):
                    home_metrics[stat_name] = team_values.get(home_team_name)
                    away_metrics[stat_name] = team_values.get(away_team_name)

        # Calculate preliminary combined xG for Rule 40 check
        home_xg_prelim = home_metrics.get("Expected goals (xG) per game", home_metrics.get("Goals scored per game", 1.3))
        away_xg_prelim = away_metrics.get("Expected goals (xG) per game", away_metrics.get("Goals scored per game", 1.1))

        # Handle None values (data might be missing)
        home_xg_prelim = home_xg_prelim if home_xg_prelim is not None else 1.3
        away_xg_prelim = away_xg_prelim if away_xg_prelim is not None else 1.1

        combined_xg_prelim = float(home_xg_prelim) + float(away_xg_prelim)

        # Extract league name for sport variant detection
        league_name = match_data.get("league", {}).get("name", "")
        if not league_name:
            # Fallback to tournament name from metadata
            league_name = metadata.get("tournament", "")

        rule_40_result = enforce_rule_40_strict(
            home_metrics=home_metrics,
            away_metrics=away_metrics,
            combined_xg=combined_xg_prelim,
            league_name=league_name
        )

        if rule_40_result["force_no_bet"]:
            print(f"⛔ [RULE 40 VETO] {rule_40_result['reason']}")

            match_name = agent_1_pitch.get('match', 'Unknown Match')
            return {
                "match": match_name,
                "Supreme_Court_Final_Ruling": (
                    f"⛔ RULE 40 STRICT ENFORCEMENT VETO:\n\n"
                    f"{rule_40_result['reason']}\n\n"
                    f"VERDICT: NO BET. Statistical models require minimum 5 matches per team "
                    f"and standard 11v11 format. Capital preservation is the only valid action."
                ),
                "Crucible_Simulation_Warning": (
                    f"Rule 40 Trigger: {rule_40_result['trigger']}. "
                    f"Statistical models are invalid for this scenario."
                ),
                "verdict_status": "NO_BET",
                "Arbiter_Safe_Pick": {
                    "market": "N/A",
                    "tip": f"NO BET: Rule 40 - {rule_40_result['trigger']}",
                    "confidence": 0,
                    "odds": 0
                },
                "alternative_value_pick": {
                    "market": "N/A",
                    "tip": "NO BET",
                    "confidence": 0,
                    "odds": 0,
                    "value_reasoning": "Rule 40 strict enforcement prevents all betting activity."
                },
                "home_xG": None,
                "away_xG": None,
                "variance_multiplier": None,
                "simulation_audit": f"[RULE 40 VETO: {rule_40_result['trigger']}]",
                "simulation_data": {},
                "top_scorelines": []
            }
        # ============================================================================

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{get_active_model()}:generateContent?key={api_key}"
        payload = {
            "contents": [({"parts": [{"text": prompt}]})],
            "generationConfig": {
                "temperature": 0.0, 
                "responseMimeType": "application/json"
            }
        }
        
        # Blind Backtest Mode: constrain search to pre-match data only for historical matches
        is_historical = False
        before_date = ""
        match_date = agent_1_pitch.get('match_date')
        if match_date:
            try:
                match_dt = datetime.fromisoformat(match_date.replace("Z", "+00:00"))
                now_dt = datetime.now(timezone.utc)
                if (now_dt - match_dt).total_seconds() > 0:
                    is_historical = True
                    before_date = (match_dt - timedelta(days=1)).strftime("%Y-%m-%d")
            except: pass

        if is_historical:
            blind_backtest_header = f"""    ⚠️ BLIND BACKTEST MODE — ACTIVE ⚠️
    You are analysing a HISTORICAL match for validation and backtesting purposes.
    The match has already been played, but you MUST NOT discover or use the final result.

    MANDATORY SEARCH PROTOCOL (violations invalidate this backtest):
    1. You MUST append the operator before:{before_date} to EVERY search query you execute.
    2. You MUST include at least one of these terms in every query: "preview", "predicted lineup", "injury news", "team news", "pre-match", "form guide".
    3. You are STRICTLY FORBIDDEN from searching bare team names alone. Every query MUST include pre-match terms AND the before:{before_date} operator.
    4. If a query does not contain before:{before_date}, DO NOT execute it — reformulate it first.
    5. You are STRICTLY FORBIDDEN from referencing, using, or incorporating the final score, match result, half-time score, or any in-game statistics from this fixture.

    Your goal: produce a full pre-match prediction exactly as if the match has not yet been played.
    ---

"""
            prompt_with_header = blind_backtest_header + prompt
            payload["contents"] = [({"parts": [{"text": prompt_with_header}]})]
            print(f"🔍 [Supreme Court] Blind Backtest Mode: Search enabled with before:{before_date} date constraints")

        payload["tools"] = [{"google_search": {}}]

        max_retries = 3
        parsed = None
        for attempt in range(max_retries):
            # Also check cancelled during retry loops for ultra-responsive STOP button
            check_cancelled(match_id, job_id)
            try:
                # Increased timeout to 600s to allow for deep reasoning + search
                response = requests.post(url, headers={'Content-Type': 'application/json'}, json=payload, timeout=600)
                response.raise_for_status()

                response_json = response.json()
                raw_text = response_json['candidates'][0]['content']['parts'][0]['text']

                parsed = json.loads(raw_text)
                if isinstance(parsed, list) and len(parsed) > 0:
                    parsed = parsed[0]

                # ===== PHYSICAL EXECUTION LOCK: RULE 48 / RULE 53 ENFORCEMENT =====
                # If the Supreme Court's ruling contains the phrase 'anchor to 0-0' (in any case),
                # it has committed an absolute violation of Rule 48 (0-0 Anchor Ban).
                # This is a hard failure — we raise an exception to force the retry loop to regenerate.
                ruling_text = ""
                if isinstance(parsed, dict):
                    ruling_text = str(parsed.get("Supreme_Court_Final_Ruling", "")).lower()
                    ruling_text += str(parsed.get("supreme_court", {}).get("Supreme_Court_Final_Ruling", "")).lower()
                if "anchor to 0-0" in ruling_text or "anchored to 0-0" in ruling_text or "0-0 anchor" in ruling_text:
                    print(f"🚨 [RULE 48 VIOLATION DETECTED] Supreme Court attempted a 0-0 Anchor. Forcing regeneration (attempt {attempt+1}/{max_retries})...")
                    raise ValueError("RULE_48_VIOLATION: '0-0 Anchor' detected in Supreme Court output. This is an absolute forbidden action. Regenerating.")
                # ===== END EXECUTION LOCK =====

                # If we reach here, validation passed - break out of retry loop
                break

            except ValueError as ve:
                # Rule 48 violation - retry if attempts remain
                if "RULE_48_VIOLATION" in str(ve) and attempt < max_retries - 1:
                    import time
                    print(f"⏳ Regenerating Supreme Court ruling (attempt {attempt + 2}/{max_retries})...")
                    time.sleep(5)
                    continue
                else:
                    raise
            except requests.exceptions.RequestException as e:
                if attempt < max_retries - 1:
                    import time
                    print(f"⚠️ Network error (Supreme Court). Retrying {attempt + 1}/{max_retries} in 5s...")
                    time.sleep(5)
                else:
                    raise

        try:
            from src.rag.simulator import run_crucible_simulation

            # Robust extraction of xG stats to prevent float(None) crashes
            # NOTE: Supreme Court is instructed to provide these values (lines 928-931),
            # but LLMs occasionally omit them. This fallback ensures simulation always runs.
            raw_home_xg = parsed.get("home_xG")
            raw_away_xg = parsed.get("away_xG")
            raw_var = parsed.get("variance_multiplier")

            # Use intelligent fallback system for xG extraction
            # (Re-use the metrics we already extracted for Rule 40)
            # If they weren't extracted yet (shouldn't happen), extract them now
            if not home_metrics or not away_metrics:
                metrics_dict = match_data.get("metrics", {})
                metadata = match_data.get("metadata", {})
                home_team_name = metadata.get("home_team", "")
                away_team_name = metadata.get("away_team", "")

                home_metrics = {}
                away_metrics = {}

                if metrics_dict and home_team_name and away_team_name:
                    for stat_name, team_values in metrics_dict.items():
                        if isinstance(team_values, dict):
                            home_metrics[stat_name] = team_values.get(home_team_name)
                            away_metrics[stat_name] = team_values.get(away_team_name)

            h_xg = get_xg_with_intelligent_fallback(
                raw_xg=raw_home_xg,
                team_metrics=home_metrics,
                is_home=True,
                match_data=match_data
            )

            a_xg = get_xg_with_intelligent_fallback(
                raw_xg=raw_away_xg,
                team_metrics=away_metrics,
                is_home=False,
                match_data=match_data
            )

            v_mult = float(raw_var) if raw_var is not None else 1.0

            # Save original LLM xG before any gate adjustments (used by overall gate cap)
            _h_xg_llm = h_xg
            _a_xg_llm = a_xg

            # ============================================================================
            # ⚖️ RULE 41 CODE ENFORCEMENT (Playoff Paralysis / Knockout Fixtures)
            # ============================================================================
            # The prompt instructs the LLM to apply a ≥25% xG discount and suppress
            # variance for knockout/cup matches. This gate enforces it when the LLM
            # outputs un-discounted season-average xG values.
            KNOCKOUT_TOURNAMENT_KEYWORDS = [
                "champions league", "europa league", "conference league",
                "fa cup", "carabao cup", "copa del rey", "dfb-pokal",
                "coupe de france", "coppa italia", "league cup", "super cup",
                "world cup", "euro ", "nations league knockout"
            ]
            KNOCKOUT_ROUND_KEYWORDS = [
                "knockout", "quarter", "semi", "final", "round of 16", "last 16",
                "round of 32", "last 32", "elimination", "play-off", "playoff"
            ]

            _tournament_text = (metadata.get("tournament", "") or "").lower()
            _round_text = (metadata.get("round", "") or "").lower()
            _sc_ruling_text = (parsed.get("Supreme_Court_Final_Ruling", "") or "").lower()

            is_knockout = (
                any(kw in _tournament_text for kw in KNOCKOUT_TOURNAMENT_KEYWORDS) or
                any(kw in _round_text for kw in KNOCKOUT_ROUND_KEYWORDS) or
                "rule 41" in _sc_ruling_text or
                "playoff paralysis" in _sc_ruling_text
            )

            # Rule 30 (Shootout Exemption / Titan Clash) explicitly overrides Rule 41.
            # When two elite teams with fully operational attacks collide, the SC can
            # legitimately void the chess-match assumption. Respect that decision.
            RULE30_OVERRIDE_KEYWORDS = [
                "rule 30", "shootout exemption", "titan clash", "titan protocol",
                "fully operational", "fully intact supply", "shootout dynamic",
                "both teams have elite", "both elite",
                "level aggregate", "tied on aggregate", "aggregate is level",
                "aggregate tied", "level after first leg"
            ]
            is_rule30_override = any(kw in _sc_ruling_text for kw in RULE30_OVERRIDE_KEYWORDS)

            # Validate "Intact Supply Lines" claim against actual injury multipliers.
            # Rule 30 Condition A requires BOTH teams to have no key attacker absent.
            # If the SC claims intact supply lines but injury_xg_multiplier < 0.90 for
            # either team (star striker / primary playmaker missing), the claim is factually
            # wrong and the override is voided — Rule 41 must stand.
            if is_rule30_override:
                _supply_claim_kws = ["fully intact supply", "fully operational", "intact supply lines", "intact supply line"]
                _is_supply_line_claim = any(kw in _sc_ruling_text for kw in _supply_claim_kws)
                if _is_supply_line_claim:
                    _inj_h_r30 = float(parsed.get("injury_xg_multiplier_home") or 1.0)
                    _inj_a_r30 = float(parsed.get("injury_xg_multiplier_away") or 1.0)
                    if _inj_h_r30 < 0.90 or _inj_a_r30 < 0.90:
                        is_rule30_override = False
                        print(f"⚖️  [Rule 41 Gate] Rule 30 'Intact Supply Lines' claim VOID — "
                              f"key attacker absent (inj_h={_inj_h_r30:.2f}, inj_a={_inj_a_r30:.2f}). "
                              f"Rule 41 enforced.")

            RULE41_XG_DISCOUNT = 0.75    # 25% reduction as specified in Rule 41 prompt
            RULE41_MAX_VARIANCE = 0.80   # NegBinom/Chaos forbidden in knockout fixtures

            if is_knockout and not is_rule30_override:
                # Read asymmetric exemption flags — desperate teams are NOT discounted
                _r41_exempt_h = bool(parsed.get("rule41_exempt_home") or False)
                _r41_exempt_a = bool(parsed.get("rule41_exempt_away") or False)

                _combined_raw = h_xg + a_xg
                # Only apply discount if LLM has NOT already discounted
                # (if LLM complied, combined xG would already be well below season average)
                if _combined_raw > 2.5:
                    _orig_h, _orig_a = h_xg, a_xg
                    if not _r41_exempt_h:
                        h_xg = round(h_xg * RULE41_XG_DISCOUNT, 2)
                    if not _r41_exempt_a:
                        a_xg = round(a_xg * RULE41_XG_DISCOUNT, 2)
                    if h_xg != _orig_h or a_xg != _orig_a:
                        print(f"⚖️  [Rule 41] Asymmetric discount: "
                              f"Home {_orig_h}→{h_xg} {'(exempt-attacking)' if _r41_exempt_h else '(discounted)'}, "
                              f"Away {_orig_a}→{a_xg} {'(exempt-attacking)' if _r41_exempt_a else '(discounted)'}")
                # Only suppress variance if at least one team is conservatively managed
                if v_mult > RULE41_MAX_VARIANCE:
                    if not (_r41_exempt_h and _r41_exempt_a):
                        _orig_v = v_mult
                        v_mult = RULE41_MAX_VARIANCE
                        parsed["variance_multiplier"] = v_mult
                        print(f"⚖️  [Rule 41] Variance suppressed: {_orig_v:.2f}→{v_mult:.2f} "
                              f"(NegBinom/Chaos forbidden in knockout)")
            # ============================================================================

            # ============================================================================
            # 🛡️ DEFENSIVE MATCHUP xG ADJUSTMENT
            # ============================================================================
            # Scale each team's attacking xG by the opponent's defensive strength.
            # e.g. Arsenal concedes 0.5 goals/game away → Sporting's 2.20 xG becomes
            # 2.20 × (0.5 / 1.20) = 0.92 — much more realistic for this specific matchup.
            LEAGUE_AVG_GOALS_CONCEDED = 1.20   # typical European league average
            DEF_MATCHUP_MIN_MULTIPLIER = 0.50  # floor: never reduce by more than 50%
            DEF_MATCHUP_MAX_MULTIPLIER = 1.30  # ceiling: LLM already accounts for known defensive weakness

            _home_ga = home_metrics.get("Goals conceded per game") or 0
            _away_ga = away_metrics.get("Goals conceded per game") or 0

            if _home_ga > 0 and _away_ga > 0:
                # Home attack vs Away team's defensive record
                _h_def_mult = max(min(_away_ga / LEAGUE_AVG_GOALS_CONCEDED, DEF_MATCHUP_MAX_MULTIPLIER), DEF_MATCHUP_MIN_MULTIPLIER)
                # Away attack vs Home team's defensive record
                _a_def_mult = max(min(_home_ga / LEAGUE_AVG_GOALS_CONCEDED, DEF_MATCHUP_MAX_MULTIPLIER), DEF_MATCHUP_MIN_MULTIPLIER)

                _h_pre, _a_pre = h_xg, a_xg
                h_xg = round(h_xg * _h_def_mult, 2)
                a_xg = round(a_xg * _a_def_mult, 2)
                print(f"🛡️  [Defensive Matchup] Home xG {_h_pre}→{h_xg} "
                      f"(opp GA/game {_away_ga:.2f}, mult {_h_def_mult:.2f}), "
                      f"Away xG {_a_pre}→{a_xg} "
                      f"(opp GA/game {_home_ga:.2f}, mult {_a_def_mult:.2f})")
            # ============================================================================

            # ============================================================================
            # 🏥 INJURY IMPACT xG GATE
            # ============================================================================
            # Part A: Attacking injuries — reduce own team's attacking xG
            _INJURY_MIN_MULT = 0.70
            _INJURY_MAX_MULT = 1.00
            _inj_mult_h = float(parsed.get("injury_xg_multiplier_home") or 1.0)
            _inj_mult_a = float(parsed.get("injury_xg_multiplier_away") or 1.0)
            _inj_mult_h = max(min(_inj_mult_h, _INJURY_MAX_MULT), _INJURY_MIN_MULT)
            _inj_mult_a = max(min(_inj_mult_a, _INJURY_MAX_MULT), _INJURY_MIN_MULT)
            if _inj_mult_h < 1.0 or _inj_mult_a < 1.0:
                _inj_h_pre, _inj_a_pre = h_xg, a_xg
                h_xg = round(h_xg * _inj_mult_h, 2)
                a_xg = round(a_xg * _inj_mult_a, 2)
                print(f"🏥  [Injury Gate - Attack] Home {_inj_h_pre}→{h_xg} (mult {_inj_mult_h:.2f}), "
                      f"Away {_inj_a_pre}→{a_xg} (mult {_inj_mult_a:.2f})")

            # Part B: Defensive injuries — boost opponent's attacking xG
            _DEF_INJ_MAX_BOOST = 1.25
            _def_boost_h = float(parsed.get("defensive_injury_xg_boost_home") or 1.0)
            _def_boost_a = float(parsed.get("defensive_injury_xg_boost_away") or 1.0)
            _def_boost_h = min(_def_boost_h, _DEF_INJ_MAX_BOOST)
            _def_boost_a = min(_def_boost_a, _DEF_INJ_MAX_BOOST)
            if _def_boost_h > 1.0 or _def_boost_a > 1.0:
                _def_h_pre, _def_a_pre = h_xg, a_xg
                h_xg = round(h_xg * _def_boost_h, 2)
                a_xg = round(a_xg * _def_boost_a, 2)
                print(f"🏥  [Injury Gate - Defense] Home {_def_h_pre}→{h_xg} "
                      f"(opp def crisis {_def_boost_h:.2f}), "
                      f"Away {_def_a_pre}→{a_xg} (opp def crisis {_def_boost_a:.2f})")
            # ============================================================================

            # ============================================================================
            # 🚨 RELEGATION MOTIVATION xG BOOST
            # ============================================================================
            # Teams fighting relegation (bottom 3-4, within 3-4 points of drop zone)
            # drastically overperform season averages in survival matches. Season stats
            # include low-motivation fixtures; this gate corrects for survival desperation.
            _RELG_MAX_BOOST = 1.20
            _relg_boost_h = float(parsed.get("relegation_pressure_boost_home") or 1.0)
            _relg_boost_a = float(parsed.get("relegation_pressure_boost_away") or 1.0)
            _relg_boost_h = min(_relg_boost_h, _RELG_MAX_BOOST)
            _relg_boost_a = min(_relg_boost_a, _RELG_MAX_BOOST)
            if _relg_boost_h > 1.0 or _relg_boost_a > 1.0:
                _relg_h_pre, _relg_a_pre = h_xg, a_xg
                h_xg = round(h_xg * _relg_boost_h, 2)
                a_xg = round(a_xg * _relg_boost_a, 2)
                print(f"🚨  [Relegation Gate] Home {_relg_h_pre}→{h_xg} "
                      f"(survival boost {_relg_boost_h:.2f}), "
                      f"Away {_relg_a_pre}→{a_xg} (survival boost {_relg_boost_a:.2f})")
            # ============================================================================

            # ============================================================================
            # 🔒 TOTAL GATE xG CAP
            # ============================================================================
            # Safety net: all upward gate adjustments combined cannot exceed 40% above the
            # original LLM estimate. The LLM already has full match context when setting xG —
            # gates add marginal corrections, not wholesale replacements of LLM judgment.
            _TOTAL_GATE_MAX_BOOST = 1.40
            _h_gate_cap = round(_h_xg_llm * _TOTAL_GATE_MAX_BOOST, 2)
            _a_gate_cap = round(_a_xg_llm * _TOTAL_GATE_MAX_BOOST, 2)
            if h_xg > _h_gate_cap:
                print(f"🔒  [Gate Cap] Home xG capped: {h_xg}→{_h_gate_cap} "
                      f"(max {_TOTAL_GATE_MAX_BOOST}× LLM estimate {_h_xg_llm})")
                h_xg = _h_gate_cap
            if a_xg > _a_gate_cap:
                print(f"🔒  [Gate Cap] Away xG capped: {a_xg}→{_a_gate_cap} "
                      f"(max {_TOTAL_GATE_MAX_BOOST}× LLM estimate {_a_xg_llm})")
                a_xg = _a_gate_cap
            # ============================================================================

            # ============================================================================
            # 🛡️ VARIANCE MULTIPLIER SANITY CHECK
            # ============================================================================
            # Prevent chaos mode (variance > 1.2) when combined xG doesn't support it
            combined_xg = h_xg + a_xg

            if v_mult > 1.2 and combined_xg < 3.0:
                print(f"⚙️ [VARIANCE CORRECTION] Variance {v_mult:.2f} too high for combined xG {combined_xg:.2f}")
                print(f"   Chaos mode (NegBinom) should ONLY activate for high-scoring games (xG >= 3.0)")
                print(f"   Forcing variance = 1.0 (Standard Poisson)")
                v_mult = 1.0
                parsed["variance_multiplier"] = 1.0

            # Additional check: If variance > 1.0 but combined xG < 2.5, also force 1.0
            elif v_mult > 1.0 and combined_xg < 2.5:
                print(f"⚙️ [VARIANCE CORRECTION] Variance {v_mult:.2f} inappropriate for low-scoring match (xG {combined_xg:.2f})")
                print(f"   Low-scoring matches (xG < 2.5) should use Standard Poisson")
                print(f"   Forcing variance = 1.0")
                v_mult = 1.0
                parsed["variance_multiplier"] = 1.0
            # ============================================================================

            # ============================================================================
            # 🛡️ RULE 35 (DEAD ENGINE) VALIDATION LAYER
            # ============================================================================
            # Check for Dead Engine scenarios BEFORE finalizing the pick
            home_form_data = match_data.get("home_form")
            away_form_data = match_data.get("away_form")

            dead_engine_check = check_dead_engine_veto(
                home_metrics=home_metrics,
                away_metrics=away_metrics,
                home_form=home_form_data,
                away_form=away_form_data
            )

            # NEW: Check for bilateral drought (BOTH teams simultaneously)
            bilateral_check = check_bilateral_dead_engine(
                home_metrics=home_metrics,
                away_metrics=away_metrics,
                home_form=home_form_data,
                away_form=away_form_data
            )

            if bilateral_check["bilateral_drought"]:
                print(f"⚠️ [BILATERAL DROUGHT DETECTED] {bilateral_check['veto_message']}")

            if dead_engine_check["veto_active"]:
                print(f"⚠️ [DEAD ENGINE VETO] {dead_engine_check['veto_message']}")

            # Run validation if ANY veto is active
            if dead_engine_check["veto_active"] or bilateral_check["bilateral_drought"]:
                # Extract GA data for Rule 53 check
                home_ga = home_metrics.get("Goals conceded per game", 0)
                away_ga = away_metrics.get("Goals conceded per game", 0)

                # Calculate combined xG for context-aware Rule 53 validation
                combined_xg_for_validation = h_xg + a_xg

                # Validate the Supreme Court's pick
                arbiter_pick = parsed.get("Arbiter_Safe_Pick", {}).get("tip", "")
                validation_result = validate_supreme_court_pick(
                    pick=arbiter_pick,
                    home_ga=home_ga,
                    away_ga=away_ga,
                    dead_engine_check=dead_engine_check,
                    bilateral_check=bilateral_check,
                    combined_xg=combined_xg_for_validation
                )

                if not validation_result["is_valid"]:
                    print(f"🚨 [VALIDATION FAILURE] {validation_result['violation']}")
                    print(f"📋 [AUTO-CORRECTION] Forcing pivot to: {validation_result['recommended_pivot']}")

                    # Determine corrected pick based on scenario
                    if bilateral_check.get("both_teams_dead"):
                        # Bilateral dead engine → Force NO BET or Under 2.5
                        if "NO BET" in validation_result["recommended_pivot"]:
                            parsed["Arbiter_Safe_Pick"]["tip"] = "NO BET: Bilateral Dead Engine detected"
                            parsed["Arbiter_Safe_Pick"]["market"] = "N/A"
                            parsed["verdict_status"] = "NO_BET"
                        else:
                            parsed["Arbiter_Safe_Pick"]["tip"] = "Under 2.5 Goals"
                            parsed["Arbiter_Safe_Pick"]["market"] = "Match_Goals"
                    else:
                        # Single dead engine or low-scoring → Under 3.5
                        parsed["Arbiter_Safe_Pick"]["tip"] = "Under 3.5 Goals"
                        parsed["Arbiter_Safe_Pick"]["market"] = "Match_Goals"

                    parsed["Supreme_Court_Final_Ruling"] = (
                        f"⚠️ AUTOMATIC CORRECTION APPLIED:\n\n"
                        f"{validation_result['violation']}\n\n"
                        f"CORRECTED PICK: {validation_result['recommended_pivot']}\n\n"
                        f"ORIGINAL RULING:\n{parsed.get('Supreme_Court_Final_Ruling', '')}"
                    )

                    # Force variance multiplier to 1.0 (standard Poisson, no chaos mode)
                    if v_mult > 1.0:
                        print(f"⚙️ [VARIANCE CORRECTION] Reducing variance_multiplier from {v_mult:.2f} to 1.0 (Dead Engine detected)")
                        v_mult = 1.0
                        parsed["variance_multiplier"] = 1.0
            # ============================================================================

            # Robust extraction of Agent 2's pick (handling fallback to Agent 1's safe_bet_tip)
            primary_obj = agent_2_critique.get("primary_pick", {})
            a2_pick = "N/A"
            if isinstance(primary_obj, dict):
                a2_pick = primary_obj.get("tip", agent_2_critique.get("safe_bet_tip", "N/A"))
            elif isinstance(primary_obj, str):
                a2_pick = primary_obj

            # NEW: Phase 1 - Extract corners and cards data for simulation
            # Default values: ~5 corners per team, ~2 cards per team (typical football averages)
            home_corners = home_metrics.get("Corner kicks per game", 5.0)
            away_corners = away_metrics.get("Corner kicks per game", 5.0)

            # Calculate cards per game from yellow/red cards
            home_matches = home_metrics.get("Matches", 1) or 1
            away_matches = away_metrics.get("Matches", 1) or 1
            home_yellow = home_metrics.get("Yellow cards", 0) or 0
            home_red = home_metrics.get("Red cards", 0) or 0
            away_yellow = away_metrics.get("Yellow cards", 0) or 0
            away_red = away_metrics.get("Red cards", 0) or 0

            # Total cards per game (yellows + reds, weighted by 1)
            home_cards = (home_yellow + home_red) / home_matches
            away_cards = (away_yellow + away_red) / away_matches

            # Safety: Ensure we have valid numbers
            if home_corners is None or not isinstance(home_corners, (int, float)):
                home_corners = 5.0
            if away_corners is None or not isinstance(away_corners, (int, float)):
                away_corners = 5.0
            if home_cards < 0: home_cards = 2.0
            if away_cards < 0: away_cards = 2.0

            print(f"📊 [Phase 1] Corners: Home={home_corners:.1f}, Away={away_corners:.1f}. Cards: Home={home_cards:.1f}, Away={away_cards:.1f}")

            # NEW: Extract alternative markets from Supreme Court response
            alternative_markets_list = []
            validated_alternatives = parsed.get("validated_alternative_markets", [])
            if validated_alternatives and isinstance(validated_alternatives, list):
                for alt_market in validated_alternatives:
                    if isinstance(alt_market, dict) and "tip" in alt_market:
                        alternative_markets_list.append(alt_market["tip"])
                print(f"🔍 [Alternative Markets] Testing {len(alternative_markets_list)} additional picks: {alternative_markets_list}")

            # Normalize team-name picks to generic Home/Away Team format before simulator call.
            # e.g. "Como 1907 Over 0.5 Goals" → "Home Team Over 0.5 Goals"
            # Prevents team-name picks falling through to match-level "over 0.5" check (96.9% bug).
            def _normalize_pick_for_sim(pick, ht, at):
                p = pick.lower().strip()
                ht_l = ht.lower().strip() if ht else ""
                at_l = at.lower().strip() if at else ""
                for threshold, side, normalized in [
                    ("over 0.5",  "home", "Home Team Over 0.5 Goals"),
                    ("over 1.5",  "home", "Home Team Over 1.5 Goals"),
                    ("under 0.5", "home", "Home Team Under 0.5 Goals"),
                    ("under 1.5", "home", "Home Team Under 1.5 Goals"),
                    ("over 0.5",  "away", "Away Team Over 0.5 Goals"),
                    ("over 1.5",  "away", "Away Team Over 1.5 Goals"),
                    ("under 0.5", "away", "Away Team Under 0.5 Goals"),
                    ("under 1.5", "away", "Away Team Under 1.5 Goals"),
                ]:
                    team = ht_l if side == "home" else at_l
                    if team and team in p and threshold in p:
                        return normalized
                return pick

            a2_pick = _normalize_pick_for_sim(a2_pick, home_team_name, away_team_name)
            sc_pick = _normalize_pick_for_sim(parsed.get("Arbiter_Safe_Pick", {}).get("tip", "N/A"), home_team_name, away_team_name)
            alternative_markets_list = [_normalize_pick_for_sim(p, home_team_name, away_team_name) for p in alternative_markets_list]

            sim_res = run_crucible_simulation(
                home_xG=h_xg,
                away_xG=a_xg,
                variance_multiplier=v_mult,
                agent_2_pick=a2_pick,
                supreme_court_pick=sc_pick,
                home_corners_avg=home_corners,  # NEW: Phase 1
                away_corners_avg=away_corners,  # NEW: Phase 1
                home_cards_avg=home_cards,      # NEW: Phase 1
                away_cards_avg=away_cards,       # NEW: Phase 1
                alternative_picks=alternative_markets_list if alternative_markets_list else None  # NEW: Pass alternative markets
            )
            parsed["simulation_audit"] = sim_res["audit_string"]
            parsed["simulation_data"] = sim_res["distribution"]
            parsed["top_scorelines"] = sim_res["top_scorelines"]

            # NEW: Store alternative results if present
            if "alternative_results" in sim_res:
                parsed["alternative_results"] = sim_res["alternative_results"]
        except Exception as sim_e:
            print(f"Crucible Simulator Execution Failed: {sim_e}")
            parsed["simulation_audit"] = "[SIMULATION AUDIT: Failed to run mathematical simulation.]"
            parsed["simulation_data"] = {}
            parsed["top_scorelines"] = []

        return parsed

    except Exception as e:
        print(f"Supreme Court Error: {e}")
        
        # Safely extract the match string from the first agent's pitch to avoid NameError
        match_name = agent_1_pitch.get('match', 'Unknown Match') if isinstance(agent_1_pitch, dict) else 'Unknown Match'
        
        return {
            "match": match_name,
            "Supreme_Court_Final_Ruling": f"The supreme court failed due to an technical error: {str(e)}",
            "Crucible_Simulation_Warning": "Technical variance is too high.",
            "verdict_status": "NO_BET",
            "Arbiter_Safe_Pick": {"market": "N/A", "tip": "N/A", "confidence": 0},
            "alternative_value_pick": {"market": "N/A", "tip": "N/A", "confidence": 0, "value_reasoning": "Error occurred."}
        }
