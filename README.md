# Vigicrues pour Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/custom-components/hacs)

Intégration Home Assistant pour sélectionner une station hydrométrique française et afficher ses mesures, ses prévisions et la vigilance de son tronçon.

## Données et continuité de service

- **Hauteur d'eau** en mètres et **débit** en m³/s.
- **Vigilance officielle** : Vert, Jaune, Orange ou Rouge, lorsqu'un tronçon surveillé est associé à la station.
- **Tendance** de la hauteur ; tendance du débit disponible en attribut.
- **Prévisions** disponibles, en attributs des mesures, limitées aux dix prochaines échéances.
- **État des données** : à jour, dégradé / secours ou données anciennes.

À chaque mise à jour, Vigicrues est interrogé en priorité. Pour la hauteur et le débit, si sa réponse échoue, est vide ou contient une dernière mesure de plus de **deux heures**, l'intégration interroge l'API officielle **Hub'Eau Hydrométrie v2**. Elle conserve la réponse ayant la mesure la plus récente. Les identifiants de station et la grandeur sont contrôlés ; les hauteurs Hub'Eau en mm et débits en l/s sont divisés par 1 000.

Les ressources sont indépendantes : une panne des prévisions n'efface pas une hauteur disponible. Si une ressource échoue, sa dernière valeur reste affichée avec `data_stale: true` pour la mesure ou la vigilance concernée. Pour les prévisions, cet indicateur s'appelle `previsions_stale`. Les valeurs retenues sont sauvegardées dans le stockage local de Home Assistant et restaurées après redémarrage. Une valeur restaurée reste marquée ancienne tant que sa récupération n'a pas réussi. Une mesure plus ancienne ne remplace jamais une mesure déjà connue.

L'intégration retente automatiquement la collecte à l'intervalle configuré et revient à Vigicrues dès que sa réponse est utilisable. Les horodatages des mesures conservées ne sont pas avancés artificiellement. Les prévisions dont l'échéance est passée sont supprimées, même pendant une panne.

### Limites du secours

Hub'Eau fournit les observations de hauteur et de débit, **pas les prévisions ni les couleurs de vigilance**. Ces deux dernières ressources restent dépendantes de Vigicrues. Hub'Eau et Vigicrues utilisent des données de la même plateforme hydrométrique nationale PHyC : le secours peut contourner une panne du site ou de son accès, mais ne garantit pas la disponibilité si la collecte en amont est arrêtée.

Sans aucune donnée disponible et sans cache lors de la première installation, Home Assistant diffère le chargement puis le retente automatiquement. La sélection initiale d'un territoire et d'une station nécessite que le catalogue Vigicrues soit accessible. Certaines stations ne publient pas toutes les grandeurs ou ne sont pas rattachées à un tronçon de vigilance ; les capteurs concernés peuvent alors rester indisponibles.

La reprise récupère la dernière mesure et les prévisions encore valables. Elle ne réinjecte pas les points manquants dans l'historique du Recorder de Home Assistant. Les crues historiques ne sont pas exposées par cette version.

## Installation

### Via HACS

1. Dans HACS, ouvrez **Dépôts personnalisés**.
2. Ajoutez `https://github.com/dspe/vigicrues-custom` avec la catégorie **Intégration**.
3. Installez **Vigicrues** puis redémarrez Home Assistant.

### Installation manuelle / mise à jour locale

1. Copiez le dossier `custom_components/vigicrues` dans `config/custom_components/`, en remplaçant les fichiers de l'ancienne version.
2. Redémarrez Home Assistant.
3. Les stations déjà configurées et les identifiants uniques des quatre capteurs existants sont conservés ; un cinquième capteur d'état est ajouté.

Le débit est désormais correctement déclaré en **m³/s**. L'ancienne version déclarait m³/h sans convertir les nombres fournis en m³/s par Vigicrues. L'historique déjà enregistré n'est pas corrigé rétroactivement ; vérifiez les statistiques et les automatisations utilisant le débit après mise à jour. Si une unité d'affichage a été personnalisée dans Home Assistant, vérifiez également cette préférence.

## Configuration

Dans **Paramètres > Appareils et services > Ajouter une intégration**, recherchez **Vigicrues**, sélectionnez un territoire puis une station. La même station ne peut être ajoutée qu'une seule fois.

Dans les options, l'intervalle de mise à jour est exprimé en **secondes** : 900 par défaut (15 minutes), 300 au minimum (5 minutes). Modifier les options recharge l'intégration sans supprimer son cache.

