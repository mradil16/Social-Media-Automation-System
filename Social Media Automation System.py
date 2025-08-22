#!/usr/bin/env python3

"""

Streamlined Social Media Automation System

Efficient, secure toolkit for social media automation with async support

"""

import os

import json

import asyncio

import logging

from datetime import datetime, timedelta

from dataclasses import dataclass

from typing import List, Dict, Optional, Any

from pathlib import Path

import aiosqlite

import tweepy

import aiohttp

from contextlib import asynccontextmanager

# Logging setup

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

logger = logging.getLogger(__name__)

@dataclass

class Post:

    content: str

    platform: str

    scheduled_time: Optional[datetime] = None

    media_paths: Optional[List[str]] = None

    status: str = "pending"

class ConfigManager:

    """Environment-based configuration"""

    

    @staticmethod

    def get_twitter_config() -> Dict[str, str]:

        config = {

            'api_key': os.getenv('TWITTER_API_KEY'),

            'api_secret': os.getenv('TWITTER_API_SECRET'),

            'access_token': os.getenv('TWITTER_ACCESS_TOKEN'),

            'access_token_secret': os.getenv('TWITTER_ACCESS_TOKEN_SECRET'),

            'bearer_token': os.getenv('TWITTER_BEARER_TOKEN')

        }

        

        if not all(config.values()):

            raise ValueError("Missing Twitter API credentials")

        return config

class Database:

    """Async SQLite manager using aiosqlite"""

    

    def __init__(self, db_path: str = "automation.db"):

        self.db_path = db_path

    

    async def init_db(self):

        """Initialize database asynchronously"""

        async with aiosqlite.connect(self.db_path) as conn:

            await conn.executescript('''

                CREATE TABLE IF NOT EXISTS posts (

                    id INTEGER PRIMARY KEY,

                    content TEXT NOT NULL,

                    platform TEXT NOT NULL,

                    scheduled_time TIMESTAMP,

                    media_paths TEXT,

                    status TEXT DEFAULT 'pending',

                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP

                );

                

                CREATE INDEX IF NOT EXISTS idx_posts_schedule 

                ON posts(scheduled_time, status);

            ''')

            await conn.commit()

    

    async def save_post(self, post: Post) -> int:

        async with aiosqlite.connect(self.db_path) as conn:

            cursor = await conn.execute(

                'INSERT INTO posts (content, platform, scheduled_time, media_paths, status) VALUES (?, ?, ?, ?, ?)',

                (post.content[:280], post.platform, post.scheduled_time, 

                 json.dumps(post.media_paths) if post.media_paths else None, post.status)

            )

            await conn.commit()

            return cursor.lastrowid

    

    async def get_pending_posts(self) -> List[Dict]:

        async with aiosqlite.connect(self.db_path) as conn:

            conn.row_factory = aiosqlite.Row

            cursor = await conn.execute('''

                SELECT * FROM posts 

                WHERE status = 'pending' AND scheduled_time <= datetime('now')

                ORDER BY scheduled_time LIMIT 20

            ''')

            rows = await cursor.fetchall()

            return [dict(row) for row in rows]

    

    async def update_status(self, post_id: int, status: str):

        async with aiosqlite.connect(self.db_path) as conn:

            await conn.execute('UPDATE posts SET status = ? WHERE id = ?', (status, post_id))

            await conn.commit()

class TwitterBot:

    """Async Twitter bot with enhanced error handling"""

    

    def __init__(self, config: Dict[str, str]):

        self.config = config

        self._setup_clients()

    

    def _setup_clients(self):

        try:

            self.client = tweepy.Client(

                bearer_token=self.config['bearer_token'],

                consumer_key=self.config['api_key'],

                consumer_secret=self.config['api_secret'],

                access_token=self.config['access_token'],

                access_token_secret=self.config['access_token_secret'],

                wait_on_rate_limit=True

            )

            

            # Test authentication in thread to avoid blocking event loop

            logger.info("Twitter client initialized")

            

        except Exception as e:

            logger.error(f"Twitter auth failed: {e}")

            raise

    

    async def post_tweet(self, content: str, media_paths: List[str] = None, retries: int = 2) -> Optional[str]:

        """Post tweet with async retry logic using thread executor"""

        for attempt in range(retries + 1):

            try:

                # Run blocking tweepy call in thread to avoid blocking event loop

                response = await asyncio.to_thread(

                    self.client.create_tweet,

                    text=content[:280]

                )

                tweet_id = response.data['id']

                logger.info(f"Tweet posted: {tweet_id}")

                return tweet_id

                

            except tweepy.TooManyRequests:

                if attempt < retries:

                    wait_time = 60 * (2 ** attempt)

                    logger.warning(f"Rate limited, waiting {wait_time}s")

                    await asyncio.sleep(wait_time)

                else:

                    raise

            except tweepy.Forbidden:

                logger.error("Tweet forbidden (duplicate or policy violation)")

                return None

            except Exception as e:

                if attempt < retries:

                    await asyncio.sleep(30)

                else:

                    logger.error(f"Tweet failed after {retries + 1} attempts: {e}")

                    raise

        return None

