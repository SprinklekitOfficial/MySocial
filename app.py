# app.py
import os
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
    """Return True if last_online is within the last 45 seconds."""
    if not isinstance(user_data, dict):
        return False
    last = user_data.get("last_online", 0)
    now = int(time.time() * 1000)
    return (now - last) < 45000

# ==================== ROUTES ====================

@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]
        result = sign_in(email, password)
        if "idToken" in result:
            id_token = result["idToken"]
            info = get_account_info(id_token)
            email_verified = False
            if "users" in info and info["users"]:
                email_verified = info["users"][0].get("emailVerified", False)
            session["user"] = email
            session["id_token"] = id_token
            uid = get_uid_from_token(id_token)
            session["uid"] = uid
            profile = db_get(f"/users/{uid}", id_token)
            if isinstance(profile, dict):
                session["username"] = profile.get("username", email)
                session["isAdmin"] = profile.get("isAdmin", False)
                session["verified"] = profile.get("verified", False)
                session["dark_mode"] = profile.get("dark_mode", False)
                if profile.get("banned", False):
                    session.clear()
                    return "Your account has been banned."
            else:
                session["username"] = email
                session["isAdmin"] = False
                session["verified"] = False
                session["dark_mode"] = False
            session["email_verified"] = email_verified
            # Update last_online immediately
            db_patch(f"/users/{uid}", {"last_online": int(time.time() * 1000)}, id_token)
            return redirect(url_for("feed"))
        else:
            error = result.get("error", {}).get("message", "Login failed")
            return f"Login failed: {error}"
    return render_template("login.html")

@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]
        username = request.form.get("username", "").strip()
        if len(password) < 8:
            return "Password must be at least 8 characters."
        if not re.search(r"[A-Z]", password):
            return "Password must contain an uppercase letter."
        if not re.search(r"[a-z]", password):
            return "Password must contain a lowercase letter."
        if not re.search(r"[0-9]", password):
            return "Password must contain a digit."
        result = sign_up(email, password)
        if "idToken" in result:
            id_token = result["idToken"]
            uid = get_uid_from_token(id_token)
            all_users = db_get("/users", id_token)
            first_user = (not all_users or len(all_users) == 0)
            profile = {
                "email": email,
                "username": username or email.split('@')[0],
                "bio": "",
                "profile_pic": "",
                "verified": False,
                "banned": False,
                "isAdmin": first_user,
                "dark_mode": False,
                "last_online": 0              # new field
            }
            db_put(f"/users/{uid}", profile, id_token)
            send_verification_email(id_token)
            return redirect(url_for("login"))
        else:
            error = result.get("error", {}).get("message", "Signup failed")
            return f"Signup failed: {error}"
    return render_template("signup.html")

@app.route("/verify_email", methods=["POST"])
def verify_email():
    if "user" not in session:
        return redirect(url_for("login"))
    send_verification_email(session["id_token"])
    return "Verification email sent. Check your inbox."

