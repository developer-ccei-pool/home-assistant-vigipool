# CCEI Vigipool pour Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/default)
[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2024.1.0+-blue.svg)](https://www.home-assistant.io/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/Tests-Passing-brightgreen.svg)]()

Intégration native Home Assistant pour l'écosystème de piscine connectée **CCEI Vigipool** (Tild VP, Ofix VP, Phileo VP, Daisy pH/OX, Antea, Lynx VP, VigiBrio, VigiW@tt).

Cette intégration communique **directement en local** avec le serveur MQTT hébergé par les équipements Vigipool. Elle ne nécessite **aucun cloud**, **aucun pont MQTT intermédiaire (bridge)**, **aucun script externe** ni modification du système Home Assistant.

---

## Sommaire

1. [Présentation de Vigipool](#1-présentation-de-vigipool)
2. [Équipements compatibles](#2-équipements-compatibles)
3. [Fonctionnalités disponibles](#3-fonctionnalités-disponibles)
4. [Prérequis](#4-prérequis)
5. [Installation via HACS](#5-installation-via-hacs)
6. [Ajout de l'intégration dans Home Assistant](#6-ajout-de-lintégration-dans-home-assistant)
7. [Découverte automatique des équipements](#7-découverte-automatique-des-équipements)
8. [Configuration & Options](#8-configuration--options)
9. [Limitations connues](#9-limitations-connues)
10. [Dépannage & Diagnostic](#10-dépannage--diagnostic)

---

## 1. Présentation de Vigipool

**Vigipool** est la solution d'équipements connectés pour piscine conçue et fabriquée par **CCEI** (France). Elle permet de superviser, automatiser et piloter tous les aspects du bassin :
- Filtration et éclairage (coffrets Tild VP, passerelle AnteaM).
- Mesure et analyse de l'eau en temps réel (Ofix VP, AnteaOX).
- Traitement automatisé et régulation pH / désinfectant ORP (Phileo VP, Daisy pH, Daisy OX, Lynx VP).
- Projecteurs subaquatiques LED RGB (VigiBrio x312).
- Mesure de la consommation électrique (VigiW@tt).

L'intégration Home Assistant Vigipool se connecte directement au bus local MQTT diffusé par vos équipements, assurant un temps de réponse instantané (*Local Push*) et une indépendance totale vis-à-vis des serveurs cloud.

---

## 2. Équipements compatibles

| Préfixe MQTT | Nom commercial | Rôle de l'équipement | Entités prises en charge |
|---|---|---|---|
| `tild` | **Tild VP** | Coffret électrique connecté pour filtration et éclairage | Température de l'eau, interrupteur de filtration, éclairage (ON/OFF, luminosité), commande auxiliaire, RSSI, numéro de série |
| `ziphox` | **Ofix VP** | Analyseur d'eau connecté / chambre de mesure | Valeur du pH, potentiel Redox / ORP, température de l'eau, capteur de débit d'eau, RSSI |
| `phileox` | **Phileo VP** | Régulation et dosage automatique du pH | Mesure pH, consigne pH réglable, volume injecté sur 24h et cumulé, volume du bidon, seuil max 24h, capteur d'injection, versions matérielle & logicielle |
| `daisyph` | **Daisy pH** | Pompe doseuse pH | Consigne pH, état d'injection, volumes injectés (24h et total), paramétrage du bidon |
| `daisyox` | **Daisy OX** | Pompe doseuse désinfectant / chlore liquide (ORP) | Consigne Redox / ORP, détection d'injection, volume 24h, volume du bidon, seuil max 24h |
| `anteam` | **AnteaM** | Antenne radio connectée & contrôleur central | Température, ORP, consigne ORP, sélecteurs de modes (Filtration, Éclairage, Aux 1, Aux 2 : `OFF`, `ON`, `PROG`, `AUTO`) |
| `anteaox` | **AnteaOX** | Émetteur de mesure ORP | Mesure ORP (mV), capteur de débit d'eau |
| `anteavs` | **AnteaVS** | Contrôleur pour pompe à vitesse variable | Vitesse de rotation, sélection du mode de filtration |
| `lynx` | **Lynx VP** | Distributeur de produit de traitement | Détection d'injection en temps réel, volumes injectés (24h et total) |
| `x312` | **VigiBrio** | Contrôleur d'éclairage LED RGB | Allumage/extinction, luminosité (0-100%), sélection des 15 ambiances lumineuses CCEI, vitesse d'effet, minuterie d'éclairage |
| `vigiwatt` | **VigiW@tt** | Moniteur d'énergie électrique | Puissance instantanée (W), tension (V), courant (A), fréquence (Hz), facteur de puissance (%), consommation |
| `vigipool` | **Passerelle Vigipool** | Hub / Passerelle de communication | État de la connexion locale, nombre d'équipements actifs, horodatage de dernière réception |

---

## 3. Fonctionnalités disponibles

- **Lecture temps réel en Local Push** : Réception immédiate des données publiées par vos équipements sans interrogation polling intempestive.
- **Création dynamique des appareils (Device Registry)** : Chaque appareil physique Vigipool (Tild, Ofix, Phileo...) dispose de sa propre fiche appareil dans Home Assistant, rattachée à la passerelle via la liaison *via_device*.
- **Détection des nouveaux modules à chaud** : Lorsqu'un nouvel équipement est allumé ou associé au bus, Home Assistant le détecte et crée ses entités instantanément sans redémarrage.
- **Pilotage complet** :
  - Interrupteurs pour la filtration et les sorties auxiliaires.
  - Variateurs et effets lumineux pour les projecteurs Tild et VigiBrio.
  - Consignes numériques ajustables pour le pH et le Redox/ORP.
  - Sélecteurs de mode de fonctionnement (`OFF`, `ON`, `PROG`, `AUTO`).
  - Minuteries d'éclairage paramétrables par pas de 15 minutes.
- **Protection contre les valeurs erronées** : Les codes sentinelles de sondes déconnectées (ex : `65534`, `65535`) sont automatiquement convertis en état `unavailable` afin d'éviter tout déclenchement anormal de vos automatisations.
- **Boutons de maintenance** :
  - *Reconnexion passerelle* : Relance la session réseau MQTT.
  - *Rafraîchir les données* : Réabonne et demande l'état complet des équipements.
- **Support des diagnostics Home Assistant** : Téléchargement en un clic de l'état complet du système pour faciliter le support technique.
- **Traductions bilingues** : Interface et entités intégralement traduites en français et en anglais.

---

## 4. Prérequis

1. **Home Assistant** : Version `2024.1.0` ou plus récente.
2. **HACS** : Installé et opérationnel sur votre instance Home Assistant.
3. **Réseau local** : Votre serveur Home Assistant et vos équipements Vigipool doivent être connectés au même réseau local (ou être mutuellement joignables via routage). Le port TCP `1883` doit être ouvert.

---

## 5. Installation via HACS

Pour installer l'intégration depuis HACS en tant que dépôt personnalisé :

1. Dans Home Assistant, ouvrez **HACS**.
2. Allez dans **Intégrations**.
3. Cliquez sur le menu **⋮** (trois points verticaux en haut à droite) puis sur **Dépôts personnalisés**.
4. Renseignez les informations suivantes :
   - **URL** : `https://github.com/developer-ccei-pool/home-assistant-vigipool`
   - **Catégorie** : `Integration`
5. Cliquez sur **Ajouter**.
6. Recherchez **CCEI Vigipool** dans la liste des intégrations HACS, puis cliquez sur **Télécharger**.
7. **Redémarrez Home Assistant** (Paramètres → Système → Redémarrer).

Les futures mises à jour de l'intégration vous seront ensuite directement notifiées dans HACS.

---

## 6. Ajout de l'intégration dans Home Assistant

Après le redémarrage de Home Assistant :

1. Rendez-vous dans **Paramètres** → **Appareils et services** → **Ajouter une intégration**.
2. Recherchez **CCEI Vigipool** et sélectionnez-le.
3. L'assistant de configuration vous propose deux modes :
   - **Recherche automatique (recommandé)** : Home Assistant analyse votre réseau local et détecte automatiquement votre boîtier Vigipool.
   - **Saisie manuelle de l'adresse IP** : Utile si votre équipement est situé sur un VLAN ou un sous-réseau spécifique.
4. Sélectionnez l'équipement découvert dans la liste puis validez : vos appareils et l'ensemble de leurs entités sont immédiatement disponibles !

---

## 7. Découverte automatique des équipements

Le processus de détection automatique est entièrement asynchrone et sécurisé :

```
[Home Assistant]
       │
       ├─► 1. Détection des interfaces réseau locales (IPv4 /24)
       │
       ├─► 2. Balayage asynchrone ultra-rapide du port 1883
       │      (concurrence contrôlée par sémaphore, sans bloquer la boucle d'événements)
       │
       ├─► 3. Sondage d'identification du protocole Vigipool
       │      • Connexion temporaire au serveur MQTT
       │      • Validation des topics caractéristiques (<appareil>_<MAC>/...)
       │      • Rejet automatique des serveurs MQTT tiers (Mosquitto, Zigbee2MQTT...)
       │
       └─► 4. Affichage des équipements Vigipool prêts à être configurés
```

---

## 8. Configuration & Options

### Options de redécouverte périodique

Une fois l'intégration configurée, vous pouvez ajuster ses paramètres :
1. Allez dans **Paramètres** → **Appareils et services** → **Vigipool** → **Configurer**.
2. **Intervalle de redécouverte périodique (secondes)** : Par défaut `300` secondes (5 minutes). Si l'équipement Vigipool change d'adresse IP (renouvellement de bail DHCP), l'intégration réanalysera le réseau en arrière-plan pour mettre à jour la configuration en toute transparence. Définissez à `0` pour désactiver ce comportement.

### Reconfiguration d'IP

Si vous changez manuellement votre réseau, vous pouvez modifier l'adresse IP à tout moment via **Paramètres** → **Appareils et services** → **Vigipool** → **⋮** → **Reconfigurer**.

---

## 9. Limitations connues

- **Accès réseau local direct** : L'intégration communique en direct via MQTT local. Les équipements doivent être joignables sur le port `1883`.
- **Mises à jour de microprogramme via l'application mobile** : Lorsque vous effectuez une mise à jour logicielle (*firmware update*) d'un appareil Vigipool depuis l'application mobile officielle en Bluetooth ou Wi-Fi direct, la connexion MQTT locale est temporairement suspendue par l'appareil. Dès la fin de la mise à jour, l'intégration se reconnecte automatiquement.
- **Baux DHCP variables** : Bien que l'intégration intègre un mécanisme de détection automatique des changements d'adresse IP, il est vivement recommandé d'assigner une adresse IP statique ou une réservation DHCP à votre boîtier Vigipool dans votre routeur/box internet.

---

## 10. Dépannage & Diagnostic

### Télécharger les diagnostics

En cas de problème :
1. Allez dans **Paramètres** → **Appareils et services** → **Vigipool**.
2. Cliquez sur le menu **⋮** de l'entrée et choisissez **Télécharger les diagnostics**.
3. Ce fichier JSON contient l'état de la connexion, les appareils reconnus et les dernières trames reçues.

### Activer les journaux détaillés

Pour analyser en détail les trames échangées, ajoutez ces lignes dans votre fichier `configuration.yaml` :

```yaml
logger:
  default: info
  logs:
    custom_components.vigipool: debug
```

---

## Licence

Ce projet est distribué sous licence [MIT](LICENSE).

*Vigipool, Tild, Ofix, Phileo, Daisy, Antea, Lynx, VigiBrio et VigiW@tt sont des marques déposées de CCEI. Ce projet open-source communautaire est développé indépendamment.*
