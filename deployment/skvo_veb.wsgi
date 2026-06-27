import sys
import os
import logging

logging.basicConfig(stream=sys.stderr)

activate_this = '/var/www/flask/skvo_veb/venv/bin/activate_this.py'

with open(activate_this) as file_:
    exec(file_.read(), dict(__file__=activate_this))

from dotenv import load_dotenv

sys.path.insert(0,"/var/www/flask/")
load_dotenv('/var/www/flask/.env')

from skvo_veb import server as application
application.secret_key = os.getenv('SECRET_KEY')
