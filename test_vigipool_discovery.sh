#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [[ ! -f "custom_components/vigipool/discovery.py" ]]; then
    echo "ERREUR : impossible de trouver le module discovery.py."
    exit 1
fi

echo
echo "============================================================"
echo "          DIAGNOSTIC DISCOVERY VIGIPOOL"
echo "============================================================"
echo
echo "Projet : $SCRIPT_DIR"
echo "Date   : $(date '+%d/%m/%Y %H:%M:%S')"
echo

python3 - <<'PYTHON'
import asyncio
import ipaddress
import subprocess
import sys
import time

try:
    from custom_components.vigipool.discovery import (
        get_local_ip_ranges,
        async_scan_network,
        async_check_vigipool_http_signature,
        async_probe_vigipool_broker,
    )
    from custom_components.vigipool.const import DEFAULT_PORT
except Exception as err:
    print(f"ERREUR : impossible de charger la découverte Vigipool : {err}")
    sys.exit(1)


def print_section(title):
    print()
    print("=" * 65)
    print(f" {title}")
    print("=" * 65)


def show_interfaces():
    print_section("INTERFACES RESEAU")

    try:
        result = subprocess.run(
            ["ip", "-o", "-4", "addr", "show", "scope", "global"],
            capture_output=True,
            text=True,
            check=True,
        )

        for line in result.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 4:
                interface = parts[1]
                address = parts[3]
                print(f"  {interface:<20} {address}")

    except Exception as err:
        print(f"  Impossible de lire les interfaces : {err}")


async def main():
    start = time.monotonic()

    show_interfaces()

    # ---------------------------------------------------------
    # 1. Récupération des IP utilisées par l'intégration
    # ---------------------------------------------------------

    print_section("1 - ADRESSES IP A SCANNER")

    ips = get_local_ip_ranges()

    if not ips:
        print("Aucune adresse IP à scanner.")
        return 1

    print(f"Nombre d'adresses IP : {len(ips)}")

    # Regroupement par réseau pour faciliter la lecture.
    networks = {}

    for ip in ips:
        try:
            addr = ipaddress.ip_address(ip)
            networks.setdefault(addr.version, []).append(ip)
        except ValueError:
            pass

    for version, addresses in networks.items():
        print(f"IPv{version} : {len(addresses)} adresses")

    # ---------------------------------------------------------
    # 2. Recherche des serveurs HTTP
    # ---------------------------------------------------------

    print_section("2 - RECHERCHE DES SERVEURS HTTP (PORT 80)")

    http_ips = await async_scan_network(
        ips,
        port=80,
    )

    print(f"Adresses scannées : {len(ips)}")
    print(f"Serveurs HTTP trouvés : {len(http_ips)}")

    if http_ips:
        for ip in http_ips:
            print(f"  HTTP : {ip}")
    else:
        print("Aucun serveur HTTP trouvé.")
        return 0

    # ---------------------------------------------------------
    # 3. Vérification de la signature Vigipool
    # ---------------------------------------------------------

    print_section('3 - VERIFICATION HTTP : "File does not exist"')

    signature_results = await asyncio.gather(
        *(
            async_check_vigipool_http_signature(ip)
            for ip in http_ips
        )
    )

    vigipool_ips = [
        ip
        for ip, matches in zip(http_ips, signature_results)
        if matches
    ]

    rejected_ips = [
        ip
        for ip, matches in zip(http_ips, signature_results)
        if not matches
    ]

    print(f"Serveurs HTTP analysés : {len(http_ips)}")
    print(f"Signatures Vigipool : {len(vigipool_ips)}")
    print(f"Serveurs rejetés : {len(rejected_ips)}")

    for ip in vigipool_ips:
        print(f"  [VIGIPOOL] {ip} - signature valide")

    for ip in rejected_ips:
        print(f"  [REJETE]   {ip} - signature absente")

    # ---------------------------------------------------------
    # 4. Recherche des brokers MQTT
    # ---------------------------------------------------------

    print_section(f"4 - VERIFICATION MQTT (PORT {DEFAULT_PORT})")

    if not vigipool_ips:
        print("Aucune IP ne possède la signature HTTP Vigipool.")
        print("Aucune recherche MQTT ne sera effectuée.")
        return 0

    mqtt_ips = await async_scan_network(
        vigipool_ips,
        port=DEFAULT_PORT,
    )

    print(f"IP Vigipool candidates : {len(vigipool_ips)}")
    print(f"Brokers MQTT accessibles : {len(mqtt_ips)}")

    for ip in mqtt_ips:
        print(f"  MQTT ouvert : {ip}")

    # ---------------------------------------------------------
    # 5. Identification des appareils Vigipool
    # ---------------------------------------------------------

    print_section("5 - IDENTIFICATION DES APPAREILS VIGIPOOL")

    brokers = []

    for ip in mqtt_ips:
        print(f"Analyse MQTT de {ip}...")

        broker = await async_probe_vigipool_broker(
            ip,
            port=DEFAULT_PORT,
        )

        if broker is not None:
            brokers.append(broker)
            print(f"  [VALIDE] {ip} : {len(broker.devices)} appareil(s)")
        else:
            print(f"  [REJETE] {ip} : aucun topic Vigipool reconnu")

    # ---------------------------------------------------------
    # 6. Rapport final
    # ---------------------------------------------------------

    print_section("6 - RAPPORT DES APPAREILS DECOUVERTS")

    total_devices = 0

    if not brokers:
        print("Aucun broker Vigipool valide découvert.")

    for broker in brokers:
        print()
        print(f"Broker MQTT : {broker.ip}:{broker.port}")
        print(f"Appareil principal : {broker.primary_device_id}")
        print(f"Nombre d'appareils : {len(broker.devices)}")

        for device in broker.devices.values():
            total_devices += 1

            print()
            print(f"  Modèle      : {device.model}")
            print(f"  Identifiant : {device.device_id}")
            print(f"  Préfixe     : {device.prefix}")
            print(f"  MAC         : {device.mac}")
            print(f"  Description : {device.description}")

    elapsed = time.monotonic() - start

    print_section("SYNTHESE")

    print(f"Adresses IP scannées       : {len(ips)}")
    print(f"Serveurs HTTP trouvés      : {len(http_ips)}")
    print(f"Signatures Vigipool        : {len(vigipool_ips)}")
    print(f"Serveurs HTTP rejetés      : {len(rejected_ips)}")
    print(f"Ports MQTT accessibles    : {len(mqtt_ips)}")
    print(f"Brokers Vigipool validés   : {len(brokers)}")
    print(f"Appareils Vigipool trouvés : {total_devices}")
    print(f"Durée totale               : {elapsed:.2f} secondes")

    print()
    print("Diagnostic terminé.")
    print()

    return 0


try:
    sys.exit(asyncio.run(main()))
except KeyboardInterrupt:
    print("\nDiagnostic interrompu par l'utilisateur.")
    sys.exit(130)
except Exception as err:
    print(f"\nERREUR pendant le diagnostic : {err}")
    raise
PYTHON
