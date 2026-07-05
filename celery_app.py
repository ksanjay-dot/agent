import os
import logging
from celery import Celery
from celery.schedules import crontab
from dotenv import load_dotenv
from pathlib import Path

env_path = Path(__file__).resolve().parent / '.env'
load_dotenv(env_path)

logger = logging.getLogger(__name__)

REDIS_URL = os.getenv('REDIS_URL')
if not REDIS_URL:
    logger.warning("REDIS_URL not set — Celery will fail at runtime")

celery_app = Celery(
    'vi_backend',
    broker=REDIS_URL,
    backend=REDIS_URL,
)

celery_app.conf.update(
    timezone='Asia/Kolkata',
    enable_utc=True,
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_soft_time_limit=300,
    task_time_limit=330,
    result_expires=3600,
    worker_prefetch_multiplier=1,
)

celery_app.conf.beat_schedule = {
    'enqueue-daily-sequences': {
        'task': 'tasks.message_tasks.enqueue_daily_sequences',
        'schedule': crontab(hour=6, minute=0),
    },
    'process-pipeline-batch': {
        'task': 'tasks.message_tasks.process_pipeline_batch',
        'schedule': crontab(minute='*/2'),
    },
    'retry-failed-pipeline': {
        'task': 'tasks.message_tasks.retry_failed_pipeline',
        'schedule': crontab(minute='*/15'),
    },
    'smart-timing': {
        'task': 'tasks.message_tasks.process_smart_timing',
        'schedule': crontab(hour='*/4', minute=0),
    },
    'process-scheduled-campaigns': {
        'task': 'tasks.campaign_tasks.process_scheduled_campaigns',
        'schedule': crontab(minute='*/1'),
    },
}

import tasks.message_tasks
import tasks.campaign_tasks