@app.route("/refresh_verification", methods=["POST"])
def refresh_verification():
    if "user" not in session:
        return redirect(url_for("login"))
    id_token = session["id_token"]
    info = get_account_info(id_token)
    if "users" in info and info["users"]:
        session["email_verified"] = info["users"][0].get("emailVerified", False)
    else:
        session["email_verified"] = False
    return redirect(request.referrer or url_for("feed"))

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/feed", methods=["GET", "POST"])
def feed():
    if "user" not in session:
        return redirect(url_for("login"))
    profile = db_get(f"/users/{session['uid']}", session["id_token"])
    if isinstance(profile, dict) and profile.get("banned", False):
        session.clear()
        return "Your account has been banned."
    if request.method == "POST":
        content = request.form["content"].strip()
        if content:
            post_data = {
                "content": content,
                "author_email": session["user"],
                "author_username": session.get("username", session["user"]),
                "timestamp": int(time.time() * 1000),
                "verified": session.get("verified", False),
                "likes": {},
                "comments": {},
                "hidden": False
            }
            db_post("/posts", post_data, session["id_token"])
        return redirect(url_for("feed"))
    posts_data = db_get("/posts", session["id_token"])
    posts_list = []
    if isinstance(posts_data, dict):
        # cache all users for online status lookup
        all_users = db_get("/users", session["id_token"])
        for post_id, post in posts_data.items():
            if isinstance(post, dict):
                if not session.get("isAdmin", False) and post.get("hidden", False):
                    continue
                post["id"] = post_id
                post["like_count"] = len(post.get("likes", {}))
                post["liked_by_me"] = session["uid"] in post.get("likes", {})
                comments = post.get("comments", {})
                comment_list = []
                if isinstance(comments, dict):
                    for cid, c in comments.items():
                        if isinstance(c, dict):
                            c["id"] = cid
                            comment_list.append(c)
                    comment_list.sort(key=lambda x: x.get("timestamp", 0))
                post["comment_list"] = comment_list
                # Determine author online status
                author_email = post.get("author_email", "")
                author_online = False
                if isinstance(all_users, dict):
                    for uid, u in all_users.items():
                        if isinstance(u, dict) and u.get("email") == author_email:
                            author_online = is_online(u)
                            break
                post["author_online"] = author_online
                posts_list.append(post)
        posts_list.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
    return render_template("feed.html", posts=posts_list)

@app.route("/like/<post_id>", methods=["POST"])
def like_post(post_id):
    if "user" not in session:
        return jsonify({"error": "Not logged in"}), 401
    uid = session["uid"]
    post = db_get(f"/posts/{post_id}", session["id_token"])
    if not isinstance(post, dict):
        return jsonify({"error": "Post not found"}), 404
    likes = post.get("likes", {})
    if not isinstance(likes, dict):
        likes = {}
    if uid in likes:
        del likes[uid]
    else:
        likes[uid] = True
    db_patch(f"/posts/{post_id}", {"likes": likes}, session["id_token"])
    return jsonify({"like_count": len(likes), "liked": uid in likes})

@app.route("/comment/<post_id>", methods=["POST"])
def comment_post(post_id):
    if "user" not in session:
        return jsonify({"error": "Not logged in"}), 401
    content = request.form.get("content", "").strip()
    if not content:
        return jsonify({"error": "Empty comment"}), 400
    comment = {
        "author": session.get("username", session["user"]),
        "uid": session["uid"],
        "content": content,
        "timestamp": int(time.time() * 1000)
    }
    db_post(f"/posts/{post_id}/comments", comment, session["id_token"])
    return redirect(url_for("feed"))

@app.route("/report/<post_id>", methods=["POST"])
def report_post(post_id):
    if "user" not in session:
        return redirect(url_for("login"))
    existing = db_get(f"/reports/posts/{post_id}/{session['uid']}", session["id_token"])
    # If already reported, silently redirect (soft confirmation)
    if isinstance(existing, dict):
        return redirect(url_for("feed") + "?reported=1")
    report_data = {
        "reporter": session["uid"],
        "reporter_name": session.get("username", session["user"]),
        "timestamp": int(time.time() * 1000),
        "status": "pending"
    }
    db_put(f"/reports/posts/{post_id}/{session['uid']}", report_data, session["id_token"])
    return redirect(url_for("feed") + "?reported=1")

# ---------- Profile / Email ----------
@app.route("/profile")
def profile():
    if "user" not in session:
        return redirect(url_for("login"))
    uid = session.get("uid")
    profile_data = db_get(f"/users/{uid}", session["id_token"])
    if not isinstance(profile_data, dict):
        profile_data = {"email": session["user"], "username": session["user"], "bio": "", "profile_pic": "", "verified": False, "dark_mode": False}
    return render_template("profile.html", profile=profile_data)

