import os
import discord
import pandas as pd
import random
import asyncio
import time # <--- Add this
from dotenv import load_dotenv
from discord.ext import commands


# --- CONFIGURATION ---
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
CSV_FILE = 'pokemon_data.csv'
STAFF_ROLE_NAME = "NPO-Draft Staff"

# Game Settings
MAX_REROLLS = 10
MAX_POINTS = 1200
MIN_TIER_COST = 20
TOTAL_POKEMON = 10
ROLL_TIMEOUT = 60  # Seconds for the "Click to Roll" button

# Probabilities
TIER_PROBS = {
    300: 0.03, 260: 0.05, 240: 0.05, 220: 0.07, 200: 0.07,
    180: 0.10, 160: 0.13, 140: 0.13, 120: 0.10, 100: 0.07,
    80: 0.07, 60: 0.05, 40: 0.05, 20: 0.03
}

# --- BOT SETUP ---
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# --- STATE MANAGEMENT ---
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


# --- LOGIC FUNCTIONS ---

def load_data():
    global pokemon_db
    if os.path.exists(CSV_FILE):
        pokemon_db = pd.read_csv(CSV_FILE)
        pokemon_db.columns = pokemon_db.columns.str.strip().str.lower()
        print(f"✅ CSV Loaded: {len(pokemon_db)} Pokemon found.")
    else:
        print(f"❌ ERROR: File {CSV_FILE} not found.")


def get_valid_tiers(user_id, pick_number):
    """Calculates valid tiers based on Rules + Salary Cap"""
    user_roster = draft_state["rosters"].get(user_id, [])
    points_spent = draft_state["points"].get(user_id, 0)

    allowed = list(TIER_PROBS.keys())

    # RULE A: CLASS RESTRICTIONS (Independent - Max 1 of each)
    has_300 = any(p['tier'] == 300 for p in user_roster)
    if has_300 and 300 in allowed: allowed.remove(300)

    has_260 = any(p['tier'] == 260 for p in user_roster)
    if has_260 and 260 in allowed: allowed.remove(260)

    has_240 = any(p['tier'] == 240 for p in user_roster)
    if has_240 and 240 in allowed: allowed.remove(240)

    # RULE B: SALARY CAP MATH
    points_remaining = MAX_POINTS - points_spent
    picks_remaining_total = TOTAL_POKEMON - (pick_number - 1)
    future_picks_needed = picks_remaining_total - 1

    # Minimum cash needed for the FUTURE
    reserve_cash = future_picks_needed * MIN_TIER_COST

    # Max we can spend NOW
    max_affordable_now = points_remaining - reserve_cash

    allowed = [t for t in allowed if t <= max_affordable_now]

    # RULE C: PITY SYSTEM (Guaranteed 300 on pick 5 if affordable)
    if pick_number == 5 and not has_300:
        if 300 in allowed:
            return [300]

    return allowed


def roll_pokemon(valid_tiers):
    if not valid_tiers: return None, "NO_VALID_TIERS"

    current_sum = sum(TIER_PROBS[t] for t in valid_tiers)
    if current_sum == 0: return None, "ZERO_SUM"

    weights = [TIER_PROBS[t] / current_sum for t in valid_tiers]
    selected_tier = random.choices(valid_tiers, weights=weights, k=1)[0]

    pool = pokemon_db[pokemon_db['tier'] == selected_tier]
    candidates = pool[~pool['name'].isin(draft_state['burned'])]

    # Exclude pokemon picked by others globally
    all_picked = []
    for roster in draft_state["rosters"].values():
        for p in roster:
            all_picked.append(p['name'])
    candidates = candidates[~candidates['name'].isin(all_picked)]

    if candidates.empty:
        return None, "EMPTY_TIER_POOL"

    picked = candidates.sample(n=1).iloc[0]
    return picked['name'], int(picked['tier'])


