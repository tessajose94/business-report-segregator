"""
credentials_helper.py
Handles AWS credentials for both environments:
  - Streamlit Cloud: reads from st.secrets (set in app Settings → Secrets)
  - Local:           fetches via ada (Conduit) automatically
"""

import os
import json
import subprocess
import shutil
import boto3
from botocore.exceptions import NoCredentialsError, ClientError

# ── Conduit config (local only) ────────────────────────────────────────────────
ACCOUNT_ID = "191667938948"
PROVIDER   = "conduit"
ROLE       = "IibsAdminAccess-DO-NOT-DELETE"

ADA_CANDIDATES = [
    os.path.expanduser("~/.toolbox/bin/ada"),
    "/usr/local/bin/ada",
    "/opt/homebrew/bin/ada",
    shutil.which("ada") or "",
]


def inject_credentials() -> tuple:
    """
    Injects AWS credentials from the best available source.
    Priority:
      1. Streamlit secrets  (cloud deployment)
      2. Already in env     (works after ada exec locally)
      3. ada Conduit fetch  (local Amazon Mac)
    Returns (ok, message, identity_str)
    """
    # ── 1. Try Streamlit secrets ───────────────────────────────────────────────
    try:
        import streamlit as st
        if hasattr(st, "secrets") and "aws" in st.secrets:
            s = st.secrets["aws"]
            os.environ["AWS_ACCESS_KEY_ID"]           = s["AWS_ACCESS_KEY_ID"]
            os.environ["AWS_SECRET_ACCESS_KEY"]       = s["AWS_SECRET_ACCESS_KEY"]
            os.environ["AWS_DEFAULT_REGION"]          = s.get("AWS_DEFAULT_REGION", "us-east-1")
            os.environ["AWS_CONFIG_FILE"]             = ""
            os.environ["AWS_SHARED_CREDENTIALS_FILE"] = ""
            ok, msg, identity = _verify()
            if ok:
                return True, "Credentials loaded from Streamlit secrets", identity
    except Exception:
        pass

    # ── 2. Check existing env credentials ─────────────────────────────────────
    os.environ.pop("AWS_CONFIG_FILE", None)
    os.environ.pop("AWS_SHARED_CREDENTIALS_FILE", None)
    ok, msg, identity = _verify()
    if ok:
        return True, "Credentials already active", identity

    # ── 3. Fetch via ada (local Amazon Mac) ────────────────────────────────────
    ada_path = next((p for p in ADA_CANDIDATES if p and os.path.isfile(p) and os.access(p, os.X_OK)), "")
    if not ada_path:
        return False, "No credentials found. Add AWS keys in Streamlit → Settings → Secrets.", ""

    try:
        result = subprocess.run(
            [ada_path, "credentials", "print",
             f"--account={ACCOUNT_ID}",
             f"--provider={PROVIDER}",
             f"--role={ROLE}",
             "--format=json"],
            capture_output=True, text=True, timeout=30,
            env={**os.environ, "HOME": os.path.expanduser("~")},
        )
        if result.returncode != 0 or not result.stdout.strip():
            err = result.stderr.strip() or "No output from ada"
            hint = " — Run `mwinit -o` to refresh Midway." if "midway" in err.lower() else ""
            return False, f"ada error: {err}{hint}", ""

        creds = json.loads(result.stdout)
        os.environ["AWS_ACCESS_KEY_ID"]           = creds["AccessKeyId"]
        os.environ["AWS_SECRET_ACCESS_KEY"]       = creds["SecretAccessKey"]
        os.environ["AWS_SESSION_TOKEN"]           = creds["SessionToken"]
        os.environ["AWS_CONFIG_FILE"]             = ""
        os.environ["AWS_SHARED_CREDENTIALS_FILE"] = ""

        ok, msg, identity = _verify()
        if ok:
            expiry = creds.get("Expiration", "")[:16]
            return True, f"Credentials fetched via ada (expires: {expiry})", identity
        return False, f"Credentials fetched but verification failed: {msg}", ""

    except subprocess.TimeoutExpired:
        return False, "ada timed out. Run `mwinit -o` to refresh Midway.", ""
    except Exception as e:
        return False, f"Unexpected error: {str(e)}", ""


def _verify() -> tuple:
    """Calls STS to confirm credentials are valid."""
    try:
        identity = boto3.client("sts").get_caller_identity()
        account  = identity["Account"]
        short_id = identity["Arn"].split("/")[-1]
        return True, "OK", f"Account: {account}  |  {short_id}"
    except NoCredentialsError:
        return False, "No credentials in environment.", ""
    except ClientError as e:
        return False, e.response["Error"]["Message"], ""
    except Exception as e:
        return False, str(e), ""
