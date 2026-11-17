# Letec Finder pour Home Assistant

Intégration personnalisée qui expose les données des API publiques de [letecfinder.be](https://letecfinder.be) dans Home Assistant.

## Fonctionnalités

- Suivi des bus en temps réel avec entités `device_tracker` (affichables sur une carte).
- Prochains passages pour les arrêts sélectionnés.
- Alertes réseau, avec filtrage par régions ou par arrêts.
- Filtre par régions TEC et par lignes.
- Fréquence de rafraîchissement configurable.
- Recherche d'un arrêt par son nom lors de la configuration.
- Conversion des tracés `itineraire.php` en GeoJSON, exposés par un capteur `Itinéraires` (alimenté quand l'enrichissement des bus est activé).

Les régions disponibles sont : `L` (Liège - Verviers), `N` (Namur), `X` (Luxembourg), `H` (Hainaut), `C` (Charleroi) et `B` (Brabant wallon).

## Installation

### Via HACS

1. Dans HACS, ouvrir `Intégrations`, puis le menu `...` et choisir `Ajouter un dépôt personnalisé`.
2. Saisir `https://github.com/slashback100/letec_finder` comme URL, avec le type `Integration`.
3. Installer `Letec Finder`, puis redémarrer Home Assistant.

### Manuellement

Copier le dossier `custom_components/letecfinder` dans le dossier `custom_components` de votre configuration Home Assistant, puis redémarrer.

## Configuration

Aller dans `Paramètres` > `Appareils et services` > `Ajouter une intégration`, puis rechercher `Letec Finder`.

1. **Régions et rafraîchissement** : choisir les régions suivies et l'intervalle en secondes (10 à 900, 30 par défaut).
2. **Lignes à suivre** : sélectionner les lignes voulues. Laisser vide pour suivre toutes les lignes des régions choisies.
3. **Arrêts et alertes** : saisir par ligne un nom d'arrêt (par exemple `Rue Loumaye`) ou directement son identifiant (par exemple `LJEloum1`). Les noms sont résolus via `arrets/search.php`, les identifiants via `stopdetail.php` ; les arrêts trouvés sont proposés à l'étape suivante.
4. Les options permettent d'activer le capteur d'alertes, de choisir son filtrage (`all`, `regions` ou `stops`) et d'enrichir les entités bus avec les informations de trajet.

## À propos du jeton API

Aucun jeton n'est demandé dans l'interface. L'intégration utilise en interne `token1`, la valeur publique employée par le site letecfinder.be.

Toutes les API ne se comportent pas de la même manière :

- `arrets/search.php`, `stopdetail.php`, `stop-schedule.php` et `reports.php` répondent sans en-tête d'authentification.
- `bus/position` et `bus/lines` renvoient `HTTP 401` sans l'en-tête `Authorization: Bearer token1`.

Le jeton est donc appliqué automatiquement à ces deux derniers endpoints.

## Entités créées

- Un `device_tracker` nommé `Bus <ligne> (<vehicle_id>)` par bus actif, avec latitude, longitude, cap, vitesse, ligne et compagnie.
- `Bus suivis` : nombre de bus actuellement vus.
- `Alertes réseau` : nombre d'alertes et zones associées, si activé.
- Un capteur par arrêt, nommé d'après l'arrêt, avec les prochains départs, la destination et le temps d'attente.
- `Itinéraires` : nombre de tracés suivis et attribut `geojson` (FeatureCollection de LineString, vide tant que l'enrichissement des bus est désactivé).

## Affichage des itinéraires

L'API `itineraire.php` renvoie des points `[longitude, latitude]` dans `geometry.paths`. L'intégration les convertit en GeoJSON (avec simplification des tracés), met le résultat en cache une seule fois par ligne et par direction, puis l'expose dans l'attribut `geojson` du capteur `Itinéraires`. Le paramètre `ligne` doit contenir le numéro **et** le nom long de la ligne (comme le fait le site) : avec le numéro seul, un même numéro peut renvoyer le tracé d'une autre région.

La carte `map` native de Home Assistant ne sait pas dessiner de polylignes. Pour afficher les tracés, utiliser la carte custom [map-card](https://github.com/nathan-gs/ha-map-card) (`type: custom:map-card`) avec un exemple dans `examples/lovelace/letecfinder.yaml`.

Le capteur `Itinéraires` n'a pas de latitude/longitude : dans sa configuration `entities`, renseigner `geojson.hide_marker: true` **et** `focus_on_fit: false` (sinon map-card cherche une position pour cadrer la carte), puis définir le centre avec `x` (latitude) et `y` (longitude) au niveau de la carte, ainsi que `zoom`. Attention : dans le code de map-card, `x` est la latitude et `y` la longitude (contrairement à sa documentation) ; mettre ces valeurs à l'envers centre la carte dans l'océan. Les clés `x` et `y` doivent être entourées de guillemets : en YAML, `y` nu est interprété comme `true` par Home Assistant.

## Options

Les options sont accessibles depuis l'intégration et reprennent les mêmes étapes que la configuration initiale. Elles permettent de modifier les régions, les lignes, les arrêts suivis et le comportement des alertes sans supprimer l'intégration.

## Dépannage

- `cannot_connect` : l'API est momentanément indisponible ou injoignable depuis Home Assistant.
- `invalid_auth` : l'authentification interne est refusée par `bus/position` ou `bus/lines`.
- `no_stops_found` : aucun arrêt ne correspond au nom saisi ; essayer un terme plus court.
- `invalid_stop` : un identifiant d'arrêt sélectionné manuellement est introuvable.

## Développement

Le code source se trouve dans `custom_components/letecfinder`.

Les API utilisées sont :

- `bus/position`, `bus`, `bus/lines` pour les véhicules et les lignes.
- `arrets/search.php`, `stopdetail.php`, `stop-schedule.php`, `horaire/schedule` pour les arrêts et horaires.
- `reports.php` pour les alertes réseau.
