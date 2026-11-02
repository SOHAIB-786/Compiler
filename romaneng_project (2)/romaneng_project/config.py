"""
Settings - the only file you need to edit.
(Alternatively set the environment variables RC_DB_SERVER, RC_DB_USER, ...)
"""
import os

# ---- SQL Server 2022 connection ----
# Use the same "Server name" you see when connecting in SSMS. Examples:
#   "localhost"            (default instance)
#   r".\SQLEXPRESS"        (Express instance)
#   "DESKTOP-ABC123"       (computer name)
DB_SERVER = os.environ.get("RC_DB_SERVER", r"localhost\SQLEXPRESS")
DB_NAME = os.environ.get("RC_DB_NAME", "RomanEngDB")   # created automatically

# Windows Authentication: leave DB_USER empty.
# SQL login (e.g. 'sa'): fill in both DB_USER and DB_PASSWORD.
DB_USER = os.environ.get("RC_DB_USER", "")
DB_PASSWORD = os.environ.get("RC_DB_PASSWORD", "")

# ---- Default user, created automatically on first run ----
DEFAULT_USERNAME = "sohaib"
DEFAULT_PASSWORD = "sohaib123"

# ---- Flask / security ----
SECRET_KEY = os.environ.get("RC_SECRET", "")   # empty = random key on every start
MAX_LOGIN_TRIES = 5      # failed attempts allowed
LOCK_SECONDS = 60        # lock time after too many failures