async def display_summary(channel):
    """Prints scorecard"""
    if not draft_state["rosters"]:
        await channel.send("📊 No data yet.")
        return

    embed = discord.Embed(title="📊 Draft Summary / Results", color=0x3498db)

    unique_ids = []
    unique_players = []
    for p in draft_state['order']:
        if p.id not in unique_ids:
            unique_ids.append(p.id)
            unique_players.append(p)

    for player in unique_players:
        roster = draft_state["rosters"].get(player.id, [])
        points_spent = draft_state["points"].get(player.id, 0)
        points_left = MAX_POINTS - points_spent
        rerolls_used = draft_state["rerolls"].get(player.id, 0)
        rerolls_left = MAX_REROLLS - rerolls_used

        if roster:
            pokemon_list = "\n".join([f"• **{p['name']}** ({p['tier']})" for p in roster])
        else:
            pokemon_list = "*(No picks yet)*"

        field_value = (
            f"{pokemon_list}\n"
            f"-------------------\n"
            f"💰 **Points:** {points_spent}/{MAX_POINTS} (Left: {points_left})\n"
            f"🎲 **Re-rolls:** {rerolls_left} left"
        )
        embed.add_field(name=f"👤 {player.display_name}", value=field_value, inline=True)

    await channel.send(embed=embed)


# --- DISCORD UI VIEWS ---

class RollView(discord.ui.View):
    """The 'Click to Roll' Button"""

    def __init__(self, coach_user):
        super().__init__(timeout=ROLL_TIMEOUT)
        self.coach = coach_user
        self.clicked = False

    async def disable_all(self, interaction):
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(view=self)

    @discord.ui.button(label="🎲 ROLL DICE", style=discord.ButtonStyle.primary, emoji="🎲")
    async def roll_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.coach.id:
            await interaction.response.send_message("🚫 Not your turn!", ephemeral=True)
            return

        self.clicked = True
        await self.disable_all(interaction)
        self.stop()


