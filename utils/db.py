from dotenv import load_dotenv, set_key
import os

load_dotenv()
env_path = '.env'
async def setToken(token: str):
    set_key(env_path, 'TOKEN', token)

async def getToken():
    token = os.getenv('TOKEN')
    
    if token:
        return token
    else:
        return None