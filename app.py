# app.py
import os
import datetime
from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import json
import time
import urllib.request
import urllib.parse
import urllib.error
import base64
import re

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "fallback-secret-change-me")

# === YOUR FIREBASE CONFIG (already filled) ===
FIREBASE_CONFIG = {
    "apiKey": "AIzaSyBXn_X7c-Pevqrnpwd-I43-DbRGVOeBiEg",
    "authDomain": "squash79-store.firebaseapp.com",
    "databaseURL": "https://squash79-store-default-rtdb.firebaseio.com",
    "projectId": "squash79-store",
    "storageBucket": "squash79-store.firebasestorage.app",
    "messagingSenderId": "963643117351",
    "appId": "1:963643117351:web:17be7e72b5fbf3c0646302"
}
API_KEY = FIREBASE_CONFIG["apiKey"]
DATABASE_URL = FIREBASE_CONFIG["databaseURL"]

# ---------- Helper Functions ----------
def _make_request(url, method="GET", data=None, headers=None):
    if headers is None:
        headers = {}
    if data is not None:
        data = json.dumps(data).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=UTF-8"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")
        try:
            return json.loads(body)
        except:
            return {"error": {"message": body}}

def sign_in(email, password):
    url = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={API_KEY}"
    return _make_request(url, "POST", {"email": email, "password": password, "returnSecureToken": True})

def sign_up(email, password):
    url = f"https://identitytoolkit.googleapis.com/v1/accounts:signUp?key={API_KEY}"
    return _make_request(url, "POST", {"email": email, "password": password, "returnSecureToken": True})

def update_email(id_token, new_email):
    url = f"https://identitytoolkit.googleapis.com/v1/accounts:update?key={API_KEY}"
    return _make_request(url, "POST", {"idToken": id_token, "email": new_email, "returnSecureToken": True})

def send_verification_email(id_token):
    url = f"https://identitytoolkit.googleapis.com/v1/accounts:sendOobCode?key={API_KEY}"
    return _make_request(url, "POST", {"requestType": "VERIFY_EMAIL", "idToken": id_token})

def get_account_info(id_token):
    url = f"https://identitytoolkit.googleapis.com/v1/accounts:lookup?key={API_KEY}"
    return _make_request(url, "POST", {"idToken": id_token})

def db_put(path, data, token):
    return _make_request(f"{DATABASE_URL}{path}.json?auth={token}", "PUT", data)

def db_patch(path, data, token):
    return _make_request(f"{DATABASE_URL}{path}.json?auth={token}", "PATCH", data)

def db_post(path, data, token):
    return _make_request(f"{DATABASE_URL}{path}.json?auth={token}", "POST", data)

def db_get(path, token):
    return _make_request(f"{DATABASE_URL}{path}.json?auth={token}", "GET")

def db_delete(path, token):
    return _make_request(f"{DATABASE_URL}{path}.json?auth={token}", "DELETE")

def get_uid_from_token(id_token):
    try:
        payload = id_token.split('.')[1]
        payload += '=' * (-len(payload) % 4)
        decoded = base64.urlsafe_b64decode(payload).decode('utf-8')
        return json.loads(decoded).get('user_id')
    except:
        return None

def get_chat_id(uid1, uid2):
    return "_".join(sorted([uid1, uid2]))

def add_notification(to_uid, from_uid, notif_type, token, extra=None):
    notif = {
        "type": notif_type,
        "from_uid": from_uid,
        "timestamp": int(time.time() * 1000),
        "seen": False
    }
    if extra:
        notif.update(extra)
    sender = db_get(f"/users/{from_uid}", token)
    if isinstance(sender, dict):
        notif["sender_name"] = sender.get("username", from_uid)
    else:
        notif["sender_name"] = from_uid
    db_post(f"/notifications/{to_uid}", notif, token)

def is_online(user_data):
    if not isinstance(user_data, dict):
        return False
    last = user_data.get("last_online", 0)
    now = int(time.time() * 1000)
    return (now - last) < 45000

def format_last_seen(timestamp_ms):
    if not timestamp_ms:
        return "a while ago"
    try:
        dt = datetime.datetime.fromtimestamp(timestamp_ms / 1000)
        now = datetime.datetime.now()
        diff = now - dt
        if diff.total_seconds() < 60:
            return "just now"
        elif diff.total_seconds() < 3600:
            minutes = int(diff.total_seconds() // 60)
            return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
        elif diff.total_seconds() < 86400:
            hours = int(diff.total_seconds() // 3600)
            return f"{hours} hour{'s' if hours != 1 else ''} ago"
        else:
            days = diff.days
            return f"{days} day{'s' if days != 1 else ''} ago"
    except:
        return "a while ago"

# ==================== ROUTES ====================

# ... (all other routes remain identical from last full version) ...
# I'll omit the rest for brevity, but you MUST keep them. Only the /admin/users route changed.

# ---------- Admin (overwrite just this one) ----------
@app.route("/admin/users")
def admin_users():
    if not session.get("isAdmin"):
        return "Access denied.", 403
    all_users = db_get("/users", session["id_token"])
    users_list = []
    if isinstance(all_users, dict):
        for uid, data in all_users.items():
            if not isinstance(data, dict):
                # Skip any non-dict junk
                continue
            data["uid"] = uid
            data["online"] = is_online(data)
            data["last_seen"] = format_last_seen(data.get("last_online", 0)) if not data["online"] else ""
            users_list.append(data)
    # Sort: online first, then by username
    users_list.sort(key=lambda x: (not x.get("online", False), x.get("username", "").lower()))
    return render_template("admin_users.html", users=users_list)

# ... (rest of the routes, keep exactly as before) ...

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)
