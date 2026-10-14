"""
<plugin key="ZonneplanEnergy" name="Zonneplan Energie" author="rayray4105"
        version="3.2.0" externallink="https://github.com/rayray4105/domoticz-zonneplan">
    <description>
        <h2>Zonneplan Energie</h2><br/>
        Integreert Zonneplan thuisbatterij (Nexus) en elektriciteitscontract in Domoticz,
        inclusief ondersteuning voor het Energy Dashboard.<br/><br/>
        <b>Eerste gebruik:</b> voer <i>setup_auth.py</i> uit en kopieer
        <i>zonneplan_token.json</i> naar de plugin-map.<br/><br/>
        Niet alle devices zijn actief — activeer ze via Setup &gt; Devices indien gewenst.
    </description>
    <params>
        <param field="Mode1" label="Polling interval" width="150px" required="true">
            <options>
                <option label="1 minuut" value="60" default="true"/>
                <option label="2 minuten" value="120"/>
                <option label="5 minuten" value="300"/>
            </options>
        </param>
        <param field="Mode6" label="Debug" width="100px">
            <options>
                <option label="Nee" value="0" default="true"/>
                <option label="Ja" value="1"/>
            </options>
        </param>
    </params>
</plugin>
"""

import Domoticz
import json
import os
import time
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone

BASE_URL = "https://app-api.zonneplan.nl"
PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
TOKEN_FILE = os.path.join(PLUGIN_DIR, "zonneplan_token.json")

HEADERS = {
    "Content-Type": "application/json;charset=utf-8",
    "x-app-version": "5.10.1",
    "x-app-environment": "production",
    "x-ha-integration": "domoticz-zonneplan/3.0.0",
    "User-Agent": "domoticz-zonneplan/3.0.0",
}

# ============================================================
# Device unit nummers
# ============================================================

# --- Batterij (1-30) ---
UNIT_SOC            = 1
UNIT_POWER          = 2
UNIT_CHARGED        = 3
UNIT_DISCHARGED     = 4
UNIT_STATE          = 5
UNIT_INVERTER       = 6
UNIT_MODEL          = 7
UNIT_CYCLES         = 8
UNIT_LAST_MEAS      = 9
UNIT_FIRST_MEAS     = 10
UNIT_BACKUP_CAP     = 11
UNIT_TODAY_EUR      = 12
UNIT_AVG_EUR        = 13
UNIT_TOTAL_EUR      = 14
UNIT_THIS_MONTH_EUR = 15
UNIT_LAST_MONTH_EUR = 16
UNIT_THIS_YEAR_EUR  = 17
UNIT_LAST_YEAR_EUR  = 18
UNIT_DYN_CHARGING   = 20
UNIT_DYN_LB_OVL     = 21
UNIT_DYN_LB_ON      = 22
UNIT_MANUAL_CTRL    = 23
UNIT_GRID_CONG      = 24
UNIT_HOME_OPT_ACT   = 25
UNIT_HOME_OPT_ON    = 26
UNIT_SELF_CONS      = 27
UNIT_BACKUP_ACT     = 28
UNIT_CTRL_MODE      = 30

# --- Elektriciteit (40-70) ---
UNIT_ELEC_TARIFF        = 40   # Huidig tarief (€/kWh)
UNIT_ELEC_TARIFF_GROUP  = 41   # Huidige tariefgroep
UNIT_ELEC_USAGE         = 42   # Huidig verbruik (W)   [standaard uitgeschakeld]
UNIT_ELEC_USAGE_AT      = 43   # Verbruik gemeten om   [standaard uitgeschakeld]
UNIT_ELEC_SUSTAIN       = 44   # Duurzaamheidsscore (%)
UNIT_ELEC_STATUS_MSG    = 45   # Statusbericht         [standaard uitgeschakeld]
UNIT_ELEC_STATUS_TIP    = 46   # Statustip
# Forecast tarieven uur +1 t/m +8                       [standaard uitgeschakeld]
UNIT_ELEC_FC_T1         = 47
UNIT_ELEC_FC_T2         = 48
UNIT_ELEC_FC_T3         = 49
UNIT_ELEC_FC_T4         = 50
UNIT_ELEC_FC_T5         = 51
UNIT_ELEC_FC_T6         = 52
UNIT_ELEC_FC_T7         = 53
UNIT_ELEC_FC_T8         = 54
# Forecast tariefgroepen uur +1 t/m +8                  [standaard uitgeschakeld]
UNIT_ELEC_FC_G1         = 55
UNIT_ELEC_FC_G2         = 56
UNIT_ELEC_FC_G3         = 57
UNIT_ELEC_FC_G4         = 58
UNIT_ELEC_FC_G5         = 59
UNIT_ELEC_FC_G6         = 60
UNIT_ELEC_FC_G7         = 61
UNIT_ELEC_FC_G8         = 62
# Gas dagprijs
UNIT_GAS_TARIFF         = 63   # Huidig gastarief (€/m³)

