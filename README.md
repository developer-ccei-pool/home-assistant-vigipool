# Intégration Native Home Assistant pour CCEI Vigipool

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/default)
[![Validate with Home Assistant](https://img.shields.io/badge/Home%20Assistant-Compatible-blue.svg)](https://www.home-assistant.io/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Intégration native Home Assistant dédiée exclusivement à l'écosystème de piscine connectée **CCEI Vigipool** (Tild VP, Ofix VP, Phileo VP, Daisy pH/OX, Antea, Lynx VP, VigiBrio, VigiW@tt).

Cette intégration se connecte **directement** au serveur MQTT local hébergé par votre équipement Vigipool sur votre réseau local. Elle ne nécessite **aucun script shell externe**, **aucun pont MQTT intermédiaire (bridge)**, **aucun Nmap**, **aucun sudo** ni modification du système Home Assistant.

---

## Sommaire

1. [Fonctionnalités principales](#1-fonctionnalités-principales)
2. [Équipements Vigipool compatibles](#2-équipements-vigipool-compatibles)
3. [Fonctionnement de la détection automatique](#3-fonctionnement-de-la-détection-automatique)
4. [Entités Home Assistant créées](#4-entités-home-assistant-créées)
5. [Installation](#5-installation)
   - [Installation via HACS (Recommandé)](#installation-via-hacs-recommandé)
   - [Installation manuelle](#installation-manuelle)
6. [Configuration dans Home Assistant](#6-configuration-dans-home-assistant)
7. [Architecture technique](#7-architecture-technique)
8. [Limitations connues](#8-limitations-connues)
9. [Dépannage & FAQ](#9-dépannage--faq)

---

## 1. Fonctionnalités principales

- **Détection automatique sur le réseau local** : Recherche asynchrone non-bloquante des sous-réseaux locaux pour identifier automatiquement le contrôleur Vigipool sur le port TCP 1883.
- **Identification intelligente du protocole Vigipool** : Vérifie les topics et trames MQTT caractéristiques (`tild_...`, `ziphox_...`, etc.) pour distinguer un équipement Vigipool d'un serveur MQTT tiers (Mosquitto, Zigbee2MQTT, etc.).
- **Connexion MQTT native directe** : Connexion asynchrone directe via `paho-mqtt` gérée par l'intégration, sans nécessiter de configuration dans le fichier `configuration.yaml`.
- **Découverte dynamique des équipements** : Détecte et enregistre automatiquement chaque appareil physique connecté au bus Vigipool (Tild, sonde Ofix, régulation Phileo, éclairage VigiBrio...) avec son propre périphérique (*Device*) dans le registre Home Assistant.
- **Gestion des valeurs invalides** : Convertit les sentinelles d'erreur ou d'absence de capteur (ex. `65534`, `65535`, sondes déconnectées) en états `unavailable` / `unknown` plutôt que des valeurs erronées.
- **Reconnexion et gestion des changements d'IP** : Reconnexion automatique avec backoff exponentiel et redécouverte périodique configurable pour retrouver un équipement dont l'adresse IP a changé lors d'un renouvellement DHCP.
- **Traductions complètes** : Interface de configuration et libellés d'entités traduits en français et en anglais.

---

## 2. Équipements Vigipool compatibles

L'intégration prend en charge tous les équipements de la gamme CCEI Vigipool communicant via le protocole local MQTT :

| Préfixe MQTT | Nom du produit | Description | Fonctionnalités intégrées |
|---|---|---|---|
| `tild` | **Tild VP** | Coffret de commande et filtration connecté | Température de l'eau, interrupteur de filtration, éclairage (ON/OFF et luminosité), commande auxiliaire, RSSI, numéro de série |
| `ziphox` | **Ofix VP** | Analyseur d'eau connecté / chambre de mesure | Valeur du pH, valeur ORP/Redox, température de l'eau, capteur de débit, RSSI |
| `phileox` | **Phileo VP** | Régulation et dosage pH | Mesure pH, consigne pH (curseur), volumes injectés (24h et total), volume du bidon, seuil max 24h, état d'injection, versions matérielles et logicielles |
| `daisyph` | **Daisy pH** | Pompe doseuse pH | Consigne pH, état d'injection, volume 24h et total injecté, paramétrage du bidon |
| `daisyox` | **Daisy OX** | Pompe doseuse désinfectant / chlore | Consigne ORP/Redox, volume 24h, volume du bidon, seuil max 24h |
| `anteam` | **AnteaM** | Antenne connectée & contrôleur | Température de refoulement, ORP, consigne ORP, sélecteurs de mode (Filtration, Éclairage, Aux 1, Aux 2 : OFF/ON/PROG/AUTO) |
| `anteaox` | **AnteaOX** | Émetteur de mesure ORP | Valeur ORP, capteur de débit |
| `anteavs` | **AnteaVS** | Contrôleur de pompe à vitesse variable | Identifiant pompe, vitesse de filtration, mode skimmer |
| `lynx` | **Lynx VP** | Distributeur de produit | Détection d'injection, volumes injectés 24h et cumulé |
| `x312` | **VigiBrio** | Contrôleur d'éclairage LED RGB | Allumage/extinction, variateur d'intensité (0-100%), sélection des effets de couleur (Rainbow, Ocean, Fun, etc.), vitesse d'animation, minuterie d'éclairage |
| `vigiwatt` | **VigiW@tt** | Compteur d'énergie et paramètres électriques | Puissance instantanée (W), tension (V), courant (A), fréquence (Hz), facteur de puissance (%), index d'énergie |
| `vigipool` | **Passerelle Vigipool** | Passerelle de communication | Métriques de connectivité, nombre d'équipements actifs, horodatage de dernière communication |

---

## 3. Fonctionnement de la détection automatique

Lors de l'ajout de l'intégration dans Home Assistant :

```
[Home Assistant]
       │
       ├─► 1. Découverte des interfaces et sous-réseaux locaux (RFC 1918)
       │      (limité automatiquement au /24 local pour ne pas saturer le réseau)
       │
       ├─► 2. Balayage TCP asynchrone non-bloquant sur le port 1883
       │      (parallélisme contrôlé par sémaphore, timeout court 0.8s)
       │
       ├─► 3. Sondage MQTT des serveurs ouverts
       │      • Connexion directe & écoute temporaire (1.5s)
       │      • Validation du format des topics: <appareil>_<MAC>/...
       │      • Distinction absolue entre Vigipool et brokers MQTT tiers
       │
       └─► 4. Présentation des équipements Vigipool découverts
              (avec nom du modèle, IP, appareils associés et choix direct)
```

En cas d'échec de la découverte automatique (par exemple si votre équipement est situé sur un VLAN ou sous-réseau différent), un mode de **saisie manuelle de l'adresse IP** est proposé.

---

## 4. Entités Home Assistant créées

Selon les équipements réellement présents dans votre bassin, l'intégration génère automatiquement les entités correspondantes :

### Capteurs (`sensor`)
- **Température de l'eau** (`°C`, classe `temperature`, état `measurement`)
- **Valeur du pH** (classe `ph`, état `measurement`)
- **Valeur ORP / Redox** (`mV`, état `measurement`)
- **Puissance du signal Wi-Fi** (`dBm`, classe `signal_strength`)
- **Volumes de produit injecté** (`L`, 24h et cumul total)
- **Mesures électriques VigiW@tt** : Puissance (`W`), Courant (`A`), Tension (`V`), Fréquence (`Hz`), Facteur de puissance (`%`)
- **Minuterie restante d'éclairage** (`minutes`)
- **Diagnostics de la passerelle** : État de connexion, Nombre d'appareils connectés, Dernière communication

### Capteurs binaires (`binary_sensor`)
- **Débit d'eau** (classe `running` : détecte la circulation d'eau dans la chambre de mesure)
- **Injection de produit** (classe `running` : indique si la pompe doseuse est en cours d'injection)
- **Connectivité passerelle** (classe `connectivity`)

### Interrupteurs (`switch`)
- **Filtration** : Marche / Arrêt direct de la pompe de filtration
- **Sortie Auxiliaire** : Marche / Arrêt de la sortie relais auxiliaire (projecteur, surpresseur, robot...)

### Éclairage (`light`)
- **Éclairage Tild VP** : Marche/Arrêt et réglage de luminosité
- **Projecteur VigiBrio** : Marche/Arrêt, variateur et sélection parmi les 15 effets lumineux CCEI (Rainbow, Fun, Ocean, Flamme, Parade, etc.)

### Curseurs et consignes (`number`)
- **Consigne pH** (6.8 à 7.6, pas de 0.1)
- **Consigne ORP** (300 à 990 mV, pas de 10 mV)
- **Volume max injecté en 24h** (0 à 2.0 L/jour)
- **Volume du bidon de produit** (0 à 50 L)
- **Vitesse d'animation VigiBrio** (50 à 150 %)

### Sélecteurs de mode (`select`)
- **Mode de filtration AnteaM** : `OFF`, `ON`, `PROG`, `AUTO`
- **Mode d'éclairage AnteaM** : `OFF`, `ON`, `PROG`, `AUTO`
- **Mode auxiliaire AnteaM** : `OFF`, `ON`, `PROG`, `AUTO`
- **Minuterie VigiBrio** : Sélecteur par pas de 15 minutes (`00:00` à `24:45`)

### Boutons (`button`)
- **Rafraîchir les données** : Force le réabonnement et la lecture de l'ensemble des données
- **Reconnexion passerelle** : Relance immédiatement la session de connexion MQTT

---

## 5. Installation

### Installation via HACS (Recommandé)

1. Ouvrez **HACS** dans votre barre latérale Home Assistant.
2. Cliquez sur les 3 points en haut à droite > **Dépôts personnalisés** (*Custom repositories*).
3. Ajoutez l'URL de ce dépôt :
   `https://github.com/developer-ccei-pool/home-assistant-vigipool`
4. Sélectionnez la catégorie **Intégration**.
5. Cliquez sur **Ajouter**, recherchez **CCEI Vigipool** et cliquez sur **Télécharger**.
6. Redémarrez Home Assistant.

### Installation manuelle

1. Téléchargez la dernière version du dépôt.
2. Copiez le dossier `custom_components/vigipool/` dans le répertoire `custom_components/` de votre installation Home Assistant :
   ```
   config/
   └── custom_components/
       └── vigipool/
           ├── __init__.py
           ├── manifest.json
           ├── const.py
           ├── coordinator.py
           ├── discovery.py
           ├── mqtt.py
           ├── entity.py
           ├── sensor.py
           ├── binary_sensor.py
           ├── switch.py
           ├── light.py
           ├── number.py
           ├── select.py
           ├── button.py
           └── translations/
               ├── en.json
               └── fr.json
   ```
3. Redémarrez Home Assistant.

---

## 6. Configuration dans Home Assistant

1. Dans Home Assistant, rendez-vous dans **Paramètres** > **Appareils et services** > **Ajouter une intégration**.
2. Recherchez **CCEI Vigipool**.
3. Choisissez **Recherche automatique** :
   - L'intégration analyse votre réseau et affiche la liste des équipements Vigipool détectés avec leurs adresses IP et leurs modèles.
   - Sélectionnez votre équipement et validez.
4. Si votre réseau comporte des sous-réseaux séparés, choisissez **Saisie manuelle** et indiquez l'adresse IP de votre équipement (port 1883).
5. Vos équipements et l'ensemble de leurs entités sont créés automatiquement !

---

## 7. Architecture technique

L'intégration a été conçue selon les meilleures pratiques Home Assistant Core :

- **Async Python natif (`asyncio`)** : Aucune fonction bloquante n'est exécutée sur la boucle d'événements principale.
- **Client MQTT dédié (`paho-mqtt`)** : Gestionnaire MQTT autonome assurant la connexion directe avec l'appareil sans dépendre d'un broker externe ni de pont réseau.
- **DataUpdateCoordinator (`VigipoolCoordinator`)** : Centralise la réception des trames MQTT, effectue la normalisation et le typage des données, et notifie les entités abonnées de façon réactive (*local push*).
- **Enregistrement dynamique** : Si un nouvel équipement physique (par exemple une sonde Ofix nouvellement allumée) commence à publier sur le bus Vigipool, les entités correspondantes sont automatiquement créées dans Home Assistant sans redémarrage.
- **Gestion des pannes & reconnexion** : En cas de coupure de courant ou de redémarrage de la box Wi-Fi, l'intégration rétablit la connexion dès que l'équipement redevient accessible. Une routine de redécouverte périodique permet également de suivre un changement d'adresse IP locale.

---

## 8. Limitations connues

- **Accès local requis** : L'équipement Vigipool doit être connecté au même réseau local (ou être routable) que votre machine Home Assistant.
- **Session exclusive de l'application mobile** : Lorsque l'application mobile officielle Vigipool effectue une mise à jour de microprogramme (*firmware update*) en Bluetooth ou Wi-Fi direct, les flux MQTT locaux peuvent être brièvement indisponibles. L'intégration se reconnectera automatiquement dès la fin de l'opération.
- **Adresses IP dynamiques très instables** : Il est recommandé de fixer un bail DHCP statique dans votre routeur/box internet pour votre équipement Vigipool, bien que l'intégration intègre un mécanisme de détection automatique des changements d'IP.

---

## 9. Dépannage & FAQ

### Aucun équipement Vigipool n'est détecté lors du scan automatique
1. Vérifiez que votre boîtier Vigipool (Tild, Lynx...) est bien sous tension et connecté à votre réseau Wi-Fi local (voyant Wi-Fi fixe).
2. Vérifiez que votre serveur Home Assistant et le boîtier Vigipool se trouvent sur le même réseau local ou sous-réseau.
3. Si vous utilisez des VLANs séparés, utilisez l'option **Saisie manuelle** en renseignant l'adresse IP directe du boîtier et vérifiez que le port TCP 1883 est autorisé entre les VLANs.

### Les valeurs de température ou pH affichent `Indisponible`
Ceci est normal si la sonde est déconnectée, en erreur matérielle ou si l'appareil vient d'être mis sous tension. Vigipool transmet le code sentinelle `65534` en cas de défaut de sonde, ce qui est traduit proprement par `unavailable` dans Home Assistant pour éviter tout faux déclenchement d'automatisation.

### Activer les logs de débogage
Pour activer les journaux détaillés de l'intégration, ajoutez dans votre `configuration.yaml` :

```yaml
logger:
  default: info
  logs:
    custom_components.vigipool: debug
```

---

## Licence

Ce projet est sous licence MIT. Tous les droits sur les marques et noms de produits CCEI et Vigipool appartiennent à leurs propriétaires respectifs.
