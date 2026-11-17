# Letec Finder pour Home Assistant

Intégration personnalisée qui expose les données des API publiques de [letecfinder.be](https://letecfinder.be) dans Home Assistant.

## Fonctionnalités

- Suivi des bus en temps réel avec entités `device_tracker` (affichables sur une carte).
- Prochains passages pour les arrêts sélectionnés.
- Alertes réseau, avec filtrage par régions ou par arrêts.
- Filtre par régions TEC et par lignes.
- Fréquence de rafraîchissement configurable.
- Recherche d'un arrêt par son nom lors de la configuration.

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
3. **Arrêts et alertes** : saisir un nom d'arrêt par ligne, par exemple `Rue Loumaye`. Les résultats de `arrets/search.php` sont proposés à l'étape suivante ; sélectionner les arrêts à suivre.
4. Les options permettent d'activer le capteur d'alertes, de choisir son filtrage (`all`, `regions` ou `stops`) et d'enrichir les entités bus avec les informations de trajet.

## À propos du jeton API

Le champ `api_token` est pré-rempli avec `token1`. Ce n'est **pas** un secret personnel : c'est la valeur publique utilisée par le site letecfinder.be lui-même.

Toutes les API ne se comportent pas de la même manière :

- `arrets/search.php`, `stopdetail.php`, `stop-schedule.php` et `reports.php` répondent sans en-tête d'authentification.
- `bus/position` et `bus/lines` renvoient `HTTP 401` sans l'en-tête `Authorization: Bearer token1`.

Le jeton est donc conservé dans la configuration pour ces deux derniers endpoints. Il peut être laissé à sa valeur par défaut.

## Entités créées

- Un `device_tracker` nommé `Bus <vehicle_id>` par bus actif, avec latitude, longitude, cap, vitesse, ligne et compagnie.
- `Bus suivis` : nombre de bus actuellement vus.
- `Alertes réseau` : nombre d'alertes et zones associées, si activé.
- Un capteur par arrêt, nommé d'après l'arrêt, avec les prochains départs, la destination et le temps d'attente.

## Options

Les options sont accessibles depuis l'intégration et reprennent les mêmes étapes que la configuration initiale. Elles permettent de modifier les régions, les lignes, les arrêts suivis et le comportement des alertes sans supprimer l'intégration.

## Dépannage

- `cannot_connect` : l'API est momentanément indisponible ou injoignable depuis Home Assistant.
- `invalid_auth` : le jeton configuré est refusé par `bus/position` ou `bus/lines`.
- `no_stops_found` : aucun arrêt ne correspond au nom saisi ; essayer un terme plus court.
- `invalid_stop` : un identifiant d'arrêt sélectionné manuellement est introuvable.

## Développement

Le code source se trouve dans `custom_components/letecfinder`.

Les API utilisées sont :

- `bus/position`, `bus`, `bus/lines` pour les véhicules et les lignes.
- `arrets/search.php`, `stopdetail.php`, `stop-schedule.php`, `horaire/schedule` pour les arrêts et horaires.
- `reports.php` pour les alertes réseau.
