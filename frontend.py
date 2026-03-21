import streamlit as st
import requests
import os
from datetime import date
import html
from streamlit.components.v1 import html as st_html

st.set_page_config(page_title="JustPost", layout="wide")

BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")
LOGO_PATH = "justpost(logo).jpeg"

if 'token' not in st.session_state:
    st.session_state.token = None
if 'user' not in st.session_state:
    st.session_state.user = None
if 'page' not in st.session_state:
    st.session_state.page = "🏠 Feed"
if 'upload_notice' not in st.session_state:
    st.session_state.upload_notice = None
if 'redirect_to_feed' not in st.session_state:
    st.session_state.redirect_to_feed = False


def get_headers():
    if st.session_state.token:
        return {"Authorization": f"Bearer {st.session_state.token}"}
    return {}


def api(method, path, **kwargs):
    """Central API call helper — always sends auth headers."""
    return requests.request(method, f"{BASE_URL}{path}", headers=get_headers(), **kwargs)

def login_page():
    if os.path.exists(LOGO_PATH):
        st.image(LOGO_PATH, width=180)
    st.title("🚀 Welcome to JustPost")

    email    = st.text_input("Email:")
    password = st.text_input("Password:", type="password")

    if email and password:
        col1, col2 = st.columns(2)

        with col1:
            if st.button("Login", type="primary", use_container_width=True):
                response = requests.post(
                    f"{BASE_URL}/auth/jwt/login",
                    data={"username": email, "password": password}
                )
                if response.status_code == 200:
                    st.session_state.token = response.json()["access_token"]
                    user_resp = api("GET", "/auth/me")
                    if user_resp.status_code == 200:
                        st.session_state.user = user_resp.json()
                        st.rerun()
                    else:
                        st.error("Failed to get user info")
                else:
                    st.error("Invalid email or password!")

        with col2:
            if st.button("Sign Up", type="secondary", use_container_width=True):
                response = requests.post(
                    f"{BASE_URL}/auth/register",
                    json={"email": email, "password": password}
                )
                if response.status_code == 201:
                    st.success("Account created! Click Login now.")
                else:
                    st.error(f"Registration failed: {response.json().get('detail', '')}")
    else:
        st.info("Enter your email and password above")

def upload_page():
    st.title("📸 Share Something")

    uploaded_file = st.file_uploader(
        "Choose media",
        type=['png', 'jpg', 'jpeg', 'mp4', 'avi', 'mov', 'mkv', 'webm']
    )
    caption = st.text_area("Caption:", placeholder="What's on your mind?")

    if uploaded_file and st.button("Share", type="primary"):
        with st.spinner("Uploading..."):
            response = api(
                "POST", "/upload",
                files={"file": (uploaded_file.name, uploaded_file.getvalue(), uploaded_file.type)},
                data={"caption": caption}
            )
            if response.status_code == 200:
                st.session_state.upload_notice = "Posted successfully!"
                st.session_state.redirect_to_feed = True
                st.rerun()
            else:
                st.error(f"Upload failed: {response.json().get('detail', '')}")

def create_transformed_url(original_url, transformation_params, caption=None):
    if not transformation_params:
        return original_url
    parts    = original_url.split("/")
    base_url = "/".join(parts[:4])
    file_path = "/".join(parts[4:])
    return f"{base_url}/tr:{transformation_params}/{file_path}"


def render_copy_link(share_url: str, key: str):
    safe_key = key.replace("-", "_")
    escaped_url = html.escape(share_url, quote=True)
    html_block = f"""
    <div style="display:flex;gap:8px;align-items:center;">
      <input id="link_{safe_key}" value="{escaped_url}" readonly
             style="flex:1;padding:8px;border:1px solid #cfd3d9;border-radius:6px;" />
      <button id="btn_{safe_key}" onclick="copy_{safe_key}()"
              style="padding:8px 12px;border-radius:6px;border:1px solid #cfd3d9;cursor:pointer;">
        Copy
      </button>
      <span id="status_{safe_key}" style="font-size:12px;color:#6b7280;"></span>
    </div>
    <script>
      function copy_{safe_key}() {{
        const input = document.getElementById("link_{safe_key}");
        const status = document.getElementById("status_{safe_key}");
        const text = input.value;
        const setStatus = (ok) => {{
          status.textContent = ok ? "Copied!" : "Press Ctrl/Cmd+C";
          setTimeout(() => status.textContent = "", 2000);
        }};

        const fallbackCopy = () => {{
          input.focus();
          input.select();
          input.setSelectionRange(0, 99999);
          try {{
            const ok = document.execCommand("copy");
            setStatus(ok);
          }} catch (e) {{
            setStatus(false);
          }}
        }};

        if (navigator.clipboard && window.isSecureContext) {{
          navigator.clipboard.writeText(text)
            .then(() => setStatus(true))
            .catch(() => fallbackCopy());
        }} else {{
          fallbackCopy();
        }}
      }}
    </script>
    """
    st_html(html_block, height=70)