@app.route("/profile/edit", methods=["GET", "POST"])
def edit_profile():
    if "user" not in session:
        return redirect(url_for("login"))
    uid = session.get("uid")
    if request.method == "POST":
        new_username = request.form["username"].strip()
        new_bio = request.form["bio"].strip()
        new_pic = request.form["profile_pic"].strip()
        update_data = {"username": new_username, "bio": new_bio, "profile_pic": new_pic}
        db_patch(f"/users/{uid}", update_data, session["id_token"])
        session["username"] = new_username
        return redirect(url_for("profile"))
    profile_data = db_get(f"/users/{uid}", session["id_token"])
    if not isinstance(profile_data, dict):
        profile_data = {"email": session["user"], "username": session["user"], "bio": "", "profile_pic": ""}
    return render_template("edit_profile.html", profile=profile_data)

@app.route("/change_email", methods=["GET", "POST"])
def change_email():
    if "user" not in session:
        return redirect(url_for("login"))
    if request.method == "POST":
        new_email = request.form["new_email"]
        result = update_email(session["id_token"], new_email)
        if "idToken" in result:
            db_patch(f"/users/{session['uid']}", {"email": new_email}, session["id_token"])
            session["user"] = new_email
            return redirect(url_for("profile"))
        else:
            return f"Failed: {result.get('error', {}).get('message', 'Unknown error')}"
    return render_template("change_email.html")

@app.route("/toggle_dark_mode", methods=["POST"])
def toggle_dark_mode():
    if "user" not in session:
        return redirect(url_for("login"))
    current = session.get("dark_mode", False)
    new = not current
    session["dark_mode"] = new
    db_patch(f"/users/{session['uid']}", {"dark_mode": new}, session["id_token"])
    return redirect(request.referrer or url_for("feed"))

# ---------- Friends ----------
@app.route("/search_users", methods=["GET"])
def search_users():
    if "user" not in session:
        return redirect(url_for("login"))
    q = request.args.get("q", "").strip()
    if not q:
        return render_template("search_users.html", results=[], query="")
    all_users = db_get("/users", session["id_token"])
    results = []
    if isinstance(all_users, dict):
        for uid, data in all_users.items():
            if not isinstance(data, dict):
                continue
            username = data.get("username", "")
            email = data.get("email", "")
            if q.lower() in username.lower() or q.lower() in email.lower():
                data["uid"] = uid
                data["is_me"] = (uid == session["uid"])
                data["online"] = is_online(data)
                if uid != session["uid"]:
                    friends = db_get(f"/friends/{session['uid']}", session["id_token"])
                    data["status"] = "none"
                    if isinstance(friends, dict) and uid in friends:
                        data["status"] = "friends"
                    else:
                        sent = db_get(f"/friend_requests/{uid}/{session['uid']}", session["id_token"])
                        received = db_get(f"/friend_requests/{session['uid']}/{uid}", session["id_token"])
                        if isinstance(sent, dict):
                            data["status"] = "pending_sent"
                        elif isinstance(received, dict):
                            data["status"] = "pending_received"
                else:
                    data["status"] = "self"
                results.append(data)
    return render_template("search_users.html", results=results, query=q)

@app.route("/friend_action", methods=["POST"])
def friend_action():
    if "user" not in session:
        return redirect(url_for("login"))
    action = request.form["action"]
    target_uid = request.form["uid"]
    cur_uid = session["uid"]
    ts = int(time.time() * 1000)
    if action == "send":
        db_put(f"/friend_requests/{target_uid}/{cur_uid}", {"status": "pending", "timestamp": ts}, session["id_token"])
        add_notification(target_uid, cur_uid, "friend_request", session["id_token"])
    elif action == "accept":
        req = db_get(f"/friend_requests/{cur_uid}/{target_uid}", session["id_token"])
        if isinstance(req, dict) and req.get("status") == "pending":
            db_patch(f"/friends/{cur_uid}", {target_uid: True}, session["id_token"])
            db_patch(f"/friends/{target_uid}", {cur_uid: True}, session["id_token"])
            db_delete(f"/friend_requests/{cur_uid}/{target_uid}", session["id_token"])
            add_notification(target_uid, cur_uid, "friend_accept", session["id_token"])
    elif action == "decline":
        db_delete(f"/friend_requests/{cur_uid}/{target_uid}", session["id_token"])
    return redirect(url_for("feed"))

