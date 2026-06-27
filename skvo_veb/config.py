import os
from dash import DiskcacheManager, CeleryManager
import diskcache
from celery import Celery

class Config:
    USE_REDIS = os.getenv('USE_REDIS', 'false').upper() == 'TRUE' or os.getenv('USE_REDIS', 'false') == '1'
    DEBUG_APP = os.getenv('DEBUG_APP', 'false').upper() == 'TRUE' or os.getenv('DEBUG_APP', 'false') == '1'
    APP_LOG = os.getenv('APP_LOG')
    DISKCACHE_DIR = os.getenv('DISKCACHE_DIR')
    REDIS_BROKER = os.getenv('REDIS_BROKER')
    REDIS_BACKEND = os.getenv('REDIS_BACKEND')

    @staticmethod
    def get_background_callback_manager(server_name):
        if Config.USE_REDIS:
            celery_app = Celery(server_name,
                                broker=Config.REDIS_BROKER,
                                backend=Config.REDIS_BACKEND,
                                broker_connection_retry_on_startup=True)
            return CeleryManager(celery_app)
        else:
            return DiskcacheManager(diskcache.Cache(Config.DISKCACHE_DIR))
