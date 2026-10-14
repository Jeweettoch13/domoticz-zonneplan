#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Zonneplan Domoticz Plugin - eenmalige authenticatie setup
Aangepast voor de OAuth 2.0 Authorization Code + PKCE-login.

Gebruik:
    py setup_auth.py

Het script slaat zonneplan_token.json op in dezelfde map.
Kopieer/plaats dat bestand in de Domoticz-pluginmap indien nodig.

De nieuwe Zonneplan-login stuurt een zescijferige code per e-mail.
IMAP en het automatisch aanklikken van een link zijn niet meer nodig.
"""

import base64
import hashlib
import json
import os
import secrets
import sys
import time
import urllib.error
import urllib.request

BASE_URL = "https://app-api.zonneplan.nl"
TOKEN_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "zonneplan_token.json",
)

APP_VERSION = "5.10.1"
INTEGRATION_VERSION = "domoticz-zonneplan/1.0.0"

HEADERS = {
    "Content-Type": "application/json;charset=utf-8",
    "Accept": "application/json",
    "x-app-version": APP_VERSION,
    "x-app-environment": "production",
    "x-ha-integration": INTEGRATION_VERSION,
    "User-Agent": INTEGRATION_VERSION,
}


class ApiError(Exception):
    """API-fout met HTTP-status en eventueel antwoord van de server."""

    def __init__(self, status, message, body=None):
        super().__init__(message)
        self.status = status
        self.body = body


def _decode_json(raw):
    if not raw:
        return {}
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {"raw_response": raw.decode("utf-8", errors="replace")}


def request_json(method, path, payload=None, expected_statuses=()):
    """Voer een JSON API-aanvraag uit en geef (status, JSON) terug."""
    url = BASE_URL + path
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers=HEADERS,
        method=method,
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            status = response.status
            body = _decode_json(response.read())
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        body = _decode_json(raw)
        if exc.code in expected_statuses:
            return exc.code, body
        detail = body.get("message") or body.get("error") or str(body)
        raise ApiError(exc.code, f"HTTP {exc.code}: {detail}", body) from exc
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        raise ApiError(None, f"Netwerkfout bij {url}: {reason}") from exc
    except TimeoutError as exc:
        raise ApiError(None, f"Time-out bij {url}") from exc

    if status not in expected_statuses and not (200 <= status < 300):
        raise ApiError(status, f"HTTP {status}", body)
    return status, body


def generate_pkce_pair():
    """Genereer een verse PKCE-verifier en bijbehorende S256-challenge."""
    verifier = secrets.token_urlsafe(96)[:128]
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def ask_nonempty(prompt, default=None):
    if default:
        answer = input(f"{prompt} [{default}]: ").strip()
        return answer or default
    while True:
        answer = input(f"{prompt}: ").strip()
        if answer:
            return answer
        print("Dit veld mag niet leeg zijn.")


def request_email_code(email_addr, source_name, verifier, challenge):
    """Start de login. HTTP 403 met otp_required=true is hierbij normaal."""
    payload = {
        "response_type": "code",
        "email": email_addr,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "source_name": source_name[:255],
    }

    print("\nAanmeldcode aanvragen bij Zonneplan...")
    status, response = request_json(
        "POST",
        "/oauth/authorize-challenge",
        payload,
        expected_statuses=(403,),
    )

    # De API gebruikt HTTP 403 als normale indicatie dat de e-mailcode nodig is.
    if not response.get("otp_required") or not response.get("auth_session"):
        detail = response.get("message") or response.get("error") or response
        raise ApiError(
            status,
            "Zonneplan gaf geen geldige OTP-sessie terug: " + str(detail),
            response,
        )

    print("Zonneplan heeft de aanmeldcode aangevraagd.")
    print(f"Controleer de inbox van: {email_addr}")
    print("Voer de zescijferige code uit de e-mail hieronder in.")
    return response["auth_session"]


def submit_code_and_get_tokens(auth_session, otp, verifier):
    """Wissel de e-mailcode in voor een autorisatiecode en vervolgens tokens."""
    _, response = request_json(
        "POST",
        "/oauth/authorize-challenge",
        {"auth_session": auth_session, "otp": otp},
    )

    authorization_code = response.get("authorization_code")
    if not authorization_code:
        raise ApiError(
            200,
            "Zonneplan gaf geen authorization_code terug: " + str(response),
            response,
        )

    print("E-mailcode geaccepteerd. Toegangstokens aanvragen...")
    _, token_response = request_json(
        "POST",
        "/oauth/token",
        {
            "grant_type": "authorization_code",
            "code": authorization_code,
            "code_verifier": verifier,
        },
    )

    # Sommige API-responses bevatten tokens direct; ondersteun ook een data-wrapper.
    token_data = token_response.get("data", token_response)
    if not isinstance(token_data, dict) or not token_data.get("access_token"):
        raise ApiError(
            200,
            "Geen access_token ontvangen: " + str(token_response),
            token_response,
        )
    return token_data


def verify_token(access_token):
    """Controleer het token en haal de accountverbindingen op."""
    headers = dict(HEADERS)
    headers["Authorization"] = f"Bearer {access_token}"
    req = urllib.request.Request(BASE_URL + "/user-accounts/me", headers=headers)

    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return _decode_json(response.read())
    except urllib.error.HTTPError as exc:
        raw = _decode_json(exc.read())
        raise ApiError(
            exc.code,
            f"Token ontvangen, maar accountcontrole mislukte (HTTP {exc.code}): {raw}",
            raw,
        ) from exc
    except urllib.error.URLError as exc:
        raise ApiError(
            None,
            f"Token ontvangen, maar accountcontrole mislukte door een netwerkfout: {exc}",
        ) from exc


def save_tokens(token_data, email_addr):
    token_data["email"] = email_addr
    token_data["obtained_at"] = time.time()

    # Schrijf eerst naar een tijdelijk bestand om een halfgeschreven JSON-bestand
    # te voorkomen als het proces wordt onderbroken.
    temp_file = TOKEN_FILE + ".tmp"
    with open(temp_file, "w", encoding="utf-8") as handle:
        json.dump(token_data, handle, indent=2)
        handle.write("\n")
    os.replace(temp_file, TOKEN_FILE)


def main():
    print("=== Zonneplan Domoticz Plugin - OAuth/PKCE setup ===\n")
    print("Deze versie gebruikt de nieuwe login met een zescijferige e-mailcode.")
    print("Je Gmail-wachtwoord of IMAP-appwachtwoord is hiervoor niet nodig.\n")

    email_addr = ask_nonempty("E-mailadres van je Zonneplan-account")
    instance_name = ask_nonempty(
        "Herkenbare naam voor deze Domoticz-installatie",
        "Domoticz Windows PC",
    )
    source_name = f"Domoticz Zonneplan {INTEGRATION_VERSION} - {instance_name}"

    verifier, challenge = generate_pkce_pair()

    try:
        auth_session = request_email_code(
            email_addr,
            source_name,
            verifier,
            challenge,
        )

        otp = ask_nonempty("Zescijferige code uit de Zonneplan-e-mail")
        otp = "".join(ch for ch in otp if ch.isdigit())
        if len(otp) != 6:
            print("Fout: de code moet uit precies 6 cijfers bestaan.")
            return 1

        token_data = submit_code_and_get_tokens(auth_session, otp, verifier)
        token_data["email"] = email_addr
        token_data["obtained_at"] = time.time()

        print("Toegangstoken ontvangen. Account controleren...")
        account = verify_token(token_data["access_token"])
        account_data = account.get("data", account)
        connections = account_data.get("connections", [])

        save_tokens(token_data, email_addr)
        print(f"\nTokens opgeslagen in:\n  {TOKEN_FILE}")
        print(f"Accountcontrole geslaagd; {len(connections)} verbinding(en) gevonden.")

        for connection in connections:
            for contract in connection.get("contracts", []):
                contract_type = contract.get("contract_type", "onbekend")
                contract_uuid = contract.get("uuid", "")
                print(f"  - {contract_type} ({contract_uuid[:16]}...)")

        if not token_data.get("refresh_token"):
            print(
                "\nLET OP: de API heeft geen refresh_token teruggegeven. "
                "Automatisch vernieuwen kan dan mogelijk niet werken."
            )

        print("\nAuthenticatie voltooid.")
        print("Plaats zonneplan_token.json in de map van de Domoticz-plugin")
        print("als dit script niet rechtstreeks in die map staat.")
        return 0

    except ApiError as exc:
        print(f"\nFOUT: {exc}")
        if exc.status == 400:
            print("Controleer de ingevoerde code en probeer opnieuw een nieuwe code aan te vragen.")
        elif exc.status == 401:
            print("De aanmelding is geweigerd. Controleer je account en probeer opnieuw.")
        elif exc.status == 404:
            print("De server meldt dat het endpoint niet bestaat. Controleer of de API-flow nog actueel is.")
        elif exc.status == 429:
            print("Er zijn te veel aanvragen gedaan. Wacht even voordat je opnieuw probeert.")
        print("\nEr is geen tokenbestand overschreven als de setup niet is voltooid.")
        return 1
    except KeyboardInterrupt:
        print("\nAfgebroken door gebruiker.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
