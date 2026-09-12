"""CloudSight Triage - front end (Cognito auth + role-based views).

Roles (Cognito groups), highest wins: owner > poweruser > patient.
  - patient:   upload own photo, view own results only
  - poweruser: upload on behalf of a patient, review queue, manual escalation
  - owner:     everything above + create/manage user accounts

``?role=patient|poweruser|owner`` in the URL only pre-fills a hint on the
login screen - it is a UI convenience, never an access-control decision.
Real permissions always come from the Cognito group claim in the signed ID
token, read after login, never from the query string.

Configuration (env vars or st.secrets): AWS_REGION, AWS_ACCESS_KEY_ID,
AWS_SECRET_ACCESS_KEY, INPUT_BUCKET, OUTPUT_BUCKET, DYNAMODB_TABLE,
COGNITO_USER_POOL_ID, COGNITO_CLIENT_ID, SES_FROM, DOCTOR_EMAIL.
"""

import base64
import hashlib
import json
import os
import time

import boto3
import streamlit as st
from boto3.dynamodb.conditions import Attr, Key
from botocore import UNSIGNED
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

st.set_page_config(page_title="CloudSight Triage", page_icon="🩺", layout="centered")

ALLOWED_TYPES = ["jpg", "jpeg", "png"]
POLL_ATTEMPTS = 20
POLL_INTERVAL_SECONDS = 3
ROLES = ("patient", "poweruser", "owner")
ROLE_PRECEDENCE = ("owner", "poweruser", "patient")


def cfg(name, default=""):
    if os.environ.get(name):
        return os.environ[name]
    try:
        return str(st.secrets[name])
    except Exception:
        return default


REGION = cfg("AWS_REGION", "us-east-1")
INPUT_BUCKET = cfg("INPUT_BUCKET")
OUTPUT_BUCKET = cfg("OUTPUT_BUCKET")
DDB_TABLE = cfg("DYNAMODB_TABLE")
USER_POOL_ID = cfg("COGNITO_USER_POOL_ID")
CLIENT_ID = cfg("COGNITO_CLIENT_ID")
SES_FROM = cfg("SES_FROM")
DOCTOR_EMAIL = cfg("DOCTOR_EMAIL") or SES_FROM


@st.cache_resource
def aws_clients():
    kwargs = {"region_name": REGION}
    access_key, secret_key = cfg("AWS_ACCESS_KEY_ID"), cfg("AWS_SECRET_ACCESS_KEY")
    if access_key and secret_key:
        kwargs["aws_access_key_id"] = access_key
        kwargs["aws_secret_access_key"] = secret_key
    session = boto3.session.Session(**kwargs)

    # Plain sign-in calls (InitiateAuth / RespondToAuthChallenge) are public
    # Cognito APIs keyed by ClientId/token, not by caller identity - call them
    # unsigned so no IAM permission is required just to log in.
    cognito_public = boto3.client("cognito-idp", region_name=REGION, config=Config(signature_version=UNSIGNED))

    return {
        "s3": session.client("s3"),
        "dynamodb": session.resource("dynamodb"),
        "cognito": session.client("cognito-idp"),  # Admin* calls - needs IAM creds
        "cognito_public": cognito_public,
        "ses": session.client("ses"),
    }


CLIENTS = aws_clients()
TABLE = CLIENTS["dynamodb"].Table(DDB_TABLE) if DDB_TABLE else None


# --------------------------------------------------------------------------- auth


def _decode_id_token(id_token):
    """Read claims out of the JWT payload without verifying the signature.

    Acceptable here: this token comes from a direct, TLS server-to-server call
    that *this same process* makes to Cognito - it is never received from, or
    forwarded to, an untrusted client. A public API built on top of this
    session would need to verify against Cognito's JWKS instead.
    """
    payload = id_token.split(".")[1]
    padded = payload + "=" * (-len(payload) % 4)
    return json.loads(base64.urlsafe_b64decode(padded))