class DraftView(discord.ui.View):
    """The Keep/Reroll Buttons"""

    def __init__(self, coach_user):
        super().__init__(timeout=300)
        self.coach = coach_user
        self.value = None
        self.clicked_by = None

    async def check_permissions(self, interaction):
        is_coach = interaction.user.id == self.coach.id
        is_staff = discord.utils.get(interaction.user.roles, name=STAFF_ROLE_NAME) is not None

        if not (is_coach or is_staff):
            await interaction.response.send_message("🚫 You are not the Coach or Staff.", ephemeral=True)
            return False
        return True

    async def disable_all(self, interaction):
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(view=self)

    @discord.ui.button(label="✅ Accept (Keep)", style=discord.ButtonStyle.success)
    async def keep(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.check_permissions(interaction): return
        self.value = "KEEP"
        self.clicked_by = interaction.user
        await self.disable_all(interaction)
        self.stop()

    @discord.ui.button(label="🎲 Re-Roll", style=discord.ButtonStyle.danger)
    async def reroll(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.check_permissions(interaction): return
        self.value = "REROLL"
        self.clicked_by = interaction.user
        await self.disable_all(interaction)
        self.stop()


# --- COMMANDS ---

@bot.event
async def on_ready():
    load_data()
    print(f'🤖 {bot.user} ready.')


@bot.command()
async def summary(ctx):
    await display_summary(ctx.channel)


@bot.command()
async def start_draft(ctx, *members: discord.Member):
    if not members:
        await ctx.send("❌ Mention players. Ex: `!start_draft @Ash @Misty`")
        return

    players = list(members)

    draft_state["order"] = players
    draft_state["rosters"] = {p.id: [] for p in players}
    draft_state["rerolls"] = {p.id: 0 for p in players}
    draft_state["points"] = {p.id: 0 for p in players}
    draft_state["round"] = 1
    draft_state["current_index"] = 0
    draft_state["active"] = True

    names = ", ".join([p.display_name for p in players])
    await ctx.send(f"🏆 **Draft Started!** (Cap: {MAX_POINTS} pts)\n**Round 1**\nOrder: {names}")

    await next_turn(ctx.channel)


async def next_turn(channel):
    # 1. Round / End Logic
    if draft_state["current_index"] >= len(draft_state["order"]):

        # --- FIX: Stop logic BEFORE creating Round 11 ---
        if draft_state["round"] >= TOTAL_POKEMON:
            await channel.send("🏁 **Draft Complete!**")
            await display_summary(channel)
            draft_state["active"] = False
            return

        # Move to next round
        draft_state["round"] += 1
        draft_state["order"].reverse()
        draft_state["current_index"] = 0
        await channel.send(f"🔁 **End of Round!** Snake order for Round {draft_state['round']}...")
        await asyncio.sleep(2)

    player = draft_state["order"][draft_state["current_index"]]
    pick_num = len(draft_state["rosters"][player.id]) + 1

    # Redundant safety check (optional now, but good to keep)
    if pick_num > TOTAL_POKEMON:
        await channel.send("🏁 **Draft Complete!**")
        await display_summary(channel)
        draft_state["active"] = False
        return

    draft_state["burned"] = []

    # --- NEW STEP: PRE-ROLL INTERACTION ---

    # Calculate the exact time when the timer ends
    expiry_time = int(time.time()) + ROLL_TIMEOUT

    # Discord Magic Syntax: <t:TIMESTAMP:R> shows "in X seconds" counting down
    embed_start = discord.Embed(
        title=f"🎲 Pick #{pick_num} for {player.display_name}",
        description=f"Click the button below to roll!\n\n⏳ **Auto-roll** <t:{expiry_time}:R>",
        color=0x2ecc71
    )
    # Note: Timestamps don't work in Footers, so we moved it to Description

    roll_view = RollView(player)
    start_msg = await channel.send(f"{player.mention} It's your turn!", embed=embed_start, view=roll_view)

    await roll_view.wait()

    if not roll_view.clicked:
        await channel.send(f"⏰ **Time expired!** Auto-rolling for {player.display_name}...")
    else:
        embed_start.description = "**Rolling...** 🎰"
        await start_msg.edit(embed=embed_start, view=None)

    # --- TURN LOOP (Rerolls) ---
    while True:
        rerolls_used = draft_state["rerolls"].get(player.id, 0)
        rerolls_left = MAX_REROLLS - rerolls_used
        can_reroll = rerolls_left > 0
        points_spent = draft_state["points"].get(player.id, 0)
        points_left = MAX_POINTS - points_spent

        valid_tiers = get_valid_tiers(player.id, pick_num)

        name, tier = roll_pokemon(valid_tiers)

        if not name:
            await channel.send(f"⚠️ **CRITICAL:** No valid pokemon found for {player.name}.")
            break

        if not can_reroll:
            draft_state["rosters"][player.id].append({'name': name, 'tier': tier})
            draft_state["points"][player.id] += tier

            embed = discord.Embed(title=f"Pick #{pick_num} for {player.display_name}", color=0x95a5a6)
            embed.add_field(name="Auto-Accepted", value=f"**{name}** (Tier {tier})")
            embed.set_footer(text=f"Budget: {MAX_POINTS - draft_state['points'][player.id]} left | 0 Re-rolls left.")
            await channel.send(f"{player.mention}", embed=embed)
            break

        embed = discord.Embed(
            title=f"Pick #{pick_num} for {player.display_name}",
            description=f"Round {draft_state['round']}",
            color=0xF1C40F
        )
        embed.add_field(name="Rolled", value=f"**{name}**", inline=True)
        embed.add_field(name="Tier", value=f"{tier}", inline=True)
        embed.add_field(name="Budget", value=f"{points_left} pts left", inline=False)
        embed.set_footer(text=f"Re-rolls left: {rerolls_left}/{MAX_REROLLS}")

        view = DraftView(player)
        await channel.send(f"{player.mention}", embed=embed, view=view)

        await view.wait()

        if view.value == "REROLL":
            draft_state["rerolls"][player.id] += 1
            new_left = MAX_REROLLS - draft_state["rerolls"][player.id]
            clicker = view.clicked_by.display_name if view.clicked_by else "Staff"

            await channel.send(f"🔄 **{clicker}** re-rolled! ({new_left} left). Rolling again...")
            draft_state["burned"].append(name)
            await asyncio.sleep(1)
            continue

        elif view.value == "KEEP" or view.value == "TIMEOUT":
            draft_state["rosters"][player.id].append({'name': name, 'tier': tier})
            draft_state["points"][player.id] += tier

            if view.value == "KEEP":
                clicker = view.clicked_by.display_name if view.clicked_by else "Staff"
                await channel.send(f"✅ **{clicker}** accepted **{name}**.")
            else:
                await channel.send(f"⏰ Timeout: Auto-accepted **{name}**.")
            break

    draft_state["current_index"] += 1
    await asyncio.sleep(1)
    await next_turn(channel)


if TOKEN:
    bot.run(TOKEN)
else:
    print("❌ Error: TOKEN missing.")