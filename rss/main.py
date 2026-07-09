import dotenv
import os

dotenv.load_dotenv(dotenv_path='../.env')

postgres_host = os.getenv('POSTGRES_HOST', 'localhost')
postgres_port = os.getenv('POSTGRES_PORT', '5432')
postgres_user = os.getenv('POSTGRES_USER', 'saver')
postgres_password = os.getenv('POSTGRES_PASSWORD', 'saver')
postgres_db = os.getenv('POSTGRES_DB', 'saverdb')