# Eenheden voor Custom-sensoren (worden als Options meegegeven)
CUSTOM_UNITS = {
    UNIT_ELEC_TARIFF:    "€/kWh",
    UNIT_ELEC_FC_T1:     "€/kWh",
    UNIT_ELEC_FC_T2:     "€/kWh",
    UNIT_ELEC_FC_T3:     "€/kWh",
    UNIT_ELEC_FC_T4:     "€/kWh",
    UNIT_ELEC_FC_T5:     "€/kWh",
    UNIT_ELEC_FC_T6:     "€/kWh",
    UNIT_ELEC_FC_T7:     "€/kWh",
    UNIT_ELEC_FC_T8:     "€/kWh",
    UNIT_TODAY_EUR:      "€",
    UNIT_AVG_EUR:        "€",
    UNIT_TOTAL_EUR:      "€",
    UNIT_THIS_MONTH_EUR: "€",
    UNIT_LAST_MONTH_EUR: "€",
    UNIT_THIS_YEAR_EUR:  "€",
    UNIT_LAST_YEAR_EUR:  "€",
    UNIT_CYCLES:         "cycli",
    UNIT_BACKUP_CAP:     "%",
    UNIT_GAS_TARIFF:     "€/m³",
}


def _custom_options(unit):
    if unit in CUSTOM_UNITS:
        return {"Custom": "1;" + CUSTOM_UNITS[unit]}
    return None


BATTERY_STATE_NL = {
    "charging":    "Opladen",
    "discharging": "Ontladen",
    "idle":        "Inactief",
    "standby":     "Stand-by",
    "full":        "Vol",
    "empty":       "Leeg",
}

TARIFF_GROUP_NL = {
    "off_peak": "Dal",
    "peak":     "Piek",
    "normal":   "Normaal",
    "low":      "Laag",
    "high":     "Hoog",
}


