import discord
import asyncio
import time
from discord.ext import commands

import config
import logic
import views

# --- BOT SETUP ---
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    logic.load_data()
    print(f'🤖 KOKOLOKO: {bot.user} is ready!')


@bot.command()
async def summary(ctx):
    embed = views.create_summary_embed(logic.draft_state)
    await ctx.send(embed=embed)


@bot.command()
async def start_draft(ctx, *members: discord.Member):
    if not members:
        await ctx.send("❌ Mention players. Ex: `!start_draft @Ash @Misty`")
        return

    players = list(members)
    logic.initialize_draft(players)

    names = ", ".join([p.display_name for p in players])
    await ctx.send(f"🏆 **Draft Started!** (Cap: {config.MAX_POINTS} pts)\n**Round 1**\nOrder: {names}")

    await next_turn(ctx.channel)


async def next_turn(channel):
    state = logic.draft_state

    # 1. Round Logic
    if state["current_index"] >= len(state["order"]):
        if state["round"] >= config.TOTAL_POKEMON:
            await channel.send("🏁 **Draft Complete!**")
            await channel.send(embed=views.create_summary_embed(state))
            state["active"] = False
            return

        state["round"] += 1
        state["order"].reverse()
        state["current_index"] = 0
        await channel.send(f"🔁 **End of Round!** Snake order for Round {state['round']}...")
        await asyncio.sleep(2)

    player = state["order"][state["current_index"]]
    pick_num = len(state["rosters"][player.id]) + 1

    if pick_num > config.TOTAL_POKEMON:
        state["current_index"] += 1
        await next_turn(channel)
        return

    state["burned"] = []

    rerolls_used = state["rerolls"].get(player.id, 0)
    rerolls_left = config.MAX_REROLLS - rerolls_used
    can_reroll = rerolls_left > 0

    # --- CAMINO A: SIN REROLLS ---
    if not can_reroll:
        valid_tiers = logic.get_valid_tiers(player.id, pick_num)
        name, tier = logic.roll_pokemon(valid_tiers)

        if not name:
            await channel.send(f"⚠️ **CRITICAL:** No valid pokemon (Auto-Mode).")
        else:
            state["rosters"][player.id].append({'name': name, 'tier': tier})
            state["points"][player.id] += tier

            embed = discord.Embed(title=f"Pick #{pick_num} • {player.display_name}", color=0x95a5a6)
            embed.add_field(name="🔒 Auto-Aceptado (0 Rerolls)", value=f"**{name}** (Tier {tier})")
            embed.set_footer(text=f"Budget Left: {config.MAX_POINTS - state['points'][player.id]}")
            await channel.send(f"{player.mention}", embed=embed)

    # --- CAMINO B: CON REROLLS ---
    else:
        # STEP 1: PRE-ROLL
        expiry_roll = int(time.time()) + config.ROLL_TIMEOUT
        odds_data = logic.calculate_tier_percentages(player.id, pick_num)

        # Generamos el texto de la Grid y lo guardamos en una variable
        odds_grid_str = views.format_odds_grid(odds_data)

        # Pasamos el string a la función de creación del embed
        embed_start = views.create_roll_embed(player, pick_num, expiry_roll, odds_grid_str)

        roll_view = views.RollView(player)
        start_msg = await channel.send(f"{player.mention}", embed=embed_start, view=roll_view)

        await roll_view.wait()

        if not roll_view.clicked:
            embed_start.description = "⏰ **Tiempo Agotado** - Rolling automático..."
            embed_start.color = 0xe74c3c
            await start_msg.edit(embed=embed_start, view=None)
            await asyncio.sleep(1)
        else:
            # ACTUALIZACIÓN: Mantenemos la Grid visible mientras gira
            embed_start.description = f"**Rolling...** 🎰\n\n**Probabilidades:**\n{odds_grid_str}"
            embed_start.color = 0xf1c40f
            await start_msg.edit(embed=embed_start, view=None)

        # STEP 2: DECISION LOOP
        while True:
            current_rerolls = state["rerolls"].get(player.id, 0)
            current_left = config.MAX_REROLLS - current_rerolls
            pts_left = config.MAX_POINTS - state["points"].get(player.id, 0)

            valid_tiers = logic.get_valid_tiers(player.id, pick_num)
            name, tier = logic.roll_pokemon(valid_tiers)

            if not name:
                await channel.send(f"⚠️ **CRITICAL:** No valid pokemon.")
                break

            if current_left <= 0:
                state["rosters"][player.id].append({'name': name, 'tier': tier})
                state["points"][player.id] += tier

                embed = discord.Embed(title=f"Pick #{pick_num} • {player.display_name}", color=0x95a5a6)
                embed.add_field(name="Auto-Accepted", value=f"**{name}** (Tier {tier})")
                embed.set_footer(text="0 Re-rolls left.")
                await channel.send(f"{player.mention}", embed=embed)
                break

            # --- ACTUALIZACIÓN: Timer en el Embed de Decisión ---
            expiry_decision = int(time.time()) + config.DECISION_TIMEOUT

            embed = discord.Embed(
                title=f"Pick #{pick_num} • {player.display_name}",
                description=f"⏳ **Decide en** <t:{expiry_decision}:R>\n(Ronda {state['round']})",
                # <--- AQUI ESTÁ EL TIMER
                color=0xF1C40F
            )
            embed.add_field(name="Rolled", value=f"**{name}**", inline=True)
            embed.add_field(name="Tier", value=f"{tier}", inline=True)
            embed.add_field(name="Budget", value=f"{pts_left} pts left", inline=False)
            embed.set_footer(text=f"Re-rolls left: {current_left}/{config.MAX_REROLLS}")

            view = views.DraftView(player)
            await channel.send(f"{player.mention}", embed=embed, view=view)

            await view.wait()

            # LÓGICA DE DECISIÓN CORREGIDA
            if view.value == "REROLL":
                state["rerolls"][player.id] += 1
                new_left = config.MAX_REROLLS - state["rerolls"][player.id]
                clicker = view.clicked_by.display_name if view.clicked_by else "Staff"

                await channel.send(f"🔄 **{clicker}** re-rolled! ({new_left} left). Rolling again...")
                state["burned"].append(name)
                await asyncio.sleep(1)
                continue

                # Si es KEEP, TIMEOUT o None (por si acaso), lo aceptamos
            else:
                state["rosters"][player.id].append({'name': name, 'tier': tier})
                state["points"][player.id] += tier

                # Determinar mensaje
                if view.value == "KEEP":
                    clicker = view.clicked_by.display_name if view.clicked_by else "Staff"
                    msg_txt = f"✅ **{clicker}** accepted"
                else:
                    msg_txt = "⏰ **Timeout:** Auto-accepted"

                await channel.send(f"{msg_txt} **{name}**.")
                break

    state["current_index"] += 1
    await asyncio.sleep(1)
    await next_turn(channel)


if __name__ == "__main__":
    if config.TOKEN:
        bot.run(config.TOKEN)
    else:
        print("❌ Error: TOKEN missing")