def _role_of(groups):
    for role in ROLE_PRECEDENCE:
        if role in groups:
            return role
    return "patient"


def _complete_login(auth_result, username):
    claims = _decode_id_token(auth_result["IdToken"])
    groups = claims.get("cognito:groups", [])
    st.session_state.auth = {"username": username, "groups": groups, "role": _role_of(groups)}
    st.session_state.pop("challenge", None)
    st.rerun()


def _login_form():
    hint = st.query_params.get("role", "patient")
    if hint not in ROLES:
        hint = "patient"
    st.caption(f"Link hint: **{hint}** - your real access always comes from your account's role, not this hint.")

    with st.form("login"):
        username = st.text_input("Email")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Log in")

    if not submitted:
        return
    try:
        resp = CLIENTS["cognito_public"].initiate_auth(
            ClientId=CLIENT_ID,
            AuthFlow="USER_PASSWORD_AUTH",
            AuthParameters={"USERNAME": username, "PASSWORD": password},
        )
    except (ClientError, BotoCoreError) as exc:
        st.error(f"Sign-in failed: {exc}")
        return

    if resp.get("ChallengeName") == "NEW_PASSWORD_REQUIRED":
        st.session_state.challenge = {"session": resp["Session"], "username": username}
        st.rerun()
        return

    _complete_login(resp["AuthenticationResult"], username)


def _new_password_form():
    st.info("First login for this account - set a permanent password (min 8 characters).")
    with st.form("new_password"):
        new_password = st.text_input("New password", type="password")
        confirm = st.text_input("Confirm new password", type="password")
        submitted = st.form_submit_button("Set password and sign in")

    if not submitted:
        return
    if new_password != confirm:
        st.error("Passwords don't match.")
        return

    challenge = st.session_state.challenge
    try:
        resp = CLIENTS["cognito_public"].respond_to_auth_challenge(
            ClientId=CLIENT_ID,
            ChallengeName="NEW_PASSWORD_REQUIRED",
            Session=challenge["session"],
            ChallengeResponses={"USERNAME": challenge["username"], "NEW_PASSWORD": new_password},
        )
    except (ClientError, BotoCoreError) as exc:
        st.error(f"Could not set password: {exc}")
        return

    _complete_login(resp["AuthenticationResult"], challenge["username"])


def login_screen():
    st.title("🩺 CloudSight Triage")
    st.caption("Sign in to continue")
    if "challenge" in st.session_state:
        _new_password_form()
    else:
        _login_form()


def logout_sidebar(auth):
    with st.sidebar:
        st.write(f"**{auth['username']}**")
        st.caption(f"Role: {auth['role']}")
        if st.button("Log out"):
            st.session_state.pop("auth", None)
            st.rerun()


# --------------------------------------------------------------------------- upload + result


def upload_section(auth):
    st.subheader("Submit a photo for screening")

    target_user = auth["username"]
    if auth["role"] in ("poweruser", "owner"):
        entered = st.text_input("Patient identifier (email) - leave blank to use your own account")
        target_user = entered.strip() or auth["username"]

    uploaded = st.file_uploader("Choose a JPG or PNG photo", type=ALLOWED_TYPES)
    if uploaded is None:
        return

    data = uploaded.getvalue()
    st.image(data, caption=uploaded.name, use_container_width=True)
    if not st.button("Submit for screening", type="primary"):
        return

    object_key = f"uploads/{target_user}/{uploaded.name}"
    try:
        CLIENTS["s3"].put_object(
            Bucket=INPUT_BUCKET, Key=object_key, Body=data, ContentType=uploaded.type or "application/octet-stream"
        )
    except (ClientError, BotoCoreError) as exc:
        st.error(f"Upload failed: {exc}")
        return

    st.success(f"Uploaded for {target_user}. Waiting for the result…")
    _poll_and_render(hashlib.md5(data).hexdigest())