def feed_page():
    st.title("🏠 Feed")
    if st.session_state.upload_notice:
        st.success(st.session_state.upload_notice)
        st.session_state.upload_notice = None

    response = api("GET", "/feed")
    if response.status_code != 200:
        st.error("Failed to load feed")
        return

    posts = response.json()["posts"]
    if not posts:
        st.info("No posts yet! Be the first to share something.")
        return

    for post in posts:
        st.markdown("---")

        col1, col2, col3 = st.columns([3, 1, 1])
        with col1:
            st.markdown(f"**{post.get('display_name', 'User')}** • {post['created_at'][:10]}")
        with col2:
            if not post.get('is_owner'):
                follow_label = "Unfollow" if post.get("is_following_author") else "Follow"
                if st.button(follow_label, key=f"follow_{post['id']}"):
                    author_id = post.get("author_id")
                    if not author_id:
                        st.error("Cannot follow this user right now.")
                    else:
                        if post.get("is_following_author"):
                            follow_resp = api("DELETE", f"/users/{author_id}/follow")
                        else:
                            follow_resp = api("POST", f"/users/{author_id}/follow")

                        if follow_resp.status_code == 200:
                            st.rerun()
                        else:
                            detail = follow_resp.json().get("detail", "Follow action failed")
                            st.error(detail)
        with col3:
            if post.get('is_owner'):
                if st.button("🗑️", key=f"del_{post['id']}", help="Delete post"):
                    del_resp = api("DELETE", f"/posts/{post['id']}")
                    if del_resp.status_code == 200:
                        st.success("Post deleted!")
                        st.rerun()
                    else:
                        st.error("Failed to delete post!")

        caption = post.get('caption', '')
        if post['file_type'] == 'image':
            st.image(create_transformed_url(post['url'], ""), width=400)
        else:
            video_url = create_transformed_url(post['url'], "w-400,h-200,cm-pad_resize,bg-blurred")
            col, _ = st.columns([1, 1])
            with col:
                st.video(video_url)
        if caption:
            st.caption(caption)

        with st.expander("🔗 Share"):
            share_url = post.get("url")
            if share_url:
                render_copy_link(share_url, key=f"share_{post['id']}")
            else:
                st.caption("No share link available.")

        like_label = f"❤️ {post['like_count']}" if post.get('is_liked') else f"🤍 {post['like_count']}"
        if st.button(like_label, key=f"like_{post['id']}"):
            if post.get('is_liked'):
                api("DELETE", f"/posts/{post['id']}/like")
            else:
                api("POST", f"/posts/{post['id']}/like")
            st.rerun()

        with st.expander(f"💬 Comments"):
            comments_resp = api("GET", f"/posts/{post['id']}/comments")
            if comments_resp.status_code == 200:
                comments = comments_resp.json()["comments"]
                if not comments:
                    st.caption("No comments yet.")
                for c in comments:
                    c_col1, c_col2 = st.columns([5, 1])
                    with c_col1:
                        st.markdown(f"**{c.get('display_name', 'User')}**: {c['text']}")
                    with c_col2:
                        if c.get('is_owner'):
                            if st.button("✕", key=f"delc_{c['id']}"):
                                api("DELETE", f"/comments/{c['id']}")
                                st.rerun()

            new_comment = st.text_input("Add a comment…", key=f"cinput_{post['id']}")
            if st.button("Post", key=f"cpost_{post['id']}") and new_comment:
                api("POST", f"/posts/{post['id']}/comments", json={"text": new_comment})
                st.rerun()