class BasePlugin:
    def __init__(self):
        self._token = None
        self._heartbeat_count = 0
        self._poll_ticks = 2
        self._debug = False

        # Batterij
        self._battery_contract_uuid = None
        self._battery_connection_uuid = None
        self._has_battery = False

        # Elektriciteit
        self._elec_connection_uuid = None
        self._has_electricity = False
        self._last_summary_hour = -1   # tarieven alleen vernieuwen bij nieuw uur

        # Gas (dagprijs)
        self._gas_connection_uuid = None
        self._gas_contract_uuid = None
        self._has_gas = False
        self._last_gas_fetch = 0

        # Rate limiting (discussie #89): bij 429 pauzeren we minimaal 60s
        self._rate_limited_until = 0

    # ------------------------------------------------------------------
    # Domoticz lifecycle
    # ------------------------------------------------------------------

    def onStart(self):
        self._debug = Parameters["Mode6"] == "1"
        if self._debug:
            Domoticz.Debugging(1)

        try:
            self._poll_ticks = max(2, int(Parameters["Mode1"]) // 30)  # min 60s
        except (ValueError, KeyError):
            self._poll_ticks = 2

        Domoticz.Heartbeat(30)
        Domoticz.Log(f"Zonneplan plugin v3.1 gestart (poll elke {self._poll_ticks * 30}s)")

        self._create_devices()
        self._load_token()

        if self._token:
            self._discover_contracts()
            self._update_data()
        else:
            Domoticz.Error(
                "Geen token gevonden. Voer setup_auth.py uit en kopieer "
                "zonneplan_token.json naar de plugin-map."
            )

    def onStop(self):
        Domoticz.Log("Zonneplan plugin gestopt.")

    def onHeartbeat(self):
        self._heartbeat_count += 1
        if self._heartbeat_count >= self._poll_ticks:
            self._heartbeat_count = 0
            self._update_data()

    # ------------------------------------------------------------------
    # Contract detectie
    # ------------------------------------------------------------------

    @staticmethod
    def _iter_connections(me):
        """Ondersteunt zowel de oude als de huidige account-responsstructuur."""
        data = me.get("data", {}) if isinstance(me, dict) else {}
        direct = data.get("connections")
        if isinstance(direct, list):
            for conn in direct:
                yield conn
        for group in data.get("address_groups", []) or []:
            for conn in (group.get("connections", []) or []):
                yield conn

    @staticmethod
    def _contract_type(contract):
        return contract.get("contract_type") or contract.get("type") or ""

    def _discover_contracts(self):
        if not self._ensure_valid_token():
            return
        try:
            me = self._get("/user-accounts/me")
        except Exception as e:
            Domoticz.Error(f"Contract detectie mislukt: {e}")
            return

        for conn in self._iter_connections(me):
            conn_uuid = conn.get("uuid", "")
            for contract in conn.get("contracts", []):
                ctype = self._contract_type(contract)

                if ctype == "home_battery_installation" and not self._has_battery:
                    self._battery_contract_uuid = contract.get("uuid")
                    self._battery_connection_uuid = conn_uuid
                    self._has_battery = True
                    Domoticz.Log(f"Batterijcontract gevonden: {self._battery_contract_uuid[:16]}...")

                if ctype == "gas" and not self._has_gas:
                    self._gas_connection_uuid = conn_uuid
                    self._gas_contract_uuid = contract.get("uuid")
                    self._has_gas = True
                    Domoticz.Log(f"Gascontract gevonden: verbinding {conn_uuid[:16]}...")

                if ctype in ("electricity", "electricity_without_feed_in") and not self._has_electricity:
                    self._elec_connection_uuid = conn_uuid
                    self._has_electricity = True
                    Domoticz.Log(f"Elektriciteitscontract gevonden: verbinding {conn_uuid[:16]}...")

        if not self._has_battery:
            Domoticz.Log("Geen batterijcontract gevonden — batterij-devices worden overgeslagen.")
        if not self._has_electricity:
            Domoticz.Log("Geen elektriciteitscontract gevonden — elektriciteits-devices worden overgeslagen.")

    # ------------------------------------------------------------------
    # Device aanmaken
    # ------------------------------------------------------------------

    def _create_devices(self):
        # Batterij devices
        battery_specs = [
            (UNIT_SOC,            "Batterij Laadniveau",           "",         0,   0,   True),
            (UNIT_POWER,          "Batterij Vermogen",             "",         248, 1,   True),
            (UNIT_CHARGED,        "Zonneplan Opgeladen",           "",         243, 29,  True),
            (UNIT_DISCHARGED,     "Zonneplan Ontladen",            "",         243, 29,  True),
            (UNIT_STATE,          "Batterij Status",               "Text",     0,   0,   True),
            (UNIT_INVERTER,       "Inverter Status",               "Text",     0,   0,   True),
            (UNIT_MODEL,          "Batterij Model",                "Text",     0,   0,   True),
            (UNIT_CYCLES,         "Batterij Cycli",                "Custom",   0,   0,   True),
            (UNIT_LAST_MEAS,      "Laatste Meting",                "Text",     0,   0,   True),
            (UNIT_FIRST_MEAS,     "Eerste Meting",                 "Text",     0,   0,   True),
            (UNIT_BACKUP_CAP,     "Backup Capaciteit",             "Custom",   0,   0,   True),
            (UNIT_TODAY_EUR,      "Verdiend Vandaag",              "Custom",   0,   0,   True),
            (UNIT_AVG_EUR,        "Gemiddeld per Dag",             "Custom",   0,   0,   True),
            (UNIT_TOTAL_EUR,      "Totaal Verdiend",               "Custom",   0,   0,   True),
            (UNIT_THIS_MONTH_EUR, "Resultaat Deze Maand",          "Custom",   0,   0,   True),
            (UNIT_LAST_MONTH_EUR, "Resultaat Vorige Maand",        "Custom",   0,   0,   True),
            (UNIT_THIS_YEAR_EUR,  "Resultaat Dit Jaar",            "Custom",   0,   0,   True),
            (UNIT_LAST_YEAR_EUR,  "Resultaat Vorig Jaar",          "Custom",   0,   0,   True),
            (UNIT_DYN_CHARGING,   "Dynamic Charging",              "Switch",   0,   0,   True),
            (UNIT_DYN_LB_OVL,     "Load Balancing Overload",       "Switch",   0,   0,   True),
            (UNIT_DYN_LB_ON,      "Load Balancing",                "Switch",   0,   0,   True),
            (UNIT_MANUAL_CTRL,    "Handmatige Bediening",          "Switch",   0,   0,   True),
            (UNIT_GRID_CONG,      "Netcongestie",                  "Switch",   0,   0,   True),
            (UNIT_HOME_OPT_ACT,   "Home Optimalisatie Actief",     "Switch",   0,   0,   True),
            (UNIT_HOME_OPT_ON,    "Home Optimalisatie",            "Switch",   0,   0,   True),
            (UNIT_SELF_CONS,      "Zelfconsumptie",                "Switch",   0,   0,   True),
            (UNIT_BACKUP_ACT,     "Backup Stroom Actief",          "Switch",   0,   0,   True),
            (UNIT_CTRL_MODE,      "Besturingsmodus",               "Text",     0,   0,   True),
        ]

        # Elektriciteit devices (enabled=False = standaard uitgeschakeld in Domoticz)
        elec_specs = [
            (UNIT_ELEC_TARIFF,       "Huidig Tarief",              "Custom",   0,   0,   True),
            (UNIT_ELEC_TARIFF_GROUP, "Tariefgroep",                "Text",     0,   0,   True),
            (UNIT_ELEC_USAGE,        "Huidig Verbruik",            "",         248, 1,   False),
            (UNIT_ELEC_USAGE_AT,     "Verbruik Gemeten Om",        "Text",     0,   0,   False),
            (UNIT_ELEC_SUSTAIN,      "Duurzaamheidsscore",         "Percentage", 0, 0,  True),
            (UNIT_ELEC_STATUS_MSG,   "Status Bericht",             "Text",     0,   0,   False),
            (UNIT_ELEC_STATUS_TIP,   "Status Tip",                 "Text",     0,   0,   True),
            (UNIT_ELEC_FC_T1,        "Forecast Tarief +1u",        "Custom",   0,   0,   False),
            (UNIT_ELEC_FC_T2,        "Forecast Tarief +2u",        "Custom",   0,   0,   False),
            (UNIT_ELEC_FC_T3,        "Forecast Tarief +3u",        "Custom",   0,   0,   False),
            (UNIT_ELEC_FC_T4,        "Forecast Tarief +4u",        "Custom",   0,   0,   False),
            (UNIT_ELEC_FC_T5,        "Forecast Tarief +5u",        "Custom",   0,   0,   False),
            (UNIT_ELEC_FC_T6,        "Forecast Tarief +6u",        "Custom",   0,   0,   False),
            (UNIT_ELEC_FC_T7,        "Forecast Tarief +7u",        "Custom",   0,   0,   False),
            (UNIT_ELEC_FC_T8,        "Forecast Tarief +8u",        "Custom",   0,   0,   False),
            (UNIT_ELEC_FC_G1,        "Forecast Tariefgroep +1u",   "Text",     0,   0,   False),
            (UNIT_ELEC_FC_G2,        "Forecast Tariefgroep +2u",   "Text",     0,   0,   False),
            (UNIT_ELEC_FC_G3,        "Forecast Tariefgroep +3u",   "Text",     0,   0,   False),
            (UNIT_ELEC_FC_G4,        "Forecast Tariefgroep +4u",   "Text",     0,   0,   False),
            (UNIT_ELEC_FC_G5,        "Forecast Tariefgroep +5u",   "Text",     0,   0,   False),
            (UNIT_ELEC_FC_G6,        "Forecast Tariefgroep +6u",   "Text",     0,   0,   False),
            (UNIT_ELEC_FC_G7,        "Forecast Tariefgroep +7u",   "Text",     0,   0,   False),
            (UNIT_ELEC_FC_G8,        "Forecast Tariefgroep +8u",   "Text",     0,   0,   False),
        ]

        gas_specs = [
            (UNIT_GAS_TARIFF, "Gas Tarief", "Custom", 0, 0, True),
        ]

        for specs in [battery_specs, elec_specs, gas_specs]:
            for unit, name, typename, devtype, subtype, _enabled in specs:
                options = _custom_options(unit) if typename == "Custom" else None

                if unit not in Devices:
                    kwargs = {"Name": name, "Unit": unit}
                    if typename:
                        kwargs["TypeName"] = typename
                    else:
                        kwargs["Type"] = devtype
                        kwargs["Subtype"] = subtype
                    if options:
                        kwargs["Options"] = options
                    Domoticz.Device(**kwargs).Create()
                    Domoticz.Log(f"Device aangemaakt: {name}")

                elif options and Devices[unit].Options != options:
                    # Bestaand device: eenheid bijwerken, geschiedenis blijft behouden
                    Devices[unit].Update(
                        nValue=Devices[unit].nValue,
                        sValue=Devices[unit].sValue,
                        Options=options,
                    )
                    Domoticz.Log(f"Eenheid bijgewerkt: {name}")


    # ------------------------------------------------------------------
    # Token beheer
    # ------------------------------------------------------------------

    def _load_token(self):
        if not os.path.exists(TOKEN_FILE):
            Domoticz.Error(f"Token bestand niet gevonden: {TOKEN_FILE}")
            return
        try:
            with open(TOKEN_FILE) as f:
                self._token = json.load(f)
            Domoticz.Log("Token geladen.")
        except Exception as e:
            Domoticz.Error(f"Token laden mislukt: {e}")

    def _save_token(self):
        try:
            with open(TOKEN_FILE, "w") as f:
                json.dump(self._token, f, indent=2)
        except Exception as e:
            Domoticz.Error(f"Token opslaan mislukt: {e}")

    def _ensure_valid_token(self):
        if not self._token:
            return False
        expires_in = self._token.get("expires_in", 3600)
        obtained_at = self._token.get("obtained_at", 0)
        if (time.time() - obtained_at) < (expires_in - 300):
            return True
        Domoticz.Log("Token verlopen, vernieuwen...")
        try:
            data = self._post("/oauth/token", {
                "grant_type": "refresh_token",
                "refresh_token": self._token["refresh_token"],
            })
            self._token.update(data.get("data", data))
            self._token["obtained_at"] = time.time()
            self._save_token()
            Domoticz.Log("Token vernieuwd.")
            return True
        except Exception as e:
            Domoticz.Error(f"Token vernieuwen mislukt: {e}")
            return False

    # ------------------------------------------------------------------
    # HTTP
    # ------------------------------------------------------------------

    def _get(self, path):
        if time.time() < self._rate_limited_until:
            raise Exception("Rate limited — wacht even")
        url = BASE_URL + path
        h = dict(HEADERS)
        h["Authorization"] = f"Bearer {self._token['access_token']}"
        req = urllib.request.Request(url, headers=h)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 429:
                retry_after = int(e.headers.get("Retry-After", 60))
                self._rate_limited_until = time.time() + retry_after
                Domoticz.Error(
                    f"Zonneplan API rate limit (429) — wacht {retry_after}s voor volgende poging."
                )
            raise

    def _post(self, path, data):
        url = BASE_URL + path
        body = json.dumps(data).encode("utf-8")
        req = urllib.request.Request(url, data=body, headers=HEADERS, method="POST")
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))

    # ------------------------------------------------------------------
    # Hoofd update loop
    # ------------------------------------------------------------------

    def _update_data(self):
        if not self._ensure_valid_token():
            return

        # Herdetecteer contracts als nog niet gevonden
        if not self._has_battery and not self._has_electricity:
            self._discover_contracts()

        if self._has_battery:
            self._update_battery()

        if self._has_electricity:
            self._update_electricity()

        if self._has_gas:
            self._update_gas()

    # ==================================================================
    # GAS (alleen dagprijs)
    # ==================================================================

    def _update_gas(self):
        """Haalt de gasdagprijs op. De prijs wijzigt maar één keer per dag,
        dus hoogstens elke 30 minuten verversen."""
        if time.time() - self._last_gas_fetch < 1800:
            return
        try:
            response = self._get(
                f"/api/consumer-prices/charts/gas-daily?connection_uuid={self._gas_connection_uuid}"
            )
        except Exception as e:
            Domoticz.Error(f"Gasprijs API fout: {e}")
            return
        self._last_gas_fetch = time.time()

        data = response.get("data", {}) if isinstance(response, dict) else {}
        prices = (data.get("chart", {}).get("series", {}).get("prices", [])
                  if isinstance(data, dict) else [])
        now_utc = datetime.now(timezone.utc)

        for item in prices:
            try:
                start = datetime.fromisoformat(item["start_date"].replace("Z", "+00:00"))
                end = datetime.fromisoformat(item["end_date"].replace("Z", "+00:00"))
                amount = item["price_tax_included"]["amount"]
            except (KeyError, TypeError, ValueError):
                continue
            if start <= now_utc < end:
                price = float(amount) * 0.0000001   # zelfde schaal als elektriciteit
                Devices[UNIT_GAS_TARIFF].Update(nValue=0, sValue=f"{price:.4f}")
                if self._debug:
                    Domoticz.Log(f"[Gas] dagprijs {start.isoformat()} t/m {end.isoformat()}: €{price:.4f}/m³")
                return

        if self._debug:
            Domoticz.Log("[Gas] geen prijs gevonden voor het huidige moment.")

    # ==================================================================
    # BATTERIJ
    # ==================================================================

    def _update_battery(self):
        try:
            me = self._get("/user-accounts/me")
        except Exception as e:
            Domoticz.Error(f"Batterij API fout: {e}")
            return

        for conn in self._iter_connections(me):
            if conn.get("uuid") != self._battery_connection_uuid:
                continue
            for contract in conn.get("contracts", []):
                if self._contract_type(contract) == "home_battery_installation":
                    meta = contract.get("meta", {})
                    self._update_battery_sensors(meta)
                    self._update_battery_binary(meta)
                    self._update_battery_charts()
                    self._update_control_mode()
                    return

    def _update_battery_sensors(self, meta):
        if self._debug:
            Domoticz.Log(f"battery meta: {json.dumps(meta)}")

        def get(key, factor=1):
            v = meta.get(key)
            return round(float(v) * factor, 4) if v is not None else None

        soc    = get("state_of_charge", 0.1)
        power  = get("power_ac")
        prod   = get("production_day", 0.001)
        deliv  = get("delivery_day", 0.001)
        today  = get("total_day", 0.0000001)
        avg    = get("average_day", 0.0000001)
        total  = get("total_earned", 0.0000001)
        cycles = get("cycle_count")
        backup = get("backup_power_usable_capacity_wh")

        if soc    is not None: Devices[UNIT_SOC].Update(nValue=0, sValue=str(soc))
        if power  is not None: Devices[UNIT_POWER].Update(nValue=0, sValue=f"{round(power)};0")
        if prod   is not None: Devices[UNIT_CHARGED].Update(nValue=0, sValue=f"0;{prod}")
        if deliv  is not None: Devices[UNIT_DISCHARGED].Update(nValue=0, sValue=f"0;{deliv}")
        if today  is not None: Devices[UNIT_TODAY_EUR].Update(nValue=0, sValue=str(round(today, 2)))
        if avg    is not None: Devices[UNIT_AVG_EUR].Update(nValue=0, sValue=str(round(avg, 2)))
        if total  is not None: Devices[UNIT_TOTAL_EUR].Update(nValue=0, sValue=str(round(total, 2)))
        if cycles is not None: Devices[UNIT_CYCLES].Update(nValue=0, sValue=str(int(cycles)))
        if backup is not None: Devices[UNIT_BACKUP_CAP].Update(nValue=0, sValue=str(int(backup)))

        battery_state = meta.get("battery_state", "")
        state_nl = BATTERY_STATE_NL.get(battery_state, battery_state or "Onbekend")
        Devices[UNIT_STATE].Update(nValue=0, sValue=state_nl)

        inverter = meta.get("inverter_state") or "Onbekend"
        Devices[UNIT_INVERTER].Update(nValue=0, sValue=inverter)

        model = meta.get("host_device_model_name")
        if model:
            Devices[UNIT_MODEL].Update(nValue=0, sValue=str(model))

        last = meta.get("last_measured_at")
        if last:
            Devices[UNIT_LAST_MEAS].Update(nValue=0, sValue=str(last))

        first = meta.get("first_measured_at")
        if first:
            Devices[UNIT_FIRST_MEAS].Update(nValue=0, sValue=str(first))

        Domoticz.Log(
            f"[Batterij] SoC: {soc}% | {power}W | "
            f"Opgeladen: {prod}kWh | Ontladen: {deliv}kWh | {state_nl}"
        )

    def _update_battery_binary(self, meta):
        binary_map = {
            UNIT_DYN_CHARGING:  "dynamic_charging_enabled",
            UNIT_DYN_LB_OVL:   "load_balancing_overload_active",
            UNIT_DYN_LB_ON:    "load_balancing_enabled",
            UNIT_MANUAL_CTRL:  "manual_control_enabled",
            UNIT_GRID_CONG:    "grid_congestion_active",
            UNIT_HOME_OPT_ACT: "home_optimization_active",
            UNIT_HOME_OPT_ON:  "home_optimization_enabled",
            UNIT_SELF_CONS:    "self_consumption_enabled",
            UNIT_BACKUP_ACT:   "backup_power_active",
        }
        for unit, key in binary_map.items():
            val = meta.get(key)
            if val is not None and unit in Devices:
                Devices[unit].Update(nValue=1 if val else 0, sValue="On" if val else "Off")

    def _update_battery_charts(self):
        if not self._battery_contract_uuid:
            return
        try:
            data = self._get(
                f"/contracts/{self._battery_contract_uuid}/home_battery_installation/charts/year"
            )
            charts = data.get("data", {})

            def eur(section):
                v = charts.get(section, {}).get("total_result")
                return round(float(v) * 0.0000001, 2) if v is not None else None

            vals = {
                UNIT_THIS_MONTH_EUR: eur("this_month"),
                UNIT_LAST_MONTH_EUR: eur("last_month"),
                UNIT_THIS_YEAR_EUR:  eur("this_year"),
                UNIT_LAST_YEAR_EUR:  eur("last_year"),
            }
            for unit, val in vals.items():
                if val is not None:
                    Devices[unit].Update(nValue=0, sValue=str(val))
        except Exception as e:
            Domoticz.Error(f"Batterij charts fout: {e}")

    def _update_control_mode(self):
        if not self._battery_contract_uuid:
            return
        try:
            data = self._get(
                f"/api/contracts/{self._battery_contract_uuid}/home-battery/control-mode"
            )
            mode = data.get("data", {}).get("control_mode") or ""
            if mode:
                Devices[UNIT_CTRL_MODE].Update(nValue=0, sValue=str(mode))
        except Exception as e:
            Domoticz.Error(f"Control mode fout: {e}")

    # ==================================================================
    # ELEKTRICITEIT
    # ==================================================================

    def _update_electricity(self):
        try:
            data = self._get(f"/connections/{self._elec_connection_uuid}/summary")
        except Exception as e:
            Domoticz.Error(f"Elektriciteit API fout: {e}")
            return

        summary = data.get("data", {})
        if self._debug:
            Domoticz.Log(f"summary: {json.dumps(summary)}")

        now_utc = datetime.now(timezone.utc)
        current_hour = now_utc.hour

        # Gebruik (verandert vaker, altijd updaten)
        usage = summary.get("usage", {})
        if usage:
            self._update_elec_usage(usage)

        # Status (altijd updaten)
        self._update_elec_status(summary)

        # Kwartierprijzen moeten elke poll worden bijgewerkt. Gebruik geen
        # uurprijs als stilzwijgende fallback, want die wijkt af van de app.
        self._last_summary_hour = current_hour
        self._update_quarter_hour_tariff(now_utc)
        self._update_elec_groups(summary.get("price_per_hour"), now_utc)

    @staticmethod
    def _hour_prices_to_dict(items):
        """Zet price_per_hour-lijsten om naar de legacy dictionaryvorm."""
        result = {}
        for item in items or []:
            stamp = item.get("datetime") or item.get("start_date")
            if not stamp:
                continue
            try:
                dt = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
                result[f"{dt:%Y-%m-%d} {dt.hour}"] = item
            except (ValueError, TypeError):
                continue
        return result

    def _update_quarter_hour_tariff(self, now_utc):
        """Lees kwartierprijzen uit data.chart.series.prices."""
        try:
            response = self._get("/api/consumer-prices/charts/electricity-quarter-hourly")
        except Exception as e:
            if self._debug:
                Domoticz.Log(f"Kwartierprijzen niet beschikbaar; geen uurprijs-fallback toegepast: {e}")
            return False

        data = response.get("data", {}) if isinstance(response, dict) else {}
        if self._debug:
            data_keys = list(data.keys()) if isinstance(data, dict) else [type(data).__name__]
            Domoticz.Log(
                f"Kwartierprijzen API-structuur: response_keys="
                f"{list(response.keys()) if isinstance(response, dict) else type(response).__name__}, "
                f"data_keys={data_keys}"
            )
        chart = data.get("chart", data)
        if self._debug:
            if isinstance(chart, dict):
                Domoticz.Log(f"Kwartierprijzen chart-keys: {list(chart.keys())}")
                for key, value in chart.items():
                    if isinstance(value, list):
                        sample = json.dumps(value[:2], ensure_ascii=False, default=str)[:700]
                        Domoticz.Log(
                            f"Kwartierprijzen chart[{key}]: list, aantal={len(value)}, "
                            f"eerste_items={sample}"
                        )
                    elif isinstance(value, dict):
                        details = {}
                        for subkey, subvalue in value.items():
                            if isinstance(subvalue, list):
                                details[subkey] = {
                                    "type": "list", "aantal": len(subvalue),
                                    "eerste_items": subvalue[:2]
                                }
                            elif isinstance(subvalue, dict):
                                details[subkey] = {"type": "dict", "keys": list(subvalue.keys())}
                            else:
                                details[subkey] = {"type": type(subvalue).__name__}
                        sample = json.dumps(details, ensure_ascii=False, default=str)[:1000]
                        Domoticz.Log(f"Kwartierprijzen chart[{key}] structuur: {sample}")
                    else:
                        Domoticz.Log(
                            f"Kwartierprijzen chart[{key}] type: {type(value).__name__}"
                        )
            else:
                Domoticz.Log(f"Kwartierprijzen chart-type: {type(chart).__name__}")
        series = chart.get("series", []) if isinstance(chart, dict) else []
        entries = []
        # De echte API geeft chart.series als één object met daarin de lijst "prices".
        # Sommige varianten kunnen series ook als lijst van objecten teruggeven.
        if isinstance(series, dict):
            values = series.get("prices") or series.get("data") or []
            if isinstance(values, list):
                entries.extend(x for x in values if isinstance(x, dict))
        elif isinstance(series, list):
            for item in series:
                if isinstance(item, dict):
                    values = item.get("prices") or item.get("data") or []
                    if isinstance(values, list):
                        entries.extend(x for x in values if isinstance(x, dict))
        if not entries:
            entries = data.get("prices", []) if isinstance(data, dict) else []
        if not entries:
            if self._debug:
                Domoticz.Log(
                    f"Kwartierprijzen-endpoint gaf geen herkenbare prijzen terug; "
                    f"data_keys={list(data.keys()) if isinstance(data, dict) else type(data).__name__}; "
                    f"chart_type={type(chart).__name__}"
                )
            return False

        def entry_time(entry):
            stamp = entry.get("start_date") or entry.get("datetime") or entry.get("startDate")
            if not stamp:
                return None
            try:
                return datetime.fromisoformat(stamp.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                return None

        timed = [(entry_time(e), e) for e in entries]
        timed = [(dt, e) for dt, e in timed if dt is not None]
        if not timed:
            return False
        timed.sort(key=lambda pair: pair[0])

        # Selecteer uitsluitend het kwartier waarvan start <= nu < einde.
        # Gebruik expliciet end_date om te voorkomen dat een verouderd kwartier
        # wordt gekozen wanneer de API-reeks achterloopt of timestamps afwijkend zijn.
        current = None
        for start, entry in timed:
            end_stamp = entry.get("end_date") or entry.get("endDate")
            end = None
            if end_stamp:
                try:
                    end = datetime.fromisoformat(end_stamp.replace("Z", "+00:00"))
                except (ValueError, TypeError):
                    end = None
            if start <= now_utc and (end is None or now_utc < end):
                current = (start, entry)
                break

        if current is None:
            # Geen periode bevat nu: log dit en kies het eerstvolgende kwartier
            # alleen als de reeks nog in de toekomst begint. Niet stilzwijgend
            # een oude prijs als huidig publiceren.
            future = [(start, entry) for start, entry in timed if start > now_utc]
            if future:
                current = future[0]
            else:
                if self._debug:
                    Domoticz.Log(
                        f"Geen actueel kwartier gevonden: nu={now_utc.isoformat()}, "
                        f"eerste_start={timed[0][0].isoformat()}, "
                        f"laatste_start={timed[-1][0].isoformat()}"
                    )
                return False

        def amount(entry):
            value = entry.get("price_tax_included")
            if isinstance(value, dict):
                value = value.get("amount", value.get("value"))
            if value is None:
                value = entry.get("electricity_price")
            if isinstance(value, dict):
                value = value.get("amount", value.get("value"))
            try:
                number = float(value)
                # API prices commonly use 1e-7/1e-8 units; chart amounts are often €/kWh.
                if number > 10:
                    number *= 0.0000001
                return round(number, 6)
            except (ValueError, TypeError):
                return None

        # Forecast +1u t/m +8u uit dezelfde kwartierreeks (zelfde prijzen als de app)
        self._update_forecast_prices(timed, amount, now_utc)

        price = amount(current[1])
        if price is None:
            if self._debug:
                Domoticz.Log("Kwartierprijs gevonden, maar prijsveld niet herkend.")
            return False
        Devices[UNIT_ELEC_TARIFF].Update(nValue=0, sValue=f"{price:.4f}")
        group = current[1].get("tariff_group") or current[1].get("tariffGroup") or ""
        if group:
            Devices[UNIT_ELEC_TARIFF_GROUP].Update(
                nValue=0, sValue=TARIFF_GROUP_NL.get(group, group)
            )
        if self._debug:
            end_stamp = current[1].get("end_date") or current[1].get("endDate") or "onbekend"
            Domoticz.Log(
                f"[Elektriciteit] Kwartiertarief nu={now_utc.isoformat()}, "
                f"periode={current[0].isoformat()} t/m {end_stamp}: €{price}/kWh"
            )
        return True

    def _update_elec_usage(self, usage):
        value = usage.get("value")
        if value is not None:
            Devices[UNIT_ELEC_USAGE].Update(nValue=0, sValue=f"{round(float(value))};0")

        measured_at = usage.get("measured_at") or usage.get("timestamp")
        if measured_at:
            Devices[UNIT_ELEC_USAGE_AT].Update(nValue=0, sValue=str(measured_at))

        score = usage.get("sustainability_score")
        if score is not None:
            Devices[UNIT_ELEC_SUSTAIN].Update(nValue=0, sValue=str(round(float(score) * 0.1, 1)))

    def _update_elec_status(self, summary):
        # Status bericht en tip — key kan variëren; probeer meerdere paden
        msg = (summary.get("status_message")
               or summary.get("status", {}).get("message")
               or summary.get("message"))
        if msg:
            Devices[UNIT_ELEC_STATUS_MSG].Update(nValue=0, sValue=str(msg))

        tip = (summary.get("status_tip")
               or summary.get("status", {}).get("tip")
               or summary.get("tip"))
        if tip:
            Devices[UNIT_ELEC_STATUS_TIP].Update(nValue=0, sValue=str(tip))

    def _update_forecast_prices(self, timed, amount, now_utc):
        """Forecast-tarieven +1u t/m +8u: het kwartier dat dan geldt."""
        units = [
            UNIT_ELEC_FC_T1, UNIT_ELEC_FC_T2, UNIT_ELEC_FC_T3, UNIT_ELEC_FC_T4,
            UNIT_ELEC_FC_T5, UNIT_ELEC_FC_T6, UNIT_ELEC_FC_T7, UNIT_ELEC_FC_T8,
        ]
        for i, unit in enumerate(units, start=1):
            if unit not in Devices:
                continue
            target = now_utc + timedelta(hours=i)
            for start, entry in timed:
                if start <= target < start + timedelta(minutes=15):
                    price = amount(entry)
                    if price is not None:
                        Devices[unit].Update(nValue=0, sValue=f"{price:.4f}")
                    break

    def _update_elec_groups(self, price_per_hour, now_utc):
        """Tariefgroep huidig uur en forecast +1u t/m +8u (alleen in de uurprijzen)."""
        by_hour = self._hour_prices_to_dict(price_per_hour)

        def group(offset):
            t = now_utc + timedelta(hours=offset)
            grp = by_hour.get(f"{t:%Y-%m-%d} {t.hour}", {}).get("tariff_group") or ""
            return TARIFF_GROUP_NL.get(grp, grp)

        current = group(0)
        if current:
            Devices[UNIT_ELEC_TARIFF_GROUP].Update(nValue=0, sValue=current)

        units = [
            UNIT_ELEC_FC_G1, UNIT_ELEC_FC_G2, UNIT_ELEC_FC_G3, UNIT_ELEC_FC_G4,
            UNIT_ELEC_FC_G5, UNIT_ELEC_FC_G6, UNIT_ELEC_FC_G7, UNIT_ELEC_FC_G8,
        ]
        for i, unit in enumerate(units, start=1):
            grp = group(i)
            if grp and unit in Devices:
                Devices[unit].Update(nValue=0, sValue=grp)


# Domoticz entry points
_plugin = BasePlugin()

def onStart():     _plugin.onStart()
def onStop():      _plugin.onStop()
def onHeartbeat(): _plugin.onHeartbeat()