def _poll_and_render(image_id):
    record = None
    status_box = st.empty()
    with st.spinner("Analyzing…"):
        for attempt in range(1, POLL_ATTEMPTS + 1):
            try:
                resp = TABLE.query(KeyConditionExpression=Key("image_id").eq(image_id), Limit=1)
                if resp.get("Items"):
                    record = resp["Items"][0]
                    break
            except (ClientError, BotoCoreError) as exc:
                status_box.warning(f"Query error: {exc}")
            status_box.info(f"Analyzing… ({attempt}/{POLL_ATTEMPTS})")
            time.sleep(POLL_INTERVAL_SECONDS)
    status_box.empty()

    if record is None:
        st.warning("Still processing - check back in a minute, or ask your health worker.")
        return
    _render_result(record)


def _render_result(record):
    classification = record.get("classification", "unclassified")
    if classification == "medical":
        st.success("✅ Submitted to your doctor for review. This is a screening aid, not a diagnosis.")
    elif classification == "non_human":
        st.error(
            "We couldn't recognize a valid subject in this photo. "
            "Please retake it - closer, better lit, one subject in frame."
        )
    elif classification == "needs_review":
        st.info("📋 This photo was sent for manual review by your local health worker.")
    else:
        st.warning("Rekognition analysis is off on this deployment (metadata-only mode) - nothing to classify.")

    with st.expander("Details", expanded=False):
        c1, c2, c3 = st.columns(3)
        c1.metric("Labels", int(record.get("label_count", 0)))
        c2.metric("Text items", int(record.get("text_count", 0)))
        c3.metric("Faces", int(record.get("face_count", 0)))
        st.write(f"**Summary:** {record.get('summary', '—')}")
        st.caption(f"image_id {record.get('image_id')} · {record.get('timestamp')}")


def _result_row(item):
    with st.container(border=True):
        st.write(f"**{item.get('image_key')}**")
        st.caption(
            f"{item.get('timestamp')} · classification: {item.get('classification')} · "
            f"status: {item.get('escalation_status')}"
        )
        st.write(item.get("summary", "—"))


# --------------------------------------------------------------------------- patient view


def my_results_section(auth):
    st.subheader("My results")
    try:
        resp = TABLE.scan(FilterExpression=Attr("uploaded_by").eq(auth["username"]))
    except (ClientError, BotoCoreError) as exc:
        st.error(f"Could not load results: {exc}")
        return

    items = sorted(resp.get("Items", []), key=lambda i: i.get("timestamp", ""), reverse=True)
    if not items:
        st.caption("No submissions yet.")
        return
    for item in items[:20]:
        _result_row(item)


# --------------------------------------------------------------------------- power user / owner view


def review_queue_section(auth):
    st.subheader("Review queue")
    try:
        resp = TABLE.scan(FilterExpression=Attr("classification").eq("needs_review"))
    except (ClientError, BotoCoreError) as exc:
        st.error(f"Could not load the queue: {exc}")
        return

    items = sorted(resp.get("Items", []), key=lambda i: i.get("timestamp", ""))
    if not items:
        st.caption("Nothing pending review.")
        return

    for item in items:
        with st.container(border=True):
            st.write(f"**{item.get('image_key')}** · uploaded by {item.get('uploaded_by')}")
            st.caption(f"{item.get('timestamp')} · status: {item.get('escalation_status')}")
            st.write(item.get("summary", "—"))
            row_key = f"{item['image_id']}-{item['timestamp']}"
            c1, c2 = st.columns(2)
            if c1.button("Mark resolved", key=f"resolve-{row_key}"):
                _update_status(item, "resolved_by_poweruser")
            if c2.button("Escalate to doctor", key=f"escalate-{row_key}"):
                _manual_escalate(item, auth)


def _update_status(item, new_status):
    try:
        TABLE.update_item(
            Key={"image_id": item["image_id"], "timestamp": item["timestamp"]},
            UpdateExpression="SET escalation_status = :s",
            ExpressionAttributeValues={":s": new_status},
        )
        st.success("Updated.")
        st.rerun()
    except (ClientError, BotoCoreError) as exc:
        st.error(f"Update failed: {exc}")