def profile_page():
    st.title("👤 Profile")
    me_resp = api("GET", "/users/profile/me")
    if me_resp.status_code != 200:
        st.error("Failed to load your profile")
        return

    me = me_resp.json()
    user_id = st.session_state.user.get("id")
    if not user_id:
        st.error("Missing user id")
        return

    st.markdown(f"**Email:** {me.get('email', '')}")
    st.markdown(f"**Display name:** {me.get('display_name', 'User')}")

    existing_birthday = None
    if me.get("birthday"):
        try:
            existing_birthday = date.fromisoformat(me["birthday"])
        except ValueError:
            existing_birthday = None

    st.subheader("Edit profile")
    username_input = st.text_input(
        "Custom username",
        value=me.get("custom_username") or "",
        help="3-30 chars, letters/numbers/_/.",
    )
    has_birthday = st.checkbox(
        "Add birthday",
        value=existing_birthday is not None,
        key="has_birthday_toggle",
    )
    birthday_input = st.date_input(
        "Birthday",
        value=existing_birthday or date(2000, 1, 1),
        disabled=not has_birthday,
        key="birthday_input",
    )
    saved = st.button("Save profile", type="primary")

    if saved:
        payload = {
            "custom_username": username_input.strip() or None,
            "birthday": birthday_input.isoformat() if has_birthday else None,
        }
        update_resp = api("PUT", "/users/profile/me", json=payload)
        if update_resp.status_code == 200:
            st.success("Profile updated")
            st.rerun()
        else:
            detail = update_resp.json().get("detail", "Failed to update profile")
            st.error(detail)

    stats_resp = api("GET", f"/users/{user_id}/profile")
    if stats_resp.status_code == 200:
        stats = stats_resp.json()
        c1, c2, c3 = st.columns(3)
        c1.metric("Followers", stats.get("followers", 0))
        c2.metric("Following", stats.get("following", 0))
        c3.metric("Posts", stats.get("post_count", 0))

    st.markdown("---")
    left, right = st.columns(2)

    with left:
        st.subheader("Followers")
        followers_resp = api("GET", f"/users/{user_id}/followers")
        if followers_resp.status_code != 200:
            st.caption("Could not load followers.")
        else:
            followers = followers_resp.json().get("followers", [])
            if not followers:
                st.caption("No followers yet.")
            for person in followers:
                p_name = person.get("display_name", "User")
                st.markdown(f"**{p_name}**")
                if person.get("is_me"):
                    st.caption("You")
                else:
                    label = "Unfollow" if person.get("is_following") else "Follow"
                    if st.button(label, key=f"follower_btn_{person['user_id']}"):
                        endpoint = f"/users/{person['user_id']}/follow"
                        if person.get("is_following"):
                            action_resp = api("DELETE", endpoint)
                        else:
                            action_resp = api("POST", endpoint)
                        if action_resp.status_code == 200:
                            st.rerun()
                        else:
                            st.error(action_resp.json().get("detail", "Action failed"))

    with right:
        st.subheader("Following")
        following_resp = api("GET", f"/users/{user_id}/following")
        if following_resp.status_code != 200:
            st.caption("Could not load following.")
        else:
            following = following_resp.json().get("following", [])
            if not following:
                st.caption("You're not following anyone yet.")
            for person in following:
                p_name = person.get("display_name", "User")
                st.markdown(f"**{p_name}**")
                if person.get("is_me"):
                    st.caption("You")
                else:
                    label = "Unfollow" if person.get("is_following") else "Follow"
                    if st.button(label, key=f"following_btn_{person['user_id']}"):
                        endpoint = f"/users/{person['user_id']}/follow"
                        if person.get("is_following"):
                            action_resp = api("DELETE", endpoint)
                        else:
                            action_resp = api("POST", endpoint)
                        if action_resp.status_code == 200:
                            st.rerun()
                        else:
                            st.error(action_resp.json().get("detail", "Action failed"))

if st.session_state.user is None:
    login_page()
else:
    current_profile_resp = api("GET", "/users/profile/me")
    if current_profile_resp.status_code == 200:
        current_name = current_profile_resp.json().get("display_name", "User")
    else:
        current_email = st.session_state.user.get("email", "")
        current_name = current_email.split("@", 1)[0].replace(".", " ").replace("_", " ").title() if current_email else "User"
    if os.path.exists(LOGO_PATH):
        st.sidebar.image(LOGO_PATH, width=140)
    st.sidebar.title(f"👋 Hi {current_name}!")

    if st.sidebar.button("Logout"):
        st.session_state.user = None
        st.session_state.token = None
        st.rerun()

    st.sidebar.markdown("---")
    if st.session_state.redirect_to_feed:
        st.session_state.page = "🏠 Feed"
        st.session_state.redirect_to_feed = False
    page = st.sidebar.radio("Navigate:", ["🏠 Feed", "📸 Upload", "👤 Profile"], key="page")

    if page == "🏠 Feed":
        feed_page()
    elif page == "📸 Upload":
        upload_page()
    else:
        profile_page()
