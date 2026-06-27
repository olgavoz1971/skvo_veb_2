from dotenv import load_dotenv
load_dotenv()
from skvo_veb import app


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=8051)