class ContentOptimizer:

    """Content optimization utilities"""

    

    @staticmethod

    def optimize_for_twitter(content: str) -> str:

        """Optimize content for Twitter"""

        # Add basic hashtag suggestions

        hashtag_keywords = {

            'ai': '#AI', 'python': '#Python', 'tech': '#Tech',

            'automation': '#Automation', 'productivity': '#Productivity'

        }

        

        content_lower = content.lower()

        hashtags = []

        

        for keyword, tag in hashtag_keywords.items():

            if keyword in content_lower and len(hashtags) < 2:

                hashtags.append(tag)

        

        if hashtags:

            hashtag_str = ' ' + ' '.join(hashtags)

            if len(content) + len(hashtag_str) <= 280:

                content += hashtag_str

        

        return content[:280]

class AutomationEngine:

    """Main automation engine with proper async task processing"""

    

    def __init__(self):

        self.db = Database()

        self.optimizer = ContentOptimizer()

        self.twitter = None

    

    async def initialize(self):

        """Initialize async components"""

        await self.db.init_db()

        

        try:

            twitter_config = ConfigManager.get_twitter_config()

            self.twitter = TwitterBot(twitter_config)

            

            # Test authentication in thread

            await asyncio.to_thread(self.twitter.client.get_me)

            logger.info("Twitter authentication successful")

            

        except ValueError as e:

            logger.warning(f"Twitter not configured: {e}")

        except Exception as e:

            logger.error(f"Twitter initialization failed: {e}")

    

    async def schedule_post(self, content: str, platform: str, 

                          scheduled_time: datetime, media_paths: List[str] = None) -> int:

        """Schedule a post for later publication"""

        if platform == 'twitter':

            content = self.optimizer.optimize_for_twitter(content)

        

        post = Post(

            content=content,

            platform=platform,

            scheduled_time=scheduled_time,

            media_paths=media_paths

        )

        

        post_id = await self.db.save_post(post)

        logger.info(f"Post {post_id} scheduled for {platform} at {scheduled_time}")

        return post_id

    

    async def publish_now(self, content: str, platforms: List[str], 

                         media_paths: List[str] = None) -> Dict[str, Optional[str]]:

        """Publish content immediately"""

        results = {}

        

        for platform in platforms:

            if platform == 'twitter' and self.twitter:

                try:

                    optimized_content = self.optimizer.optimize_for_twitter(content)

                    tweet_id = await self.twitter.post_tweet(optimized_content, media_paths)

                    results[platform] = tweet_id

                except Exception as e:

                    logger.error(f"Failed to post to Twitter: {e}")

                    results[platform] = None

            else:

                logger.warning(f"Platform {platform} not available")

                results[platform] = None

        

        return results

    

    async def process_scheduled_posts(self):

        """Process pending scheduled posts"""

        pending_posts = await self.db.get_pending_posts()

        

        tasks = []

        for post_data in pending_posts:

            task = self._process_single_post(post_data)

            tasks.append(task)

        

        if tasks:

            await asyncio.gather(*tasks, return_exceptions=True)

    

    async def _process_single_post(self, post_data: Dict):

        """Process a single scheduled post"""

        try:

            media_paths = json.loads(post_data['media_paths']) if post_data['media_paths'] else None

            

            results = await self.publish_now(

                post_data['content'],

                [post_data['platform']],

                media_paths

            )

            

            status = 'posted' if results.get(post_data['platform']) else 'failed'

            await self.db.update_status(post_data['id'], status)

            

        except Exception as e:

            logger.error(f"Failed to process post {post_data['id']}: {e}")

            await self.db.update_status(post_data['id'], 'failed')

    

    async def run_scheduler(self, interval_minutes: int = 5):

        """Run the scheduler continuously"""

        logger.info(f"Scheduler started - checking every {interval_minutes} minutes")

        

        while True:

            try:

                await self.process_scheduled_posts()

                await asyncio.sleep(interval_minutes * 60)

            except KeyboardInterrupt:

                logger.info("Scheduler stopped")

                break

            except Exception as e:

                logger.error(f"Scheduler error: {e}")

                await asyncio.sleep(60)  # Wait 1 minute on error

async def main():

    """Main async function"""

    # Check environment variables

    required_vars = ['TWITTER_API_KEY', 'TWITTER_API_SECRET', 

                    'TWITTER_ACCESS_TOKEN', 'TWITTER_ACCESS_TOKEN_SECRET']

    

    missing_vars = [var for var in required_vars if not os.getenv(var)]

    if missing_vars:

        print(f"Missing environment variables: {', '.join(missing_vars)}")

        print("Please install aiosqlite: pip install aiosqlite")

        return

    

    try:

        engine = AutomationEngine()

        await engine.initialize()  # Proper async initialization

        

        print("Streamlined Social Media Automation (Truly Async)")

        print("=" * 50)

        

        # Example: Post immediately

        content = "🚀 Testing truly async automation - no blocked event loops!"

        results = await engine.publish_now(content, ['twitter'])

        print(f"Immediate post results: {results}")

        

        # Example: Schedule posts

        base_time = datetime.now() + timedelta(minutes=5)

        for i, content in enumerate([

            "💡 Proper async/await with aiosqlite and asyncio.to_thread!",

            "📊 Event loop stays responsive during all I/O operations"

        ]):

            scheduled_time = base_time + timedelta(minutes=i * 10)

            post_id = await engine.schedule_post(content, 'twitter', scheduled_time)

            print(f"Scheduled post {post_id} for {scheduled_time}")

        

        # Uncomment to run continuous scheduler

        # await engine.run_scheduler()

        

    except Exception as e:

        logger.error(f"Application error: {e}")

if __name__ == "__main__":

    asyncio.run(main())