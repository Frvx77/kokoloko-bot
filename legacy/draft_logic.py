import random

# 1. THE CONFIGURATION
# Based on your screenshot
BASE_PROBABILITIES = {
    300: 0.03, 260: 0.05, 240: 0.05, 220: 0.07, 200: 0.07,
    180: 0.10, 160: 0.13, 140: 0.13, 120: 0.10, 100: 0.07,
    80: 0.07, 60: 0.05, 40: 0.05, 20: 0.03
}

# Dummy Database (In reality, this comes from your CSV)
POKEMON_DB = {
    300: ["Mewtwo", "Rayquaza", "Arceus", "Giratina", "Dialga"],
    260: ["Dragonite", "Tyranitar", "Metagross", "Salamence", "Garchomp"],
    240: ["Charizard", "Blastoise", "Venusaur", "Gengar", "Alakazam"],
    # ... fill with more later ...
    100: ["Pikachu", "Eevee", "Meowth", "Psyduck", "Growlithe"]
}


def get_valid_tiers(user_roster, pick_number):
    """
    Determines which tiers are allowed for this specific pick.
    """
    allowed_tiers = list(BASE_PROBABILITIES.keys())

    # RULE: Max 1 of Tier 300, 260, 240
    if any(p['tier'] == 300 for p in user_roster):
        if 300 in allowed_tiers: allowed_tiers.remove(300)

    if any(p['tier'] == 260 for p in user_roster):
        if 260 in allowed_tiers: allowed_tiers.remove(260)

    if any(p['tier'] == 240 for p in user_roster):
        if 240 in allowed_tiers: allowed_tiers.remove(240)

    # RULE: Pity System (Guaranteed 300 on 5th pick if missing)
    has_300 = any(p['tier'] == 300 for p in user_roster)
    if pick_number == 5 and not has_300:
        return [300]  # FORCE Tier 300

    return allowed_tiers


def calculate_dynamic_probabilities(valid_tiers):
    """
    Redistributes the % of banned tiers proportionally among valid ones.
    """
    # 1. Get the base % sum of allowed tiers
    current_sum = sum(BASE_PROBABILITIES[t] for t in valid_tiers)

    # 2. Create new probability map
    new_probs = {}
    for t in valid_tiers:
        # Formula: (Base% / Sum of Valid Base%)
        new_probs[t] = BASE_PROBABILITIES[t] / current_sum

    return new_probs


def roll_pokemon(valid_tiers, burned_pokemon_names=[]):
    """
    Picks a Tier, then picks a Pokemon.
    """
    # 1. Calculate Probabilities
    probs_map = calculate_dynamic_probabilities(valid_tiers)
    tiers = list(probs_map.keys())
    weights = list(probs_map.values())

    # 2. Roll the Tier
    selected_tier = random.choices(tiers, weights=weights, k=1)[0]

    # 3. Roll the Pokemon (Avoiding Burned ones)
    # Get all pokemon in that tier
    available_in_tier = POKEMON_DB.get(selected_tier, [f"MissingNo-{selected_tier}"])

    # Filter out ones we already rejected (burned)
    valid_candidates = [p for p in available_in_tier if p not in burned_pokemon_names]

    if not valid_candidates:
        return None, "Error: No Pokémon left in this tier!"

    selected_pokemon = random.choice(valid_candidates)

    return selected_pokemon, selected_tier


# --- SIMULATION ---
if __name__ == "__main__":
    print("--- STARTING DRAFT SIMULATION ---")

    # Scenario: Coach Ash has already picked a Tier 260
    roster = [{'name': 'Tyranitar', 'tier': 260}]
    pick_num = 2
    burned = []  # No re-rolls yet

    print(f"Roster: {roster}")

    # Step 1: Check Logic
    valid = get_valid_tiers(roster, pick_num)
    print(f"Valid Tiers: {valid}")
    # Expectation: 260 should be GONE.

    # Step 2: Roll
    poke, tier = roll_pokemon(valid, burned)
    print(f"Rolled: {poke} (Tier {tier})")

    # Step 3: Simulate a Re-Roll
    print(f"\n--- PLAYER REQUESTS RE-ROLL ---")
    burned.append(poke)  # Burn the previous pick
    print(f"Burned List: {burned}")

    poke2, tier2 = roll_pokemon(valid, burned)
    print(f"Re-Rolled: {poke2} (Tier {tier2})")

    # Step 4: Test Pity System
    print(f"\n--- TESTING PITY SYSTEM (Pick 5) ---")
    roster_no_300 = [{'tier': 100}, {'tier': 100}, {'tier': 100}, {'tier': 100}]
    valid_pity = get_valid_tiers(roster_no_300, 5)
    print(f"Valid Tiers for Pick 5 (No 300 yet): {valid_pity}")
    # Expectation: Should only show [300]