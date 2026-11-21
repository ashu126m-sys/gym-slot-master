GYM SLOT MASTER
===============

Flask-based gym slot booking and basic membership management demo.

Features
--------
- Admin and member login
- Members are created by admin only
- Admin member directory with search and activate/deactivate
- First-login password change for newly created members
- 8 daily gym slots with booking and cancellation
- Monthly, Quarterly, Half-Yearly and Yearly membership plans
- Admin-controlled membership prices
- Membership assignment with Paid / Unpaid fee status
- Admin can mark Cash or UPI payments as Paid
- Booking requires an active account and a paid, unexpired membership
- Admin can change admin username/password
- Admin can set phone, WhatsApp and email contact shown on home page
- Admin can permanently delete a member and their bookings/subscriptions
- Inactive members are signed out when they next access a protected page
- Past-date slot bookings are cleaned up automatically on app requests

Run locally
-----------
1. Install Python 3.
2. Open a terminal in this folder.
3. Install dependencies: pip install -r requirements.txt
4. Run: python app.py
5. Open: http://127.0.0.1:5000

Default demo admin login
------------------------
Username: admin@gym.local
Password: GymAdmin@123

IMPORTANT: Change the default admin password in Admin > Settings before using
this project outside a local demo. Set SECRET_KEY, ADMIN_EMAIL and
ADMIN_PASSWORD environment variables before first launch for a fresh database.

Database
--------
The existing SQLite database is kept in instance/gym_slot_master.db. The app
adds new tables/columns when it starts and does not intentionally delete
existing member or booking records. Keep a backup before replacing your old app.

This is a college demo. It does not process online payments; admin manually
marks fees as Paid after receiving cash or UPI.
