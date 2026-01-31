# Vigicrues pour Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/custom-components/hacs)

Intégration Home Assistant pour récupérer les données de [Vigicrues](https://www.vigicrues.gouv.fr/), le service d'information sur le risque de crues des principaux cours d'eau en France.

## Fonctionnalités

- **Hauteur d'eau** : Niveau d'eau actuel de la station (en mètres)
- **Débit** : Débit actuel de la rivière (en m³/h)
- **Niveau de vigilance** : Couleur de vigilance crues (Vert, Jaune, Orange, Rouge)
- **Tendance** : Évolution du niveau d'eau (hausse, stable, baisse)
- **Prévisions** : Prévisions de hauteur et débit disponibles en attributs
- **Crues historiques** : Données de référence

## Installation

### Via HACS (recommandé)

1. Ouvrez HACS dans Home Assistant
2. Cliquez sur "Intégrations"
3. Cliquez sur les 3 points en haut à droite et sélectionnez "Dépôts personnalisés"
4. Ajoutez l'URL de ce dépôt avec la catégorie "Intégration"
5. Recherchez "Vigicrues" et installez-le
6. Redémarrez Home Assistant

### Installation manuelle

1. Copiez le dossier `custom_components/vigicrues` dans votre dossier `config/custom_components/`
2. Redémarrez Home Assistant

## Configuration

1. Allez dans **Paramètres** > **Appareils et services**
2. Cliquez sur **Ajouter une intégration**
3. Recherchez "Vigicrues"
4. Sélectionnez votre territoire (ex: Seine-Nord-Est)
5. Choisissez une station hydrométrique dans la liste

## Entités créées

Pour chaque station configurée, les capteurs suivants sont créés :

| Capteur | Description | Unité |
|---------|-------------|-------|
| `sensor.vigicrues_[station]_hauteur` | Hauteur d'eau | m |
| `sensor.vigicrues_[station]_debit` | Débit | m³/h |
| `sensor.vigicrues_[station]_vigilance` | Niveau de vigilance | - |
| `sensor.vigicrues_[station]_tendance` | Tendance | - |

### Attributs disponibles

Chaque capteur inclut des attributs supplémentaires :

- `station_id` : Identifiant de la station
- `station_name` : Nom de la station
- `cours_eau` : Nom du cours d'eau
- `latitude` / `longitude` : Coordonnées de la station
- `timestamp` : Horodatage de la dernière mesure
- `previsions` : Liste des prévisions (pour hauteur et débit)

## Options

Vous pouvez modifier l'intervalle de mise à jour via les options de l'intégration :

- **Intervalle de mise à jour** : Par défaut 15 minutes (minimum 5 minutes)

## Exemple d'automatisation

```yaml
automation:
  - alias: "Alerte crue"
    trigger:
      - platform: state
        entity_id: sensor.vigicrues_paris_austerlitz_vigilance
        to: "Orange"
    action:
      - service: notify.mobile_app
        data:
          title: "Alerte Vigicrues"
          message: "Niveau de vigilance Orange sur la Seine à Paris-Austerlitz"
```

## Carte Lovelace

Exemple de carte pour afficher les données :

```yaml
type: entities
title: Station Vigicrues
entities:
  - entity: sensor.vigicrues_paris_austerlitz_hauteur
    name: Hauteur d'eau
  - entity: sensor.vigicrues_paris_austerlitz_debit
    name: Débit
  - entity: sensor.vigicrues_paris_austerlitz_vigilance
    name: Vigilance
  - entity: sensor.vigicrues_paris_austerlitz_tendance
    name: Tendance
```

## API Vigicrues

Cette intégration utilise l'API publique Vigicrues v1.1 :
- [Documentation API](https://www.vigicrues.gouv.fr/services/v1.1)

## Licence

Ce projet est sous licence Apache 2.0. Voir le fichier [LICENSE](LICENSE) pour plus de détails.

## Contributions

Les contributions sont les bienvenues ! N'hésitez pas à ouvrir une issue ou une pull request.
