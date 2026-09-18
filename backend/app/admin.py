"""Local administrator bootstrap and independent audit checkpoints.

Run from backend: python -m app.admin create-admin --username NAME
Production keys and LEDGER_PATH must match the service environment.
"""
import argparse
import getpass
import json
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[2]/'.env')
from .auth import create_user
from .ledger import db

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['create-admin','verify','migrate','backup','checkpoint','verify-checkpoint','restore','restore-drill'])
    parser.add_argument('--username')
    parser.add_argument('--output',type=Path)
    parser.add_argument('--backup',type=Path)
    parser.add_argument('--checkpoint',type=Path)
    args=parser.parse_args()
    if args.command=='create-admin':
        import re
        if not args.username or not re.fullmatch(r'[A-Za-z0-9_.@-]{3,80}',args.username):parser.error('A valid --username is required')
        password=getpass.getpass('Administrator password (12+ characters): ')
        if password!=getpass.getpass('Confirm password: '):parser.error('Passwords differ')
        create_user(args.username,password,args.username,'admin',bootstrap=True)
        print('Administrator created. Sign in through the application.')
    elif args.command=='migrate': print(f'Baselined {db.migrate_legacy()} legacy inventories. Original-source authenticity is not retroactively asserted.')
    elif args.command=='verify':
        result=db.verify();print(json.dumps(result,indent=2))
        raise SystemExit(0 if result['valid'] else 1)
    else:
        from . import operations
        if args.command in {'backup','checkpoint','restore'} and not args.output:
            parser.error('--output is required (the path must not already exist)')
        if args.command in {'restore','restore-drill'} and not args.backup:
            parser.error('--backup is required')
        if args.command in {'restore','restore-drill','verify-checkpoint'} and not args.checkpoint:
            parser.error('--checkpoint is required; use an independently retained checkpoint')
        if args.command=='backup': result=operations.create_backup(args.output,args.checkpoint)
        elif args.command=='checkpoint': result=operations.create_checkpoint(args.output)
        elif args.command=='restore': result=operations.restore_backup(args.backup,args.output,args.checkpoint)
        elif args.command=='restore-drill': result=operations.restore_drill(args.backup,args.checkpoint)
        else:
            with operations.snapshot() as path:
                result=operations.verify_checkpoint(path,json.loads(args.checkpoint.read_text(encoding='utf-8')))
        print(json.dumps(result,indent=2))

if __name__=='__main__':main()