@app.route("/friends")
def friends_list():
    if "user" not in session:
        return redirect(url_for("login"))
    cur_uid = session["uid"]
    friends_data = db_get(f"/friends/{cur_uid}", session["id_token"])
    requests_data = db_get(f"/friend_requests/{cur_uid}", session["id_token"])
    friends = []
    if isinstance(friends_data, dict):
        for f_uid in friends_data:
            prof = db_get(f"/users/{f_uid}", session["id_token"])
            if isinstance(prof, dict):
                prof["uid"] = f_uid
                prof["online"] = is_online(prof)
                friends.append(prof)
    pending = []
    if isinstance(requests_data, dict):
        for sender, req in requests_data.items():
            if isinstance(req, dict) and req.get("status") == "pending":
                sender_prof = db_get(f"/users/{sender}", session["id_token"])
                if isinstance(sender_prof, dict):
                    sender_prof["uid"] = sender
                    sender_prof["online"] = is_online(sender_prof)
                    pending.append(sender_prof)
    return render_template("friends.html", friends=friends, pending_requests=pending)

# ---------- Messaging ----------
@app.route("/inbox")
def inbox():
    if "user" not in session:
        return redirect(url_for("login"))
    cur_uid = session["uid"]
    friends_data = db_get(f"/friends/{cur_uid}", session["id_token"])
    friend_list = []
    if isinstance(friends_data, dict):
        for f_uid in friends_data:
            prof = db_get(f"/users/{f_uid}", session["id_token"])
            if isinstance(prof, dict):
                prof["uid"] = f_uid
                prof["online"] = is_online(prof)
                chat_id = get_chat_id(cur_uid, f_uid)
                msgs = db_get(f"/messages/{chat_id}", session["id_token"])
                if isinstance(msgs, dict):
                    sorted_msgs = sorted(msgs.values(), key=lambda x: x.get("timestamp", 0) if isinstance(x, dict) else 0)
                    if sorted_msgs and isinstance(sorted_msgs[-1], dict):
                        prof["last_message"] = sorted_msgs[-1]["content"]
                else:
                    prof["last_message"] = "No messages yet."
                friend_list.append(prof)
    return render_template("inbox.html", friends=friend_list)

@app.route("/chat/<other_uid>")
def chat_page(other_uid):
    if "user" not in session:
        return redirect(url_for("login"))
    cur_uid = session["uid"]
    my_friends = db_get(f"/friends/{cur_uid}", session["id_token"])
    if not isinstance(my_friends, dict) or other_uid not in my_friends:
        return "You must be friends to chat.", 403
    other_prof = db_get(f"/users/{other_uid}", session["id_token"])
    if not isinstance(other_prof, dict):
        other_prof = {"username": "Unknown", "email": ""}
    other_online = is_online(other_prof)
    return render_template("chat.html",
                           other_user=other_prof,
                           other_uid=other_uid,
                           chat_id=get_chat_id(cur_uid, other_uid),
                           other_online=other_online,
                           config={
                               "apiKey": API_KEY,
                               "authDomain": FIREBASE_CONFIG["authDomain"],
                               "databaseURL": DATABASE_URL,
                               "projectId": FIREBASE_CONFIG.get("projectId", ""),
                               "storageBucket": FIREBASE_CONFIG.get("storageBucket", ""),
                               "messagingSenderId": FIREBASE_CONFIG.get("messagingSenderId", ""),
                               "appId": FIREBASE_CONFIG.get("appId", "")
                           })

@app.route("/api/send_message", methods=["POST"])
def api_send_message():
    if "user" not in session:
        return jsonify({"error": "Not logged in"}), 401
    data = request.get_json()
    if not data:
        return jsonify({"error": "Invalid JSON"}), 400
    to_uid = data.get("to")
    content = data.get("content", "").strip()
    if not to_uid or not content:
        return jsonify({"error": "Missing fields"}), 400
    cur_uid = session["uid"]
    chat_id = get_chat_id(cur_uid, to_uid)
    msg = {
        "sender": cur_uid,
        "sender_name": session.get("username", session["user"]),
        "content": content,
        "timestamp": int(time.time() * 1000)
    }
    db_post(f"/messages/{chat_id}", msg, session["id_token"])
    add_notification(to_uid, cur_uid, "message", session["id_token"], extra={"content": content[:30]})
    return jsonify({"success": True, "message": msg})

