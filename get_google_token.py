"""
One-time script to get a Google OAuth refresh token.

Steps:
  1. Go to https://console.cloud.google.com/
  2. Create a project (or use existing)
  3. Enable "Google Calendar API"
  4. Create OAuth 2.0 credentials → Desktop app
  5. Download the JSON, copy client_id and client_secret below
  6. Run: python3 get_google_token.py
  7. Copy the printed refresh_token → add as GitHub Secret GOOGLE_REFRESH_TOKEN
"""

import urllib.request, urllib.parse, json, webbrowser

CLIENT_ID     = input("Paste your Google OAuth client_id: ").strip()
CLIENT_SECRET = input("Paste your client_secret: ").strip()

SCOPE    = "https://www.googleapis.com/auth/calendar.readonly"
AUTH_URL = (
    "https://accounts.google.com/o/oauth2/v2/auth"
    f"?client_id={CLIENT_ID}"
    f"&redirect_uri=urn:ietf:wg:oauth:2.0:oob"
    f"&response_type=code"
    f"&scope={urllib.parse.quote(SCOPE)}"
    f"&access_type=offline"
    f"&prompt=consent"
)

print(f"\nOpening browser for Google login…\n{AUTH_URL}\n")
webbrowser.open(AUTH_URL)
code = input("Paste the authorization code from the browser: ").strip()

data = urllib.parse.urlencode({
    "code":          code,
    "client_id":     CLIENT_ID,
    "client_secret": CLIENT_SECRET,
    "redirect_uri":  "urn:ietf:wg:oauth:2.0:oob",
    "grant_type":    "authorization_code",
}).encode()

req  = urllib.request.Request("https://oauth2.googleapis.com/token", data=data, method="POST")
resp = json.loads(urllib.request.urlopen(req).read())

print("\n✅ Add these as GitHub Secrets:")
print(f"  GOOGLE_CLIENT_ID     = {CLIENT_ID}")
print(f"  GOOGLE_CLIENT_SECRET = {CLIENT_SECRET}")
print(f"  GOOGLE_REFRESH_TOKEN = {resp.get('refresh_token', 'ERROR — missing refresh_token')}")
