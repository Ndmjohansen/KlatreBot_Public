#!/usr/bin/env python3
"""
Discord History Migration Script

This script migrates Discord message history to the SQLite database.
It includes rate limiting, checkpointing, and error recovery.
"""

import asyncio
import discord
import argparse
import json
import os
import time
from datetime import datetime, timedelta
from MessageDatabase import MessageDatabase
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class DiscordMigrator:
    def __init__(self, discord_token: str, db_path: str = "klatrebot.db"):
        self.discord_token = discord_token
        self.db = MessageDatabase(db_path)
        self.checkpoint_file = "migration_checkpoint.json"
        self.rate_limit_delay = 0.02  # 50 requests per second
        self.batch_size = 100
        self.max_retries = 3
        
    async def initialize(self):
        """Initialize database and Discord client"""
        await self.db.initialize()
        
        intents = discord.Intents.default()
        intents.message_content = True
        intents.guilds = True
        
        self.client = discord.Client(intents=intents)
        
        @self.client.event
        async def on_ready():
            logger.info(f"Logged in as {self.client.user}")
            self.guild = self.client.guilds[0]  # Assume first guild
            logger.info(f"Connected to guild: {self.guild.name}")
    
    async def load_checkpoint(self):
        """Load migration checkpoint"""
        if os.path.exists(self.checkpoint_file):
            with open(self.checkpoint_file, 'r') as f:
                checkpoint = json.load(f)
                logger.info(f"Loaded checkpoint: {checkpoint}")
                return checkpoint
        return {
            'last_channel_id': None,
            'last_message_id': None,
            'total_messages': 0,
            'channels_processed': 0,
            'start_time': None
        }
    
    async def save_checkpoint(self, checkpoint):
        """Save migration checkpoint"""
        checkpoint['last_save'] = datetime.now().isoformat()
        with open(self.checkpoint_file, 'w') as f:
            json.dump(checkpoint, f, indent=2)
        logger.info(f"Checkpoint saved: {checkpoint['total_messages']} messages processed")
    
    async def migrate_channel(self, channel, checkpoint):
        """Migrate messages from a single channel"""
        logger.info(f"Migrating channel: {channel.name} ({channel.id})")
        
        # Determine starting point
        after_id = checkpoint.get('last_message_id') if checkpoint.get('last_channel_id') == channel.id else None
        
        messages_processed = 0
        batch_messages = []
        
        try:
            async for message in channel.history(limit=None, after=discord.Object(id=after_id) if after_id else None):
                # Skip bot messages
                if message.author.bot:
                    continue
                
                # Determine message type
                message_type = 'command' if message.content.startswith('!') else 'text'
                
                # Resolve mentions in content
                content = message.content
                for mention in message.mentions:
                    user = channel.guild.get_member(mention.id)
                    if user:
                        mention_str = f"<@{mention.id}>"
                        name = user.display_name or user.name
                        content = content.replace(mention_str, f"@{name}")
                
                # Add to batch
                batch_messages.append({
                    'discord_message_id': message.id,
                    'discord_channel_id': message.channel.id,
                    'discord_user_id': message.author.id,
                    'content': content,
                    'message_type': message_type,
                    'timestamp': message.created_at
                })
                
                messages_processed += 1
                
                # Process batch when full
                if len(batch_messages) >= self.batch_size:
                    success_count = await self.db.batch_log_messages(batch_messages)
                    logger.info(f"Processed batch: {success_count}/{len(batch_messages)} messages")
                    batch_messages = []
                    
                    # Rate limiting
                    await asyncio.sleep(self.rate_limit_delay)
                
                # Update checkpoint every 1000 messages
                if messages_processed % 1000 == 0:
                    checkpoint['last_channel_id'] = channel.id
                    checkpoint['last_message_id'] = message.id
                    checkpoint['total_messages'] += messages_processed
                    await self.save_checkpoint(checkpoint)
                    logger.info(f"Checkpoint: {checkpoint['total_messages']} total messages processed")
            
            # Process remaining messages
            if batch_messages:
                success_count = await self.db.batch_log_messages(batch_messages)
                logger.info(f"Final batch: {success_count}/{len(batch_messages)} messages")
            
            logger.info(f"Completed channel {channel.name}: {messages_processed} messages")
            return messages_processed
            
        except Exception as e:
            logger.error(f"Error migrating channel {channel.name}: {e}")
            return 0
    
    async def migrate_all_channels(self, channel_ids=None):
        """Migrate all channels or specific channels"""
        checkpoint = await self.load_checkpoint()
        
        if checkpoint['start_time'] is None:
            checkpoint['start_time'] = datetime.now().isoformat()
        
        # Get channels to migrate
        if channel_ids:
            channels = [self.guild.get_channel(int(cid)) for cid in channel_ids]
            channels = [c for c in channels if c is not None]
        else:
            channels = [ch for ch in self.guild.text_channels if ch.permissions_for(self.guild.me).read_message_history]
        
        logger.info(f"Found {len(channels)} channels to migrate")
        
        total_messages = 0
        for i, channel in enumerate(channels):
            if channel is None:
                continue
                
            logger.info(f"Processing channel {i+1}/{len(channels)}: {channel.name}")
            
            # Skip if we've already processed this channel completely
            if (checkpoint.get('last_channel_id') == channel.id and 
                checkpoint.get('last_message_id') is not None):
                logger.info(f"Skipping channel {channel.name} - already processed")
                continue
            
            messages_processed = await self.migrate_channel(channel, checkpoint)
            total_messages += messages_processed
            
            # Update checkpoint
            checkpoint['last_channel_id'] = channel.id
            checkpoint['last_message_id'] = None  # Reset for next channel
            checkpoint['channels_processed'] += 1
            
            # Save checkpoint after each channel
            await self.save_checkpoint(checkpoint)
            
            # Rate limiting between channels
            await asyncio.sleep(1)
        
        logger.info(f"Migration completed! Total messages processed: {total_messages}")
        
        # Clean up checkpoint file
        if os.path.exists(self.checkpoint_file):
            os.remove(self.checkpoint_file)
            logger.info("Checkpoint file cleaned up")
    
    async def run(self, channel_ids=None):
        """Run the migration"""
        try:
            await self.initialize()
            await self.client.start(self.discord_token)
        except KeyboardInterrupt:
            logger.info("Migration interrupted by user")
        except Exception as e:
            logger.error(f"Migration failed: {e}")
        finally:
            if hasattr(self, 'client'):
                await self.client.close()

async def main():
    parser = argparse.ArgumentParser(description="Migrate Discord history to SQLite")
    parser.add_argument("--discord-token", required=True, help="Discord bot token")
    parser.add_argument("--db-path", default="klatrebot.db", help="SQLite database path")
    parser.add_argument("--channels", nargs="+", help="Specific channel IDs to migrate")
    
    args = parser.parse_args()
    
    migrator = DiscordMigrator(args.discord_token, args.db_path)
    await migrator.run(args.channels)

if __name__ == "__main__":
    asyncio.run(main())
