import discord
from discord import app_commands
from discord.ext import tasks
import aiohttp
import datetime
from typing import Optional

# Bot configuration
TOKEN = os.getenv('DISCORD_TOKEN')
API_KEY = os.getenv('API_KEY')
API_BASE_URL = os.getenv('API_BASE_URL')
AFFILIATE_CODE = os.getenv('AFFILIATE_CODE')

class LeaderboardBot(discord.Client):
    def __init__(self):
        super().__init__(intents=discord.Intents.default())
        self.tree = app_commands.CommandTree(self)
        self.active_leaderboards = {}  # Store channel_id: (message, end_date, days)

    async def setup_hook(self):
        # Start the background task
        self.update_leaderboards.start()
        
        # Sync slash commands
        await self.tree.sync()

    async def fetch_affiliate_data(self, days: int = 7) -> Optional[list]:
        current_time = int(datetime.datetime.now().timestamp() * 1000)
        start_time = int((datetime.datetime.now() - datetime.timedelta(days=days)).timestamp() * 1000)
        
        async with aiohttp.ClientSession() as session:
            headers = {"Authorization": f"Bearer {API_KEY}"}
            params = {
                "code": AFFILIATE_CODE,
                "gt": start_time,
                "lt": current_time,
                "by": "createdAt",
                "sort": "desc",
                "take": 1000
            }
            
            try:
                async with session.get(f"{API_BASE_URL}/affiliate/external", 
                                     headers=headers, 
                                     params=params) as response:
                    if response.status == 200:
                        return await response.json()
                    return None
            except Exception as e:
                print(f"Error fetching data: {e}")
                return None

    def create_leaderboard_embed(self, data: list, days: int, end_date: datetime.datetime) -> discord.Embed:
        # Aggregate user data
        user_stats = {}
        for entry in data:
            username = entry.get('username', 'Unknown')
            if username not in user_stats:
                user_stats[username] = {'wager': 0, 'deposits': 0}
            user_stats[username]['wager'] += entry.get('wager', 0)
            user_stats[username]['deposits'] += entry.get('deposit', 0)
        
        # Sort users by wager
        top_users = sorted(user_stats.items(), 
                         key=lambda x: x[1]['wager'], 
                         reverse=True)[:10]
        
        # Calculate time remaining
        time_remaining = end_date - datetime.datetime.now()
        days_remaining = time_remaining.days
        hours_remaining = time_remaining.seconds // 3600
        
        embed = discord.Embed(
            title="🏆 Affiliate Leaderboard 🏆",
            description=f"Top Users - Last {days} days\nLeaderboard ends in: {days_remaining}d {hours_remaining}h",
            color=discord.Color.gold(),
            timestamp=datetime.datetime.now()
        )
        
        # Add total stats
        total_wager = sum(stats['wager'] for _, stats in user_stats.items())
        total_deposits = sum(stats['deposits'] for _, stats in user_stats.items())
        
        embed.add_field(
            name="📊 Total Stats",
            value=f"Total Wager: ${total_wager:,.2f}\nTotal Deposits: ${total_deposits:,.2f}",
            inline=False
        )
        
        # Add user rankings
        for i, (username, stats) in enumerate(top_users, 1):
            medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else "👑"
            embed.add_field(
                name=f"{medal} #{i} {username}",
                value=f"Wager: ${stats['wager']:,.2f}\nDeposits: ${stats['deposits']:,.2f}",
                inline=False
            )
        
        return embed

    @tasks.loop(minutes=5)
    async def update_leaderboards(self):
        current_time = datetime.datetime.now()
        channels_to_remove = []

        for channel_id, (message, end_date, days) in self.active_leaderboards.items():
            if current_time > end_date:
                channels_to_remove.append(channel_id)
                try:
                    await message.edit(content="🏁 Leaderboard event has ended! 🏁")
                except:
                    pass
                continue

            data = await self.fetch_affiliate_data(days)
            if data:
                try:
                    embed = self.create_leaderboard_embed(data, days, end_date)
                    await message.edit(embed=embed)
                except Exception as e:
                    print(f"Error updating leaderboard in channel {channel_id}: {e}")

        # Remove ended leaderboards
        for channel_id in channels_to_remove:
            del self.active_leaderboards[channel_id]

    @tasks.loop(minutes=1)
    async def cleanup_old_leaderboards(self):
        current_time = datetime.datetime.now()
        channels_to_remove = [
            channel_id for channel_id, (_, end_date, _) in self.active_leaderboards.items()
            if current_time > end_date
        ]
        for channel_id in channels_to_remove:
            del self.active_leaderboards[channel_id]

client = LeaderboardBot()

@client.tree.command(name="leaderboard", description="Start a leaderboard event for specified number of days")
async def leaderboard(interaction: discord.Interaction, days: int):
    if days <= 0 or days > 30:
        await interaction.response.send_message("Please specify a number of days between 1 and 30.", ephemeral=True)
        return

    # Check if there's already an active leaderboard in this channel
    if interaction.channel_id in client.active_leaderboards:
        await interaction.response.send_message("There's already an active leaderboard in this channel!", ephemeral=True)
        return

    await interaction.response.defer()

    data = await client.fetch_affiliate_data(days)
    if not data:
        await interaction.followup.send("Unable to fetch leaderboard data. Please try again later.")
        return

    end_date = datetime.datetime.now() + datetime.timedelta(days=days)
    embed = client.create_leaderboard_embed(data, days, end_date)
    
    message = await interaction.followup.send(embed=embed)
    client.active_leaderboards[interaction.channel_id] = (message, end_date, days)

if __name__ == "__main__":
    client.run(TOKEN)
