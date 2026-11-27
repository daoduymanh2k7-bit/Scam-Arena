"""Read-only production diagnostic. Does not print passwords, keys or conversation text."""
import argparse
import json
import os
import psycopg
from psycopg.rows import dict_row

parser=argparse.ArgumentParser()
parser.add_argument('--username',default='')
args=parser.parse_args()
with psycopg.connect(os.environ['DATABASE_URL'],row_factory=dict_row) as c:
    c.execute('SET TRANSACTION READ ONLY')
    totals=c.execute("SELECT count(*) AS accounts,max(created_at) AS newest_account_at FROM app_users").fetchone()
    print(json.dumps(totals,default=str))
    if args.username:
        account=c.execute("""SELECT u.username,u.created_at,u.last_login_at,u.is_locked,
            (SELECT count(*) FROM call_sessions s WHERE s.user_id=u.user_id) AS sessions
            FROM app_users u WHERE u.username=%s""",(args.username.strip().lower(),)).fetchone()
        print(json.dumps({'account_found':bool(account),'account':account},default=str))
