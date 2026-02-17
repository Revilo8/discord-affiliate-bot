import discord
from discord.ext import commands, tasks
import requests
import asyncio
from datetime import datetime, timedelta
import json
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configuration
TOKEN = os.getenv('DISCORD_TOKEN')
API_KEY = os.getenv('API_KEY')
API_BASE_URL = "https://api.csgodiamonds.com/affiliate/leaderboard/referrals"

# Bot setup
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# Store active leaderboards
active_leaderboards = {}

def fetch_leaderboard_data(start_date, end_date):
    """Fetch data from the API"""
    payload = {
        "key": API_KEY,
        "type": "WAGER",
        "after": int(start_date.timestamp() * 1000),
        "before": int(end_date.timestamp() * 1000)
    }
    
    try:
        response = requests.post(API_BASE_URL, json=payload)
        if response.status_code == 200:
            return response.json()
        else:
            print(f"API Error: {response.status_code}")
            return None
    except Exception as e:
        print(f"Error fetching data: {e}")
        return None

def create_leaderboard_embed(data, days_remaining):
    """Create Discord embed with leaderboard data"""
    embed = discord.Embed(
        title="🏆 CSGODiamonds Wager Leaderboard 🏆",
        description=f"Days remaining: {days_remaining}",
        color=discord.Color.gold(),
        timestamp=datetime.now()
    )
    
    if not data or not data.get('success'):
        embed.add_field(name="No Data", value="Unable to fetch leaderboard data", inline=False)
        return embed
    
    # Get users from the API response
    users = data.get('data', [])
    
    if not users:
        embed.add_field(name="No Entries", value="No data available for this period", inline=False)
        return embed
    
    # Filter out entries without username (to avoid duplicates/broken entries)
    valid_users = sorted(
        [user for user in users if user.get('username')],
        key=lambda x: float(x.get('totalAmount', 0)),
        reverse=True
    )[:10]
    
    for i, user in enumerate(valid_users, 1):
        medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else "👑"
        username = user.get('username', 'Unknown')
        amount = float(user.get('totalAmount', 0))
        
        embed.add_field(
            name=f"{medal} #{i} {username}",
            value=f"Total Wager: ${amount:,.2f}",
            inline=False
        )
    
    embed.set_footer(text=f"Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    return embed

@bot.event
async def on_ready():
    print(f'{bot.user} is online!')
    try:
        # Force sync commands
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s)")
    except Exception as e:
        print(f"Failed to sync commands: {e}")
    update_leaderboards.start()

@bot.hybrid_command(name="leaderboard", description="Start a leaderboard for specified days")
async def leaderboard(ctx, days: int):
    """Start a leaderboard command"""
    if days <= 0 or days > 30:
        await ctx.send("Please specify days between 1 and 30.")
        return
    
    if ctx.channel.id in active_leaderboards:
        await ctx.send("There's already an active leaderboard in this channel!")
        return
    
    # Calculate dates
    start_date = datetime.now()
    end_date = start_date + timedelta(days=days)
    
    # Fetch initial data
    data = fetch_leaderboard_data(start_date, end_date)
    embed = create_leaderboard_embed(data, days)
    
    # Send embed
    message = await ctx.send(embed=embed)
    
    # Store leaderboard info
    active_leaderboards[ctx.channel.id] = {
        'message': message,
        'start_date': start_date,
        'end_date': end_date,
        'days': days
    }
    
    await ctx.send(f"Leaderboard started for {days} days! Updates every hour.", ephemeral=True)

@bot.hybrid_command(name="stop", description="Stop the leaderboard in this channel")
async def stop_leaderboard(ctx):
    """Stop leaderboard command"""
    if ctx.channel.id in active_leaderboards:
        del active_leaderboards[ctx.channel.id]
        await ctx.send("Leaderboard stopped!")
    else:
        await ctx.send("No active leaderboard in this channel.")

@tasks.loop(hours=1)
async def update_leaderboards():
    """Update all active leaderboards every hour"""
    current_time = datetime.now()
    channels_to_remove = []
    
    for channel_id, leaderboard_info in active_leaderboards.items():
        # Check if leaderboard has ended
        if current_time > leaderboard_info['end_date']:
            channels_to_remove.append(channel_id)
            try:
                await leaderboard_info['message'].edit(content="🏁 Leaderboard has ended!")
            except:
                pass
            continue
        
        # Update leaderboard
        try:
            days_remaining = (leaderboard_info['end_date'] - current_time).days
            data = fetch_leaderboard_data(leaderboard_info['start_date'], leaderboard_info['end_date'])
            embed = create_leaderboard_embed(data, days_remaining)
            await leaderboard_info['message'].edit(embed=embed)
        except Exception as e:
            print(f"Error updating leaderboard in channel {channel_id}: {e}")
    
    # Remove ended leaderboards
    for channel_id in channels_to_remove:
        if channel_id in active_leaderboards:
            del active_leaderboards[channel_id]

@update_leaderboards.before_loop
async def before_update_leaderboards():
    await bot.wait_until_ready()

if __name__ == "__main__":
    if not TOKEN:
        print("Please set DISCORD_TOKEN in your .env file")
    else:
        bot.run(TOKEN)