## Capteurs et attributs

Les identifiants ci-dessous sont indicatifs ; utilisez les identifiants réels de votre installation.

| Capteur | Unité / valeurs |
|---------|-----------------|
| `sensor.vigicrues_paris_austerlitz_hauteur` | m |
| `sensor.vigicrues_paris_austerlitz_debit` | m³/s |
| `sensor.vigicrues_paris_austerlitz_vigilance` | Vert, Jaune, Orange, Rouge |
| `sensor.vigicrues_paris_austerlitz_tendance` | hausse, stable, baisse |
| `sensor.vigicrues_paris_austerlitz_statut` | `ok`, `degraded`, `stale` (traduits dans l'interface) |

Le statut est `stale` si toutes les valeurs disponibles sont anciennes ou si leur récupération échoue. Il est `degraded` si une ressource échoue, si une partie des valeurs est ancienne ou si Hub'Eau fournit une mesure. Il est `ok` lorsque les ressources interrogées répondent normalement et que les valeurs disponibles sont récentes.

La tendance compare les cinq dernières observations de la source retenue. Le seuil de stabilité vaut le maximum entre 1 % de la première valeur et 0,01 dans l'unité de la grandeur. Ce calcul décrit une évolution locale, pas une prévision.

| Attribut | Signification |
|----------|---------------|
| `station_id`, `station_name`, `cours_eau` | Identité et métadonnées disponibles |
| `timestamp` | Date réelle de la dernière observation (UTC) |
| `source` | `vigicrues` ou `hubeau` pour les mesures |
| `age_seconds` | Âge de la mesure lors de la dernière actualisation |
| `data_stale` | Échec de récupération ou mesure de plus de deux heures |
| `data_status` | État global de la station |
| `last_attempt` | Date de la dernière tentative de collecte |
| `last_success` | Date de la dernière collecte réussie, par ressource |
| `errors` | Erreurs par ressource lors de la dernière tentative |
| `previsions`, `previsions_stale` | Prévisions futures et état de leur collecte |
| `sources` | Sources des mesures, sur le capteur d'état |

La date `last_success` de la vigilance est une date de récupération, pas une date de publication du bulletin. L'âge des données et le statut sont réévalués à chaque collecte. Les coordonnées sont affichées uniquement si elles sont fournies en latitude / longitude ; les coordonnées Lambert du catalogue ne sont pas présentées comme des degrés.

## Carte Lovelace Vigicrues

La version 1.2.0 inclut une carte personnalisée, sans dépendance à une autre carte ni téléchargement depuis un CDN. Elle affiche, pour chaque station, la hauteur, le débit, la tendance de chacune de ces deux grandeurs et, en option, la vigilance. Les valeurs, les unités d'affichage et les dates proviennent des capteurs Home Assistant : la carte ne contacte pas les API hydrométriques.

### Installation de la carte

1. Mettez à jour `custom_components/vigicrues` (en conservant son sous-dossier `www`) et redémarrez Home Assistant.
2. Dans **Paramètres > Tableaux de bord > Ressources**, ajoutez la ressource suivante, de type **Module JavaScript** :

   ```text
   /vigicrues/vigicrues-card.js?v=1.2.0
   ```

   Activez le mode avancé de votre profil si le menu Ressources n'est pas visible. Pour un tableau de bord géré en YAML, ajoutez cette entrée à la liste `lovelace.resources` existante :

   ```yaml
   lovelace:
     resources:
       - url: /vigicrues/vigicrues-card.js?v=1.2.0
         type: module
   ```

3. Rechargez la page du navigateur, puis ajoutez une carte **Vigicrues** dans le tableau de bord. Si elle n'apparaît pas encore dans le sélecteur, ajoutez une carte manuelle avec le YAML ci-dessous.

Pour utiliser uniquement la carte avec l'intégration 1.1.0, copiez `custom_components/vigicrues/www/vigicrues-card.js` dans `config/www/vigicrues-card.js`, puis utilisez la ressource `/local/vigicrues-card.js?v=1.2.0` de type Module JavaScript. La version 1.2.0 ajoute des attributs stables qui permettent de retrouver les capteurs même après renommage ; avec la version 1.1.0, la détection repose sur leurs attributs et unités existants.

### Afficher toutes les stations configurées

```yaml
type: custom:vigicrues-card
title: Mes cours d’eau
```

Les nouvelles stations ajoutées à l'intégration apparaissent automatiquement. La carte n'ajoute pas de station à l'intégration : les stations disponibles restent celles configurées dans **Appareils et services > Vigicrues**.

### Choisir une ou plusieurs stations

Dans l'éditeur visuel de la carte, décochez **Toutes les stations configurées (automatique)** et cochez les stations souhaitées. Aucun identifiant d'entité n'est à saisir.

La configuration équivalente en YAML utilise les codes de station hydrométrique :

```yaml
type: custom:vigicrues-card
title: Mes stations
stations:
  - H413041010
  - F700000103
show_vigilance: true
show_updated: true
```

Avec une seule entrée dans `stations`, seule cette station est affichée. Les stations explicitement sélectionnées gardent l'ordre de cette liste ; en mode automatique, elles sont triées par nom. `stations: []` correspond à une sélection vide et affiche une invitation à choisir des stations.

| Option | Par défaut | Effet |
|--------|------------|-------|
| `title` | `Vigicrues` | Titre de la carte ; chaîne vide pour le masquer |
| `stations` | non défini | Toutes les stations ; sinon liste de codes hydrométriques |
| `show_vigilance` | `true` | Afficher la vigilance officielle et son éventuelle ancienneté |
| `show_updated` | `true` | Afficher la date et l'âge de chaque mesure |

Un clic sur une hauteur ou un débit ouvre le panneau de détails Home Assistant de l'entité correspondante, avec son historique lorsqu'il est disponible. Un clic sur la vigilance ouvre également ses détails.

### Données anciennes et données absentes

Les badges signalent la source de secours ou une collecte dégradée. Chaque mesure conservée ou de plus de deux heures affiche **Dernière valeur connue**. La carte réévalue l'âge des données toutes les minutes tant qu'elle est affichée, même si aucun nouvel état n'arrive de Home Assistant. Une grandeur absente affiche un tiret et **Mesure indisponible**, jamais un zéro inventé. Une vigilance absente affiche **Vigilance inconnue**. Une station sélectionnée mais introuvable reste visible avec ses mesures indisponibles.

Les flèches décrivent les dernières tendances connues, calculées par l'intégration ; elles ne constituent pas une prévision. Pendant une panne, leur ancienneté est celle de la mesure affichée. Les styles suivent le thème clair ou sombre de Home Assistant et s'adaptent à la largeur de la carte.

Pour les automatisations qui nécessitent une mesure récente, ajoutez une condition sur son attribut `data_stale` plutôt que de vous fier à sa seule disponibilité : une dernière valeur connue reste volontairement affichable pendant une panne.

### Carte native simple

Une carte standard Home Assistant reste possible sans installer la ressource JavaScript. Adaptez ces identifiants à ceux de votre installation :

```yaml
type: entities
title: Station Vigicrues
entities:
  - sensor.vigicrues_paris_austerlitz_statut
  - sensor.vigicrues_paris_austerlitz_hauteur
  - sensor.vigicrues_paris_austerlitz_debit
  - sensor.vigicrues_paris_austerlitz_tendance
```

## Vérification du code

Tests exécutés avec Home Assistant 2026.10.2, Python 3.14 et Node.js 22 pour la carte. Les tests n'appellent aucun service externe. Les exemples de réponses dans `tests/fixtures` sont des extraits des flux officiels observés le 20 octobre 2026 ; les dates utilisées dans les scénarios sont ajustées pendant les tests. Les tests de la carte couvrent la détection des stations, les capteurs renommés, les deux tendances, les données absentes, les données anciennes, le secours et les sélections multiples.

```sh
python3 -m venv venv
venv/bin/pip install -r requirements-test.txt
venv/bin/python -m pytest
venv/bin/ruff check custom_components tests
venv/bin/ruff format --check custom_components tests
node --test tests/frontend/card.test.mjs
```

Les tests couvrent les pannes HTTP / réseau, JSON invalide, réponses partielles HTTP 206, conversions d'unités, conservation partielle, reprise, redémarrage avec cache, dates anciennes, prévisions et configuration des options.

## Sources officielles

- [Documentation API Vigicrues v1.1](https://www.vigicrues.gouv.fr/services/v1.1)
- [Hub'Eau Hydrométrie : fonctionnement, unités et limites](https://hubeau.eaufrance.fr/page/api-hydrometrie)
- [Fiche de l'API Hub'Eau sur data.gouv.fr](https://www.data.gouv.fr/dataservices/hubeau-hydrometrie)

## Licence

Apache 2.0 — voir [LICENSE](LICENSE).
