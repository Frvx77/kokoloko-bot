import discord
import config
import logic


# --- HELPER: GENERADOR DE CUADRÍCULA ---
def format_odds_grid(odds_data):
    """Devuelve solo el string de la cuadrícula formateada"""
    if not odds_data:
        return "⚠️ Sin Tiers Válidas"

    items = []
    for tier, pct in odds_data.items():
        if tier >= 240:
            icon = "🔥"
        elif tier <= 40:
            icon = "⚪"
        else:
            icon = "🔹"
        items.append(f"{icon} **T{tier}:** `{pct:.1f}%`")

    grid_rows = []
    for i in range(0, len(items), 2):
        left = items[i]
        right = items[i + 1] if (i + 1) < len(items) else ""
        grid_rows.append(f"{left} \u2003 {right}")

    return "\n".join(grid_rows)


# --- CREACIÓN DE EMBEDS ---

def create_roll_embed(player, pick_num, expiry_time, odds_grid_str):
    """Genera el Embed PRE-ROLL"""
    embed = discord.Embed(
        title=f"🎲 Pick #{pick_num} • {player.display_name}",
        description=f"¡Toca el botón para girar!\n⏳ **Auto-roll** <t:{expiry_time}:R>\n\n**Probabilidades:**\n{odds_grid_str}",
        color=0x2ecc71
    )
    return embed


def create_summary_embed(draft_state):
    """Genera la Tabla de Resultados (Scorecard)"""
    if not draft_state["rosters"]:
        return discord.Embed(title="📊 No Data", description="Draft hasn't started.")

    embed = discord.Embed(title="📊 Draft Summary / Resultados", color=0x3498db)

    unique_ids = []
    unique_players = []
    for p in draft_state['order']:
        if p.id not in unique_ids:
            unique_ids.append(p.id)
            unique_players.append(p)

    for player in unique_players:
        roster = draft_state["rosters"].get(player.id, [])
        points_spent = draft_state["points"].get(player.id, 0)
        points_left = config.MAX_POINTS - points_spent
        rerolls_used = draft_state["rerolls"].get(player.id, 0)
        rerolls_left = config.MAX_REROLLS - rerolls_used

        if roster:
            pokemon_list = "\n".join([f"• **{p['name']}** ({p['tier']})" for p in roster])
        else:
            pokemon_list = "*(No picks yet)*"

        field_value = (
            f"{pokemon_list}\n"
            f"-------------------\n"
            f"💰 **Points:** {points_spent}/{config.MAX_POINTS} (Left: {points_left})\n"
            f"🎲 **Re-rolls:** {rerolls_left} left"
        )
        embed.add_field(name=f"👤 {player.display_name}", value=field_value, inline=True)

    return embed


# --- VISTAS / BOTONES ---

class RollView(discord.ui.View):
    def __init__(self, coach_user):
        super().__init__(timeout=config.ROLL_TIMEOUT)
        self.coach = coach_user
        self.clicked = False

    async def disable_all(self, interaction):
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(view=self)

    @discord.ui.button(label="🎲 ROLL DICE", style=discord.ButtonStyle.primary, emoji="🎲")
    async def roll_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        is_coach = interaction.user.id == self.coach.id
        is_staff = discord.utils.get(interaction.user.roles, name=config.STAFF_ROLE_NAME) is not None

        if not (is_coach or is_staff):
            await interaction.response.send_message("🚫 No es tu turno ni eres Staff.", ephemeral=True)
            return

        self.clicked = True
        await self.disable_all(interaction)
        self.stop()


class DraftView(discord.ui.View):
    def __init__(self, coach_user):
        super().__init__(timeout=config.DECISION_TIMEOUT)
        self.coach = coach_user
        self.value = None
        self.clicked_by = None

        # --- FIX CRÍTICO: MANEJO DEL TIMEOUT ---

    async def on_timeout(self):
        # Si se acaba el tiempo, forzamos el valor a "TIMEOUT" y paramos
        self.value = "TIMEOUT"
        self.stop()

    async def check_permissions(self, interaction):
        is_coach = interaction.user.id == self.coach.id
        is_staff = discord.utils.get(interaction.user.roles, name=config.STAFF_ROLE_NAME) is not None

        if not (is_coach or is_staff):
            await interaction.response.send_message("🚫 No eres el Coach ni Staff.", ephemeral=True)
            return False
        return True

    async def disable_all(self, interaction):
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(view=self)

    @discord.ui.button(label="✅ Aceptar (Keep)", style=discord.ButtonStyle.success)
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