@app.route("/api/get_messages/<other_uid>")
def api_get_messages(other_uid):
    if "user" not in session:
        return jsonify([]), 401
    cur_uid = session["uid"]
    chat_id = get_chat_id(cur_uid, other_uid)
    msgs = db_get(f"/messages/{chat_id}", session["id_token"])
    if isinstance(msgs, dict):
        msg_list = []
        for mid, m in msgs.items():
            if isinstance(m, dict):
                m["id"] = mid
                msg_list.append(m)
        msg_list.sort(key=lambda x: x.get("timestamp", 0))
        return jsonify(msg_list)
    return jsonify([])

# ---------- Notifications ----------
@app.route("/notifications")
def view_notifications():
    if "user" not in session:
        return redirect(url_for("login"))
    cur_uid = session["uid"]
    notifs_data = db_get(f"/notifications/{cur_uid}", session["id_token"])
    notifs = []
    if isinstance(notifs_data, dict):
        for nid, n in notifs_data.items():
            if isinstance(n, dict):
                n["id"] = nid
                notifs.append(n)
        notifs.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
    for n in notifs:
        if not n.get("seen", True):
            db_patch(f"/notifications/{cur_uid}/{n['id']}", {"seen": True}, session["id_token"])
    return render_template("notifications.html", notifications=notifs)

@app.route("/api/unread_notifications")
def api_unread_notifications():
    if "user" not in session:
        return jsonify({"unread": 0}), 401
    cur_uid = session["uid"]
    notifs_data = db_get(f"/notifications/{cur_uid}", session["id_token"])
    unread = 0
    if isinstance(notifs_data, dict):
        for n in notifs_data.values():
            if isinstance(n, dict) and not n.get("seen", False):
                unread += 1
    return jsonify({"unread": unread})

# ---------- Online Ping ----------
@app.route("/api/ping", methods=["POST"])
def api_ping():
    if "user" not in session:
        return jsonify({"success": False}), 401
    db_patch(f"/users/{session['uid']}", {"last_online": int(time.time() * 1000)}, session["id_token"])
    return jsonify({"success": True})

# ---------- Admin ----------
@app.route("/admin")
def admin_dashboard():
    if not session.get("isAdmin"):
        return "Access denied.", 403
    users_data = db_get("/users", session["id_token"])
    posts_data = db_get("/posts", session["id_token"])
    total_users = len(users_data) if isinstance(users_data, dict) else 0
    total_posts = len(posts_data) if isinstance(posts_data, dict) else 0
    return render_template("admin_dashboard.html", total_users=total_users, total_posts=total_posts)

@app.route("/admin/users")
def admin_users():
    if not session.get("isAdmin"):
        return "Access denied.", 403
    all_users = db_get("/users", session["id_token"])
    users_list = []
    if isinstance(all_users, dict):
        for uid, data in all_users.items():
            if isinstance(data, dict):
                data["uid"] = uid
                users_list.append(data)
    return render_template("admin_users.html", users=users_list)

@app.route("/admin/posts")
def admin_posts():
    if not session.get("isAdmin"):
        return "Access denied.", 403
    all_posts = db_get("/posts", session["id_token"])
    posts_list = []
    if isinstance(all_posts, dict):
        for pid, post in all_posts.items():
            if isinstance(post, dict):
                post["id"] = pid
                posts_list.append(post)
        posts_list.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
    return render_template("admin_posts.html", posts=posts_list)

@app.route("/admin/reports")
def admin_reports():
    if not session.get("isAdmin"):
        return "Access denied.", 403
    reports_data = db_get("/reports/posts", session["id_token"])
    reports_list = []
    if isinstance(reports_data, dict):
        for post_id, reporters in reports_data.items():
            if isinstance(reporters, dict):
                for uid, rep in reporters.items():
                    if isinstance(rep, dict):
                        rep["post_id"] = post_id
                        rep["reporter_uid"] = uid
                        reports_list.append(rep)
        reports_list.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
    return render_template("admin_reports.html", reports=reports_list)

