"""CLI: Grant admin + Agency tier to an existing user account.
Usage: python scripts/make_admin.py your@email.com
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import database as db

def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/make_admin.py <email>")
        sys.exit(1)
    email = sys.argv[1].strip().lower()
    user = db.get_user_by_email(email)
    if not user:
        print(f"No account found for {email}")
        print("Create one at /auth/register first, then run this script.")
        sys.exit(1)
    db.update_user(user["id"], is_admin=1, subscription_tier="agency", subscription_status="active")
    print(f"Done. {email} (ID #{user['id']}) is now admin with Agency tier.")

if __name__ == "__main__":
    main()
