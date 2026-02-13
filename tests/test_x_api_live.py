import os
import json
from datetime import datetime

import pytest

try:
    import tweepy  # type: ignore
except Exception as e:  # pragma: no cover - local env dependency
    tweepy = None  # type: ignore


def _require_env(var: str) -> str:
    val = os.getenv(var)
    if not val:
        pytest.skip(f"Skipping: environment variable {var} is not set")
    return val


def _make_client() -> "tweepy.Client":
    if tweepy is None:
        pytest.skip("Skipping: tweepy not installed in this environment")
    _require_env("TWITTER_API_KEY")
    _require_env("TWITTER_API_SECRET")
    _require_env("TWITTER_ACCESS_TOKEN")
    _require_env("TWITTER_ACCESS_SECRET")
    return tweepy.Client(
        consumer_key=os.getenv("TWITTER_API_KEY"),
        consumer_secret=os.getenv("TWITTER_API_SECRET"),
        access_token=os.getenv("TWITTER_ACCESS_TOKEN"),
        access_token_secret=os.getenv("TWITTER_ACCESS_SECRET"),
        wait_on_rate_limit=True,
    )


def _fail_with_http_details(e: Exception) -> None:
    resp = getattr(e, "response", None)
    if resp is None:
        pytest.fail(f"X API error: {e}")
    try:
        body = resp.json()
    except Exception:
        body = getattr(resp, "text", "<no body>")
    headers = {}
    try:
        raw = dict(getattr(resp, "headers", {}) or {})
        for k in list(raw.keys()):
            if k and k.lower() in {"authorization", "proxy-authorization"}:
                raw.pop(k, None)
        # Keep a few useful hints
        for k in ("content-type", "x-rate-limit-limit", "x-rate-limit-remaining", "x-rate-limit-reset"):
            if k in {kk.lower() for kk in raw.keys()}:
                # normalize casing lookups
                for kk in raw.keys():
                    if kk.lower() == k:
                        headers[kk] = raw[kk]
                        break
    except Exception:
        pass
    pytest.fail(
        "X API HTTP error: "
        f"status={getattr(resp, 'status_code', '?')} reason={getattr(resp, 'reason', '')}\n"
        f"headers={headers}\n"
        f"body={json.dumps(body, indent=2) if isinstance(body, (dict, list)) else body}"
    )


@pytest.mark.skipif(
    os.getenv("TWITTER_LIVE_GET_ME", "false").lower() not in {"1", "true", "yes"},
    reason="Set TWITTER_LIVE_GET_ME=true to exercise a real GET /2/users/me",
)
def test_x_api_get_me_smoke():
    """Smoke test: verifies credentials/auth by calling GET /2/users/me."""
    client = _make_client()
    try:
        r = client.get_me()
        data = getattr(r, "data", None)
        assert data is not None, "Expected user data in response"
        # Soft print to help debugging when running locally
        print(f"whoami: id={getattr(data, 'id', '?')} username={getattr(data, 'username', '?')}")
    except Exception as e:  # Tweepy raises various subclasses; capture and show details
        _fail_with_http_details(e)


@pytest.mark.skipif(
    os.getenv("TWITTER_LIVE_POST", "false").lower() not in {"1", "true", "yes"},
    reason="Set TWITTER_LIVE_POST=true to exercise a real post/delete",
)
def test_x_api_post_and_delete_optional():
    """Optional live test: posts and deletes a throwaway tweet to verify write access."""
    client = _make_client()
    text = f"insiders live test {datetime.utcnow().isoformat(timespec='seconds')}Z"
    try:
        created = client.create_tweet(text=text)
    except Exception as e:
        _fail_with_http_details(e)
        return  # for type checkers

    tweet_id = None
    try:
        data = getattr(created, "data", {}) or {}
        tweet_id = data.get("id")
        assert tweet_id, "Expected an id in create_tweet response"
    finally:
        if tweet_id:
            try:
                client.delete_tweet(tweet_id)
            except Exception:
                # Best-effort cleanup; ignore delete failures
                pass