@app.route("/admin/dismiss_report/<post_id>/<reporter_uid>", methods=["POST"])
def dismiss_report(post_id, reporter_uid):
    if not session.get("isAdmin"):
        return "Access denied.", 403
    db_patch(f"/reports/posts/{post_id}/{reporter_uid}", {"status": "dismissed"}, session["id_token"])
    return redirect(url_for("admin_reports"))

@app.route("/admin/toggle_hide/<post_id>", methods=["POST"])
def toggle_hide(post_id):
    if not session.get("isAdmin"):
        return "Access denied.", 403
    post = db_get(f"/posts/{post_id}", session["id_token"])
    if isinstance(post, dict):
        current = post.get("hidden", False)
        db_patch(f"/posts/{post_id}", {"hidden": not current}, session["id_token"])
    return redirect(request.referrer or url_for("feed"))

@app.route("/admin/delete_post/<post_id>", methods=["POST"])
def delete_post(post_id):
    if not session.get("isAdmin"):
        return "Access denied.", 403
    db_delete(f"/posts/{post_id}", session["id_token"])
    return redirect(request.referrer or url_for("admin_posts"))

@app.route("/admin/bulk_users", methods=["POST"])
def bulk_users():
    if not session.get("isAdmin"):
        return "Access denied.", 403
    uids = request.form.getlist("uids")
    action = request.form.get("action")
    if not uids or not action:
        return "Missing parameters.", 400
    for uid in uids:
        if uid == session["uid"] and action in ("ban", "delete"):
            continue
        if action == "verify":
            db_patch(f"/users/{uid}", {"verified": True}, session["id_token"])
        elif action == "unverify":
            db_patch(f"/users/{uid}", {"verified": False}, session["id_token"])
        elif action == "ban":
            db_patch(f"/users/{uid}", {"banned": True}, session["id_token"])
        elif action == "unban":
            db_patch(f"/users/{uid}", {"banned": False}, session["id_token"])
        elif action == "make_admin":
            db_patch(f"/users/{uid}", {"isAdmin": True}, session["id_token"])
        elif action == "revoke_admin":
            db_patch(f"/users/{uid}", {"isAdmin": False}, session["id_token"])
        elif action == "delete":
            db_delete(f"/users/{uid}", session["id_token"])
    return redirect(url_for("admin_users"))

@app.route("/admin/toggle_verify/<uid>", methods=["POST"])
def toggle_verify(uid):
    if not session.get("isAdmin"): return "Access denied.", 403
    user = db_get(f"/users/{uid}", session["id_token"])
    if isinstance(user, dict):
        curr = user.get("verified", False)
        db_patch(f"/users/{uid}", {"verified": not curr}, session["id_token"])
        if uid == session["uid"]:
            session["verified"] = not curr
    return redirect(url_for("admin_users"))

@app.route("/admin/toggle_ban/<uid>", methods=["POST"])
def toggle_ban(uid):
    if not session.get("isAdmin"): return "Access denied.", 403
    if uid == session["uid"]: return "Cannot ban self.", 400
    user = db_get(f"/users/{uid}", session["id_token"])
    if isinstance(user, dict):
        curr = user.get("banned", False)
        db_patch(f"/users/{uid}", {"banned": not curr}, session["id_token"])
    return redirect(url_for("admin_users"))

@app.route("/admin/toggle_admin/<uid>", methods=["POST"])
def toggle_admin(uid):
    if not session.get("isAdmin"): return "Access denied.", 403
    user = db_get(f"/users/{uid}", session["id_token"])
    if isinstance(user, dict):
        curr = user.get("isAdmin", False)
        db_patch(f"/users/{uid}", {"isAdmin": not curr}, session["id_token"])
        if uid == session["uid"]:
            session["isAdmin"] = not curr
    return redirect(url_for("admin_users"))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)
