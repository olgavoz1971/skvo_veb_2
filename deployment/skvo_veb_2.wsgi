import sys
import os
import logging

# logging.basicConfig(stream=sys.stderr)
# logging.basicConfig(filename="/var/www/flask/skvo_veb_2/log/app.log", level=logging.INFO)

# activate_this = '/var/www/flask/skvo_veb/venv/bin/activate_this.py'

# with open(activate_this) as file_:
#     exec(file_.read(), dict(__file__=activate_this))

from dotenv import load_dotenv

sys.path.insert(0,"/var/www/flask/skvo_veb_2")
load_dotenv('/var/www/flask/.env')

logging.basicConfig(filename=os.getenv('APP_LOG'), level=logging.INFO)


from skvo_veb import server as application
application.secret_key = os.getenv('SECRET_KEY')