def _manual_escalate(item, auth):
    if not SES_FROM or not DOCTOR_EMAIL:
        st.error("SES_FROM / DOCTOR_EMAIL not configured - cannot send an escalation email.")
        return
    try:
        CLIENTS["ses"].send_email(
            Source=SES_FROM,
            Destination={"ToAddresses": [DOCTOR_EMAIL]},
            Message={
                "Subject": {"Data": f"[CloudSight] Manually escalated: {item.get('image_key', '')[:60]}"},
                "Body": {
                    "Text": {
                        "Data": (
                            f"{auth['username']} manually escalated this item.\n\n"
                            f"Image:   {item.get('image_key')}\n"
                            f"Summary: {item.get('summary')}\n"
                            f"Result:  s3://{OUTPUT_BUCKET}/results/{item['image_id']}.json\n"
                        )
                    }
                },
            },
        )
        _update_status(item, "escalated_manually")
    except (ClientError, BotoCoreError) as exc:
        st.error(f"Could not send the escalation email: {exc}")


# --------------------------------------------------------------------------- owner view


def manage_users_section():
    st.subheader("Manage users")

    with st.form("create_user"):
        email = st.text_input("New user's email")
        role = st.selectbox("Role", ROLES)
        submitted = st.form_submit_button("Create account")

    if submitted and email:
        try:
            CLIENTS["cognito"].admin_create_user(
                UserPoolId=USER_POOL_ID,
                Username=email,
                UserAttributes=[
                    {"Name": "email", "Value": email},
                    {"Name": "email_verified", "Value": "true"},
                ],
                DesiredDeliveryMediums=["EMAIL"],
            )
            CLIENTS["cognito"].admin_add_user_to_group(UserPoolId=USER_POOL_ID, Username=email, GroupName=role)
            st.success(f"Created {email} as {role}. They'll receive a temporary password by email.")
        except (ClientError, BotoCoreError) as exc:
            st.error(f"Could not create user: {exc}")

    st.divider()
    st.caption("Existing users")
    try:
        users = CLIENTS["cognito"].list_users(UserPoolId=USER_POOL_ID).get("Users", [])
    except (ClientError, BotoCoreError) as exc:
        st.error(f"Could not list users: {exc}")
        return

    for u in users:
        try:
            groups = [
                g["GroupName"]
                for g in CLIENTS["cognito"]
                .admin_list_groups_for_user(UserPoolId=USER_POOL_ID, Username=u["Username"])
                .get("Groups", [])
            ]
        except (ClientError, BotoCoreError):
            groups = ["?"]
        st.write(f"- **{u['Username']}** — {', '.join(groups) or 'no group'} — {u['UserStatus']}")


# --------------------------------------------------------------------------- main


missing = [
    name
    for name, value in {
        "INPUT_BUCKET": INPUT_BUCKET,
        "OUTPUT_BUCKET": OUTPUT_BUCKET,
        "DYNAMODB_TABLE": DDB_TABLE,
        "COGNITO_USER_POOL_ID": USER_POOL_ID,
        "COGNITO_CLIENT_ID": CLIENT_ID,
    }.items()
    if not value
]
if missing:
    st.error("Missing configuration: " + ", ".join(missing))
    st.caption("Set these in the Streamlit **Secrets** panel (or as environment variables locally).")
    st.stop()

if "auth" not in st.session_state:
    login_screen()
    st.stop()

auth = st.session_state.auth
logout_sidebar(auth)

st.title("🩺 CloudSight Triage")
st.caption(f"Signed in as {auth['username']} · role: {auth['role']}")

upload_section(auth)
st.divider()

if auth["role"] == "patient":
    my_results_section(auth)
elif auth["role"] == "poweruser":
    review_queue_section(auth)
elif auth["role"] == "owner":
    review_queue_section(auth)
    st.divider()
    manage_users_section()
