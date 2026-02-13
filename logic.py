import pandas as pd
import random
import config
import os

# --- STATE MANAGEMENT ---
# This dictionary holds the entire game state
draft_state = {
    "active": False,
    "round": 1,
    "order": [],
    "current_index": 0,
    "rosters": {},  # {user_id: [{'name': 'Mew', 'tier': 300}, ...]}
    "rerolls": {},  # {user_id: 5}
    "points": {},  # {user_id: 300}
    "burned": []
}

pokemon_db = pd.DataFrame()


def load_data():
    global pokemon_db
    if os.path.exists(config.CSV_FILE):
        pokemon_db = pd.read_csv(config.CSV_FILE)
        pokemon_db.columns = pokemon_db.columns.str.strip().str.lower()
        print(f"✅ Logic: CSV Loaded ({len(pokemon_db)} rows).")
    else:
        print(f"❌ Logic Error: File {config.CSV_FILE} not found.")


def initialize_draft(players):
    """Resets the state for a new game"""
    draft_state["order"] = players
    draft_state["rosters"] = {p.id: [] for p in players}
    draft_state["rerolls"] = {p.id: 0 for p in players}
    draft_state["points"] = {p.id: 0 for p in players}
    draft_state["round"] = 1
    draft_state["current_index"] = 0
    draft_state["active"] = True
    draft_state["burned"] = []


def get_valid_tiers(user_id, pick_number):
    """Core Logic for High Tier Restrictions + Salary Cap"""
    user_roster = draft_state["rosters"].get(user_id, [])
    points_spent = draft_state["points"].get(user_id, 0)

    allowed = list(config.TIER_PROBS.keys())

    # --- RULE A: HIGH TIER LOGIC ---
    count_300 = sum(1 for p in user_roster if p['tier'] == 300)
    count_260 = sum(1 for p in user_roster if p['tier'] == 260)
    count_240 = sum(1 for p in user_roster if p['tier'] == 240)

    # 1. If you have a 300 -> Block all High Tiers
    if count_300 > 0:
        for t in [300, 260, 240]:
            if t in allowed: allowed.remove(t)

    # 2. If you have 2+ combination of 260/240 -> Block all High Tiers
    elif (count_260 + count_240) >= 2:
        for t in [300, 260, 240]:
            if t in allowed: allowed.remove(t)

    # 3. Intermediate restrictions
    else:
        if count_260 > 0:
            # Can only get one more 240. Block 300 and 260.
            if 300 in allowed: allowed.remove(300)
            if 260 in allowed: allowed.remove(260)

        elif count_240 > 0:
            # Can get 260 OR 240. Block 300.
            if 300 in allowed: allowed.remove(300)

    # --- RULE B: SALARY CAP ---
    points_remaining = config.MAX_POINTS - points_spent
    picks_remaining_total = config.TOTAL_POKEMON - (pick_number - 1)
    future_picks_needed = picks_remaining_total - 1

    reserve_cash = future_picks_needed * config.MIN_TIER_COST
    max_affordable_now = points_remaining - reserve_cash

    allowed = [t for t in allowed if t <= max_affordable_now]

    return allowed


def roll_pokemon(valid_tiers):
    if not valid_tiers: return None, "NO_VALID_TIERS"

    current_sum = sum(config.TIER_PROBS[t] for t in valid_tiers)
    if current_sum == 0: return None, "ZERO_SUM"

    weights = [config.TIER_PROBS[t] / current_sum for t in valid_tiers]
    selected_tier = random.choices(valid_tiers, weights=weights, k=1)[0]

    pool = pokemon_db[pokemon_db['tier'] == selected_tier]
    candidates = pool[~pool['name'].isin(draft_state['burned'])]

    # Exclude global picks
    all_picked = []
    for roster in draft_state["rosters"].values():
        for p in roster:
            all_picked.append(p['name'])
    candidates = candidates[~candidates['name'].isin(all_picked)]

    if candidates.empty:
        return None, "EMPTY_TIER_POOL"

    picked = candidates.sample(n=1).iloc[0]
    return picked['name'], int(picked['tier'])


def calculate_tier_percentages(user_id, pick_number):
    """
    Returns a dictionary {tier: percentage} of the actual odds
    for the specific player's current turn.
    """
    valid_tiers = get_valid_tiers(user_id, pick_number)

    # Calculate total weight of currently valid tiers
    current_sum = sum(config.TIER_PROBS[t] for t in valid_tiers)

    if current_sum == 0:
        return {}

    # Calculate percentage for each tier (Weight / Total * 100)
    stats = {}
    # Sort high to low for display
    for t in sorted(valid_tiers, reverse=True):
        raw_prob = (config.TIER_PROBS[t] / current_sum) * 100
        stats[t] = raw_prob

    return stats