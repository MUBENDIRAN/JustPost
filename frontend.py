import streamlit as st
import requests
import os

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

        col1, col2 = st.columns([4, 1])
        with col1:
            st.markdown(f"**{post.get('display_name', 'User')}** • {post['created_at'][:10]}")
        with col2:
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

if st.session_state.user is None:
    login_page()
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
    page = st.sidebar.radio("Navigate:", ["🏠 Feed", "📸 Upload"], key="page")

    if page == "🏠 Feed":
        feed_page()
    else:
        upload_page()
