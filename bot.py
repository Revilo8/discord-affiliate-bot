import os
import discord
from discord import app_commands
from discord.ext import tasks
import aiohttp
import datetime
from typing import Optional
from dotenv import load_dotenv
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('discord_bot')

# Load environment variables
load_dotenv()

# Bot configuration
TOKEN = os.getenv('DISCORD_TOKEN')
API_KEY = os.getenv('API_KEY')
API_BASE_URL = os.getenv('API_BASE_URL')
AFFILIATE_CODE = os.getenv('AFFILIATE_CODE')

# Check environment variables
if not all([TOKEN, API_KEY, API_BASE_URL, AFFILIATE_CODE]):
    logger.error("Missing environment variables!")
    if not TOKEN: logger.error("DISCORD_TOKEN is missing")
    if not API_KEY: logger.error("API_KEY is missing")
    if not API_BASE_URL: logger.error("API_BASE_URL is missing")
    if not AFFILIATE_CODE: logger.error("AFFILIATE_CODE is missing")
    raise ValueError("Missing required environment variables")

class LeaderboardBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        intents.presences = True
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        self.active_leaderboards = {}
        logger.info("Bot initialized")

    async def setup_hook(self):
        try:
            # Force sync commands to all guilds
            await self.tree.sync()
            self.update_leaderboards.start()
            logger.info("Slash commands synced and update task started")
        except Exception as e:
            logger.error(f"Setup hook error: {e}")
            raise

    async def fetch_affiliate_data(self, days: int = 7) -> Optional[list]:
        logger.info(f"Fetching affiliate data for {days} days")
        current_time = int(datetime.datetime.now().timestamp() * 1000)
        start_time = int((datetime.datetime.now() - datetime.timedelta(days=days)).timestamp() * 1000)
        
        async with aiohttp.ClientSession() as session:
            headers = {'x-apikey': API_KEY}
            params = {
                'code': AFFILIATE_CODE,
                'gt': str(start_time),
                'lt': str(current_time),
                'by': 'createdAt',
                'sort': 'desc',
                'take': '1000',
                'skip': '0'  # Changed to 0 as per example
            }
            
            try:
                url = f"{API_BASE_URL}/affiliate/external"
                logger.info(f"Making API request to: {url}")
                logger.info(f"With params: {params}")
                logger.info(f"Headers present: {bool(headers.get('x-apikey'))}")
                
                async with session.get(url, 
                                     headers=headers, 
                                     params=params) as response:
                    logger.info(f"API Response Status: {response.status}")
                    
                    if response.status == 200:
                        data = await response.json()
                        logger.info("Successfully fetched affiliate data")
                        return data
                    else:
                        response_text = await response.text()
                        logger.error(f"API request failed with status {response.status}")
                        logger.error(f"Response text: {response_text}")
                    return None
            except Exception as e:
                logger.error(f"Error fetching data: {str(e)}")
                return None

    def create_leaderboard_embed(self, data: list, days: int, end_date: datetime.datetime) -> discord.Embed:
        try:
            # Aggregate user data
            user_stats = {}
            for entry in data:
                username = entry.get('username', 'Unknown')
                if username not in user_stats:
                    user_stats[username] = {'wager': 0, 'deposits': 0}
                user_stats[username]['wager'] += float(entry.get('wager', 0))
                user_stats[username]['deposits'] += float(entry.get('deposit', 0))
            
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
        except Exception as e:
            logger.error(f"Error creating embed: {e}")
            raise

    @tasks.loop(minutes=5)
    async def update_leaderboards(self):
        logger.info("Starting leaderboard updates")
        current_time = datetime.datetime.now()
        channels_to_remove = []

        for channel_id, (message, end_date, days) in self.active_leaderboards.items():
            try:
                if current_time > end_date:
                    channels_to_remove.append(channel_id)
                    try:
                        await message.edit(content="🏁 Leaderboard event has ended! 🏁")
                        logger.info(f"Ended leaderboard in channel {channel_id}")
                    except Exception as e:
                        logger.error(f"Failed to edit end message: {e}")
                    continue

                data = await self.fetch_affiliate_data(days)
                if data:
                    embed = self.create_leaderboard_embed(data, days, end_date)
                    await message.edit(embed=embed)
                    logger.info(f"Updated leaderboard in channel {channel_id}")
            except Exception as e:
                logger.error(f"Error updating leaderboard in channel {channel_id}: {e}")

        # Remove ended leaderboards
        for channel_id in channels_to_remove:
            del self.active_leaderboards[channel_id]

    @update_leaderboards.before_loop
    async def before_update_leaderboards(self):
        await self.wait_until_ready()
        logger.info("Bot is ready to start updating leaderboards")

client = LeaderboardBot()

@client.tree.command(name="leaderboard", description="Start a leaderboard event for specified number of days")
async def leaderboard(interaction: discord.Interaction, days: int):
    logger.info(f"Leaderboard command received from {interaction.user} for {days} days")
    try:
        if days <= 0 or days > 30:
            await interaction.response.send_message("Please specify a number of days between 1 and 30.", ephemeral=True)
            return

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
        logger.info(f"Successfully started leaderboard in channel {interaction.channel_id}")
    
    except Exception as e:
        logger.error(f"Error processing leaderboard command: {e}")
        await interaction.followup.send("An error occurred while processing your request.", ephemeral=True)

@client.event
async def on_ready():
    logger.info(f'Bot is logged in as {client.user}')
    logger.info('-------------------')

if __name__ == "__main__":
    try:
        logger.info("Starting bot...")
        client.run(TOKEN)
    except Exception as e:
        logger.error(f"Fatal error: {e}")
