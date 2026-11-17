# Interfaces Lovelace Vigipool

Ce dossier fournit des **vues Lovelace prêtes à l'emploi**, une par modèle
d'équipement Vigipool. Elles sont construites uniquement avec des **cartes
standard Home Assistant** (aucun custom component requis) et n'affichent que
des informations et commandes **réellement disponibles** sur les topics MQTT
de chaque appareil :

| Fichier | Modèle | Contenu |
|---|---|---|
| `tild_vp.yaml` | Tild VP | Vue synthétique : température, filtration, éclairage, sortie auxiliaire, RSSI |
| `vigiwatt.yaml` | VigiW@tt | Supervision électrique : puissance, tension, courant, fréquence, facteur de puissance |
| `lynx_vp.yaml` | Lynx VP | Distribution de traitement : état d'injection, volumes 24 h et cumulé |
| `tildrc.yaml` | Tildrc | Vue générique : entités créées automatiquement selon les topics réellement publiés par l'appareil |

## Installation — sans toucher à votre tableau de bord actuel

Les vues ci-dessous **ne modifient jamais** votre tableau de bord existant.
Vous avez deux possibilités :

### Option A — Tableau de bord dédié (recommandé)

1. Créez un nouveau tableau de bord : **Aperçus → ⋮ → Nouveau tableau de bord**,
   nommez-le par exemple `Piscine`, puis choisissez **Commencer avec un tableau de bord vide**.
2. Passez-le en mode YAML : **⋮ → Modifier le tableau de bord → ⋮ → Modifier en YAML**.
3. Collez le contenu du fichier de vue souhaité (par exemple `tild_vp.yaml`)
   à l'intérieur de la clé `views:` :

```yaml
views:
  # ▼▼▼ contenu du fichier tild_vp.yaml ▼▼▼
  - title: Tild VP
    path: tild-vp
    cards:
      ...
  # ▲▲▲ fin du contenu ▲▲▲
```

### Option B — Ajout d'une vue à un tableau de bord existant

Ouvrez votre tableau de bord en édition, **⋮ → Modifier en YAML**, puis
ajoutez le bloc `- title: ...` du fichier à la fin de la liste `views:`.

## Adapter les identifiants d'entités

Les identifiants sont prédits à partir de la convention de nommage de
l'intégration (`<modèle slugifié> <nom d'entité>`), par exemple
`sensor.tild_vp_water_temperature`. En cas de doublon, Home Assistant ajoute
un suffixe numérique. Vérifiez vos identifiants exacts dans
**Paramètres → Appareils et services → Entités** (filtrez par marque *CCEI*),
ou renommez l'appareil dans Home Assistant pour un identifiant plus lisible.

> Astuce : remplacez simplement les `entity_id` dans les fichiers par ceux de
> votre installation. Aucune autre modification n'est nécessaire.

## Pourquoi pas de création automatique du tableau de bord ?

Home Assistant ne propose pas de mécanisme standard permettant à une
intégration d'injecter des vues dans le tableau de bord d'un utilisateur sans
risque d'écraser sa configuration. La livraison de vues YAML réutilisables est
le mécanisme officiel recommandé (dashboard en mode *stockage* + coller la
vue), qui garantit :

- zéro écrasement de votre configuration existante ;
- aucune dépendance à `custom:lovelace-*` ;
- des vues versionnées et relisibles dans ce dépôt.
