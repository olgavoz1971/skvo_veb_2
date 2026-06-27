#!/bin/bash
export $(grep -v '^#' .env | xargs)
celery -A skvo_veb.celery_app worker --loglevel=DEBUG
